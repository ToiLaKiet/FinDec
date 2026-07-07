import argparse
import json
from pathlib import Path


DEFAULT_INPUT = Path("data/raw_news/cafef_raw/cafef_news_2021_2026.jsonl")
DEFAULT_OUTPUT = Path("data/title_classification/cafef_article_metadata_2021_2026.json")
FIELDS = ("article_id", "usable_from_date", "title")


def extract_article_metadata(input_path, output_path):
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_rows = 0

    with input_path.open("r", encoding="utf-8") as infile, output_path.open(
        "w", encoding="utf-8"
    ) as outfile:
        outfile.write("[\n")

        first_record = True
        for line_number, line in enumerate(infile, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                article = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_number}: {exc}") from exc

            record = {field: article.get(field, "") for field in FIELDS}

            if not first_record:
                outfile.write(",\n")
            json.dump(record, outfile, ensure_ascii=False, indent=2)
            first_record = False
            total_rows += 1

        outfile.write("\n]\n")

    return total_rows


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract article_id, usable_from_date, and title from CafeF JSONL."
    )
    parser.add_argument(
        "--input",
        default=DEFAULT_INPUT,
        type=Path,
        help=f"Input JSONL file. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        type=Path,
        help=f"Output JSON file. Default: {DEFAULT_OUTPUT}",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    total_rows = extract_article_metadata(args.input, args.output)
    print(f"Wrote {total_rows} records to {args.output}")


if __name__ == "__main__":
    main()
