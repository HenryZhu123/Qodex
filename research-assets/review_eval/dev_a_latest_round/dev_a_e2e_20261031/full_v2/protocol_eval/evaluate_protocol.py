#!/usr/bin/env python3
"""Qodex evaluation protocol v1.0.0 for the Dev A full_v2 run.

Implements exam-checker-evaluation-system.md:
  1. empty-value normalisation
  2. duplicate prediction collapse (DUP, counts nothing)
  3. deterministic pre-checks (empty GT / empty prediction / incompatible type)
  4. one-to-one semantic match by a Judge
  5. modification validity check
  6. TP/FP/TN/FN counting with the "no double penalty" rule
  7. metrics over evaluation_status=success only

Outputs per_question.jsonl, metrics.json, report table.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
FULL_V2 = SCRIPT_DIR.parent
REVIEW_ROOT = SCRIPT_DIR.parents[3]

RESULTS = FULL_V2 / "rescored" / "results.jsonl"
DATASET = REVIEW_ROOT / "taxonomy_v2" / "dev_a" / "strict" / "review_eval_dataset_v2.csv"
ENV_FILE = Path(r"D:\Code\hku\LLM\hku_agent\pi-coding-agent\services\exam-checker\.env.local")

TYPE_CN = {
    "typo": "错别字",
    "punctuation": "标点符号错误",
    "option_structure": "选项结构错误",
    "type_mismatch": "题目与题型不一致",
    "solvability_failure": "信息缺失/题目无解",
    "ambiguity": "语义不清",
    "answer_leakage": "答案泄露",
    "factual_logical": "事实/逻辑错误",
}
EMPTY_VALUES = {"", "[]", "nan", "none", "null", "无", "['nan']", '["nan"]'}

SYSTEM = "你是 Qodex 试卷审校评估 Judge。严格按给定规范判定，只输出 JSON。"

PROMPT = """【评估规范要点】
1. 一条 Prediction 记为 TP 必须同时满足：位置/错误事实命中 GT；修改或处理方案成立，且没有引入明确的新错误。
2. 修改措辞与 GT 不同但同样正确 → TP；类型标签不同但错误事实一致 → TP；无法唯一还原时使用占位符也算合理处理。
3. 位置命中但修改不成立、未解决问题、破坏题意或引入新错误 → FP。
4. 一个 GT 最多被一条 Prediction 计入 TP；指向同一位置/同一错误事实的重复报告 → DUP，不计入任何量。
5. 不双罚：整题没有任何 TP 时，FN 必须为 0。
6. TN 只在 GT 为空且 Prediction 为空时为 1，本题 GT 非空，故 TN=0。

【题目全文】
{text}

【GT】
错误类型：{gt_type}
可独立修复的错误项数量：{gt_count}
（GT 只标注类型，未给出具体位置与参考改法，请据题面自行判断该类型错误是否真实存在。）

【Prediction 列表（共 {pred_count} 条）】
{predictions}

