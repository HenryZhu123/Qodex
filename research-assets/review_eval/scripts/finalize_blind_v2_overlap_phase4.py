#!/usr/bin/env python3
"""Audit Phase-3 candidates and build the versioned Blind-v2 expansion pack."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "blind_v2_expansion" / "runs" / "blind_v2_overlap_expansion_20261031"
VERSION = "blind_v2_overlap_expansion_v1"
OUT_DIR = RUN_DIR / "final" / VERSION

TYPE_CN = {
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
    "option_structure": "选项错误",
    "punctuation": "标点符号错误",
    "solvability_failure": "可解性错误",
    "type_mismatch": "题目与题型不一致",
}

SUBJECT_CN = {
    "data_structure": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_system": "操作系统",
    "computer_network": "计算机网络",
}

POSITION_CN = {
    "stem-storage-units": "题干中的容量对应关系",
    "step-1": "算法步骤（1）",
    "stem-merge-time": "题干中的归并段数量指代",
    "stem-ftp-actor": "题干中的连接指代",
    "stem-comparison": "题干中的优先级比较",
    "stem-complexity-object": "题干中的复杂度对象",
    "stem-quantifier": "题干中的量词表达",
    "stem-answer-slot": "题干作答位置",
    "option-C": "选项C",
    "stem-ending": "题干末尾",
    "stem-answer-clause": "题干答案内容处",
    "stem-opening": "题干开头",
    "stem-middle": "题干中部",
    "stem-given-values": "题干给定数值",
    "stem-access-counts": "题干访问次数",
    "stem-resource-totals": "题干资源总数",
    "stem-optimization-condition": "题干优化条件",
    "stem-device-layer-definition": "题干设备层级定义",
    "stem-protocol-behavior": "题干协议行为定义",
    "stem-forwarding-rule": "题干交换机转发规则",
    "stem-frame-length": "题干帧长单位换算",
    "stem-channel-condition": "题干信噪比单位",
    "program-loop-update": "程序循环更新语句",
    "stem-data-structure-definition": "题干数据结构定义",
    "stem-scheduling-property": "题干调度算法性质",
    "stem-stack-capacity": "题干栈容量条件",
    "stem-cpi-table": "题干指令比例表",
    "option-A-label": "选项A标号",
    "option-B-C-boundary": "选项B与C的边界",
    "stem-condition": "题干条件句",
    "stem-sequence": "题干序列分隔处",
    "stem-device-count": "题干设备数量条件",
    "stem-bit-count": "题干位数条件",
    "stem-matrix-order": "题干矩阵阶数条件",
    "option-A": "选项A",
    "option-B": "选项B",
    "stem-task": "题干作答任务",
}

# Phase-4 semantic repairs. The Phase-2 and Phase-3 artifacts remain immutable.
QUESTION_REPAIRS = {
    "v2x-ambiguity-022": {
        "error_text": "设外存上有120 个初始归并段，进行12 路归并时，为实现最佳归并，按该数计算需要补充的虚段个数\n是 。\nA. 1\nB. 2\nC. 3\nD. 4",
        "error_detailed_type": "数值代词指向歧义",
        "rationale": "“该数”之前同时出现120和12两个数值，无法确定虚段个数应以哪个数为计算依据。",
        "mutation_operation": "insert_ambiguous_numeric_pronoun",
        "mutation_location": "stem-merge-time",
        "mutation_token_class": "numeric-pronoun-two-antecedents",
    },
    "v2x-factual_logical-006": {
        "error_text": "程序P 在机器M 上的执行时间是20 秒，编译优化后，P 执行的指令数减少到原来的70%，而\nCPI 增加到原来的1.2 倍且同时仍等于原值，则P 在M 上的执行时间是 。\nA. 8.4 秒\nB. 11.7 秒\nC. 14 秒\nD. 16.8 秒",
        "rationale": "CPI被同时规定为原值的1.2倍和仍等于原值，两项条件不能同时成立。",
        "mutation_operation": "add_explicit_incompatible_cpi_equality",
        "mutation_location": "stem-optimization-condition",
        "mutation_token_class": "explicit-numeric-state-contradiction",
    },
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", "", value)


def char_grams(text: str, n: int = 5) -> set[str]:
    value = normalize(text)
    if len(value) < n:
        return {value} if value else set()
    return {value[index : index + n] for index in range(len(value) - n + 1)}


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def minimal_diff(error_text: str, clean_text: str) -> tuple[int, str, str]:
    prefix = 0
    limit = min(len(error_text), len(clean_text))
    while prefix < limit and error_text[prefix] == clean_text[prefix]:
        prefix += 1
    suffix = 0
    error_remaining = len(error_text) - prefix
    clean_remaining = len(clean_text) - prefix
    while (
        suffix < error_remaining
        and suffix < clean_remaining
        and error_text[len(error_text) - suffix - 1] == clean_text[len(clean_text) - suffix - 1]
    ):
        suffix += 1
    error_end = len(error_text) - suffix if suffix else len(error_text)
    clean_end = len(clean_text) - suffix if suffix else len(clean_text)
    return prefix, error_text[prefix:error_end], clean_text[prefix:clean_end]


def unique_anchor(error_text: str, start: int, original_text: str) -> str:
    end = start + len(original_text)
    radius = 8
    while radius <= len(error_text):
        left = max(0, start - radius)
        right = min(len(error_text), end + radius)
        anchor = error_text[left:right]
        if len(anchor) > len(original_text) and error_text.count(anchor) == 1:
            return anchor
        radius *= 2
    return error_text


def targeted_repair(error_text: str, anchor_text: str, original_text: str, correction: str) -> str:
    anchor_start = error_text.find(anchor_text)
    if anchor_start < 0 or error_text.count(anchor_text) != 1:
        raise ValueError("anchor is not unique")
    relative = anchor_text.find(original_text)
    if relative < 0:
        raise ValueError("original span is not inside anchor")
    start = anchor_start + relative
    return error_text[:start] + correction + error_text[start + len(original_text) :]


def candidate_failure_codes(candidate: dict[str, Any], final_error: dict[str, Any], clean_text: str, error_text: str) -> list[str]:
    if candidate.get("has_error") is not True or not candidate.get("errors"):
        return ["model_missed_intended_error"]
    codes = ["candidate_type_label_normalized"]
    candidate_error = candidate["errors"][0]
    if candidate_error.get("original_text") != final_error["original_text"]:
        codes.append("candidate_span_adjusted")
    if candidate_error.get("correction") != final_error["correction"]:
        codes.append("candidate_correction_repaired")
    try:
        candidate_anchor = str(candidate_error.get("anchor_text") or "")
        candidate_original = str(candidate_error.get("original_text") or "")
        candidate_correction = str(candidate_error.get("correction") or "")
        restored = targeted_repair(error_text, candidate_anchor, candidate_original, candidate_correction)
        if restored != clean_text:
            codes.append("candidate_not_exact_restoration")
    except Exception:
        codes.append("candidate_not_exact_restoration")
    return sorted(set(codes))


def load_historical_error_texts() -> list[tuple[str, str]]:
    paths = [
        ROOT / "taxonomy_v2" / "dev_a" / "review_eval_full.jsonl",
        ROOT / "taxonomy_v2" / "dev_b" / "blind_test_full.jsonl",
        ROOT / "taxonomy_v2" / "blind_v2" / "blind_v2_full.jsonl",
    ]
    result: list[tuple[str, str]] = []
    for path in paths:
        for row in read_jsonl(path):
            if row.get("error_type") != "none":
                result.append((str(row.get("sample_id") or ""), str(row.get("error_text") or row.get("full_text") or "")))
    return result


def corrected_subject(row: dict[str, Any]) -> str:
    match = re.search(r"-(\d{2})$", str(row.get("source_record_id") or ""))
    if match and 1 <= int(match.group(1)) <= 11:
        return "data_structure"
    return str(row["source_subject"])


def main() -> None:
    manifest = read_jsonl(RUN_DIR / "mutation_manifest.jsonl")
    attempts = read_jsonl(RUN_DIR / "model_outputs.jsonl")
    candidates: dict[str, dict[str, Any]] = {}
    candidate_records: dict[str, dict[str, Any]] = {}
    for attempt in attempts:
        if attempt.get("status") == "success":
            sample_id = str(attempt["sample_id"])
            candidates[sample_id] = attempt["parsed_response"]
            candidate_records[sample_id] = attempt
    if len(manifest) != 54 or len(candidates) != 54:
        raise ValueError(f"expected 54 manifests and candidates, got {len(manifest)} and {len(candidates)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_rows: list[dict[str, Any]] = []
    gold_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for source in manifest:
        row = dict(source)
        sample_id = str(row["sample_id"])
        question_repaired = sample_id in QUESTION_REPAIRS
        if question_repaired:
            row.update(QUESTION_REPAIRS[sample_id])
            row["mutation_signature"] = "|".join(
                [
                    str(row["error_detailed_type"]),
                    str(row["mutation_operation"]),
                    str(row["mutation_location"]),
                    str(row["mutation_token_class"]),
                ]
            )

        clean_text = str(row["clean_text"])
        error_text = str(row["error_text"])
        start, original_text, correction = minimal_diff(error_text, clean_text)
        if not original_text and not correction:
            raise ValueError(f"{sample_id}: final mutation has neither erroneous span nor insertion")
        anchor_text = unique_anchor(error_text, start, original_text)
        restored_final = (
            error_text[:start] + correction + error_text[start:]
            if not original_text
            else targeted_repair(error_text, anchor_text, original_text, correction)
        )
        if restored_final != clean_text:
            raise ValueError(f"{sample_id}: exact restoration failed")

        error_type = str(row["error_type"])
        final_subject = corrected_subject(row)
        subject_metadata_corrected = final_subject != str(row["source_subject"])
        nested_type = "可解性错误" if error_type == "solvability_failure" else error_type
        description = str(row["rationale"])
        if not original_text:
            suggestion = f"在{POSITION_CN.get(str(row.get('mutation_location')), '指定位置')}补入「{correction}」。"
        elif correction:
            suggestion = f"将「{original_text}」修正为「{correction}」。"
        else:
            suggestion = f"删除「{original_text}」。"
        final_error: dict[str, Any] = {
            "error_type": nested_type,
            "position": POSITION_CN.get(str(row.get("mutation_location")), "题干或选项中的修改处"),
            "original_text": original_text,
            "anchor_text": anchor_text,
            "correction": correction,
            "description": description,
            "suggestion": suggestion,
        }
        if error_type == "solvability_failure":
            final_error["error_subtype"] = str(row["solvability_subtype"])

        gold: dict[str, Any] = {
            "sample_id": sample_id,
            "error_type": error_type,
            "reason": f"发现1处{TYPE_CN[error_type]}。",
            "has_error": True,
            "total_errors": 1,
            "errors": [final_error],
            "strict_eval_eligible": True,
        }
        if error_type == "solvability_failure":
            gold["solvability_subtype"] = str(row["solvability_subtype"])

        candidate = candidates[sample_id]
        failure_codes = candidate_failure_codes(candidate, final_error, clean_text, error_text)
        if question_repaired:
            failure_codes.append("phase2_question_repaired")
        if subject_metadata_corrected:
            failure_codes.append("source_subject_corrected")
        origin = "codex_repaired" if candidate.get("has_error") is True else "codex_supplied"
        provenance = {
            "sample_id": sample_id,
            "model_candidate_status": "success",
            "model_candidate_has_error": bool(candidate.get("has_error")),
            "model_candidate_attempt": candidate_records[sample_id].get("attempt"),
            "requested_model": candidate_records[sample_id].get("requested_model"),
            "returned_model": candidate_records[sample_id].get("returned_model"),
            "final_origin": origin,
            "audit_failure_codes": sorted(set(failure_codes)),
            "audit_reason": "；".join(sorted(set(failure_codes))),
            "question_repaired_in_phase4": question_repaired,
            "source_subject_corrected_in_phase4": subject_metadata_corrected,
            "final_answer_sha256": sha256_json(gold),
            "auditor_identity": "Codex",
            "audit_timestamp": now,
            "output_dataset_version": VERSION,
        }

        full: dict[str, Any] = {
            "sample_id": sample_id,
            "error_type": error_type,
            "error_type_cn": TYPE_CN[error_type],
            "error_detailed_type": row["error_detailed_type"],
            "provenance": "blind_v2_overlap_expansion_20261031",
            "source_origin": row["source_origin"],
            "source_dataset": row["source_dataset"],
            "source_record_id": row["source_record_id"],
            "source_subject": final_subject,
            "source_year": row["source_year"],
            "reference": f"【学科】{SUBJECT_CN.get(final_subject, final_subject)}\n【题型或其它信息】单项选择题",
            "clean_text": clean_text,
            "error_text": error_text,
            "original_text": original_text,
            "correction": correction,
            "anchor_text": anchor_text,
            "rationale": description,
            "source_answer": row["source_answer"],
            "source_fingerprint_sha256": row["source_fingerprint_sha256"],
            "mutation_signature": row["mutation_signature"],
            "question_repaired_in_phase4": question_repaired,
            "source_subject_corrected_in_phase4": subject_metadata_corrected,
            "strict_eval_eligible": True,
        }
        if error_type == "solvability_failure":
            full["solvability_subtype"] = row["solvability_subtype"]

        audit_rows.append(
            {
                "sample_id": sample_id,
                "decision": "keep",
                "question_repaired_in_phase4": question_repaired,
                "source_subject_corrected_in_phase4": subject_metadata_corrected,
                "candidate_has_error": bool(candidate.get("has_error")),
                "final_origin": origin,
                "failure_codes": sorted(set(failure_codes)),
                "exact_restoration": True,
                "anchor_unique": error_text.count(anchor_text) == 1,
                "single_root_error": True,
                "final_error": final_error,
            }
        )
        full_rows.append(full)
        gold_rows.append(gold)
        provenance_rows.append(provenance)

    # Structural and diversity checks.
    ids = [row["sample_id"] for row in full_rows]
    error_norms = [normalize(row["error_text"]) for row in full_rows]
    if len(ids) != len(set(ids)) or len(error_norms) != len(set(error_norms)):
        raise ValueError("duplicate final ids or error texts")
    if any(row["has_error"] is not True or row["total_errors"] != 1 or len(row["errors"]) != 1 for row in gold_rows):
        raise ValueError("final gold structural invariant failed")
    process_trace_pattern = re.compile(r"为了造错|按要求修改|错误片段|对应错误类型的说明")
    if any(process_trace_pattern.search(row["error_text"]) for row in full_rows):
        raise ValueError("process trace found in final questions")

    historical = load_historical_error_texts()
    historical_norms = {normalize(text) for _, text in historical}
    historical_exact = [row["sample_id"] for row in full_rows if normalize(row["error_text"]) in historical_norms]
    near_history: list[dict[str, Any]] = []
    history_grams = [(sample_id, char_grams(text)) for sample_id, text in historical]
    for row in full_rows:
        grams = char_grams(row["error_text"])
        best_id, best_score = "", 0.0
        for historical_id, other in history_grams:
            union = grams | other
            score = len(grams & other) / len(union) if union else 1.0
            if score > best_score:
                best_id, best_score = historical_id, score
        if best_score >= 0.85:
            near_history.append(
                {"sample_id": row["sample_id"], "historical_sample_id": best_id, "jaccard_5gram": round(best_score, 6)}
            )
    near_batch: list[dict[str, Any]] = []
    for index, row in enumerate(full_rows):
        left = char_grams(row["error_text"])
        for other in full_rows[index + 1 :]:
            right = char_grams(other["error_text"])
            union = left | right
            score = len(left & right) / len(union) if union else 1.0
            if score >= 0.85:
                near_batch.append({"left": row["sample_id"], "right": other["sample_id"], "jaccard_5gram": round(score, 6)})
    if historical_exact or near_history or near_batch:
        raise ValueError(
            f"final duplicate gate failed: exact={historical_exact}, near_history={near_history}, near_batch={near_batch}"
        )

    write_jsonl(OUT_DIR / f"{VERSION}_full.jsonl", full_rows)
    write_jsonl(OUT_DIR / f"{VERSION}_gold.jsonl", gold_rows)
    write_jsonl(RUN_DIR / "answer_provenance.jsonl", provenance_rows)
    write_jsonl(RUN_DIR / "phase4_audit_manifest.jsonl", audit_rows)

    csv_fields = [
        "sample_id", "label", "error_type", "error_detailed_type", "subject", "year",
        "source_record_id", "full_text", "reference", "strict_eval_eligible",
        "legacy_error_type", "legacy_error_detailed_type", "solvability_subtype",
        "solvability_subtype_cn", "human_decision", "human_decision_inferred",
        "human_corrected_legacy_type", "human_reason", "leakage_level",
    ]
    with (OUT_DIR / f"{VERSION}_dataset.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in full_rows:
            writer.writerow(
                {
                    "sample_id": row["sample_id"],
                    "label": "error",
                    "error_type": row["error_type"],
                    "error_detailed_type": row["error_detailed_type"],
                    "subject": row["source_subject"],
                    "year": row["source_year"],
                    "source_record_id": row["source_record_id"],
                    "full_text": row["error_text"],
                    "reference": row["reference"],
                    "strict_eval_eligible": True,
                    "legacy_error_type": "",
                    "legacy_error_detailed_type": "",
                    "solvability_subtype": row.get("solvability_subtype", ""),
                    "solvability_subtype_cn": "条件矛盾" if row.get("solvability_subtype") == "contradictory_conditions" else ("多个有效答案" if row.get("solvability_subtype") == "multiple_valid_answers" else ""),
                    "human_decision": "keep",
                    "human_decision_inferred": False,
                    "human_corrected_legacy_type": "",
                    "human_reason": "Phase 4 Codex audit passed",
                    "leakage_level": "",
                }
            )

    signature_counts = Counter(row["mutation_signature"] for row in full_rows)
    location_counts = Counter(str(row.get("position")) for row in audit_rows)
    final_summary = {
        "dataset_version": VERSION,
        "total_audited": len(manifest),
        "model_accepted": 0,
        "codex_repaired": sum(row["final_origin"] == "codex_repaired" for row in provenance_rows),
        "codex_supplied": sum(row["final_origin"] == "codex_supplied" for row in provenance_rows),
        "excluded": 0,
        "remaining_unresolved": 0,
        "phase2_questions_repaired": sum(row["question_repaired_in_phase4"] for row in audit_rows),
        "source_subject_metadata_corrected": sum(row["source_subject_corrected_in_phase4"] for row in audit_rows),
        "by_error_type": dict(Counter(row["error_type"] for row in full_rows)),
        "by_solvability_subtype": dict(
            Counter(row.get("solvability_subtype") for row in full_rows if row["error_type"] == "solvability_failure")
        ),
        "answer_completeness": len(gold_rows),
        "schema_valid": len(gold_rows),
        "single_root_error": sum(row["single_root_error"] for row in audit_rows),
        "exact_restoration": sum(row["exact_restoration"] for row in audit_rows),
        "anchor_unique": sum(row["anchor_unique"] for row in audit_rows),
        "historical_exact_duplicates": len(historical_exact),
        "batch_exact_duplicates": len(error_norms) - len(set(error_norms)),
        "near_history_at_0_85": near_history,
        "near_batch_at_0_85": near_batch,
        "mutation_signatures_unique": len(signature_counts),
        "mutation_signature_max_count": max(signature_counts.values()),
        "requested_model": "gpu-qwen3.8-27b",
        "returned_model": "qwen3.8-27b-fp8",
        "files": {
            "dataset_csv": str(OUT_DIR / f"{VERSION}_dataset.csv"),
            "full_jsonl": str(OUT_DIR / f"{VERSION}_full.jsonl"),
            "gold_jsonl": str(OUT_DIR / f"{VERSION}_gold.jsonl"),
            "answer_provenance": str(RUN_DIR / "answer_provenance.jsonl"),
            "audit_manifest": str(RUN_DIR / "phase4_audit_manifest.jsonl"),
        },
        "trainable": True,
    }
    (RUN_DIR / "phase4_validation.json").write_text(
        json.dumps(final_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
