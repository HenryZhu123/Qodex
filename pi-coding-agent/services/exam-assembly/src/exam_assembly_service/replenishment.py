"""Build a jointly feasible supplement proposal; never create questions or PASS evidence."""
from collections import Counter

from exam_assembly_agent.assembly import stem_key


def propose_replenishment(request, candidates, *, max_nodes=50000, forbidden_pairs=None):
    topics = request["topic_counts"].copy()
    levels = request["difficulty_counts"].copy()
    selected, best = [], []
    used_stems, used_ids = set(), set()
    nodes, exhausted = 0, False
    forbidden_pairs = forbidden_pairs or set()
    upper_bound = min(request["question_count"], len({stem_key(q["stem"]) for q in candidates}),
                      len({q["question_id"] for q in candidates}))

    def search(start):
        nonlocal best, nodes, exhausted
        if len(selected) > len(best):
            best = selected.copy()
        if len(best) == upper_bound or len(selected) + len(candidates) - start <= len(best):
            return
        for index in range(start, len(candidates)):
            if nodes >= max_nodes:
                exhausted = True
                return
            nodes += 1
            q = candidates[index]
            level, key, qid = q["difficulty"], stem_key(q["stem"]), q["question_id"]
            if levels.get(level, 0) <= 0 or key in used_stems or qid in used_ids:
                continue
            if any(frozenset((qid, used)) in forbidden_pairs for used in used_ids):
                continue
            for topic in q.get("eligible_topics", [q["topic"]]):
                if topics.get(topic, 0) <= 0:
                    continue
                topics[topic] -= 1
                levels[level] -= 1
                used_stems.add(key)
                used_ids.add(qid)
                selected.append({**q, "topic": topic})
                search(index + 1)
                selected.pop()
                used_stems.remove(key)
                used_ids.remove(qid)
                topics[topic] += 1
                levels[level] += 1
                if exhausted or len(best) == upper_bound:
                    return

    search(0)
    kept_topics = Counter(q["topic"] for q in best)
    kept_levels = Counter(q["difficulty"] for q in best)
    missing_topics = {key: count - kept_topics[key] for key, count in request["topic_counts"].items()}
    missing_levels = {key: count - kept_levels[key] for key, count in request["difficulty_counts"].items()}
    deficits = []
    # User supplied marginal quotas, not exact cells. This is one explicit feasible
    # pairing of the residual margins, not a claim that these cells are uniquely required.
    for topic, count in missing_topics.items():
        for level in missing_levels:
            fill = min(count, missing_levels[level])
            if fill:
                deficits.append(dict(subject=request["subject"], question_type=request["question_type"],
                                     knowledge_point=topic, difficulty=level,
                                     score_per_question=request["score_per_question"], missing_count=fill))
                count -= fill
                missing_levels[level] -= fill
    return dict(schema_version="1.0", request_id=request["request_id"],
                plan_status="PROPOSED_NOT_EXECUTED", scope="CURRENT_VERIFIED_CANDIDATE_POOL",
                suggested_additional_count=request["question_count"] - len(best),
                minimum_count_proven=not exhausted or len(best) == upper_bound,
                search=dict(nodes=nodes, max_nodes=max_nodes, budget_exhausted=exhausted),
                pairing_basis="ONE_FEASIBLE_COMPLETION_OF_MARGINAL_QUOTAS",
                deficits=deficits,
                keep_assignments=[dict(record_id=q["question_id"], source_version_id=q["version"],
                                       knowledge_point=q["topic"], difficulty=q["difficulty"],
                                       question_type=q["question_type"], score=q["score"]) for q in best],
                avoid_stems=[q["stem"] for q in best],
                requirements=dict(review_status="PASS", ingestion_status="STORED", answer_required=True,
                                  review_must_match_current_version=True, distinct_stems=True,
                                  new_unique_record_ids=True,
                                  avoid_confirmed_record_pairs=[sorted(pair) for pair in sorted(forbidden_pairs, key=lambda p: sorted(p))],
                                  rerun_similarity_screen=True),
                next_action="SUPPLY_ACCEPTED_BANK_QUESTIONS_THEN_REASSEMBLE",
                note="仅为补题建议，不调用生成或审校；补题须独立通过审校并入库，之后重新查询和验证整卷。")
