"""Phase C false negatives: recorded candidates/readers that local checks rejected.

Four candidates were correct but died on a mechanical check (punctuation or a
page header inside a textbook quote, hexadecimal witness values). Two readers
agreed with the author but were dropped because ``quality.depth == 1``. The
fixtures are the recorded model responses plus the exact evidence payload, so
these tests do not need the local knowledge base or a network.
"""
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from question_generation.general_authoring import (
    CANDIDATE_FIELDS,
    READER_PROMPT,
    student_quality,
)
from question_generation.general_contract import contains_span, validate_candidate
from question_generation.generation import Request, _evidence_refs
from question_generation.verification import integer, solve

FIXTURES = Path(__file__).parent / 'fixtures/question_generation/phase_c_rescue'
CANDIDATE_CASES = ('ds.linear-sc', 'os.io-sc', 'cn.transport-co', 'os.memory-sc')
READER_CASES = ('co.instructions-sc', 'cn.architecture-sc')


def fixture(name):
    return json.loads((FIXTURES / f'{name}.json').read_text(encoding='utf-8'))


def request_for(data):
    """Rebuild the Request the author stage saw, without the local knowledge base."""
    fields = data['payload']
    evidence = [{key: item[key] for key in ('id', 'source', 'version', 'anchor', 'summary', 'rules')}
                for item in data['evidence']]
    refs = _evidence_refs(evidence, set(), '通用创作')
    return Request(fields['request_id'], fields['seed'],
                   {key: fields[key] for key in ('subject', 'topic', 'question_type')},
                   fields['constraints'], refs)


def normalize(authored):
    """The envelope normalization run() applies to an author response."""
    if 'candidate' not in authored and set(authored) == CANDIDATE_FIELDS:
        return {'candidate': authored}
    if set(authored) == {'candidate', 'calculations'} and isinstance(authored['candidate'], dict):
        candidate = authored['candidate']
        candidate.setdefault('calculations', authored['calculations'])
        return {'candidate': candidate}
    return authored


class RescuedCandidateTests(TestCase):
    def test_recorded_candidates_pass_validation_after_the_mechanical_fixes(self):
        for case_id in CANDIDATE_CASES:
            with self.subTest(case=case_id):
                data = fixture(case_id)
                request = request_for(data)
                authored = normalize(data['author_response'])
                self.assertEqual(set(authored), {'candidate'}, f'{case_id} envelope drift')
                evidence_ids = validate_candidate(authored['candidate'], request, data['evidence'])
                self.assertTrue(evidence_ids, f'{case_id} produced no evidence ids')

    def test_quote_tolerances_are_bounded_to_punctuation_and_page_noise(self):
        data = fixture('ds.linear-sc')
        candidate = normalize(data['author_response'])['candidate']
        k2 = next(claim for claim in candidate['design']['claims'] if claim['id'] == 'k2')
        source = next(item for item in data['evidence'] if item['id'] == k2['evidence_id'])
        # Same sentence; the source has a comma the quote omits.
        self.assertTrue(contains_span(k2['quote'], source['excerpt']))
        # Removing one character of substance still fails.
        doctored = k2['quote'].replace('需要修改指针', '需要修改内存')
        self.assertFalse(contains_span(doctored, source['excerpt']))
        # A fabricated sentence fails, and so does a 5-character fragment.
        self.assertFalse(contains_span('链表插入必须移动一半节点。', source['excerpt']))
        self.assertFalse(contains_span('插入操作', source['excerpt']))

    def test_page_header_split_quote_matches_only_when_the_gap_is_short(self):
        data = fixture('os.io-sc')
        candidate = normalize(data['author_response'])['candidate']
        k1 = next(claim for claim in candidate['design']['claims'] if claim['id'] == 'k1')
        source = next(item for item in data['evidence'] if item['id'] == k1['evidence_id'])
        self.assertTrue(contains_span(k1['quote'], source['excerpt']))
        cut = k1['quote'].index('较')
        left, right = k1['quote'][:cut + 1], k1['quote'][cut + 1:]
        # A short running header between the halves is tolerated ...
        self.assertTrue(contains_span(k1['quote'], left + '输\n入\n/' + right))
        # ... but a long unrelated block between them is not.
        self.assertFalse(contains_span(k1['quote'], left + 'x' * 20 + right))

    def test_hexadecimal_witness_values_are_parsed_not_rejected(self):
        data = fixture('os.memory-sc')
        candidate = normalize(data['author_response'])['candidate']
        witness, = candidate['calculations']
        self.assertEqual(witness['inputs']['address'], '0x0B7C')
        self.assertEqual(solve(witness['kind'], witness['inputs']), witness['result'])
        self.assertEqual(solve('paging', witness['inputs'])['physical_address'], 8060)
        self.assertEqual(integer('0B7CH', 0, 2**32 - 1), 2940)
        self.assertEqual(integer('0X0b7c', 0, 2**32 - 1), 2940)
        self.assertEqual(integer('2940', 0, 2**32 - 1), 2940)
        for rejected in ('0x', 'ZZ', '', True, 1.5, None):
            with self.subTest(value=rejected):
                with self.assertRaises(ValueError):
                    integer(rejected, 0, 2**32 - 1)


class RescuedReaderTests(TestCase):
    def test_recorded_reader_reviews_pass_quality_with_depth_one(self):
        for case_id in READER_CASES:
            with self.subTest(case=case_id):
                review = fixture(f'{case_id}.reader')['reader_response']
                self.assertEqual(review['quality']['depth'], 1)
                self.assertEqual(review['issues'], [])
                self.assertTrue(student_quality(review))

    def test_depth_zero_or_unanswerable_still_blocks(self):
        review = fixture('co.instructions-sc.reader')['reader_response']
        for broken, value in (('depth', 0), ('answerability', 1), ('clarity', 0), ('distractors', 0)):
            with self.subTest(field=broken):
                mutated = json.loads(json.dumps(review))
                mutated['quality'][broken] = value
                self.assertFalse(student_quality(mutated))
        with_issues = json.loads(json.dumps(review))
        with_issues['issues'] = ['Two readings give different answers.']
        self.assertFalse(student_quality(with_issues))

    def test_depth_one_reader_reaches_the_audit_and_is_recorded_as_a_warning(self):
        from test_question_generation_brief import BriefReplay  # noqa: PLC0415
        from test_question_generation_general import CASES  # noqa: PLC0415

        from question_generation.brief_authoring import generate_from_brief  # noqa: PLC0415

        case = CASES[0]

        class ShallowReader(BriefReplay):
            def complete(self, system, payload):
                result = super().complete(system, payload)
                if system == READER_PROMPT:
                    result['quality']['depth'] = 1
                return result

        model = ShallowReader(case)
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp, patch('question_generation.model_client.build_opener',
                                                side_effect=AssertionError('no network')):
            payload = {k: case['request'][k] for k in ('schema_version', 'request_id', 'evidence')}
            result = generate_from_brief(payload, client=model, cache_path=Path(tmp) / 'cache.sqlite')
        self.assertEqual(result['status'], 'GENERATED', result)
        question, = result['questions']
        warnings = question['self_check']['review_warnings']
        self.assertIn({'check': 'reader_depth', 'reason': '独立解题判定推理深度偏基础（depth=1）。'}, warnings)
        self.assertEqual(len(model.calls), 4)
