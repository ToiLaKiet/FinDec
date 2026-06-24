
#!/usr/bin/env python3
"""Crawl tin tuc su kien co phieu tu VietstockFinance.

Cach hoat dong:
1. Truy cap trang {SYMBOL}/tin-tuc-su-kien.htm de lay CSRF token va Cookie.
2. Goi POST toi endpoint noi bo de lay danh sach tin tuc dang JSON (phan trang).
3. Vao tung trang bai viet tren vietstock.vn de lay noi dung day du.
4. Gan ticker, tinh usable_from_date, ghi ra CSV va JSONL.

Luu y:
- Vietstock yeu cau CSRF token va Cookie hop le cho moi request AJAX.
- Chi crawl voi muc dich nghien cuu, ton trong delay va robots.txt.
- Khong co gang bypass bat ky co che bao mat nao.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, time as dtime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse, urlencode
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Hang so
# ---------------------------------------------------------------------------

VIETSTOCK_BASE = "https://finance.vietstock.vn"
VIETSTOCK_NEWS_DOMAIN = "https://vietstock.vn"

# Endpoint AJAX chinh - lay tu reverse-engineer JS bundle /bundles/company/newsevent/jsx
# Method: POST, Content-Type: application/x-www-form-urlencoded
# Payload bat buoc: code, type, page, pageSize
# type=-1 => lay tat ca tin tuc (tin va su kien); type=0 => tin tuc; type>0 => loai cu the
# KHONG can __RequestVerificationToken trong payload nay.
AJAX_NEWS_ENDPOINT = "https://finance.vietstock.vn/data/getnews"

# Endpoint thu 2 - lay tin theo nhom kenh (bychannel3)
AJAX_NEWS_ENDPOINT_BY_CHANNEL = "https://finance.vietstock.vn/data/getnewsbychannel3"

# NEWS_TYPE cho endpoint /data/getnews
# -1 = tat ca (tin + su kien), 0 = chi tin tuc, >0 = loai cu the
NEWS_TYPE_ALL = -1
NEWS_TYPE_NEWS_ONLY = 0

VN_TZ = timezone(timedelta(hours=7))

# User-Agent gia lap trinh duyet de vuot qua filter co ban.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Ten cac cot output, nhat quan voi schema CafeF de de merge sau nay.
FIELDNAMES = [
    "article_id",
    "source",
    "raw_source",
    "symbol",        # Ma co phieu chinh ma trang nay thuoc ve.
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


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class VietstockArticle:
    """Mot record tin tuc tu VietstockFinance."""

    article_id: str = ""
    source: str = "vietstock"
    raw_source: str = ""        # ajax_list | detail
    symbol: str = ""            # Ma co phieu, vi du FPT.
    title: str = ""
    summary: str = ""
    content: str = ""
    url: str = ""
    published_at: str = ""
    published_date: str = ""
    usable_from_date: str = ""
    author: str = ""
    tags: str = ""
    image_url: str = ""
    content_length: int = 0
    crawled_at: str = ""
    crawl_error: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Utility: text & datetime
# ---------------------------------------------------------------------------

def clean_text(value: str | None) -> str:
    """Lam sach whitespace, tra ve chuoi rong neu None."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def parse_vietstock_datetime(value: str | None) -> datetime | None:
    """Parse nhieu dinh dang ngay gio Vietstock ve datetime VN.

    Vietstock tra ve cac dinh dang:
    - "/Date(1779969199880)/"     <- Unix milliseconds trong JSON AJAX (pho bien nhat)
    - "dd/MM/yyyy HH:mm"          <- hien thi tren trang web
    - "dd/MM/yyyy HH:mm:ss"
    - ISO 8601 "yyyy-MM-ddTHH:mm:ss"
    """
    value = clean_text(value)
    if not value:
        return None

    # /Date(milliseconds)/ - dinh dang JSON .NET cua Vietstock
    ms_match = re.match(r"/Date\((\d+)(?:[+-]\d+)?\)/", value)
    if ms_match:
        ts_ms = int(ms_match.group(1))
        # Unix milliseconds -> datetime UTC -> chuyen sang VN
        return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(VN_TZ)

    # Thu dd/MM/yyyy HH:mm[:ss]
    match = re.match(
        r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?",
        value,
    )
    if match:
        day, month, year, hour, minute = (int(g) for g in match.groups()[:5])
        second = int(match.group(6)) if match.group(6) else 0
        try:
            return datetime(year, month, day, hour, minute, second, tzinfo=VN_TZ)
        except ValueError:
            pass

    # Thu ISO 8601
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt.astimezone(VN_TZ)
    except ValueError:
        pass

    return None


