from datetime import UTC, datetime

from infinity_context_core.application.context_collectors import (
    _canonical_fact_candidate_limit,
    _rank_facts_for_query,
)
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_rank_facts_for_query_prefers_specific_term_coverage_over_input_order() -> None:
    decoy = _fact(
        "fact_decoy",
        "QUALITY_DECOY_WRONG_MODEL: local canary uses GPT-3.5 legacy fallback.",
    )
    current = _fact(
        "fact_current",
        "QUALITY_FACT_MODEL_CURRENT: local interview canary uses GPT-5.4 mini.",
    )

    ranked = _rank_facts_for_query(
        (decoy, current),
        query_text="GPT-5.4 mini local interview canary current model",
        limit=1,
    )

    assert ranked == (current,)


def test_canonical_fact_candidate_limit_overfetches_before_relevance_ranking() -> None:
    assert _canonical_fact_candidate_limit(0) == 0
    assert _canonical_fact_candidate_limit(1) == 9
    assert _canonical_fact_candidate_limit(30) == 100


def test_rank_facts_for_query_uses_normalized_lexical_variants() -> None:
    decoy = _fact(
        "fact_decoy",
        "Проект Apollo обсуждал релиз без участия Алекса.",
    )
    current = _fact(
        "fact_current",
        "Встреча с Алексом по проекту Атлас завершилась решением сохранить запись.",
    )

    ranked = _rank_facts_for_query(
        (decoy, current),
        query_text="встречу Алекс проектом Атласом",
        limit=1,
    )

    assert ranked == (current,)


def test_rank_facts_for_query_prefers_phrase_signal_over_loose_decoy_terms() -> None:
    target = _fact(
        "fact_graphiti",
        "LONGMEM_DECISION_GRAPHITI: Graphiti remains the temporal fact engine.",
    )
    decoy = _fact(
        "fact_obsidian",
        "LONGMEM_DECOY_OBSIDIAN: Obsidian 3D graph is the primary runtime engine.",
    )

    ranked = _rank_facts_for_query(
        (decoy, target),
        query_text="primary runtime temporal fact engine Graphiti Obsidian 3D graph",
        limit=1,
    )

    assert ranked == (target,)


def _fact(fact_id: str, text: str) -> MemoryFact:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        text=text,
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id=f"{fact_id}_source"),),
        now=now,
    )
