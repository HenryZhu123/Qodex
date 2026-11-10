"""Replay regressions through normal entry points without live model calls."""
from copy import deepcopy
from unittest import TestCase

import test_question_generation_general as general
from question_generation import scenario_binding
from question_generation.general_authoring import AUDIT_PROMPT, READER_PROMPT
from question_generation.public_scenarios import pipeline, selective_repeat


PIPELINE_INPUTS = {
    "instructions": [
        {"op": "load", "dest": 1, "sources": [2]},
        {"op": "alu", "dest": 3, "sources": [1, 4]},
        {"op": "alu", "dest": 5, "sources": [3, 1]},
        {"op": "alu", "dest": 6, "sources": [5, 3]},
        {"op": "alu", "dest": 8, "sources": [6, 5]},
    ],
    "write_before_read": False,
    "forwarding": ["none", "full"],
}


def sr_inputs(width=4, policy="receive_base_minus_one"):
    packets = [*range(width), 0, *range(width, 8 if width == 5 else width + 1)]
    return {"modulus": 8, "window": width, "outside_ack": policy,
            "events": [{"packet": packet, "ack_lost": i == 0} for i, packet in enumerate(packets)]}


def make_case(kind):
    source = next(c for c in general.CASES if c["request"]["question_type"] == (
        "comprehensive" if kind == "pipeline" else "single_choice"))
    case = deepcopy(source)
    request, candidate = case["request"], case["candidate"]
    request["topic"] = f"public_{kind}"
    request["request_id"] = f"public-{kind}-regression"
    settings = request["constraints"]["authoring"]
    if kind == "pipeline":
        request["subject"] = "computer_organization"
        settings["syllabus_areas"] = ["co.cpu"]
        statement = "ID在WB次周期才能读到新值，转发只在对应流水寄存器持有该值时可用。"
        given = "ID 最早在 WB 的下一周期读到新值"
        scenario = {
            "inputs": deepcopy(PIPELINE_INPUTS),
            "parts": [{"id": "p1", "targets": ["full.ex", "full.total"], "score": 6},
                      {"id": "p2", "targets": ["none.total"], "score": 4}],
        }
        teacher = {"grading_policy": "逐项给分，允许按前问数据一致推导。", "parts": [
            {"part_id": "p1", "solution": "全转发的 EX 周期为 3、5、7、9、11，最后 WB 为 13。",
             "depends_on": [], "scoring_points": [
                 {"id": "s1", "points": 4, "criterion": "给出最早 EX 周期", "expected": [3, 5, 7, 9, 11]},
                 {"id": "s2", "points": 2, "criterion": "给出最后写回周期", "expected": 13}],
             "equivalent_methods": [{"id": "m1", "acceptance": "接受正确周期表。"}]},
            {"part_id": "p2", "solution": "每个相邻 RAW 需等待三拍，最后 WB 为 21。",
             "depends_on": [], "scoring_points": [
                 {"id": "s1", "points": 4, "criterion": "给出最后写回周期", "expected": 21}],
             "equivalent_methods": [{"id": "m1", "acceptance": "接受按指令逐项列时序。"}]},
        ]}
    else:
        request["subject"] = "computer_networks"
        settings["syllabus_areas"] = ["cn.transport"]
        statement = "选择重传逐个确认分组，只有连续确认窗口头部才允许发送窗口前移。"
        given = "回（当前接收窗口基号−1）模 M"
        scenario = {
            "inputs": sr_inputs(), "targets": ["e5.ack", "e5.send_base", "e6.sent"],
            "choices": [[0, 4, True], [3, 0, False], [3, 4, True], [None, 0, False]],
        }
        teacher = {"correct_option_id": "B",
                   "explanation": "旧 0 在窗口外，只回 ACK3；缺 ACK0，基号仍为 0，分组 4 不能发送。",
                   "option_explanations": {"A": "把规则替换成回原序号。", "B": "回 ACK3，基号不动。",
                                           "C": "把 ACK3 当作累积确认。", "D": "遗漏了窗口外回 ACK。"},
                   "misconceptions": {"A": "误用另一种 ACK 规则。", "C": "误将选择 ACK 作累积 ACK。",
                                      "D": "误将丢弃分组等同于没有响应。"}}
    settings.update(public_scenario=kind, objective="analyze", focus="根据给定状态和规则比较结果")
    settings.pop("material_query", None)
    request["evidence"] = [{"id": "fixture", "source": "协议测试资料", "version": "1",
                            "anchor": "用到的机制", "summary": statement, "rules": []}]
    design = {
        "target": "检查时序假设对结果的影响", "concepts": ["时序与可见状态"],
        "claims": [{"id": "k1", "statement": statement, "evidence_id": "fixture", "quote": statement}],
        "givens": [{"id": "g1", "text": given}],
        "derivation": [{"id": "d1", "uses": ["k1", "g1"], "result": "推导允许的状态转移"},
                       {"id": "d2", "uses": ["d1"], "result": "再确定请求的结果"}],
        "conclusions": ["d2"],
        "counterfactual": {"given_id": "g1", "replacement": "改用另一种规则",
                           "effect": "关键状态会变化", "reason": "决定当前可见的值"},
    }
    case["candidate"] = {"scenario": scenario, "instructor_view": teacher, "design": design}
    return case


class ScenarioReplay(general.Replay):
    def __init__(self, case):
        super().__init__(case["candidate"])
        self.kind = case["request"]["constraints"]["authoring"]["public_scenario"]
        self.question_type = case["request"]["question_type"]

    def complete(self, system, payload):
        if system == scenario_binding.prompt(self.kind):
            self.calls.append((system, deepcopy(payload)))
            return {"candidate": self.candidate}
        if system == READER_PROMPT:
            self.candidate, _ = scenario_binding.bind(self.candidate, self.kind, self.question_type)
        return super().complete(system, payload)


