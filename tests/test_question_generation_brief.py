from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.brief_authoring import (
    CHAPTER_QUERIES, PLAN_PROMPT, SCOUT_PROMPT, explicit_total_score, generate_from_brief,
)
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
                if request['question_type'] == 'single_choice':
                    author_options = {o['id']: o['text'] for o in case['candidate']['student_view']['options']}
                    mapping = question['self_check']['delivered_option_mapping']
                    self.assertEqual({o['id']: o['text'] for o in question['student_view']['options']},
                                     {label: author_options[author_id]
                                      for label, author_id in mapping.items()})
                else:
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

    def test_comprehensive_total_follows_a_self_consistent_design_when_not_pinned(self):
        case = next(c for c in CASES if c['request']['question_type'] == 'comprehensive')
        request = case['request']
        design = deepcopy(case['candidate'])
        design['student_view']['parts'][1]['score'] = 6
        design['instructor_view']['parts'][1]['scoring_points'].append(
            {'id': 's9', 'points': 2, 'criterion': '补充判据。', 'expected': '补充期望。'})
        model = BriefReplay({**case, 'candidate': design})
        payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence', 'subject')}
        payload.update(question_type='comprehensive', brief='比较两种方案并说明翻转阈值。')
        result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        self.assertEqual(question['metadata']['score'], 12)
        self.assertEqual(question['generator']['parameters']['constraints']['total_score'], 12)
        self.assertEqual([p['score'] for p in question['student_view']['parts']], [3, 6, 3])

    def test_caller_pinned_total_still_rejects_a_different_design_total(self):
        case = next(c for c in CASES if c['request']['question_type'] == 'comprehensive')
        request = case['request']
        design = deepcopy(case['candidate'])
        design['student_view']['parts'][1]['score'] = 6
        design['instructor_view']['parts'][1]['scoring_points'].append(
            {'id': 's9', 'points': 2, 'criterion': '补充判据。', 'expected': '补充期望。'})
        for pinned in (10, 14):
            with self.subTest(pinned=pinned):
                model = BriefReplay({**case, 'candidate': design})
                payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence')}
                payload.update(question_type='comprehensive', brief='比较两种方案。', total_score=pinned)
                result = generate_from_brief(payload, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
                self.assertIn('综合题总分与请求不符', str(result['authoring_report']['details']))

    def test_prose_total_score_is_pinned_and_scaled_or_rejected(self):
        case = next(c for c in CASES if c['request']['question_type'] == 'comprehensive')
        request = case['request']
        base = {k: request[k] for k in ('schema_version', 'request_id', 'evidence')}
        # The fixture designs 3+4+3=10; a prose total of 20 doubles cleanly.
        model = BriefReplay(case)
        hinted = generate_from_brief({**base, 'brief': '想练 CPU 时间这块，帮我出一道总分20分的综合题。'},
                                     client=model, cache_path=self.cache)
        self.assertEqual(hinted['status'], 'GENERATED', hinted)
        plan_input = model.calls[0][1]['constraints']
        self.assertEqual((plan_input['total_score'], plan_input['question_type']), (20, 'comprehensive'))
        self.assertIn('严格等于该总分（20分）', plan_input['score_requirement'])
        self.assertNotIn('score_guidance', plan_input)
        question, = hinted['questions']
        self.assertEqual(question['metadata']['score'], 20)
        self.assertEqual([p['score'] for p in question['student_view']['parts']], [6, 8, 6])
        self.assertEqual([[p['points'] for p in s['scoring_points']]
                          for s in question['instructor_view']['parts']], [[4, 2], [6, 2], [4, 2]])
        self.assertIn('严格等于请求总分 20 分', model.calls[1][0])
        # A prose total that cannot be reached by exact scaling is rejected, not overridden.
        model = BriefReplay(case)
        rejected = generate_from_brief({**base, 'brief': '帮我出一道总分12分的综合题。'},
                                       client=model, cache_path=self.cache)
        self.assertEqual(rejected['status'], 'SELF_CHECK_FAILED', rejected)
        self.assertIn('综合题总分与请求不符', str(rejected['authoring_report']['details']))
        model = BriefReplay(case)
        unpinned = generate_from_brief({**base, 'brief': '比较两种方案对执行时间的影响。'},
                                       client=model, cache_path=self.cache)
        self.assertEqual(unpinned['status'], 'GENERATED', unpinned)
        plan_input = model.calls[0][1]['constraints']
        self.assertNotIn('total_score', plan_input)
        self.assertIn('默认按10分', plan_input['score_guidance'])
        self.assertEqual(unpinned['questions'][0]['metadata']['score'], 10)

    def test_prose_score_parser_ignores_impossible_totals(self):
        self.assertEqual(explicit_total_score('出一道满分 8 分的综合题'), 8)
        self.assertEqual(explicit_total_score('共 30 分'), 30)
        self.assertIsNone(explicit_total_score('共 40 分'))
        self.assertIsNone(explicit_total_score('每问 2 分'))
        self.assertIsNone(explicit_total_score('共 3 小问，每问 2 分'))
        self.assertEqual(explicit_total_score('排序 稳定性 复杂度，出一道12分的综合题'), 12)
        self.assertEqual(explicit_total_score('算法分析 递归 复杂度递推，出一道8分的综合题'), 8)
        self.assertIsNone(explicit_total_score(None, ['总分 1 分']))
        self.assertEqual(explicit_total_score('无分值说明', ['总分 12 分']), 12)

    def test_author_response_without_the_candidate_envelope_is_accepted(self):
        case = CASES[0]
        request = case['request']
        payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence', 'question_type')}
        model = BriefReplay(case)
        complete = model.complete

        def unwrapped(system, inputs):
            result = complete(system, inputs)
            return result['candidate'] if system.startswith(AUTHOR_PROMPT) else result

        with patch.object(model, 'complete', side_effect=unwrapped) as invoke:
            result = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        author_options = {o['id']: o['text'] for o in case['candidate']['student_view']['options']}
        delivered = {o['id']: o['text'] for o in question['student_view']['options']}
        self.assertEqual(sorted(delivered.values()), sorted(author_options.values()))
        self.assertEqual(delivered[question['instructor_view']['correct_option_id']],
                         author_options[case['candidate']['instructor_view']['correct_option_id']])
        self.assertEqual(invoke.call_count, 4)

    def test_envelope_normalization_never_swallows_incomplete_bodies(self):
        case = CASES[0]
        request = case['request']
        payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence', 'question_type')}
        for drifted in ({'student_view': {}, 'instructor_view': {}, 'design': {}},
                        {'student_view': {}, 'instructor_view': {}, 'design': {}, 'calculations': [], 'extra': 1}):
            with self.subTest(keys=sorted(drifted)):
                model = BriefReplay(case)
                complete = model.complete

                def partial(system, inputs, value=drifted):
                    if system.startswith(AUTHOR_PROMPT):
                        return value
                    return complete(system, inputs)

                with patch.object(model, 'complete', side_effect=partial) as invoke:
                    result = generate_from_brief(payload, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'SELF_CHECK_FAILED', result)
                self.assertEqual(invoke.call_count, 2)

    def test_stage_reasoning_effort_variants_never_share_cached_questions(self):
        case = CASES[0]
        request = case['request']
        payload = {k: request[k] for k in ('schema_version', 'request_id', 'evidence', 'question_type')}
        model = BriefReplay(case)
        first = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(first['status'], 'GENERATED', first)
        self.assertEqual(len(model.calls), 4)
        model.stage_reasoning_effort = {'plan': 'low', 'author': 'high', 'reader': 'low', 'audit': 'low'}
        second = generate_from_brief(payload, client=model, cache_path=self.cache)
        self.assertEqual(second['status'], 'GENERATED', second)
        self.assertEqual(len(model.calls), 8)
        # The stage effort is restored, not left behind on the client.
        self.assertFalse(hasattr(model, 'reasoning_effort'))
        self.assertEqual(generate_from_brief(payload, client=model, cache_path=self.cache), second)
        self.assertEqual(len(model.calls), 8)

