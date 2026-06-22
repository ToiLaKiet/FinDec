#!/usr/bin/env python3
"""CLI agent crawl tin tuc theo danh sach ma tu Vietstock.

Agent nay dung lai logic trong ``vietstock_news_crawler.py`` va bo sung:
- universe mac dinh gom 10 ma co phieu;
- schema output chung de co the merge voi cac nguon khac;
- nhan dien keyword cong nghe neu can;
- che do chay lap dinh ky theo gio.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    from news_crawler.vietstock.vietstock_news_crawler import (
        VN_TZ,
        VietstockArticle,
        clean_text,
        crawl_vietstock_news,
        parse_date_arg,
        validate_date_range,
    )
except ImportError:  # Khi import tu project root bang python -m/pytest.
    from news_crawler.vietstock.vietstock_news_crawler import (
        VN_TZ,
        VietstockArticle,
        clean_text,
        crawl_vietstock_news,
        parse_date_arg,
        validate_date_range,
    )


DEFAULT_SYMBOLS = [
    "FPT",
    "VCB",
    "MBB",
    "HPG",
    "VNM",
    "MWG",
    "GAS",
    "VHM",
    "GMD",
    "PNJ",
]

DEFAULT_TECH_KEYWORDS = [
    "cong nghe",
    "vien thong",
    "ict",
    "phan mem",
    "chuyen doi so",
    "so hoa",
    "ha tang so",
    "du lieu",
    "du lieu lon",
    "big data",
    "cloud",
    "dien toan dam may",
    "data center",
    "trung tam du lieu",
    "tri tue nhan tao",
    "artificial intelligence",
    "machine learning",
    "hoc may",
    "ban dan",
    "chip",
    "5g",
    "internet",
    "an ninh mang",
    "cybersecurity",
    "thuong mai dien tu",
    "fintech",
    "smart city",
]

COMMON_FIELDNAMES = [
    "record_id",
    "source",
    "source_article_id",
    "raw_source",
    "crawl_scope",
    "sector",
    "primary_symbol",
    "symbols",
    "matched_keywords",
    "title",
    "summary",
    "content",
    "url",
    "published_at",
    "published_date",
    "usable_from_date",
    "author",
    "tags",
    "image_url",
    "content_length",
    "crawled_at",
    "crawl_error",
]


@dataclass
class AgentRunResult:
    """Ket qua mot lan agent crawl."""

    rows: list[dict[str, Any]]
    symbols: list[str]
    error_count: int
    started_at: str
    finished_at: str


def fold_vietnamese(value: str) -> str:
    """Bo dau tieng Viet va lower de match keyword on dinh."""
    normalized = unicodedata.normalize("NFD", value)
    folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return folded.replace("đ", "d").replace("Đ", "D").lower()


def parse_csv_list(value: str | None) -> list[str]:
    """Tach chuoi CSV don gian thanh list da clean."""
    if not value:
        return []
    return [clean_text(item) for item in value.split(",") if clean_text(item)]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    """Bo trung nhung giu thu tu xuat hien dau tien."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def load_symbols(symbols_arg: str | None, symbols_file: str | None) -> list[str]:
    """Nap danh sach ma tu CLI/file, mac dinh la 10 ma co phieu."""
    symbols: list[str] = []

    if symbols_file:
        path = Path(symbols_file)
        symbols.extend(
            clean_text(line).upper()
            for line in path.read_text(encoding="utf-8").splitlines()
            if clean_text(line) and not clean_text(line).startswith("#")
        )

    symbols.extend(symbol.upper() for symbol in parse_csv_list(symbols_arg))

    if not symbols:
        symbols = DEFAULT_SYMBOLS[:]

    return dedupe_preserve_order(symbols)


