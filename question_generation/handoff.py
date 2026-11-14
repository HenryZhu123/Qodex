"""Project an authored question package into the exam-checker ``QuestionView`` shape.

The handoff is deliberately lossy in one direction only: it produces the thirteen fields the
review service already declares, and it refuses anything the downstream cannot honestly carry.

Two rules come from the receiving services, not from this module's taste:

* ``reference`` must stay empty. The assembly exporter cannot render a shared parent passage,
  so a non-empty reference is rejected there (``exam_assembly_service.service.convert``).
* ``question_id`` carries the pending version (``<id>-v<n>``). The review-side version store
  inserts on conflict without an update, so re-using an id would silently review an old
  version instead of the new one.

Only four-option single choice is projected. Comprehensive items have parts and scoring
points, and the current bank/assembly contract cannot carry them; refusing here keeps the
gap visible instead of flattening a comprehensive item into something it is not.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .curriculum import AREAS

QUESTION_VIEW_FIELDS = (
    "document_id", "question_id", "question_number", "question_type", "question_text",
    "options", "answer_text", "points", "subject", "paper_title", "section_titles",
    "numbering_path", "numbering_description", "reference",
)

# The bank and the assembly request both use Chinese subject labels; authoring uses slugs.
SUBJECT_LABELS = {
    "data_structures": "数据结构",
    "computer_organization": "计算机组成原理",
    "operating_systems": "操作系统",
    "computer_networks": "计算机网络",
}
AREA_LABELS = {area: label for group in AREAS.values() for area, label in group.items()}


class HandoffError(ValueError):
    """A package that cannot be handed over without misrepresenting it."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _text(value, code: str, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(code, message)
    return value.strip()


def _options(student) -> list[str]:
    options = student.get("options") if isinstance(student, dict) else None
    if not isinstance(options, list) or len(options) != 4:
        raise HandoffError("OPTION_SHAPE", "hand-off 只支持四个选项的单选。")
    if [o.get("id") if isinstance(o, dict) else None for o in options] != list("ABCD"):
        raise HandoffError("OPTION_SHAPE", "选项ID须依次为A、B、C、D。")
    texts = []
    for option in options:
        texts.append(_text(option.get("text"), "OPTION_SHAPE", "选项文本为空。"))
    if len({text.casefold() for text in texts}) != 4:
        raise HandoffError("DUPLICATE_OPTIONS", "选项文本重复，无法唯一定位答案。")
    return texts


def project_package(package, *, document_id=None, question_number="1", points=2, paper_title=None) -> dict:
    """Return one ``QuestionView``-shaped dict for a delivered single-choice package."""
    if not isinstance(package, dict):
        raise HandoffError("PACKAGE_SHAPE", "题包须为JSON对象。")
    if package.get("review_status") != "PENDING":
        raise HandoffError("NOT_DELIVERED", "只有待审（PENDING）题包可以交接。")
    metadata = package.get("metadata")
    student = package.get("student_view")
    teacher = package.get("instructor_view")
    if not isinstance(metadata, dict) or not isinstance(student, dict) or not isinstance(teacher, dict):
        raise HandoffError("PACKAGE_SHAPE", "题包缺少 metadata、student_view 或 instructor_view。")
    kind = metadata.get("question_type")
    if kind != "single_choice":
        raise HandoffError(
            "UNSUPPORTED_QUESTION_TYPE",
            "当前题库与组卷契约只接收四选项单选；综合题需先由组卷侧支持多题型与逐题分值。",
        )
    subject = metadata.get("subject")
    if subject not in SUBJECT_LABELS:
        raise HandoffError("SUBJECT_UNMAPPED", f"未知科目：{subject!r}。")
    stem = _text(student.get("stem"), "STEM_MISSING", "题干为空。")
    options = _options(student)
    correct = teacher.get("correct_option_id")
    if correct not in list("ABCD"):
        raise HandoffError("ANSWER_SHAPE", "教师视图的正确答案不是A-D之一。")
    version = package.get("version", 1)
    if type(version) is not int or version < 1:
        raise HandoffError("VERSION_INVALID", "题包版本须为正整数。")
    question_id = _text(package.get("question_id"), "PACKAGE_SHAPE", "题包缺少 question_id。")
    areas = metadata.get("syllabus_areas") or []
    if not isinstance(areas, list):
        raise HandoffError("SCOPE_SHAPE", "syllabus_areas 须为数组。")
    if type(points) is not int or points < 1:
        raise HandoffError("POINTS_INVALID", "交接分值须为正整数。")
    request_id = package.get("request_id")
    if document_id is None:
        batch = request_id if isinstance(request_id, str) and request_id.strip() else question_id
        document_id = f"pending-{batch}"
    return {
        "document_id": document_id,
        "question_id": f"{question_id}-v{version}",
        "question_number": str(question_number),
        "question_type": "single_choice",
        "question_text": stem,
        # Python 3.9 is still a supported interpreter here, so avoid zip(strict=);
        # _options() already pinned the list to four entries.
        "options": [f"{label}. {options[index]}" for index, label in enumerate("ABCD")],
        "answer_text": options[list("ABCD").index(correct)],
        "points": points,
        "subject": SUBJECT_LABELS[subject],
        "paper_title": paper_title or f"Qodex 待审题包 {document_id}",
        "section_titles": [AREA_LABELS[a] for a in areas if isinstance(a, str) and a in AREA_LABELS],
        "numbering_path": [],
        "numbering_description": "Qodex 生成待审题",
        "reference": "",
    }


