from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from question_generation.brief_authoring import CHAPTER_QUERIES, PLAN_PROMPT, generate_from_brief
from question_generation.curriculum import AREAS
from question_generation.general_authoring import AUTHOR_PROMPT, AUDIT_PROMPT, READER_PROMPT
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
        if system == PLAN_PROMPT:
            self.calls.append((system, deepcopy(payload)))
            return {'plan': self.plan}
        for base in (AUTHOR_PROMPT, AUDIT_PROMPT):
            if system.startswith(base):
                return super().complete(base, payload)
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
                self.assertEqual([s for s, _ in model.calls], [PLAN_PROMPT, AUTHOR_PROMPT, READER_PROMPT, AUDIT_PROMPT])
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
        for addition in ({}, {'brief': '想练信道容量这块'}):
            with self.subTest(addition=addition):
                model = BriefReplay(CASES[0])
                with patch.object(model, 'complete', return_value={'material_gaps': ['需要更多编码机制']}) as complete:
                    result = generate_from_brief({**payload, **addition}, client=model, cache_path=self.cache)
                self.assertEqual(result['status'], 'NEEDS_MATERIAL', result)
                self.assertEqual(complete.call_count, 1)
                planning_input = complete.call_args.args[1]
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
