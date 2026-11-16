"""Ordered mixed-paper plans. Every slot is matched to an immutable accepted record."""
import asyncio
from copy import deepcopy
from html import escape
import json
from pathlib import Path
import re
from uuid import uuid4

from exam_assembly_agent.similarity import decisions_template, review_packet, screen, validate_human_decisions
from .repository import BankError, verified_state
from .semantic_selection import screened_questions, select_reviewed


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def positive(value):
    return type(value) in (int, float) and 0 < value <= 150


def convert_paper(entry, state):
    verified_state(entry, state)
    payload = entry["question_json"]
    if any(payload.get(key) != entry[key] for key in ("task_id", "question_id", "version")):
        raise ValueError("来源身份不一致")
    q, meta = payload["question"], payload["metadata"]
    if not nonempty(q.get("question_text")) or not nonempty(q.get("subject")) or not positive(q.get("points")):
        raise ValueError("题干、学科或原始分值缺失")
    knowledge = meta.get("knowledge_points")
    if not isinstance(knowledge, list) or not knowledge or any(not nonempty(k) for k in knowledge):
        raise ValueError("知识点标签无效")
    if meta.get("difficulty") not in ("easy", "medium", "hard"):
        raise ValueError("难度标签无效")
    reference = q.get("reference", "")
    if not isinstance(reference, str):
        raise ValueError("参考材料必须为文本")
    # Do not silently discard images or turn remote resources into executable HTML.
    if re.search(r"!\[|<\s*(?:img|svg|iframe)\b", reference + q["question_text"], re.I):
        raise ValueError("包含图像材料，须先接入受控资源渲染")
    raw_question_type = q.get("question_type")
    # Deterministic comprehensive questions are stored as comprehensive_application;
    # the v2 paper contract exposes one comprehensive slot type. Normalise at the
    # boundary instead of making callers know the authoring sub-type.
    question_type = "comprehensive" if raw_question_type == "comprehensive_application" else raw_question_type
    result = dict(question_id=entry["record_id"], subject=q["subject"],
                  question_type=question_type, score=q["points"],
                  stem=q.get("student_stem") or q["question_text"], reference=reference,
                  knowledge_points=knowledge, difficulty=meta["difficulty"], options={}, parts=[])
    if not nonempty(result["stem"]):
        raise ValueError("学生题干无效")
    if result["question_type"] == "single_choice":
        raw = q.get("options")
        if not isinstance(raw, list) or not 2 <= len(raw) <= 26:
            raise ValueError("单选须有2至26个选项")
        labelled = []
        for label, value in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", raw):
            if not nonempty(value):
                raise ValueError("选项缺失")
            match = re.fullmatch(r"\s*([A-Z])[.．、:：)）]\s*(.+)", value, re.S)
            if match and match[1] != label:
                raise ValueError("选项标签与顺序不一致")
            labelled.append(bool(match))
            result["options"][label] = match[2].strip() if match else value.strip()
        if any(labelled) != all(labelled) or len(set(result["options"].values())) != len(raw):
            raise ValueError("选项重复或标签混用")
        answer = q.get("answer_text")
        if answer not in result["options"]:
            matched = [key for key, value in result["options"].items() if value == answer]
            if len(matched) != 1:
                raise ValueError("缺少唯一匹配的单选答案")
            answer = matched[0]
        result.update(answer=answer, explanation=q.get("explanation") or payload.get("explanation") or "")
    elif result["question_type"] == "comprehensive":
        parts, grading = q.get("parts"), deepcopy(q.get("grading"))
        if not isinstance(parts, list) or not 1 <= len(parts) <= 20 or not isinstance(grading, dict):
            raise ValueError("综合题缺少结构化小问和评分；旧快照须重新导入并审校，不能猜测")
        # Deterministic comprehensive answers are numeric; the export layer renders
        # text, so normalise the expected value without changing the stored snapshot.
        for solution in grading.get("parts", []):
            if isinstance(solution, dict):
                for point in solution.get("scoring_points", []):
                    expected = point.get("expected") if isinstance(point, dict) else None
                    if expected is not None and not isinstance(expected, str):
                        # Deterministic answers may be numbers, dicts (for structured
                        # witnesses) or booleans; the HTML renderer needs text.
                        point["expected"] = json.dumps(expected, ensure_ascii=False, sort_keys=True)
        solutions = grading.get("parts")
        if not isinstance(solutions, list) or len(parts) != len(solutions):
            raise ValueError("小问答案数量不一致")
        seen = set()
        for part, solution in zip(parts, solutions, strict=True):
            if (not isinstance(part, dict) or not nonempty(part.get("id")) or part["id"] in seen
                    or not nonempty(part.get("prompt")) or not positive(part.get("score"))
                    or not isinstance(solution, dict) or solution.get("part_id") != part["id"]
                    or not nonempty(solution.get("solution"))):
                raise ValueError("小问题面、分值或解答无效")
            points = solution.get("scoring_points")
            if (not isinstance(points, list) or not points
                    or any(not isinstance(p, dict) or not positive(p.get("points"))
                           or not nonempty(p.get("id")) or not nonempty(p.get("criterion"))
                           or not (nonempty(p.get("expected")) or type(p.get("expected")) in (int, float))
                           for p in points)
                    or len({p["id"] for p in points}) != len(points)
                    or sum(p["points"] for p in points) != part["score"]):
                raise ValueError("评分点分值与小问不一致")
            seen.add(part["id"])
        if sum(part["score"] for part in parts) != result["score"]:
            raise ValueError("小问分值之和与题目总分不一致")
        if not nonempty(grading.get("grading_policy")):
            raise ValueError("综合题缺少评分规则")
        for index, solution in enumerate(solutions):
            dependencies = solution.get("depends_on", [])
            methods = solution.get("equivalent_methods", [])
            if (not isinstance(dependencies, list) or any(not isinstance(d, str) for d in dependencies)
                    or not set(dependencies) <= {p["id"] for p in parts[:index]}
                    or not isinstance(methods, list)
                    or any(not isinstance(m, dict) or not nonempty(m.get("acceptance")) for m in methods)):
                raise ValueError("小问依赖或等价方法无效")
        if any(re.search(r"!\[|<\s*(?:img|svg|iframe)\b", part["prompt"], re.I) for part in parts):
            raise ValueError("小问包含尚未接入渲染的图片")
        result.update(parts=deepcopy(parts), answer=deepcopy(grading), explanation="")
    else:
        raise ValueError("不支持的题型")
    if not isinstance(result["explanation"], str):
        raise ValueError("解析必须是文本")
    return result


