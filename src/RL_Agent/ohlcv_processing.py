import os
import pandas as pd

INPUT_FILE = "../../data/all_processed.csv"
OUTPUT_DIR = "its-sentarl/app/data"

os.makedirs(OUTPUT_DIR, exist_ok=True)

df = pd.read_csv(INPUT_FILE)

# Chuẩn hóa datetime
df["datetime"] = pd.to_datetime(df["time"])

# Sắp xếp dữ liệu
df = df.sort_values(["ticker", "datetime"])

# Tạo cột thời gian nếu chưa có
if "hour_of_day" not in df.columns:
    df["hour_of_day"] = df["datetime"].dt.hour

if "day_of_week" not in df.columns:
    df["day_of_week"] = df["datetime"].dt.dayofweek

# Nếu chưa có dữ liệu news/sentiment thì tạo cột giả
if "news-count" not in df.columns:
    df["news-count"] = 0

if "min-sent" not in df.columns:
    df["min-sent"] = 0.0

# Đảm bảo tên cột đúng format
rename_map = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
}
df = df.rename(columns=rename_map)

required_cols = [
    "datetime",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "hour_of_day",
    "day_of_week",
    "news-count",
    "min-sent",
]

for ticker, g in df.groupby("ticker"):
    ticker_lower = str(ticker).lower()

    out_file = os.path.join(
        OUTPUT_DIR,
        f"ready_{ticker_lower}_hour.csv"
    )

    g = g[required_cols].copy()
    g = g.sort_values("datetime")

    g.to_csv(out_file, index=False)

    print(f"Saved {ticker} -> {out_file}, rows = {len(g)}")
