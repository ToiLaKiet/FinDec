# SE365 Financial AI Demo

<p align="center">
  <img src="findec.png" alt="FinDec Logo" width="1800" />
</p>

## Giới thiệu

Dự án là website demo hợp nhất cho hai luồng xử lý tài chính:

- **Event Extraction**: crawl tin tức CafeF và dùng mô hình FinDec để rút trích sự kiện tài chính từ bài báo.
- **RL Trading**: dùng dữ liệu OHLCV và mô hình A2C đã train để sinh tín hiệu giao dịch cho danh sách cổ phiếu.

Thư mục `demo-ee` là bản demo chính hiện tại. Thư mục `demo` là bản đầu tiên, chưa đầy đủ, chỉ giữ lại để tham khảo lịch sử phát triển.

## Tính năng

- Crawl bài báo CafeF, theo dõi trạng thái job và xem kết quả rút trích sự kiện.
- Rút trích `topic`, `event_type`, `entities`, `context`, `attributes`, `evidence_text` từ bài viết tài chính.
- Hiển thị dashboard RL Trading dạng grid cổ phiếu.
- Load checkpoint A2C `.zip` mới nhất cho từng mã cổ phiếu khi trả quyết định `Buy`, `Sell`, `Hold`.
- Dùng một backend FastAPI chung ở port `8000` cho cả Event Extraction và RL Trading.

## Công nghệ sử dụng

- Python
- React
- TypeScript
- Tailwind CSS
- FastAPI
- PyTorch / Transformers
- Stable-Baselines3
- vnstock

## Cài đặt

```bash
git clone <repo-url>
cd <repo-name>
```

Cài backend:

```bash
cd demo-ee/SE365-backend
pip install -r requirements.txt
```

Cài frontend:

```bash
cd ../SE365
npm install
```

Lưu ý: backend cần thư mục model Event Extraction tại:

```bash
demo-ee/SE365-backend/model/findec_models
```

Các checkpoint RL Trading A2C nằm trong:

```bash
src/RL_Agent/its-sentarl/app/models/hour/static
```

## Cách chạy

Chạy backend:

```bash
cd demo-ee/SE365-backend
python -m uvicorn main:app --port 8000
```

Chạy frontend ở terminal khác:

```bash
cd demo-ee/SE365
npm run dev
```

Mở website theo URL Vite hiển thị trên terminal, thường là:

```bash
http://localhost:5173
```

Kiểm tra backend:

```bash
curl http://127.0.0.1:8000/health
```

## Cấu trúc thư mục

```text
.
├── README.md
├── requirements.txt
├── api.py
├── fin-rl.ipynb
├── data/
│   ├── ohlcv.csv
│   ├── labeled_ee_dataset/
│   └── raw_news/
│       ├── cafef_raw/
│       └── vietstock_raw/
├── demo-ee/
│   ├── SE365/
│   │   ├── src/
│   │   │   ├── App.tsx
│   │   │   ├── main.tsx
│   │   │   ├── styles.css
│   │   │   ├── components/
│   │   │   ├── services/
│   │   │   ├── types/
│   │   │   ├── utils/
│   │   │   └── data/
│   │   ├── findec.png
│   │   ├── package.json
│   │   ├── vite.config.ts
│   │   ├── tailwind.config.js
│   │   └── index.html
│   └── SE365-backend/
│       ├── main.py
│       ├── cafef_news_crawler.py
│       ├── model_inference.py
│       ├── detail_worker.py
│       ├── rl_trading.py
│       ├── requirements.txt
│       ├── data/
│       │   └── raw/
│       └── model/
│           └── findec_models/
│               ├── ner/
│               ├── topic/
│               ├── event/
│               └── detail/
├── demo/
│   └── rl_trading_demo/
│       ├── src/
│       ├── package.json
│       └── vite.config.ts
├── src/
│   ├── LLM_Labeling/
│   ├── News_Crawler/
│   │   ├── cafef/
│   │   └── vietstock/
│   ├── Title_Classification/
│   └── RL_Agent/
│       └── its-sentarl/
│           ├── app/
│           │   ├── common/
│           │   ├── data/
│           │   ├── envs/
│           │   ├── models/
│           │   ├── results/
│           │   ├── routines/
│           │   └── setups/
│           ├── docs/
│           └── sandbox/
└── paper /
    └── *.pdf
```

Mô tả nhanh:

- `demo-ee`: demo chính hiện tại, gồm frontend `SE365` và backend `SE365-backend`.
- `demo-ee/SE365`: giao diện React/TypeScript/Tailwind. `components` chứa UI, `services` chứa code gọi API, `types` chứa type TypeScript, `utils` chứa hàm format/map dữ liệu.
- `demo-ee/SE365-backend`: FastAPI backend chung. `main.py` khai báo API crawl/inference, `model_inference.py` chạy pipeline FinDec, `detail_worker.py` chạy Tier 2 Detail model tách process, `rl_trading.py` phục vụ RL Trading.
- `demo-ee/SE365-backend/model/findec_models`: nơi đặt các mô hình Event Extraction theo 4 nhóm `ner`, `topic`, `event`, `detail`.
- `demo-ee/SE365-backend/data/raw`: dữ liệu crawl và kết quả event sinh ra khi chạy demo.
- `demo`: bản demo đầu tiên, chưa đầy đủ; không phải luồng chạy chính.
- `src`: mã nguồn nghiên cứu/huấn luyện ban đầu, gồm crawler, labeling, title classification và RL agent.
- `src/RL_Agent/its-sentarl/app/models`: nơi chứa model/checkpoint RL; demo RL lấy checkpoint A2C `.zip` mới nhất trong nhánh `hour/static`.
- `data`: dữ liệu thô, dữ liệu đã gán nhãn và file OHLCV dùng cho thử nghiệm.
- `paper `: tài liệu PDF/paper tham khảo của dự án.
- `api.py`: Flask API/demo cũ của RL Trading, hiện chỉ dùng làm nguồn tham khảo logic; demo chính dùng FastAPI trong `demo-ee/SE365-backend`.
- `fin-rl.ipynb`: notebook thử nghiệm RL/financial data.

Các thư mục như `node_modules`, `dist`, `__pycache__`, `.git`, `.DS_Store` là thư mục/file sinh ra bởi môi trường chạy hoặc công cụ phát triển, không cần chỉnh trực tiếp.

## Cách sử dụng

1. Khởi động backend FastAPI ở port `8000`.
2. Khởi động frontend bằng `npm run dev`.
3. Vào tab **Event Extraction** để crawl tin CafeF, chờ job chạy xong và xem danh sách event được rút trích.
4. Vào tab **RL Trading** để xem grid cổ phiếu và tín hiệu `Buy`, `Sell`, `Hold`.
5. Backend API chính:
   - `GET /health`
   - `POST /crawl`
   - `GET /crawl/status/{job_id}`
   - `GET /crawl/result/{job_id}`
   - `GET /demo/decision/{ticker}`

## Tác giả

SE365 Team.

Thông tin liên hệ: cập nhật theo thông tin nhóm/dự án.

## License

MIT License.
