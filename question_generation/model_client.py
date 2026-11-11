"""Small, bounded JSON-completion adapter. Credentials never enter artifacts."""
from __future__ import annotations

import json
import math
import os
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class ModelError(Exception):
    def __init__(self, message: str, *, code: str | None = None,
                 finish_reason: str | None = None, http_status: int | None = None,
                 response_issue: str | None = None, content_decode_position: int | None = None,
                 content_length: int | None = None):
        super().__init__(message)
        self.diagnostics = {key: value for key, value in (
            ("code", code), ("finish_reason", finish_reason), ("http_status", http_status),
            ("response_issue", response_issue),
            ("content_decode_position", content_decode_position), ("content_length", content_length),
        ) if value is not None}


def complete_stage(client, stage: str, system: str, payload: dict) -> dict:
    """Attach the calling stage and apply any frozen per-stage budget without changing the client."""
    budgets = getattr(client, "stage_output_tokens", {})
    timeouts = getattr(client, "stage_timeout_seconds", {})
    previous_budget = getattr(client, "max_output_tokens", None)
    previous_timeout = getattr(client, "timeout", None)
    try:
        if stage in budgets:
            client.max_output_tokens = budgets[stage]
        if stage in timeouts:
            client.timeout = timeouts[stage]
        return client.complete(system, payload)
    except ModelError as error:
        error.diagnostics["stage"] = stage
        raise
    finally:
        if previous_budget is not None:
            client.max_output_tokens = previous_budget
        if previous_timeout is not None:
            client.timeout = previous_timeout


FINISH_REASONS = (
    "stop", "length", "content_filter", "tool_calls", "insufficient_system_resource", "aborted",
)
DEFAULT_OUTPUT_TOKENS = 16384
AUDIT_OUTPUT_TOKENS = 32768
AUDIT_TIMEOUT_SECONDS = 420
AUTHOR_TIMEOUT_SECONDS = 300
INVALID_JSON_MESSAGE = "模型返回无效或空 JSON，本次未生成题目。"


def _stream_result(raw: bytes) -> dict:
    """Fold an SSE response into the same envelope used by non-streaming calls."""
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="stream_decode") from None
    parts, usage, finish_reason, response_model, events = [], {}, None, None, 0
    saw_delta = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except (ValueError, RecursionError):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="stream_decode") from None
        if not isinstance(event, dict):
            continue
        events += 1
        if event.get("error") is not None:
            raise ModelError("模型服务返回流式错误，本次未生成题目。", code="provider_error")
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        if isinstance(event.get("model"), str):
            response_model = event["model"]
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            continue
        choice = choices[0]
        if choice.get("finish_reason") is not None:
            finish_reason = choice["finish_reason"]
        delta = choice.get("delta")
        delta_content = delta.get("content") if isinstance(delta, dict) else None
        message = choice.get("message")
        if isinstance(delta_content, str):
            parts.append(delta_content)
            saw_delta = True
        elif isinstance(message, dict) and isinstance(message.get("content"), str) and not saw_delta:
            parts.append(message["content"])
    if not events:
        raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_decode")
    result = {"choices": [{"finish_reason": finish_reason or "unknown", "message": {"content": "".join(parts)}}],
              "usage": usage}
    if response_model is not None:
        result["model"] = response_model
    return result


