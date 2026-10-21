"""语义重复复核：全量题对、文本粗筛排序、人工结论及内容指纹验证。"""
import argparse
from difflib import SequenceMatcher
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
from .assembly import stem_key


CRITERIA = (
    "比较考查目标、已知条件、求解过程和所需结论。仅表述或数字改变、核心任务及解法相同可判 DUPLICATE；"
    "仅同知识点但考查目标或推理任务不同判 DISTINCT；缺少材料或无法确定判 UNRESOLVED。"
    "答案字母相同不能作为重复证据。本检查不包含跨题答案提示。"
)


def content_fingerprint(question):
    content = {k: question.get(k) for k in ("question_id", "version", "stem", "options", "answer", "explanation")}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_review_packet(questions):
    ids = [q["question_id"] for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("复核输入题号必须唯一")
    pairs = []
    for left, right in combinations(questions, 2):
        score = SequenceMatcher(None, stem_key(left["stem"]), stem_key(right["stem"])).ratio()
        pair_id = hashlib.sha256(json.dumps(sorted([left["question_id"], right["question_id"]]),
                                           ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
        pairs.append({"pair_id": pair_id, "question_ids": [left["question_id"], right["question_id"]],
                      "content_hashes": [content_fingerprint(left), content_fingerprint(right)],
                      "text_similarity": round(score, 4),
                      "same_topic": left.get("topic") == right.get("topic"),
                      "left": left, "right": right})
    # 全部题对保留，避免低字面相似度导致漏检；排序只是帮助人工优先处理。
    pairs.sort(key=lambda p: (p["same_topic"], p["text_similarity"]), reverse=True)
    return {"criteria": CRITERIA, "question_count": len(questions), "pair_count": len(pairs),
            "method": "ALL_PAIRS_WITH_LEXICAL_PRIORITY", "pairs": pairs,
            "note": "相似度不是语义结论，尚未接入 embedding 或大模型；包含教师答案，不发给学生。"}


def evaluate_decisions(packet, decisions):
    if not isinstance(decisions, list):
        raise ValueError("复核结论必须是列表")
    known = {p["pair_id"]: p for p in packet["pairs"]}
    seen, accepted, errors = set(), {}, []
    invalid_ids = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append("结论不是对象")
            continue
        pid = decision.get("pair_id")
        if not isinstance(pid, str) or pid not in known:
            errors.append("结论引用未知题对")
            continue
        if pid in seen:
            invalid_ids.add(pid)
            errors.append(f"重复的题对结论：{pid}")
            continue
        seen.add(pid)
        if (decision.get("content_hashes") != known[pid]["content_hashes"]
                or decision.get("verdict") not in ("DUPLICATE", "DISTINCT", "UNRESOLVED")
                or not isinstance(decision.get("reviewer"), str) or not decision["reviewer"].strip()
                or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()
                or decision.get("source") != "human"):
            invalid_ids.add(pid)
            errors.append(f"题对 {pid} 缺少有效人工依据、审核人，或内容已变更")
            continue
        accepted[pid] = decision
    for pid in invalid_ids:
        accepted.pop(pid, None)
    duplicates = [p for p in packet["pairs"] if accepted.get(p["pair_id"], {}).get("verdict") == "DUPLICATE"]
    unresolved = [p["pair_id"] for p in packet["pairs"]
                  if accepted.get(p["pair_id"], {}).get("verdict") not in ("DUPLICATE", "DISTINCT")]
    return {"status": "DUPLICATES_FOUND" if duplicates else
                       "NEEDS_REVIEW" if unresolved or errors else "SEMANTIC_REVIEW_PASS",
            "pair_count": packet["pair_count"], "accepted_decisions": list(accepted.values()),
            "duplicate_pairs": [{"pair_id": p["pair_id"], "question_ids": p["question_ids"]} for p in duplicates],
            "unresolved_pair_ids": unresolved, "errors": errors,
            "note": "仅判断语义重复；不等于全卷质量通过。人工填写仅记录声明，不验证审核人身份。"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="带完整题目字段的内部格式列表")
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    packet = build_review_packet(json.loads(args.input.read_text(encoding="utf-8-sig")))
    decisions = json.loads(args.decisions.read_text(encoding="utf-8-sig")) if args.decisions else []
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("请使用新的空输出目录，避免覆盖人工复核记录")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    template = [{"pair_id": p["pair_id"], "content_hashes": p["content_hashes"], "source": "human",
                 "verdict": "UNRESOLVED", "reviewer": "", "reason": ""} for p in packet["pairs"]]
    result = evaluate_decisions(packet, decisions)
    for name, value in (("review_packet.json", packet), ("decisions_template.json", template), ("report.json", result)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "pair_count": result["pair_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
