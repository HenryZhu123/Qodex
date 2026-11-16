"""Scripted semantic decisions test control flow, not real model judgement accuracy."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from exam_assembly_service.app import create_app
from exam_assembly_service.contracts import PaperRequest
from exam_assembly_service.paper import allocate, assemble_paper, convert_paper
from exam_assembly_service.semantic_selection import ModelReviewer, ReviewUnavailable, screened_questions
from exam_assembly_service.semantic_selection import validate_model_decisions
from exam_assembly_agent.similarity import inspect_pair
from test_mixed_paper import item, plan, Repository


class ScriptedReviewer:
    def __init__(self, duplicates=(), unresolved=False, malformed=False):
        self.duplicates = {frozenset(p) for p in duplicates}
        self.unresolved, self.malformed = unresolved, malformed
        self.payloads = []

    async def review(self, pairs):
        self.payloads.append(deepcopy(pairs))
        if self.malformed:
            return []
        return [{**{k: p[k] for k in ('pair_id', 'question_ids', 'content_hashes')},
                 'verdict': 'UNRESOLVED' if self.unresolved else 'DUPLICATE' if frozenset(p['question_ids']) in self.duplicates else 'DISTINCT',
                 'reason': 'TEST_ONLY scripted comparison of task and reasoning, not a real semantic evaluation.'} for p in pairs]


def semantic_plan(entries, **overrides):
    return PaperRequest.model_validate({**plan(entries), 'semantic_review': True, **overrides}).model_dump()


def report(result):
    return json.loads(Path(result['artifacts']['report']).read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_low_lexical_overlap_replaced_and_new_pairs_reviewed(tmp_path):
    entries = [item(i) for i in range(3)]
    repo = Repository(entries)
    converted = [convert_paper(e, await repo.state(e)) for e in entries]
    request = semantic_plan(entries[:2])
    initial = allocate(request['slots'], converted)
    conflict = [initial[i]['question_id'] for i in range(2)]
    reviewer = ScriptedReviewer([conflict])
    result = await assemble_paper(request, repo, tmp_path, semantic_reviewer=reviewer)
    assert result['status'] == 'STRUCTURAL_PASS'
    audit = result['semantic_review']
    assert audit['coverage_complete'] and audit['replacements']
    assert len(reviewer.payloads) == 2
    chosen = {s['record_id'] for s in result['selected_sources']}
    assert not set(conflict) <= chosen
    assert sum(q['score'] for q in report(result)['student_exam']) == 4
    assert result['validation']['semantic_quality_certified'] is False


@pytest.mark.asyncio
async def test_same_topic_distinct_questions_not_removed_and_parts_included(tmp_path):
    entries = [item(10, score=10, part_scores=[2, 2, 2, 4]), item(11)]
    entries[0]['question_json']['question']['reference'] = 'TEST_ONLY shared material'
    reviewer = ScriptedReviewer()
    result = await assemble_paper(semantic_plan(entries), Repository(entries), tmp_path, semantic_reviewer=reviewer)
    assert result['status'] == 'STRUCTURAL_PASS'
    assert not result['semantic_review']['replacements']
    payload = reviewer.payloads[0][0]
    comprehensive = next(payload[k] for k in ('left', 'right') if payload[k]['question_type'] == 'comprehensive')
    assert len(comprehensive['parts']) == 4 and 'TEST_ONLY shared material' in comprehensive['stem']
    assert 'SECRET_' in json.dumps(comprehensive['answer'])
    assert 'SECRET_' not in Path(result['artifacts']['student_exam_html']).read_text(encoding='utf-8')


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['disabled', 'budget', 'unresolved', 'malformed', 'provider'])
async def test_inconclusive_never_exports(tmp_path, mode):
    entries = [item(20), item(21)]
    reviewer = None if mode == 'disabled' else ScriptedReviewer(unresolved=mode == 'unresolved', malformed=mode == 'malformed')
    if mode == 'provider':
        async def fail(pairs):
            raise ReviewUnavailable('SEMANTIC_PROVIDER_FAILED')
        reviewer.review = fail
    request = semantic_plan(entries, semantic_max_calls=0 if mode == 'budget' else 8)
    result = await assemble_paper(request, Repository(entries), tmp_path, semantic_reviewer=reviewer)
    assert result['status'] == 'UNRESOLVED'
    assert not list(tmp_path.rglob('*.html'))
    if mode in ('disabled', 'budget', 'unresolved'):
        assert len(json.loads(Path(result['artifacts']['similarity_decisions_template']).read_text(encoding='utf-8'))) == 1


@pytest.mark.asyncio
async def test_confirmed_conflicts_exhaustion_and_search_bound(tmp_path):
    entries = [item(30), item(31)]
    reviewer = ScriptedReviewer([[e['record_id'] for e in entries]])
    request = semantic_plan(entries)
    result = await assemble_paper(request, Repository(entries), tmp_path/'exhausted', semantic_reviewer=reviewer)
    assert result['status'] == 'NEEDS_QUESTIONS'
    assert result['semantic_review']['status'] == 'NO_CONFLICT_FREE_PAPER_IN_POOL'
    request['similarity_search_limit'] = 1
    bounded = await assemble_paper(request, Repository(entries), tmp_path/'bounded', semantic_reviewer=reviewer)
    assert bounded['status'] == 'UNRESOLVED'
    assert bounded['semantic_review']['status'] == 'SEARCH_LIMIT_REACHED'
    assert not list(tmp_path.rglob('*.html'))


@pytest.mark.asyncio
async def test_human_full_coverage_and_changed_content_invalidates(tmp_path):
    entries = [item(40), item(41)]
    repo = Repository(entries)
    questions = [convert_paper(e, await repo.state(e)) for e in entries]
    sources = {e['record_id']: e for e in entries}
    pair = inspect_pair(*screened_questions(questions, sources))
    decision = {**{k: pair[k] for k in ('pair_id', 'question_ids', 'content_hashes')},
                'source': 'human', 'reviewer': 'TEST_ONLY', 'verdict': 'DISTINCT', 'reason': 'TEST_ONLY explicit decision'}
    request = semantic_plan(entries, similarity_decisions=[decision], semantic_max_calls=0)
    result = await assemble_paper(request, repo, tmp_path/'first')
    assert result['status'] == 'STRUCTURAL_PASS' and result['semantic_review']['model_calls'] == 0
    entries[0]['question_json']['question']['reference'] = 'changed material'
    changed = await assemble_paper(request, repo, tmp_path/'changed')
    assert changed['status'] == 'UNRESOLVED'
    assert changed['semantic_review']['status'] == 'INVALID_OR_STALE_DECISIONS'


@pytest.mark.asyncio
async def test_exact_duplicate_replacement_branches_preserve_unique_slot(tmp_path):
    a, b, c = item(50), item(51), item(52)
    for e in (a, b):
        e['question_json']['question']['question_text'] = 'TEST_ONLY identical original student stem'
    a['question_json']['metadata']['knowledge_points'] = ['required', 'flexible']
    b['question_json']['metadata']['knowledge_points'] = ['flexible']
    c['question_json']['metadata']['knowledge_points'] = ['flexible']
    request = semantic_plan([a, b])
    request['slots'][0]['knowledge_point'] = 'required'
    request['slots'][1]['knowledge_point'] = 'flexible'
    result = await assemble_paper(request, Repository([a, b, c]), tmp_path, semantic_reviewer=ScriptedReviewer())
    assert result['status'] == 'STRUCTURAL_PASS'
    assert result['selected_sources'][0]['record_id'] == a['record_id']
    assert result['selected_sources'][1]['record_id'] == c['record_id']


@pytest.mark.asyncio
async def test_server_limit_and_default_do_not_silently_call_reviewer(tmp_path):
    entries = [item(i) for i in range(60, 64)]
    reviewer = ScriptedReviewer()
    reviewer.max_calls = 1
    result = await assemble_paper(semantic_plan(entries, semantic_max_calls=100), Repository(entries), tmp_path/'limited', semantic_reviewer=reviewer)
    assert result['status'] == 'UNRESOLVED' and len(reviewer.payloads) == 1
    reviewer.payloads.clear()
    default = await assemble_paper(plan(entries), Repository(entries), tmp_path/'default', semantic_reviewer=reviewer)
    assert default['status'] == 'STRUCTURAL_PASS' and not reviewer.payloads


@pytest.mark.asyncio
async def test_api_semantic_dispatch_without_external_calls(tmp_path):
    entries = [item(70), item(71)]
    app = create_app(Repository(entries), tmp_path, database_url='', semantic_reviewer=ScriptedReviewer())
    async with app.router.lifespan_context(app), httpx.AsyncClient(base_url='http://local', transport=httpx.ASGITransport(app=app)) as client:
        assert (await client.get('/health')).json()['semantic_model_enabled'] is True
        response = await client.post('/v1/exam-assembly/assemble', json=semantic_plan(entries))
    assert response.status_code == 200 and response.json()['semantic_review']['coverage_complete']


@pytest.mark.asyncio
async def test_model_adapter_strict_response_and_no_retry(monkeypatch):
    monkeypatch.setenv('EXAM_ASSEMBLY_SEMANTIC_ENABLED', '0')
    with pytest.raises(ReviewUnavailable, match='DISABLED'):
        await ModelReviewer().review([])
    for key, value in dict(ENABLED='1', MODEL='TEST_ONLY', API_KEY='TEST_ONLY', BASE_URL='https://test.invalid/v1').items():
        monkeypatch.setenv('EXAM_ASSEMBLY_SEMANTIC_'+key, value)
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == 'https://test.invalid/v1/chat/completions'
        return httpx.Response(200, json={'choices':[{'finish_reason':'length', 'message':{'content':'{}'}}]})
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(ReviewUnavailable, match='OUTPUT_INCOMPLETE'):
        await ModelReviewer().review([])
    assert len(requests) == 1


@pytest.mark.parametrize('change', [
    {'pair_id':'unknown'}, {'content_hashes':['old','old']}, {'question_ids':['a','a']},
    {'verdict':'PASS'}, {'reason':' '},
])
def test_wrong_pair_hash_or_verdict_is_not_accepted(change):
    pair = dict(pair_id='known', question_ids=['a','b'], content_hashes=['hash-a','hash-b'])
    with pytest.raises(ReviewUnavailable):
        validate_model_decisions([pair], [{**pair, 'verdict':'DISTINCT', 'reason':'TEST_ONLY', **change}])


@pytest.mark.asyncio
async def test_source_change_after_semantic_pass_still_prevents_export(tmp_path):
    entries = [item(80), item(81)]
    result = await assemble_paper(semantic_plan(entries), Repository(entries, stale=True), tmp_path,
                                  semantic_reviewer=ScriptedReviewer())
    assert result['status'] == 'UNRESOLVED'
    assert not list(tmp_path.rglob('*.html'))