def matches(slot, q):
    return (slot["subject"] == q["subject"] and slot["question_type"] == q["question_type"]
            and slot["score"] == q["score"]
            and (not slot.get("knowledge_point") or slot["knowledge_point"] in q["knowledge_points"])
            and (not slot.get("difficulty") or slot["difficulty"] == q["difficulty"])
            and (not slot.get("part_scores") or slot["part_scores"] == [p["score"] for p in q["parts"]]))


def allocate(slots, questions):
    edges = [[i for i, q in enumerate(questions) if matches(slot, q)] for slot in slots]
    owners = {}
    def augment(slot, visited):
        for candidate in edges[slot]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in owners or augment(owners[candidate], visited):
                owners[candidate] = slot
                return True
        return False
    for index in sorted(range(len(slots)), key=lambda i: len(edges[i])):
        augment(index, set())
    return {slot: questions[candidate] for candidate, slot in owners.items()}


def export_paper(request, students, answers, folder):
    """Escaped text-only HTML, with separate student and teacher content."""
    paths = {}
    for teacher, name in ((False, "student_exam"), (True, "answer_key")):
        blocks, previous = [], None
        for number, (q, a) in enumerate(zip(students, answers, strict=True), 1):
            if q["question_type"] != previous:
                blocks.append(f'<h2>{"单项选择题" if q["question_type"] == "single_choice" else "综合应用题"}</h2>')
                previous = q["question_type"]
            blocks.append(f'<section><h3>{number}. {escape(q["subject"])}（{q["score"]}分）</h3>')
            if not teacher:
                for text in (q["reference"], q["stem"]):
                    if text:
                        blocks.append(f'<div class="text">{escape(text)}</div>')
                blocks.extend(f'<p>{key}. {escape(value)}</p>' for key, value in q["options"].items())
                blocks.extend(f'<p>（{i}）（{p["score"]}分）{escape(p["prompt"])}</p>'
                              for i, p in enumerate(q["parts"], 1))
            elif q["question_type"] == "single_choice":
                blocks.append(f'<p>答案：{escape(a["answer"])}</p><div class="text">{escape(a["explanation"])}</div>')
            else:
                grading = a["answer"]
                blocks.append(f'<p>{escape(str(grading.get("grading_policy", "")))}</p>')
                for i, (p, solution) in enumerate(zip(q["parts"], grading["parts"], strict=True), 1):
                    blocks.append(f'<h4>（{i}）（{p["score"]}分）</h4><div class="text">{escape(solution["solution"])}</div>')
                    for point in solution["scoring_points"]:
                        blocks.append(f'<p>{point["points"]}分：{escape(point["criterion"])} — {escape(point["expected"])}</p>')
                    for method in solution.get("equivalent_methods", []):
                        blocks.append(f'<p>等价方法：{escape(str(method.get("acceptance", "")))}</p>')
                    if solution.get("depends_on"):
                        blocks.append(f'<p>依赖小问：{escape(", ".join(solution["depends_on"]))}</p>')
            blocks.append('</section>')
        heading = request["request_id"] + (" · 答案与评分" if teacher else " · 学生试卷")
        html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                f'<title>{escape(heading)}</title><style>body{{font-family:"Microsoft YaHei",sans-serif;max-width:800px;margin:40px auto;padding:24px;line-height:1.8;color:#242424}}'
                '.text{white-space:pre-wrap}section{margin:24px 0}h2{border-bottom:1px solid #ccc}p{white-space:pre-wrap}'
                '@page{size:A4;margin:18mm}@media print{body{margin:0;padding:0}h3,h4{break-after:avoid}}</style>'
                f'<h1>{escape(heading)}</h1><p>共{len(students)}题 · 满分{request["total_score"]}分</p>'
                + ('<p>教师用答案，与学生卷分开保存。</p>' if teacher else '<p>姓名：____________　学号：____________</p>')
                + ''.join(blocks) + '</html>')
        path = folder / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        paths[name + "_html"] = str(path.resolve())
    return paths


