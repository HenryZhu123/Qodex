"""Offline synthetic demo only: no database, no model, no real PASS acceptance."""
import json
from pathlib import Path
import sys

from exam_assembly_agent.main import assemble_exam
from exam_assembly_service.replenishment import propose_replenishment


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    request = dict(request_id="JOINT_DEFICIT_SYNTHETIC_DEMO", subject="数据结构", question_type="single_choice",
                   question_count=3, total_score=6, score_per_question=2, topic_counts={"栈": 2, "队列": 1},
                   difficulty_counts={"easy": 1, "medium": 0, "hard": 2}, allow_mock_reviews=True)
    candidates = []
    for index, (topic, difficulty) in enumerate([("栈", "easy")] * 3 + [("队列", "hard")] * 3):
        candidates.append(dict(question_id=f"TEST_ONLY_{index}", version=1, subject="数据结构", topic=topic,
                               question_type="single_choice", difficulty=difficulty, score=2,
                               stem=f"合成槽位测试题{index}，非正式试题", options=dict(A="甲", B="乙", C="丙", D="丁"),
                               answer="A", explanation="合成测试", review=dict(status="PASS", question_version=1, is_mock=True)))
    report = assemble_exam(request, candidates)
    plan = propose_replenishment(request, candidates)
    report.update(mode="DEVELOPMENT_MOCK_BANK", real_quality_acceptance=False,
                  replenishment_request=plan, deficits=plan["deficits"])
    root = Path(__file__).resolve().parents[4]
    folder = root / "outputs/joint_deficit_demo"
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in (("report.json", report), ("replenishment_request.json", plan)):
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(status=report["status"], mode=report["mode"],
                          topic_deficits=report["topic_deficits"], difficulty_deficits=report["difficulty_deficits"],
                          joint_deficits=plan["deficits"], output_dir=str(folder)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
