from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

from infinity_context_core.application.context_hydration import (
    _should_preserve_chunk_item_evidence,
    _with_application_evidence_contract,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    score_query_relevance,
)
from infinity_context_core.application.context_source_siblings import (
    _source_session_group,
    _SourceGroupSeed,
    is_direct_source_sibling_obligation_evidence,
    project_source_sibling_obligation_evidence,
    select_source_sibling_groups,
    source_group_admission_rank,
    source_group_seed_turns,
    source_sibling_candidate_rank_key,
    source_sibling_group_limit,
    source_sibling_obligation_evidence_rank,
    source_sibling_obligation_evidence_score,
    source_sibling_rank,
    source_sibling_seed_group_limit,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _keyword_aggregation_chunk_items,
    _prioritize_source_sibling_answer_evidence_seed_chunks,
    _prioritized_source_sibling_seed_groups,
)
from infinity_context_core.application.use_cases.build_context_source_selection import (
    _keyword_source_sibling_chunk_items,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryChunk,
    MemoryChunkKind,
    MemoryScopeId,
    SpaceId,
    ThreadId,
)


def test_document_chunks_with_same_opaque_source_are_siblings() -> None:
    source_id = "archive:case-42:opaque-session-a"
    seed = _chunk("seed", source_id=source_id, sequence=6)
    candidate = _chunk("candidate", source_id=source_id, sequence=0)

    source_groups = source_group_seed_turns((seed,))

    assert tuple(source_groups) == (source_id,)
    rank = source_sibling_rank(candidate, source_groups=source_groups)
    assert rank is not None
    assert rank.group_level_seed
    assert rank.turn_distance == 0
    assert rank.turn_delta == 0


def test_document_chunks_from_unrelated_opaque_sessions_do_not_join() -> None:
    seed = _chunk("seed", source_id="archive:case-42:opaque-session-a", sequence=6)
    unrelated = _chunk(
        "unrelated",
        source_id="archive:case-42:opaque-session-b",
        sequence=0,
    )

    source_groups = source_group_seed_turns((seed,))

    assert source_sibling_rank(unrelated, source_groups=source_groups) is None


def test_non_document_chunk_does_not_seed_or_join_an_opaque_source_group() -> None:
    opaque_source_id = "archive:case-42:opaque-session-a"
    document_seed = _chunk("document-seed", source_id=opaque_source_id, sequence=2)
    episode_seed = replace(
        _chunk("episode-seed", source_id=opaque_source_id, sequence=2),
        document_id=None,
        episode_id="episode",
    )
    episode_candidate = replace(
        _chunk("episode-candidate", source_id=opaque_source_id, sequence=0),
        document_id=None,
        episode_id="episode",
    )

    assert source_group_seed_turns((episode_seed,)) == {}
    assert (
        source_sibling_rank(
            episode_candidate,
            source_groups=source_group_seed_turns((document_seed,)),
        )
        is None
    )


def test_legacy_session_tail_and_suffix_grouping_is_preserved() -> None:
    session_group = "archive:case-42:session_7"

    assert _source_session_group(session_group) == session_group
    assert _source_session_group(f"{session_group}:observation") == session_group
    assert (
        _source_session_group(
            "archive:case-42:opaque-session-a:observation",
            allow_opaque_document_source=True,
        )
        is None
    )
    for suffix in ("events", "observation", "summary"):
        assert (
            _source_session_group(
                f"archive:case-42:opaque-session-a:{suffix}",
                allow_opaque_document_source=True,
            )
            is None
        )


def test_malformed_opaque_source_ids_are_not_groups() -> None:
    for source_id in (
        "",
        "archive",
        "archive:case-42",
        "archive::opaque-session-a",
        ":case-42:opaque-session-a",
        "archive:case-42:",
        "archive:case-42:observation",
    ):
        assert (
            _source_session_group(
                source_id,
                allow_opaque_document_source=True,
            )
            is None
        )


