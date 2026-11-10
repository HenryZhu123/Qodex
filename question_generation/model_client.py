"""Small, bounded JSON-completion adapter. Credentials never enter artifacts."""
from __future__ import annotations

import json
from http.client import HTTPException
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ModelError(Exception):
    def __init__(self, message: str, *, code: str | None = None,
                 finish_reason: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.diagnostics = {key: value for key, value in (
            ("code", code), ("finish_reason", finish_reason), ("http_status", http_status)
        ) if value is not None}


FINISH_REASONS = (
    "stop", "length", "content_filter", "tool_calls", "insufficient_system_resource", "aborted",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonModel:
    reasoning_effort = "high"

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
            "thinking": {"type": "enabled"}, "reasoning_effort": self.reasoning_effort}, ensure_ascii=False).encode()
        if len(body) > 100_000:
            raise ModelError("命题材料超过单次调用预算。", code="request_size_limit")
        request = Request(self.base_url + "/chat/completions", data=body, headers={
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
        })
        start = time.monotonic()
        finish_reason = None
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                chunks, size = [], 0
                while True:
                    if time.monotonic() - start > self.timeout:
                        raise ModelError("模型响应超过总时限，本次不交付题目。", code="response_timeout")
                    chunk = response.read1(min(65536, 1_000_001 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > 1_000_000:
                        raise ModelError("模型响应超过大小上限。", code="response_size_limit")
                raw = b"".join(chunks)
            if len(raw) > 1_000_000:
                raise ModelError("模型响应超过大小上限。", code="response_size_limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            usage = result.get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            tokens = {"elapsed_seconds": round(time.monotonic() - start, 3), **{
                key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and usage[key] >= 0
            }}
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict) and type(details.get("reasoning_tokens")) is int:
                reasoning_tokens = details["reasoning_tokens"]
                if 0 <= reasoning_tokens <= tokens.get("completion_tokens", -1):
                    tokens["reasoning_tokens"] = reasoning_tokens
            self.usage.append(tokens)
            choice = result["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError()
            reason = choice.get("finish_reason")
            finish_reason = reason if reason in FINISH_REASONS else "unknown"
            if finish_reason != "stop":
                raise ModelError("模型输出未完整结束，本次不交付题目。",
                                 code="incomplete_output", finish_reason=finish_reason)
            content = choice["message"]["content"]
            if content is None or (isinstance(content, str) and not content.strip()):
                raise ModelError("模型返回无效或空 JSON，本次未生成题目。",
                                 code="empty_content", finish_reason=finish_reason)
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError()
        except HTTPError as error:
            raise ModelError(f"模型服务返回 HTTP {error.code}，本次未生成题目。",
                             code="http_error", http_status=error.code) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise ModelError("模型服务连接失败或超时，本次未生成题目。", code="transport_error") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError("模型返回无效或空 JSON，本次未生成题目。",
                             code="invalid_content" if finish_reason == "stop" else "invalid_response",
                             finish_reason=finish_reason) from None
        return value
