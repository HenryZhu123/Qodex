from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
import time
from typing import Any

import httpx
from pydantic import ValidationError

from ..domain.models import CheckerPayload, ReviewTaskId, SpecialistReviewResult
from ..parsing.factual_guard import check_factual_guards
from ..parsing.rule_checker import check_deterministic_rules
from ..prompts.repositories import ReviewPromptRepository
from .knowledge_base import KnowledgeBaseRetriever
from .openai_streaming import (
    StreamingChatHTTPError,
    StreamingChatProtocolError,
    stream_chat_completion,
)


class SpecialistReviewError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        retryable: bool,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.attempts = attempts


EXPECTED_ERROR_TYPES: dict[ReviewTaskId, str] = {
    "typo_check": "错别字",
    "punctuation_check": "标点符号错误",
    "options_check": "选项错误",
    "mismatch_check": "题目与题型不一致",
    "solvability_check": "可解性错误",
    "ambiguity_check": "语义不清",
    "answer_leak_check": "答案泄露",
    "logic_check": "事实/逻辑错误",
}

DEFAULT_KB_ENABLED_TASKS: frozenset[ReviewTaskId] = frozenset({"logic_check"})

# Valid domain terms that a character-level reviewer has repeatedly tried to
# "complete" into a different phrase. These are exact protections, not a
# general typo allowlist.
TYPO_PROTECTED_TERMS: frozenset[str] = frozenset({"界地址保护"})

KB_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "查询计算机考研408教材权威知识库，获取特定概念定义、参数规范、定理或计算公式",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "精准的实体检索词",
                    },
                    "subject": {
                        "type": "string",
                        "enum": [
                            "computer_network",
                            "operating_system",
                            "computer_organization",
                            "data_structure",
                            "auto",
                        ],
                        "description": (
                            "考点所属学科，按考点所在课程判断。"
                            "computer_organization：指令系统、寻址方式、数据通路、流水线、"
                            "Cache 与主存、总线、I/O 接口、中断与 DMA 的硬件机制；"
                            "operating_system：进程与线程、调度、同步互斥、死锁、内存管理、"
                            "文件系统、磁盘调度；"
                            "data_structure：线性表、树、图、查找、排序、算法复杂度；"
                            "computer_network：协议分层、TCP/IP、路由、链路层、无线网络。"
                            "跨两门或无法判定时填 auto，由系统跨库检索。"
                        ),
                    },
                },
                "required": ["query", "subject"],
            },
        },
    }
]


