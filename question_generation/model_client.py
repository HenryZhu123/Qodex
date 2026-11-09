"""Small, bounded JSON-completion adapter. Credentials never enter artifacts."""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ModelError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonModel:
    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float = 120):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ModelError("模型服务地址须为不含凭据、查询参数的 HTTPS 地址。")
        if not model.strip() or not api_key.strip():
            raise ModelError("请配置 DEEPSEEK_MODEL 和 DEEPSEEK_API_KEY。")
        self.base_url, self.model, self.api_key, self.timeout = base_url.rstrip("/"), model, api_key, timeout
        self.usage = []

    @classmethod
    def from_env(cls):
        return cls(base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                   model=os.environ.get("DEEPSEEK_MODEL", ""), api_key=os.environ.get("DEEPSEEK_API_KEY", ""))

    def complete(self, system: str, payload: dict) -> dict:
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], "response_format": {"type": "json_object"}, "max_tokens": 16384,
            "thinking": {"type": "enabled"}, "reasoning_effort": "low"}, ensure_ascii=False).encode()
        if len(body) > 100_000:
            raise ModelError("命题材料超过单次调用预算。")
        request = Request(self.base_url + "/chat/completions", data=body, headers={
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
        })
        start = time.monotonic()
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                chunks, size = [], 0
                while True:
                    if time.monotonic() - start > self.timeout:
                        raise ModelError("模型响应超过总时限，本次不交付题目。")
                    chunk = response.read1(min(65536, 1_000_001 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ModelError("模型响应超过大小上限。")
                raw = b"".join(chunks)
            if len(raw) > 1_000_000:
                raise ModelError("模型响应超过大小上限。")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            usage = result.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            self.usage.append({"elapsed_seconds": round(time.monotonic() - start, 3), **{
                key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0
            }})
            choice = result["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError()
            if choice.get("finish_reason") != "stop":
                raise ModelError("模型输出未完整结束，本次不交付题目。")
            value = json.loads(choice["message"]["content"])
            if not isinstance(value, dict):
                raise ValueError()
        except HTTPError as error:
            raise ModelError(f"模型服务返回 HTTP {error.code}，本次未生成题目。") from None
        except (URLError, TimeoutError, OSError):
            raise ModelError("模型服务连接失败或超时，本次未生成题目。") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("模型返回无效或空 JSON，本次未生成题目。") from None
        return value