def load_keywords(keywords_arg: str | None) -> list[str]:
    """Nap keyword cong nghe, cho phep user bo sung qua CLI."""
    keywords = DEFAULT_TECH_KEYWORDS[:]
    keywords.extend(parse_csv_list(keywords_arg))
    return sorted(set(fold_vietnamese(keyword) for keyword in keywords if keyword))


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Tao regex co bien ky tu de tranh match vao giua tu."""
    escaped = re.escape(fold_vietnamese(keyword))
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.I)


def _join_text(article: VietstockArticle) -> str:
    """Gom cac vung text quan trong cua bai viet."""
    return "\n".join(
        [
            article.title,
            article.summary,
            article.content,
            article.tags,
            article.author,
        ]
    )


def match_keywords(article: VietstockArticle, keywords: list[str]) -> list[str]:
    """Tim keyword cong nghe trong title/summary/content/tags."""
    haystack = fold_vietnamese(_join_text(article))
    matches = [
        keyword
        for keyword in keywords
        if keyword and _keyword_pattern(keyword).search(haystack)
    ]
    return sorted(set(matches))


def detect_symbols(article: VietstockArticle, symbols: list[str]) -> list[str]:
    """Tim ticker trong bai, luon giu primary symbol cua seed Vietstock."""
    haystack = fold_vietnamese(_join_text(article))
    found: set[str] = set()

    if article.symbol:
        found.add(article.symbol.upper())

    for symbol in symbols:
        pattern = _keyword_pattern(symbol)
        if pattern.search(haystack):
            found.add(symbol.upper())

    return sorted(found)


def stable_record_id(article: VietstockArticle) -> str:
    """Tao ID on dinh cho schema chung."""
    source = article.source or "vietstock"
    if article.article_id:
        return f"{source}:{article.article_id}"

    seed = "|".join([source, article.url, article.title, article.published_at])
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{digest}"


def normalize_article(
    article: VietstockArticle,
    *,
    symbols: list[str],
    keywords: list[str],
) -> dict[str, Any]:
    """Chuyen VietstockArticle sang schema chung."""
    matched_keywords = match_keywords(article, keywords)
    detected_symbols = detect_symbols(article, symbols)
    primary_symbol = article.symbol.upper() if article.symbol else ""
    is_technology = bool(matched_keywords)

    scopes: list[str] = []
    if primary_symbol:
        scopes.append("symbol")
    if is_technology:
        scopes.append("technology")

    return {
        "record_id": stable_record_id(article),
        "source": article.source,
        "source_article_id": article.article_id,
        "raw_source": article.raw_source,
        "crawl_scope": "|".join(sorted(set(scopes))),
        "sector": "technology" if is_technology else "",
        "primary_symbol": primary_symbol,
        "symbols": "|".join(detected_symbols),
        "matched_keywords": "|".join(matched_keywords),
        "title": article.title,
        "summary": article.summary,
        "content": article.content,
        "url": article.url,
        "published_at": article.published_at,
        "published_date": article.published_date,
        "usable_from_date": article.usable_from_date,
        "author": article.author,
        "tags": article.tags,
        "image_url": article.image_url,
        "content_length": article.content_length,
        "crawled_at": article.crawled_at,
        "crawl_error": article.crawl_error,
    }


def merge_pipe_values(left: str, right: str) -> str:
    """Merge cac field dang a|b|c."""
    values = [
        clean_text(value)
        for raw in (left, right)
        for value in raw.split("|")
        if clean_text(value)
    ]
    return "|".join(sorted(set(values)))


def merge_duplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe theo URL/record_id va merge symbol/keyword neu trung bai."""
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for row in rows:
        key = str(row.get("url") or row.get("record_id") or "")
        if not key:
            key_seed = "|".join(
                [
                    str(row.get("source", "")),
                    str(row.get("title", "")),
                    str(row.get("published_at", "")),
                ]
            )
            key = hashlib.sha1(key_seed.encode("utf-8")).hexdigest()[:16]

        if key not in by_key:
            by_key[key] = row.copy()
            order.append(key)
            continue

        existing = by_key[key]
        for field in ("crawl_scope", "symbols", "matched_keywords"):
            existing[field] = merge_pipe_values(
                str(existing.get(field, "")),
                str(row.get(field, "")),
            )
        if not existing.get("sector") and row.get("sector"):
            existing["sector"] = row["sector"]
        if not existing.get("primary_symbol") and row.get("primary_symbol"):
            existing["primary_symbol"] = row["primary_symbol"]
        if len(str(row.get("content", ""))) > len(str(existing.get("content", ""))):
            existing["content"] = row.get("content", "")
            existing["content_length"] = row.get("content_length", 0)
        if row.get("crawl_error"):
            existing["crawl_error"] = merge_pipe_values(
                str(existing.get("crawl_error", "")),
                str(row.get("crawl_error", "")),
            )

    return [by_key[key] for key in order]


def read_existing_csv(path: Path) -> list[dict[str, Any]]:
    """Doc CSV cu de append/dedupe."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_existing_jsonl(path: Path) -> list[dict[str, Any]]:
    """Doc JSONL cu de append/dedupe."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], append: bool) -> None:
    """Ghi CSV schema chung."""
    output_rows = merge_duplicate_rows(read_existing_csv(path) + rows) if append else rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COMMON_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]], append: bool) -> None:
    """Ghi JSONL schema chung."""
    output_rows = merge_duplicate_rows(read_existing_jsonl(path) + rows) if append else rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in output_rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_once(args: argparse.Namespace) -> AgentRunResult:
    """Chay mot vong crawl cho tat ca symbols."""
    started_at = datetime.now(VN_TZ).isoformat(timespec="seconds")
    symbols = load_symbols(args.symbols, args.symbols_file)
    keywords = load_keywords(args.keywords)
    rows: list[dict[str, Any]] = []

    print(f"[agent] Start crawl at {started_at}")
    print(f"[agent] Symbols: {', '.join(symbols)}")

    for idx, symbol in enumerate(symbols, start=1):
        print(f"[agent] ({idx}/{len(symbols)}) Crawl {symbol}")
        articles = crawl_vietstock_news(
            symbol,
            max_pages=args.max_pages,
            page_size=args.page_size,
            include_content=args.include_content,
            start_date=args.start_date,
            end_date=args.end_date,
            timeout=args.timeout,
            delay=args.delay,
        )
        normalized = [
            normalize_article(article, symbols=symbols, keywords=keywords)
            for article in articles
        ]

        if args.technology_keyword_only:
            normalized = [row for row in normalized if row["matched_keywords"]]

        rows.extend(normalized)

        if idx < len(symbols):
            time.sleep(max(args.symbol_delay, 0))

    rows = merge_duplicate_rows(rows)
    finished_at = datetime.now(VN_TZ).isoformat(timespec="seconds")
    error_count = sum(1 for row in rows if row.get("crawl_error"))

    if args.output:
        write_csv(Path(args.output), rows, append=args.append)
        print(f"[agent] CSV written -> {args.output}")
    if args.jsonl_output:
        write_jsonl(Path(args.jsonl_output), rows, append=args.append)
        print(f"[agent] JSONL written -> {args.jsonl_output}")

    print(
        f"[agent] Done at {finished_at}. "
        f"Rows: {len(rows)}. Errors: {error_count}."
    )
    return AgentRunResult(
        rows=rows,
        symbols=symbols,
        error_count=error_count,
        started_at=started_at,
        finished_at=finished_at,
    )


