"""Contract, failure injection, cost and correctness tests; not quality evidence."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import itertools
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.authoring import generate_authored, VERSION, AUTHOR_PROMPT, READER_PROMPT, AUDIT_PROMPT
from question_generation.batch import generate_batch
from question_generation.generation import generate_question
from question_generation.knowledge import with_knowledge
from question_generation.model_client import ModelError
from question_generation.verification import solve, verify_witnesses

ROOT = Path(__file__).resolve().parents[1]


def request():
    value = json.loads((ROOT / 'question_generation/examples/paging.json').read_text())
    value['constraints']['authoring'] = {'objective': 'diagnose'}
    return value


def candidate():
    return {
        'stem': '页大小为256 B，虚页1映射页框5。虚地址257被某计算过程算成1280。若其余步骤正确，遗漏了哪一步？',
        'options': [{'id': k, 'text': v} for k, v in zip('ABCD', ['加页内偏移', '查页表', '除以页大小', '页框乘页大小'])],
        'correct_option_id': 'A', 'explanation': '257=1×256+1，正确地址5×256+1=1281，报告值遗漏偏移1。',
        'option_explanations': dict(zip('ABCD', ['遗漏偏移得到1280。', '不查页表不能得到页框5。', '不拆地址不能确定虚页1。', '不乘页大小不会得到1280。'])),
        'misconceptions': dict(zip('BCD', ['混淆页号与页框。', '混淆拆分和组装。', '忽略报告值已含页框基址。'])),
        'learning_objective': '通过错误输出反推遗漏步骤', 'reasoning_steps': ['拆分地址', '查表并组装', '对比错误地址'],
        'evidence_ids': ['ostep-paging'], 'calculations': [{'kind': 'paging', 'inputs': {
            'page_size': 256, 'address': 257, 'page_table': {'1': 5}},
            'result': {'page': 1, 'offset': 1, 'frame': 5, 'physical_address': 1281}}],
    }


class FakeModel:
    """Scripted transport only, deliberately not a pedagogical evaluator."""
    model, base_url = 'test-double', 'https://fixture.invalid'

    def __init__(self, mutate=None, bad_reader=False, bad_audit=False):
        self.usage, self.calls = [], []
        self.mutate, self.bad_reader, self.bad_audit = mutate, bad_reader, bad_audit

    def complete(self, system, payload):
        self.calls.append((system, deepcopy(payload)))
        if system == AUTHOR_PROMPT:
            value = {'candidates': [candidate(), candidate()]}
            if self.mutate:
                self.mutate(value)
            return value
        if system == READER_PROMPT:
            reviews = []
            for item in payload['candidates']:
                answer = next(o['id'] for o in item['options'] if o['text'] == '加页内偏移')
                reviews.append({'candidate_index': item['candidate_index'], 'answer': 'NONE' if self.bad_reader else answer,
                                'solution': '独立复算为1281，报告值差1。',
                                'quality': dict.fromkeys(['answerability', 'grounding', 'constraint_alignment', 'objective_alignment', 'depth', 'distractors', 'clarity'], 2),
                                'issues': [], 'calculation_coverage': '257→1281'})
            return {'reviews': reviews}
        if system == AUDIT_PROMPT:
            return {'valid': not self.bad_audit, 'issues': ['解析错误'] if self.bad_audit else []}
        raise AssertionError('unexpected model call')


class AuthoringTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'cache.sqlite'

    def run_model(self, model, payload=None):
        return generate_authored(payload or request(), client=model, cache_path=self.path)

    def test_blind_reading_does_not_receive_answer_and_success_is_cached(self):
        model = FakeModel()
        result = self.run_model(model)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(len(model.calls), 3)
        blind = model.calls[1][1]['candidates'][0]
        self.assertEqual(set(blind), {'candidate_index', 'stem', 'options'})
        self.assertEqual(self.run_model(model), result)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(result['questions'][0]['review_status'], 'PENDING')
        self.assertEqual(result['questions'][0]['student_view'].keys(), {'stem', 'options'})

    def test_concurrent_retries_pay_once_and_return_identical_content(self):
        model = FakeModel()
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: self.run_model(model), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(model.calls), 3)

    def test_high_effort_does_not_reuse_historical_low_effort_cache(self):
        from hashlib import sha256

        model = FakeModel()
        model.reasoning_effort = 'high'
        payload = request()
        old_key = json.dumps([VERSION, model.base_url, model.model, payload], sort_keys=True, ensure_ascii=False)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE results (digest TEXT PRIMARY KEY, result TEXT NOT NULL)')
            db.execute('INSERT INTO results VALUES (?, ?)', (sha256(old_key.encode()).hexdigest(), '{}'))
        result = self.run_model(model, payload)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(self.run_model(model, payload), result)
        self.assertEqual(len(model.calls), 3)

    def test_failed_numerical_witnesses_never_reach_model_reader(self):
        def corrupt(value):
            for item in value['candidates']:
                item['calculations'][0]['result']['physical_address'] = 1280
        model = FakeModel(mutate=corrupt)
        self.assertEqual(self.run_model(model)['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)

    def test_different_output_budgets_do_not_share_cached_questions(self):
        model = FakeModel()
        default = self.run_model(model)
        model.max_output_tokens = 32768
        expanded = self.run_model(model)
        self.assertEqual(expanded, default)
        self.assertEqual(len(model.calls), 6)
        self.assertEqual(self.run_model(model), expanded)
        self.assertEqual(len(model.calls), 6)
        model.max_output_tokens = 16384
        self.assertEqual(self.run_model(model), default)
        self.assertEqual(len(model.calls), 6)

    def test_blind_disagreement_and_bad_explanation_fail_closed(self):
        for model in (FakeModel(bad_reader=True), FakeModel(bad_audit=True)):
            with self.subTest(model=model):
                result = self.run_model(model)
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
                self.assertEqual(result['questions'], [])

    def test_invalid_candidates_fail_closed(self):
        mutations = [lambda c: c.update(correct_option_id=['A']),
                     lambda c: c.update(evidence_ids=['invented']),
                     lambda c: c['options'][1].update(text=c['options'][0]['text']),
                     lambda c: c.update(calculations=[]),
                     lambda c: c.update(misconceptions={})]
        for change in mutations:
            def mutate(value):
                for c in value['candidates']:
                    change(c)
            self.assertEqual(self.run_model(FakeModel(mutate=mutate))['status'], 'SELF_CHECK_FAILED')

    def test_missing_material_precedes_model_and_knowledge_lookup_still_works(self):
        payload = request()
        evidence = payload.pop('evidence')
        model = FakeModel()
        with patch('question_generation.authoring.JsonModel.from_env', return_value=model), patch.dict(
            'os.environ', {'QUESTION_GENERATION_AUTHORING_CACHE': str(self.path)}
        ):
            self.assertEqual(generate_question(payload)['status'], 'NEEDS_MATERIAL')
            self.assertEqual(model.calls, [])
            result = with_knowledge(generate_question, payload, lambda subject, topic: evidence)
            self.assertEqual(result['status'], 'GENERATED')

    def test_provider_failure_and_invalid_settings_are_structured(self):
        model = FakeModel()
        with patch.object(model, 'complete', side_effect=ModelError('timeout', code='transport_error')):
            result = self.run_model(model)
            self.assertEqual(result['status'], 'MODEL_UNAVAILABLE')
            self.assertEqual(result['authoring_report']['model_failure'], {'code': 'transport_error'})
        for settings in (None, [], {'objective': []}, {'objective': 'invent'}, {'objective': 'analyze', 'focus': 1}):
            payload = request()
            payload['constraints']['authoring'] = settings
            self.assertEqual(self.run_model(model, payload)['status'], 'INVALID_REQUEST')

    def test_provider_response_issue_reaches_authoring_report(self):
        from io import BytesIO
        from question_generation.model_client import JsonModel
        model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture')
        with patch('question_generation.model_client.build_opener') as opener:
            opener.return_value.open.return_value = BytesIO(
                b'{"choices":[{"finish_reason":"stop","message":{"content":"[]"}}],'
                b'"usage":{"prompt_tokens":10,"completion_tokens":20}}')
            result = self.run_model(model)
        self.assertEqual(result['status'], 'MODEL_UNAVAILABLE')
        self.assertEqual(result['questions'], [])
        report = result['authoring_report']
        self.assertEqual(report['model_failure'], {
            'code': 'invalid_content', 'finish_reason': 'stop', 'response_issue': 'content_not_object'})
        self.assertEqual(report['usage'][0]['completion_tokens'], 20)

    def test_unvalidated_tcp_transfer_is_blocked_before_api_or_cache(self):
        payload = json.loads((ROOT / 'question_generation/examples/tcp.json').read_text())
        payload['constraints']['authoring'] = {'objective': 'transfer'}
        model = FakeModel()
        self.assertEqual(self.run_model(model, payload)['status'], 'UNSUPPORTED_REQUEST')
        self.assertEqual(model.calls, [])

    def test_batch_does_not_multiply_paid_candidate_attempts(self):
        payload = request()
        slot = {k: payload[k] for k in ('subject', 'topic', 'question_type', 'constraints', 'evidence')}
        batch = {'schema_version': '0.1', 'request_id': 'cost-test', 'seed': 42, 'question_count': 1,
                 'total_score': 2, 'slots': [{**slot, 'slot_id': 's1', 'count': 1, 'score_per_question': 2}]}
        calls = []
        def generate(item):
            calls.append(item)
            return {'status': 'SELF_CHECK_FAILED', 'questions': [], 'message': 'fixture'}
        self.assertEqual(generate_batch(batch, single_generator=generate)['status'], 'NO_QUESTIONS')
        self.assertEqual(len(calls), 1)
        batch['question_count'] = batch['slots'][0]['count'] = 3
        batch['total_score'] = 6
        self.assertEqual(generate_batch(batch, single_generator=generate)['status'], 'INVALID_REQUEST')
        self.assertEqual(len(calls), 1)

    def test_explicit_offset_cannot_be_ignored_by_a_numerically_correct_candidate(self):
        payload = request()
        payload['constraints']['offset'] = 0
        model = FakeModel()
        self.assertEqual(self.run_model(model, payload)['status'], 'SELF_CHECK_FAILED')
        self.assertEqual(len(model.calls), 1)


class WitnessTests(TestCase):
    def test_paging_and_cache_against_arithmetic_oracle(self):
        for size in (16, 256, 4096):
            for address in (0, 1, size-1, size, 65535):
                p, offset = divmod(address, size)
                result = solve('paging', {'page_size': size, 'address': address, 'page_table': {str(p): 7}})
                self.assertEqual(result['physical_address'], 7*size+offset)
                for block in (4, 8):
                    result = solve('cache', {'cache_size': size, 'block_size': block, 'address': address})
                    self.assertEqual(result, {'tag': address//size, 'index': address//block % (size//block), 'offset': address % block})

    def test_stack_minimum_capacity_against_exhaustive_operation_paths(self):
        for n in range(2, 7):
            reachable = {}
            def walk(next_value, stack, out, peak):
                if len(out) == n:
                    reachable[out] = min(reachable.get(out, n+1), peak)
                if next_value <= n:
                    walk(next_value+1, stack+(next_value,), out, max(peak, len(stack)+1))
                if stack:
                    walk(next_value, stack[:-1], out+(stack[-1],), peak)
            walk(1, (), (), 0)
            for permutation in itertools.permutations(range(1, n+1)):
                answer = solve('stack', {'output': list(permutation)})
                self.assertEqual(answer['reachable'], permutation in reachable)
                self.assertEqual(answer['minimum_capacity'], reachable.get(permutation))

    def test_invalid_witness_types_and_ranges(self):
        for kind, inputs in [('cache', {'cache_size': True, 'block_size': 4, 'address': 0}),
                             ('stack', {'output': [True, 2]}), ('python', {'code': 'raise Exception()'}),
                             ('paging', {'page_size': 256, 'address': 256, 'page_table': {'01': 5}})]:
            with self.assertRaises(ValueError):
                solve(kind, inputs)
        verify_witnesses('tcp_message_boundaries', [])

class TransportTests(TestCase):
    def test_explicit_output_budget_is_sent_to_provider(self):
        from io import BytesIO
        from question_generation.model_client import JsonModel
        with patch.dict('os.environ', {'DEEPSEEK_BASE_URL': 'https://fixture.invalid',
                                      'DEEPSEEK_MODEL': 'test', 'DEEPSEEK_API_KEY': 'fixture',
                                      'QUESTION_GENERATION_MAX_OUTPUT_TOKENS': '32768'}):
            model = JsonModel.from_env()
        with patch('question_generation.model_client.build_opener') as opener:
            opener.return_value.open.return_value = BytesIO(
                b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}')
            self.assertEqual(model.complete('json', {}), {})
            self.assertEqual(json.loads(opener.return_value.open.call_args.args[0].data)['max_tokens'], 32768)
        for value in ('bad', '0'):
            with self.subTest(value=value), patch.dict('os.environ', {
                'DEEPSEEK_BASE_URL': 'https://fixture.invalid', 'DEEPSEEK_MODEL': 'test',
                'DEEPSEEK_API_KEY': 'fixture', 'QUESTION_GENERATION_MAX_OUTPUT_TOKENS': value
            }):
                with self.assertRaises(ModelError):
                    JsonModel.from_env()

    def test_truncated_or_malformed_responses_are_not_successes(self):
        from io import BytesIO
        from question_generation.model_client import JsonModel
        cases = [(b'[]', 'invalid_response', None, 'envelope_shape'),
                 (b'not json', 'invalid_response', None, 'envelope_decode'),
                 (b'{"choices":[]}', 'invalid_response', None, 'envelope_shape')]
        for reason, message, code, safe_reason, issue in (
            ('length', {'content': '{}'}, 'incomplete_output', 'length', None),
            ('unexpected provider text', {'content': '{}'}, 'incomplete_output', 'unknown', None),
            ('stop', {'content': None}, 'empty_content', 'stop', None),
            ('stop', {'content': ' '}, 'empty_content', 'stop', None),
            ('stop', {}, 'invalid_content', 'stop', 'envelope_shape'),
            ('stop', {'content': {'private': True}}, 'invalid_content', 'stop', 'content_type'),
            ('stop', {'content': '{"private题":'}, 'invalid_content', 'stop', 'content_decode'),
            ('stop', {'content': '[]'}, 'invalid_content', 'stop', 'content_not_object'),
        ):
            raw = json.dumps({'choices': [{'finish_reason': reason, 'message': message}],
                              'usage': {'prompt_tokens': 10, 'completion_tokens': 90,
                                        'completion_tokens_details': {'reasoning_tokens': 75}}}).encode()
            cases.append((raw, code, safe_reason, issue))
        for raw, code, reason, issue in cases:
            with self.subTest(raw=raw):
                model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture')
                with patch('question_generation.model_client.build_opener') as opener:
                    opener.return_value.open.return_value = BytesIO(raw)
                    with self.assertRaises(ModelError) as error:
                        model.complete('json', {})
                    self.assertEqual(error.exception.diagnostics.get('code'), code)
                    self.assertEqual(error.exception.diagnostics.get('finish_reason'), reason)
                    self.assertEqual(error.exception.diagnostics.get('response_issue'), issue)
                    if issue == 'content_decode':
                        self.assertEqual(error.exception.diagnostics['content_decode_position'], 12)
                        self.assertEqual(error.exception.diagnostics['content_length'], 12)
                    else:
                        self.assertNotIn('content_decode_position', error.exception.diagnostics)
                        self.assertNotIn('content_length', error.exception.diagnostics)
                    self.assertNotIn('private', str(error.exception) + str(error.exception.diagnostics))
                    if reason is not None:
                        self.assertEqual(model.usage[0]['reasoning_tokens'], 75)

    def test_interrupted_chunked_response_fails_without_retry_or_partial_output(self):
        from http.client import IncompleteRead
        from io import BytesIO
        from question_generation.model_client import JsonModel
        class BrokenResponse(BytesIO):
            def read1(self, size):
                raise IncompleteRead(b'partial private response')
        model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture')
        with patch('question_generation.model_client.build_opener') as opener:
            opener.return_value.open.return_value = BrokenResponse()
            with self.assertRaises(ModelError) as error:
                model.complete('json', {})
            self.assertNotIn('private', str(error.exception))
            self.assertEqual(error.exception.diagnostics, {'code': 'transport_error'})
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertEqual(model.usage, [])

    def test_opencode_go_session_and_billing_survive_incomplete_output(self):
        from io import BytesIO
        from question_generation.model_client import JsonModel
        model = JsonModel(base_url='https://opencode.ai/inference/go/openai/v1',
                          model='deepseek-v4.1-flash', api_key='fixture')
        receipts = []
        for finish in ('stop', 'length'):
            raw = json.dumps({'model': 'deepseek-v4.1-flash',
                              'choices': [{'finish_reason': finish, 'message': {'content': '{}'}}],
                              'usage': {'completion_tokens': 20, 'cost': 0,
                                        'opencode': {'billing_source': 'go', 'allowance': 0.001,
                                                     'list_cost': 0.002, 'private': 'excluded'}}}).encode()
            with patch('question_generation.model_client.build_opener') as opener:
                opener.return_value.open.return_value = BytesIO(raw)
                if finish == 'stop':
                    self.assertEqual(model.complete('json', {}), {})
                else:
                    with self.assertRaises(ModelError):
                        model.complete('json', {})
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('User-agent'), 'Qodex-question-generation/0.5')
                receipts.append(request.get_header('X-opencode-session'))
        self.assertEqual(receipts, [model.session_id] * 2)
        self.assertNotEqual(JsonModel(base_url=model.base_url, model=model.model, api_key='fixture').session_id,
                            model.session_id)
        for usage in model.usage:
            self.assertEqual(usage['cost'], 0)
            self.assertEqual(usage['response_model'], 'deepseek-v4.1-flash')
            self.assertEqual(usage['opencode'], {'billing_source': 'go', 'allowance': 0.001, 'list_cost': 0.002})

    def test_transport_bounds_tokens_and_ignores_provider_reasoning_text(self):
        from io import BytesIO
        from question_generation.model_client import JsonModel
        model = JsonModel(base_url='https://fixture.invalid', model='test', api_key='fixture')
        raw = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}',
                                                                         'reasoning_content': 'not an artifact'}}],
                          'usage': {'prompt_tokens': 10, 'completion_tokens': 20}}).encode()
        with patch('question_generation.model_client.build_opener') as opener:
            opener.return_value.open.return_value = BytesIO(raw)
            self.assertEqual(model.complete('json', {}), {'ok': True})
            req = opener.return_value.open.call_args.args[0]
            sent = json.loads(req.data)
            self.assertEqual(sent['max_tokens'], 16384)
            self.assertEqual(sent['thinking'], {'type': 'enabled'})
            self.assertEqual(sent['reasoning_effort'], 'high')
            self.assertEqual(len(model.usage), 1)
            self.assertNotIn('reasoning_content', str(model.usage))