class OpenAICompatibleSpecialistReviewer:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        prompts: ReviewPromptRepository,
        *,
        timeout_seconds: float = 180,
        max_concurrency: int = 8,
        max_attempts: int = 3,
        retry_base_delay_seconds: float = 1,
        client: httpx.AsyncClient | None = None,
        knowledge_base: KnowledgeBaseRetriever | None = None,
        kb_enabled_tasks: frozenset[ReviewTaskId] = DEFAULT_KB_ENABLED_TASKS,
        reasoning_effort: str = "",
        max_tokens: int = 2048,
        agentic_logic_prompt_path: str | Path = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.prompts = prompts
        self.max_attempts = max(1, max_attempts)
        self.retry_base_delay_seconds = max(0, retry_base_delay_seconds)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self.knowledge_base = knowledge_base
        self.kb_enabled_tasks = kb_enabled_tasks
        self.reasoning_effort = reasoning_effort.strip()
        self.max_tokens = max(256, max_tokens)
        self.agentic_logic_prompt_path = (
            Path(agentic_logic_prompt_path).expanduser()
            if agentic_logic_prompt_path
            else None
        )

    def _reasoning_params(self) -> dict[str, Any]:
        """Extra body fields that control reasoning output.

        Reasoning models on some gateways ignore ``enable_thinking`` and spend
        the ``max_tokens`` budget on reasoning_content, which truncates the JSON
        answer. ``reasoning_effort="none"`` turns that off. Empty by default so
        models that do not support the field keep the previous request shape.
        """
        return {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def review(
        self, task_id: ReviewTaskId, payload: CheckerPayload
    ) -> tuple[SpecialistReviewResult, int, int]:
        if not self.base_url or not self.api_key or not self.model:
            raise SpecialistReviewError(
                "EXAM_CHECKER_REVIEW_LLM_BASE_URL, "
                "EXAM_CHECKER_REVIEW_LLM_API_KEY and "
                "EXAM_CHECKER_REVIEW_LLM_MODEL are required",
                error_code="CONFIGURATION_ERROR",
                retryable=False,
            )
        started = time.perf_counter()
        user_prompt = (
            "[INPUT_PAYLOAD]\n"
            f"{json.dumps(payload.model_dump(), ensure_ascii=False)}"
        )

        # Fast path 1: check deterministic format & structure rules
        if task_id in {"options_check", "mismatch_check"}:
            rule_res = check_deterministic_rules(payload.detection_content)
            if rule_res and rule_res.has_error:
                if (
                    task_id == "options_check"
                    and rule_res.errors[0].error_type == "选项错误"
                ) or (
                    task_id == "mismatch_check"
                    and rule_res.errors[0].error_type == "题目与题型不一致"
                ):
                    latency_ms = round((time.perf_counter() - started) * 1000)
                    return rule_res, latency_ms, 1

        # Fast path 2: check deterministic factual guards
        if task_id == "logic_check":
            guard_res = check_factual_guards(payload.detection_content)
            if guard_res and guard_res.has_error:
                latency_ms = round((time.perf_counter() - started) * 1000)
                return guard_res, latency_ms, 1

        use_kb = (
            task_id in self.kb_enabled_tasks
            and self.knowledge_base is not None
            and self.knowledge_base.is_available()
        )
        if (
            use_kb
            and task_id == "logic_check"
            and self.agentic_logic_prompt_path is not None
            and self.agentic_logic_prompt_path.is_file()
        ):
            system_prompt = self.agentic_logic_prompt_path.read_text(
                encoding="utf-8"
            ).strip()
        else:
            system_prompt = self.prompts.system_prompt(task_id)
        last_error: SpecialistReviewError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                async with self._semaphore:
                    if use_kb:
                        result = await self._review_with_tools(
                            task_id, payload, system_prompt, user_prompt
                        )
                    else:
                        content = await stream_chat_completion(
                            self._client,
                            url=f"{self.base_url}/chat/completions",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            payload={
                                "model": self.model,
                                "messages": [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt},
                                ],
                                "temperature": 0,
                                "seed": 42,
                                "response_format": {"type": "json_object"},
                                "enable_thinking": False,
                                "chat_template_kwargs": {"enable_thinking": False},
                                **self._reasoning_params(),
                            },
                        )
                        result = self._parse_content(content)
                        self._validate_result(task_id, result, payload)
                latency_ms = round((time.perf_counter() - started) * 1000)
                return result, latency_ms, attempt
            except (
                TimeoutError,
                httpx.HTTPError,
                StreamingChatHTTPError,
                StreamingChatProtocolError,
                SpecialistReviewError,
            ) as exc:
                if isinstance(exc, SpecialistReviewError):
                    last_error = exc
                elif isinstance(exc, StreamingChatHTTPError):
                    last_error = self._http_error(
                        exc.status_code, exc.response_text
                    )
                elif isinstance(exc, StreamingChatProtocolError):
                    last_error = SpecialistReviewError(
                        str(exc),
                        error_code="INVALID_MODEL_RESPONSE",
                        retryable=True,
                    )
                else:
                    error_code = (
                        "UPSTREAM_TIMEOUT"
                        if isinstance(exc, (TimeoutError, httpx.TimeoutException))
                        else "UPSTREAM_NETWORK_ERROR"
                    )
                    last_error = SpecialistReviewError(
                        f"Specialist request failed: {exc}",
                        error_code=error_code,
                        retryable=True,
                    )
                last_error.attempts = attempt
                if not last_error.retryable or attempt == self.max_attempts:
                    raise last_error
                await asyncio.sleep(
                    self.retry_base_delay_seconds * (2 ** (attempt - 1))
                )
        assert last_error is not None
        raise SpecialistReviewError(
            f"Specialist review failed after {self.max_attempts} attempts: {last_error}",
            error_code=last_error.error_code,
            retryable=last_error.retryable,
            attempts=self.max_attempts,
        ) from last_error

    async def _review_with_tools(
        self,
        task_id: ReviewTaskId,
        payload: CheckerPayload,
        system_prompt: str,
        user_prompt: str,
    ) -> SpecialistReviewResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tool_queries: list[str] = []
        total_retrieval_latency = 0.0
        max_rounds = 3

        for round_idx in range(max_rounds):
            tools = KB_TOOLS_SCHEMA if round_idx < (max_rounds - 1) else None
            choice = "auto" if round_idx < (max_rounds - 1) else "none"

            request_body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": choice,
                "temperature": 0,
                "seed": 42,
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": self.max_tokens,
                **self._reasoning_params(),
            }
            if choice == "none":
                request_body["response_format"] = {"type": "json_object"}
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_body,
            )
            if resp.status_code != 200:
                raise self._http_error(resp.status_code, resp.text)

            choice_msg = resp.json()["choices"][0]["message"]
            messages.append(choice_msg)

            tcs = choice_msg.get("tool_calls")
            if not tcs:
                content = choice_msg.get("content") or ""
                finish_reason = resp.json()["choices"][0].get("finish_reason")
                try:
                    if finish_reason == "length":
                        raise SpecialistReviewError(
                            "Specialist response was truncated by the output limit",
                            error_code="JSON_TRUNCATED",
                            retryable=True,
                        )
                    result = self._parse_content(content)
                except SpecialistReviewError as exc:
                    if exc.error_code not in {
                        "JSON_PREFIX_NOISE",
                        "JSON_TRUNCATED",
                        "JSON_SCHEMA_INVALID",
                    }:
                        raise
                    result = await self._regenerate_compact_json(messages)
                result.kb_queries = tool_queries
                result.kb_latency_ms = round(total_retrieval_latency)
                self._validate_result(task_id, result, payload)
                return result

            for tc in tcs:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                q = args.get("query", "")
                sub = args.get("subject", "computer_network")
                tool_queries.append(f"[{sub}] {q}")

                assert self.knowledge_base is not None
                evs, r_lat = self.knowledge_base.search(sub, q, top_k=2)
                total_retrieval_latency += r_lat
                ev_text = self.knowledge_base.format_evidence(evs)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": ev_text if ev_text else "知识库未检索到完全匹配的教材段落。",
                    }
                )

        raise SpecialistReviewError(
            "Specialist exceeded max tool rounds without decision",
            error_code="MAX_ROUNDS_EXCEEDED",
            retryable=True,
        )

    async def _regenerate_compact_json(
        self, messages: list[dict[str, Any]]
    ) -> SpecialistReviewResult:
        repair_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "上一条回答的格式无效或被截断。保留已经完成的判断，只重新输出"
                    "一个完整、紧凑的 JSON 对象。不要输出 Markdown、解释、推理过程或 think 字段；"
                    "reason 不超过60字，每条 description 和 suggestion 各不超过两句话。"
                ),
            },
        ]
        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": repair_messages,
                "tool_choice": "none",
                "temperature": 0,
                "seed": 42,
                "enable_thinking": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                **self._reasoning_params(),
            },
        )
        if resp.status_code != 200:
            raise self._http_error(resp.status_code, resp.text)
        choice = resp.json()["choices"][0]
        if choice.get("finish_reason") == "length":
            raise SpecialistReviewError(
                "Compact JSON regeneration was truncated by the output limit",
                error_code="JSON_TRUNCATED",
                retryable=True,
            )
        return self._parse_content(choice.get("message", {}).get("content") or "")

    @staticmethod
    def _http_error(status_code: int, response_text: str) -> SpecialistReviewError:
        if status_code in {401, 403}:
            error_code = "AUTHENTICATION_FAILED"
            retryable = False
        elif status_code == 400:
            error_code = "INVALID_REQUEST"
            retryable = False
        elif status_code == 429:
            error_code = "RATE_LIMITED"
            retryable = True
        elif status_code >= 500:
            error_code = "UPSTREAM_SERVER_ERROR"
            retryable = True
        else:
            error_code = "UPSTREAM_REQUEST_FAILED"
            retryable = False
        return SpecialistReviewError(
            f"Specialist request failed with HTTP {status_code}: "
            f"{response_text[:500]}",
            error_code=error_code,
            retryable=retryable,
        )

    @staticmethod
    def _parse_content(content: str) -> SpecialistReviewResult:
        stripped = content.strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
        try:
            return SpecialistReviewResult.model_validate_json(stripped)
        except ValidationError as exc:
            decoder = json.JSONDecoder()
            for start in (index for index, char in enumerate(stripped) if char == "{"):
                try:
                    value, _ = decoder.raw_decode(stripped[start:])
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                try:
                    return SpecialistReviewResult.model_validate(value)
                except ValidationError:
                    continue

            lowered_error = str(exc).lower()
            truncated = "{" in stripped and any(
                marker in lowered_error
                for marker in (
                    "eof while parsing",
                    "unterminated string",
                    "expected value at line",
                )
            )
            if truncated:
                error_code = "JSON_TRUNCATED"
            elif "{" in stripped:
                error_code = "JSON_SCHEMA_INVALID"
            else:
                error_code = "JSON_PREFIX_NOISE"
            raise SpecialistReviewError(
                f"Specialist response violates the result schema: {exc}",
                error_code=error_code,
                retryable=True,
            ) from exc

    @staticmethod
    def _validate_result(
        task_id: ReviewTaskId,
        result: SpecialistReviewResult,
        payload: CheckerPayload,
    ) -> None:
        retained_errors = []
        for error in result.errors:
            if error.error_type != EXPECTED_ERROR_TYPES[task_id]:
                raise SpecialistReviewError(
                    f"Specialist returned {error.error_type!r} for {task_id}",
                    error_code="INVALID_MODEL_RESPONSE",
                    retryable=True,
                )
            if task_id == "typo_check" and any(
                protected in error.original_text for protected in TYPO_PROTECTED_TERMS
            ):
                continue
            if not error.original_text:
                continue
            if error.original_text not in payload.detection_content:
                matched = OpenAICompatibleSpecialistReviewer._match_ignoring_whitespace(
                    payload.detection_content, error.original_text
                )
                if matched is None:
                    # A finding that cannot quote the input is not safe to expose. Treat it
                    # as an unsupported candidate rather than making the whole question
                    # unresolved.
                    continue
                error.original_text = matched
            retained_errors.append(error)

        if len(retained_errors) != len(result.errors):
            result.errors = retained_errors
            result.total_errors = len(retained_errors)
            result.has_error = bool(retained_errors)

    @staticmethod
    def _match_ignoring_whitespace(haystack: str, needle: str) -> str | None:
        def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
            normalized: list[str] = []
            offsets: list[int] = []
            in_whitespace = False
            for index, char in enumerate(text):
                if char.isspace():
                    if not in_whitespace:
                        normalized.append(" ")
                        offsets.append(index)
                    in_whitespace = True
                else:
                    normalized.append(char)
                    offsets.append(index)
                    in_whitespace = False
            return "".join(normalized), offsets

        normalized_haystack, offsets = normalize_with_offsets(haystack)
        normalized_needle = re.sub(r"\s+", " ", needle).strip()
        if not normalized_needle:
            return None
        start = normalized_haystack.find(normalized_needle)
        if start < 0 or start >= len(offsets):
            return None
        end_index = start + len(normalized_needle) - 1
        if end_index >= len(offsets):
            return None
        return haystack[offsets[start] : offsets[end_index] + 1]