def test_opaque_document_sibling_rank_and_tie_break_are_deterministic() -> None:
    source_id = "archive:case-42:opaque-session-a"
    seed = _chunk("seed", source_id=source_id, sequence=9)
    first = _chunk("candidate-b", source_id=source_id, sequence=4)
    second = _chunk("candidate-a", source_id=source_id, sequence=3)
    source_groups = source_group_seed_turns((seed,))
    rank = source_sibling_rank(first, source_groups=source_groups)

    assert rank is not None
    assert rank == source_sibling_rank(first, source_groups=source_groups)
    assert rank == source_sibling_rank(second, source_groups=source_groups)

    relevance = QueryRelevance(
        score_boost=0.0,
        query_term_count=1,
        unique_term_hits=0,
        capped_frequency_hits=0,
        hit_ratio=0.0,
        distinctive_term_count=0,
        distinctive_term_hits=0,
    )

    def rank_key(chunk: MemoryChunk) -> tuple[float | int | str, ...]:
        return source_sibling_candidate_rank_key(
            precise_turn=False,
            dialogue_visual_reference=False,
            visual_continuation=False,
            observation_companion=False,
            marker_coverage=0,
            relevance=relevance,
            score=rank.score,
            rank=rank,
            chunk=chunk,
        )

    assert [chunk.id for chunk in sorted((first, second), key=rank_key)] == [
        "candidate-a",
        "candidate-b",
    ]


def test_query_relevant_opaque_group_wins_bounded_admission_stably() -> None:
    query = "Which repaired equipment is ready for me to collect?"
    relevant_group = "archive:account:opaque-repair-session"
    source_groups = {
        f"archive:account:opaque-session-{index:02d}": _SourceGroupSeed(
            priority=index,
            primary_turn=0,
            turns=frozenset(),
            group_level=True,
        )
        for index in range(24)
    }
    source_groups[relevant_group] = _SourceGroupSeed(
        priority=24,
        primary_turn=0,
        turns=frozenset(),
        group_level=True,
    )
    irrelevant = score_query_relevance(
        query=query,
        text="General suggestions for arranging a reading list.",
    )
    relevant = score_query_relevance(
        query=query,
        text="My repaired camera equipment is ready for collection.",
    )
    rank_by_group = {
        group: source_group_admission_rank(
            group=group,
            original_relevance=relevant if group == relevant_group else irrelevant,
            relevance=relevant if group == relevant_group else irrelevant,
            answer_evidence=False,
            related_anchor=False,
        )
        for group in source_groups
    }
    limit = source_sibling_group_limit()

    selected = select_source_sibling_groups(
        source_groups=source_groups,
        rank_by_group=rank_by_group,
        limit=limit,
    )
    permuted = select_source_sibling_groups(
        source_groups=dict(reversed(tuple(source_groups.items()))),
        rank_by_group=rank_by_group,
        limit=limit,
    )

    assert len(selected) == limit == 20
    assert tuple(selected) == tuple(permuted)
    assert next(iter(selected)) == relevant_group
    assert selected[relevant_group].priority == 0
    assert "archive:account:opaque-session-23" not in selected


def test_seed_admission_keeps_late_relevant_group_across_large_permutations() -> None:
    query = "Which calibrated instruments do I still need to collect?"
    query_plan = build_query_expansion_plan(query)
    relevant_group = "archive:account:opaque-session-relevant"
    irrelevant_chunks = tuple(
        _chunk(
            f"neutral-{index:02d}",
            source_id=f"archive:account:opaque-session-{index:02d}",
            sequence=index,
            text="A neutral archival entry about a neighborhood garden.",
        )
        for index in range(40)
    )
    relevant = _chunk(
        "relevant",
        source_id=relevant_group,
        sequence=40,
        text="I still need to collect my calibrated instrument from the service counter.",
    )
    forward = (*irrelevant_chunks, relevant)
    orderings = (
        forward,
        tuple(reversed(forward)),
        (*forward[::3], *forward[1::3], *forward[2::3]),
    )
    admitted_runs: list[tuple[str, ...]] = []
    selected_runs: list[tuple[str, ...]] = []

    for seed_chunks in orderings:
        relevance_cache: dict[str, tuple[str, str, QueryRelevance]] = {}
        prioritized = _prioritize_source_sibling_answer_evidence_seed_chunks(
            seed_chunks=seed_chunks,
            query_plan=query_plan,
            query_relevance_cache=relevance_cache,
        )
        source_groups = source_group_seed_turns(prioritized)
        selected = _prioritized_source_sibling_seed_groups(
            source_groups=source_groups,
            seed_chunks=prioritized,
            query_plan=query_plan,
            query_relevance_cache=relevance_cache,
            limit=source_sibling_group_limit(),
        )
        admitted_runs.append(tuple(source_groups))
        selected_runs.append(tuple(selected))

        assert len(source_groups) == source_sibling_seed_group_limit() == 32
        assert len(selected) == source_sibling_group_limit() == 20
        assert relevant_group in source_groups
        assert next(iter(selected)) == relevant_group

    assert admitted_runs[0] == admitted_runs[1] == admitted_runs[2]
    assert selected_runs[0] == selected_runs[1] == selected_runs[2]