def format_dt(dt: datetime | None) -> str:
    """Chuyen datetime -> ISO string phut, hoac chuoi rong."""
    if not dt:
        return ""
    return dt.astimezone(VN_TZ).isoformat(timespec="minutes")


def next_weekday(value: date) -> date:
    """Dich len ngay lam viec tiep theo neu la cuoi tuan."""
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def usable_from_date(dt: datetime | None, cutoff: dtime = dtime(14, 45)) -> str:
    """Tinh ngay an toan dung tin de tranh leakage khi join gia EOD."""
    if not dt:
        return ""
    local = dt.astimezone(VN_TZ)
    day = local.date()
    if day.weekday() >= 5:
        day = next_weekday(day)
    elif local.time() >= cutoff:
        day = next_weekday(day + timedelta(days=1))
    return day.isoformat()


def parse_date_arg(value: str | None) -> date | None:
    """Parse CLI date YYYY-MM-DD."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Ngay khong hop le: {value!r}. Dung dinh dang YYYY-MM-DD."
        ) from exc


def validate_date_range(start_date: date | None, end_date: date | None) -> None:
    """Bao loi neu khoang ngay bi nguoc."""
    if start_date and end_date and end_date < start_date:
        raise ValueError("--end-date phai lon hon hoac bang --start-date")


def article_published_date(article: VietstockArticle) -> date | None:
    """Lay published_date cua article ve date object."""
    if not article.published_date:
        return None
    try:
        return date.fromisoformat(article.published_date)
    except ValueError:
        return None


def article_usable_from_date(article: VietstockArticle) -> date | None:
    """Lay usable_from_date cua article ve date object."""
    if not article.usable_from_date:
        return None
    try:
        return date.fromisoformat(article.usable_from_date)
    except ValueError:
        return None


def in_date_range(
    article: VietstockArticle,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    """Kiem tra bai viet co nam trong khoang usable_from_date hay khong."""
    if not start_date and not end_date:
        return True

    usable = article_usable_from_date(article)
    if not usable:
        return False
    if start_date and usable < start_date:
        return False
    if end_date and usable > end_date:
        return False
    return True


def page_date_bounds(
    articles: list[VietstockArticle],
) -> tuple[date | None, date | None]:
    """Tra ve (newest_usable, oldest_usable) tu danh sach bai tren mot trang."""
    dates = [
        usable
        for article in articles
        if (usable := article_usable_from_date(article)) is not None
    ]
    if not dates:
        return None, None
    return max(dates), min(dates)


def page_is_before_start(
    articles: list[VietstockArticle],
    start_date: date | None,
) -> bool:
    """True neu toan bo trang co usable_from_date cu hon start_date."""
    if not start_date or not articles:
        return False
    dates = [article_usable_from_date(article) for article in articles]
    return all(usable is not None and usable < start_date for usable in dates)


def page_is_after_end(
    articles: list[VietstockArticle],
    end_date: date | None,
) -> bool:
    """True neu toan bo trang co usable_from_date moi hon end_date."""
    if not end_date or not articles:
        return False
    _, oldest = page_date_bounds(articles)
    return oldest is not None and oldest > end_date


def normalize_url(url: str, base: str = VIETSTOCK_BASE) -> str:
    """Bien URL tuong doi thanh tuyet doi va bo query/fragment."""
    absolute = urljoin(base, url)
    parsed = urlparse(absolute)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

def _build_headers(referer: str = "", extra: dict[str, str] | None = None) -> dict[str, str]:
    """Tra ve headers co ban kem gia lap trinh duyet."""
    h: dict[str, str] = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.8,en;q=0.6",
    }
    if referer:
        h["Referer"] = referer
    if extra:
        h.update(extra)
    return h


def fetch_html(
    url: str,
    *,
    timeout: int = 25,
    retries: int = 3,
    referer: str = "",
    cookies: dict[str, str] | None = None,
) -> str:
    """GET HTML voi retry tuyen tinh, tra ve noi dung decode UTF-8.

    Args:
        url: URL can tai.
        timeout: Thoi gian cho moi request (giay).
        retries: So lan thu lai khi loi mang/500+.
        referer: Gia tri header Referer.
        cookies: Dict cookie them vao request.

    Returns:
        Noi dung HTML da decode.

    Raises:
        RuntimeError: Neu tat ca retry deu that bai.
    """
    headers = _build_headers(referer=referer)
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers["Cookie"] = cookie_str

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code not in {408, 429}:
                break  # Loi 4xx kho tu phuc hoi, dung retry.
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch_html failed for {url}: {last_error}")


def fetch_ajax_post(
    url: str,
    payload: dict[str, str],
    *,
    timeout: int = 25,
    retries: int = 3,
    referer: str = "",
    cookies: dict[str, str] | None = None,
) -> str:
    """POST form-urlencoded va tra ve body raw (thuong la JSON).

    Vietstock dung POST voi Content-Type application/x-www-form-urlencoded
    cho cac endpoint AJAX tra ve JSON. Ham nay mo phong dung request nay.

    Args:
        url: Endpoint AJAX.
        payload: Dict du lieu form se duoc encode.
        timeout: Timeout (giay).
        retries: So lan retry.
        referer: Header Referer - quan trong de Vietstock chap nhan.
        cookies: Cookie session (can thiet neu endpoint yeu cau dang nhap).

    Returns:
        Body phan hoi dang str (thuong la JSON).

    Raises:
        RuntimeError: Neu tat ca retry that bai.
    """
    headers = _build_headers(
        referer=referer,
        extra={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
    )
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers["Cookie"] = cookie_str

    body = urlencode(payload).encode("utf-8")

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(url, data=body, headers=headers, method="POST")
            with urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code not in {408, 429}:
                break
        except (URLError, TimeoutError) as exc:
            last_error = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch_ajax_post failed for {url}: {last_error}")


# ---------------------------------------------------------------------------
# Token & cookie extraction
# ---------------------------------------------------------------------------

def extract_csrf_token(html: str) -> str:
    """Lay __RequestVerificationToken tu hidden input trong HTML.

    Vietstock nhung CSRF token vao mot form an trong trang chu,
    token nay phai duoc gui kem trong moi AJAX POST request.

    Args:
        html: Noi dung HTML cua trang tin-tuc-su-kien.

    Returns:
        Gia tri CSRF token, hoac chuoi rong neu khong tim thay.
    """
    soup = BeautifulSoup(html, "html.parser")
    # Form chinh co id __CHART_AjaxAntiForgeryForm
    form = soup.find("form", id="__CHART_AjaxAntiForgeryForm")
    if form:
        token_input = form.find("input", attrs={"name": "__RequestVerificationToken"})
        if token_input and token_input.get("value"):
            return token_input["value"]
    # Fallback: tim bat ky input co name = __RequestVerificationToken
    token_input = soup.find("input", attrs={"name": "__RequestVerificationToken"})
    if token_input and token_input.get("value"):
        return token_input["value"]
    return ""


def fetch_token_and_cookies(
    symbol: str,
    timeout: int = 25,
) -> tuple[str, dict[str, str]]:
    """Tai trang tin-tuc-su-kien, lay CSRF token va cookie session.

    Day la buoc khoi tao bat buoc truoc khi goi bat ky AJAX endpoint nao
    cua Vietstock, vi ho kiem tra ca token lan cookie.

    Args:
        symbol: Ma co phieu, vi du "FPT".
        timeout: Timeout HTTP (giay).

    Returns:
        Tuple (csrf_token, cookies_dict).
        csrf_token la chuoi rong neu khong tim thay (AJAX co the van chay
        doi voi endpoint khong yeu cau xac thuc).
        cookies_dict chua cac cookie can thiet cho session.
    """
    page_url = f"{VIETSTOCK_BASE}/{symbol}/tin-tuc-su-kien.htm"
    headers = _build_headers()
    cookies: dict[str, str] = {}

    req = Request(page_url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            # Thu thap Set-Cookie de duy tri session.
            raw_cookies = resp.getheader("Set-Cookie") or ""
            # Parse thu cong vi urllib khong co cookie jar day du.
            for part in raw_cookies.split(","):
                kv = part.strip().split(";")[0]
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    cookies[k.strip()] = v.strip()
            charset = resp.headers.get_content_charset() or "utf-8"
            html = resp.read().decode(charset, errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Cannot fetch Vietstock page for {symbol}: {exc}") from exc

    token = extract_csrf_token(html)
    return token, cookies


# ---------------------------------------------------------------------------
# Parse danh sach tin tu AJAX JSON
# ---------------------------------------------------------------------------

def _safe_str(val: Any) -> str:
    """Chuyen gia tri bat ky thanh chuoi sach."""
    if val is None:
        return ""
    return clean_text(str(val))


def parse_ajax_news_response(raw_json: str, symbol: str) -> list[VietstockArticle]:
    """Parse JSON tra ve tu /data/getnews thanh danh sach VietstockArticle.

    Schema JSON Vietstock (nguon: reverse-engineer JS bundle + kiem tra thuc te):
    [
        {
            "StockCode": "FPT",
            "ChannelID": 161,
            "Head": "<sapo ngan>",
            "ArticleID": 1448114,
            "Title": "<tieu de>",
            "PublishTime": "/Date(1779969199880)/",   <- Unix ms
            "Content": "",                              <- thuong rong, lay tu trang chi tiet
            "URL": "/2026/05/slug-bai-viet-1448114.htm",  <- relative URL
            "TotalRow": 224,                           <- tong so bai (de phan trang)
            "Source": "FILI",                          <- nguon phat hanh
            "Icon": ""
        },
        ...
    ]

    Args:
        raw_json: Chuoi JSON tra ve tu server.
        symbol: Ma co phieu de dien vao field symbol.

    Returns:
        Danh sach VietstockArticle seed (chua co full content).
    """
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []

    # Endpoint /data/getnews luon tra ve mang JSON truc tiep
    items: list[dict] = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        for key in ("data", "Data", "result", "Result", "news", "News"):
            if key in parsed and isinstance(parsed[key], list):
                items = parsed[key]
                break

    articles: list[VietstockArticle] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        # --- Cac truong chinh theo schema da kiem tra thuc te ---
        # ArticleID: so nguyen, dung lam ID bai viet
        article_id = _safe_str(item.get("ArticleID") or item.get("articleID") or "")

        # Title: tieu de bai viet
        title = _safe_str(item.get("Title") or item.get("title") or "")

        # Head: sapo/tom tat ngan
        summary = _safe_str(item.get("Head") or item.get("head") or
                            item.get("Summary") or item.get("summary") or "")
        if "<" in summary:
            summary = clean_text(BeautifulSoup(summary, "html.parser").get_text(" "))

        # PublishTime: dinh dang /Date(ms)/
        date_raw = _safe_str(item.get("PublishTime") or item.get("publishTime") or
                             item.get("PublishDate") or item.get("publishDate") or "")
        published_dt = parse_vietstock_datetime(date_raw)

        # URL: relative URL, can them domain vietstock.vn
        url = _safe_str(item.get("URL") or item.get("Url") or item.get("url") or "")
        if url and not url.startswith("http"):
            url = urljoin(VIETSTOCK_NEWS_DOMAIN, url)

        # Source: ten nguon (FILI, Vietstock, ...)
        source_name = _safe_str(item.get("Source") or item.get("source") or "")

        # Content: thuong rong trong listing, se lay day du tu trang chi tiet
        content = _safe_str(item.get("Content") or item.get("content") or "")
        if "<" in content:
            content = clean_text(BeautifulSoup(content, "html.parser").get_text(" "))

        if not title and not url:
            continue  # Bo qua item rong

        articles.append(
            VietstockArticle(
                article_id=article_id,
                raw_source="ajax_list",
                symbol=symbol.upper(),
                title=title,
                summary=summary,
                content=content,
                url=url,
                published_at=format_dt(published_dt),
                published_date=published_dt.date().isoformat() if published_dt else "",
                usable_from_date=usable_from_date(published_dt),
                author=source_name,  # Source = ten to bao / nguon
            )
        )
    return articles


def _extract_total_row(raw_json: str) -> int | None:
    """Lay TotalRow tu JSON listing Vietstock."""
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and parsed:
        total = parsed[0].get("TotalRow")
        if isinstance(total, int) and total > 0:
            return total
    return None


def fetch_news_page(
    symbol: str,
    page: int,
    *,
    page_size: int = 10,
    news_type: int = NEWS_TYPE_ALL,
    timeout: int = 25,
    referer: str = "",
    cookies: dict[str, str] | None = None,
) -> tuple[list[VietstockArticle], int | None]:
    """Lay mot trang tin AJAX, tra ve (articles, total_row)."""
    payload = {
        "code": symbol.upper(),
        "type": str(news_type),
        "page": str(page),
        "pageSize": str(page_size),
    }
    raw = fetch_ajax_post(
        AJAX_NEWS_ENDPOINT,
        payload,
        timeout=timeout,
        referer=referer or f"{VIETSTOCK_BASE}/{symbol}/tin-tuc-su-kien.htm",
        cookies=cookies,
    )
    return parse_ajax_news_response(raw, symbol), _extract_total_row(raw)


def find_news_start_page(
    symbol: str,
    *,
    end_date: date,
    max_page: int,
    page_size: int = 10,
    news_type: int = NEWS_TYPE_ALL,
    timeout: int = 25,
    delay: float = 0.0,
    cookies: dict[str, str] | None = None,
) -> int:
    """Binary search trang dau tien co oldest usable_from_date <= end_date.

    Listing Vietstock sap xep moi -> cu. Khi end_date nam trong qua khu, bo qua
    cac trang dau neu toan bo bai tren trang co usable_from_date > end_date.
    """
    if max_page < 1:
        return 1

    referer = f"{VIETSTOCK_BASE}/{symbol}/tin-tuc-su-kien.htm"
    low, high, best = 1, max_page, 1

    while low <= high:
        mid = (low + high) // 2
        try:
            page_articles, _ = fetch_news_page(
                symbol,
                mid,
                page_size=page_size,
                news_type=news_type,
                timeout=timeout,
                referer=referer,
                cookies=cookies,
            )
        except RuntimeError:
            high = mid - 1
            continue

        if not page_articles:
            high = mid - 1
            continue

        _, oldest = page_date_bounds(page_articles)
        if oldest is None:
            return 1
        if oldest > end_date:
            low = mid + 1
        else:
            best = mid
            high = mid - 1

        if delay > 0 and low <= high:
            time.sleep(delay)

    return best


# ---------------------------------------------------------------------------
# Lay danh sach tin tuc (phan trang)
# ---------------------------------------------------------------------------

def fetch_news_list(
    symbol: str,
    *,
    max_pages: int = 5,
    page_size: int = 10,
    news_type: int = NEWS_TYPE_ALL,   # -1 = tat ca (tin + su kien)
    start_date: date | None = None,
    end_date: date | None = None,
    auto_pages: bool = False,
    timeout: int = 25,
    delay: float = 1.0,
    cookies: dict[str, str] | None = None,
) -> list[VietstockArticle]:
    """Lay danh sach tin tuc Vietstock qua AJAX phan trang.

    Ham nay POST toi /data/getnews cua Vietstock de lay danh sach tin JSON
    phan trang. Payload chinh xac lay tu reverse-engineer JS bundle:
        {code, type, page, pageSize}
    Khong can CSRF token trong payload cua endpoint nay.

    Khi co start_date/end_date, loc theo usable_from_date (ngay an toan join
    gia EOD). Neu co end_date, binary search de nhay toi trang gan end_date.

    Args:
        symbol: Ma co phieu, vi du "FPT".
        max_pages: So trang AJAX toi da khi auto_pages=False.
        page_size: So bai moi trang (mac dinh 10 theo JS Vietstock).
        news_type: Loai tin: -1=tat ca, 0=chi tin tuc, so khac=loai cu the.
        start_date: Chi giu bai co usable_from_date >= start_date.
        end_date: Chi giu bai co usable_from_date <= end_date.
        auto_pages: Tu tinh max trang tu TotalRow.
        timeout: Timeout HTTP (giay).
        delay: Delay giua cac trang (giay).
        cookies: Cookie session (lay tu fetch_token_and_cookies).

    Returns:
        Danh sach VietstockArticle seed tu danh sach AJAX (chua full content).
    """
    referer = f"{VIETSTOCK_BASE}/{symbol}/tin-tuc-su-kien.htm"
    all_articles: list[VietstockArticle] = []
    date_filter = start_date is not None or end_date is not None
    last_page = 0

    try:
        first_articles, total_rows = fetch_news_page(
            symbol,
            1,
            page_size=page_size,
            news_type=news_type,
            timeout=timeout,
            referer=referer,
            cookies=cookies,
        )
    except RuntimeError as exc:
        print(f"  [warn] Page 1 fetch failed: {exc}")
        return []

    if not first_articles:
        return []

    if total_rows is None:
        total_rows = len(first_articles)

    if auto_pages and total_rows:
        max_page = max(1, (total_rows + page_size - 1) // page_size)
    else:
        max_page = max(1, max_pages)

    start_page = 1
    if end_date:
        start_page = find_news_start_page(
            symbol,
            end_date=end_date,
            max_page=max_page,
            page_size=page_size,
            news_type=news_type,
            timeout=timeout,
            delay=min(delay, 0.5) if delay > 0 else 0.0,
            cookies=cookies,
        )
        print(
            f"  [{symbol}] Date range: start_page={start_page}/{max_page} "
            f"for end_date={end_date.isoformat()}"
        )

    for page in range(start_page, max_page + 1):
        last_page = page
        if page == 1:
            page_articles = first_articles
        else:
            try:
                page_articles, page_total = fetch_news_page(
                    symbol,
                    page,
                    page_size=page_size,
                    news_type=news_type,
                    timeout=timeout,
                    referer=referer,
                    cookies=cookies,
                )
            except RuntimeError as exc:
                print(f"  [warn] Page {page} fetch failed: {exc}")
                break
            if page_total is not None:
                total_rows = page_total

        if not page_articles:
            break
        if page_is_after_end(page_articles, end_date):
            continue
        if page_is_before_start(page_articles, start_date):
            break

        all_articles.extend(
            article
            for article in page_articles
            if in_date_range(article, start_date, end_date)
        )

        if not date_filter:
            pages_fetched = page - start_page + 1
            if len(page_articles) < page_size:
                break
            if total_rows is not None and pages_fetched * page_size >= min(
                total_rows, max_pages * page_size
            ):
                break

        if page < max_page:
            time.sleep(max(delay, 0))

    if date_filter:
        print(
            f"  [{symbol}] Listing crawl: pages {start_page}-{last_page}, "
            f"{len(all_articles)} articles in usable_from_date range."
        )

    return all_articles


# ---------------------------------------------------------------------------
# Parse trang bai viet chi tiet tren vietstock.vn
# ---------------------------------------------------------------------------

def _get_meta(soup: BeautifulSoup, key: str) -> str:
    """Lay noi dung meta tag theo property hoac name."""
    el = soup.find("meta", attrs={"property": key}) or soup.find(
        "meta", attrs={"name": key}
    )
    return clean_text(el.get("content")) if el and el.get("content") else ""


def _first_text(soup: BeautifulSoup, *selectors: str) -> str:
    """Tra ve text dau tien tim duoc trong cac CSS selector."""
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            val = clean_text(el.get_text(" ", strip=True))
            if val:
                return val
    return ""


def parse_vietstock_article_page(html: str, url: str) -> VietstockArticle:
    """Parse trang chi tiet bai viet tren vietstock.vn.

    Trang chi tiet vietstock.vn co layout khac finance.vietstock.vn.
    Ham nay trich cac truong chinh tu HTML da tai.

    Args:
        html: HTML cua trang bai viet chi tiet.
        url: URL cua trang de dien vao record.

    Returns:
        VietstockArticle voi cac truong da parse (chua symbol).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = _first_text(soup, "h1.article-title", "h1.title", "h1")
    title = title or _get_meta(soup, "og:title")

    # Summary / sapo
    summary = _first_text(
        soup,
        ".article-sapo", ".article-summary",
        ".article-description", ".sapo", "h2.sapo",
    )
    summary = summary or _get_meta(soup, "og:description")

    # Thoi gian xuat ban
    published_dt = parse_vietstock_datetime(
        _get_meta(soup, "article:published_time")
    )
    if not published_dt:
        # Thu lay tu cac selector hien thi tren trang
        date_str = _first_text(
            soup,
            ".article-time", ".article-date",
            ".date-time", ".post-date", "time",
            ".pdate",
        )
        published_dt = parse_vietstock_datetime(date_str)
        if not published_dt:
            # Thu lay tu attribute datetime cua the <time>
            time_el = soup.find("time")
            if time_el and time_el.get("datetime"):
                published_dt = parse_vietstock_datetime(time_el["datetime"])

    # Tac gia
    author = _get_meta(soup, "article:author")
    if not author:
        author = _first_text(soup, ".article-author", ".author", ".byline")

    # Noi dung bai
    content = _extract_vietstock_content(soup)

    # Tag / tu khoa
    tags_els = soup.select(".article-tag a, .tags a, .tag a")
    tags = [clean_text(t.get_text(" ", strip=True)) for t in tags_els if t.get_text(strip=True)]
    tags = [t for t in tags if t]

    # Anh dai dien
    image_url = _get_meta(soup, "og:image")

    # ID bai viet tu URL
    article_id = ""
    id_match = re.search(r"/(\d+)[^/]*\.htm", url)
    if id_match:
        article_id = id_match.group(1)

    return VietstockArticle(
        article_id=article_id,
        raw_source="detail",
        title=title,
        summary=summary,
        content=content,
        url=url,
        published_at=format_dt(published_dt),
        published_date=published_dt.date().isoformat() if published_dt else "",
        usable_from_date=usable_from_date(published_dt),
        author=author,
        tags="|".join(tags),
        image_url=image_url,
        content_length=len(content),
    )


