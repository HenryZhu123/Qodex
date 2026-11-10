import asyncio
import json
from pathlib import Path
import re
from uuid import uuid4

from exam_assembly_agent.exam_export import export_exam
from exam_assembly_agent.main import validate_request
from exam_assembly_agent.similarity_assembly import assemble_with_similarity
from .repository import QuestionBankRepository, verified_state
from .replenishment import propose_replenishment


def convert(entry, state, request):
    review_id = verified_state(entry, state)
    payload = entry["question_json"]
    q, meta = payload["question"], payload["metadata"]
    if (payload.get("document_id") != entry["document_id"]
            or payload.get("question_id") != entry["question_id"]):
        raise ValueError("题目来源标识不一致")
    if q.get("subject") != request["subject"] or q.get("question_type") != "single_choice":
        raise ValueError("学科或题型不匹配；目前生产接口仅支持 single_choice")
    points = q.get("points")
    if type(points) not in (int, float) or points != request["score_per_question"]:
        raise ValueError("题目原始分值不匹配，不自动修改分值")
    raw_options = q.get("options")
    if not isinstance(raw_options, list) or len(raw_options) != 4:
        raise ValueError("需要四个完整文本选项")
    options, labelled = {}, []
    for label, raw in zip("ABCD", raw_options):
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("选项内容缺失")
        match = re.fullmatch(r"\s*([A-D])[.．、:：)）]\s*(.+)", raw, re.DOTALL)
        labelled.append(bool(match))
        if match and match[1] != label:
            raise ValueError("选项标签顺序不一致")
        options[label] = match[2].strip() if match else raw.strip()
    if (any(labelled) and not all(labelled)) or len(set(options.values())) != 4:
        raise ValueError("选项标签混用或内容重复")
    answer = q.get("answer_text", "").strip()
    if answer not in options:
        matches = [label for label, text in options.items() if text == answer]
        if len(matches) != 1:
            raise ValueError("答案必须是单个 A-D 或唯一匹配的选项全文")
        answer = matches[0]
    knowledge = meta.get("knowledge_points")
    if not isinstance(knowledge, list) or any(not isinstance(k, str) for k in knowledge):
        raise ValueError("知识点标签无效")
    topics = [k for k, count in request["topic_counts"].items() if count and k in knowledge]
    if not topics or meta.get("difficulty") not in request["difficulty_counts"]:
        raise ValueError("知识点或难度标签不匹配")
    if not isinstance(q.get("question_text"), str) or not q["question_text"].strip():
        raise ValueError("缺少题干")
    if q.get("reference"):
        # Current document exporter cannot render parent passages or source images.
        raise ValueError("包含参考材料，尚不支持完整渲染，不能输出残缺题面")
    return dict(question_id=entry["record_id"], version=entry["source_version_id"],
                subject=q["subject"], question_type="single_choice", topic=topics[0],
                eligible_topics=topics, knowledge_points=knowledge, difficulty=meta["difficulty"],
                score=int(points), stem=q["question_text"], options=options, answer=answer,
                explanation=q.get("explanation") or payload.get("explanation") or "",
                provenance={k: entry[k] for k in ("record_id", "document_id", "question_id", "source_version_id")},
                review={"status": "PASS", "question_version": entry["source_version_id"],
                        "is_mock": False, "review_id": review_id})


