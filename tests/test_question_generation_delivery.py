"""S3 delivery correctness: option relabeling, tolerance, guards and metadata.

Every model call here is a scripted transport replay. These tests assert the
delivery contract, not authoring quality.
"""
from copy import deepcopy
from typing import Any, cast
from unittest import TestCase

from test_question_generation_general import CASES, GeneralContractTests, Replay

from question_generation.general_authoring import (
    AUTHOR_PROMPT,
    AUTHOR_VIEWS,
    READER_PROMPT,
    delivered_choice_views,
    run,
)
from question_generation.general_contract import (
    content_warnings,
    read_request,
    validate_option_content,
)
from question_generation.replenishment import generate_replenishment
from question_generation.verification import solve


class DeliveryTests(TestCase):
    setUp = GeneralContractTests.setUp
    run_case = GeneralContractTests.run_case


class OptionDeliveryTests(DeliveryTests):
    def test_helper_relabels_student_and_teacher_with_one_mapping(self):
        candidate = CASES[0]['candidate']
        author_text = {o['id']: o['text'] for o in candidate['student_view']['options']}
        student, teacher, mapping = delivered_choice_views(candidate, CASES[0]['request']['seed'])
        delivered = {o['id']: o['text'] for o in student['options']}
        self.assertEqual([o['id'] for o in student['options']], list('ABCD'))
        self.assertEqual(delivered, {label: author_text[author_id]
                                     for label, author_id in mapping.items()})
        self.assertEqual(sorted(mapping.values()), list('ABCD'))
        inverse = {author_id: label for label, author_id in mapping.items()}
        author_correct = candidate['instructor_view']['correct_option_id']
        self.assertEqual(mapping[teacher['correct_option_id']], author_correct)
        self.assertEqual(delivered[teacher['correct_option_id']], author_text[author_correct])
        # Explanation and misconception values stay attached to the same option.
        for field in ('option_explanations', 'misconceptions'):
            expected = {inverse[author_id]: value
                        for author_id, value in candidate['instructor_view'][field].items()}
            self.assertEqual(teacher[field], expected)
        self.assertEqual(set(teacher['option_explanations']), set('ABCD'))
        self.assertEqual(set(teacher['misconceptions']), set('ABCD') - {teacher['correct_option_id']})
        # The author candidate is never mutated by relabeling.
        self.assertEqual(candidate, CASES[0]['candidate'])

    def test_pipeline_delivers_shuffled_views_and_records_both_mappings(self):
        result, model = self.run_case(deepcopy(CASES[0]))
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        mapping = question['self_check']['delivered_option_mapping']
        author_text = {o['id']: o['text'] for o in CASES[0]['candidate']['student_view']['options']}
        self.assertEqual({o['id']: o['text'] for o in question['student_view']['options']},
                         {label: author_text[author_id] for label, author_id in mapping.items()})
        self.assertEqual(mapping[question['instructor_view']['correct_option_id']],
                         CASES[0]['candidate']['instructor_view']['correct_option_id'])
        self.assertEqual(question['self_check']['delivered_correct_option_author_id'],
                         CASES[0]['candidate']['instructor_view']['correct_option_id'])
        self.assertEqual(question['self_check']['blind_option_mapping'], mapping)
        # The reader's answer is a delivered label; the audit trail still ties it
        # back to the author's correct option id.
        self.assertEqual(question['self_check']['blind_review']['answer'],
                         question['instructor_view']['correct_option_id'])
        self.assertEqual(model.calls[1][1]['student_view'], question['student_view'])

    def test_two_hundred_seeds_cover_all_four_correct_labels(self):
        candidate = CASES[0]['candidate']
        labels, orders = set(), set()
        for seed in range(200):
            student, teacher, mapping = delivered_choice_views(candidate, seed)
            self.assertEqual(sorted(mapping.values()), list('ABCD'))
            labels.add(teacher['correct_option_id'])
            orders.add(tuple(o['text'] for o in student['options']))
        self.assertEqual(labels, set('ABCD'))
        self.assertGreater(len(orders), 1)

    def test_comprehensive_delivery_is_not_relabeled(self):
        result, _ = self.run_case(deepcopy(CASES[4]))
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        self.assertEqual(question['student_view'], CASES[4]['candidate']['student_view'])
        self.assertEqual(question['instructor_view'], CASES[4]['candidate']['instructor_view'])
        self.assertEqual(question['self_check']['delivered_option_mapping'], {})
        self.assertEqual(question['self_check']['blind_option_mapping'], {})