def _extract_vietstock_content(soup: BeautifulSoup) -> str:
    """Trich noi dung bai viet Vietstock, loai noise script/quang cao.

    Vietstock su dung mot so class container pho bien cho noi dung bai:
    - .article-content
    - .content-detail
    - .article-body
    - #article-body
    Neu khong tim thay, fallback sang lay toan bo p/li/h2/h3.
    """
    # Thu cac selector container noi dung theo thu tu uu tien
    content_el = (
        soup.select_one(".article-content")
        or soup.select_one(".content-detail")
        or soup.select_one(".article-body")
        or soup.select_one("#article-body")
        or soup.select_one(".cms-body")
        or soup.select_one("[id*='content']")
    )

    if not content_el:
        return ""

    # Xoa cac phan tu noise
    for noise in content_el.select(
        "script, style, iframe, noscript, form, "
        "figure, figcaption, .adsbygoogle, "
        "[class*='ads'], [class*='banner'], "
        "[class*='related'], [class*='recommend']"
    ):
        noise.decompose()

    paragraphs: list[str] = []
    seen: set[str] = set()
    for el in content_el.find_all(["p", "li", "h2", "h3"], recursive=True):
        text = clean_text(el.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)

    if paragraphs:
        return "\n".join(paragraphs)
    # Fallback lay toan bo text
    return clean_text(content_el.get_text(" ", strip=True))


