# CafeF News Crawler cho mô hình RL

Crawler này lấy tin từ chuyên mục CafeF:

- Trang chuyên mục: <https://cafef.vn/thi-truong-chung-khoan.chn>
- RSS nhẹ hơn để lấy danh sách bài mới: <https://cafef.vn/thi-truong-chung-khoan.rss>

Sau khi lấy danh sách bài, script vào từng trang bài để trích xuất `title`, `summary`,
`content`, `published_at`, `author`, `tags` và ngày có thể dùng cho mô hình
`usable_from_date`. Crawler không lọc theo mã cổ phiếu; dữ liệu thu được là tin chung
của chuyên mục thị trường chứng khoán.

## Cài đặt

```bash
python3 -m pip install -r requirements.txt
```

## Crawl nhanh 30 bài mới nhất

```bash
python3 src/news_crawler/cafef_news_crawler.py \
  --max-articles 30 \
  --delay 1 \
  --output data/raw/cafef_news.csv \
  --jsonl-output data/raw/cafef_news.jsonl
```

## Crawl từ cả RSS và trang chuyên mục

Mặc định crawler dùng trang chuyên mục CafeF và tự gọi endpoint “xem thêm”
`/timelinelist/18831/{page}.chn` khi `--max-articles` lớn hơn số bài ở trang đầu.
`--max-articles 0` nghĩa là không tự giới hạn số bài sau discovery.

```bash
python3 src/news_crawler/cafef_news_crawler.py \
  --max-articles 100 \
  --append \
  --output data/raw/cafef_news.csv \
  --jsonl-output data/raw/cafef_news.jsonl
```

## Crawl theo khoảng ngày

Lọc theo `published_date`, với `--end-date` được tính inclusive. CafeF RSS/category chủ yếu
trả danh sách bài mới. Crawler sẽ tự gọi timeline khi cần; nếu muốn giới hạn cứng số trang
timeline thì truyền `--timeline-pages`. Với chuyên mục thị trường chứng khoán,
`timeline-zone-id` mặc định là `18831`. Các khoảng ngày cũ có thể cần đi rất sâu
trong timeline; `--auto-timeline-page-limit` mặc định là 500.

```bash
python3 src/news_crawler/cafef_news_crawler.py \
  --start-date 2026-01-01 \
  --end-date 2026-06-08 \
  --source category \
  --max-articles 0 \
  --auto-timeline-page-limit 500
```

## Các cột quan trọng

- `published_at`: thời điểm CafeF đăng bài theo giờ Việt Nam.
- `published_date`: ngày đăng gốc.
- `usable_from_date`: ngày nên dùng khi merge với dữ liệu giá EOD. Tin sau 14:45 được đẩy sang ngày làm việc tiếp theo để giảm rủi ro leakage.
- `content`: nội dung text đã bỏ phần lớn HTML, ảnh, quảng cáo và box liên quan.
- `crawl_error`: lỗi nếu không lấy được trang chi tiết; dòng vẫn được giữ nếu RSS có dữ liệu.

## Gợi ý đưa vào RL

Khi merge với dữ liệu giá theo ngày, dùng `usable_from_date` để tránh leakage thời gian.
Từ dữ liệu tin có thể tạo feature như:

- số bài thị trường theo ngày;
- độ dài tin trung bình;
- flag có tin thị trường trong ngày;
- sentiment score hoặc embedding từ `title + summary + content`;
- nhóm từ khóa như ETF, IPO, cổ tức, khối ngoại, bán ròng, mua ròng, lãnh đạo, ESOP.

Giữ delay hợp lý khi crawl định kỳ, không crawl quá dày và không bỏ qua điều khoản/robots của nguồn.

## Vietstock Stock News CLI Agent

Agent thuần CLI dùng lại logic trong `vietstock_news_crawler.py`, mặc định crawl 10 mã
cổ phiếu:

```text
FPT, VCB, MBB, HPG, VNM, MWG, GAS, VHM, GMD, PNJ
```

Chạy một lần và ghi schema chung:

```bash
python3 src/news_crawler/news_crawl_agent.py \
  --max-pages 3 \
  --include-content \
  --output data/raw/stock_news.csv \
  --jsonl-output data/raw/stock_news.jsonl
```

Chạy theo khoảng ngày:

```bash
python3 src/news_crawler/news_crawl_agent.py \
  --start-date 2026-01-01 \
  --end-date 2026-06-08 \
  --max-pages 30 \
  --append
```

Chạy định kỳ mỗi giờ, tự append và dedupe theo URL:

```bash
python3 src/news_crawler/news_crawl_agent.py \
  --interval-hours 1 \
  --max-pages 3 \
  --append
```

Schema chung của agent gồm các cột chính:

- `record_id`, `source`, `source_article_id`, `raw_source`
- `crawl_scope`, `sector`, `primary_symbol`, `symbols`, `matched_keywords`
- `title`, `summary`, `content`, `url`
- `published_at`, `published_date`, `usable_from_date`
- `author`, `tags`, `image_url`, `content_length`, `crawled_at`, `crawl_error`

Nếu chỉ muốn giữ các bài có keyword công nghệ trong nội dung, thêm:

```bash
python3 src/news_crawler/news_crawl_agent.py --technology-keyword-only
```
