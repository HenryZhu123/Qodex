"""Pi 工具的离线开发入口。固定测试题库，不读写真实审校数据库。"""
import argparse
import base64
import json
from pathlib import Path
import sys
from uuid import uuid4
from .main import assemble_exam
from .question_bank import load_questions


BANKS = {"development": "question_bank.json", "repair_success": "repair_bank.json",
         "repair_failure": "repair_no_alternative_bank.json"}


def run_request(request, bank_name):
    if not isinstance(request, dict):
        raise ValueError("request 必须为对象")
    if bank_name not in BANKS:
        raise ValueError("未知开发题库")
    root = Path(__file__).parent
    result = assemble_exam(request, load_questions(root / "examples" / BANKS[bank_name]))
    folder = root / "outputs" / "pi_runs" / uuid4().hex
    folder.mkdir(parents=True)
    def save(name, value):
        path = folder / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.resolve())
    request_path = save("request.json", request)
    report_path = save("report.json", result)
    artifacts = {"request": request_path, "report": report_path}
    for key in ("student_exam", "answer_key", "replenishment_request"):
        if key in result:
            artifacts[key] = save(f"{key}.json", result[key])
    # 完整答案保存在本地教师文件，模型收到结构检查、学生题面和可追溯路径。
    return {"mode": "DEVELOPMENT_MOCK_BANK", "status": result["status"], "bank": bank_name,
            "request_snapshot": request, "artifacts": artifacts,
            "validation": result.get("validation"), "student_exam": result.get("student_exam"),
            "errors": result.get("errors", []), "message": result.get("message"),
            "topic_deficits": result.get("topic_deficits"),
            "difficulty_deficits": result.get("difficulty_deficits"),
            "repair_history": result.get("repair_history", []),
            "replenishment_request": result.get("replenishment_request"),
            "note": "模拟审校题库；STRUCTURAL_PASS 仅表示结构和相同题干检查通过，未完成语义或真实审校验证。"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-base64", required=True)
    parser.add_argument("--bank", choices=BANKS, default="development")
    args = parser.parse_args()
    try:
        request = json.loads(base64.b64decode(args.request_base64, validate=True).decode("utf-8"))
        result = run_request(request, args.bank)
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"status": "TOOL_ERROR", "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