def project_result(result, *, document_id=None, points=2, paper_title=None) -> list[dict]:
    """Project every delivered package of one generation result into the same document."""
    if not isinstance(result, dict) or result.get("status") != "GENERATED":
        status = result.get("status") if isinstance(result, dict) else None
        raise HandoffError("NOT_DELIVERED", f"结果不是 GENERATED（实际 {status!r}），不能交接。")
    questions = result.get("questions")
    if not isinstance(questions, list) or not questions:
        raise HandoffError("NOT_DELIVERED", "结果没有题包。")
    if document_id is None:
        request_id = result.get("request_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise HandoffError("PACKAGE_SHAPE", "结果缺少 request_id，无法确定文档标识。")
        document_id = f"pending-{request_id}"
    return [
        project_package({**package, "request_id": result.get("request_id")},
                        document_id=document_id, question_number=str(index + 1),
                        points=points, paper_title=paper_title)
        for index, package in enumerate(questions)
    ]


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"无法读取 {path}：{error}") from error


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="question_generation.handoff",
        description="Project an authored package into exam-checker QuestionView JSON.",
    )
    parser.add_argument("--package", type=Path, required=True, help="题包JSON或GENERATED结果JSON")
    parser.add_argument("--document-id", default=None, help="默认 pending-<request_id>")
    parser.add_argument("--points", type=int, default=2)
    parser.add_argument("--paper-title", default=None)
    parser.add_argument("--out", type=Path, default=None, help="默认打印到标准输出")
    args = parser.parse_args(argv)
    payload = _load(args.package)
    try:
        if isinstance(payload, dict) and "questions" in payload:
            views = project_result(payload, document_id=args.document_id, points=args.points,
                                   paper_title=args.paper_title)
        else:
            views = [project_package(payload, document_id=args.document_id, points=args.points,
                                     paper_title=args.paper_title)]
    except HandoffError as error:
        print(json.dumps({"status": "HANDOFF_REFUSED", "code": error.code, "message": str(error)},
                         ensure_ascii=False))
        return 2
    body = json.dumps(
        {
            "document_id": views[0]["document_id"],
            "paper_title": views[0]["paper_title"],
            # The review service takes subject from the document, so it must travel here.
            "subject": views[0]["subject"],
            "questions": views,
        },
        ensure_ascii=False,
        indent=1,
    )
    if args.out is None:
        print(body)
    else:
        args.out.write_text(body + "\n", encoding="utf-8")
        print(json.dumps({"status": "PROJECTED", "count": len(views), "out": str(args.out),
                          "document_id": views[0]["document_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
