"""Material-grounded task designs; structural checks are not semantic proofs."""
from __future__ import annotations

from unicodedata import normalize
from math import isfinite

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


def positive_half_step(value):
    """Positive integers or exact .5 increments (e.g. 0.5, 1, 1.5)."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and value > 0 and round(value * 2) == value * 2)


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


def design_diagnostics(design, student=None):
    reachable = set(design["conclusions"])
    for step in reversed(design["derivation"]):
        if step["id"] in reachable:
            reachable.update(step["uses"])
    return {"unlinked_claims": [c["id"] for c in design["claims"] if c["id"] not in reachable],
            "unlinked_steps": [s["id"] for s in design["derivation"] if s["id"] not in reachable],
            "counterfactual_dependency_unlinked": design["counterfactual"]["given_id"] not in reachable,
            "nonliteral_givens": [] if student is None else [g for g in design["givens"]
                if not contains_given_span(g["text"], visible_text(student))]}


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


def validate_design(design, evidence, student):
    require(isinstance(design, dict) and design.keys() == {
        "target", "concepts", "claims", "givens", "derivation", "conclusions", "counterfactual"
    }, "考查设计字段不完整。")
    require(text(design["target"]) and texts(design["concepts"], 1, 8), "缺少具体学习表现或概念。")
    sources = {e["id"]: e for e in evidence}
    nodes, claims = set(), set()
    require(isinstance(design["claims"], list) and 1 <= len(design["claims"]) <= 12, "须提供材料知识依据。")
    for claim in design["claims"]:
        require(isinstance(claim, dict) and claim.keys() == {"id", "statement", "evidence_id", "quote"}, "知识依据字段无效。")
        require(all(text(v, 2000) for v in claim.values()), "知识依据须为非空文本。")
        require(claim["id"] not in nodes and claim["evidence_id"] in sources, "知识依据ID重复或来源不存在。")
        source = sources[claim["evidence_id"]]
        require(contains_span(claim["quote"], source.get("excerpt", source["summary"])), "知识依据引文未出现在所选原文或摘要中。")
        nodes.add(claim["id"])
        claims.add(claim["id"])
    givens = design["givens"]
    require(isinstance(givens, list) and 1 <= len(givens) <= 12, "须明确列出题设条件。")
    for given in givens:
        require(isinstance(given, dict) and given.keys() == {"id", "text"}
                and text(given["id"], 100) and text(given["text"], 2000), "题设条件字段无效。")
        require(given["id"] not in nodes, "题设ID重复。")
        nodes.add(given["id"])
    derivation = design["derivation"]
    require(isinstance(derivation, list) and 2 <= len(derivation) <= 12, "须给出可检查的解题依赖，步骤数量不代表深度。")
    dependencies = {}
    for step in derivation:
        require(isinstance(step, dict) and step.keys() == {"id", "uses", "result"}
                and text(step["id"], 100) and text(step["result"]), "推导字段无效。")
        require(texts(step["uses"], 1, 12) and len(set(step["uses"])) == len(step["uses"])
                and set(step["uses"]) <= nodes and step["id"] not in nodes, "推导依赖不存在、重复或成环。")
        dependencies[step["id"]] = set(step["uses"])
        nodes.add(step["id"])
    ends = design["conclusions"]
    require(texts(ends, 1, 6) and set(ends) <= dependencies.keys(), "结论须引用推导节点。")
    reachable = set(ends)
    for step in reversed(derivation):
        if step["id"] in reachable:
            reachable.update(step["uses"])
    require(bool(claims & reachable), "结论没有依赖任何材料知识依据。")
    change = design["counterfactual"]
    require(isinstance(change, dict) and change.keys() == {"given_id", "replacement", "effect", "reason"}
            and all(text(v) for v in change.values())
            and change["given_id"] in {g["id"] for g in givens}, "条件变化须指向已有题设并解释结论如何变化。")
    # Unlinked nodes are diagnostic evidence for semantic review, not proof that
    # a correct problem is unusable. Equivalent methods and prerequisite work
    # may legitimately be outside the author's minimal dependency graph.
    return sorted({c["evidence_id"] for c in design["claims"]})


def validate_candidate(candidate, request, evidence):
    require(isinstance(candidate, dict) and candidate.keys() == {
        "student_view", "instructor_view", "design", "calculations"
    }, "候选字段无效。")
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
                and positive_half_step(p["points"]) for p in points
            ), "评分点无效。")
            require(len({p["id"] for p in points}) == len(points)
                    and round(sum(p["points"] for p in points) * 2) == part["score"] * 2,
                    "评分点重复或分值不守恒。")
            methods = solution["equivalent_methods"]
            require(isinstance(methods, list) and 1 <= len(methods) <= 4 and all(
                isinstance(m, dict) and m.keys() == {"id", "acceptance"}
                and all(text(v) for v in m.values()) for m in methods), "须说明等价答案的接受条件。")
            seen.add(part["id"])
            total += part["score"]
        require(total == request.constraints["total_score"], "综合题总分与请求不符。")
    evidence_ids = validate_design(candidate["design"], evidence, student)
    witnesses = candidate["calculations"]
    require(isinstance(witnesses, list) and len(witnesses) <= 16, "计算见证须为最多16项的数组。")
    for w in witnesses:
        require(isinstance(w, dict) and w.keys() == {"kind", "inputs", "result"}, "见证字段无效。")
        import json
        require(json.dumps(solve(w["kind"], w["inputs"]), sort_keys=True) == json.dumps(w["result"], sort_keys=True), "数值见证与求解结果不一致。")
    return evidence_ids
