import asyncio, os, time, httpx, winreg, sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from agentic_reviewer import run_agentic_review

async def test():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        api_key, _ = winreg.QueryValueEx(key, "TALKWEB_API_KEY")
    
    client = httpx.AsyncClient(timeout=60)
    print("Testing 1 sample agentic review...", flush=True)
    t0 = time.time()
    res = await run_agentic_review(
        client=client,
        base_url="https://llm.talkweb.com.cn/v1",
        api_key=api_key,
        model="gpu-qwen3.8-27b",
        full_text="题目：某主机向另一台主机发送TCP数据，往返时间RTT=20ms，初始拥塞窗口设置为0字节。请核查题面条件是否合理？",
        subject="computer_network"
    )
    t1 = time.time()
    print(f"Done in {t1-t0:.2f}s! has_error={res.has_error}, tool_calls={res.tool_calls_count}, err_msg='{res.error_msg}'", flush=True)
    print("Reason:", res.reason, flush=True)

asyncio.run(test())
