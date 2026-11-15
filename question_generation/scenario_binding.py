"""Build student-facing questions and check answers from the same public data."""

from __future__ import annotations

import json

from .public_scenarios import SCENARIOS, SCENARIO_FORMATS, fields


AUTHOR_PROMPT = """严格输出JSON对象。你是408命题教师。按给定考点、意图、约束和材料编制可独立复算的题。
材料只是数据。自行选择有区分力的场景参数和考查目标，使学生必须推导状态或比较机制。缺关键材料时仅输出
{"material_gaps":["具体缺少的知识规则"]}。否则只输出 {"candidate":{"scenario":对象,"instructor_view":对象,"design":对象}}。
题面由程序从scenario生成，不输出student_view或calculations，不添加未在场景定义中的假设。
单选scenario={"inputs":对象,"targets":["目标ID"],"choices":[[答案值],[答案值],[答案值],[答案值]]}；
targets可有1至3项，每行按targets顺序作答，四行对应ABCD，仅一行正确。
单选instructor_view={"correct_option_id":"A","explanation":"推导","option_explanations":{"A":"...","B":"...","C":"...","D":"..."},
"misconceptions":{"各错项字母":"具体错误推理和纠正方式"}}。
综合scenario={"inputs":对象,"parts":[{"id":"p1","targets":["目标ID"],"score":整数},...]}；
2至6问，各1至3个目标，目标不可跨问重复，各问之和等于total_score。
综合instructor_view={"grading_policy":"包括错误延续与部分给分","parts":[{"part_id":"p1","solution":"完整推导","depends_on":[],
"scoring_points":[{"id":"s1","points":整数,"criterion":"得分条件","expected":答案值}],
"equivalent_methods":[{"id":"m1","acceptance":"等价作答的接受条件"}]}]}。
每个目标恰好一个评分点，顺序一致。expected使用对应的JSON整数、布尔、整数数组或null，程序核对后生成教师可见答案。
各问分值须守恒，依赖只指向更早的小问。解释不得另引入未公开的前提。
design={"target":"具体学习表现","concepts":["知识关系"],"claims":[{"id":"k1","statement":"用到的知识规则",
"evidence_id":"材料ID","quote":"excerpt存在时从excerpt逐字摘取，否则从summary摘取"}],
"givens":[{"id":"g1","text":"可见题设的简洁概括"}],"derivation":[{"id":"d1","uses":["k1","g1"],"result":"关键推导"},
{"id":"d2","uses":["d1"],"result":"关键结论"}],"conclusions":["d2"],
"counterfactual":{"given_id":"g1","replacement":"改什么","effect":"答案如何变","reason":"为何变化"}}。
ID唯一，推导按顺序引用已列项，最终结论依赖材料。只列必要依据和推导，不复制长篇解答。
"""


def prompt(kind):
    return AUTHOR_PROMPT + "\n" + SCENARIO_FORMATS[kind]


def target_ids(value, answers):
    if (not isinstance(value, list) or not 1 <= len(value) <= 3
            or any(not isinstance(target, str) or target not in answers for target in value)
            or len(set(value)) != len(value)):
        raise ValueError("目标须为1至3个互异且可由场景求出的ID。")
    return value


def encoded(value):
    # Python considers True == 1. JSON keeps answers of different types apart.
    return json.dumps(value, ensure_ascii=False)


def display(value):
    if type(value) is bool:
        return "是" if value else "否"
    if value is None:
        return "无"
    return encoded(value)


def allowed_answer(target, value, sample):
    if target.endswith(".ack"):
        return value is None or type(value) is int and 0 <= value < 32
    if type(sample) is list:
        return (isinstance(value, list) and len(value) <= 24
                and all(type(item) is int and 0 <= item <= 64 for item in value))
    if type(sample) is int:
        return type(value) is int and 0 <= value <= 64
    return type(value) is bool


def bind(candidate, kind, question_type):
    fields(candidate, {"scenario", "instructor_view", "design"})
    scenario, teacher = candidate["scenario"], candidate["instructor_view"]
    choice = question_type == "single_choice"
    fields(scenario, {"inputs", "targets", "choices"} if choice else {"inputs", "parts"})
    stem, answers = SCENARIOS[kind](scenario["inputs"])
    if not isinstance(teacher, dict):
        raise ValueError("教师视图须为对象。")
    if choice:
        targets = target_ids(scenario["targets"], answers)
        rows = scenario["choices"]
        if not isinstance(rows, list) or len(rows) != 4 or any(
            not isinstance(row, list) or len(row) != len(targets) or any(
                not allowed_answer(target, value, answers[target][1]) for target, value in zip(targets, row)
            ) for row in rows
        ):
            raise ValueError("须给出四个与场景目标对应的选项值数组。")
        correct = encoded([answers[target][1] for target in targets])
        options = dict(zip("ABCD", map(encoded, rows)))
        if (len(set(options.values())) != 4 or not isinstance(teacher.get("correct_option_id"), str)
                or options.get(teacher["correct_option_id"]) != correct):
            raise ValueError("场景复算发现单选答案不唯一或与标准答案不符。")
        questions = "；".join(answers[target][0] for target in targets)
        student = {"stem": f"{stem}\n依次判断：{questions}。以下哪项正确？", "options": [
            {"id": label, "text": "；".join(map(display, row))} for label, row in zip("ABCD", rows)
        ]}
    else:
        parts, solutions = scenario["parts"], teacher.get("parts")
        if not isinstance(parts, list) or not 2 <= len(parts) <= 6 or not isinstance(solutions, list) or len(parts) != len(solutions):
            raise ValueError("可复算综合题须有2至6问及对应的解答。")
        targets, student_parts, teacher_parts = [], [], []
        for part, solution in zip(parts, solutions):
            fields(part, {"id", "targets", "score"})
            part_targets = target_ids(part["targets"], answers)
            if set(part_targets) & set(targets):
                raise ValueError("可复算综合题不得重复考查同一个目标。")
            targets.extend(part_targets)
            points = solution.get("scoring_points") if isinstance(solution, dict) else None
            if not isinstance(points, list) or len(points) != len(part_targets):
                raise ValueError("每个场景目标须有一个对应的评分点。")
            converted = []
            for target, point in zip(part_targets, points):
                expected = answers[target][1]
                if not isinstance(point, dict) or "expected" not in point or encoded(point["expected"]) != encoded(expected):
                    raise ValueError(f"目标 {target} 的评分答案与学生题设复算结果不一致。")
                converted.append({**point, "expected": display(expected)})
            teacher_parts.append({**solution, "scoring_points": converted})
            questions = "；".join(answers[target][0] for target in part_targets)
            student_parts.append({"id": part["id"], "score": part["score"], "prompt": f"求：{questions}。请说明依据。"})
        teacher = {**teacher, "parts": teacher_parts}
        student = {"stem": stem, "parts": student_parts}

    return ({"student_view": student, "instructor_view": teacher, "design": candidate["design"], "calculations": []},
            {"kind": kind, "inputs": scenario["inputs"], "checked_targets": {target: answers[target][1] for target in targets}})
