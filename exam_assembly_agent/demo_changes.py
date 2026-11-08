"""离线演示：初次组卷、有效修改、矛盾修改和修改后缺题。"""
import argparse
import json
from pathlib import Path
import sys
from .question_bank import load_questions
from .request_session import RequestSession


def run_demo(output_dir):
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录已有内容，请使用新目录")
    root = Path(__file__).parent / "examples"
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    session = RequestSession(load_questions(root / "question_bank.json"))
    first = session.submit(request)
    changed = session.submit(changes={"question_count": 15, "total_score": 30,
        "topic_counts": {k: 3 for k in request["topic_counts"]},
        "difficulty_counts": {"easy": 5, "medium": 7, "hard": 3}}, base_revision=1)
    invalid = session.submit(changes={"total_score": 20}, base_revision=2)
    shortage = session.submit(changes={"question_count": 10, "total_score": 20,
        "topic_counts": request["topic_counts"],
        "difficulty_counts": {"easy": 0, "medium": 0, "hard": 10}}, base_revision=3)
    stages = [("01_initial", first), ("02_changed_valid", changed),
              ("03_conflicting_request", invalid), ("04_candidate_shortage", shortage)]
    checks = {"initial_passes": first["result"]["status"] == "STRUCTURAL_PASS",
              "changed_passes": changed["result"]["status"] == "STRUCTURAL_PASS",
              "changed_has_15_questions": len(changed["result"].get("student_exam", [])) == 15,
              "changed_total_30": changed["result"].get("validation", {}).get("actual_total_score") == 30,
              "conflict_detected": invalid["result"]["status"] == "INVALID_REQUEST",
              "shortage_detected": shortage["result"]["status"] == "NEEDS_QUESTIONS",
              "no_stale_exam_on_failure": all("student_exam" not in entry["result"] and
                                                not entry["current_exam_available"]
                                                for entry in (invalid, shortage))}
    summary = {"mode": "OFFLINE_MOCK_DEMO", "passed": all(checks.values()), "checks": checks,
               "statuses": {name: entry["result"]["status"] for name, entry in stages},
               "note": "模拟审校题库；只支持结构化修改，无自然语言解析或持久化会话恢复。"}
    output.mkdir(parents=True, exist_ok=True)
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, entry in stages:
        folder = output / name
        folder.mkdir()
        save(folder / "request.json", entry["request_snapshot"])
        save(folder / "revision.json", entry)
        save(folder / "report.json", entry["result"])
        for key in ("student_exam", "answer_key"):
            if key in entry["result"]:
                save(folder / f"{key}.json", entry["result"][key])
    save(output / "history.json", session.history)
    save(output / "summary.json", summary)
    return summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    summary = run_demo(parser.parse_args().output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
