"""Transport replays test contracts; separate oracles check authored examples.

No result here measures a model's authoring or judgment quality.
"""
import ipaddress
import itertools
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.authoring import generate_authored, read_authoring
from question_generation.batch import generate_batch
from question_generation.brief_authoring import PLAN_PROMPT
from question_generation.comprehensive import generate_comprehensive
from question_generation.curriculum import AREAS, coverage_report
from question_generation.general_authoring import (
    ADVISORY_CHECKS,
    AUDIT_PROMPT,
    AUTHOR_PROMPT,
    AUTHOR_VIEWS,
    BLOCKING_CHECKS,
    CHECKS,
    READER_PROMPT,
    audit_evidence,
    audit_passed,
    audit_warnings,
)
from question_generation.general_contract import contains_given_span, contains_span
from question_generation.generation import generate_question
from question_generation.knowledge import with_knowledge
from question_generation.model_client import JsonModel

CASES = json.loads((Path(__file__).parent / 'fixtures/question_generation/general_cases.json').read_text())


class Replay:
    model, base_url = 'scripted-protocol-fixture', 'https://fixture.invalid'

    def __init__(self, candidate, bad_audit=None):
        self.candidate = deepcopy(candidate)
        self.calls, self.usage = [], []
        self.bad_audit = bad_audit

    def complete(self, system, payload):
        self.calls.append((system, deepcopy(payload)))
        c = self.candidate
        if system.startswith(AUTHOR_PROMPT):
            return {'candidate': c}
        if system == READER_PROMPT:
            student = payload['student_view']
            if 'options' in student:
                expected = next(o['text'] for o in c['student_view']['options']
                                if o['id'] == c['instructor_view']['correct_option_id'])
                answer = next(o['id'] for o in student['options'] if o['text'] == expected)
                parts = []
            else:
                answer = 'OPEN'
                parts = [{'part_id': p['part_id'], 'solution': p['solution']} for p in c['instructor_view']['parts']]
            return {'answer': answer, 'solution': 'Scripted answer, not an independent model evaluation.',
                    'part_solutions': parts, 'issues': [], 'depth_evidence': 'Protocol fixture only.',
                    'condition_test': {'change': 'Fixture perturbation', 'effect': 'Fixture consequence'},
                    'quality': dict.fromkeys(['answerability', 'depth', 'distractors', 'clarity'], 2)}
        if system.startswith(AUDIT_PROMPT):
            checks = {k: {'passed': True, 'reason': 'Protocol fixture only.'} for k in CHECKS}
            if self.bad_audit:
                checks[self.bad_audit]['passed'] = False
            return {'valid': True, 'issues': [], 'adversarial_case': 'Scripted protocol fixture.', 'checks': checks}
        raise AssertionError('Unexpected call')


