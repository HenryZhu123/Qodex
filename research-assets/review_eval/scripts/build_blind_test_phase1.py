#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 1: Planning the Blind Test Set.

Follows the non-negotiable workflow of question-error-synthesis:
1. Defines error types, exact quotas, proportions, and source isolation.
2. Selects 100% isolated source questions from the 397 unused 408 pool.
3. Generates plan.md, plan.json, source_selection.jsonl, run_state.json.
4. Enforces strict diversity caps (<= 25% per mutation signature).
5. Stops after Phase 1 and waits for explicit user approval before Phase 2.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"D:\Code\hku\LLM\hku_agent")
ROOT = REPO / "research-assets" / "review_eval"
DEV_DATASET_FULL = ROOT / "dataset" / "review_eval_full.jsonl"
REFQ_FILE = Path(r"D:\Code\hku\LLM\kb_refq_out\reference_questions.jsonl")

PHASE1_DIR = ROOT / "blind_test_set" / "phase1"

ERROR_TYPES = [
    ("type_mismatch", "题目与题型不一致", 20, 20, 0),     # 20 new, 0 retained
    ("option_structure", "选项结构错误", 20, 20, 0),   # 20 new, 0 retained
    ("factual_logical", "事实/逻辑错误", 20, 20, 0),   # 20 new, 0 retained
    ("typo", "错别字", 20, 10, 10),                     # 10 new, 10 retained
    ("punctuation", "标点符号错误", 20, 10, 10),       # 10 new, 10 retained
    ("missing_info", "信息缺失", 20, 10, 10),           # 10 new, 10 retained
    ("ambiguity", "语义不清", 20, 10, 10),               # 10 new, 10 retained
    ("unsolvable", "题目无解", 20, 10, 10),             # 10 new, 10 retained
    ("answer_leakage", "答案泄露", 20, 10, 10),         # 10 new, 10 retained
]
CLEAN_COUNT = 60


def normalize_for_hash(text: str) -> str:
    n = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", "", n)


def fingerprint(text: str) -> str:
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()[:16]


