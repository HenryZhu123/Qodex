from __future__ import annotations

import asyncio
import json
import re

import httpx
from pydantic import ValidationError

from .openai_streaming import (
    StreamingChatError,
    StreamingChatHTTPError,
    stream_chat_completion,
)
from ..domain.models import (
    QuestionMetadata,
    QuestionView,
)
from ..prompts.repositories import SinglePromptRepository


class QuestionWorkflowModelError(RuntimeError):
    pass


class OpenAICompatibleQuestionWorkflowModel:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        metadata_prompts: SinglePromptRepository,
        timeout_seconds: float = 180,
        max_concurrency: int = 8,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.metadata_prompts = metadata_prompts
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def annotate(self, question: QuestionView) -> QuestionMetadata:
        user_prompt = json.dumps(question.model_dump(mode="json"), ensure_ascii=False)
        content = await self._complete(
            self.metadata_prompts.system_prompt(), user_prompt
        )
        try:
            return QuestionMetadata.model_validate_json(content)
        except ValidationError as exc:
            raise QuestionWorkflowModelError(
                f"Metadata response violates the result schema: {exc}"
            ) from exc

    async def _complete(self, system_prompt: str, user_prompt: str) -> str:
        if not self.base_url or not self.api_key or not self.model:
            raise QuestionWorkflowModelError(
                "Question workflow LLM endpoint, API key and model are required"
            )
        try:
            async with self._semaphore:
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
                        "response_format": {"type": "json_object"},
                        "enable_thinking": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
        except StreamingChatHTTPError as exc:
            raise QuestionWorkflowModelError(str(exc)) from exc
        except (httpx.HTTPError, StreamingChatError) as exc:
            raise QuestionWorkflowModelError(
                f"Question workflow model request failed: {exc}"
            ) from exc
        stripped = content.strip()
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        return re.sub(r"\s*```$", "", stripped)
