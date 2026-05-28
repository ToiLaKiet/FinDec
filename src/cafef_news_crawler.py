#!/usr/bin/env python3
"""Crawl CafeF stock-market news for downstream RL/news features.

The crawler uses CafeF's public category RSS feed for discovery, then visits
article pages to extract the full text. It is intentionally polite: small
request rate, retry with backoff, and no attempt to bypass access controls.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, time as dtime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


BASE_URL = "https://cafef.vn"
DEFAULT_CATEGORY_URL = "https://cafef.vn/thi-truong-chung-khoan.chn"
DEFAULT_RSS_URL = "https://cafef.vn/thi-truong-chung-khoan.rss"
VN_TZ = timezone(timedelta(hours=7))

# Matches the 5-stock MVP in the project plan. Pass --symbols or
# --symbols-file to use the full VN30 list or a project-specific universe.
DEFAULT_SYMBOLS = ["FPT", "VCB", "HPG", "MWG", "VNM"]

DEFAULT_ALIASES = {
    "FPT": ["FPT"],
    "VCB": ["VCB", "Vietcombank", "Ngan hang Ngoai thuong"],
    "HPG": ["HPG", "Hoa Phat", "Hoa Phat Group"],
    "MWG": ["MWG", "The Gioi Di Dong", "Dien May Xanh", "DMX"],
    "VNM": ["VNM", "Vinamilk"],
    "VIC": ["VIC", "Vingroup"],
    "VHM": ["VHM", "Vinhomes"],
    "VRE": ["VRE", "Vincom Retail"],
    "MSN": ["MSN", "Masan"],
    "TCB": ["TCB", "Techcombank"],
}

FIELDNAMES = [
    "article_id",
    "source",
    "raw_source",
    "category",
    "title",
    "summary",
    "content",
    "url",
    "published_at",
    "published_date",
    "usable_from_date",
    "author",
    "tags",
    "symbols",
    "image_url",
    "content_length",
    "crawled_at",
    "crawl_error",
]


@dataclass
class NewsArticle:
    article_id: str = ""
    source: str = "cafef"
    raw_source: str = ""
    category: str = ""
    title: str = ""
    summary: str = ""
    content: str = ""
    url: str = ""
    published_at: str = ""
    published_date: str = ""
    usable_from_date: str = ""
    author: str = ""
    tags: str = ""
    symbols: str = ""
    image_url: str = ""
    content_length: int = 0
    crawled_at: str = ""
    crawl_error: str = ""

    def to_row(self) -> dict[str, str | int]:
        return asdict(self)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def fold_vietnamese(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return folded.replace("đ", "d").replace("Đ", "D")


def normalize_url(url: str, base_url: str = BASE_URL) -> str:
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def is_cafef_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.netloc.endswith("cafef.vn")
        and parsed.path.endswith(".chn")
        and re.search(r"-\d+\.chn$", parsed.path) is not None
    )


def extract_article_id(url: str) -> str:
    match = re.search(r"-(\d+)\.chn$", urlparse(url).path)
    return match.group(1) if match else ""


def fetch_url(url: str, timeout: int = 25, retries: int = 3) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.8,en;q=0.6",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code not in {408, 429}:
                break
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def parse_datetime(value: str | None) -> datetime | None:
    value = clean_text(value)
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=VN_TZ)
        return parsed.astimezone(VN_TZ)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=VN_TZ)
        return parsed.astimezone(VN_TZ)
    except ValueError:
        pass

    match = re.search(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}).*?(\d{1,2}):(\d{2})", value
    )
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        return datetime(year, month, day, hour, minute, tzinfo=VN_TZ)
    return None


def format_dt(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(VN_TZ).isoformat(timespec="minutes")


def next_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def usable_from_date(dt: datetime | None, cutoff: dtime = dtime(14, 45)) -> str:
    """Approximate when news should become usable for daily stock features.

    CafeF timestamps are Vietnam local time. If an article is published after
    the stock market close, shift it to the next weekday to reduce leakage when
    merging with EOD price data. This does not account for exchange holidays.
    """

    if not dt:
        return ""
    local_dt = dt.astimezone(VN_TZ)
    usable = local_dt.date()
    if usable.weekday() >= 5:
        usable = next_weekday(usable)
    elif local_dt.time() >= cutoff:
        usable = next_weekday(usable + timedelta(days=1))
    return usable.isoformat()


def parse_description_html(description: str) -> tuple[str, str]:
    soup = BeautifulSoup(description or "", "html.parser")
    image = ""
    img = soup.find("img")
    if img and img.get("src"):
        image = normalize_url(img["src"])
    for element in soup.select("img, script, style"):
        element.decompose()
    return clean_text(soup.get_text(" ", strip=True)), image


def parse_rss_items(rss_xml: str) -> list[NewsArticle]:
    root = ET.fromstring(rss_xml)
    channel = root.find("channel")
    if channel is None:
        return []

    articles: list[NewsArticle] = []
    for item in channel.findall("item"):
        title = clean_text(item.findtext("title"))
        link = normalize_url(item.findtext("link") or "")
        if not link or not is_cafef_article_url(link):
            continue

        summary, image_url = parse_description_html(item.findtext("description") or "")
        published_dt = parse_datetime(item.findtext("pubDate"))
        articles.append(
            NewsArticle(
                article_id=extract_article_id(link),
                raw_source="rss",
                category=clean_text(channel.findtext("title")).replace(" | cafef", ""),
                title=title,
                summary=summary,
                url=link,
                published_at=format_dt(published_dt),
                published_date=published_dt.date().isoformat() if published_dt else "",
                usable_from_date=usable_from_date(published_dt),
                image_url=image_url,
            )
        )
    return articles


def parse_category_items(html_doc: str, category_url: str) -> list[NewsArticle]:
    soup = BeautifulSoup(html_doc, "html.parser")
    containers = soup.select(".firstitem, .cate-hl-row2 .big, .tlitem.box-category-item")
    articles: list[NewsArticle] = []
    for container in containers:
        link_element = container.select_one("h1 a[href], h2 a[href], h3 a[href], a.avatar[href]")
        if not link_element:
            continue
        url = normalize_url(link_element.get("href") or "", category_url)
        if not is_cafef_article_url(url):
            continue

        title_element = container.select_one("h1 a[href], h2 a[href], h3 a[href]")
        title = clean_text(
            title_element.get_text(" ", strip=True)
            if title_element
            else link_element.get("title") or ""
        )
        summary = clean_text(
            container.select_one(".sapo").get_text(" ", strip=True)
            if container.select_one(".sapo")
            else ""
        )
        time_element = container.select_one(".time-ago[title], .time[data-time]")
        published_raw = ""
        if time_element:
            published_raw = time_element.get("title") or time_element.get("data-time") or ""
        published_dt = parse_datetime(published_raw)
        image = container.select_one("img[src]")

        articles.append(
            NewsArticle(
                article_id=extract_article_id(url),
                raw_source="category",
                category="Thi truong chung khoan",
                title=title,
                summary=summary,
                url=url,
                published_at=format_dt(published_dt),
                published_date=published_dt.date().isoformat() if published_dt else "",
                usable_from_date=usable_from_date(published_dt),
                image_url=normalize_url(image["src"]) if image and image.get("src") else "",
            )
        )
    return articles


def get_meta(soup: BeautifulSoup, key: str) -> str:
    element = soup.find("meta", attrs={"property": key}) or soup.find(
        "meta", attrs={"name": key}
    )
    return clean_text(element.get("content")) if element and element.get("content") else ""


def first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            value = clean_text(element.get_text(" ", strip=True))
            if value:
                return value
    return ""


def extract_content(soup: BeautifulSoup) -> str:
    content = soup.select_one("#mainContent [data-role='content']")
    content = content or soup.select_one("#mainContent .detail-content")
    content = content or soup.select_one(".detail-content[data-role='content']")
    content = content or soup.select_one(".contentdetail")
    if not content:
        return ""

    noise_selectors = [
        "script",
        "style",
        "iframe",
        "noscript",
        "form",
        "figure",
        "figcaption",
        ".PhotoCMS_Caption",
        ".tindnd",
        ".tinlienquan",
        ".relatednews",
        ".VCSortableInPreviewMode[type='RelatedNewsBox']",
        ".c-banner",
        ".h-show-pc",
        ".h-show-mobile",
        ".adsbygoogle",
    ]
    for element in content.select(",".join(noise_selectors)):
        element.decompose()

    paragraphs: list[str] = []
    seen: set[str] = set()
    for element in content.find_all(["p", "li", "h2", "h3"], recursive=True):
        text = clean_text(element.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        if text.upper() in {"TIN MOI", "TIN LIEN QUAN"}:
            continue
        seen.add(text)
        paragraphs.append(text)

    if paragraphs:
        return "\n".join(paragraphs)
    return clean_text(content.get_text(" ", strip=True))


def parse_article_page(html_doc: str, url: str) -> NewsArticle:
    soup = BeautifulSoup(html_doc, "html.parser")

    title = first_text(soup, ["h1.title[data-role='title']", "h1.title", "h1"])
    title = title or get_meta(soup, "og:title")

    summary = first_text(soup, ["h2.sapo[data-role='sapo']", ".sapo[data-role='sapo']"])
    summary = summary or get_meta(soup, "og:description")

    published_dt = parse_datetime(get_meta(soup, "article:published_time"))
    if not published_dt:
        published_dt = parse_datetime(first_text(soup, [".pdate[data-role='publishdate']", ".pdate"]))

    tags = [
        clean_text(tag.get_text(" ", strip=True)).strip(" ,")
        for tag in soup.select(".tagdetail .row2 a")
    ]
    tags = [tag for tag in tags if tag]

    category = first_text(soup, ["[data-role='cate-name']", ".category-page__name.cat"])
    author = get_meta(soup, "article:author") or first_text(
        soup, ["[data-role='author']", ".dateandcat .author", ".t-contentdetail .author"]
    )
    author = author.replace("|", "").strip()

    content = extract_content(soup)
    return NewsArticle(
        article_id=extract_article_id(url),
        raw_source="detail",
        category=category,
        title=title,
        summary=summary,
        content=content,
        url=url,
        published_at=format_dt(published_dt),
        published_date=published_dt.date().isoformat() if published_dt else "",
        usable_from_date=usable_from_date(published_dt),
        author=author,
        tags="|".join(tags),
        image_url=get_meta(soup, "og:image"),
        content_length=len(content),
    )


def load_symbols(symbols_arg: str | None, symbols_file: str | None) -> list[str]:
    symbols: list[str] = []
    if symbols_file:
        path = Path(symbols_file)
        symbols.extend(
            clean_text(line).upper()
            for line in path.read_text(encoding="utf-8").splitlines()
            if clean_text(line) and not clean_text(line).startswith("#")
        )
    if symbols_arg:
        symbols.extend(
            clean_text(symbol).upper()
            for symbol in symbols_arg.split(",")
            if clean_text(symbol)
        )
    if not symbols:
        symbols = DEFAULT_SYMBOLS[:]
    return sorted(set(symbols))


def extract_symbols(article: NewsArticle, symbols: list[str]) -> str:
    haystack = "\n".join(
        [article.title, article.summary, article.content, article.tags]
    )
    folded_haystack = fold_vietnamese(haystack)
    found: list[str] = []
    for symbol in symbols:
        aliases = DEFAULT_ALIASES.get(symbol, [symbol])
        for alias in aliases:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])"
            folded_pattern = rf"(?<![A-Za-z0-9]){re.escape(fold_vietnamese(alias))}(?![A-Za-z0-9])"
            if re.search(pattern, haystack, re.I) or re.search(
                folded_pattern, folded_haystack, re.I
            ):
                found.append(symbol)
                break
    return "|".join(sorted(set(found)))


def merge_detail(seed: NewsArticle, detail: NewsArticle) -> NewsArticle:
    merged = seed.to_row()
    detail_row = detail.to_row()
    for key, value in detail_row.items():
        if value not in {"", 0}:
            merged[key] = value
    merged["raw_source"] = seed.raw_source
    return NewsArticle(**merged)


def dedupe_articles(articles: Iterable[NewsArticle]) -> list[NewsArticle]:
    seen: set[str] = set()
    result: list[NewsArticle] = []
    for article in articles:
        if article.url in seen:
            continue
        seen.add(article.url)
        result.append(article)
    return result


def read_existing_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, articles: list[NewsArticle], append: bool = False) -> None:
    rows = [article.to_row() for article in articles]
    if append and path.exists():
        existing = read_existing_csv(path)
        seen_urls = {row.get("url", "") for row in existing}
        rows = existing + [row for row in rows if row.get("url", "") not in seen_urls]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, articles: list[NewsArticle], append: bool = False) -> None:
    rows = [article.to_row() for article in articles]
    if append and path.exists():
        existing_rows: list[dict[str, str]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    existing_rows.append(json.loads(line))
        seen_urls = {row.get("url", "") for row in existing_rows}
        rows = existing_rows + [row for row in rows if row.get("url", "") not in seen_urls]

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def crawl(args: argparse.Namespace) -> list[NewsArticle]:
    seeds: list[NewsArticle] = []
    if args.source in {"rss", "both"}:
        seeds.extend(parse_rss_items(fetch_url(args.rss_url, timeout=args.timeout)))
    if args.source in {"category", "both"}:
        seeds.extend(
            parse_category_items(
                fetch_url(args.category_url, timeout=args.timeout), args.category_url
            )
        )

    articles = dedupe_articles(seeds)
    if args.max_articles > 0:
        articles = articles[: args.max_articles]

    now = datetime.now(VN_TZ).isoformat(timespec="seconds")
    result: list[NewsArticle] = []
    for index, seed in enumerate(articles, start=1):
        article = seed
        if args.include_content:
            try:
                detail_html = fetch_url(seed.url, timeout=args.timeout)
                detail = parse_article_page(detail_html, seed.url)
                article = merge_detail(seed, detail)
            except Exception as exc:  # noqa: BLE001 - keep partial rows for analysis.
                article.crawl_error = str(exc)
        article.crawled_at = now
        article.symbols = extract_symbols(article, args.symbols)
        article.content_length = len(article.content)
        if args.require_symbol and not article.symbols:
            continue
        result.append(article)
        if index < len(articles):
            time.sleep(max(args.delay, 0))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl CafeF stock-market news into CSV/JSONL."
    )
    parser.add_argument("--category-url", default=DEFAULT_CATEGORY_URL)
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument(
        "--source",
        choices=["rss", "category", "both"],
        default="rss",
        help="Use RSS for discovery, category HTML, or both.",
    )
    parser.add_argument("--max-articles", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument(
        "--include-content",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch article detail pages for full text.",
    )
    parser.add_argument("--symbols", default=None, help="Comma-separated ticker list.")
    parser.add_argument("--symbols-file", default=None, help="One ticker per line.")
    parser.add_argument(
        "--require-symbol",
        action="store_true",
        help="Keep only articles mentioning at least one configured ticker/alias.",
    )
    parser.add_argument("--output", default="data/raw/cafef_news.csv")
    parser.add_argument("--jsonl-output", default="data/raw/cafef_news.jsonl")
    parser.add_argument("--append", action="store_true", help="Merge with existing output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.symbols = load_symbols(args.symbols, args.symbols_file)

    articles = crawl(args)
    if args.output:
        write_csv(Path(args.output), articles, append=args.append)
    if args.jsonl_output:
        write_jsonl(Path(args.jsonl_output), articles, append=args.append)

    error_count = sum(1 for article in articles if article.crawl_error)
    print(
        f"Crawled {len(articles)} CafeF articles "
        f"({error_count} with errors). Output: {args.output}, {args.jsonl_output}"
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
