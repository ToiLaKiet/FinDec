# CafeF News Crawler cho mô hình RL

Crawler này lấy tin từ chuyên mục CafeF:

- Trang chuyên mục: <https://cafef.vn/thi-truong-chung-khoan.chn>
- RSS nhẹ hơn để lấy danh sách bài mới: <https://cafef.vn/thi-truong-chung-khoan.rss>

Sau khi lấy danh sách bài, script vào từng trang bài để trích xuất `title`, `summary`,
`content`, `published_at`, `author`, `tags`, `symbols` và ngày có thể dùng cho mô hình
`usable_from_date`.

## Cài đặt

```bash
python3 -m pip install -r requirements.txt
```

## Crawl nhanh 30 bài mới nhất

```bash
python3 src/cafef_news_crawler.py \
  --max-articles 30 \
  --delay 1 \
  --output data/raw/cafef_news.csv \
  --jsonl-output data/raw/cafef_news.jsonl
```

## Crawl và chỉ giữ bài nhắc tới mã trong universe

Ví dụ theo MVP 5 mã trong kế hoạch đồ án:

```bash
python3 src/cafef_news_crawler.py \
  --max-articles 100 \
  --symbols FPT,VCB,HPG,MWG,VNM \
  --require-symbol \
  --append \
  --output data/raw/cafef_news.csv \
  --jsonl-output data/raw/cafef_news.jsonl
```

Nếu dùng nhiều mã hơn, tạo file mỗi dòng một ticker rồi chạy:

```bash
python3 src/cafef_news_crawler.py \
  --symbols-file data/symbols_vn30.txt \
  --require-symbol \
  --append
```

## Các cột quan trọng

- `published_at`: thời điểm CafeF đăng bài theo giờ Việt Nam.
- `published_date`: ngày đăng gốc.
- `usable_from_date`: ngày nên dùng khi merge với dữ liệu giá EOD. Tin sau 14:45 được đẩy sang ngày làm việc tiếp theo để giảm rủi ro leakage.
- `symbols`: các mã được phát hiện từ ticker hoặc alias tên doanh nghiệp.
- `content`: nội dung text đã bỏ phần lớn HTML, ảnh, quảng cáo và box liên quan.
- `crawl_error`: lỗi nếu không lấy được trang chi tiết; dòng vẫn được giữ nếu RSS có dữ liệu.

## Gợi ý đưa vào RL

Khi merge với dữ liệu giá theo ngày, dùng `usable_from_date` + `symbols`.
Từ dữ liệu tin có thể tạo feature như:

- số bài theo mã/ngày;
- độ dài tin trung bình;
- flag có tin liên quan trong ngày;
- sentiment score hoặc embedding từ `title + summary + content`;
- nhóm từ khóa như ETF, IPO, cổ tức, khối ngoại, bán ròng, mua ròng, lãnh đạo, ESOP.

Giữ delay hợp lý khi crawl định kỳ, không crawl quá dày và không bỏ qua điều khoản/robots của nguồn.
