# VietstockFinance News Crawler

Crawler này lấy tin tức và sự kiện của từng mã cổ phiếu từ VietstockFinance:

- **Trang listing**: `https://finance.vietstock.vn/{SYMBOL}/tin-tuc-su-kien.htm`
- **AJAX endpoint**: `https://finance.vietstock.vn/data/getnews` (POST)
- **Trang bài viết**: `https://vietstock.vn/...` (fetch full content)

## Cơ chế hoạt động

```
1. GET /FPT/tin-tuc-su-kien.htm     → lấy ASP.NET_SessionId cookie
2. POST /data/getnews                → trả JSON danh sách tin (type=-1, paged)
3. GET https://vietstock.vn/<slug>   → parse full content từng bài
```

### Cấu trúc JSON từ /data/getnews

| Field        | Kiểu     | Mô tả                                     |
|--------------|----------|--------------------------------------------|
| `ArticleID`  | int      | ID bài viết (dùng làm primary key)        |
| `Title`      | string   | Tiêu đề bài viết                          |
| `Head`       | string   | Sapo / tóm tắt ngắn                       |
| `PublishTime`| string   | `/Date(ms)/` — Unix timestamp miliseconds |
| `URL`        | string   | URL tương đối, ghép với `vietstock.vn`    |
| `TotalRow`   | int      | Tổng số bài (dùng để phân trang)          |
| `Source`     | string   | Nguồn: FILI, HOSE, HNX, Vietstock, ...    |
| `Content`    | string   | Thường rỗng trong listing                 |

### Tham số AJAX

```
POST /data/getnews
code=FPT&type=-1&page=1&pageSize=10
```
- `type=-1`: lấy tất cả (tin + sự kiện); `type=0`: chỉ tin tức
- Không cần `__RequestVerificationToken` trong payload này

## Cài đặt

```bash
pip install -r requirements.txt  # beautifulsoup4>=4.12
```

## Chạy nhanh — chỉ metadata (không fetch bài chi tiết)

```bash
python3 src/news_crawler/vietstock_news_crawler.py \
  --symbols FPT \
  --max-pages 3 \
  --no-include-content \
  --output data/raw/vietstock_news.csv \
  --jsonl-output data/raw/vietstock_news.jsonl
```

## Crawl đầy đủ kèm nội dung bài viết

```bash
python3 src/news_crawler/vietstock_news_crawler.py \
  --symbols FPT,VCB,HPG \
  --max-pages 5 \
  --include-content \
  --delay 1.5 \
  --output data/raw/vietstock_news.csv \
  --jsonl-output data/raw/vietstock_news.jsonl
```

## Crawl thêm vào file hiện có (--append)

```bash
python3 src/news_crawler/vietstock_news_crawler.py \
  --symbols FPT \
  --max-pages 2 \
  --append \
  --jsonl-output data/raw/vietstock_news.jsonl
```

## Schema output

| Cột               | Mô tả                                                        |
|-------------------|--------------------------------------------------------------|
| `article_id`      | ArticleID từ Vietstock JSON                                  |
| `source`          | Luôn là `vietstock`                                          |
| `raw_source`      | `ajax_list` hoặc `detail`                                    |
| `symbol`          | Mã cổ phiếu crawl (FPT, VCB, ...)                           |
| `title`           | Tiêu đề bài viết                                             |
| `summary`         | Sapo từ JSON listing (`Head`)                                |
| `content`         | Nội dung đầy đủ (nếu `--include-content`)                   |
| `url`             | URL bài viết đầy đủ trên vietstock.vn                       |
| `published_at`    | Timestamp xuất bản ISO 8601 theo giờ VN                     |
| `published_date`  | Ngày xuất bản YYYY-MM-DD                                     |
| `usable_from_date`| Ngày an toàn dùng cho feature (tránh leakage sau 14:45)    |
| `author`          | Nguồn bài: FILI, HOSE, HNX, Vietstock, ...                  |
| `tags`            | Tag bài viết, nối bằng `\|`                                  |
| `image_url`       | OG image (nếu fetch detail)                                  |
| `content_length`  | Số ký tự content                                             |
| `crawled_at`      | Timestamp script crawl                                       |
| `crawl_error`     | Lỗi fetch detail nếu có                                      |

## Tái sử dụng hàm trong code khác

```python
from src.news_crawler.vietstock_news_crawler import crawl_vietstock_news, write_jsonl
from pathlib import Path

# Lấy 30 bài mới nhất của FPT, bao gồm full content
articles = crawl_vietstock_news(
    "FPT",
    max_pages=3,        # 3 trang × 10 bài = tối đa 30 bài
    include_content=True,
    delay=1.5,          # giây giữa mỗi request
)

# Ghi ra JSONL
write_jsonl(Path("data/raw/fpt_news.jsonl"), articles)

# Hoặc xử lý trực tiếp
for a in articles:
    print(a.title, a.published_at, a.usable_from_date)
```

## Lưu ý

- Giữ `--delay` ≥ 1.0 giây để tôn trọng server Vietstock.
- Endpoint `/data/getnews` không yêu cầu đăng nhập (public).
- Một số bài có `Source=HOSE/HNX` là công bố thông tin chính thức — rất hữu ích cho sự kiện doanh nghiệp.
- Tin sau 14:45 được `usable_from_date` đẩy sang ngày làm việc kế tiếp.