# ---------------------------------------------------------------------------
# Merge seed + detail
# ---------------------------------------------------------------------------

def merge_detail(seed: VietstockArticle, detail: VietstockArticle) -> VietstockArticle:
    """Gop du lieu tu trang chi tiet vao seed, giu gia tri seed khi detail trong.

    Logic: truong nao detail co gia tri thi ghi de seed; nguoc lai giu seed.
    raw_source luon giu lai gia tri cua seed (diem xuat phat).
    """
    merged = seed.to_row()
    for key, val in detail.to_row().items():
        if val not in ("", 0):
            merged[key] = val
    merged["raw_source"] = seed.raw_source
    merged["symbol"] = seed.symbol  # symbol phai lay tu seed (co ticker cu the)
    return VietstockArticle(**merged)


# ---------------------------------------------------------------------------
# Deduplicate
# ---------------------------------------------------------------------------

def dedupe(articles: list[VietstockArticle]) -> list[VietstockArticle]:
    """Bo trung theo URL, giu ban ghi xuat hien dau."""
    seen: set[str] = set()
    result: list[VietstockArticle] = []
    for a in articles:
        key = a.url or a.article_id
        if key and key not in seen:
            seen.add(key)
            result.append(a)
    return result


# ---------------------------------------------------------------------------
# Ham crawl chinh (tai su dung duoc)
# ---------------------------------------------------------------------------

