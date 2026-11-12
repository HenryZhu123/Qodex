import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from test_question_generation_brief import BriefReplay
from test_question_generation_general import CASES

from question_generation.brief_authoring import generate_from_brief
from question_generation.preview import PreviewTrace, planning_format, unfinished_draft
from question_generation.ui import preview_result


class WorkbenchTests(TestCase):
    def test_workbench_wrapper_applies_stage_budgets_and_efforts_to_the_inner_client(self):
        from io import BytesIO

        from question_generation.model_client import JsonModel, complete_stage
        with patch.dict('os.environ', {'DEEPSEEK_BASE_URL': 'https://fixture.invalid',
                                       'DEEPSEEK_MODEL': 'test', 'DEEPSEEK_API_KEY': 'fixture'}):
            model = JsonModel.from_env()
        trace = PreviewTrace(model)
        envelope = b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}'
        expected = {'plan': (32768, 240, 'low'), 'author': (32768, 600, 'high'),
                    'reader': (32768, 600, 'low'), 'audit': (32768, 600, 'low')}
        with patch('question_generation.model_client.build_opener') as opener:
            opener.return_value.open.side_effect = lambda *args, **kwargs: BytesIO(envelope)
            for stage, (tokens, timeout, effort) in expected.items():
                with self.subTest(stage=stage):
                    complete_stage(trace, stage, 'json', {})
                    call = opener.return_value.open.call_args
                    sent = json.loads(call.args[0].data)
                    self.assertEqual(sent['max_tokens'], tokens)
                    self.assertEqual(sent['reasoning_effort'], effort)
                    self.assertEqual(call.kwargs['timeout'], min(timeout, 90))
                    self.assertEqual((model.max_output_tokens, model.timeout, model.reasoning_effort),
                                     (16384, 120, 'high'))
        self.assertEqual(dict(trace.stage_efforts), {'需求细化': 'low', '题目创作': 'high',
                                                    '独立解答': 'low', '反例与解析审计': 'low'})

    def test_automatic_material_plan_allows_optional_queries_without_existing_selection(self):
        payload = {'scope': [{'id': 'os.memory', 'subject': 'operating_systems'}],
                   'evidence': [{'material': {'id': 'source-1'}}], 'fixed': {'subject': 'operating_systems'}}
        explicit = planning_format(payload)['anyOf'][0]['properties']['plan']
        automatic = planning_format(payload, allow_queries=True)['anyOf'][0]['properties']['plan']
        self.assertNotIn('material_queries', explicit['properties'])
        self.assertEqual(automatic['properties']['evidence_ids']['minItems'], 0)
        self.assertIn('material_queries', automatic['properties'])
        self.assertNotIn('material_queries', automatic['required'])
        self.assertNotIn('subject', automatic['properties'])

    def test_incomplete_output_can_preview_only_complete_view_fields(self):
        prefix = '{"candidate":{"student_view":{"stem":"模型题干","options":[]},'
        self.assertEqual(unfinished_draft(prefix + '"instructor_view":{"explanation":"截断'),
                         {'student_view': {'stem': '模型题干', 'options': []}})
        self.assertIsNone(unfinished_draft('{"message":"student_view 不完整'))
        self.assertIsNone(unfinished_draft('{"candidate":{"student_view":{"stem":"截断'))

    def test_cloud_requires_confirmation_before_loading_credentials(self):
        with patch('question_generation.ui.JsonModel.from_env') as model:
            for value in (None, False, 1, 'true'):
                result = preview_result({'request': {}, 'cloud_confirmed': value}, None, 'deepseek')
                self.assertEqual(result['status'], 'CLOUD_CONFIRMATION_REQUIRED')
            model.assert_not_called()

    def test_rejected_local_candidate_remains_distinct_from_delivered_questions(self):
        case = CASES[0]
        payload = {k: case['request'][k] for k in ('schema_version', 'request_id', 'evidence')}
        bad_audit = BriefReplay(case)
        bad_audit.bad_audit = 'grounding'
        with TemporaryDirectory() as tmp, patch('question_generation.ui.JsonModel.from_env') as cloud:
            def run(request, *, knowledge, client, cache_path):
                return generate_from_brief(request, knowledge=knowledge, client=client, cache_path=Path(tmp) / 'cache.sqlite')

            with patch('question_generation.ui.generate_from_brief', side_effect=run), patch(
                'question_generation.ui.LocalPreviewModel', side_effect=[BriefReplay(case), bad_audit]
            ):
                accepted = preview_result({'request': payload}, None, 'local')
                rejected = preview_result({'request': {**payload, 'request_id': 'reject'}}, None, 'local')
            cloud.assert_not_called()
        self.assertEqual(accepted['status'], 'GENERATED')
        self.assertNotIn('unverified_draft', accepted['preview'])
        self.assertEqual(rejected['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(rejected['questions'], [])
        self.assertEqual(rejected['preview']['unverified_draft']['student_view'], case['candidate']['student_view'])
