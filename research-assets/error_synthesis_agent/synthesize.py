#!/usr/bin/env python3
"""并发调用 OpenAI 兼容接口，从 Excel 或单道题构造指定错误样本。"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from prompt_library import PROMPT_FILES, build_prompt

REQUIRED_FIELDS = {
    "error_type", "error_detailed_type", "design_rationale",
    "correction", "error_content", "error_cnt",
}
TITLE_ALIASES = ("title", "题型", "题型或其它信息", "题型或其他信息")
CONTENT_ALIASES = ("content", "题目", "题干", "detection_content")


def load_dotenv(path: Path) -> None:
    """加载本目录 .env；已有环境变量优先，避免覆盖部署环境配置。"""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(Path(__file__).with_name(".env"))


def chat_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("模型输出中未找到 JSON 对象")
        value = json.loads(match.group(0))
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        value = value[0]
    if not isinstance(value, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return value


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def validate(item: dict[str, Any], expected_type: str, source_content: str, required_detailed_type: str = "", require_suffix_deletion: bool = False, min_suffix_delete_chars: int = 2) -> dict[str, Any]:
    missing = REQUIRED_FIELDS - item.keys()
    if missing:
        raise ValueError(f"缺少字段：{', '.join(sorted(missing))}")
    if item["error_type"] != expected_type:
        raise ValueError(f"error_type 不匹配：{item['error_type']!r}")
    if required_detailed_type and item["error_detailed_type"] != required_detailed_type:
        raise ValueError(f"error_detailed_type 不匹配：{item['error_detailed_type']!r}")
    if not isinstance(item["error_cnt"], int) or item["error_cnt"] < 1:
        raise ValueError("error_cnt 必须是正整数")
    for key in REQUIRED_FIELDS - {"error_cnt"}:
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError(f"字段 {key} 必须为非空字符串")
    if require_suffix_deletion:
        original, broken = normalize(source_content), normalize(item["error_content"])
        deleted_chars = len(original) - len(broken)
        if deleted_chars < min_suffix_delete_chars or not original.startswith(broken):
            raise ValueError("专项要求不符合：error_content 必须仅删除原题末尾连续内容")
    return {key: item[key] for key in REQUIRED_FIELDS}


def call_model(record: dict[str, Any], args: argparse.Namespace, index: int) -> dict[str, Any]:
    title = str(record.get("title", "")).strip()
    content = str(record.get("content", "")).strip()
    if not title or not content:
        raise ValueError("输入记录必须含有非空 title 和 content")
    special = str(record.get("generation_instruction", args.generation_instruction or ""))
    prompt = build_prompt(
        args.error_type, title, content, special,
        str(record.get("reference", "")), args.required_detailed_type,
    )
    system_prompt = "你必须严格按用户要求输出一个有效 JSON 对象。"
    if args.require_suffix_deletion:
        system_prompt += (
            "本次唯一允许的改动是从原题末尾删除一段连续文本。"
            "error_content 必须是原题的严格前缀，不得替换、添加或改写任意字符。"
            f"error_detailed_type 必须严格为“{args.required_detailed_type}”。"
            "删除内容至少为两个非空白字符，不能只删除句号、问号或空格。"
            "删除后必须留下真实的末尾残缺：悬空连词、缺失宾语/中心词、未完成问句，或缺失实际填空/选择位置。"
            "例如：原文“简述甲与乙的区别和联系。”可变为“简述甲与乙的区别和”；"
            "原文“请说明该方法的主要内容。”可变为“请说明该方法的主要”；"
            "原文“下列说法正确的是（ ）。”可变为“下列说法正确的是”。"
            "只删句号、将句子改成句式杂糅、搭配不当或语序改写均不允许。"
        )
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        # DashScope OpenAI compatible mode supports this and prevents prose output.
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        chat_url(args.base_url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {args.api_key}"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(args.retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            message = body["choices"][0]["message"]
            text = message.get("content") or ""
            try:
                return validate(
                    extract_json(text), args.error_type, content,
                    args.required_detailed_type, args.require_suffix_deletion,
                    args.min_suffix_delete_chars,
                )
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"模型输出不是有效目标 JSON：{text[:1000]!r}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
            if attempt < args.retries:
                time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < args.retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error))


def first_existing(headers: tuple[str, ...], requested: str | None, aliases: tuple[str, ...], label: str) -> str:
    if requested:
        if requested not in headers:
            raise ValueError(f"Excel 中没有列 {requested!r}；现有列：{', '.join(headers)}")
        return requested
    for name in aliases:
        if name in headers:
            return name
    raise ValueError(f"未找到{label}列，请使用 --{label}-column 指定；现有列：{', '.join(headers)}")


def read_excel(path: Path, title_column: str | None, content_column: str | None) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("Excel 输入需要 openpyxl：pip install -r requirements.txt") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    raw_headers = next(rows, None)
    if not raw_headers:
        raise ValueError("Excel 为空")
    headers = tuple(str(value).strip() if value is not None else "" for value in raw_headers)
    title_key = first_existing(headers, title_column, TITLE_ALIASES, "title")
    content_key = first_existing(headers, content_column, CONTENT_ALIASES, "content")
    records = []
    for row_no, row in enumerate(rows, 2):
        data = {headers[i]: row[i] if i < len(row) else None for i in range(len(headers))}
        if not str(data.get(title_key, "") or "").strip() or not str(data.get(content_key, "") or "").strip():
            continue
        records.append({
            "title": str(data[title_key]).strip(),
            "content": str(data[content_key]).strip(),
            "reference": str(data.get("reference", "") or ""),
            "generation_instruction": str(data.get("generation_instruction", "") or ""),
            "_source_row": row_no,
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--excel", type=Path, help="题目 Excel 文件")
    source.add_argument("--content", help="单道题完整题目文本；必须与 --title 同时提供")
    parser.add_argument("--title", help="单道题题型；Excel 输入时忽略")
    parser.add_argument("--title-column", help="Excel 的题型列名，默认自动识别")
    parser.add_argument("--content-column", help="Excel 的题目列名，默认自动识别")
    parser.add_argument("--output", required=True, type=Path, help="输出 JSONL")
    parser.add_argument("--error-type", required=True, choices=sorted(PROMPT_FILES))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", ""), help="OpenAI 兼容 API 根地址或完整 chat/completions 地址")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", ""))
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--generation-instruction", default="", help="专项要求；Excel 同名列可逐题覆盖")
    parser.add_argument("--required-detailed-type", default="", help="要求模型返回的二级错误类型")
    parser.add_argument("--require-suffix-deletion", action="store_true", help="要求 error_content 仅删除原题末尾连续内容")
    parser.add_argument("--min-suffix-delete-chars", type=int, default=2, help="题末截断时至少删除的非空白字符数")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--only-source-index", default="", help="仅处理指定的 1 起始题目序号，逗号分隔；用于重试失败项")
    args = parser.parse_args()
    if args.content and not args.title:
        parser.error("单道题模式必须同时提供 --title")
    if not args.api_key:
        parser.error("请通过 --api-key 或 OPENAI_API_KEY 提供 API 密钥")
    if not args.base_url or not args.model:
        parser.error("请通过参数或 .env 提供 --base-url 和 --model")
    if args.concurrency < 1:
        parser.error("--concurrency 必须大于 0")

    records = read_excel(args.excel, args.title_column, args.content_column) if args.excel else [
        {"title": args.title, "content": args.content, "generation_instruction": args.generation_instruction}
    ]
    if args.only_source_index:
        try:
            wanted = {int(value.strip()) for value in args.only_source_index.split(',') if value.strip()}
        except ValueError as exc:
            parser.error(f"--only-source-index 必须为逗号分隔的正整数：{exc}")
        if not wanted or min(wanted) < 1:
            parser.error("--only-source-index 必须使用从 1 开始的正整数")
        records = [record for index, record in enumerate(records, 1) if index in wanted]
    if not records:
        parser.error("未从输入中读取到有效题目")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print(f"开始处理 {len(records)} 条，类型={args.error_type}，并发={args.concurrency}")
    outputs: list[dict[str, Any] | None] = [None] * len(records)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        future_map = {executor.submit(call_model, record, args, idx): idx for idx, record in enumerate(records)}
        for future in concurrent.futures.as_completed(future_map):
            idx = future_map[future]
            try:
                outputs[idx] = future.result()
                print(f"[{idx + 1}/{len(records)}] OK")
            except Exception as exc:  # failure remains visible/retryable in output
                outputs[idx] = {
                    "_source_index": idx,
                    "_status": "failed",
                    "_error": str(exc),
                }
                print(f"[{idx + 1}/{len(records)}] FAILED: {exc}", file=sys.stderr)
    with args.output.open("w", encoding="utf-8") as handle:
        for result in outputs:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    success = sum(result is not None and result.get("_status") != "failed" for result in outputs)
    print(f"完成：成功 {success}/{len(records)}，输出：{args.output}")
    return 0 if success == len(records) else 2


if __name__ == "__main__":
    raise SystemExit(main())