def crawl_vietstock_news(
    symbol: str,
    *,
    max_pages: int = 5,
    page_size: int = 10,
    include_content: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
    auto_pages: bool = False,
    timeout: int = 25,
    delay: float = 1.5,
) -> list[VietstockArticle]:
    """Crawl danh sach tin tuc va su kien cua mot ma co phieu tu Vietstock.

    Day la ham chinh de tai su dung. Quy trinh:
    1. Lay CSRF token va cookie tu trang listing.
    2. Goi AJAX phan trang de lay seed list (title, url, date...).
    3. Neu include_content=True, vao tung URL bai viet de lay full text.
    4. Merge seed + detail, tra ve danh sach day du.

    Args:
        symbol: Ma co phieu, vi du "FPT", "VCB".
        max_pages: So trang AJAX toi da khi auto_pages=False.
        page_size: So bai moi trang AJAX (nen de 10, Vietstock co the cap).
        include_content: Co fetch full content trang bai viet khong.
        start_date: Chi giu bai co usable_from_date >= start_date.
        end_date: Chi giu bai co usable_from_date <= end_date.
        auto_pages: Tu tinh max trang tu TotalRow khi crawl theo ngay.
        timeout: Timeout HTTP (giay).
        delay: Delay giua cac request (giay), de tranh bi chan IP.

    Returns:
        Danh sach VietstockArticle da day du thong tin.

    Example:
        # Lay tin FPT trong khoang usable_from_date
        articles = crawl_vietstock_news(
            "FPT",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
            auto_pages=True,
            delay=1.5,
        )
        for a in articles:
            print(a.title, a.usable_from_date)
    """
    validate_date_range(start_date, end_date)
    now = datetime.now(VN_TZ).isoformat(timespec="seconds")

    # Buoc 1: Lay token va cookie
    try:
        csrf_token, cookies = fetch_token_and_cookies(symbol, timeout=timeout)
    except RuntimeError as exc:
        # Neu khong lay duoc token, van thu khong token (co the van chay)
        print(f"[warn] Could not get CSRF token for {symbol}: {exc}")
        csrf_token, cookies = "", {}

    # Buoc 2: Lay danh sach tin AJAX (endpoint /data/getnews khong can CSRF token)
    seeds = fetch_news_list(
        symbol,
        max_pages=max_pages,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        auto_pages=auto_pages,
        timeout=timeout,
        delay=delay,
        cookies=cookies,
    )
    seeds = dedupe(seeds)
    print(f"[{symbol}] Found {len(seeds)} articles from AJAX listing.")

    # Buoc 3 (tuy chon): Fetch trang chi tiet lay full content
    result: list[VietstockArticle] = []
    for idx, seed in enumerate(seeds, start=1):
        article = seed
        if include_content and seed.url:
            try:
                detail_html = fetch_html(
                    seed.url,
                    timeout=timeout,
                    referer=f"{VIETSTOCK_BASE}/{symbol}/tin-tuc-su-kien.htm",
                )
                detail = parse_vietstock_article_page(detail_html, seed.url)
                article = merge_detail(seed, detail)
            except Exception as exc:  # noqa: BLE001
                article.crawl_error = str(exc)
                print(f"  [error] Cannot fetch detail for: {seed.url} -> {exc}")

        article.crawled_at = now
        article.content_length = len(article.content)
        if not in_date_range(article, start_date, end_date):
            continue
        result.append(article)

        if include_content and idx < len(seeds):
            time.sleep(max(delay, 0))

    print(f"[{symbol}] Crawl done. Total: {len(result)} articles.")
    return result


