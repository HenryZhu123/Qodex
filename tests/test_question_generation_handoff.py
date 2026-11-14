"""Hand-off projection and failure routing are contracts, so they are tested directly.

Nothing here measures whether an authored question is good; it only fixes what the
downstream services are allowed to receive and how a caller can route a rejection.
"""
import json
import re
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from question_generation.general_authoring import FAILURE_STAGES, failure_payload
from question_generation.handoff import (
    QUESTION_VIEW_FIELDS,
    HandoffError,
    main,
    project_package,
    project_result,
)

PACKAGE = {
    "version": 1,
    "question_id": "authored-0123456789abcdef01234567",
    "review_status": "PENDING",
    "metadata": {
        "subject": "data_structures",
        "topic": "循环队列的入队出队跟踪",
        "question_type": "single_choice",
        "syllabus_areas": ["ds.stack_queue_array"],
        "knowledge_points": ["队空与队满判别"],
    },
    "student_view": {
        "stem": "设循环队列 MAXQSIZE=7，初始 front=rear=0，依次入队 a,b,c。队头到队尾的元素序列是？",
        "options": [
            {"id": "A", "text": "a,b"},
            {"id": "B", "text": "a,b,c"},
            {"id": "C", "text": "b,c"},
            {"id": "D", "text": "c"},
        ],
    },
    "instructor_view": {
        "correct_option_id": "B",
        "explanation": "教师推导。",
        "option_explanations": {"A": "少一个元素。", "B": "正确。", "C": "多出队一次。", "D": "语义混淆。"},
        "misconceptions": {"A": "漏元素。", "C": "多次出队。", "D": "rear 语义。"},
    },
}


def view(**overrides):
    package = deepcopy(PACKAGE)
    package.update(overrides)
    return package


class ProjectionTests(TestCase):
    def test_projects_exactly_the_fields_the_review_service_declares(self):
        projected = project_package(PACKAGE)
        self.assertEqual(tuple(projected), QUESTION_VIEW_FIELDS)
        self.assertEqual(projected["question_type"], "single_choice")
        self.assertEqual(projected["subject"], "数据结构")
        self.assertEqual(projected["section_titles"], ["栈、队列与数组"])
        self.assertEqual(projected["points"], 2)
        self.assertEqual(projected["options"], ["A. a,b", "B. a,b,c", "C. b,c", "D. c"])
        # Conventional answer: the bare option text, which the assembly adapter
        # maps back to a label by unique text match.
        self.assertEqual(projected["answer_text"], "a,b,c")
        self.assertEqual(projected["question_id"], "authored-0123456789abcdef01234567-v1")

    def test_reference_stays_empty_because_the_exporter_cannot_render_material(self):
        # A non-empty reference is rejected by assembly, so the hand-off must not set one.
        self.assertEqual(project_package(PACKAGE)["reference"], "")

    def test_teacher_only_content_is_not_projected(self):
        blob = json.dumps(project_package(PACKAGE), ensure_ascii=False)
        for teacher_only in ("教师推导", "少一个元素", "rear 语义"):
            self.assertNotIn(teacher_only, blob)

    def test_comprehensive_is_refused_instead_of_flattened(self):
        package = view(metadata={**PACKAGE["metadata"], "question_type": "comprehensive"})
        with self.assertRaises(HandoffError) as caught:
            project_package(package)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_QUESTION_TYPE")

    def test_duplicate_option_texts_are_refused(self):
        package = deepcopy(PACKAGE)
        package["student_view"]["options"][2]["text"] = "a,b"
        with self.assertRaises(HandoffError) as caught:
            project_package(package)
        self.assertEqual(caught.exception.code, "DUPLICATE_OPTIONS")

    def test_non_pending_or_unmapped_subject_is_refused(self):
        for package, code in (
            (view(review_status="ACCEPTED"), "NOT_DELIVERED"),
            (view(metadata={**PACKAGE["metadata"], "subject": "chemistry"}), "SUBJECT_UNMAPPED"),
            (view(version=0), "VERSION_INVALID"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(HandoffError) as caught:
                    project_package(package)
                self.assertEqual(caught.exception.code, code)

    def test_result_projection_numbers_questions_inside_one_document(self):
        result = {"status": "GENERATED", "request_id": "req-handoff", "questions": [PACKAGE, PACKAGE]}
        views = project_result(result, points=2)
        self.assertEqual([v["question_number"] for v in views], ["1", "2"])
        self.assertEqual({v["document_id"] for v in views}, {"pending-req-handoff"})
        self.assertEqual(views[0]["paper_title"], "Qodex 待审题包 pending-req-handoff")

    def test_result_projection_refuses_undelivered_status(self):
        with self.assertRaises(HandoffError) as caught:
            project_result({"status": "SELF_CHECK_FAILED", "request_id": "r", "questions": []})
        self.assertEqual(caught.exception.code, "NOT_DELIVERED")


class CommandLineTests(TestCase):
    def test_cli_reports_the_refusal_code_and_a_nonzero_status(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(PACKAGE), encoding="utf-8")
            out = Path(directory) / "handoff.json"
            status = main(["--package", str(path), "--out", str(out)])
            self.assertEqual(status, 0)
            body = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(body["document_id"], "pending-authored-0123456789abcdef01234567")
            self.assertEqual(len(body["questions"]), 1)
            # Without this the review service sees an empty subject and assembly rejects
            # every question for a subject mismatch.
            self.assertEqual(body["subject"], "数据结构")

            path.write_text(json.dumps(view(metadata={**PACKAGE["metadata"],
                                                      "question_type": "comprehensive"})), encoding="utf-8")
            self.assertEqual(main(["--package", str(path), "--out", str(out)]), 2)


class FailureRoutingTests(TestCase):
    def test_every_rejection_stage_has_a_machine_readable_route(self):
        source = (Path(__file__).resolve().parent.parent
                  / "question_generation" / "general_authoring.py").read_text(encoding="utf-8")
        used = set(re.findall(r'rejected\("([^"]+)"', source))
        self.assertEqual(used, set(FAILURE_STAGES))
        for stage, (code, retry, needs) in FAILURE_STAGES.items():
            payload = failure_payload(stage, "SELF_CHECK_FAILED")
            self.assertEqual(payload["code"], code, stage)
            self.assertIn(payload["retry"], ("same_request", "new_request", "no"))
            self.assertIn(payload["needs"], (None, "material", "human"))
            self.assertEqual((payload["retry"], payload["needs"]), (retry, needs), stage)
        self.assertEqual(failure_payload("材料不足", "NEEDS_MATERIAL"),
                         {"code": "material_gap", "status": "NEEDS_MATERIAL",
                          "retry": "new_request", "needs": "material"})

    def test_unknown_stage_degrades_to_a_stop_signal(self):
        self.assertEqual(failure_payload("未分类", "SELF_CHECK_FAILED"),
                         {"code": "unspecified", "status": "SELF_CHECK_FAILED",
                          "retry": "no", "needs": None})
