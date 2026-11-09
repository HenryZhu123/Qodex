"""Run one local request from a UTF-8 JSON file."""

import argparse
import json
from pathlib import Path
import sys

from .batch import generate_batch
from .comprehensive import generate_comprehensive, revise_comprehensive
from .generation import failure_result, generate_question


def main() -> int:
    parser = argparse.ArgumentParser(description="生成或修订可自检的 408 题目。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--batch", dest="run", action="store_const", const=generate_batch, help="按批量槽位请求出题")
    mode.add_argument("--comprehensive", dest="run", action="store_const", const=generate_comprehensive,
                      help="生成综合题")
    mode.add_argument("--revise", dest="run", action="store_const", const=revise_comprehensive,
                      help="按版本反馈修订综合题")
    parser.set_defaults(run=generate_question)
    parser.add_argument("request", type=Path, help="UTF-8 JSON 请求文件")
    args = parser.parse_args()

    try:
        payload = json.loads(args.request.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        result = failure_result("INVALID_REQUEST", f"无法读取 JSON 请求：{error}")
    else:
        result = args.run(payload)

    output = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")
    return 0 if result["status"] in {"GENERATED", "REVISED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