# ---------------------------------------------------------------------------
# I/O: ghi CSV va JSONL
# ---------------------------------------------------------------------------

def write_csv(path: Path, articles: list[VietstockArticle], append: bool = False) -> None:
    """Ghi danh sach bai viet ra CSV co BOM (mo duoc bang Excel)."""
    rows = [a.to_row() for a in articles]
    if append and path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
        seen_urls = {r.get("url", "") for r in existing}
        rows = existing + [r for r in rows if r.get("url", "") not in seen_urls]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, articles: list[VietstockArticle], append: bool = False) -> None:
    """Ghi danh sach bai viet ra JSONL (moi dong la mot JSON object)."""
    rows = [a.to_row() for a in articles]
    if append and path.exists():
        existing_rows: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing_rows.append(json.loads(line))
        seen_urls = {r.get("url", "") for r in existing_rows}
        rows = existing_rows + [r for r in rows if r.get("url", "") not in seen_urls]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Tao parser CLI cho script."""
    parser = argparse.ArgumentParser(
        description=(
            "Crawl tin tuc su kien co phieu tu VietstockFinance.\n"
            "Vi du: python3 vietstock_news_crawler.py --symbols FPT,VCB --max-pages 3"
        )
    )
    parser.add_argument(
        "--symbols",
        default="FPT",
        help="Danh sach ma co phieu phan tach bang dau phay. Vi du: FPT,VCB,HPG",
    )
    parser.add_argument("--max-pages", type=int, default=3, help="So trang AJAX moi ma (10 bai/trang).")
    parser.add_argument("--page-size", type=int, default=10, help="So bai moi trang AJAX.")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay giua cac request (giay).")
    parser.add_argument("--timeout", type=int, default=25, help="Timeout HTTP (giay).")
    parser.add_argument(
        "--include-content",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Co fetch full content trang bai viet hay chi lay metadata tu AJAX.",
    )
    parser.add_argument(
        "--start-date",
        type=parse_date_arg,
        default=None,
        help="Ngay bat dau usable_from_date, dinh dang YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_date_arg,
        default=None,
        help="Ngay ket thuc usable_from_date, inclusive, dinh dang YYYY-MM-DD.",
    )
    parser.add_argument(
        "--auto-pages",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Tu tinh max trang tu TotalRow. Mac dinh bat khi co --start-date "
            "hoac --end-date."
        ),
    )
    parser.add_argument(
        "--output",
        default="data/raw/vietstock_raw/vietstock_news.csv",
        help="Duong dan file CSV output.",
    )
    parser.add_argument(
        "--jsonl-output",
        default="data/raw/vietstock_raw/vietstock_news.jsonl",
        help="Duong dan file JSONL output.",
    )
    parser.add_argument("--append", action="store_true", help="Them vao file cu thay vi ghi moi.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point cua script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_date_range(args.start_date, args.end_date)
    except ValueError as exc:
        parser.error(str(exc))

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_articles: list[VietstockArticle] = []
    auto_pages = args.auto_pages
    if auto_pages is None:
        auto_pages = bool(args.start_date or args.end_date)

    for symbol in symbols:
        articles = crawl_vietstock_news(
            symbol,
            max_pages=args.max_pages,
            page_size=args.page_size,
            include_content=args.include_content,
            start_date=args.start_date,
            end_date=args.end_date,
            auto_pages=auto_pages,
            timeout=args.timeout,
            delay=args.delay,
        )
        all_articles.extend(articles)
        if len(symbols) > 1:
            # Nghi them giua cac ma de tranh hammer server
            time.sleep(args.delay * 2)

    if args.output:
        write_csv(Path(args.output), all_articles, append=args.append)
        print(f"CSV written -> {args.output}")
    if args.jsonl_output:
        write_jsonl(Path(args.jsonl_output), all_articles, append=args.append)
        print(f"JSONL written -> {args.jsonl_output}")

    error_count = sum(1 for a in all_articles if a.crawl_error)
    print(
        f"Total: {len(all_articles)} articles across {len(symbols)} symbol(s) "
        f"({error_count} with errors)."
    )
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
