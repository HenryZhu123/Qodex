#!/usr/bin/env python3
"""Use a stronger model to review synthesized training samples without modifying them."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

from synthesize import chat_url, load_dotenv
import urllib.request


load_dotenv(Path(__file__).with_name('.env'))


def review(item: dict, model: str, timeout: int) -> dict:
    source = item.get('source_content', '')
    prompt = f'''你是中文试题训练数据质检官。只审核，不改写。
原题：{source}
候选样本：{json.dumps(item['sample'], ensure_ascii=False)}

请判断该样本是否可作为“{item['sample'].get('error_type')}—{item['sample'].get('error_detailed_type')}”训练样本。
必须同时满足：error_content 与原题相比确有且仅有一处明确错误；错误真实属于该二级类型；题目仍完整可读；没有提示词、构造过程、元说明或学科事实被随意改写。
特别规则：成分残缺不得通过删去题末、选项、数值、公式或整段内容制造；搭配不当必须是词语搭配客观错误而非同义替换；句式杂糅必须出现两个句式结构的混合而非普通删改。
只输出 JSON：{{"approved":true或false,"reason":"不超过30字"}}。'''
    body = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是严格的数据质检官，只输出JSON。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
        'max_tokens': 200,
        'response_format': {'type': 'json_object'},
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        chat_url(os.environ['OPENAI_BASE_URL']), data=body,
        headers={'Authorization': f"Bearer {os.environ['OPENAI_API_KEY']}", 'Content-Type': 'application/json'}, method='POST')
    last_error = ''
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                content = json.loads(res.read().decode('utf-8'))['choices'][0]['message']['content']
            verdict = json.loads(content)
            return {**item, 'audit': {'approved': bool(verdict.get('approved')), 'reason': str(verdict.get('reason', ''))}}
        except Exception as exc:  # 单条调用异常不应中断整批审核
            last_error = f'{type(exc).__name__}: {exc}'
            if attempt == 0:
                time.sleep(2)
    return {**item, 'audit': {'approved': False, 'reason': f'Max审核调用失败：{last_error[:120]}'}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--source-manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--model', default='qwen3.8-max')
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=120)
    parser.add_argument('--limit', type=int, default=0, help='仅审核前 N 条，用于连通性与提示词测试')
    args = parser.parse_args()

    samples = [json.loads(line) for line in Path(args.input).read_text(encoding='utf-8').splitlines() if line.strip()]
    sources = [json.loads(line) for line in Path(args.source_manifest).read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(samples) != len(sources):
        raise ValueError(f'样本数{len(samples)}与题源数{len(sources)}不一致')
    items = [{'sample': s, 'source_content': x.get('content') or x.get('question_preview', '')} for s, x in zip(samples, sources)]
    if args.limit:
        items = items[:args.limit]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda x: review(x, args.model, args.timeout), items))
    Path(args.output).write_text('\n'.join(json.dumps(x, ensure_ascii=False) for x in results) + '\n', encoding='utf-8')
    print(f'审核完成：{sum(x["audit"]["approved"] for x in results)}/{len(results)} 通过，输出：{args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
