import os
import argparse

def merge_jsonl_files(input_folder):
    output_file = os.path.join(
        input_folder,
        "cafef_news_2021_2026.jsonl"
    )

    jsonl_files = sorted(
        f for f in os.listdir(input_folder)
        if f.endswith(".jsonl")
    )

    total_lines = 0

    with open(output_file, "w", encoding="utf-8") as outfile:
        for file_name in jsonl_files:
            file_path = os.path.join(input_folder, file_name)

            # tránh đọc chính file output nếu chạy lại
            if file_path == output_file:
                continue

            print(f"Đang xử lý: {file_name}")

            with open(file_path, "r", encoding="utf-8") as infile:
                for line in infile:
                    line = line.strip()
                    if line:
                        outfile.write(line + "\n")
                        total_lines += 1

    print(f"\nĐã gộp {len(jsonl_files)} file.")
    print(f"Tổng số bản ghi: {total_lines}")
    print(f"File kết quả: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Thư mục chứa các file JSONL")
    args = parser.parse_args()

    merge_jsonl_files(args.folder)
