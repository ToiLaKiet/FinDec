# Báo cáo quy trình dán nhãn dữ liệu CafeF

## 1. Mục đích

Notebook `label_cafef_2023_deepseek_v4_flash_raw_response.ipynb` được dùng để dán nhãn tự động cho dữ liệu tin tức tài chính tiếng Việt. Mục tiêu là đọc từng bài báo, nhận diện các sự kiện tài chính quan trọng và trích xuất kết quả theo một schema JSON thống nhất để phục vụ các bước phân tích hoặc huấn luyện mô hình sau này.

## 2. Dữ liệu đầu vào

Dữ liệu được đọc từ file:

```text
data/raw_news/merged_news.csv
```

Trong notebook, tập dữ liệu được lấy mẫu ngẫu nhiên 10.000 dòng với `random_state=42`:

```python
df = pd.read_csv(DATA_PATH).sample(n=N_ROWS, random_state=42).copy()
```

Mỗi dòng tương ứng với một bài báo và có các trường chính như `article_id`, `title`, `summary`, `content`, `published_date`, `url`, `source`, `category`.

## 3. Công cụ dán nhãn

Quá trình dán nhãn sử dụng mô hình DeepSeek thông qua Chat Completions API:

```python
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0
MAX_TOKENS = 8192
```

Notebook dùng `temperature = 0` để giảm tính ngẫu nhiên và giúp kết quả ổn định hơn. API được gọi từng bài một, tránh việc nhiều bài bị trộn thông tin sự kiện với nhau.

## 4. Thiết kế prompt

Prompt gồm ba phần chính:

1. `system_prompt.txt`: chứa quy tắc dán nhãn, danh sách loại sự kiện, schema JSON bắt buộc và hướng dẫn trích xuất.
2. `few_shots.txt`: chứa một số ví dụ mẫu để mô hình học cách chọn loại sự kiện, điền thông tin 5W1H, attributes và evidence.
3. Bài báo hiện tại: gồm `article_id`, nguồn, chuyên mục, tiêu đề, tóm tắt và nội dung bài.

Notebook yêu cầu mô hình chỉ trả về JSON hợp lệ, không giải thích thêm và bật:

```python
response_format = {"type": "json_object"}
```

Điều này giúp đầu ra dễ parse và dễ lưu vào file JSONL.

## 5. Schema nhãn

Mỗi bài báo được dán nhãn theo cấu trúc chính:

```json
{
  "doc_id": "string",
  "language": "vi",
  "main_topic": "ownership_change | lawsuit_bankruptcy | corporate_action | earnings | dividend | personnel | legal_risk | macro | market_price | other",
  "entities": [],
  "events": [],
  "summary": "string"
}
```

Trong đó, mỗi sự kiện trong `events` có:

- `event_type`: loại sự kiện tài chính.
- `entities_involved`: các thực thể liên quan.
- `context`: thông tin 5W1H gồm ai, làm gì, khi nào, ở đâu, tại sao, bằng cách nào, trạng thái và kết quả.
- `attributes`: thông tin chi tiết tùy theo từng loại sự kiện.
- `evidence_text`: câu hoặc đoạn gốc trong bài báo làm bằng chứng.
- `confidence`: độ tin cậy của nhãn.

Các nhóm sự kiện chính gồm biến động sở hữu cổ phiếu, kiện tụng/phá sản, M&A, chuyển giao tiền hoặc tài sản, báo cáo kết quả kinh doanh, cổ tức, phát hành chứng khoán, thay đổi nhân sự, xử phạt pháp lý, chỉ số vĩ mô và biến động giá.

## 6. Cách chạy batch

Để tránh chạy toàn bộ 10.000 dòng trong một lần, notebook chia dữ liệu thành 10 batch. Mỗi batch xử lý 1.000 dòng:

```python
run_label_batch(0, 1000, run_batch=True)
run_label_batch(1000, 2000, run_batch=True)
...
run_label_batch(9000, 10000, run_batch=True)
```

Kết quả được ghi nối tiếp vào:

```text
data/processed/10k_labeled_news.jsonl
```

File JSONL lưu mỗi bài trên một dòng. Nếu notebook bị dừng giữa chừng, khi chạy lại sẽ đọc file output hiện có và bỏ qua các `article_id` đã có nhãn thành công. Những dòng bị lỗi sẽ không bị bỏ qua mà được retry ở lần chạy sau.

## 7. Xử lý lỗi và kiểm tra kết quả

Trong quá trình gọi API, notebook có cơ chế retry với các lỗi tạm thời như timeout, rate limit hoặc lỗi server. Nếu một bài vẫn lỗi, notebook lưu lại `article_id`, tiêu đề và nội dung lỗi vào trường `error` để kiểm tra sau.

Theo file output hiện tại:

- Tổng số dòng đã ghi: 5.710
- Số dòng có label hợp lệ: 5.699
- Số dòng lỗi rõ ràng: 1
- Số dòng chưa có label nhưng không có lỗi rõ ràng: 10

Một số `main_topic` xuất hiện nhiều gồm `market_price`, `other`, `earnings`, `ownership_change`, `corporate_action`, `macro`, `dividend`, `legal_risk`, `personnel`, `lawsuit_bankruptcy`.

Các `event_type` phổ biến trong output hiện tại gồm `price_movement`, `earnings_report`, `dividend`, `equity_overweight`, `equity_underweight`, `share_issuance`, `macro_indicator`, `personnel_change`, `legal_penalty`, `transfer_money` và `transfer_ownership`.

## 8. Nhận xét

Quy trình dán nhãn này phù hợp để tạo nhanh dữ liệu có cấu trúc từ tin tức tài chính tiếng Việt. Điểm mạnh là schema rõ ràng, có ví dụ few-shot, có bằng chứng trích từ bài gốc và có cơ chế chạy lại khi bị gián đoạn. Tuy nhiên, vì nhãn được sinh bởi LLM, kết quả vẫn cần được kiểm tra mẫu thủ công, đặc biệt với các bài có nhiều sự kiện, bài có thông tin pháp lý phức tạp hoặc các trường hợp mô hình có thể suy diễn quá mức.

