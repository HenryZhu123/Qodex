"""Run one local request from a UTF-8 JSON file."""

import argparse
import json
from pathlib import Path
import sys

from .batch import generate_batch
from .generation import failure_result, generate_question


def main() -> int:
    parser = argparse.ArgumentParser(description="生成可自检的 408 单选题。")
    parser.add_argument("--batch", action="store_true", help="按批量槽位请求出题")
    parser.add_argument("request", type=Path, help="UTF-8 JSON 请求文件")
    args = parser.parse_args()

    try:
        payload = json.loads(args.request.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        result = failure_result("INVALID_REQUEST", f"无法读取 JSON 请求：{error}")
    else:
        result = generate_batch(payload) if args.batch else generate_question(payload)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")
    return 0 if result["status"] == "GENERATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
