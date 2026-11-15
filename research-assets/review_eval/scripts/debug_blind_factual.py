import asyncio
import json
import os
import winreg
import httpx
from agentic_reviewer import run_agentic_review

async def test():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        api_key, _ = winreg.QueryValueEx(key, "TALKWEB_API_KEY")
    client = httpx.AsyncClient(timeout=90)
    
    records = [json.loads(l) for l in open('hku_agent/research-assets/review_eval/blind_test_set/dataset/blind_test_full.jsonl', encoding='utf-8')]
    r = [x for x in records if x['error_type'] == 'factual_logical'][0]
    
    res = await run_agentic_review(
        client=client,
        base_url="https://llm.talkweb.com.cn/v1",
        api_key=api_key,
        model="gpu-qwen3.8-27b",
        full_text=r['error_text'],
        subject=r['source_subject']
    )
    print("has_error:", res.has_error)
    print("tool_calls:", res.tool_calls_count)
    print("err_msg:", res.error_msg)
    print("raw_content:", repr(res.raw_content[:400]))

asyncio.run(test())