def sleep_until_next_run(interval_hours: float, started_monotonic: float) -> None:
    """Sleep phan thoi gian con lai cua interval."""
    interval_seconds = max(interval_hours, 0) * 3600
    elapsed = time.monotonic() - started_monotonic
    wait_seconds = max(interval_seconds - elapsed, 0)
    next_run = datetime.now(VN_TZ) + timedelta(seconds=wait_seconds)
    print(
        f"[agent] Next run at {next_run.isoformat(timespec='seconds')} "
        f"(sleep {wait_seconds:.0f}s)."
    )
    time.sleep(wait_seconds)


def run_agent(args: argparse.Namespace) -> int:
    """Chay agent mot lan hoac lap dinh ky."""
    if args.interval_hours <= 0:
        result = run_once(args)
        return 0 if result.error_count == 0 else 1

    while True:
        started_monotonic = time.monotonic()
        try:
            run_once(args)
            sleep_until_next_run(args.interval_hours, started_monotonic)
        except KeyboardInterrupt:
            print("[agent] Stopped by user.")
            return 130
        except Exception as exc:  # noqa: BLE001
            print(f"[agent] Run failed: {exc}")
            try:
                sleep_until_next_run(args.interval_hours, started_monotonic)
            except KeyboardInterrupt:
                print("[agent] Stopped by user.")
                return 130


def build_parser() -> argparse.ArgumentParser:
    """Tao CLI parser cho news crawl agent."""
    parser = argparse.ArgumentParser(
        description=(
            "CLI agent crawl tin tuc theo danh sach ma tu Vietstock, "
            "chuan hoa schema va co the chay dinh ky theo gio."
        )
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Danh sach ma phan tach bang dau phay. Mac dinh la 10 ma co phieu.",
    )
    parser.add_argument("--symbols-file", default=None, help="File ticker, moi dong mot ma.")
    parser.add_argument("--keywords", default=None, help="Bo sung keyword cong nghe, phan tach bang dau phay.")
    parser.add_argument("--max-pages", type=int, default=3, help="So trang AJAX moi ma.")
    parser.add_argument("--page-size", type=int, default=10, help="So bai moi trang AJAX.")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay giua request detail/page.")
    parser.add_argument("--symbol-delay", type=float, default=3.0, help="Delay giua cac ma.")
    parser.add_argument("--timeout", type=int, default=25, help="Timeout HTTP moi request.")
    parser.add_argument(
        "--include-content",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch full content detail hay chi lay metadata AJAX.",
    )
    parser.add_argument(
        "--start-date",
        type=parse_date_arg,
        default=None,
        help="Ngay bat dau published_date, dinh dang YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date_arg,
        default=None,
        help="Ngay ket thuc published_date, inclusive, dinh dang YYYY-MM-DD.",
    )
    parser.add_argument(
        "--technology-keyword-only",
        action="store_true",
        help="Chi giu bai co keyword cong nghe trong title/summary/content/tags.",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=0.0,
        help=">0 de agent chay lap dinh ky theo so gio. Vi du: 1 = moi gio.",
    )
    parser.add_argument(
        "--output",
        default="data/raw/stock_news.csv",
        help="Duong dan CSV schema chung.",
    )
    parser.add_argument(
        "--jsonl-output",
        default="data/raw/stock_news.jsonl",
        help="Duong dan JSONL schema chung.",
    )
    parser.add_argument(
        "--append",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Append/dedupe voi file cu. Dung --no-append de ghi moi.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_date_range(args.start_date, args.end_date)
    except ValueError as exc:
        parser.error(str(exc))
    return run_agent(args)


if __name__ == "__main__":
    raise SystemExit(main())