class AuditContractTests(DeliveryTests):
    def test_clear_reason_with_failed_hard_check_is_contradictory(self):
        from question_generation.general_authoring import CHECKS, audit_contract_conflict
        checks = {name: {'passed': True, 'reason': 'ok'} for name in CHECKS}
        checks['ambiguity'] = {'passed': False, 'reason': '未发现影响答案的歧义。'}
        audit = {'valid': True, 'issues': [], 'checks': checks}
        self.assertTrue(audit_contract_conflict(audit))

    def test_real_rejection_reason_is_not_treated_as_a_contradiction(self):
        from question_generation.general_authoring import CHECKS, audit_contract_conflict
        checks = {name: {'passed': True, 'reason': 'ok'} for name in CHECKS}
        checks['ambiguity'] = {'passed': False, 'reason': '题干对初值有两种读法，答案不唯一。'}
        audit = {'valid': True, 'issues': [], 'checks': checks}
        self.assertFalse(audit_contract_conflict(audit))


class EnvelopeToleranceTests(DeliveryTests):
    def test_scalar_annotation_beside_candidate_is_ignored_and_recorded(self):
        class TypedEnvelope(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system.startswith(AUTHOR_PROMPT):
                    return {'candidate': result['candidate'], 'type': 'single_choice'}
                return result

        result, _ = self.run_case(deepcopy(CASES[0]), TypedEnvelope(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(result['authoring_report']['ignored_author_keys'], ['type'])

    def test_structured_extra_keys_beside_candidate_are_still_rejected(self):
        for extra in ({'design': {}}, {'calc': []}):
            with self.subTest(keys=sorted(extra)):
                class DriftedEnvelope(Replay):
                    def complete(self, system, payload, value=extra):
                        result = super().complete(system, payload)
                        if system.startswith(AUTHOR_PROMPT):
                            return {'candidate': result['candidate'], **value}
                        return result

                result, model = self.run_case(deepcopy(CASES[0]), DriftedEnvelope(CASES[0]['candidate']))
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(result['authoring_report']['stage'], '创作响应结构')

    def test_missing_calculations_defaults_to_an_empty_witness_list(self):
        case = deepcopy(CASES[0])
        case['candidate'].pop('calculations')
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        self.assertEqual(question['self_check']['calculations'], [])
        self.assertEqual(question['self_check']['verification_scope']['typed_calculation_count'], 0)

    def test_fabricated_quote_missing_design_and_score_drift_still_reject(self):
        def drop_design(candidate):
            candidate.pop('design')

        def drift_score(candidate):
            candidate['student_view']['parts'][0]['score'] = 4

        cases = (
            (CASES[0], lambda c: c['design']['claims'][0].update(quote='材料中并不存在的伪造引文。')),
            (CASES[0], drop_design),
            (CASES[4], drift_score),
        )
        for source, change in cases:
            with self.subTest(case=source['request']['request_id']):
                case = deepcopy(source)
                change(case['candidate'])
                result, model = self.run_case(case)
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
                self.assertEqual(len(model.calls), 1)


class ReaderToleranceTests(DeliveryTests):
    def test_extra_quality_annotation_is_prose_not_a_failure(self):
        class AnnotatedQuality(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result['quality']['evidence_scope'] = '受题面约束'
                return result

        result, _ = self.run_case(deepcopy(CASES[0]), AnnotatedQuality(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'GENERATED', result)
        review = result['questions'][0]['self_check']['blind_review']
        self.assertEqual(review['quality']['evidence_scope'], '受题面约束')

    def test_missing_required_quality_verdict_still_rejects_before_audit(self):
        class MissingAnswerability(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result['quality'].pop('answerability')
                return result

        result, model = self.run_case(deepcopy(CASES[0]), MissingAnswerability(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 2)

    def test_missing_depth_evidence_is_recorded_as_a_warning(self):
        class NoDepthEvidence(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result.pop('depth_evidence')
                return result

        result, _ = self.run_case(deepcopy(CASES[0]), NoDepthEvidence(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'GENERATED', result)
        warnings = result['questions'][0]['self_check']['review_warnings']
        self.assertEqual([item['check'] for item in warnings], ['reader_depth_evidence'])


class ContentGuardTests(DeliveryTests):
    def test_causal_language_in_an_option_is_rejected_before_the_reader(self):
        case = deepcopy(CASES[0])
        case['candidate']['student_view']['options'][1]['text'] += '，因为第一条边不影响入度'
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)
        self.assertIn('因果解释词', result['authoring_report']['details'])

    def test_nfkc_or_whitespace_duplicate_options_are_rejected(self):
        case = deepcopy(CASES[0])
        original = case['candidate']['student_view']['options'][0]['text']
        case['candidate']['student_view']['options'][1]['text'] = original.replace('A', 'Ａ').replace('B', 'Ｂ')
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)
        self.assertIn('选项重复', result['authoring_report']['details'])

    def test_option_content_guard_is_available_without_the_full_candidate(self):
        options = deepcopy(CASES[0]['candidate']['student_view']['options'])
        validate_option_content(options)
        options[2]['text'] = options[0]['text'] + ' '
        with self.assertRaises(ValueError):
            validate_option_content(options)

    def test_table_reference_is_a_warning_not_a_rejection(self):
        case = deepcopy(CASES[0])
        case['candidate']['student_view']['stem'] += '（见表8.2）'
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        warnings = result['questions'][0]['self_check']['review_warnings']
        self.assertIn('content_visual_reference', [item['check'] for item in warnings])

    def test_scoring_point_expected_in_the_stem_is_a_free_point_warning(self):
        case = deepcopy(CASES[4])
        stem = case['candidate']['student_view']['stem']
        case['candidate']['instructor_view']['parts'][0]['scoring_points'][0]['expected'] = stem[:10]
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        warnings = result['questions'][0]['self_check']['review_warnings']
        self.assertIn('content_free_scoring_point', [item['check'] for item in warnings])

    def test_witness_input_absent_from_the_student_view_is_a_warning(self):
        case = deepcopy(CASES[0])
        inputs = {'page_size': 4096, 'address': 28795, 'page_table': {'7': 42}}
        case['candidate']['calculations'] = [{'kind': 'paging', 'inputs': inputs,
                                              'result': solve('paging', inputs)}]
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        warnings = result['questions'][0]['self_check']['review_warnings']
        self.assertIn('witness_inputs_not_visible', [item['check'] for item in warnings])

        visible = deepcopy(case)
        visible['request']['request_id'] += '-visible-witness'
        visible['candidate']['student_view']['stem'] += ' 页大小4096字节，页号7的页框为42，访问地址28795。'
        result, _ = self.run_case(visible)
        self.assertEqual(result['status'], 'GENERATED', result)
        checks = [item['check'] for item in result['questions'][0]['self_check']['review_warnings']]
        self.assertNotIn('witness_inputs_not_visible', checks)

    def test_content_warnings_are_pure_and_empty_for_a_clean_item(self):
        candidate = CASES[0]['candidate']
        before = deepcopy(candidate)
        self.assertEqual(content_warnings(candidate, 'single_choice'), [])
        self.assertEqual(candidate, before)


class PromptContextTests(DeliveryTests):
    def test_single_choice_prompt_no_longer_teaches_that_a_is_correct(self):
        self.assertIn('正确项位置由系统重排', AUTHOR_VIEWS['single_choice'])
        self.assertNotIn('示例中A为正确项', AUTHOR_VIEWS['single_choice'])

    def test_comprehensive_score_rule_is_conditional_on_a_pinned_total(self):
        view = AUTHOR_VIEWS['comprehensive']
        self.assertIn('若请求固定了总分', view)
        self.assertIn('各小问分数合计必须严格等于该总分', view)
        self.assertIn('可自行确定一个自洽总分', view)
        self.assertIn('2至30分内', view)
        self.assertIn('part.score 必须严格等于该问 scoring_points 的 points 之和', view)
        self.assertNotIn('会被采纳', view)
        self.assertNotIn('不要为了凑', view)

    def test_audit_context_uses_the_score_adopted_by_sync(self):
        case = deepcopy(CASES[4])
        candidate = case['candidate']
        candidate['student_view']['parts'][1]['score'] = 6
        candidate['instructor_view']['parts'][1]['scoring_points'].append(
            {'id': 's9', 'points': 2, 'criterion': '补充判据。', 'expected': '补充期望。'})
        request = case['request']
        settings = request['constraints']['authoring']
        base = {**request, 'constraints': {k: v for k, v in request['constraints'].items() if k != 'authoring'}}
        parsed = read_request(base, settings)
        model = Replay(candidate)
        result = run(base, model, parsed, settings, score_pinned=False)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(model.calls[2][1]['constraints']['total_score'], 12)
        self.assertEqual(result['questions'][0]['metadata']['score'], 12)

        pinned = read_request(base, settings)
        rejected = run(base, Replay(candidate), pinned, settings, score_pinned=True)
        self.assertEqual(rejected['status'], 'SELF_CHECK_FAILED')
        self.assertIn('综合题总分与请求不符', rejected['authoring_report']['details'])

    def test_metadata_carries_scope_without_knowledge_points_or_difficulty(self):
        # The bank's knowledge_points are written by exam-checker's annotation, which
        # runs only after review PASS. Copying design concepts into delivery metadata
        # produced a free-text list that no code read and that the downstream assembly
        # step mistook for a classification key, so the field is no longer emitted.
        result, _ = self.run_case(deepcopy(CASES[0]))
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        metadata = question['metadata']
        self.assertEqual(metadata['syllabus_areas'], ['ds.graphs'])
        self.assertNotIn('knowledge_points', metadata)
        self.assertNotIn('difficulty', metadata)
        self.assertEqual(question['generator']['parameters']['authoring'],
                         CASES[0]['request']['constraints']['authoring'])


class ReplenishmentPreflightTests(TestCase):
    @staticmethod
    def payload(count):
        request = CASES[0]['request']
        deficit = {'subject': '数据结构', 'knowledge_point': '拓扑排序', 'question_type': 'single_choice',
                   'difficulty': 'medium', 'score_per_question': 2, 'missing_count': 1}
        return {
            'seed': 7,
            'replenishment_request': {
                'schema_version': '1.0', 'request_id': 'joint-deficit',
                'plan_status': 'PROPOSED_NOT_EXECUTED', 'scope': 'CURRENT_VERIFIED_CANDIDATE_POOL',
                'suggested_additional_count': count, 'avoid_stems': [],
                'deficits': [dict(deficit) for _ in range(count)],
            },
            'slot_profiles': {
                f'assembly-{index}': {
                    'topic': f'assembly:拓扑排序{index}',
                    'constraints': deepcopy(request['constraints']),
                    'evidence': deepcopy(request['evidence']),
                } for index in range(1, count + 1)
            },
        }

    def test_three_authored_slots_are_rejected_before_any_generation(self):
        def unexpected(_):
            self.fail('The preflight must reject before sampling')

        result = generate_replenishment(self.payload(3), single_generator=unexpected)
        self.assertEqual(result['status'], 'INVALID_REQUEST')
        self.assertIn('拆分', result['message'])
        self.assertEqual(result['questions'], [])

    def test_non_object_payload_is_an_invalid_request_not_an_exception(self):
        for payload in (None, [], 'x'):
            with self.subTest(payload=payload):
                # Deliberately non-object input: the contract must reject it, not raise.
                result = generate_replenishment(cast(Any, payload))
                self.assertEqual(result['status'], 'INVALID_REQUEST')

    def test_two_authored_slots_remain_usable(self):
        def scripted(slot):
            return {'schema_version': '0.1', 'request_id': slot['request_id'], 'status': 'GENERATED',
                    'questions': [{
                        'metadata': {key: slot[key] for key in ('subject', 'topic', 'question_type')},
                        'student_view': {'stem': '脚本候选题 ' + slot['request_id']},
                        'self_check': {'status': 'PASSED'},
                    }]}

        result = generate_replenishment(self.payload(2), single_generator=scripted)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(len(result['questions']), 2)
        self.assertEqual(result['deficits'], [])
        self.assertEqual({q['slot_id'] for q in result['questions']}, {'assembly-1', 'assembly-2'})
        self.assertTrue(all(q['assembly_slot']['difficulty_status'] == 'REVIEW_REQUIRED'
                            for q in result['questions']))