def test_seed_admission_is_bounded_and_deterministic_for_semantic_ties() -> None:
    query_plan = build_query_expansion_plan("Which calibrated instruments are pending?")
    chunks = tuple(
        _chunk(
            f"tie-{index:02d}",
            source_id=f"archive:account:opaque-tie-{index:02d}",
            sequence=index,
            text="A neutral archival entry about a neighborhood garden.",
        )
        for index in range(48)
    )
    expected = tuple(sorted(str(chunk.source_external_id) for chunk in chunks))[:32]
    runs: list[tuple[str, ...]] = []

    for seed_chunks in (chunks, tuple(reversed(chunks)), (*chunks[::2], *chunks[1::2])):
        prioritized = _prioritize_source_sibling_answer_evidence_seed_chunks(
            seed_chunks=seed_chunks,
            query_plan=query_plan,
            query_relevance_cache={},
        )
        groups = tuple(source_group_seed_turns(prioritized))
        runs.append(groups)
        assert len(prioritized) == source_sibling_seed_group_limit()
        assert groups == expected

    assert runs[0] == runs[1] == runs[2]


def test_obligation_evidence_beats_generic_advice_and_unrelated_work() -> None:
    query = "Which equipment do I still need to collect or return?"
    direct_text = "I still need to collect my repaired camera equipment from the service counter."
    advice_text = (
        "Here are some tips: create a list and set reminders so you remember your errands."
    )
    unrelated_text = "I still need to water the garden before sunset."
    related_topic_wrong_action_text = "I still need to wash my favorite jacket before the weekend."
    unrelated_same_action_texts = (
        "I still need to collect seashells along the shore.",
        "I still need to collect the laundry from the cleaner.",
    )

    direct_rank = source_sibling_obligation_evidence_rank(
        query_text=query,
        relevance=score_query_relevance(query=query, text=direct_text),
        text=direct_text,
    )
    advice_rank = source_sibling_obligation_evidence_rank(
        query_text=query,
        relevance=score_query_relevance(query=query, text=advice_text),
        text=advice_text,
    )
    unrelated_rank = source_sibling_obligation_evidence_rank(
        query_text=query,
        relevance=score_query_relevance(query=query, text=unrelated_text),
        text=unrelated_text,
    )
    related_topic_wrong_action_rank = source_sibling_obligation_evidence_rank(
        query_text=query,
        relevance=score_query_relevance(
            query=query,
            text=related_topic_wrong_action_text,
        ),
        text=related_topic_wrong_action_text,
    )

    assert direct_rank == 0
    assert advice_rank == 2
    assert unrelated_rank == 1
    assert related_topic_wrong_action_rank == 1
    for text in unrelated_same_action_texts:
        rank = source_sibling_obligation_evidence_rank(
            query_text=query,
            relevance=score_query_relevance(query=query, text=text),
            text=text,
        )
        assert rank == 3
        assert source_sibling_obligation_evidence_score(score=0.99, rank=rank) < 0.99
    assert source_sibling_obligation_evidence_score(score=0.95, rank=direct_rank) == 0.99