async def assemble(request, repository: QuestionBankRepository, output_root: Path, *, pdf=False, public_request=None,
                   similarity_decisions=None):
    errors = validate_request(request)
    if request.get("question_type") != "single_choice":
        errors.append("目前仅支持四选项 single_choice；多题型不能静默转换")
    if request.get("allow_mock_reviews"):
        errors.append("生产接口不接受模拟审校记录")
    if request.get("question_count", 0) > 100:
        errors.append("本次题数上限为 100")
    if errors:
        return {"status": "INVALID_REQUEST", "errors": errors, "mode": "POSTGRES_QUESTION_BANK_API"}
    entries, complete = await repository.search_candidates(request)
    questions, rejected, sources = [], [], {}
    states = await asyncio.gather(*(repository.state(e) for e in entries))
    for entry, state in zip(entries, states):
        try:
            question = convert(entry, state, request)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            rejected.append({"record_id": entry.get("record_id"), "reason": str(exc)})
        else:
            questions.append(question)
            sources[question["question_id"]] = entry
    result = await asyncio.to_thread(assemble_with_similarity, request, questions, decisions=similarity_decisions)
    result.update(schema_version="1.0", mode="POSTGRES_QUESTION_BANK_API", pool_complete=complete,
                  rejected_records=rejected, artifacts={},
                  note="真实题库接口；已核对版本和 PASS，已接入字面相似筛查及内容绑定人工复核。未认证完整语义去重，未检测跨题提示。")
    if result["status"] == "INCOMPLETE" or (not complete and result["status"] == "NEEDS_QUESTIONS"):
        result.update(status="UNRESOLVED", message="候选查询达到接口上限或搜索预算不足，不能断言全库缺题。")
    # The engine can return NEEDS_QUESTIONS even when every marginal deficit is zero.
    # Compute an explicit partial allocation before asking other agents for new items.
    if result["status"] == "NEEDS_QUESTIONS":
        excluded_indexes = {item["index"] for item in result.get("excluded_questions", [])}
        eligible_questions = [q for index, q in enumerate(questions) if index not in excluded_indexes]
        forbidden = {frozenset(pair) for pair in result.get("confirmed_duplicate_pairs", [])}
        plan = await asyncio.to_thread(propose_replenishment, request, eligible_questions, forbidden_pairs=forbidden)
        result["replenishment_request"] = plan
        result["deficits"] = plan["deficits"]
        result["deficit_semantics"] = "PROPOSED_JOINT_COMPLETION_NOT_ADDITIONAL_MARGINAL_TOTALS"
    elif result["status"] == "UNRESOLVED":
        result.pop("replenishment_request", None)
    if result["status"] == "STRUCTURAL_PASS":
        selected = {q["question_id"]: q for q in questions}
        result["selected_sources"] = [selected[q["question_id"]]["provenance"] for q in result["student_exam"]]
        # Re-read selected sources just before export; a concurrent revision invalidates output.
        for q in result["student_exam"]:
            entry = sources[q["question_id"]]
            try:
                verified_state(entry, await repository.state(entry))
            except (KeyError, ValueError, TypeError, AttributeError):
                result.update(status="UNRESOLVED", message="选题后源题发生变化，请重新组卷。")
                result.pop("student_exam", None)
                result.pop("answer_key", None)
                break
    folder = output_root / uuid4().hex
    folder.mkdir(parents=True)
    for key in ("similarity_review_packet", "similarity_decisions_template"):
        if key in result:
            path = folder / f"{key}.json"
            path.write_text(json.dumps(result[key], ensure_ascii=False, indent=2), encoding="utf-8")
            result["artifacts"][key] = str(path.resolve())
    if "replenishment_request" in result:
        path = folder / "replenishment_request.json"
        path.write_text(json.dumps(result["replenishment_request"], ensure_ascii=False, indent=2), encoding="utf-8")
        result["artifacts"]["replenishment_request"] = str(path.resolve())
    if result["status"] == "STRUCTURAL_PASS":
        result["artifacts"].update(await asyncio.to_thread(export_exam, request, result, folder, pdf=pdf))
        for name in ("student_exam", "answer_key"):
            path = folder / f"{name}.json"
            path.write_text(json.dumps(result[name], ensure_ascii=False, indent=2), encoding="utf-8")
            result["artifacts"][name] = str(path.resolve())
    request_path, report_path = folder / "request.json", folder / "report.json"
    result["artifacts"].update(request=str(request_path.resolve()), report=str(report_path.resolve()))
    request_path.write_text(json.dumps(public_request if public_request is not None else request,
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # Teacher answers stay in separate artifacts; tool response contains paths and validation.
    return {key: value for key, value in result.items() if key not in (
        "student_exam", "answer_key", "similarity_review_packet", "similarity_decisions_template")}