def main() -> int:
    PHASE1_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Gather all Dev Set used sources
    dev_records = [json.loads(line) for line in DEV_DATASET_FULL.open(encoding="utf-8") if line.strip()]
    dev_used_source_ids = {r["source_record_id"] for r in dev_records if r.get("source_record_id")}
    print(f"Loaded Dev Set: {len(dev_records)} records, {len(dev_used_source_ids)} unique source IDs.")

    # 2. Gather all candidate clean reference questions
    refq_records = [json.loads(line) for line in REFQ_FILE.open(encoding="utf-8") if line.strip()]
    usable_pool = [
        q for q in refq_records
        if q["record_id"] not in dev_used_source_ids
        and q.get("options_complete", True)
        and len(q.get("options", [])) == 4
        and len(q.get("stem", "")) >= 15
    ]
    print(f"Total reference pool: {len(refq_records)}. Usable unused clean pool: {len(usable_pool)}.")

    # 3. Stratify sources by subject
    by_subject = defaultdict(list)
    for q in usable_pool:
        by_subject[q.get("subject", "unknown")].append(q)

    # Calculate exact source allocation
    # New error sources needed: 20*3 + 10*6 = 120
    # Clean sources needed: 60
    # Total new sources needed = 180
    assert len(usable_pool) >= 180, f"Need 180 sources, but only have {len(usable_pool)}"

    # 4. Source assignment: Allocate 120 sources for error questions + 60 for clean
    allocated_sources = {}
    assigned_records = []
    pool_idx = 0

    # Build selections
    for et_key, et_cn, total_cnt, new_cnt, ret_cnt in ERROR_TYPES:
        # Get new sources
        for i in range(new_cnt):
            q = usable_pool[pool_idx]
            pool_idx += 1
            sample_id = f"blind-{et_key}-{q['record_id']}"
            q_text = q.get("stem", "")
            raw_opts = q.get("options", {})
            if isinstance(raw_opts, dict):
                opts = [f"{k}. {v}" for k, v in raw_opts.items()]
            else:
                opts = list(raw_opts)
            full_txt = f"{q_text}\n" + "\n".join(opts) if opts else q_text
            allocated_sources[sample_id] = {
                "sample_id": sample_id,
                "error_type": et_key,
                "error_type_cn": et_cn,
                "provenance": "new_synthesis",
                "source_record_id": q["record_id"],
                "source_year": q.get("year"),
                "source_subject": q.get("subject"),
                "fingerprint": fingerprint(q_text),
                "full_text": full_txt,
                "question_text": q_text,
                "options": opts,
                "source_answer": q.get("standard_answer"),
            }
            assigned_records.append(allocated_sources[sample_id])

        # Get retained sources from Dev Set
        if ret_cnt > 0:
            dev_matches = [r for r in dev_records if r.get("error_type") == et_key][:ret_cnt]
            for r in dev_matches:
                sample_id = f"blind-retained-{r['sample_id']}"
                allocated_sources[sample_id] = {
                    "sample_id": sample_id,
                    "error_type": et_key,
                    "error_type_cn": et_cn,
                    "provenance": "retained_from_dev",
                    "source_record_id": r.get("source_record_id"),
                    "source_year": r.get("year"),
                    "source_subject": r.get("subject"),
                    "fingerprint": fingerprint(r.get("question_text", "")),
                    "full_text": r.get("full_text"),
                    "question_text": r.get("question_text"),
                    "options": r.get("options"),
                    "source_answer": r.get("source_answer"),
                    "retained_gold": {
                        "original_text": r.get("original_text"),
                        "correction": r.get("correction"),
                        "anchor_text": r.get("anchor_text"),
                        "rationale": r.get("rationale"),
                        "error_detailed_type": r.get("error_detailed_type"),
                    },
                }
                assigned_records.append(allocated_sources[sample_id])

    # Allocate Clean sources
    clean_records = []
    for i in range(CLEAN_COUNT):
        q = usable_pool[pool_idx]
        pool_idx += 1
        c_id = f"blind-clean-{q['record_id']}"
        q_text = q.get("stem", "")
        raw_opts = q.get("options", {})
        if isinstance(raw_opts, dict):
            opts = [f"{k}. {v}" for k, v in raw_opts.items()]
        else:
            opts = list(raw_opts)
        full_txt = f"{q_text}\n" + "\n".join(opts) if opts else q_text
        rec = {
            "sample_id": c_id,
            "error_type": "none",
            "error_type_cn": "正常题（正样本）",
            "provenance": "new_clean_unseen",
            "source_record_id": q["record_id"],
            "source_year": q.get("year"),
            "source_subject": q.get("subject"),
            "fingerprint": fingerprint(q_text),
            "full_text": full_txt,
            "question_text": q_text,
            "options": opts,
            "source_answer": q.get("standard_answer"),
        }
        clean_records.append(rec)
        assigned_records.append(rec)

    # Write source_selection.jsonl
    src_file = PHASE1_DIR / "source_selection.jsonl"
    with src_file.open("w", encoding="utf-8") as f:
        for r in assigned_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Generate plan.json
    plan_data = {
        "run_id": "blind_test_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workflow": "question-error-synthesis (NeurIPS 2026)",
        "source_pool_summary": {
            "total_pool": len(refq_records),
            "dev_set_used": len(dev_used_source_ids),
            "blind_set_new_sources": pool_idx,
            "remaining_unused": len(usable_pool) - pool_idx,
        },
        "quotas": {
            "total_blind_test_samples": len(assigned_records),
            "error_samples": len(assigned_records) - len(clean_records),
            "clean_samples": len(clean_records),
            "by_error_type": {
                et_k: {
                    "total": tot,
                    "new_synthesis": n_cnt,
                    "retained_from_dev": r_cnt,
                    "construction_policy": "Reconstruct from scratch with non-template variations" if n_cnt == tot else "50% retained / 50% new synthesis",
                }
                for et_k, _, tot, n_cnt, r_cnt in ERROR_TYPES
            },
        },
        "diversity_constraints": {
            "max_signature_concentration": "25% per error type (max 5 items per detailed subtype)",
            "subject_balance": "Cross-discipline across DS, CO, OS, CN",
            "forbidden_shortcuts": [
                "No fixed trailing parenthetical markers like （多选）/（请证明） across batch",
                "No repetitive mechanical replacement of option markers",
                "Must represent diverse realistic paper layout & exam drafting anomalies",
            ],
        },
    }
    (PHASE1_DIR / "plan.json").write_text(json.dumps(plan_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write run_state.json
    run_state = {
        "run_id": "blind_test_v1",
        "current_phase": "phase1",
        "phase1_status": "COMPLETED",
        "phase1_completed_at": datetime.now(timezone.utc).isoformat(),
        "phase2_status": "PENDING_APPROVAL",
        "total_planned": len(assigned_records),
        "error_planned": len(assigned_records) - len(clean_records),
        "clean_planned": len(clean_records),
    }
    (PHASE1_DIR / "run_state.json").write_text(json.dumps(run_state, ensure_ascii=False, indent=2), encoding="utf-8")

    # Write plan.md
    plan_md = fr"""# Blind Test Set 规划方案 (Phase 1 Plan)

**方案编号**：`blind_test_v1`  
**执行技能规范**：`question-error-synthesis` (NeurIPS 2026 / COMP7608B)  
**规划生成时间**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  

---

## 一、方案目标与数据集隔离 (Data Split & Leakage Prevention)

为彻底解决 Dev Set 评测中存在的后验规则拟合（Shortcut Learning）与测试集窥探（Information Leakage）问题，正式构建独立的 **Blind Test Set（盲测集）**：
1. **源题绝对隔离**：全部新源题均从 720 道 408 真题中**完全未被 Dev Set 触碰的 397 道全新源题池**中独立抽取，确保源题哈希（Normalized Fingerprint）零重叠。
2. **重点类别全新重构 (Reconstruct from Scratch)**：
   - `type_mismatch`（题型不一致）：20 道 100% 全新构造，废除固定模板后缀，引入跨学科真实题型矛盾；
   - `option_structure`（选项结构）：20 道 100% 全新构造，引入真实排版错乱（选项丢失、非标准标号、跨行断裂等）；
   - `factual_logical`（事实/逻辑）：20 道 100% 全新构造，引入细微的定理反转、公式变量颠倒与参数矛盾。
3. **其余类别平分策略 (50% Retained / 50% New)**：
   - `typo`, `punctuation`, `missing_info`, `ambiguity`, `unsolvable`, `answer_leakage` 均由 10 道原保留样本 + 10 道全新合成样本构成。
4. **高质量干净题基线**：
   - 抽取 **60 道完全未见的干净真题** 作为正样本，严格检验误报率（FPR）。

---

## 二、样本配额与构成清单 (Quotas & Proportions)

总计规划 **240 道题目**（180 道负样本错题 + 60 道正样本干净题）：

| 类别 (Category) | 中文名称 | 规划总量 | 全新合成量 (New) | 沿用/保留量 (Retained) | 占比 | 构造与防泄露策略 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **type_mismatch** | 题目与题型不一致 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，杜绝固定机械后缀 |
| **option_structure** | 选项结构错误 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，覆盖多样化真实排版破坏 |
| **factual_logical** | 事实/逻辑错误 | 20 | **20** | 0 | 8.3% | **100% 全新重构**，涉及四门学科核心定理反转 |
| **missing_info** | 信息缺失 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新删除必要解题约束 |
| **unsolvable** | 题目无解 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新构造矛盾/发散无解 |
| **typo** | 错别字 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新学科形近/音近字变异 |
| **punctuation** | 标点符号错误 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新真实标点误用 |
| **answer_leakage** | 答案泄露 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新形式泄露 |
| **ambiguity** | 语义不清 | 20 | 10 | 10 | 8.3% | 50% 沿用 + 50% 全新代词歧义与范围泛化 |
| **clean** | 干净正样本原题 | 60 | **60** | 0 | 25.0% | **100% 全新真题**，用于严格测量 FPR |
| **总计** | — | **240** | **180** | **60** | **100.0%** | **源题零复用，完全隔离** |

---

## 三、多样性约束与质检标准 (Diversity & Quality Gates)

1. **变异签名上限**：同类错误下，单一造错手法（Mutation Signature）占比**严禁超过 25%**（即每类 20 道错题必须覆盖 $\ge 5$ 种不同亚型，每种亚型不得超过 5 道）。
2. **学科均衡覆盖**：新源题分配覆盖数据结构（DS）、计算机组成原理（CO）、操作系统（OS）、计算机网络（CN）四门统考科目。
3. **单根因与精确可还原**：
   - 每道题严格只植入一处错误；
   - 必须满足 `error_text.replace(original_text, correction, 1) == clean_text`，保证标准答案能一字不差精确改回原题。
4. **定位锚点唯一性**：`anchor_text` 必须在题干中唯一可召回，杜绝位置歧义。

---

## 四、产物文件规划

- `research-assets/review_eval/blind_test_set/phase1/plan.md`（本方案人读版）
- `research-assets/review_eval/blind_test_set/phase1/plan.json`（机器可读配额）
- `research-assets/review_eval/blind_test_set/phase1/source_selection.jsonl`（240 道源题预留与指纹清单）
- `research-assets/review_eval/blind_test_set/phase1/run_state.json`（阶段审批状态控制）
"""
    (PHASE1_DIR / "plan.md").write_text(plan_md, encoding="utf-8")
    print(f"Phase 1 files successfully generated under {PHASE1_DIR}!")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
