"""Small, bounded JSON-completion adapter. Credentials never enter artifacts."""
from __future__ import annotations

from contextvars import ContextVar
import json
import math
import os
import re
import socket
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from . import observability


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


def _restore(client, name, previous):
    """Undo a per-stage override, including an attribute this call introduced."""
    if previous is not None:
        setattr(client, name, previous)
    elif name in vars(client):
        delattr(client, name)


# A pipeline-wide deadline shared by every stage of one authoring attempt. The
# value is an absolute ``time.monotonic()`` instant, set by ``cached_authoring``.
PIPELINE_DEADLINE: ContextVar[float | None] = ContextVar(
    "question_generation_pipeline_deadline", default=None,
)
PIPELINE_TIMEOUT_SECONDS = 900
PIPELINE_TIMEOUT_ENV = "QUESTION_GENERATION_PIPELINE_TIMEOUT_SECONDS"


def pipeline_timeout_seconds() -> float:
    """Read the total pipeline budget; invalid values fall back to the default."""
    raw = os.environ.get(PIPELINE_TIMEOUT_ENV, str(PIPELINE_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(PIPELINE_TIMEOUT_SECONDS)
    return value if value > 0 else float(PIPELINE_TIMEOUT_SECONDS)


def _usage_since(client, start: int) -> dict | None:
    usage = getattr(client, "usage", None)
    if isinstance(usage, list) and len(usage) > start and isinstance(usage[-1], dict):
        return usage[-1]
    return None


def complete_stage(client, stage: str, system: str, payload: dict) -> dict:
    """Attach the calling stage and apply its frozen budget/effort without changing the client."""
    budgets = getattr(client, "stage_output_tokens", {})
    timeouts = getattr(client, "stage_timeout_seconds", {})
    efforts = getattr(client, "stage_reasoning_effort", {})
    deadline = PIPELINE_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        attempt = max(1, int(getattr(client, "attempt", 1) or 1))
        observability.event("stage.start", stage=stage, attempt=attempt, elapsed_ms=0.0, usage=None)
        observability.event(
            "stage.end", stage=stage, attempt=attempt, elapsed_ms=0.0, usage=None,
            status="deadline", code="response_timeout",
        )
        error = ModelError(
            "命题流水线超过总时限，本次未交付题目。",
            code="response_timeout", response_issue="pipeline_deadline",
        )
        error.diagnostics["stage"] = stage
        if stage in efforts:
            error.diagnostics["reasoning_effort"] = efforts[stage]
        raise error
    started = time.monotonic()
    attempt = max(1, int(getattr(client, "attempt", 1) or 1))
    usage = getattr(client, "usage", None)
    usage_start = len(usage) if isinstance(usage, list) else 0
    observability.event("stage.start", stage=stage, attempt=attempt, elapsed_ms=0.0, usage=None)
    previous_budget = getattr(client, "max_output_tokens", None)
    previous_timeout = getattr(client, "timeout", None)
    previous_effort = getattr(client, "reasoning_effort", None)
    try:
        if stage in budgets:
            client.max_output_tokens = budgets[stage]
        if stage in timeouts:
            client.timeout = timeouts[stage]
        if stage in efforts:
            client.reasoning_effort = efforts[stage]
        result = client.complete(system, payload)
    except ModelError as error:
        error.diagnostics["stage"] = stage
        if stage in efforts:
            error.diagnostics["reasoning_effort"] = efforts[stage]
        observability.event(
            "stage.end", stage=stage, attempt=max(1, int(getattr(client, "attempt", attempt) or attempt)),
            elapsed_ms=round((time.monotonic() - started) * 1000, 1), usage=_usage_since(client, usage_start),
            status="error", code=error.diagnostics.get("code"),
        )
        raise
    else:
        observability.event(
            "stage.end", stage=stage, attempt=max(1, int(getattr(client, "attempt", attempt) or attempt)),
            elapsed_ms=round((time.monotonic() - started) * 1000, 1), usage=_usage_since(client, usage_start),
            status="ok",
        )
        return result
    finally:
        _restore(client, "max_output_tokens", previous_budget)
        _restore(client, "timeout", previous_timeout)
        _restore(client, "reasoning_effort", previous_effort)


FINISH_REASONS = (
    "stop", "length", "content_filter", "tool_calls", "insufficient_system_resource", "aborted",
)
# The provider exposes exactly these thinking levels (there is no "medium").
REASONING_EFFORTS = ("off", "low", "high", "max")
STAGES = ("plan", "author", "reader", "audit")
DEFAULT_OUTPUT_TOKENS = 16384
PLAN_OUTPUT_TOKENS = 32768
AUTHOR_OUTPUT_TOKENS = 32768
READER_OUTPUT_TOKENS = 32768
AUDIT_OUTPUT_TOKENS = 32768
PLAN_TIMEOUT_SECONDS = 240
AUTHOR_TIMEOUT_SECONDS = 600
READER_TIMEOUT_SECONDS = 600
AUDIT_TIMEOUT_SECONDS = 600
STAGE_OUTPUT_TOKENS = {"plan": PLAN_OUTPUT_TOKENS, "author": AUTHOR_OUTPUT_TOKENS,
                       "reader": READER_OUTPUT_TOKENS, "audit": AUDIT_OUTPUT_TOKENS}
STAGE_TIMEOUT_SECONDS = {"plan": PLAN_TIMEOUT_SECONDS, "author": AUTHOR_TIMEOUT_SECONDS,
                         "reader": READER_TIMEOUT_SECONDS, "audit": AUDIT_TIMEOUT_SECONDS}
# Deep thinking only pays off where the model must design or verify an item.
STAGE_REASONING_EFFORT = {"plan": "low", "author": "high", "reader": "low", "audit": "low"}
# A silent SSE stream means a dead connection; total time is still bounded by self.timeout.
IDLE_TIMEOUT_SECONDS = 90
# Python 3.9 keeps socket.timeout distinct from TimeoutError; 3.10+ aliases them.
TIMEOUT_ERRORS = (TimeoutError, socket.timeout)


class _IdleTimeout(Exception):
    """Internal marker: the provider stopped sending chunks for the idle window."""


INVALID_JSON_MESSAGE = "模型返回无效或空 JSON，本次未生成题目。"
RAW_RESPONSE_LIMIT = 16_000_000
CONTENT_LIMIT = 1_000_000
JSON_FENCE = re.compile(r"^\s*```[A-Za-z0-9_-]*\s*(.*?)\s*```\s*$", re.S)
INVALID_ESCAPE = re.compile(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})')


def _strip_fence(content):
    """Drop a ```json wrapper some gateways add despite json_object mode."""
    match = JSON_FENCE.match(content)
    return match.group(1) if match else content


def _escape_invalid_backslashes(content):
    r"""Double LaTeX-style single backslashes (\alpha, \le, \times) that JSON rejects."""
    return INVALID_ESCAPE.sub(r"\\\\", content)


def _close_braces(content):
    """Append up to two missing closing braces; deeper truncation is not repaired."""
    missing = content.count("{") - content.count("}")
    if not 0 < missing <= 2:
        return None
    return content.rstrip() + "}" * missing


def _parse_json_content(content: str, report: dict | None = None) -> dict:
    """Decode a model JSON body, repairing only bounded formatting slips.

    Repair order: fenced code block, unescaped backslashes, missing closing
    braces. Repairs never invent content: an unterminated string, a wrong value
    or trailing text still fails. ``report["repair"]`` names what was applied.
    """
    bases = [(content, "none")]
    fenced = _strip_fence(content)
    if fenced != content:
        bases.append((fenced, "fence"))
    for base, label in list(bases):
        escaped = _escape_invalid_backslashes(base)
        if escaped != base:
            bases.append((escaped, label.replace("none", "") + "backslash"
                          if label != "none" else "backslash"))
    for base, label in list(bases):
        filled = _close_braces(base)
        if filled is not None:
            bases.append((filled, label + "+brace" if label != "none" else "brace"))
    error = None
    for text, repair in bases:
        try:
            value = json.loads(text, strict=False)
        except (json.JSONDecodeError, RecursionError) as exc:
            error = exc
            continue
        if report is not None:
            report["repair"] = repair
        return value
    raise error


def _stream_result(raw: bytes) -> dict:
    """Fold an SSE response into the same envelope used by non-streaming calls."""
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="stream_decode") from None
    parts, usage, finish_reason, response_model, events = [], {}, None, None, 0
    accumulated = ""
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
            # Some gateways send cumulative delta.content instead of the standard
            # incremental delta. Replace when the new block starts with the old one.
            if accumulated and len(delta_content) >= len(accumulated) and delta_content.startswith(accumulated):
                parts = [delta_content]
                accumulated = delta_content
            else:
                parts.append(delta_content)
                accumulated += delta_content
            saw_delta = True
        elif isinstance(message, dict) and isinstance(message.get("content"), str) and not saw_delta:
            parts.append(message["content"])
            accumulated += message["content"]
    if not events:
        raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_decode")
    result = {"choices": [{"finish_reason": finish_reason or "unknown",
                           "message": {"content": accumulated}}], "usage": usage}
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
                 max_output_tokens: int = DEFAULT_OUTPUT_TOKENS, max_retries: int = 1,
                 retry_delay: float = 1.75, attempt_hook=None):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ModelError("模型服务地址须为不含凭据、查询参数的 HTTPS 地址。")
        if not model.strip() or not api_key.strip():
            raise ModelError("请配置 DEEPSEEK_MODEL 和 DEEPSEEK_API_KEY。")
        if type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ModelError("模型输出 token 预算须为正整数。")
        if type(max_retries) is not int or max_retries < 0:
            raise ModelError("模型重试次数须为非负整数。")
        if isinstance(retry_delay, bool) or not isinstance(retry_delay, (int, float)) or retry_delay < 0:
            raise ModelError("模型重试等待须为非负数。")
        self.base_url, self.model, self.api_key, self.timeout = base_url.rstrip("/"), model, api_key, timeout
        self.max_output_tokens = max_output_tokens
        self.stream = True
        self.max_retries, self.retry_delay, self.attempt_hook = max_retries, retry_delay, attempt_hook
        self.stage_output_tokens: dict[str, int] = {}
        self.stage_timeout_seconds: dict[str, int] = {}
        self.stage_reasoning_effort: dict[str, str] = {}
        self.usage = []
        self.attempt = 1
        self.session_id = uuid4().hex
        self.opencode_go = parsed.hostname == "opencode.ai" and parsed.path.rstrip("/") == "/inference/go/openai/v1"

    @classmethod
    def from_env(cls):
        def env_int(name, default):
            try:
                value = int(os.environ.get(name, str(default)))
            except ValueError:
                raise ModelError("模型输出 token 预算须为正整数。") from None
            if value < 1:
                raise ModelError("模型输出 token 预算须为正整数。")
            return value

        def env_effort(stage):
            name = f"QUESTION_GENERATION_{stage.upper()}_REASONING_EFFORT"
            value = os.environ.get(name, STAGE_REASONING_EFFORT[stage]).strip().lower()
            if value not in REASONING_EFFORTS:
                raise ModelError(f"{name} 须为 {'、'.join(REASONING_EFFORTS)} 之一。")
            return value

        output_tokens = env_int("QUESTION_GENERATION_MAX_OUTPUT_TOKENS", DEFAULT_OUTPUT_TOKENS)
        stages = {stage: {"tokens": env_int(f"QUESTION_GENERATION_{stage.upper()}_MAX_OUTPUT_TOKENS",
                                            STAGE_OUTPUT_TOKENS[stage]),
                          "timeout": env_int(f"QUESTION_GENERATION_{stage.upper()}_TIMEOUT_SECONDS",
                                             STAGE_TIMEOUT_SECONDS[stage]),
                          "effort": env_effort(stage)} for stage in STAGES}
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        # The official DeepSeek gateway can hold an SSE connection open without
        # emitting bytes during a long reasoning phase. Non-streaming is the
        # stable default there; other OpenAI-compatible gateways keep streaming.
        default_stream = "0" if urlsplit(base_url).hostname == "api.deepseek.com" else "1"
        stream = os.environ.get("QUESTION_GENERATION_STREAM", default_stream).strip().lower() not in {
            "0", "false", "off", "no",
        }
        client = cls(base_url=base_url,
                     model=os.environ.get("DEEPSEEK_MODEL", ""), api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                     max_output_tokens=output_tokens)
        client.stream = stream
        # Author must design the whole item; audit must re-derive it. Planning and
        # the blind solve are short, so deep thinking there only added latency.
        # Budgets stay wide (32768 tokens) so a long item never hits "length".
        client.stage_output_tokens = {stage: settings["tokens"] for stage, settings in stages.items()}
        client.stage_timeout_seconds = {stage: settings["timeout"] for stage, settings in stages.items()}
        client.stage_reasoning_effort = {stage: settings["effort"] for stage, settings in stages.items()}
        return client

    def _request_body(self, system: str, payload: dict, stream: bool) -> bytes:
        effort = getattr(self, "reasoning_effort", "high")
        if effort not in REASONING_EFFORTS:
            raise ModelError(f"推理档位须为 {'、'.join(REASONING_EFFORTS)} 之一。", code="invalid_config")
        thinking = {"thinking": {"type": "disabled"}} if effort == "off" else {
            "thinking": {"type": "enabled"}, "reasoning_effort": effort}
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
            **thinking,
            "stream": bool(stream),
        }
        if stream:
            body["stream_options"] = {"include_usage": True}
        return json.dumps(body, ensure_ascii=False).encode()

    def complete(self, system: str, payload: dict) -> dict:
        body = self._request_body(system, payload, self.stream)
        if len(body) > 100_000:
            raise ModelError("命题材料超过单次调用预算。", code="request_size_limit")
        headers = {
            "Authorization": "Bearer " + self.api_key, "Content-Type": "application/json",
        }
        if self.opencode_go:
            headers.update({"User-Agent": "Qodex-question-generation/0.5", "x-opencode-session": self.session_id})
        started = time.monotonic()
        idle = min(self.timeout, IDLE_TIMEOUT_SECONDS)
        nonstream_timeout = self.timeout if not self.stream else idle
        attempts = 0
        stream = self.stream
        fallback_used = False
        while True:
            self.attempt = attempts + 1
            if self.attempt_hook is not None:
                self.attempt_hook()
            body = self._request_body(system, payload, stream)
            # base_url is validated as HTTPS in __init__ and redirects are disabled.
            request = Request(self.base_url + "/chat/completions", data=body, headers=headers)  # noqa: S310
            try:
                if stream:
                    chunks, size = [], 0
                    # Only a silence window bounds a single read; a stream that keeps
                    # producing output may legitimately run until self.timeout.
                    with build_opener(NoRedirect()).open(request, timeout=idle) as response:
                        while True:
                            if time.monotonic() - started > self.timeout:
                                raise ModelError("模型响应超过总时限，本次不交付题目。", code="response_timeout")
                            try:
                                chunk = response.read1(min(65536, RAW_RESPONSE_LIMIT + 1 - size))
                            except TIMEOUT_ERRORS:
                                raise _IdleTimeout from None
                            if not chunk:
                                break
                            chunks.append(chunk)
                            size += len(chunk)
                            if size > RAW_RESPONSE_LIMIT:
                                raise ModelError("模型响应超过大小上限。", code="response_size_limit",
                                                 content_length=size, response_issue="raw_stream")
                    raw = b"".join(chunks)
                else:
                    with build_opener(NoRedirect()).open(request, timeout=max(1, nonstream_timeout)) as response:
                        raw = response.read(RAW_RESPONSE_LIMIT + 1)
                    if len(raw) > RAW_RESPONSE_LIMIT:
                        raise ModelError("模型响应超过大小上限。", code="response_size_limit",
                                         content_length=len(raw), response_issue="raw_stream")
            except _IdleTimeout:
                if stream and not fallback_used:
                    # Official DeepSeek Flash can hold an SSE connection open
                    # without emitting bytes during a long reasoning phase. A
                    # non-streaming retry avoids the chunked-read deadlock.
                    stream, fallback_used = False, True
                    attempts += 1
                    continue
                if attempts < self.max_retries and time.monotonic() - started < self.timeout:
                    attempts += 1
                    time.sleep(self.retry_delay)
                    continue
                raise ModelError(f"模型响应连续 {idle:.0f} 秒无数据，本次不交付题目。",
                                 code="response_timeout", response_issue="idle_timeout") from None
            except HTTPError as error:
                if error.code in {502, 503, 504} and attempts < self.max_retries:
                    attempts += 1
                    time.sleep(self.retry_delay)
                    continue
                raise ModelError(f"模型服务返回 HTTP {error.code}，本次未生成题目。",
                                 code="http_error", http_status=error.code) from None
            except TIMEOUT_ERRORS:
                raise ModelError("模型调用超时，本次不交付题目。", code="response_timeout") from None
            except URLError as error:
                if isinstance(error.reason, TIMEOUT_ERRORS):
                    raise ModelError("模型调用超时，本次不交付题目。", code="response_timeout") from None
                if attempts < self.max_retries:
                    attempts += 1
                    time.sleep(self.retry_delay)
                    continue
                raise ModelError("模型服务连接失败，本次未生成题目。", code="transport_error") from None
            except (OSError, HTTPException):
                if attempts < self.max_retries:
                    attempts += 1
                    time.sleep(self.retry_delay)
                    continue
                raise ModelError("模型服务连接失败或超时，本次未生成题目。", code="transport_error") from None
            try:
                return self._finish_response(raw, started)
            except ModelError as error:
                # Only a body that failed to decode (or came back empty) is re-rolled.
                # Contract failures such as "not an object" are deterministic, and the
                # re-roll shares the transport retry budget instead of stacking on it.
                decodable = (error.diagnostics.get("code") == "empty_content"
                             or error.diagnostics.get("response_issue") == "content_decode")
                if decodable and attempts < self.max_retries and time.monotonic() - started < self.timeout:
                    attempts += 1
                    time.sleep(self.retry_delay)
                    continue
                raise

    def _finish_response(self, raw: bytes, started: float) -> dict:
        result = _decode_body(raw)
        if not isinstance(result, dict):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_response", response_issue="envelope_shape")
        usage = result.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        tokens = {"elapsed_seconds": round(time.monotonic() - started, 3), **{
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
        if len(content) > CONTENT_LIMIT:
            raise ModelError("模型响应正文超过大小上限。", code="response_size_limit",
                             content_length=len(content), response_issue="decoded_content")
        report = {}
        try:
            # Tolerates raw control characters inside strings plus the bounded
            # formatting slips described in _parse_json_content. No structural
            # check below is relaxed by a repair.
            value = _parse_json_content(content, report)
        except json.JSONDecodeError as error:
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_decode", content_decode_position=error.pos,
                             content_length=len(content)) from None
        except (ValueError, RecursionError):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_decode") from None
        repair = report.get("repair")
        if repair and repair != "none":
            self.usage[-1]["content_repair"] = repair
        if not isinstance(value, dict):
            raise ModelError(INVALID_JSON_MESSAGE, code="invalid_content", finish_reason=finish_reason,
                             response_issue="content_not_object")
        return value