【输出】
逐条给出判定，并汇总计数。FN 只能是 {fn_rule}。
只输出 JSON：
{{"matches":[{{"id":"P1","verdict":"TP或FP或DUP","reason":"不超过40字"}}],"TP":整数,"FP":整数,"FN":整数,"reason":"不超过50字的总体说明"}}"""


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            values[name.strip()] = value.strip()
    return values


def norm(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in EMPTY_VALUES else text


def collapse_duplicates(items: list[dict]) -> tuple[list[dict], list[dict]]:
    kept: list[dict] = []
    dups: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            norm(item.get("error_type")),
            norm(item.get("original_text")),
            norm(item.get("correction")),
        )
        if key in seen:
            dups.append(item)
        else:
            seen.add(key)
            kept.append(item)
    return kept, dups


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


async def judge_question(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    base: str,
    key: str,
    model: str,
    unit: dict,
    max_tokens: int,
) -> dict:
    rendered = "\n".join(
        f"[{item['pid']}] 类型：{item.get('error_type') or '未标注'} | 原文：「{norm(item.get('original_text'))[:60]}」"
        f" | 位置：{norm(item.get('position'))[:40]} | 建议：{norm(item.get('correction'))[:120]}"
        f" | 说明：{norm(item.get('description'))[:80]}"
        for item in unit["predictions"]
    )
    prompt = PROMPT.format(
        text=unit["text"][:4000],
        gt_type=TYPE_CN.get(unit["gt_type"], unit["gt_type"] or "未知"),
        gt_count=unit["gt_count"],
        pred_count=len(unit["predictions"]),
        predictions=rendered,
        fn_rule="0 或 " + str(unit["gt_count"]),
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    last = ""
    async with semaphore:
        for attempt in range(1, 4):
            try:
                response = await client.post(
                    f"{base.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                if response.status_code == 400 and "response_format" in body:
                    body.pop("response_format")
                    continue
                if response.status_code != 200:
                    last = f"HTTP {response.status_code}: {response.text[:150]}"
                    await asyncio.sleep(attempt * 2)
                    continue
                parsed = parse_json(response.json()["choices"][0]["message"].get("content") or "")
                if parsed is None:
                    last = "parse_fail"
                    await asyncio.sleep(attempt * 2)
                    continue
                tp = int(parsed.get("TP", 0))
                fp = int(parsed.get("FP", 0))
                fn = int(parsed.get("FN", 0))
                reason = str(parsed.get("reason", ""))[:200]
                matches = parsed.get("matches") or []
                # protocol constraints (§11.3)
                if min(tp, fp, fn) < 0:
                    last = "negative_count"
                    continue
                if tp == 0 and fp > 0 and fn != 0:
                    fn = 0
                if tp == 0 and fp == 0 and fn == 0 and unit["predictions"]:
                    last = "all_zero_with_predictions"
                    continue
                return {
                    "sample_id": unit["sample_id"],
                    "evaluation_status": "success",
                    "TP": tp,
                    "FP": fp,
                    "TN": 0,
                    "FN": fn,
                    "reason": reason,
                    "matches": matches,
                    "judge_error": None,
                }
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(attempt * 2)
    return {
        "sample_id": unit["sample_id"],
        "evaluation_status": "llm_call_failed",
        "TP": None,
        "FP": None,
        "TN": None,
        "FN": None,
        "reason": "",
        "matches": [],
        "judge_error": last,
    }


async def run(args: argparse.Namespace) -> int:
    env = load_env()
    base = env["EXAM_CHECKER_REVIEW_LLM_BASE_URL"]
    key = env["EXAM_CHECKER_REVIEW_LLM_API_KEY"]
    with DATASET.open(encoding="utf-8-sig", newline="") as handle:
        gt = {row["sample_id"]: row for row in csv.DictReader(handle)}
    records = [
        json.loads(line)
        for line in RESULTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    units: list[dict] = []
    precomputed: dict[str, dict] = {}
    for record in records:
        sid = record["sample_id"]
        row = gt[sid]
        is_clean = row["label"] == "clean"
        raw = [
            {
                "pid": f"P{i}",
                "error_type": error.get("error_type"),
                "original_text": error.get("original_text"),
                "position": error.get("position"),
                "correction": error.get("correction"),
                "description": error.get("description"),
            }
            for i, error in enumerate(
                [e for check in (record.get("checks") or []) for e in (check.get("errors") or [])],
                start=1,
            )
        ]
        preds = [p for p in raw if norm(p.get("error_type")) or norm(p.get("original_text"))]
        kept, dups = collapse_duplicates(preds)
        status = record["status"]

        if status == "UNRESOLVED":
            precomputed[sid] = {
                "sample_id": sid,
                "evaluation_status": "skipped_timeout",
                "TP": None,
                "FP": None,
                "TN": None,
                "FN": None,
                "reason": "上游任务失败，按 §12 不进入指标",
                "raw_predictions": raw,
                "dup_predictions": len(dups),
            }
            continue
        if not kept and is_clean:
            precomputed[sid] = {
                "sample_id": sid, "evaluation_status": "success",
                "TP": 0, "FP": 0, "TN": 1, "FN": 0,
                "reason": "GT 空且 Prediction 空", "raw_predictions": raw, "dup_predictions": len(dups),
            }
            continue
        if not kept and not is_clean:
            mn = 1
            precomputed[sid] = {
                "sample_id": sid, "evaluation_status": "success",
                "TP": 0, "FP": 0, "TN": 0, "FN": mn,
                "reason": "Prediction 空，GT 未命中", "raw_predictions": raw, "dup_predictions": len(dups),
            }
            continue
        if kept and is_clean:
            precomputed[sid] = {
                "sample_id": sid, "evaluation_status": "success",
                "TP": 0, "FP": len(kept), "TN": 0, "FN": 0,
                "reason": "无错题发生误报", "raw_predictions": raw, "dup_predictions": len(dups),
            }
            continue
        units.append(
            {
                "sample_id": sid,
                "text": row["full_text"],
                "gt_type": row["error_type"],
                "gt_count": 1,
                "predictions": kept,
                "dup_count": len(dups),
                "raw": raw,
            }
        )

    if args.limit:
        units = units[: args.limit]
    print(f"precomputed={len(precomputed)} judge_pending={len(units)}", flush=True)

    out_path = SCRIPT_DIR / "per_question.jsonl"
    done: dict[str, dict] = {}
    if args.resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("evaluation_status") == "success":
                    done[row["sample_id"]] = row
    pending = [u for u in units if u["sample_id"] not in done]
    print(f"already_judged={len(done)} pending={len(pending)}", flush=True)

    semaphore = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    mode = "a" if done else "w"
    with out_path.open(mode, encoding="utf-8") as handle:
        async with httpx.AsyncClient(timeout=args.timeout) as client:
            async def worker(unit: dict) -> None:
                result = await judge_question(
                    client, semaphore, base, key, args.model, unit, args.max_tokens
                )
                result["raw_predictions"] = unit["raw"]
                result["dup_predictions"] = unit["dup_count"]
                async with lock:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    handle.flush()
                    if result["evaluation_status"] == "success":
                        done[unit["sample_id"]] = result

            await asyncio.gather(*(worker(u) for u in pending))

    judged: list[dict] = []
    if out_path.exists():
        judged = [
            json.loads(line)
            for line in out_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    # a sample retried later supersedes its earlier failed row
    latest: dict[str, dict] = {}
    for row in judged:
        if row.get("evaluation_status") == "success" or row["sample_id"] not in latest:
            latest[row["sample_id"]] = row
    judged = list(latest.values())
    all_rows = list(precomputed.values()) + judged
    success = [r for r in all_rows if r["evaluation_status"] == "success"]

    totals = Counter()
    per_type: dict[str, Counter] = defaultdict(Counter)
    for row in success:
        sid = row["sample_id"]
        gold = gt[sid]
        key_t = "clean" if gold["label"] == "clean" else gold["error_type"]
        for field in ("TP", "FP", "TN", "FN"):
            totals[field] += row[field]
            per_type[key_t][field] += row[field]
        per_type[key_t]["samples"] += 1

    def metrics(c: Counter) -> dict:
        tp, fp, tn, fn = c["TP"], c["FP"], c["TN"], c["FN"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        beta2 = 5 * precision * recall / (4 * precision + recall) if (4 * precision + recall) else 0.0
        accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        return {
            "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": round(precision, 6), "recall": round(recall, 6),
            "f1": round(f1, 6), "f2": round(beta2, 6),
            "accuracy": round(accuracy, 6), "fpr": round(fpr, 6),
        }

    report = {
        "evaluation_protocol_version": "1.0.0",
        "dataset": DATASET.name,
        "judge_model": sorted({r.get("judge_model") for r in judged if r.get("judge_model")}) or [args.model],
        "questions_total": len(all_rows),
        "questions_scored": len(success),
        "excluded": [
            {"sample_id": r["sample_id"], "status": r["evaluation_status"], "error": r.get("judge_error")}
            for r in all_rows
            if r["evaluation_status"] != "success"
        ],
        "overall": metrics(totals),
        "by_type": {name: metrics(counter) | {"samples": counter["samples"]} for name, counter in sorted(per_type.items())},
    }
    (SCRIPT_DIR / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    print(json.dumps({"scored": len(success), "excluded": len(report["excluded"])}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