def test_followup_bridge_does_not_contract_unrelated_direct_obligation() -> None:
    query = "What do I need to do before launch?"
    source_id = "archive:account:opaque-launch-planning"
    seed = _chunk(
        "launch-seed",
        source_id=source_id,
        sequence=0,
        text="We discussed the launch preparations.",
    )
    noise = _chunk(
        "unrelated-obligation",
        source_id=source_id,
        sequence=1,
        text="I need to call the dentist next week.",
    )
    query_plan = build_query_expansion_plan(query)

    items, _ = asyncio.run(
        _keyword_source_sibling_chunk_items(
            uow_factory=lambda: _SourceSiblingUnitOfWork((noise,)),
            query=BuildContextQuery(
                space_id=SpaceId("space"),
                memory_scope_ids=(MemoryScopeId("scope"),),
                thread_id=ThreadId("thread"),
                query=query,
                max_chunks=10,
            ),
            query_plan=query_plan,
            memory_scope_ids=("scope",),
            seed_chunks=(seed,),
            query_relevance_cache={},
        )
    )

    item = next(item for item in items if item.item_id == str(noise.id))
    assert item.diagnostics["provenance"]["query_expansion_reason"] == "followup_task_bridge"
    signals = item.diagnostics["score_signals"]
    assert signals["source_sibling_obligation_evidence_rank"] != 0
    assert signals["source_sibling_obligation_projection_applied"] == 0
    assert "application_evidence_contract_tier" not in signals

    hydrated = _with_application_evidence_contract(item, query_text=query)
    assert "application_evidence_contract_tier" not in hydrated.diagnostics["score_signals"]


def test_source_selection_projects_direct_clause_beside_matching_report() -> None:
    query = "Which access request do I need to file?"
    source_id = "archive:account:opaque-access-planning"
    seed = _chunk(
        "access-seed",
        source_id=source_id,
        sequence=0,
        text="We discussed the access request workflow.",
    )
    direct_clause = "I need to file the access request"
    candidate = _chunk(
        "mixed-attribution",
        source_id=source_id,
        sequence=1,
        text=(f'The coordinator reported: "I need to file the access request." {direct_clause}.'),
    )

    items, _ = asyncio.run(
        _keyword_source_sibling_chunk_items(
            uow_factory=lambda: _SourceSiblingUnitOfWork((candidate,)),
            query=BuildContextQuery(
                space_id=SpaceId("space"),
                memory_scope_ids=(MemoryScopeId("scope"),),
                thread_id=ThreadId("thread"),
                query=query,
                max_chunks=10,
            ),
            query_plan=build_query_expansion_plan(query),
            memory_scope_ids=("scope",),
            seed_chunks=(seed,),
            query_relevance_cache={},
        )
    )

    item = next(item for item in items if item.item_id == str(candidate.id))
    assert item.text == direct_clause
    assert item.source_refs[0].chunk_id == str(candidate.id)
    signals = item.diagnostics["score_signals"]
    assert signals["source_sibling_obligation_evidence_rank"] == 0
    assert signals["source_sibling_obligation_projection_applied"] == 1
    assert signals["application_evidence_contract_tier"] == 1


def test_direct_obligation_contract_is_generic_across_actions_and_subjects() -> None:
    cases = (
        (
            "Which readiness checklist do I need to confirm?",
            "I need to confirm the readiness checklist with operations.",
        ),
        (
            "What does Morgan need to prepare before the briefing?",
            "Morgan needs to prepare the briefing notes.",
        ),
        (
            "What must Taylor submit to Priya?",
            "Taylor must submit the signed report to Priya.",
        ),
        (
            "Which repaired devices do I need to return?",
            "I need to return the repaired devices to the service desk.",
        ),
        (
            "What package does Morgan need to pick up?",
            "Morgan needs to pick up the package from reception.",
        ),
        (
            "Which supplies does Taylor need to drop off?",
            "Taylor needs to drop the supplies off at the workshop.",
        ),
    )

    for query, text in cases:
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            semantic_query_text=(
                "action item task todo owner responsible assignee commitment call decision"
            ),
            relevance=score_query_relevance(query=query, text=text),
            text=text,
        )
        assert projection.rank == 0
        assert projection.applied
        assert projection.text == text.removesuffix(".")
        assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)


def test_direct_obligation_contract_requires_clause_scope_action_and_subject() -> None:
    cases = (
        (
            "What do I need to do before launch?",
            "The launch is planned for Friday. I need to call the dentist next week.",
        ),
        (
            "What does Morgan need to prepare before the briefing?",
            "Taylor needs to prepare the briefing notes.",
        ),
        (
            "Which launch checklist does Morgan need to approve?",
            "Morgan needs to archive the launch checklist.",
        ),
    )

    for query, text in cases:
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            semantic_query_text=(
                "action item task todo owner responsible assignee commitment call decision"
            ),
            relevance=score_query_relevance(query=query, text=text),
            text=text,
        )
        assert projection.rank != 0
        assert not projection.applied
        assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=text)


