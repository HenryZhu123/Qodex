from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.brief_authoring import CHAPTER_QUERIES, PLAN_PROMPT, SCOUT_PROMPT, generate_from_brief
from question_generation.curriculum import AREAS
from question_generation.general_authoring import AUTHOR_PROMPT, AUTHOR_VIEWS, AUDIT_PROMPT, READER_PROMPT
from question_generation.model_client import ModelError
from test_question_generation_general import CASES, Replay


class BriefReplay(Replay):
    def __init__(self, case):
        super().__init__(case['candidate'])
        request = case['request']
        settings = request['constraints']['authoring']
        design = self.candidate['design']
        self.plan = {k: request[k] for k in ('subject', 'topic', 'question_type')}
        self.plan.update(syllabus_areas=settings['syllabus_areas'], objective=settings['objective'],
                         target=design['target'], task='按题设给出决定性推导。', student_evidence=design['derivation'][-1]['result'],
                         evidence_ids=list(dict.fromkeys(c['evidence_id'] for c in design['claims'])))

    def complete(self, system, payload):
        if system in (PLAN_PROMPT, SCOUT_PROMPT):
            self.calls.append((system, deepcopy(payload)))
            return {'plan': self.plan}
        if system.startswith(AUDIT_PROMPT):
            return super().complete(AUDIT_PROMPT, payload)
        return super().complete(system, payload)


class BriefAuthoringTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cache = Path(directory.name) / 'cache.sqlite'
        guard = patch('question_generation.model_client.build_opener', side_effect=AssertionError('No external models'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_material_only_and_optional_type_across_four_subjects(self):
        for case in CASES:
            request = case['request']
            payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence')}
            model = BriefReplay(case)
            with self.subTest(topic=model.plan['topic']):
                result = generate_from_brief(payload, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'GENERATED', result)
                self.assertEqual(generate_from_brief(payload, client=model, cache_path=self.cache), result)
                author = AUTHOR_PROMPT + AUTHOR_VIEWS[request['question_type']]
                plan_prompt, author_prompt, reader_prompt, audit_prompt = [s for s, _ in model.calls]
                self.assertEqual((plan_prompt, reader_prompt, audit_prompt), (PLAN_PROMPT, READER_PROMPT, AUDIT_PROMPT))
                self.assertTrue(author_prompt.startswith(author + '\nbrief_plan.brief'))
                question, = result['questions']
                self.assertEqual(question['review_status'], 'PENDING')
                self.assertEqual(question['student_view'], case['candidate']['student_view'])
                self.assertEqual(question['metadata']['question_type'], request['question_type'])
                self.assertEqual(set(model.calls[2][1]), {'question_type', 'student_view'})
                self.assertEqual(model.calls[3][1]['brief_plan'], result['authoring_report']['plan'])
                self.assertEqual(question['generator']['parameters']['brief_plan'], result['authoring_report']['plan'])

    def test_pins_and_invalid_evidence_never_reach_author(self):
        case = CASES[0]
        payload = {k: case['request'][k] for k in ('schema_version', 'request_id', 'evidence')}
        payload.update(subject='data_structures', syllabus_areas=['ds.graphs'], question_type='single_choice')
        for drift in (
            {'subject': 'computer_networks', 'syllabus_areas': ['cn.network']},
            {'syllabus_areas': ['ds.sort']}, {'question_type': 'comprehensive'},
            {'evidence_ids': ['fabricated']}, {'subject': []}, {'objective': []},
        ):
            model = BriefReplay(case)
            model.plan.update(drift)
            result = generate_from_brief(payload, client=model, cache_path=self.cache)
            self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
            self.assertEqual(len(model.calls), 1)

    def test_provider_failure_identifies_each_stage_without_returning_a_question(self):
        case = CASES[0]
        payload = {k: case['request'][k] for k in ('schema_version', 'request_id', 'evidence')}
        for index, stage in enumerate(('plan', 'author', 'reader', 'audit')):
            with self.subTest(stage=stage):
                model = BriefReplay(case)
                complete = model.complete

                def fail_at_stage(system, inputs):
                    if len(model.calls) == index:
                        model.usage.append({'completion_tokens': 16384})
                        raise ModelError('incomplete', code='incomplete_output', finish_reason='length')
                    return complete(system, inputs)

                with patch.object(model, 'complete', side_effect=fail_at_stage) as invoke:
                    result = generate_from_brief(payload, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'MODEL_UNAVAILABLE')
                self.assertEqual(result['questions'], [])
                self.assertEqual(result['authoring_report']['usage'], model.usage)
                self.assertEqual(result['authoring_report']['model_failure'], {
                    'code': 'incomplete_output', 'finish_reason': 'length', 'stage': stage,
                })
                self.assertEqual(invoke.call_count, index + 1)

    def test_pinned_comprehensive_and_user_requirement_survive_planning(self):
        case = next(c for c in CASES if c['request']['question_type'] == 'comprehensive')
        request = case['request']
        model = BriefReplay(case)
        payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence', 'subject')}
        payload['evidence'] = [*payload['evidence'], {**payload['evidence'][0], 'id': 'unused-source'}]
        payload.update(brief='考查决定性条件，解释理由。', requirements=['明确必要条件'],
                       total_score=request['constraints']['total_score'], syllabus_areas=model.plan['syllabus_areas'])
        for fixed in ('subject', 'question_type', 'syllabus_areas'):
            model.plan.pop(fixed)
        result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(model.calls[1][1]['constraints']['requirements'], payload['requirements'])
        self.assertEqual(model.calls[1][1]['evidence'], request['evidence'])
        self.assertEqual(result['questions'][0]['metadata']['score'], payload['total_score'])
        self.assertEqual(model.calls[3][1]['brief_plan']['brief'], payload['brief'])
        self.assertEqual(model.calls[0][1]['fixed']['syllabus_areas'], payload['syllabus_areas'])

    def test_scouting_bare_and_rough_requests_with_source_notes(self):
        self.assertEqual(set(CHAPTER_QUERIES), {a for group in AREAS.values() for a in group})
        payload = {'schema_version': '0.1', 'request_id': 'note-only', 'subject': 'computer_networks',
                   'syllabus_areas': ['cn.physical']}
        for addition in ({}, {'brief': '想练信道容量这块'}, {'brief': '直接出一道 408 题。'}):
            with self.subTest(addition=addition):
                model = BriefReplay(CASES[0])
                with patch.object(model, 'complete', return_value={'material_gaps': ['需要更多编码机制']}) as complete:
                    result = generate_from_brief({**payload, **addition}, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'NEEDS_MATERIAL', result)
                self.assertEqual(complete.call_count, 1)
                planning_input = complete.call_args.args[1]
                self.assertEqual(planning_input['brief'], addition.get('brief', ''))
                self.assertEqual(len(planning_input['evidence']), 2)
                self.assertEqual({item['subject'] for item in planning_input['evidence']}, {'computer_networks'})

    def test_empty_material_and_invalid_request_do_not_call_model(self):
        payload = {'schema_version': '0.1', 'request_id': 'empty', 'evidence': []}
        model = BriefReplay(CASES[0])
        with patch('question_generation.brief_authoring.discover', side_effect=AssertionError('Explicit evidence wins')):
            self.assertEqual(generate_from_brief(payload, client=model)['status'], 'NEEDS_MATERIAL')
            for fields in ({'seed': True}, {'brief': []}, {'subject': []}, {'syllabus_areas': ['missing']},
                           {'total_score': 4, 'question_type': 'single_choice'}, {'evidence': [{}]}):
                self.assertNotEqual(generate_from_brief({**payload, **fields}, client=model)['status'], 'GENERATED')
        self.assertEqual(model.calls, [])

    def test_focused_lookup_adds_separate_evidence_without_another_model_call(self):
        case = CASES[0]
        request = case['request']
        materials = request['evidence']
        model = BriefReplay(case)
        area, = model.plan['syllabus_areas']
        model.plan.update(evidence_ids=[], material_queries=[{'area': area, 'query': '拓扑序 唯一'}])
        payload = {'schema_version': '0.1', 'request_id': 'scouted', 'brief': '只能排成一种次序',
                   'syllabus_areas': [area]}
        unrelated = {**materials[0], 'id': 'irrelevant'}
        with patch('question_generation.brief_authoring.discover', side_effect=[[unrelated], materials]) as search:
            result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(len(model.calls), 4)
        self.assertEqual(model.calls[0][0], SCOUT_PROMPT)
        self.assertEqual(model.calls[1][1]['evidence'], materials)
        self.assertEqual(search.call_args.kwargs, {'limit': 1, 'exact_anchor': True, 'related_notes': True})
        self.assertEqual(result['authoring_report']['plan']['evidence_ids'], [materials[0]['id']])

    def test_material_query_falls_back_to_related_notes(self):
        case = CASES[0]
        model = BriefReplay(case)
        area, = model.plan['syllabus_areas']
        model.plan.update(evidence_ids=[], material_queries=[{'area': area, 'query': '只能排成一种次序'}])
        payload = {'schema_version': '0.1', 'request_id': 'fallback', 'brief': '只能排成一种次序',
                   'syllabus_areas': [area]}
        shortlisted = case['request']['evidence'][0]
        hit = shortlisted
        with patch('question_generation.brief_authoring.discover',
                   side_effect=[[shortlisted], [], [hit]]) as search:
            result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(search.call_count, 3)
        self.assertEqual(search.call_args.kwargs,
                         {'limit': 1, 'exact_anchor': False, 'related_notes': True})
        self.assertEqual(result['authoring_report']['plan']['evidence_ids'], [hit['id']])

    def test_missing_supplementary_query_keeps_selected_materials(self):
        case = CASES[0]
        model = BriefReplay(case)
        area, = model.plan['syllabus_areas']
        materials = case['request']['evidence']
        model.plan.update(material_queries=[{'area': area, 'query': '不存在的补充机制'}])
        payload = {'schema_version': '0.1', 'request_id': 'missing-supplement',
                   'brief': '只能排成一种次序', 'syllabus_areas': [area]}
        with patch('question_generation.brief_authoring.discover',
                   side_effect=[materials, [], []]) as search:
            result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        self.assertEqual(search.call_count, 3)
        self.assertEqual(model.calls[1][1]['evidence'], materials)
        self.assertTrue(result['authoring_report']['material_query_gaps'])

    def test_focused_lookup_fails_before_author_when_material_is_missing_or_out_of_scope(self):
        case = CASES[0]
        model = BriefReplay(case)
        area, = model.plan['syllabus_areas']
        payload = {'schema_version': '0.1', 'request_id': 'no-match', 'brief': '只能排成一种次序',
                   'syllabus_areas': [area]}
        for addition, status in (
            ({'area': area, 'query': '缺失机制'}, 'NEEDS_MATERIAL'),
            ({'area': 'cn.link', 'query': '以太网'}, 'SELF_CHECK_FAILED'),
        ):
            model.plan.update(evidence_ids=[], material_queries=[addition])
            model.calls.clear()
            effects = ([[case['request']['evidence'][0]], [], []] if status == 'NEEDS_MATERIAL'
                       else [[case['request']['evidence'][0]]])
            with patch('question_generation.brief_authoring.discover',
                       side_effect=effects) as search:
                result = generate_from_brief(payload, client=model, cache_path=self.cache)
            self.assertEqual(result['status'], status, result)
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(search.call_count, 3 if status == 'NEEDS_MATERIAL' else 1)
        model.plan.update(material_queries=[{'area': area, 'query': '不应查询'}])
        with patch('question_generation.brief_authoring.discover', side_effect=AssertionError('Explicit evidence wins')):
            result = generate_from_brief({**payload, 'evidence': case['request']['evidence']},
                                         client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'SELF_CHECK_FAILED')
