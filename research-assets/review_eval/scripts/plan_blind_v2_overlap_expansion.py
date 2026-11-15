"""Phase-1 source selection for the Blind-v2 overlap-source stress expansion.

This script performs bookkeeping only: it does not mutate any question.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "blind_v2_overlap_expansion_20261031"
RUN_DIR = ROOT / "blind_v2_expansion" / "runs" / RUN_ID
MANUAL_EXCLUDE_REASONS = {
    "refq-408-2010-34": "clean baseline contains duplicated phrase 分组交换网/网络中",
    "refq-408-2016-34": "clean baseline depends on missing shared figure and contains trailing figure caption",
    "refq-408-2019-12": "clean baseline already contains a parenthetical answer hint",
    "refq-408-2019-20": "clean baseline already contains a parenthetical answer hint",
}
ANSWER_OVERRIDES = {
    "refq-408-2010-01": "D",
    "refq-408-2010-11": "A",
    "refq-408-2010-16": "A",
    "refq-408-2010-25": "B",
    "refq-408-2010-26": "A",
    "refq-408-2011-01": "A",
    "refq-408-2011-19": "D",
    "refq-408-2011-23": "B",
    "refq-408-2011-25": "D",
    "refq-408-2011-33": "A",
    "refq-408-2012-02": "A",
    "refq-408-2012-03": "A",
    "refq-408-2012-11": "D",
    "refq-408-2012-12": "D",
    "refq-408-2012-27": "D",
    "refq-408-2018-14": "A",
    "refq-408-2018-23": "B",
    "refq-408-2018-33": "B",
    "refq-408-2018-34": "C",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in text.split("\n")]
    return "\n".join(lines).strip()


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def infer_408_subject(source_id: str, fallback: str) -> str:
    match = re.search(r"-(\d{2})$", source_id)
    if not match:
        return fallback
    question_no = int(match.group(1))
    if 1 <= question_no <= 11:
        return "data_structure"
    if 12 <= question_no <= 22:
        return "computer_organization"
    if 23 <= question_no <= 32:
        return "operating_system"
    if 33 <= question_no <= 40:
        return "computer_network"
    return fallback


def corrected_answer(source_id: str, fallback: str) -> str:
    match = re.search(r"refq-408-(\d{4})-(\d{2})$", source_id)
    if not match:
        return fallback
    year, question_no = match.groups()
    answer_path = ROOT.parents[0] / "408exam" / "真题" / "manual_answers.json"
    manual_answers = json.loads(answer_path.read_text(encoding="utf-8"))
    return str(manual_answers.get(year, {}).get(str(int(question_no))) or ANSWER_OVERRIDES.get(source_id) or fallback)


def planned_slots() -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []

    def add(error_type: str, subtype: str, count: int, **constraints: Any) -> None:
        for index in range(1, count + 1):
            slots.append(
                {
                    "planned_error_type": error_type,
                    "planned_subtype": subtype,
                    "subtype_index": index,
                    **constraints,
                }
            )

    add("answer_leakage", "答案字母尾注", 3)
    add("answer_leakage", "正确项视觉标记", 3)
    add("answer_leakage", "作答括号预填", 3)
    add("answer_leakage", "答案文本内嵌", 3)
    add("answer_leakage", "解析首句直给结论", 3)

    add("factual_logical", "内部数值关系矛盾", 4, require_digits=True, require_pattern=r"\d+\s*(?:次|个|位|B|KB|MB|GB|%|GHz|MHz|秒|台|类|条|帧|页|块)", allowed_subjects=["computer_organization", "operating_system"])
    add("factual_logical", "协议层级或行为冲突", 3, require_pattern=r"TCP|UDP|IP|以太网|协议|OSI|DNS|SMTP|HTTP|FTP|交换机", allowed_subjects=["computer_network"])
    add("factual_logical", "算法不变量破坏", 3, allowed_subjects=["data_structure", "operating_system"])
    add("factual_logical", "边界值使对象失效", 2, require_digits=True)
    add("factual_logical", "单位容量关系不相容", 2, require_digits=True, require_pattern=r"KB|MB|GB|字节|位|bps|Hz|秒|CPI|容量|大小|频率|带宽|速率", allowed_subjects=["computer_organization", "operating_system", "computer_network"])

    add("type_mismatch", "配伍表格作答混入单选", 2)
    add("type_mismatch", "代码补全接口混入单选", 2)
    add("type_mismatch", "反例证明任务混入单选", 1)
    add("type_mismatch", "图中标注任务混入单选", 1)
    add("type_mismatch", "分步推导评分混入单选", 1)
    add("type_mismatch", "真假矩阵作答混入单选", 1)

    add("ambiguity", "比较基准缺失", 1, require_ambiguity_cue=True)
    add("ambiguity", "量词辖域歧义", 1, require_ambiguity_cue=True)
    add("ambiguity", "条件前件指向歧义", 1, require_ambiguity_cue=True)
    add("ambiguity", "同类对象未编号", 1, require_ambiguity_cue=True)
    add("ambiguity", "时间参照点不明", 1, require_ambiguity_cue=True)
    add("ambiguity", "否定附着歧义", 1, require_ambiguity_cue=True)
    add("ambiguity", "跨选项代词指代", 1, require_ambiguity_cue=True)

    add("solvability_failure", "multiple_valid_answers", 1, require_statement_mcq=True, allowed_source_ids=["refq-408-2014-39"])
    add("solvability_failure", "multiple_valid_answers", 1, require_statement_mcq=True, allowed_source_ids=["refq-408-2010-16"])
    add("solvability_failure", "multiple_valid_answers", 1, require_statement_mcq=True, allowed_source_ids=["refq-408-2009-07"])
    add("solvability_failure", "contradictory_conditions", 3, require_digits=True)

    add("option_structure", "层级编号与选项标号冲突", 1)
    add("option_structure", "选项标号与正文跨行错配", 1)
    add("punctuation", "引号与句末标点位置冲突", 1, require_quotes=True)
    add("punctuation", "省略号与分隔标点重复", 1, require_ellipsis=True)
    return slots


def load_historical_rows() -> list[dict[str, Any]]:
    paths = [
        ROOT / "taxonomy_v2" / "dev_a" / "review_eval_full.jsonl",
        ROOT / "taxonomy_v2" / "dev_b" / "blind_test_full.jsonl",
        ROOT / "taxonomy_v2" / "blind_v2" / "blind_v2_full.jsonl",
    ]
    return [row for path in paths for row in read_jsonl(path)]


def load_candidates() -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates: dict[str, dict[str, Any]] = {}
    rejected: Counter[str] = Counter()

    for row in read_jsonl(ROOT / "dataset" / "clean_set.jsonl"):
        source_id = str(row.get("record_id") or "")
        candidates[source_id] = {
            "source_record_id": source_id,
            "clean_text": row.get("full_text", ""),
            "source_answer": corrected_answer(source_id, str(row.get("standard_answer", ""))),
            "source_answer_original": row.get("standard_answer", ""),
            "source_subject": infer_408_subject(source_id, str(row.get("subject", ""))),
            "source_year": row.get("year"),
            "source_origin": "dev_a",
            "source_file": str(ROOT / "dataset" / "clean_set.jsonl"),
        }

    for row in read_jsonl(ROOT / "taxonomy_v2" / "dev_b" / "blind_test_full.jsonl"):
        source_id = str(row.get("source_record_id") or "")
        if not source_id or source_id in candidates:
            continue
        candidates[source_id] = {
            "source_record_id": source_id,
            "clean_text": row.get("clean_text") or (row.get("full_text") if row.get("label") == "clean" else ""),
            "source_answer": corrected_answer(source_id, str(row.get("source_answer", ""))),
            "source_answer_original": row.get("source_answer", ""),
            "source_subject": infer_408_subject(source_id, str(row.get("source_subject", ""))),
            "source_year": row.get("source_year"),
            "source_origin": "dev_b",
            "source_file": str(ROOT / "taxonomy_v2" / "dev_b" / "blind_test_full.jsonl"),
        }

    usable: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    for row in candidates.values():
        text = str(row["clean_text"] or "").strip()
        answer = str(row["source_answer"] or "").strip().upper()[:1]
        if row["source_record_id"] in MANUAL_EXCLUDE_REASONS:
            rejected["manual_clean_baseline_rejection"] += 1
            continue
        if not text or len(text) < 40:
            rejected["missing_or_short_clean_text"] += 1
            continue
        if answer not in {"A", "B", "C", "D"}:
            rejected["missing_single_choice_answer"] += 1
            continue
        if re.search(r"如下所示[。.]?\s*\n\s*\n\s*(?:若|则|下列)", text):
            rejected["visible_structure_gap"] += 1
            continue
        if not all(re.search(rf"(?m)^\s*{letter}[.．、)]", text) for letter in "ABCD"):
            rejected["not_four_option_mcq"] += 1
            continue
        digest = fingerprint(text)
        if digest in seen_fingerprints:
            rejected["duplicate_clean_text"] += 1
            continue
        seen_fingerprints.add(digest)
        row["source_fingerprint_sha256"] = digest
        usable.append(row)
    return usable, rejected


def eligible(candidate: dict[str, Any], slot: dict[str, Any], historical_types: dict[str, set[str]]) -> bool:
    target = slot["planned_error_type"]
    source_id = candidate["source_record_id"]
    if target in historical_types[source_id]:
        return False
    if slot.get("allowed_source_ids") and source_id not in slot["allowed_source_ids"]:
        return False
    text = candidate["clean_text"]
    subject = candidate["source_subject"]
    if slot.get("allowed_subjects") and subject not in slot["allowed_subjects"]:
        return False
    if slot.get("require_digits") and not re.search(r"\d", text):
        return False
    if slot.get("require_quotes") and not re.search(r"[“”\"《》]", text):
        return False
    if slot.get("require_ellipsis") and not re.search(r"[…]|\.\.\.", text):
        return False
    if slot.get("require_statement_mcq") and not re.search(r"正确的是|错误的是|不正确的是|叙述中", text):
        return False
    if slot.get("require_pattern") and not re.search(str(slot["require_pattern"]), text, re.IGNORECASE):
        return False
    if slot.get("require_ambiguity_cue") and not re.search(r"其|该|这|上述|其中|若|当|时|前者|后者|不|均|所有", text):
        return False
    return True


def registry_fingerprints() -> set[str]:
    fingerprints: set[str] = set()
    paths = [
        ROOT.parents[0] / "训练集-微调版提示词" / "train_v2" / "source_usage_registry.jsonl",
        ROOT.parents[0] / "数据资产" / "finetune" / "source_usage_registry.jsonl",
    ]
    for path in paths:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            digest = row.get("source_fingerprint_sha256") or row.get("source_question_fingerprint")
            if digest:
                fingerprints.add(str(digest))
    return fingerprints


def near_duplicate_pairs(rows: list[dict[str, Any]], threshold: float = 0.85) -> list[dict[str, Any]]:
    def grams(text: str) -> set[str]:
        compact = re.sub(r"\s+", "", normalize(text))
        return {compact[index : index + 5] for index in range(max(0, len(compact) - 4))}

    cached = [(row["source_record_id"], grams(row["clean_text"])) for row in rows]
    pairs: list[dict[str, Any]] = []
    for index, (left_id, left) in enumerate(cached):
        for right_id, right in cached[index + 1 :]:
            union = left | right
            score = len(left & right) / len(union) if union else 1.0
            if score >= threshold:
                pairs.append({"left": left_id, "right": right_id, "jaccard_5gram": round(score, 6)})
    return pairs


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    historical = load_historical_rows()
    historical_types: dict[str, set[str]] = defaultdict(set)
    for row in historical:
        source_id = str(row.get("source_record_id") or "")
        if source_id and row.get("error_type") != "none":
            historical_types[source_id].add(str(row.get("error_type")))

    candidates, rejected = load_candidates()
    slots = sorted(
        planned_slots(),
        key=lambda slot: (
            not slot.get("require_quotes", False),
            not slot.get("require_ellipsis", False),
            not bool(slot.get("allowed_subjects")),
            not slot.get("require_digits", False),
            slot["planned_error_type"],
            slot["planned_subtype"],
        ),
    )
    selected: list[dict[str, Any]] = []
    used_sources: set[str] = set()
    subject_counts: Counter[str] = Counter()
    type_subject_counts: dict[str, Counter[str]] = defaultdict(Counter)
    year_counts: Counter[str] = Counter()
    registry = registry_fingerprints()

    subject_targets = {
        "data_structure": 14,
        "computer_organization": 14,
        "operating_system": 13,
        "computer_network": 13,
    }
    for slot in slots:
        options = [
            row
            for row in candidates
            if row["source_record_id"] not in used_sources
            and eligible(row, slot, historical_types)
        ]
        if not options:
            raise RuntimeError(f"No eligible source for {slot}")

        def score(row: dict[str, Any]) -> tuple[Any, ...]:
            subject = str(row["source_subject"])
            target = subject_targets.get(subject, 1)
            return (
                subject_counts[subject] / target,
                type_subject_counts[slot["planned_error_type"]][subject],
                year_counts[str(row["source_year"])],
                row["source_origin"] != "dev_a",
                row["source_record_id"],
            )

        choice = min(options, key=score)
        used_sources.add(choice["source_record_id"])
        subject_counts[str(choice["source_subject"])] += 1
        type_subject_counts[slot["planned_error_type"]][str(choice["source_subject"])] += 1
        year_counts[str(choice["source_year"])] += 1
        selected.append(
            {
                "sample_id": f"v2x-{slot['planned_error_type']}-{len(selected) + 1:03d}",
                **choice,
                "planned_error_type": slot["planned_error_type"],
                "planned_subtype": slot["planned_subtype"],
                "historical_types_for_source": sorted(historical_types[choice["source_record_id"]]),
                "registry_hit": choice["source_fingerprint_sha256"] in registry,
                "selection_status": "selected_phase1",
                "reuse_authorization": "user_explicitly_allowed_dev_a_dev_b_source_overlap",
            }
        )

    selected.sort(key=lambda row: (row["planned_error_type"], row["planned_subtype"], row["sample_id"]))
    (RUN_DIR / "source_selection.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected),
        encoding="utf-8",
    )
    near_duplicates = near_duplicate_pairs(selected)
    summary = {
        "run_id": RUN_ID,
        "candidate_rows_usable": len(candidates),
        "candidate_rows_rejected": dict(rejected),
        "selected": len(selected),
        "by_error_type": dict(Counter(row["planned_error_type"] for row in selected)),
        "by_subtype": dict(Counter(row["planned_subtype"] for row in selected)),
        "by_subject": dict(subject_counts),
        "by_source_origin": dict(Counter(row["source_origin"] for row in selected)),
        "selected_source_answers_corrected": sum(
            str(row.get("source_answer_original", "")).strip().upper()[:1]
            != str(row.get("source_answer", "")).strip().upper()[:1]
            for row in selected
        ),
        "registry_hits_authorized": sum(bool(row["registry_hit"]) for row in selected),
        "selected_exact_duplicate_fingerprints": len(selected)
        - len({row["source_fingerprint_sha256"] for row in selected}),
        "selected_near_duplicate_pairs_at_0_85": near_duplicates,
        "same_source_same_target_blocks": sum(
            1
            for slot in slots
            for row in candidates
            if slot["planned_error_type"] in historical_types[row["source_record_id"]]
        ),
    }
    (RUN_DIR / "phase1_selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
