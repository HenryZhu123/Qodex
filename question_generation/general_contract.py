"""Material-grounded task designs; structural checks are not semantic proofs."""
from __future__ import annotations

import json
import re
from unicodedata import normalize

from .curriculum import read_scope
from .generation import Request, RequestError, REQUEST_FIELDS, _evidence_refs
from .verification import solve


def text(value, limit=6000):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def texts(value, low=1, high=12):
    return isinstance(value, list) and low <= len(value) <= high and all(text(v, 1000) for v in value)


def contains_span(quote, source):
    # PDF line wraps, full-width glyphs and ligatures are layout differences,
    # not missing evidence. Never use fuzzy similarity or delete punctuation.
    compact = lambda s: "".join(normalize("NFKC", s).split())
    return compact(quote) in compact(source)


def contains_given_span(quote, source):
    if contains_span(quote, source):
        return True
    # An extracted sentence may end with a period while the visible sentence
    # introduces code with a colon. Do not normalize internal punctuation or
    # apply this relaxation to textbook quotations.
    stripped = quote.rstrip()
    endings = "。.;；:："
    return bool(stripped and stripped[-1] in endings and any(
        contains_span(stripped[:-1] + ending, source) for ending in endings))


def visible_text(student):
    return "\n".join([student["stem"]] + [p["prompt"] for p in student.get("parts", [])]
                     + [o["text"] for o in student.get("options", [])])


def index_evidence(evidence):
    """Address contiguous source text without asking the model to transcribe it."""
    material, spans = [], {}
    for number, item in enumerate(evidence, 1):
        source = item.get("excerpt", item["summary"])
        sections = {}
        # Prefer nearby sentence or paragraph boundaries. Bound long OCR lines.
        for match in re.finditer(r".{1,479}(?:[。！？；\n]|$)|.{1,480}", source, re.DOTALL):
            excerpt = match.group().strip()
            if excerpt:
                key = f"M{number}.{len(sections) + 1}"
                sections[key] = excerpt
                spans[key] = (item["id"], excerpt)
        material.append({"source": item["source"], "anchor": item["anchor"], "spans": sections})
    return material, spans


def design_diagnostics(design, student):
    given = design["hinge"]["given"]
    return {"nonliteral_givens": [] if contains_given_span(given, visible_text(student)) else [given]}


def read_request(payload, settings):
    if not isinstance(payload, dict) or payload.keys() - REQUEST_FIELDS:
        raise RequestError("请求包含未知字段。")
    if payload.get("schema_version") != "0.1" or not text(payload.get("request_id"), 200):
        raise RequestError("须指定schema_version=0.1及有效request_id。")
    read_scope(payload.get("subject"), settings.get("syllabus_areas"))
    if not text(payload.get("topic"), 200):
        raise RequestError("topic须描述具体考查内容，不超过200字。")
    kind = payload.get("question_type")
    if kind not in ("single_choice", "comprehensive"):
        raise RequestError("通用创作支持single_choice或comprehensive。", "UNSUPPORTED_REQUEST")
    seed = payload.get("seed")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise RequestError("seed须为0至4294967295的整数。")
    constraints = payload.get("constraints", {})
    if not isinstance(constraints, dict) or constraints.keys() - {"requirements", "total_score"}:
        raise RequestError("通用约束支持requirements文本数组；综合题还须指定total_score。")
    if "requirements" in constraints and not texts(constraints["requirements"], 1, 8):
        raise RequestError("requirements须为1至8条非空要求，每条不超过1000字。")
    if kind == "comprehensive":
        score = constraints.get("total_score")
        if type(score) is not int or not 2 <= score <= 30:
            raise RequestError("综合题total_score须为2至30的整数。")
    elif "total_score" in constraints:
        raise RequestError("单选题不使用total_score；分值由批量槽位指定。")
    evidence = payload.get("evidence", [])
    # Reuse provenance validation, but don't invent a fixed set of rule tags.
    _evidence_refs(evidence, set(), "通用创作")
    if not evidence:
        raise RequestError("请提供解释目标概念及其关系的材料。", "NEEDS_MATERIAL")
    if len(evidence) > 16 or any(len(e["summary"]) > 12000 for e in evidence):
        raise RequestError("最多16条材料，每条摘要不超过12000字。")
    refs = [{k: e[k] for k in ("id", "source", "version", "anchor", "rules")} for e in evidence]
    return Request(payload["request_id"], seed, {k: payload[k] for k in
                   ("subject", "topic", "question_type")}, constraints, refs)


