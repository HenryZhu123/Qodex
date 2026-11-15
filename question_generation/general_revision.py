"""Targeted repair of a versioned general question with its original sources."""
from __future__ import annotations

from hashlib import sha256
import re

from .authoring import cached_authoring, read_authoring
from .comprehensive import read_revision, request_id, revised
from .curriculum import AREAS
from .comprehensive import MAX_REVISIONS
from .general_authoring import BRIEF_VERSION, REVISION_VERSION, SCOUTED_BRIEF_VERSION, VERSION, prompt_fingerprint, run
from .general_contract import text, validate_candidate
from .generation import RequestError, _evidence_refs, failure_result
from .knowledge import KnowledgeUnavailable
from .material_discovery import restore_discovered
from .reference_material import restore_reference


def _materials(payload, current, areas, knowledge):
    refs = current.get("evidence_refs")
    _evidence_refs(refs, set(), "原题", require_summary=False)
    if not refs or len(refs) > 16:
        raise RequestError("原题没有可恢复的材料引用。", "NEEDS_MATERIAL")
    if "evidence" in payload:
        supplied = payload["evidence"]
        _evidence_refs(supplied, set(), "修订")
        if len(supplied) > 16:
            raise RequestError("修订最多接受16条原始材料。")
        sources = {item["id"]: item for item in supplied}
        if not {r["id"] for r in refs} <= sources.keys():
            raise RequestError("请提供与原题引用ID一致的完整材料。", "NEEDS_MATERIAL")
    else:
        sources = {}
        if knowledge is not None:
            subjects = {s for s, group in AREAS.items() if any(a in group for a in areas)}
            for subject in subjects:
                for item in knowledge.find(subject, current["metadata"]["topic"]):
                    sources[item["id"]] = item
    restored = []
    for ref in refs:
        item = sources.get(ref["id"])
        if "evidence" not in payload and not item:
            item = restore_reference(areas, ref)
            if item is None and knowledge is not None:
                item = restore_discovered(knowledge, ref, areas)
        if not item or any(item.get(key) != value for key, value in ref.items()):
            raise RequestError(f'请提供原题引用的材料「{ref["anchor"]}」。', "NEEDS_MATERIAL")
        pin = re.search(r"(?:chunk sha256:|^Qodex explanatory note · sha256:)([a-f0-9]{64})(?: · |$)",
                        ref["version"])
        if pin and sha256(item.get("excerpt", item["summary"]).encode()).hexdigest() != pin[1]:
            raise RequestError(f'材料「{ref["anchor"]}」的内容与原题指纹不一致。', "NEEDS_MATERIAL")
        restored.append(item)
    return restored


def revise_authored(payload, *, knowledge=None, client=None, cache_path=None):
    identifier = request_id(payload)
    try:
        if not isinstance(payload, dict):
            raise RequestError("修订请求须为JSON对象。")
        current, feedback = read_revision({k: v for k, v in payload.items() if k != "evidence"})
        if (feedback["action"] != "repair" or not text(feedback["comment"], 2000)
                or not text(feedback["feedback_id"], 200)):
            raise RequestError("通用修订须指定 action=repair 和不超过2000字的具体问题。")
        # v1 -> v2 -> v3 is the whole chain: the agent may review at most three versions,
        # so a repaired package must itself be revisable once more.
        if current["version"] > MAX_REVISIONS:
            raise RequestError(f"通用创作题最多修订至 v{MAX_REVISIONS + 1}。", "REVISION_LIMIT")
        generator = current["generator"]
        if generator["version"] not in {VERSION, VERSION + "-public-v1", BRIEF_VERSION,
                                        SCOUTED_BRIEF_VERSION, REVISION_VERSION}:
            raise RequestError("当前创作版本没有可复用的修订契约。", "UNSUPPORTED_REQUEST")
        if current.get("review_status") != "PENDING" or current["self_check"].get("status") != "PASSED":
            raise RequestError("修订须提供已入待审流程的完整题包。")
        params = generator["parameters"]
        settings = params["authoring"]
        metadata = current["metadata"]
        evidence = _materials(payload, current, settings["syllabus_areas"], knowledge)
        planned = {k: metadata[k] for k in ("subject", "topic", "question_type")}
        planned.update(schema_version="0.1", request_id=identifier, seed=generator["seed"],
                       constraints={**params["constraints"], "authoring": settings}, evidence=evidence)
        request, settings, base = read_authoring(planned)
        previous = {"student_view": current["student_view"], "instructor_view": current["instructor_view"],
                    "design": current["pedagogy"], "calculations": current["self_check"]["calculations"]}
        validate_candidate(previous, request, evidence)
        student = previous["student_view"]
        targets = {p["id"] for p in student.get("parts", student.get("options", []))}
        if feedback["part_id"] not in targets | {"stem", "question"}:
            raise RequestError("反馈须指向题干、整题或题面已有的小问或选项。", "FEEDBACK_TARGET_MISMATCH")
        if "public_scenario" in settings:
            previous["public_scenario"] = current["self_check"]["public_scenario_verification"]
        brief_plan = params.get("brief_plan")
    except RequestError as error:
        return failure_result(error.status, str(error), identifier)
    except KnowledgeUnavailable:
        return failure_result("KNOWLEDGE_BASE_UNAVAILABLE", "原题所用的教材索引暂不可读。", identifier)
    except (KeyError, TypeError, AttributeError, ValueError):
        return failure_result("INVALID_REQUEST", "当前题包或其创作依据不完整。", identifier)

    def repair(_, model):
        result = run(base, model, request, settings, brief_plan=brief_plan, version=REVISION_VERSION,
                     repair={"previous": previous, "feedback": feedback})
        if result["status"] != "GENERATED":
            return result
        question, = result["questions"]
        question["metadata"] = metadata.copy()
        return {**revised(identifier, question, current, feedback, {}),
                "authoring_report": result["authoring_report"]}

    return cached_authoring({**payload, "evidence": evidence}, REVISION_VERSION, repair,
                            client=client, cache_path=cache_path, cache_salt=prompt_fingerprint())
