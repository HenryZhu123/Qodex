#!/usr/bin/env python3
"""Render the protocol v1.0.0 evaluation into the report required by §14."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FULL_V2 = SCRIPT_DIR.parent
RUN_DIR = FULL_V2.parent
REVIEW_ROOT = SCRIPT_DIR.parents[3]
AGENT_ROOT = REVIEW_ROOT.parents[1]

METRICS = SCRIPT_DIR / "metrics.json"
DATASET = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset_v2.csv"
MANIFEST = FULL_V2 / "run_manifest_v2.json"
OUT = SCRIPT_DIR / "dev_a_protocol_report.md"

ORDER = [
    "typo",
    "punctuation",
    "option_structure",
    "type_mismatch",
    "solvability_failure",
    "ambiguity",
    "answer_leakage",
    "factual_logical",
    "clean",
]
LABEL = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项结构错误",
    "type_mismatch": "题目与题型不一致",
    "solvability_failure": "信息缺失/题目无解",
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
    "clean": "无错样本",
}


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def main() -> None:
    metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dataset_sha = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    overall = metrics["overall"]
    by_type = metrics["by_type"]
    clean = by_type.get("clean", {})
    clean_fpr = clean["FP"] / (clean["FP"] + clean["TN"]) if (clean["FP"] + clean["TN"]) else 0.0

    lines: list[str] = []
    add = lines.append
    add("# Dev A 审校结果质量评估报告（评估协议 v1.0.0）")
    add("")
    add("依据 `exam-checker-evaluation-system.md`（Qodex 混淆矩阵计数规范）对 Dev A strict 全量结果重新评分。"
        "评估粒度为 **Prediction 级**，与此前题级 conservative / exact-type 指标不是同一口径，不可混用。")
    add("")
    add("## 1. 运行与版本信息（§14）")
    add("")
    add("| 项 | 值 |")
    add("| --- | --- |")
    add(f"| 被测模型 | `{manifest['configuration']['review_model']}` |")
    add(f"| 被测端点 | `{manifest['configuration']['review_base_url']}` |")
    add(f"| 解码参数 | temperature 0，seed 42，max_tokens {manifest['configuration']['review_max_tokens']} |")
    add(f"| reviewer 内部并发 | {manifest['configuration']['reviewer_max_concurrency']} |")
    add(f"| Prompt Profile | `reviewer-prompt/qwen38_27b`，24 个文件哈希在 v1 manifest 中校验 24/24 匹配 |")
    add(f"| 数据集 | `{DATASET.name}`，SHA-256 `{dataset_sha}` |")
    add(f"| 数据集构成 | 318 题：错误 227、无错 91 |")
    add(f"| Judge 模型 | {', '.join(metrics['judge_model'])} |")
    add(f"| 评估协议版本 | `{metrics['evaluation_protocol_version']}` |")
    add(f"| 评分样本 / 排除样本 | {metrics['questions_scored']} / {len(metrics['excluded'])} |")
    add("")
    add("## 2. 全量汇总指标（§13）")
    add("")
    add("| 指标 | 值 | 计数 |")
    add("| --- | ---: | --- |")
    add(f"| Precision | **{pct(overall['precision'])}** | TP {overall['TP']} / (TP {overall['TP']} + FP {overall['FP']}) |")
    add(f"| Recall | **{pct(overall['recall'])}** | TP {overall['TP']} / (TP {overall['TP']} + FN {overall['FN']}) |")
    add(f"| F1 | **{pct(overall['f1'])}** | — |")
    add(f"| F2 | {pct(overall['f2'])} | 更看重 Recall |")
    add(f"| Accuracy | {pct(overall['accuracy'])} | (TP {overall['TP']} + TN {overall['TN']}) / 全部 |")
    add(f"| FPR（协议公式） | {pct(overall['fpr'])} | FP {overall['FP']} / (FP {overall['FP']} + TN {overall['TN']}) |")
    add(f"| **无错题 FPR** | **{pct(clean_fpr)}** | 无错题中 {clean['FP']}/{clean['FP'] + clean['TN']} 被误报 |")
    add("")
    add("> `Accuracy` 与协议公式的 `FPR` 混合了「错误项级」的 FP 和「题目级」的 TN（§13.2 已提示该限制），"
        "不应作为主要判据。**无错题 FPR** 才是可解释的误报率。")
    add("")
    add("## 3. 分类型混淆矩阵（§14 推荐表）")
    add("")
    add("| 错误类型 | TP | TN | FP | FN | Precision | Recall | F1 | F2 | FPR | 成功样本 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for key in ORDER:
        value = by_type.get(key)
        if not value:
            continue
        fpr_text = pct(value["fpr"]) if value["TN"] else "—"
        add(
            f"| {LABEL[key]} | {value['TP']} | {value['TN']} | {value['FP']} | {value['FN']} | "
            f"{pct(value['precision'])} | {pct(value['recall'])} | {pct(value['f1'])} | "
            f"{pct(value['f2'])} | {fpr_text} | {value['samples']} |"
        )
    add("")
    add("> 有错类的 TN 恒为 0（该题必然有 GT），因此按 §13.1 公式 `FP/(FP+TN)` 会恒等于 100%，不具信息量，故记作 —。")
    add("")
    add("## 4. 排除样本（§12）")
    add("")
    add("| 样本 | evaluation_status | 说明 |")
    add("| --- | --- | --- |")
    for item in metrics["excluded"]:
        add(f"| `{item['sample_id']}` | `{item['status']}` | {(item.get('error') or '上游任务失败')[:60]} |")
    add("")
    add(f"排除率 {len(metrics['excluded'])}/{metrics['questions_total']} = "
        f"{len(metrics['excluded']) / metrics['questions_total']:.2%}，这些样本未进入任何指标。")
    add("")
    add("## 5. 结论")
    add("")
    add(f"在 Prediction 级、官方协议口径下，本系统表现为 **Precision {pct(overall['precision'])}、"
        f"Recall {pct(overall['recall'])}、F1 {pct(overall['f1'])}**。")
    add("")
    add("- 强项：答案泄露、题目与题型不一致、选项结构、信息缺失，Precision 与 Recall 均在 76% 以上。")
    add("- 短板：语义不清（Recall 约 41%）、错别字（FP 18 条，占全部误报的三分之一以上）。")
    add("- 无错题误报率 6.6%（6/91），但 Wilson 上界约 13.6%，样本量不足以断言稳定低于 10%。")
    add("")
    add("## 6. 产物")
    add("")
    add("| 文件 | 内容 |")
    add("| --- | --- |")
    add("| `per_question.jsonl` | 每题的 GT、原始 Prediction、去重后 Prediction、TP/FP/TN/FN、reason、evaluation_status |")
    add("| `metrics.json` | 全量与分类型指标、排除清单 |")
    add("| `evaluate_protocol.py` | 按 §16 伪代码实现的评估器 |")
    add("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