class PublicScenarioTests(TestCase):
    setUp = general.GeneralContractTests.setUp
    run_case = general.GeneralContractTests.run_case

    def run_scenario(self, case):
        return self.run_case(case, ScenarioReplay(case))

    def test_pipeline_student_and_scoring_values_use_same_configuration(self):
        case = make_case("pipeline")
        result, model = self.run_scenario(case)
        self.assertEqual(result["status"], "GENERATED", result)
        question, = result["questions"]
        self.assertEqual(question["generator"]["version"], "general-authoring-v0.5-public-v1")
        self.assertIn("I3：ALU，读 R3、R1，写 R5", question["student_view"]["stem"])
        self.assertIn("WB 的下一周期", question["student_view"]["stem"])
        self.assertIn("配置 full 下各指令进入 EX", question["student_view"]["parts"][0]["prompt"])
        values = question["self_check"]["public_scenario_verification"]["checked_targets"]
        self.assertEqual(values, {"full.ex": [3, 5, 7, 9, 11], "full.total": 13, "none.total": 21})
        self.assertEqual(question["instructor_view"]["parts"][0]["scoring_points"][1]["expected"], "13")
        blind_prompt, blind = model.calls[1]
        self.assertEqual(blind_prompt, READER_PROMPT)
        self.assertEqual(blind, {"question_type": "comprehensive", "student_view": question["student_view"]})
        audit_prompt, audit = model.calls[2]
        self.assertEqual(audit_prompt, AUDIT_PROMPT)
        self.assertEqual(audit["public_scenario_verification"], values)

    def test_pipeline_historical_wrong_total_is_rejected_before_blind_reader(self):
        case = make_case("pipeline")
        case["candidate"]["instructor_view"]["parts"][0]["scoring_points"][1]["expected"] = 10
        result, model = self.run_scenario(case)
        self.assertEqual(result["status"], "SELF_CHECK_FAILED")
        self.assertIn("full.total", result["authoring_report"]["details"])
        self.assertEqual(len(model.calls), 1)

    def test_sr_visible_ack_rule_drives_correct_choice_and_progress(self):
        case = make_case("selective_repeat")
        result, model = self.run_scenario(case)
        self.assertEqual(result["status"], "GENERATED", result)
        question, = result["questions"]
        self.assertIn("回（当前接收窗口基号−1）模 M", question["student_view"]["stem"])
        self.assertIn("事件 6：尝试发送编号 4", question["student_view"]["stem"])
        self.assertEqual(question["self_check"]["public_scenario_verification"]["checked_targets"],
                         {"e5.ack": 3, "e5.send_base": 0, "e6.sent": False})
        self.assertEqual(question["student_view"]["options"][1]["text"], "3；0；否")
        self.assertEqual(set(model.calls[1][1]), {"question_type", "student_view"})

        case["request"]["request_id"] += "-different-ack-rule"
        case["candidate"]["scenario"]["inputs"]["outside_ack"] = "packet_sequence"
        result, model = self.run_scenario(case)
        self.assertEqual(result["status"], "SELF_CHECK_FAILED")
        self.assertEqual(len(model.calls), 1)
        case["candidate"]["instructor_view"].update(
            correct_option_id="A", misconceptions={"B": "错用旧规则", "C": "错算 ACK", "D": "漏掉 ACK"})
        result, _ = self.run_scenario(case)
        self.assertEqual(result["status"], "GENERATED", result)
        question, = result["questions"]
        self.assertIn("回收到分组的线上序号", question["student_view"]["stem"])
        self.assertEqual(question["self_check"]["public_scenario_verification"]["checked_targets"],
                         {"e5.ack": 0, "e5.send_base": 4, "e6.sent": True})

    def test_sr_duplicate_payload_is_observable_after_wraparound(self):
        _, answers = selective_repeat(sr_inputs(5))
        self.assertEqual(answers["e9.delivered"][1], [0, 1, 2, 3, 4, 5, 6, 7, 0])

    def test_pipeline_same_cycle_write_changes_finite_schedule(self):
        inputs = {**PIPELINE_INPUTS, "write_before_read": True}
        stem, answers = pipeline(inputs)
        self.assertIn("WB 同周期写后 ID 可以读到新值", stem)
        self.assertEqual(answers["full.ex"][1], [3, 5, 6, 7, 8])
        self.assertEqual(answers["none.total"][1], 17)

    def test_rejects_injected_student_prose_invalid_targets_and_bool_as_int(self):
        mutations = [
            lambda c: c.update(student_view={"stem": "题面给出答案"}),
            lambda c: c["scenario"].update(targets=["e7.sent"]),
            lambda c: c["scenario"]["choices"][1].__setitem__(1, False),
            lambda c: c["scenario"]["choices"].__setitem__(0, [3, 0, False]),
            lambda c: c["scenario"]["inputs"]["events"][0].update(packet=1),
        ]
        for change in mutations:
            case = make_case("selective_repeat")
            change(case["candidate"])
            result, model = self.run_scenario(case)
            self.assertEqual(result["status"], "SELF_CHECK_FAILED", result)
            self.assertEqual(len(model.calls), 1)

    def test_invalid_scenario_kind_rejected_before_model(self):
        case = make_case("selective_repeat")
        model = ScenarioReplay(case)
        case["request"]["constraints"]["authoring"]["public_scenario"] = "missing"
        result, _ = self.run_case(case, model)
        self.assertEqual(result["status"], "INVALID_REQUEST")
        self.assertFalse(model.calls)
