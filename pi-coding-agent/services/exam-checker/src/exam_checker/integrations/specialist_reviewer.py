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
    "missing_check": "信息缺失",
    "ambiguity_check": "语义不清",
    "unsolvability_check": "题目无解",
    "answer_leak_check": "答案泄露",
    "logic_check": "事实/逻辑错误",
}

DEFAULT_KB_ENABLED_TASKS: frozenset[ReviewTaskId] = frozenset({"logic_check"})

AGENTIC_LOGIC_PROMPT_PATH = Path(
    r"D:\Code\hku\LLM\hku_agent\research-assets\review_eval\prompts\agentic_logic_check\task.txt"
)

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
                        ],
                        "description": "所属学科",
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
        if use_kb and task_id == "logic_check" and AGENTIC_LOGIC_PROMPT_PATH.exists():
            system_prompt = AGENTIC_LOGIC_PROMPT_PATH.read_text(encoding="utf-8").strip()
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
                            },
                        )
                        result = self._parse_content(content)
                        self._validate_result(task_id, result, payload)
                latency_ms = round((time.perf_counter() - started) * 1000)
                return result, latency_ms, attempt
            except (
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
                        if isinstance(exc, httpx.TimeoutException)
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

            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": choice,
                    "temperature": 0,
                    "seed": 42,
                    "enable_thinking": False,
                },
            )
            if resp.status_code != 200:
                raise self._http_error(resp.status_code, resp.text)

            choice_msg = resp.json()["choices"][0]["message"]
            messages.append(choice_msg)

            tcs = choice_msg.get("tool_calls")
            if not tcs:
                content = choice_msg.get("content") or ""
                result = self._parse_content(content)
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
            raise SpecialistReviewError(
                f"Specialist response violates the result schema: {exc}",
                error_code="INVALID_MODEL_RESPONSE",
                retryable=True,
            ) from exc

    @staticmethod
    def _validate_result(
        task_id: ReviewTaskId,
        result: SpecialistReviewResult,
        payload: CheckerPayload,
    ) -> None:
        for error in result.errors:
            if error.error_type != EXPECTED_ERROR_TYPES[task_id]:
                raise SpecialistReviewError(
                    f"Specialist returned {error.error_type!r} for {task_id}",
                    error_code="INVALID_MODEL_RESPONSE",
                    retryable=True,
                )
            if not error.original_text or error.original_text not in payload.detection_content:
                raise SpecialistReviewError(
                    "Specialist original_text is missing from detection_content",
                    error_code="INVALID_MODEL_RESPONSE",
                    retryable=True,
                )