class GeneralContractTests(TestCase):
    def test_all_stages_satisfy_provider_json_mode_precondition(self):
        for prompt in (AUTHOR_PROMPT, READER_PROMPT, AUDIT_PROMPT):
            self.assertIn('json', prompt.lower())

    def test_prompts_forbid_unseen_tables_and_mathematically_impossible_inversions(self):
        self.assertIn('必须将该表所需的数据或公式完整写入student_view', AUTHOR_PROMPT)
        self.assertIn('不得让题面引用学生看不见的图表', AUTHOR_PROMPT)
        self.assertIn('不得要求数学上不成立的翻转', PLAN_PROMPT)
        self.assertIn('HRRN', PLAN_PROMPT)

    def test_single_choice_prompts_forbid_self_defeating_options_and_stem_spoilers(self):
        rules = ('严禁在选项文本中附带', '不得在四选项中唯一', '不得直接写出本应由学生推导的中间结论')
        for prompt in (PLAN_PROMPT, AUTHOR_VIEWS['single_choice']):
            with self.subTest(prompt=prompt[:24]):
                for rule in rules:
                    self.assertIn(rule, prompt)
        self.assertIn('错因分析只写在教师视图', PLAN_PROMPT)
        self.assertIn('所有错因分析只准写在 instructor_view', AUTHOR_VIEWS['single_choice'])
        self.assertIn('禁止设成完全同构的冗余子项', AUTHOR_VIEWS['single_choice'])

    def test_comprehensive_view_binds_part_scores_to_scoring_points(self):
        self.assertIn('part.score 必须严格等于该问 scoring_points 的 points 之和',
                      AUTHOR_VIEWS['comprehensive'])
        self.assertIn('2至30分内', AUTHOR_VIEWS['comprehensive'])

    def test_audit_grading_rejects_only_wrong_answers_leaks_or_rejected_equivalents(self):
        self.assertIn('grading 仅在下列情形判 passed=false', AUDIT_PROMPT)
        for reason in ('标准答案或评分点 expected 的期望值本身错误', '评分标准泄露答案',
                       '拒绝声明了接受条件的合法等价解法'):
            self.assertIn(reason, AUDIT_PROMPT)
        # The prompt may not invite suggestions into issues: audit_passed treats a
        # non-empty issues list without a failed check as a contract contradiction.
        self.assertIn('不要放进 issues', AUDIT_PROMPT)
        self.assertIn('issues 只允许写会阻断交付的问题', AUDIT_PROMPT)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = Path(directory.name) / 'cache.sqlite'
        # Fail closed if any test accidentally reaches the external transport.
        self.guard = patch('question_generation.model_client.build_opener', side_effect=AssertionError('No network in tests'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def run_case(self, case, model=None):
        model = model or Replay(case['candidate'])
        with patch('question_generation.authoring.JsonModel.from_env', return_value=model), patch.dict(
            'os.environ', {'QUESTION_GENERATION_AUTHORING_CACHE': str(self.cache)}
        ):
            entry = generate_comprehensive if case['request']['question_type'] == 'comprehensive' else generate_question
            return entry(case['request']), model

    def test_four_subjects_both_types_normal_entry_and_cache(self):
        for case in CASES:
            with self.subTest(request=case['request']['request_id']):
                result, model = self.run_case(case)
                self.assertEqual(result['status'], 'GENERATED', result)
                q = result['questions'][0]
                if q['metadata']['question_type'] == 'single_choice':
                    # Delivered options are shuffled and relabeled; the mapping
                    # keeps each delivered label tied to the author's option id.
                    author_options = {o['id']: o['text'] for o in case['candidate']['student_view']['options']}
                    mapping = q['self_check']['delivered_option_mapping']
                    self.assertEqual({o['id']: o['text'] for o in q['student_view']['options']},
                                     {label: author_options[author_id]
                                      for label, author_id in mapping.items()})
                else:
                    self.assertEqual(q['student_view'], case['candidate']['student_view'])
                self.assertEqual(q['review_status'], 'PENDING')
                self.assertEqual(q['self_check']['verification_scope']['typed_calculation_count'], len(case['candidate']['calculations']))
                self.assertEqual(len(model.calls), 3)
                prompt, _ = model.calls[0]
                self.assertEqual(prompt, AUTHOR_PROMPT + AUTHOR_VIEWS[q['metadata']['question_type']])
                self.assertEqual('correct_option_id' in prompt, q['metadata']['question_type'] == 'single_choice')
                self.assertEqual('scoring_points' in prompt, q['metadata']['question_type'] == 'comprehensive')
                self.assertEqual(self.run_case(case, model)[0], result)
                self.assertEqual(len(model.calls), 3)

    def test_reader_never_receives_author_design_answers_or_rubric(self):
        for case in (CASES[0], CASES[4]):
            result, model = self.run_case(case)
            blind = model.calls[1][1]
            self.assertEqual(set(blind), {'question_type', 'student_view'})
            self.assertNotIn('instructor_view', blind)
            self.assertNotIn('design', blind)
            self.assertEqual(result['status'], 'GENERATED')

    def test_audit_omits_only_identical_summary_without_changing_author_sources(self):
        sources = [
            {'id': 'same', 'source': 'book', 'anchor': 'page 1', 'summary': '原文', 'excerpt': '原文'},
            {'id': 'different', 'summary': '摘要', 'excerpt': '完整原文'},
            {'id': 'summary-only', 'summary': '唯一正文'},
        ]
        original = deepcopy(sources)
        compact = audit_evidence(sources)
        self.assertEqual(sources, original)
        self.assertEqual(compact[0], {k: v for k, v in original[0].items() if k != 'summary'})
        self.assertEqual(compact[1:], original[1:])
        case = deepcopy(CASES[0])
        case['request']['evidence'][0]['excerpt'] = case['request']['evidence'][0]['summary']
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(model.calls[0][1]['evidence'], case['request']['evidence'])
        self.assertNotIn('summary', model.calls[2][1]['evidence'][0])
        self.assertEqual(model.calls[2][1]['evidence'][0]['excerpt'], case['request']['evidence'][0]['summary'])

    def test_short_evidenced_audit_rejection_cannot_deliver_a_question(self):
        report = {'valid': False, 'issues': ['Two readings give opposite answers.'],
                  'adversarial_case': 'Concrete alternative reading.',
                  'checks': {'ambiguity': {'passed': False, 'reason': 'A required condition is absent.'}}}
        class ShortRejection(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                return report if system == AUDIT_PROMPT else result
        result, _ = self.run_case(CASES[0], ShortRejection(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(result['questions'], [])
        self.assertEqual(result['authoring_report']['details'], report)

    def test_partial_or_inconsistent_audit_never_passes_with_valid_true(self):
        class PartialApproval(Replay):
            omitted: str
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system.startswith(AUDIT_PROMPT):
                    result['checks'].pop(self.omitted)
                return result
        for omitted in CHECKS:
            model = PartialApproval(CASES[0]['candidate'])
            model.omitted = omitted
            result, _ = self.run_case(CASES[0], model)
            self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
            self.assertEqual(result['questions'], [])

    def test_explicit_transport_timeouts_retain_stage_without_a_question(self):
        from urllib.error import URLError
        for error, code in ((TimeoutError('private details'), 'response_timeout'),
                            (URLError(TimeoutError('private details')), 'response_timeout'),
                            (URLError('private timed out text'), 'transport_error'),
                            (ConnectionRefusedError('private details'), 'transport_error')):
            model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture', max_retries=0)
            with patch('question_generation.model_client.build_opener') as opener:
                opener.return_value.open.side_effect = error
                result, _ = self.run_case(CASES[0], model)
            self.assertEqual(result['status'], 'MODEL_UNAVAILABLE')
            self.assertEqual(result['questions'], [])
            self.assertEqual(result['authoring_report']['model_failure'], {'stage': 'author', 'code': code})
            self.assertEqual(result['authoring_report']['usage'], [])
            self.assertNotIn('private', json.dumps(result))
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_student_cannot_use_material_or_author_intent_to_fill_hidden_conditions(self):
        case = deepcopy(CASES[0])
        case['request']['evidence'][0]['summary'] += ' HIDDEN_SOURCE_SENTINEL'
        case['request']['constraints']['authoring']['focus'] = 'HIDDEN_INTENT_SENTINEL'
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED')
        blind = json.dumps(model.calls[1][1])
        self.assertNotIn('HIDDEN_SOURCE_SENTINEL', blind)
        self.assertNotIn('HIDDEN_INTENT_SENTINEL', blind)
        audit = json.dumps(model.calls[2][1])
        self.assertIn('HIDDEN_SOURCE_SENTINEL', audit)
        self.assertIn('HIDDEN_INTENT_SENTINEL', audit)

    def test_sibling_calculations_with_a_non_object_candidate_are_a_contract_failure(self):
        class WrongEnvelope(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system.startswith(AUTHOR_PROMPT):
                    return {'candidate': [], 'calculations': []}
                return result
        result, model = self.run_case(CASES[0], WrongEnvelope(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)

    def test_author_decode_failure_keeps_safe_diagnostics_without_a_question(self):
        model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture')
        content = '{"private题":'
        envelope = {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}],
                    'usage': {'completion_tokens': 20}}
        with patch('question_generation.model_client.build_opener') as opener, patch(
                'question_generation.model_client.time.sleep'):
            # Fresh body per attempt: the decode failure consumes one re-roll.
            opener.return_value.open.side_effect = lambda *args, **kwargs: BytesIO(json.dumps(envelope).encode())
            result, _ = self.run_case(CASES[0], model)
        self.assertEqual(opener.return_value.open.call_count, 2)
        self.assertEqual(result['status'], 'MODEL_UNAVAILABLE')
        self.assertEqual(result['questions'], [])
        self.assertEqual(result['authoring_report']['model_failure'], {
            'stage': 'author', 'code': 'invalid_content', 'finish_reason': 'stop',
            'response_issue': 'content_decode', 'content_decode_position': len(content),
            'content_length': len(content),
        })
        self.assertEqual(result['authoring_report']['usage'][0]['completion_tokens'], 20)
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(opener.return_value.open.call_count, 2)

    def test_student_issue_blocks_before_material_aware_audit(self):
        class Unanswerable(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result['issues'] = ['Two reasonable readings give different answers.']
                return result
        result, model = self.run_case(CASES[0], Unanswerable(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 2)

    def test_invalid_dependencies_quotes_and_conditions_stop_before_reader(self):
        changes = [
            lambda c: c['design']['claims'][0].update(quote='invented source text'),
            lambda c: c['design']['claims'][0].update(evidence_id='missing'),
            lambda c: c['design']['givens'].append(deepcopy(c['design']['givens'][0])),
            lambda c: c['design']['derivation'][0].update(uses=['d2']),
            lambda c: c['design']['derivation'][1].update(uses=['g1']),
            lambda c: c['design']['counterfactual'].update(given_id='missing'),
            lambda c: c['design']['derivation'][0].update(uses=['k1', 'k1']),
            lambda c: c['student_view']['options'][1].update(text=c['student_view']['options'][0]['text']),
            lambda c: c.update(calculations=[{'kind': 'python', 'inputs': {'code': 'print(1)'}, 'result': 1}]),
        ]
        for change in changes:
            case = deepcopy(CASES[0])
            change(case['candidate'])
            result, model = self.run_case(case)
            self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
            self.assertEqual(len(model.calls), 1)

    def test_comprehensive_score_and_dependency_mutations(self):
        changes = [
            lambda c: c['student_view']['parts'][0].update(score=4),
            lambda c: c['instructor_view']['parts'][0].update(depends_on=['p2']),
            lambda c: c['instructor_view']['parts'][0]['scoring_points'][0].update(points=True),
            lambda c: c['instructor_view']['parts'][1].update(part_id='p1'),
            lambda c: c['instructor_view']['parts'][0].update(equivalent_methods=[]),
        ]
        for change in changes:
            case = deepcopy(CASES[4]); change(case['candidate'])
            result, model = self.run_case(case)
            self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
            self.assertEqual(len(model.calls), 1)

    def test_comprehensive_half_point_scoring_points_are_supported(self):
        case = deepcopy(CASES[4])
        part = case['candidate']['instructor_view']['parts'][0]
        part['scoring_points'][0]['points'] = 2.5
        part['scoring_points'][1]['points'] = 0.5
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(result['questions'][0]['instructor_view']['parts'][0]['scoring_points'][0]['points'], 2.5)
        self.assertIn('0.5分', AUTHOR_VIEWS['comprehensive'])

    def test_invalid_half_point_scoring_points_are_rejected(self):
        for value in (0.25, 2.6):
            with self.subTest(points=value):
                case = deepcopy(CASES[4])
                case['candidate']['instructor_view']['parts'][0]['scoring_points'][0]['points'] = value
                result, model = self.run_case(case)
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
                self.assertEqual(len(model.calls), 1)

    def test_only_hard_audit_checks_block_despite_valid_flag(self):
        for key in BLOCKING_CHECKS:
            result, _ = self.run_case(CASES[0], Replay(CASES[0]['candidate'], bad_audit=key))
            self.assertEqual(result['status'], 'SELF_CHECK_FAILED')

    def test_advisory_audit_failures_deliver_as_review_warnings(self):
        for key in ADVISORY_CHECKS:
            with self.subTest(check=key):
                case = deepcopy(CASES[0])
                case['request']['request_id'] += '-' + key
                result, _ = self.run_case(case, Replay(case['candidate'], bad_audit=key))
                self.assertEqual(result['status'], 'GENERATED', result)
                question, = result['questions']
                self.assertEqual(question['review_status'], 'PENDING')
                self.assertEqual(question['self_check']['status'], 'PASSED')
                self.assertEqual(question['self_check']['review_warnings'],
                                 [{'check': key, 'reason': 'Protocol fixture only.'}])

    def test_quote_found_in_another_supplied_material_is_rebound(self):
        case = deepcopy(CASES[0])
        request = case['request']
        original = deepcopy(request['evidence'][0])
        decoy = {**deepcopy(original), 'id': 'note-decoy', 'summary': '与本条引文无关的另一段材料。'}
        request['evidence'] = [decoy, original]
        case['candidate']['design']['claims'][0]['evidence_id'] = decoy['id']
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        self.assertEqual(question['pedagogy']['claims'][0]['evidence_id'], original['id'])
        self.assertIn(original['id'], [ref['id'] for ref in question['evidence_refs']])
        self.assertNotIn(decoy['id'], [ref['id'] for ref in question['evidence_refs']])

    def test_quote_absent_from_every_supplied_material_is_still_rejected(self):
        case = deepcopy(CASES[0])
        request = case['request']
        original = deepcopy(request['evidence'][0])
        request['evidence'] = [{**deepcopy(original), 'id': 'note-decoy', 'summary': '无关材料。'}, original]
        case['candidate']['design']['claims'][0]['quote'] = '材料中并不存在的伪造引文。'
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertIn('知识依据引文未出现在所选原文或摘要中', str(result['authoring_report']['details']))

    def test_calculations_beside_the_candidate_envelope_are_accepted(self):
        class SiblingCalculations(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system.startswith(AUTHOR_PROMPT):
                    candidate = result['candidate']
                    return {'candidate': {k: v for k, v in candidate.items() if k != 'calculations'},
                            'calculations': candidate['calculations']}
                return result
        result, _ = self.run_case(CASES[0], SiblingCalculations(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        self.assertEqual(question['self_check']['calculations'], CASES[0]['candidate']['calculations'])

    def test_unknown_sibling_keys_beside_the_candidate_are_still_rejected(self):
        for extra in ({'design': {}}, {'calc': []}):
            with self.subTest(extra=sorted(extra)):
                class DriftedEnvelope(Replay):
                    def complete(self, system, payload, value=extra):
                        result = super().complete(system, payload)
                        if system.startswith(AUTHOR_PROMPT):
                            candidate = result['candidate']
                            return {'candidate': {k: v for k, v in candidate.items() if k != 'calculations'},
                                    **value}
                        return result
                result, _ = self.run_case(CASES[0], DriftedEnvelope(CASES[0]['candidate']))
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
                self.assertIn('创作响应结构', str(result['authoring_report']['stage']))

    def test_audit_passed_ignores_advisory_verdict_and_requires_all_hard_checks(self):
        def audit(**failed):
            checks = {k: {'passed': True, 'reason': 'Checked.'} for k in CHECKS}
            for key in failed:
                checks[key]['passed'] = False
                checks[key]['reason'] = f'{key} failed.'
            return {'valid': not failed, 'issues': ['advisory issue'] if failed else [],
                    'adversarial_case': 'Concrete alternative reading.', 'checks': checks}
        soft = audit(reasoning_necessity=True, requirements=True)
        self.assertTrue(audit_passed(soft))
        self.assertEqual([w['check'] for w in audit_warnings(soft)],
                         ['reasoning_necessity', 'requirements'])
        for key in BLOCKING_CHECKS:
            with self.subTest(check=key):
                self.assertFalse(audit_passed(audit(**{key: True})))
        self.assertEqual(audit_warnings(audit()), [])
        inconsistent = audit()
        inconsistent['valid'] = False
        self.assertFalse(audit_passed(inconsistent))

    def test_checks_tolerate_extra_explanatory_keys_but_require_the_verdict(self):
        checks = {k: {'passed': True, 'reason': 'Checked.'} for k in CHECKS}
        checks['grading'] = {'passed': True, 'reason': 'Checked.',
                             'reasoning': '分值粒度未涉及。'}
        audit = {'valid': True, 'issues': [], 'adversarial_case': 'Concrete reading.', 'checks': checks}
        self.assertTrue(audit_passed(audit))
        for broken in ({'passed': True}, {'reason': 'no verdict'},
                       {'passed': 'true', 'reason': 'string verdict'},
                       {'passed': True, 'reason': '  '}):
            with self.subTest(broken=broken):
                self.assertFalse(audit_passed({**audit, 'checks': {**checks, 'grading': broken}}))

    def test_non_blocking_issues_are_advisory_notes_not_rejections(self):
        # baseline-16 co-co-1: valid=true, all nine checks passed, three suggestions
        # in issues, and the old contract dropped the item as self-contradictory.
        checks = {k: {'passed': True, 'reason': 'Checked.'} for k in CHECKS}
        audit = {'valid': True, 'issues': ['p1 未定义“指令间隔”。', 'p2 分值粒度过粗。'],
                 'adversarial_case': 'Concrete alternative reading.', 'checks': checks}
        self.assertTrue(audit_passed(audit))
        warnings = audit_warnings(audit)
        self.assertEqual([w['check'] for w in warnings], ['advisory_note', 'advisory_note'])
        self.assertEqual([w['reason'] for w in warnings], audit['issues'])
        # Blocking failures still veto regardless of issues.
        for key in BLOCKING_CHECKS:
            failed = {'valid': True, 'issues': ['still an issue'], 'adversarial_case': 'x',
                      'checks': {**checks, key: {'passed': False, 'reason': 'failed.'}}}
            with self.subTest(check=key):
                self.assertFalse(audit_passed(failed))
        # A false valid with no advisory explanation stays a contract failure.
        self.assertFalse(audit_passed({**audit, 'valid': False}))
        self.assertEqual(audit_warnings({**audit, 'valid': False, 'issues': []}), [])

    def test_single_choice_plan_and_audit_prompts_do_not_require_written_steps(self):
        self.assertIn('单选题', PLAN_PROMPT)
        self.assertIn('不得要求列出中间步骤', PLAN_PROMPT)
        self.assertIn('不得因题面未要求学生列出或写出中间过程', AUDIT_PROMPT)
        self.assertNotIn('即使仍需少量算术核对', AUDIT_PROMPT)

    def test_nested_condition_test_quality_is_normalized_before_reader_check(self):
        class NestedQuality(Replay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result['condition_test']['quality'] = result.pop('quality')
                return result
        result, _ = self.run_case(CASES[0], NestedQuality(CASES[0]['candidate']))
        self.assertEqual(result['status'], 'GENERATED', result)
        review = result['questions'][0]['self_check']['blind_review']
        self.assertIn('quality', review)
        self.assertEqual(set(review['condition_test']), {'change', 'effect'})

    def test_missing_material_and_lookup_before_provider(self):
        case = deepcopy(CASES[0]); evidence = case['request'].pop('evidence')
        with patch('question_generation.authoring.JsonModel.from_env', side_effect=AssertionError('No model')):
            self.assertEqual(generate_question(case['request'])['status'], 'NEEDS_MATERIAL')
        model = Replay(case['candidate'])
        with patch('question_generation.authoring.JsonModel.from_env', return_value=model), patch.dict(
            'os.environ', {'QUESTION_GENERATION_AUTHORING_CACHE': str(self.cache)}
        ):
            result = with_knowledge(generate_question, case['request'], lambda s, t: evidence)
            self.assertEqual(result['status'], 'GENERATED')

    def test_scope_is_navigation_not_a_topic_allowlist(self):
        for subject, areas in AREAS.items():
            for area in areas:
                request = deepcopy(CASES[0]['request'])
                request.update(subject=subject, topic='material_defined_new_topic')
                request['constraints']['authoring']['syllabus_areas'] = [area]
                parsed, _, _ = read_authoring(request)
                self.assertEqual(parsed.metadata['topic'], 'material_defined_new_topic')
        report = coverage_report()
        self.assertEqual(len(report['areas']), 24)
        self.assertTrue(all(not a['chapter_quality_verified'] and not a['evaluated_topics'] for a in report['areas']))

    def test_invalid_scope_and_constraints_do_not_call_model(self):
        for areas in ([], ['invented'], ['os.process'], ['ds.graphs'] * 2, [None]):
            case = deepcopy(CASES[0]); case['request']['constraints']['authoring']['syllabus_areas'] = areas
            result, model = self.run_case(case)
            self.assertEqual(result['status'], 'INVALID_REQUEST')
            self.assertEqual(model.calls, [])

    def test_wrong_finite_count_is_rejected_before_reader(self):
        case = deepcopy(CASES[0])
        case['candidate']['calculations'][0]['result']['queries']['A'] = 2
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)

    def test_excerpt_is_authority_for_quote_when_present(self):
        case = deepcopy(CASES[0])
        case['request']['evidence'][0]['excerpt'] = '原文中没有摘要给出的结论。'
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)

    def test_citation_layout_normalization_does_not_accept_semantic_edits(self):
        self.assertTrue(contains_span('overflow 等于 0', 'overﬂow\n等于　０'))
        self.assertFalse(contains_span('overflow 不等于 0', 'overﬂow\n等于　０'))
        self.assertFalse(contains_span('起点先于终点', '起点不先于终点'))

    def test_option_data_is_visible_but_teacher_only_data_is_not(self):
        case = deepcopy(CASES[0])
        case['candidate']['design']['givens'][0]['text'] = case['candidate']['student_view']['options'][0]['text']
        result, _ = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED')
        case['request']['request_id'] += '-hidden'
        case['candidate']['design']['givens'][0]['text'] = 'Only the teacher knows this condition'
        case['candidate']['instructor_view']['explanation'] += ' Only the teacher knows this condition'
        result, model = self.run_case(case, Replay(case['candidate'], bad_audit='ambiguity'))
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        # Callers need a machine-readable route, not only a Chinese stage label.
        self.assertEqual(result['failure']['code'], 'audit_rejected')
        self.assertEqual(result['failure']['retry'], 'new_request')
        self.assertEqual(result['failure']['needs'], 'human')
        self.assertEqual(len(model.calls), 3)
        diagnostic = model.calls[2][1]['program_design_diagnostics']['nonliteral_givens']
        self.assertEqual(diagnostic[0]['text'], 'Only the teacher knows this condition')
        self.assertNotIn('Only the teacher knows this condition', json.dumps(model.calls[1][1]))

    def test_given_sentence_terminator_can_introduce_code_without_fuzzy_matching(self):
        self.assertTrue(contains_given_span('Each x++ counts once.', 'Each x++ counts once: C1: x++;'))
        # Claim quotes tolerate punctuation differences; givens stay literal.
        self.assertTrue(contains_span('Each x++ counts once.', 'Each x++ counts once: C1: x++;'))
        self.assertFalse(contains_given_span('Each x++ counts twice.', 'Each x++ counts once: C1: x++;'))
        self.assertFalse(contains_given_span('x=1.5.', 'x=15.'))

    def test_nonliteral_condition_is_explicitly_sent_for_semantic_audit(self):
        case = deepcopy(CASES[0])
        case['candidate']['student_view']['stem'] += ' Uses variable allocation and local replacement.'
        case['candidate']['design']['givens'][0]['text'] = 'Uses local replacement.'
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(model.calls[2][1]['program_design_diagnostics']['nonliteral_givens'][0]['text'],
                         'Uses local replacement.')

    def test_supplementary_claim_is_a_diagnostic_not_a_fake_correctness_failure(self):
        case = deepcopy(CASES[0])
        extra = deepcopy(case['candidate']['design']['claims'][0]); extra['id'] = 'supplement'
        case['candidate']['design']['claims'].append(extra)
        result, model = self.run_case(case)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(model.calls[2][1]['program_design_diagnostics']['unlinked_claims'], ['supplement'])

    def test_model_can_report_a_specific_material_gap(self):
        model = Replay(CASES[0]['candidate'])
        with patch.object(model, 'complete', return_value={'material_gaps': ['材料只列概念名称，没有解释有向边的约束。']}):
            result, _ = self.run_case(CASES[0], model)
        self.assertEqual(result['status'], 'NEEDS_MATERIAL')
        self.assertEqual(result['questions'], [])

    def test_comprehensive_batch_preserves_total_score(self):
        case = CASES[4]; request = case['request']; model = Replay(case['candidate'])
        slot = {k: request[k] for k in ('subject', 'topic', 'question_type', 'constraints', 'evidence')}
        batch = {'schema_version': '0.1', 'request_id': 'general-batch', 'seed': 3,
                 'question_count': 1, 'total_score': 10,
                 'slots': [{**slot, 'slot_id': 's1', 'count': 1, 'score_per_question': 10}]}
        result = generate_batch(batch, single_generator=lambda p: generate_authored(p, client=model, cache_path=self.cache))
        self.assertEqual(len(result['questions']), 1, result)
        self.assertEqual(result['questions'][0]['metadata']['score'], 10)


class SampleOracleTests(TestCase):
    """Independent finite checks of the hand-authored examples, not model quality."""
    def test_graph_unique_order_and_changed_condition(self):
        def orders(edges):
            return [''.join(p) for p in itertools.permutations('ABCD')
                    if all(p.index(a) < p.index(b) for a, b in edges)]
        edges = [('A', 'C'), ('B', 'C'), ('C', 'D')]
        self.assertEqual(orders(edges), ['ABCD', 'BACD'])
        self.assertEqual([len(orders(edges+[e])) for e in [('A','B'),('A','D'),('D','C'),('C','B')]], [1,2,0,0])
        self.assertGreater(len(orders(edges[:2]+[('D','C'),('A','B')])), 1)

    def test_overflow_all_candidate_flags(self):
        vectors = []
        for a, b in [(127, 1), (255, 1)]:
            signed = lambda n: n if n < 128 else n - 256
            s = signed(a) + signed(b)
            vectors.append([int(a+b > 255), ((a+b)&255)>>7,
                            int((a>>7) == (b>>7)), int(not -128 <= s <= 127)])
        self.assertEqual(list(zip(*vectors)), [(0,1), (1,0), (1,0), (1,0)])

    def test_safety_all_completion_orders(self):
        allocation, maximum = [5,2,2], [7,5,3]
        def safe(total):
            good = []
            for order in itertools.permutations(range(3)):
                work = total - sum(allocation)
                for p in order:
                    if maximum[p] - allocation[p] > work:
                        break
                    work += allocation[p]
                else:
                    good.append(order)
            return good
        self.assertIn((2,0,1), safe(10))
        self.assertEqual(safe(9), [])

    def test_route_equivalence_by_all_interval_boundaries(self):
        original = [('10.0.0.0/24','X'),('10.0.1.0/24','X'),('10.0.1.128/25','Y'),('0.0.0.0/0','Z')]
        def lookup(table, address):
            matches = [(ipaddress.ip_network(n).prefixlen, hop) for n, hop in table
                       if ipaddress.ip_address(address) in ipaddress.ip_network(n)]
            return max(matches)[1]
        for replacement, equivalent in [('10.0.0.0/23',True),('10.0.0.0/22',False),('10.0.0.0/24',False)]:
            table = [(replacement,'X')] + original[2:]
            bounds = {0, 2**32}
            for n, _ in original + table:
                net = ipaddress.ip_network(n)
                bounds.update([int(net.network_address), int(net.broadcast_address)+1])
            probes = [n for n in sorted(bounds) if n < 2**32]
            self.assertEqual(all(lookup(table,n) == lookup(original,n) for n in probes), equivalent)
