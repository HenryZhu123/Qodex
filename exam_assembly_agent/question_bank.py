"""题库读取边界：数据库接入时在这里增加适配器。"""
import json
from pathlib import Path


def load_questions(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    questions = data if isinstance(data, list) else [data]
    if any(not isinstance(q, dict) for q in questions):
        raise ValueError("题库必须是题目对象或对象列表")
    return questions
