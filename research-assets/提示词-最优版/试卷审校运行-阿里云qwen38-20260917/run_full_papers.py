"""Run the five complete papers with the selected eight 27B prompts.

All other built-in tasks and their think modes come from system-qwen38-27b-v1.
The source papers and production prompt profile are not modified.
"""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen


OUTPUT = Path(os.getenv("BEST_PROMPT_RUN_OUTPUT") or Path(__file__).resolve().parent)
PROMPTS = Path("/Users/softzephyr/Desktop/hyt-agent/提示词-最优版")
SOURCE = Path(
    os.getenv("BEST_PROMPT_SOURCE")
    or "/Users/softzephyr/Desktop/hyt-agent/外部数据源/完整试卷测试集"
)
RUN_ID = os.getenv("BEST_PROMPT_RUN_ID") or "aliyun-qwen38-27b-fullpapers-20260917"
EXPECTED_PAPERS = int(os.getenv("BEST_PROMPT_EXPECTED_PAPERS") or "5")
MODEL = "qwen3.8-27b"
BASE_PROFILE = "system-qwen38-27b-v1"
EXPECTED_NAMES = {
    "10题_实际10题_2024广西民族大学824西方科技史.pdf",
    "20题_实际20题_2024广西民族大学646普通物理.pdf",
    "40题档_实际39题_2023重庆理工大学816会计学原理A卷.pdf",
    "60题档_实际62题_641生物化学与分子生物学.docx",
    "180题档_实际190题_2019昆明理工大学628西医综合A卷.doc",
}
SELECTED = {
    "typo_check": ("错别字_disabled.txt", "disabled"),
    "options_check": ("选项错误_disabled.txt", "disabled"),
    "ambiguity_check": ("语义不清_disabled.txt", "disabled"),
    "punctuation_check": ("标点符号_explicit.txt", "explicit"),
    "mismatch_check": ("题目和题型不一致_disabled.txt", "disabled"),
    "missing_check": ("信息缺失_disabled.txt", "disabled"),
    "unsolvability_check": ("题目无解_explicit.txt", "explicit"),
    "answer_leak_check": ("答案泄露_explicit.txt", "explicit"),
}


