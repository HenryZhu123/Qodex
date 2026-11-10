"""Model adapters used by the loopback question workbench."""
from __future__ import annotations

from http.client import HTTPException
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .authoring import OBJECTIVES
from .brief_authoring import PLAN_PROMPT, QUESTION_TYPES
from .model_client import ModelError, NoRedirect


def planning_format(payload):
    def choices(values):
        return {"type": "string", "enum": list(values)}

    def array(items, maximum):
        return {"type": "array", "items": items, "minItems": 1, "maxItems": maximum}

    def record(fields):
        return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}

    prose = {"type": "string"}
    fields = {k: prose for k in ("topic", "target", "task", "student_evidence")}
    fields.update(subject=choices(dict.fromkeys(item["subject"] for item in payload["scope"])),
                  syllabus_areas=array(choices(item["id"] for item in payload["scope"]), 4),
                  question_type=choices(QUESTION_TYPES), objective=choices(sorted(OBJECTIVES)),
                  evidence_ids=array(choices(item["material"]["id"] for item in payload["evidence"]), 4))
    for key in payload["fixed"]:
        fields.pop(key)
    return {"anyOf": [record({"plan": record(fields)}), record({"material_gaps": array(prose, 8)})]}


def unfinished_draft(content):
    """Read complete JSON view fields from a truncated candidate prefix."""
    prefix = re.match(r'\s*\{\s*"candidate"\s*:\s*\{\s*', content)
    if not prefix:
        return None
    read = json.JSONDecoder().raw_decode
    colon_pattern, comma_pattern = re.compile(r'\s*:\s*'), re.compile(r'\s*,\s*')
    offset = prefix.end()
    draft = {}
    while offset < len(content):
        try:
            key, offset = read(content, offset)
            colon = colon_pattern.match(content, offset)
            if not colon:
                break
            value, offset = read(content, colon.end())
        except (ValueError, RecursionError):
            break
        if key in ("student_view", "instructor_view") and isinstance(value, dict):
            draft[key] = value
        comma = comma_pattern.match(content, offset)
        if not comma:
            break
        offset = comma.end()
    return draft if isinstance(draft.get("student_view", {}).get("stem"), str) else None


class LocalPreviewModel:
    base_url = "http://127.0.0.1:11434"
    model = "jun-e4b:latest"
    reasoning_effort = "local-planning-schema-v1"

    def __init__(self):
        self.usage = []
        self.partial_draft = None

    def complete(self, system, payload):
        format = planning_format(payload) if system == PLAN_PROMPT else "json"
        body = json.dumps({"model": self.model, "stream": False, "think": False, "format": format,
                           "options": {"temperature": 0, "num_ctx": 12288, "num_predict": 4096},
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
                          ensure_ascii=False).encode()
        if len(body) > 100_000:
            raise ModelError("命题材料超过本机模型单次调用预算，请缩短材料。")
        request = Request(self.base_url + "/api/chat", data=body, headers={"Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=150) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ModelError("本机模型响应超过大小上限。")
            wire = json.loads(raw)
            self.usage.append({"elapsed_seconds": round(time.monotonic() - started, 2), **{
                key: wire[field] for key, field in (("prompt_tokens", "prompt_eval_count"), ("completion_tokens", "eval_count"))
                if type(wire.get(field)) is int
            }})
            if wire.get("done_reason") != "stop":
                content = wire.get("message", {}).get("content")
                if isinstance(content, str):
                    self.partial_draft = unfinished_draft(content)
                raise ModelError("本机模型输出未完整结束。")
            result = json.loads(wire["message"]["content"])
            if not isinstance(result, dict):
                raise ValueError
        except HTTPError as error:
            if error.code == 404:
                raise ModelError("本机 Ollama 未安装 jun-e4b:latest 模型。") from None
            raise ModelError(f"本机 Ollama 返回 HTTP {error.code}。") from None
        except (URLError, OSError, HTTPException):
            raise ModelError("无法连接本机 Ollama，或模型响应超时。") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ModelError("本机模型返回了无效 JSON。") from None
        return result


class PreviewTrace:
    stages = ("需求细化", "题目创作", "独立解答", "反例与解析审计")

    def __init__(self, client):
        self.client = client
        self.base_url, self.model = client.base_url, client.model
        self.reasoning_effort = getattr(client, "reasoning_effort", None)
        self.usage = client.usage
        self.stage, self.draft, self.proposed_plan = None, None, None
        self.calls = 0

    def complete(self, system, payload):
        self.stage = self.stages[self.calls]
        self.calls += 1
        try:
            result = self.client.complete(system, payload)
        except ModelError:
            if self.calls == 2:
                self.draft = getattr(self.client, "partial_draft", None)
            raise
        if self.calls == 1 and isinstance(result.get("plan"), dict):
            self.proposed_plan = result["plan"]
        if self.calls == 2 and isinstance(result.get("candidate"), dict):
            candidate = result["candidate"]
            if isinstance(candidate.get("student_view"), dict):
                self.draft = {k: candidate[k] for k in ("student_view", "instructor_view") if k in candidate}
        return result