def _decode_body(raw: bytes) -> dict:
    head = raw.lstrip()[:16]
    if head.startswith((b"data:", b"event:", b":")):
        return _stream_result(raw)
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_decode") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JsonModel:
    reasoning_effort = "high"

    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float = 120,
                 max_output_tokens: int = DEFAULT_OUTPUT_TOKENS):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ModelError("模型服务地址须为不含凭据、查询参数的 HTTPS 地址。")
        if not model.strip() or not api_key.strip():
            raise ModelError("请配置 DEEPSEEK_MODEL 和 DEEPSEEK_API_KEY。")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ModelError("模型输出 token 预算须为正整数。")
        self.base_url, self.model, self.api_key, self.timeout = base_url.rstrip("/"), model, api_key, timeout
        self.max_output_tokens = max_output_tokens
        self.stage_output_tokens: dict[str, int] = {}
        self.stage_timeout_seconds: dict[str, int] = {}
        self.usage = []
        self.session_id = uuid4().hex
        self.opencode_go = parsed.hostname == "opencode.ai" and parsed.path.rstrip("/") == "/inference/go/openai/v1"

    @classmethod
    def from_env(cls):
        try:
            output_tokens = int(os.environ.get("QUESTION_GENERATION_MAX_OUTPUT_TOKENS", str(DEFAULT_OUTPUT_TOKENS)))
            audit_tokens = int(os.environ.get("QUESTION_GENERATION_AUDIT_MAX_OUTPUT_TOKENS", str(AUDIT_OUTPUT_TOKENS)))
            audit_timeout = int(os.environ.get("QUESTION_GENERATION_AUDIT_TIMEOUT_SECONDS", str(AUDIT_TIMEOUT_SECONDS)))
            author_timeout = int(os.environ.get("QUESTION_GENERATION_AUTHOR_TIMEOUT_SECONDS", str(AUTHOR_TIMEOUT_SECONDS)))
        except ValueError:
            raise ModelError("模型输出 token 预算须为正整数。") from None
        if min(audit_tokens, audit_timeout, author_timeout) < 1:
            raise ModelError("模型输出 token 预算须为正整数。")
        client = cls(base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                     model=os.environ.get("DEEPSEEK_MODEL", ""), api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                     max_output_tokens=output_tokens)
        # Audit stage: 16384 exhausted reasoning on comprehensive items; 32768/420s produced verdicts in the frozen run.
        client.stage_output_tokens = {"audit": audit_tokens}
        # Author stage: 120 s timed out on every Go author call in the paired run; 300 s produced 3/4 completions.
        client.stage_timeout_seconds = {"audit": audit_timeout, "author": author_timeout}
        return client

    def complete(self, system: str, payload: dict) -> dict:
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], "response_format": {"type": "json_object"}, "max_tokens": self.max_output_tokens,
            "thinking": {"type": "enabled"}, "reasoning_effort": self.reasoning_effort,
            "stream": True, "stream_options": {"include_usage": True}}, ensure_ascii=False).encode()
        if len(body) > 100_000:
            raise ModelError("命题材料超过单次调用预算。", code="request_size_limit")
        headers = {
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
        }
        if self.opencode_go:
            headers.update({"User-Agent": "Qodex-question-generation/0.5", "x-opencode-session": self.session_id})
        # base_url is validated as HTTPS in __init__ and redirects are disabled.
        request = Request(self.base_url + "/chat/completions", data=body, headers=headers)  # noqa: S310
        start = time.monotonic()
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
        except HTTPError as error:
            raise ModelError(f"模型服务返回 HTTP {error.code}，本次未生成题目。",
                             code="http_error", http_status=error.code) from None
        except TimeoutError:
            raise ModelError("模型调用超时，本次不交付题目。", code="response_timeout") from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelError("模型调用超时，本次不交付题目。", code="response_timeout") from None
            raise ModelError("模型服务连接失败，本次未生成题目。", code="transport_error") from None
        except (OSError, HTTPException):
            raise ModelError("模型服务连接失败或超时，本次未生成题目。", code="transport_error") from None
        result = _decode_body(b"".join(chunks))
        if not isinstance(result, dict):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_shape")
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
        if self.opencode_go:
            billing = usage.get("opencode", {})
            if isinstance(billing, dict):
                tokens["opencode"] = {key: billing[key] for key in ("list_cost", "allowance")
                                     if type(billing.get(key)) in (int, float)
                                     and math.isfinite(billing[key]) and billing[key] >= 0}
                source = billing.get("billing_source")
                if source in ("free", "balance", "go", "go-plus", "go-teams", "byok"):
                    tokens["opencode"]["billing_source"] = source
            cost = usage.get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost >= 0:
                tokens["cost"] = cost
            response_model = result.get("model")
            if isinstance(response_model, str) and 0 < len(response_model) <= 200:
                tokens["response_model"] = response_model
        self.usage.append(tokens)

        choices = result.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_shape")
        choice = choices[0]
        reason = choice.get("finish_reason")
        finish_reason = reason if reason in FINISH_REASONS else "unknown"
        if finish_reason != "stop":
            raise ModelError("模型输出未完整结束，本次不交付题目。",
                             code="incomplete_output", finish_reason=finish_reason)
        message = choice.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="envelope_shape")
        content = message["content"]
        if content is None or (isinstance(content, str) and not content.strip()):
            raise ModelError(INVALID_JSON_MESSAGE, code="empty_content", finish_reason=finish_reason)
        if not isinstance(content, str):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_type")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as error:
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_decode", content_decode_position=error.pos,
                             content_length=len(content)) from None
        except (ValueError, RecursionError):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_decode") from None
        if not isinstance(value, dict):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_not_object")
        return value