def main() -> None:
    from backend.smart_checker.services.evalkit import runner
    from backend.smart_checker.services.evalkit.workspace import EvalWorkspace, SET_INCOMING
    from backend.smart_checker.infrastructure.prompts.profile_registry import (
        HASH_ALGORITHM,
        calculate_prompt_content_hash,
    )

    import yaml
    config_file = Path("/Users/softzephyr/Desktop/hyt-agent/exam_checker_agent/backend/config/llm_config.yaml")
    cloud_config = yaml.safe_load(config_file.read_text(encoding="utf-8"))["cloud"]["ali"]
    os.environ["QWEN_API_KEY"] = cloud_config["api_keys"][0]
    if not os.getenv("MINERU_TEXT_EXTRACTION_URL"):
        raise RuntimeError("MINERU_TEXT_EXTRACTION_URL is not set")
    model_url = cloud_config["base_url"].rstrip("/")
    if not os.getenv("MINERU_TEXT_EXTRACTION_URL", "").endswith("/file_parse"):
        raise RuntimeError("MINERU_TEXT_EXTRACTION_URL must end with /file_parse")
    # A minimal completion for this exact model was verified before the run.
    workspace = EvalWorkspace.resolve(OUTPUT)
    result_dir = workspace.run_dir(RUN_ID)
    if result_dir.exists():
        raise RuntimeError(f"Run ID already exists; refusing overwrite: {result_dir}")

    paper_dir = workspace.papers_dir(SET_INCOMING)
    paper_dir.mkdir(parents=True, exist_ok=True)
    papers = sorted(
        path for path in SOURCE.iterdir()
        if path.is_file() and path.suffix.lower() in {".doc", ".docx", ".pdf"}
    )
    if len(papers) != EXPECTED_PAPERS:
        raise RuntimeError(f"Expected {EXPECTED_PAPERS} input papers, got {len(papers)}")
    if {paper.name for paper in papers} != EXPECTED_NAMES:
        raise RuntimeError("Input paper filenames differ from the handoff's five originals")
    input_sha256 = {}
    for paper in papers:
        with paper.open("rb") as stream:
            input_sha256[paper.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    for paper in papers:
        link = paper_dir / paper.name
        if not link.exists():
            link.symlink_to(paper)
        elif not link.is_symlink() or link.resolve() != paper.resolve():
            raise RuntimeError(f"Unexpected existing staged paper: {link}")

    config = workspace.load_config()
    config.update({
        "name": "best27b-fullpapers-aliyun-qwen38",
        "threads": 40,
        "reviewRoutingEnabled": False,
        "textExtractionProvider": "mineru",
        "plagiarism": {"basic": False, "cross": False, "history": False},
    })
    workspace.load_config = lambda: config

    original_enqueue = runner._enqueue_batch_like_frontend
    snapshot_details: dict[str, object] = {}

    def enqueue_with_best_prompts(
        runtime, *, batch_id, threads, detection_error_types, options, pipeline_steps
    ):
        snapshot = runtime.prompt_profiles.resolve_snapshot("", BASE_PROFILE, "pro")
        prompts = dict(snapshot["taskPrompts"])
        modes = dict(snapshot["taskThinkModes"])
        for task_id, (filename, mode) in SELECTED.items():
            text = (PROMPTS / filename).read_text(encoding="utf-8").strip()
            if not text or ('"think":' in text) != (mode == "explicit"):
                raise RuntimeError(f"Prompt output protocol mismatch: {filename}")
            if task_id not in prompts or task_id not in modes:
                raise RuntimeError(f"Unknown task: {task_id}")
            prompts[task_id] = text
            modes[task_id] = mode
        content_hash = calculate_prompt_content_hash(prompts)
        snapshot.update({
            "id": f"evalkit-{RUN_ID}",
            "name": "27B best eight plus original specialist prompts",
            "kind": "evalkit-candidate",
            "version": content_hash[:16],
            "thinkModeOverride": None,
            "taskThinkModes": modes,
            "hashAlgorithm": HASH_ALGORITHM,
            "hash": content_hash,
            "taskPrompts": prompts,
        })
        snapshot_details.update({
            "base_profile": BASE_PROFILE,
            "profile_sha256": content_hash,
            "task_think_modes": modes,
            "selected_prompt_files": {
                task_id: {"file": filename, "mode": mode}
                for task_id, (filename, mode) in SELECTED.items()
            },
        })
        run_options = dict(options)
        run_options["promptProfileSnapshot"] = snapshot
        return original_enqueue(
            runtime,
            batch_id=batch_id,
            threads=threads,
            detection_error_types=detection_error_types,
            options=run_options,
            pipeline_steps=pipeline_steps,
        )

    runner._enqueue_batch_like_frontend = enqueue_with_best_prompts
    started = time.perf_counter()
    try:
        summary = runner.run_eval(
            workspace=workspace,
            source=SET_INCOMING,
            run_id=RUN_ID,
            environment="local",
            model_name=MODEL,
            threads=40,
            local_base_url=model_url,
            local_api_key_env="QWEN_API_KEY",
            think_mode=None,
            poll_interval=10.0,
            timeout_seconds=21600,
        )
    finally:
        runner._enqueue_batch_like_frontend = original_enqueue
    wall_seconds = time.perf_counter() - started

    db_path = Path(summary["runtime"]["data_dir"]) / "app.db"
    with sqlite3.connect(db_path) as connection:
        metrics = {
            row[0]: {
                "questions": int(row[1] or 0),
                "parse_seconds": float(row[2] or 0),
                "review_seconds": float(row[3] or 0),
                "error_message": str(row[4] or ""),
            }
            for row in connection.execute(
                "SELECT task_id, total_questions, parse_elapsed_seconds, "
                "review_elapsed_seconds, error_message FROM task_metrics"
            )
        }
    per_paper = [
        {**task, **metrics.get(task["task_id"], {})}
        for task in summary["tasks"]
    ]
    successful = [row for row in per_paper if row["status"] == "success"]
    total_questions = sum(row.get("questions", 0) for row in successful)
    total_review_seconds = sum(row.get("review_seconds", 0) for row in successful)
    result = {
        "run_id": RUN_ID,
        "batch_id": summary["batch_id"],
        "model": MODEL,
        "model_endpoint": model_url,
        "mineru_endpoint": os.getenv("MINERU_TEXT_EXTRACTION_URL"),
        "input_sha256": input_sha256,
        "threads": 40,
        "total_papers": len(per_paper),
        "total_questions": total_questions,
        "total_findings": summary["total_findings"],
        "wall_seconds": round(wall_seconds, 3),
        "review_seconds_sum": round(total_review_seconds, 3),
        "avg_wall_seconds_per_question": round(wall_seconds / total_questions, 3)
        if total_questions else None,
        "avg_review_seconds_per_question": round(total_review_seconds / total_questions, 3)
        if total_questions else None,
        "papers": per_paper,
        "prompt_profile": snapshot_details,
        "source_summary": str(result_dir / "summary.json"),
    }
    (OUTPUT / "运行结果.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 完整试卷审校结果",
        "",
        f"模型：{MODEL}（阿里云）；题目级并发：40；解析：MinerU。",
        f"试卷：{len(per_paper)} 份；实际解析题目：{total_questions} 题；发现问题：{summary['total_findings']} 条。",
        f"端到端总耗时：{wall_seconds:.1f} 秒；平均单题摊销耗时：{wall_seconds / total_questions:.2f} 秒。"
        if total_questions else f"端到端总耗时：{wall_seconds:.1f} 秒；无有效题目可计算平均值。",
        f"审校阶段累计耗时：{total_review_seconds:.1f} 秒；审校阶段平均每题：{total_review_seconds / total_questions:.2f} 秒。"
        if total_questions else "审校阶段平均每题：不可计算。",
        "",
        "| 试卷 | 状态 | 解析题数 | 问题数 | 解析耗时(s) | 审校耗时(s) | 错误信息 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in per_paper:
        error_message = row.get("error_message", "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['paper']} | {row['status']} | {row.get('questions', 0)} | "
            f"{row['finding_count']} | {row.get('parse_seconds', 0):.1f} | "
            f"{row.get('review_seconds', 0):.1f} | {error_message} |"
        )
    lines += [
        "",
        "平均单题摊销耗时 = 本次试卷端到端墙钟时间 ÷ 实际解析题数；",
        "审校阶段平均每题 = 各卷 review_elapsed_seconds 之和 ÷ 实际解析题数。",
        "运行记录保留在本目录的 `runs/` 下；8 类使用最优版，其余任务继承现有 27B 专用 Profile。",
    ]
    (OUTPUT / "运行结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
