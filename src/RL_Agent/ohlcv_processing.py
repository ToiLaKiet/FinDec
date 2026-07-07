import pandas as pd

input_file = "data/all_processed.csv"
output_file = "data/ready_myasset_hour.csv"

df = pd.read_csv(input_file)

# Đổi tên cột cho đúng format repo
df = df.rename(columns={
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume": "Volume",
})

# Parse datetime
df["datetime"] = pd.to_datetime(df["time"])

# Sắp xếp theo thời gian tăng dần
df = df.sort_values("datetime")

# Tạo cột thời gian
df["hour_of_day"] = df["datetime"].dt.hour
df["day_of_week"] = df["datetime"].dt.dayofweek

# Nếu chưa có dữ liệu news/sentiment thì tạo cột giả
if "news-count" not in df.columns:
    df["news-count"] = 0

if "min-sent" not in df.columns:
    df["min-sent"] = 0.0

# Chọn các cột cần thiết
cols = [
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

df = df[cols]

df.to_csv(output_file, index=False)

print(f"Saved to {output_file}")
print(df.head())