async def assemble_paper(request, repository, output_root, history=None, semantic_reviewer=None):
    slots = request["slots"]
    result = dict(schema_version="2.0", request_id=request["request_id"], mode="POSTGRES_QUESTION_BANK_API",
                  status="UNRESOLVED", rejected_records=[], artifacts={}, pool_complete=True,
                  note="仅核验结构、原分值、PASS版本与字面重复；不认证完整语义质量。HTML可在浏览器打印为PDF。")
    entries, conflicts, searched = {}, set(), set()
    for slot in slots:
        query_types = [slot["question_type"]]
        if slot["question_type"] == "comprehensive":
            # Older deterministic comprehensive questions carry this sub-type.
            query_types.append("comprehensive_application")
        for query_type in query_types:
            search = dict(subject=slot["subject"], question_type=query_type,
                          topic_counts={slot.get("knowledge_point") or "": 1},
                          difficulty_counts={slot["difficulty"]: 1} if slot.get("difficulty") else {"": 1})
            search_key = json.dumps(search, sort_keys=True)
            if search_key in searched:
                continue
            searched.add(search_key)
            page, complete = await repository.search_candidates(search)
            result["pool_complete"] &= complete
            for entry in page:
                identifier = entry.get("record_id") if isinstance(entry, dict) else None
                if not nonempty(identifier):
                    result["rejected_records"].append(dict(record_id=None, reason="无效记录身份"))
                    continue
                if identifier in entries and entries[identifier] != entry:
                    conflicts.add(identifier)
                entries[identifier] = entry
    if len(entries) > 2000:
        result["pool_complete"] = False
        result["candidate_budget"] = 2000
        entries = dict(list(entries.items())[:2000])
    questions, sources = [], {}
    async def read(entry):
        try:
            state = await repository.state(entry)
            return convert_paper(entry, state)
        except (BankError, KeyError, ValueError, TypeError, AttributeError) as exc:
            return exc
    usable = [e for key, e in entries.items() if key not in conflicts]
    for identifier in conflicts:
        result["rejected_records"].append(dict(record_id=identifier, reason="冲突的记录快照"))
    for entry, converted in zip(usable, await asyncio.gather(*(read(e) for e in usable)), strict=True):
        if isinstance(converted, Exception):
            result["rejected_records"].append(dict(record_id=entry["record_id"],
                reason=converted.code if isinstance(converted, BankError) else str(converted)))
            if isinstance(converted, BankError) and converted.status not in (404, 410):
                result["pool_complete"] = False
        else:
            questions.append(converted)
            sources[converted["question_id"]] = entry
    allocated = allocate(slots, questions)
    if len(allocated) != len(slots):
        result["status"] = "NEEDS_QUESTIONS" if result["pool_complete"] else "UNRESOLVED"
        result["deficits"] = [dict(position=i+1, **slot) for i, slot in enumerate(slots) if i not in allocated]
        result["message"] = "缺口为当前候选池的一种联合补题方案，未生成残缺试卷。"
    else:
        selected = [allocated[i] for i in range(len(slots))]
        semantic = None
        if request.get("semantic_review"):
            reviewed, semantic, semantic_pending, semantic_questions = await select_reviewed(
                request, questions, sources, allocate, semantic_reviewer)
            if reviewed is not None:
                selected = reviewed
            result["semantic_review"] = semantic
            result["note"] = "语义题对复核不等于全卷质量认证，判断依据及替换过程见semantic_review。"
        # Include materials and all subquestions in the existing lexical screen.
        screened = screened_questions(selected, sources)
        audit = screen(screened)
        accepted, errors = validate_human_decisions(screened, request.get("similarity_decisions", []))
        pending = [p for p in audit["flagged_pairs"] if p["classification"] == "CONFIRMED_DUPLICATE"
                   or accepted.get(p["pair_id"], {}).get("verdict") != "DISTINCT"]
        # A supplied DUPLICATE decision remains binding even if the lexical heuristic did not flag it.
        pending += [d for d in accepted.values() if d["verdict"] in ("DUPLICATE", "UNRESOLVED")]
        audit.update(status="INVALID_OR_STALE_DECISIONS" if errors else "NEEDS_REVIEW" if pending else "NO_PENDING_LEXICAL_FLAGS",
                     errors=errors)
        result["similarity_review"] = audit
        if semantic is not None:
            errors = semantic["errors"]
            pending = semantic_pending
            if semantic["status"] != "SEMANTIC_REVIEW_PASS":
                errors = errors + [semantic["status"]]
                screened = semantic_questions
            else:
                pending = []
            result["similarity_review"] = semantic
        if pending or errors:
            result["message"] = "相似题复核尚未通过；查看复核报告及预算/候选限制，未输出完整试卷。"
            if semantic is not None and semantic["status"] == "NO_CONFLICT_FREE_PAPER_IN_POOL":
                result["status"] = "NEEDS_QUESTIONS" if result["pool_complete"] else "UNRESOLVED"
            result["similarity_review_packet"] = review_packet(screened, pending)
            result["similarity_decisions_template"] = decisions_template(pending)
        else:
            for q in selected:
                try:
                    verified_state(sources[q["question_id"]], await repository.state(sources[q["question_id"]]))
                except (BankError, KeyError, ValueError, TypeError, AttributeError):
                    result["message"] = "导出前来源状态改变或不可访问，请重新组卷。"
                    break
            else:
                students = [{k: deepcopy(v) for k, v in q.items() if k not in ("answer", "explanation")} for q in selected]
                answers = [{k: deepcopy(q[k]) for k in ("question_id", "answer", "explanation")} for q in selected]
                result.update(status="STRUCTURAL_PASS", student_exam=students, answer_key=answers,
                    selected_sources=[{k: sources[q["question_id"]][k] for k in ("record_id", "task_id", "question_id", "version")} for q in selected],
                    validation=dict(passed=True, semantic_quality_certified=False,
                        checks=dict(ordered_slots=True, original_scores=True, current_pass=True, unique_records=True,
                                    semantic_pairs_reviewed=semantic is not None and semantic["coverage_complete"])))
    folder = Path(output_root) / uuid4().hex
    folder.mkdir(parents=True)
    if result["status"] == "STRUCTURAL_PASS":
        result["artifacts"].update(export_paper(request, result["student_exam"], result["answer_key"], folder))
    for key in ("student_exam", "answer_key", "similarity_review_packet", "similarity_decisions_template"):
        if key in result:
            path = folder / f"{key}.json"
            path.write_text(json.dumps(result[key], ensure_ascii=False, indent=2), encoding="utf-8")
            result["artifacts"][key] = str(path.resolve())
    for key, value in (("request", request), ("report", result)):
        result["artifacts"][key] = str((folder / f"{key}.json").resolve())
        (folder / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    result["history"] = await history.save(request, result) if history is not None else {"status": "DISABLED"}
    return {k: v for k, v in result.items() if k not in ("student_exam", "answer_key", "similarity_review_packet", "similarity_decisions_template")}