def test_negated_obligations_cannot_establish_direct_promotion() -> None:
    query = "Which audit form do I need to sign?"
    negated_texts = (
        "I must not sign the audit form.",
        "I must never sign the audit form.",
        "I need not sign the audit form.",
        "I do not need to sign the audit form.",
        "I am not required to sign the audit form.",
    )

    for text in negated_texts:
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            relevance=score_query_relevance(query=query, text=text),
            text=text,
        )
        assert projection.rank != 0
        assert not projection.applied
        assert not is_direct_source_sibling_obligation_evidence(
            query_text=query,
            text=text,
        )

    stale_rank_item = ContextItem(
        item_id="negated-stale-rank",
        item_type="chunk",
        text=negated_texts[0],
        score=0.99,
        source_refs=(),
        diagnostics={
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "source_sibling_obligation_evidence_rank": 0,
            }
        },
    )
    hydrated = _with_application_evidence_contract(stale_rank_item, query_text=query)
    assert "application_evidence_contract_tier" not in hydrated.diagnostics["score_signals"]


def test_public_obligation_entry_rejects_clause_local_negation_and_reported_speech() -> None:
    query = "Which access request do I need to file?"
    unsafe_candidates = (
        ("I should not file the access request.", "should-not contradiction"),
        ("I must not file the access request.", "must-not contradiction"),
        ("I do not need to file the access request.", "does-not-need contradiction"),
        (
            "The coordinator said, 'I must file the access request.'",
            "third-party reported first-person obligation",
        ),
        (
            "The coordinator reported that they must file the access request.",
            "third-party reported pronoun obligation",
        ),
    )

    for text, case in unsafe_candidates:
        relevance = score_query_relevance(query=query, text=text)
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            relevance=relevance,
            text=text,
        )

        assert not is_direct_source_sibling_obligation_evidence(
            query_text=query,
            text=text,
        ), case
        assert (
            source_sibling_obligation_evidence_rank(
                query_text=query,
                relevance=relevance,
                text=text,
            )
            != 0
        ), case
        assert not projection.applied, case

    safe_candidates = (
        "I said I need to file the access request.",
        "I need to file the access request. However, I should not file it.",
        "I need to file the access request, but I must not file it.",
        "The access request does not need to be filed. I need to file the access request.",
        ("The coordinator said they must water the plants. I need to file the access request."),
    )
    for text in safe_candidates:
        relevance = score_query_relevance(query=query, text=text)
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            relevance=relevance,
            text=text,
        )
        assert is_direct_source_sibling_obligation_evidence(query_text=query, text=text)
        assert (
            source_sibling_obligation_evidence_rank(
                query_text=query,
                relevance=relevance,
                text=text,
            )
            == 0
        )
        assert projection.applied


def test_obligation_subject_alignment_is_clause_local_and_possessor_aware() -> None:
    attributed_query = "What does Avery need to submit for the audit?"
    attributed_text = "Avery reported that Rowan needs to submit the audit worksheet."

    assert not is_direct_source_sibling_obligation_evidence(
        query_text=attributed_query,
        text=attributed_text,
    )
    projection = project_source_sibling_obligation_evidence(
        query_text=attributed_query,
        relevance=score_query_relevance(query=attributed_query, text=attributed_text),
        text=attributed_text,
    )
    assert projection.rank != 0
    assert not projection.applied

    owner_query = "What does Rowan need to submit for the audit?"
    owner_text = "Rowan's pending obligation is to submit the audit worksheet."
    assert is_direct_source_sibling_obligation_evidence(
        query_text=owner_query,
        text=owner_text,
    )


def test_actionless_obligation_query_cannot_promote_shared_scope_alone() -> None:
    query = "What do I need to do for the exhibition?"
    text = "I need to polish the exhibition placard before opening."

    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=text),
        text=text,
    )

    assert projection.rank != 0
    assert not projection.applied
    assert not is_direct_source_sibling_obligation_evidence(query_text=query, text=text)


