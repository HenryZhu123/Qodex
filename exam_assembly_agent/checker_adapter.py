"""将审校题库导出/API 响应转换为内部格式；不连接或修改数据库。"""
import argparse
import json
from pathlib import Path
import re
import sys


def convert_entry(entry, topic_mapping, *, mock_input=False):
    payload = entry["question_json"]
    question = payload["question"]
    metadata = payload["metadata"]
    document_id, question_id = entry["document_id"], entry["question_id"]
    if payload.get("document_id") != document_id or payload.get("question_id") != question_id:
        raise ValueError("题目来源标识不一致")
    if payload.get("review_status") != "PASS":
        raise ValueError("题库记录未标记 PASS")
    version = entry.get("source_version_id")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("缺少 source_version_id，不能伪造版本")
    # 当前搜索 API 不提供最新版本/最新审校证据，不能据入库 PASS 推断当前仍有效。
    if not mock_input:
        raise ValueError("真实记录还需验证来源审校及版本有效性；当前转换器仅支持显式开发模式")

    raw_options = question.get("options")
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        raise ValueError("目前仅支持四选项单选题")
    options = {}
    labelled = []
    for label, raw in zip("ABCD", raw_options):
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("选项内容为空或不是文本")
        match = re.match(r"^\s*([A-D])[.．、:：)）]\s*(.+)$", raw)
        labelled.append(bool(match))
        if match and match[1] != label:
            raise ValueError("选项标签顺序不一致")
        options[label] = match[2].strip() if match else raw.strip()
    if any(labelled) and not all(labelled):
        raise ValueError("选项标签格式混用，需要人工确认")
    if len(set(options.values())) != 4:
        raise ValueError("存在重复选项内容，答案无法可靠匹配")
    answer_text = question.get("answer_text", "").strip()
    if answer_text in options:
        answer = answer_text
    else:
        matches = [k for k, v in options.items() if v == answer_text]
        if len(matches) != 1:
            raise ValueError("答案不是单个 A-D 字母或唯一匹配的选项全文，需要人工确认")
        answer = matches[0]
    knowledge_points = metadata.get("knowledge_points")
    if not isinstance(knowledge_points, list) or not knowledge_points or any(
            not isinstance(k, str) or not k.strip() for k in knowledge_points):
        raise ValueError("知识点列表缺失或无效")
    mapped = {topic_mapping[k] for k in knowledge_points if k in topic_mapping}
    if len(mapped) != 1:
        raise ValueError("知识点没有唯一主分类；请在映射文件中明确归类，不能默认取第一项")
    question_type = question.get("question_type")
    if question_type not in ("single_choice", "单选题", "单项选择题"):
        raise ValueError("不支持或尚未映射的题型")
    score = question.get("points")
    if type(score) not in (int, float) or score <= 0 or not float(score).is_integer():
        raise ValueError("当前组卷器要求正整数分值；不自动补分或四舍五入")
    if metadata.get("difficulty") not in ("easy", "medium", "hard"):
        raise ValueError("难度标签无效")
    return {
        "question_id": json.dumps([document_id, question_id], ensure_ascii=False, separators=(",", ":")),
        "version": version, "subject": question["subject"], "topic": next(iter(mapped)),
        "knowledge_points": knowledge_points, "question_type": "single_choice",
        "difficulty": metadata["difficulty"], "score": int(score),
        "stem": question["question_text"], "options": options, "answer": answer,
        "explanation": "", "explanation_status": "NOT_PROVIDED",
        "provenance": {k: entry.get(k) for k in
                       ("record_id", "document_id", "question_id", "source_version_id", "source_review_id")},
        "original_answer_text": answer_text,
        "review": {"status": "PASS", "question_version": version, "is_mock": True,
                   "note": "显式开发转换；未验证真实审校及最新版本，不用于正式交付"},
    }


def convert_export(data, mapping, *, mock_input=False):
    entries = data.get("questions") if isinstance(data, dict) and "questions" in data else data
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise ValueError("需要题库记录列表、单条记录或 questions API 响应")
    accepted, rejected = [], []
    for index, entry in enumerate(entries):
        try:
            accepted.append(convert_entry(entry, mapping, mock_input=mock_input))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            rejected.append({"index": index, "reason": str(exc)})
    return accepted, {"accepted_count": len(accepted), "rejected": rejected,
                      "mode": "MOCK_DEVELOPMENT" if mock_input else "REAL_UNVERIFIED",
                      "note": "无解析不编造；无法转换的记录不参与组卷。"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--topic-map", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mock-input", action="store_true", help="明确按模拟开发数据处理")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    mapping = json.loads(args.topic_map.read_text(encoding="utf-8-sig"))
    if not isinstance(mapping, dict) or any(not isinstance(v, str) or not v.strip() for v in mapping.values()):
        raise ValueError("主知识点映射必须是名称到非空名称的对象")
    questions, report = convert_export(data, mapping, mock_input=args.mock_input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (("question_bank.json", questions), ("conversion_report.json", report)):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
