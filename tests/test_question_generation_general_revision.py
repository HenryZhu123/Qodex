from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from test_question_generation_general import CASES, Replay

from question_generation.authoring import generate_authored
from question_generation.comprehensive import revise_comprehensive
from question_generation.general_authoring import (
    AUDIT_PROMPT,
    READER_PROMPT,
    REPAIR_PROMPT,
    apply_replacements,
)
from question_generation.general_revision import revise_authored


class RepairReplay(Replay):
    def complete(self, system, payload):
        if system.startswith(REPAIR_PROMPT):
            self.calls.append((REPAIR_PROMPT, deepcopy(payload)))
            return {'replacements': [{'path': ['student_view', 'stem'], 'value': self.candidate['student_view']['stem']}]}
        if system.startswith(AUDIT_PROMPT):
            return super().complete(AUDIT_PROMPT, payload)
        return super().complete(system, payload)


class GeneralRevisionTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = Path(directory.name) / 'cache.sqlite'
        self.guard = patch('question_generation.model_client.build_opener', side_effect=AssertionError('No external models'))
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def make_revision(self, case):
        result = generate_authored(case['request'], client=Replay(case['candidate']), cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        current, = result['questions']
        refs = {ref['id'] for ref in current['evidence_refs']}
        return {
            'schema_version': '0.1', 'request_id': 'repair-' + case['request']['request_id'],
            'current_question': current, 'evidence': [e for e in case['request']['evidence'] if e['id'] in refs],
            'feedback': {'feedback_id': 'review-1', 'question_id': current['question_id'], 'target_version': 1,
                         'part_id': 'stem', 'action': 'repair', 'comment': '请明确题设规则的适用范围。'},
        }

    def test_both_types_recheck_keep_identity_and_cache_only_the_success(self):
        for case in (CASES[0], next(c for c in CASES if c['request']['question_type'] == 'comprehensive')):
            with self.subTest(question_type=case['request']['question_type']):
                payload = self.make_revision(case)
                original = deepcopy(payload['current_question'])
                candidate = deepcopy(case['candidate'])
                candidate['student_view']['stem'] += '\n按上述规则。'
                model = RepairReplay(candidate)
                with patch('question_generation.authoring.JsonModel.from_env', return_value=model), patch.dict(
                    'os.environ', {'QUESTION_GENERATION_AUTHORING_CACHE': str(self.cache)}
                ):
                    result = revise_comprehensive(payload)
                    self.assertEqual(revise_comprehensive(payload), result)
                self.assertEqual(result['status'], 'REVISED', result)
                repaired, = result['questions']
                self.assertEqual(repaired['question_id'], original['question_id'])
                self.assertEqual(repaired['version'], 2)
                self.assertEqual(repaired['metadata'], original['metadata'])
                self.assertEqual(repaired['review_status'], 'PENDING')
                self.assertEqual(repaired['revision']['from_version'], 1)
                self.assertEqual(payload['current_question'], original)
                self.assertEqual([call[0] for call in model.calls], [REPAIR_PROMPT, READER_PROMPT, AUDIT_PROMPT])
                self.assertEqual(set(model.calls[1][1]), {'question_type', 'student_view'})
                self.assertEqual(model.calls[2][1]['repair']['feedback'], payload['feedback'])
                limit = {**payload, 'current_question': repaired,
                         'feedback': {**payload['feedback'], 'target_version': 2}}
                self.assertEqual(revise_authored(limit, client=model, cache_path=self.cache)['status'], 'REVISION_LIMIT')

    def test_malformed_target_source_drift_and_stale_feedback_stop_before_model(self):
        payload = self.make_revision(CASES[0])
        model = RepairReplay(CASES[0]['candidate'])
        for field, value, status in [
            ('evidence', [], 'NEEDS_MATERIAL'),
            ('feedback', {**payload['feedback'], 'target_version': 2}, 'STALE_FEEDBACK'),
            ('feedback', {**payload['feedback'], 'part_id': 'p100'}, 'FEEDBACK_TARGET_MISMATCH'),
            ('evidence', [{**item, 'version': 'different'} for item in payload['evidence']], 'NEEDS_MATERIAL'),
        ]:
            with self.subTest(field=field, status=status):
                result = revise_authored({**payload, field: value}, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], status)
        self.assertEqual(model.calls, [])

    def test_noop_or_audit_rejection_never_produces_a_revised_version(self):
        case = CASES[0]
        payload = self.make_revision(case)
        model = RepairReplay(case['candidate'])
        result = revise_authored(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)
        candidate = deepcopy(case['candidate'])
        candidate['student_view']['stem'] += '\n按上述规则。'
        model = RepairReplay(candidate, bad_audit='ambiguity')
        result = revise_authored(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(result['questions'], [])
        self.assertEqual(len(model.calls), 3)

    def test_advisory_revision_warning_delivers_but_is_recorded(self):
        case = CASES[0]
        payload = self.make_revision(case)
        candidate = deepcopy(case['candidate'])
        candidate['student_view']['stem'] += '\n按上述规则。'
        model = RepairReplay(candidate, bad_audit='requirements')
        result = revise_authored(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'REVISED', result)
        question, = result['questions']
        self.assertEqual(question['self_check']['review_warnings'],
                         [{'check': 'requirements', 'reason': 'Protocol fixture only.'}])
        self.assertEqual(len(model.calls), 3)

    def test_replacements_preserve_unmodified_fields_and_reject_ambiguous_paths(self):
        original = {'student_view': {'stem': '原题干', 'parts': [{'score': 2, 'prompt': '原小问'}]}}
        replacement = {'path': ['student_view', 'parts', 0, 'prompt'], 'value': '新小问'}
        updated = apply_replacements(original, [replacement])
        self.assertEqual(updated['student_view']['parts'], [{'score': 2, 'prompt': '新小问'}])
        self.assertEqual(original['student_view']['parts'][0]['prompt'], '原小问')
        for invalid in (['student_view', 'parts', -1], ['student_view', 'parts', False],
                        ['student_view', 'missing'], ['metadata'], ['student_view', 'parts', 0]):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                apply_replacements(original, [replacement, {'path': invalid, 'value': {}}])