def test_compound_action_contract_uses_bounded_surrounding_semantics() -> None:
    query = "Which release materials do I need to review or publish?"
    semantic_query = "deployment dependency memo migration notice rollout bulletin"
    direct_texts = (
        "The release materials are staged. I still need to review the dependency memo.",
        "The rollout includes a migration notice, and I still need to publish it.",
    )

    for text in direct_texts:
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            semantic_query_text=semantic_query,
            relevance=score_query_relevance(query=semantic_query, text=text),
            text=text,
        )

        assert projection.rank == 0
        assert projection.applied
        assert projection.text.startswith("I still need to")

    unrelated_texts = (
        "The release materials are staged. I still need to schedule a dental cleaning.",
        "I still need to review the gym membership.",
        "The rollout includes a migration notice. I still need to publish it.",
    )
    for text in unrelated_texts:
        projection = project_source_sibling_obligation_evidence(
            query_text=query,
            semantic_query_text=semantic_query,
            relevance=score_query_relevance(query=semantic_query, text=text),
            text=text,
        )

        assert projection.rank != 0
        assert not projection.applied


def test_obligation_rank_preserves_deterministic_candidate_ties() -> None:
    query = "Which equipment do I still need to collect?"
    text = "I still need to collect repaired equipment from the service counter."
    relevance = score_query_relevance(query=query, text=text)
    rank = source_sibling_rank(
        _chunk("seed", source_id="archive:account:opaque-session", sequence=0),
        source_groups=source_group_seed_turns(
            (_chunk("group", source_id="archive:account:opaque-session", sequence=0),)
        ),
    )
    assert rank is not None
    chunks = (
        _chunk("candidate-z", source_id="archive:account:opaque-session", sequence=2),
        _chunk("candidate-a", source_id="archive:account:opaque-session", sequence=2),
    )

    def key(chunk: MemoryChunk) -> tuple[float | int | str, ...]:
        return source_sibling_candidate_rank_key(
            precise_turn=False,
            dialogue_visual_reference=False,
            visual_continuation=False,
            observation_companion=False,
            obligation_evidence_rank=source_sibling_obligation_evidence_rank(
                query_text=query,
                relevance=relevance,
                text=text,
            ),
            answer_evidence=True,
            marker_coverage=0,
            relevance=relevance,
            score=rank.score,
            rank=rank,
            chunk=chunk,
        )

    assert [chunk.id for chunk in sorted(reversed(chunks), key=key)] == [
        "candidate-a",
        "candidate-z",
    ]


def test_opaque_document_aggregation_keeps_obligation_over_generic_advice() -> None:
    query = "How many repaired devices do I still need to collect or return?"
    direct = _chunk(
        "direct-obligation",
        source_id="archive:account:opaque-repair-session",
        sequence=2,
        text="I still need to collect my repaired camera device from the service counter.",
    )
    advice = _chunk(
        "generic-advice",
        source_id="archive:account:opaque-repair-session",
        sequence=3,
        text=(
            "Here are some tips: create a list and set reminders so you remember "
            "your pickups and returns."
        ),
    )
    same_action_noise = (
        _chunk(
            "same-action-shore",
            source_id="archive:account:opaque-outdoor-session",
            sequence=4,
            text="I still need to collect seashells along the shore.",
        ),
        _chunk(
            "same-action-household",
            source_id="archive:account:opaque-household-session",
            sequence=5,
            text="I still need to collect the laundry from the cleaner.",
        ),
    )

    items, diagnostics = _keyword_aggregation_chunk_items(
        query=BuildContextQuery(
            space_id=SpaceId("space"),
            memory_scope_ids=(MemoryScopeId("scope"),),
            query=query,
            max_chunks=10,
        ),
        seed_chunks=(advice, *same_action_noise, direct),
    )

    assert items[0].item_id == "direct-obligation"
    assert diagnostics["keyword_aggregation_chunks_skipped"] >= 1
    assert items[0].diagnostics["score_signals"]["source_sibling_obligation_evidence_rank"] == 0
    for item in items[1:]:
        assert item.diagnostics["score_signals"]["source_sibling_obligation_evidence_rank"] == 3
        assert item.score < 0.99


