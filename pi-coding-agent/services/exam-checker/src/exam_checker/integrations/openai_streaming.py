from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx


class StreamingChatError(RuntimeError):
    """Base error for streamed OpenAI-compatible chat completions."""


class StreamingChatHTTPError(StreamingChatError):
    def __init__(self, status_code: int, response_text: str) -> None:
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(
            f"LLM request failed with HTTP {status_code}: {response_text[:500]}"
        )


class StreamingChatProtocolError(StreamingChatError):
    """Raised when a successful response contains an invalid SSE stream."""


async def stream_chat_completion(
    client: httpx.AsyncClient,
    *,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> str:
    """Return text assembled from an OpenAI-compatible SSE chat stream."""
    request_payload = dict(payload)
    request_payload["stream"] = True

    async with client.stream(
        "POST",
        url,
        headers=headers,
        json=request_payload,
    ) as response:
        if response.is_error:
            response_body = (await response.aread()).decode(errors="replace")
            raise StreamingChatHTTPError(response.status_code, response_body)

        chunks: list[str] = []
        finished = False
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue

            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                finished = True
                continue
            if finished:
                continue

            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise StreamingChatProtocolError(
                    "LLM stream contained invalid JSON data"
                ) from exc

            if not isinstance(event, dict):
                raise StreamingChatProtocolError(
                    "LLM stream event must be a JSON object"
                )
            if event.get("error") is not None:
                raise StreamingChatProtocolError(
                    f"LLM stream returned an error event: {event['error']}"
                )

            choices = event.get("choices")
            if not choices:
                continue
            if not isinstance(choices, list) or not isinstance(choices[0], dict):
                raise StreamingChatProtocolError(
                    "LLM stream event has invalid choices"
                )

            delta = choices[0].get("delta")
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if content is None:
                continue
            if not isinstance(content, str):
                raise StreamingChatProtocolError(
                    "LLM stream delta content must be a string"
                )
            chunks.append(content)

    content = "".join(chunks)
    if not content:
        raise StreamingChatProtocolError("LLM stream returned no content")
    return content