def resolve_design(design, spans):
    require(isinstance(design, dict) and design.keys() == {"target", "claims", "hinge"},
            "考查设计字段无效。")
    require(text(design["target"], 1000), "缺少具体可观察的学习表现。")
    hinge = design["hinge"]
    require(isinstance(hinge, dict) and hinge.keys() == {"given", "reasoning", "change", "effect"}
            and all(text(v, 2000) for v in hinge.values()), "须说明决定性题设、推理及改变题设后的结果。")
    claims = design["claims"]
    require(isinstance(claims, list) and 1 <= len(claims) <= 12, "须提供材料知识依据。")
    resolved = []
    seen = set()
    for claim in claims:
        require(isinstance(claim, dict) and claim.keys() == {"statement", "span_ids"}
                and text(claim["statement"], 2000) and texts(claim["span_ids"], 1, 4)
                and len(set(claim["span_ids"])) == len(claim["span_ids"]),
                "知识依据须给出规则和不重复的材料片段ID。")
        require(all(key in spans for key in claim["span_ids"]), "知识依据引用了不存在的材料片段。")
        identity = (claim["statement"].strip(), frozenset(claim["span_ids"]))
        require(identity not in seen, "知识依据重复。")
        seen.add(identity)
        resolved.append({"statement": claim["statement"], "citations": [
            {"span_id": key, "evidence_id": spans[key][0], "quote": spans[key][1]}
            for key in claim["span_ids"]
        ]})
    return {**design, "claims": resolved}


def validate_candidate(candidate, request, spans):
    fields = {"student_view", "instructor_view", "design"}
    require(isinstance(candidate, dict) and fields <= candidate.keys()
            and candidate.keys() <= fields | {"calculations"}, "候选字段无效。")
    student, teacher = candidate["student_view"], candidate["instructor_view"]
    require(isinstance(student, dict) and text(student.get("stem")) and isinstance(teacher, dict), "题面或教师视图无效。")
    if request.metadata["question_type"] == "single_choice":
        require(student.keys() == {"stem", "options"}, "单选学生视图只能包含题干与选项。")
        options = student["options"]
        require(isinstance(options, list) and len(options) == 4 and all(
            isinstance(o, dict) and o.keys() == {"id", "text"} and text(o["text"], 2000) for o in options
        ) and [o["id"] for o in options] == list("ABCD"), "须给出ABCD四个选项。")
        require(len({o["text"].strip() for o in options}) == 4, "选项重复。")
        require(teacher.keys() == {"correct_option_id", "explanation", "option_explanations", "misconceptions"}, "单选教师视图字段无效。")
        answer = teacher["correct_option_id"]
        require(isinstance(answer, str) and answer in list("ABCD") and text(teacher["explanation"]), "单选答案无效。")
        for field, keys in (("option_explanations", set("ABCD")), ("misconceptions", set("ABCD") - {answer})):
            require(isinstance(teacher[field], dict) and teacher[field].keys() == keys
                    and all(text(v) for v in teacher[field].values()), "须逐项解释并给出每个错项的具体错误机制。")
    else:
        require(student.keys() == {"stem", "parts"} and teacher.keys() == {"grading_policy", "parts"}
                and text(teacher["grading_policy"]), "综合题视图字段无效。")
        parts, solutions = student["parts"], teacher["parts"]
        require(isinstance(parts, list) and 2 <= len(parts) <= 6 and isinstance(solutions, list)
                and len(parts) == len(solutions), "综合题须有2至6个小问与对应评分。")
        seen, total = set(), 0
        for part, solution in zip(parts, solutions):
            require(isinstance(part, dict) and part.keys() == {"id", "prompt", "score"}
                    and text(part["id"], 100) and text(part["prompt"]) and part["id"] not in seen
                    and type(part["score"]) is int and 1 <= part["score"] <= 30, "小问ID、题面或分值无效。")
            require(isinstance(solution, dict) and solution.keys() == {
                "part_id", "solution", "scoring_points", "equivalent_methods", "depends_on"
            } and solution["part_id"] == part["id"] and text(solution["solution"]), "小问解答不匹配。")
            require(texts(solution["depends_on"], 0, 5) and set(solution["depends_on"]) <= seen, "小问依赖只能引用前面的小问。")
            points = solution["scoring_points"]
            require(isinstance(points, list) and 1 <= len(points) <= 8 and all(
                isinstance(p, dict) and p.keys() == {"id", "points", "criterion", "expected"}
                and all(text(p[k]) for k in ("id", "criterion", "expected"))
                and type(p["points"]) is int and p["points"] > 0 for p in points
            ), "评分点无效。")
            require(len({p["id"] for p in points}) == len(points)
                    and sum(p["points"] for p in points) == part["score"], "评分点重复或分值不守恒。")
            methods = solution["equivalent_methods"]
            require(isinstance(methods, list) and 1 <= len(methods) <= 4 and all(
                isinstance(m, dict) and m.keys() == {"id", "acceptance"}
                and all(text(v) for v in m.values()) for m in methods), "须说明等价答案的接受条件。")
            seen.add(part["id"])
            total += part["score"]
        require(total == request.constraints["total_score"], "综合题总分与请求不符。")
    design = resolve_design(candidate["design"], spans)
    witnesses = candidate.get("calculations", [])
    require(isinstance(witnesses, list) and len(witnesses) <= 16, "计算见证须为最多16项的数组。")
    for w in witnesses:
        require(isinstance(w, dict) and w.keys() == {"kind", "inputs", "result"}, "见证字段无效。")
        require(json.dumps(solve(w["kind"], w["inputs"]), sort_keys=True) == json.dumps(w["result"], sort_keys=True), "数值见证与求解结果不一致。")
    return {**candidate, "design": design, "calculations": witnesses}