def test_mixed_advice_projects_later_obligation_with_canonical_provenance() -> None:
    query = "How many calibrated devices do I still need to collect or return?"
    long_advice_prefix = " ".join(
        f"You can review checklist section {index}." for index in range(72)
    )
    matching_report = (
        'The coordinator reported: "I still need to collect my calibrated device '
        'from the service counter."'
    )
    canonical_text = (
        f"{long_advice_prefix} {matching_report} "
        "I still need to collect my calibrated device from the service counter. "
        "You should review the checklist each week."
    )
    direct_clause = "I still need to collect my calibrated device from the service counter"
    relevance = score_query_relevance(query=query, text=canonical_text)
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=relevance,
        text=canonical_text,
    )

    assert projection.rank == 0
    assert projection.applied
    assert projection.text == direct_clause
    assert projection.text == " ".join(canonical_text[start:end] for start, end in projection.spans)
    assert "checklist section" not in projection.text
    assert "You should" not in projection.text

    mixed = _chunk(
        "mixed-obligation",
        source_id="archive:account:opaque-mixed-session",
        sequence=4,
        text=canonical_text,
    )
    items, _ = _keyword_aggregation_chunk_items(
        query=BuildContextQuery(
            space_id=SpaceId("space"),
            memory_scope_ids=(MemoryScopeId("scope"),),
            query=query,
            max_chunks=10,
        ),
        seed_chunks=(mixed,),
    )

    assert len(items) == 1
    assert items[0].text == direct_clause
    assert mixed.text == canonical_text
    assert items[0].source_refs[0].chunk_id == str(mixed.id)
    provenance = items[0].diagnostics["provenance"]
    assert provenance["source_sibling_obligation_projection_applied"] is True
    assert provenance["source_sibling_obligation_projection_spans"] == [
        list(span) for span in projection.spans
    ]
    assert provenance["source_sibling_obligation_projection_canonical_text_length"] == len(
        canonical_text
    )


def test_ordinary_advice_query_preserves_useful_non_obligation_evidence() -> None:
    query = "What tips help organize routine errands?"
    advice = "Create a short checklist and review it before leaving home."
    projection = project_source_sibling_obligation_evidence(
        query_text=query,
        relevance=score_query_relevance(query=query, text=advice),
        text=advice,
    )

    assert projection.rank == 1
    assert not projection.applied
    assert projection.text == advice

    embedded_request = "Do you have tips for items I need to pick up or return?"
    embedded_projection = project_source_sibling_obligation_evidence(
        query_text="Which household items do I still need to pick up or return?",
        relevance=score_query_relevance(
            query="Which household items do I still need to pick up or return?",
            text=embedded_request,
        ),
        text=embedded_request,
    )
    assert embedded_projection.rank == 2
    assert not embedded_projection.applied
    assert embedded_projection.text == embedded_request

    projected_item = ContextItem(
        item_id="focused-evidence",
        item_type="chunk",
        text=advice,
        score=0.8,
        source_refs=(),
        diagnostics={
            "retrieval_source": "keyword_source_sibling_chunks",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
        },
    )
    assert _should_preserve_chunk_item_evidence(projected_item)
    assert not _should_preserve_chunk_item_evidence(
        replace(
            projected_item,
            diagnostics={
                "retrieval_source": "keyword_chunks",
                "retrieval_sources": ["keyword_chunks"],
            },
        )
    )


def _chunk(
    chunk_id: str,
    *,
    source_id: str,
    sequence: int,
    text: str | None = None,
) -> MemoryChunk:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    text = text or f"Evidence from sequence {sequence}."
    return MemoryChunk(
        id=chunk_id,
        space_id="space",
        memory_scope_id="scope",
        thread_id="thread",
        document_id="document",
        episode_id=None,
        source_type="archive_session",
        source_external_id=source_id,
        source_hash=f"hash-{chunk_id}",
        kind=MemoryChunkKind.DOCUMENT_SECTION,
        text=text,
        normalized_text=text.casefold(),
        status=LifecycleStatus.ACTIVE,
        sequence=sequence,
        char_start=0,
        char_end=len(text),
        token_estimate=8,
        created_at=now,
        updated_at=now,
        metadata={},
    )


class _SourceSiblingChunkRepository:
    def __init__(self, chunks: tuple[MemoryChunk, ...]) -> None:
        self._chunks = chunks

    async def list_by_source_external_id_groups(self, **_kwargs: object) -> tuple[MemoryChunk, ...]:
        return self._chunks


class _SourceSiblingUnitOfWork:
    def __init__(self, chunks: tuple[MemoryChunk, ...]) -> None:
        self.chunks = _SourceSiblingChunkRepository(chunks)

    async def __aenter__(self) -> _SourceSiblingUnitOfWork:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None
