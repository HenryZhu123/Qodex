"""结构化需求修改：会话内版本检查、独立快照和重新组卷。"""
from copy import deepcopy
from .main import assemble_exam


class RequestSession:
    def __init__(self, questions):
        self._questions = deepcopy(questions)
        self._history = []

    @property
    def history(self):
        return deepcopy(self._history)

    def submit(self, request=None, *, changes=None, base_revision=None):
        revision = len(self._history) + 1
        if revision == 1:
            if not isinstance(request, dict) or changes is not None or base_revision is not None:
                raise ValueError("首次提交需要完整 request")
            snapshot = deepcopy(request)
        else:
            if type(base_revision) is not int or base_revision != revision - 1:
                raise ValueError("修改基于旧版本，请先读取最新需求，未执行组卷")
            if request is not None or not isinstance(changes, dict) or not changes:
                raise ValueError("后续提交需要非空 changes")
            allowed = {"subject", "question_type", "question_count", "score_per_question", "total_score",
                       "topic_counts", "difficulty_counts", "max_repair_rounds", "allow_mock_reviews"}
            if set(changes) - allowed:
                raise ValueError("修改包含未知字段或不允许修改的标识")
            snapshot = deepcopy(self._history[-1]["request_snapshot"])
            # 顶层覆盖：知识点及难度字典需完整提供，不隐式调整其他配额。
            snapshot.update(deepcopy(changes))
        result = assemble_exam(snapshot, self._questions)
        previous = self._history[-1] if self._history else None
        entry = {"request_id": snapshot.get("request_id"), "revision": revision,
                 "base_revision": base_revision, "request_snapshot": snapshot,
                 "changes": deepcopy(changes) if changes else {}, "result": result,
                 "replaces_revision": previous["revision"] if previous else None,
                 "current_exam_available": result["status"] == "STRUCTURAL_PASS",
                 "previous_exam_reusable_for_current_request": False,
                 "note": "历史结果仅用于追溯。本次失败时不回退输出旧试卷；未自动修正矛盾要求。"}
        self._history.append(deepcopy(entry))
        return deepcopy(entry)
