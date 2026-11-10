import pytest

from exam_checker.parsing.normalizer import ExamDocumentNormalizer, NormalizationError


def normalize(options, question_type="单项选择题（single_choice）"):
    document = ExamDocumentNormalizer().normalize(
        {"questions": [{"id": "1", "content": "原题干", "options": options,
                        "question_type": question_type, "answer": "B"}]},
        source_file_name="source.pdf", provider_task_id="task-1", markdown="原文",
    )
    return document.nodes["question_1"]


def test_labeled_objects_keep_explicit_label_content_and_answer():
    question = normalize([{"label": "B", "text": "第二项"}, {"label": "A", "text": "第一项"}])
    assert question.options == ["B. 第二项", "A. 第一项"]
    assert question.answer_text == "B"
    assert question.question_text == "原题干"
    assert question.question_type == "single_choice"


def test_string_options_are_not_rewritten_or_given_missing_labels():
    assert normalize(["无标签内容", "B、原文"]).options == ["无标签内容", "B、原文"]


@pytest.mark.parametrize("options", [[{"text": "缺标签"}], [{"label": "A"}], [123], [{"label": "??", "text": "内容"}]])
def test_unsupported_options_fail_instead_of_becoming_dictionary_strings(options):
    with pytest.raises(NormalizationError):
        normalize(options)


@pytest.mark.parametrize("question_type", ["选择题", "多选题", "未知题型"])
def test_ambiguous_types_are_not_assumed_single_choice(question_type):
    assert normalize([], question_type).question_type == question_type
