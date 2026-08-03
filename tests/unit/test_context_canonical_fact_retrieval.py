from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from infinity_context_core.application.context_building_legacy_candidate_adapter import (
    _fused_ranked_keys,
)
from infinity_context_core.application.context_canonical_fact_retrieval import (
    _fact_match_is_preferred,
    canonical_fact_candidate_limit,
    canonical_fact_match,
    canonical_fact_rerank_pool_limit,
    retrieve_plan_aware_active_facts,
)
from infinity_context_core.application.context_collectors import CanonicalContextCollector
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.context_ranking import (
    _best_query_relevance_for_rerank,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _fact_context_item,
)
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)


def test_canonical_collector_finds_plan_derived_fact_beyond_large_original_distractor_set() -> None:
    distractors = tuple(
        _fact(f"distractor_{index}", f"Unrelated generic memory number {index}.")
        for index in range(125)
    )
    target = _fact(
        "target",
        "I feel fulfilled helping injured animals through rescue and veterinary care.",
    )
    facts = _BatchFacts(
        {
            "What career would suit me?": distractors,
            "animal rescue veterinary care career": (target,),
        }
    )
    collector = CanonicalContextCollector(
        uow_factory=_UowFactory(_Uow(facts=facts)),
    )
    plan = QueryExpansionPlan(
        original_query="What career would suit me?",
        expansions=(
            QueryExpansion(
                query="animal rescue veterinary care career",
                reason="animal_career_inference_bridge",
            ),
        ),
    )

    result = asyncio.run(
        collector.collect(
            query=BuildContextQuery(
                space_id=SpaceId("space_test"),
                memory_scope_ids=(MemoryScopeId("scope_test"),),
                query=plan.original_query,
                max_facts=2,
                max_chunks=0,
            ),
            memory_scope_ids=("scope_test",),
            keyword_query_plan=plan,
        )
    )

    assert facts.call_count == 1
    assert len(distractors) > 100
    assert [str(fact.id) for fact in result.facts] == ["target"]
    assert result.fact_matches[0].query == "animal rescue veterinary care career"
    assert result.fact_matches[0].reason == "animal_career_inference_bridge"


def test_plan_aware_fact_retrieval_falls_back_to_scalar_repository_calls() -> None:
    target = _fact(
        "target",
        "I feel fulfilled helping injured animals through rescue and veterinary care.",
    )
    repository = _ScalarFacts(
        {
            "What career would suit me?": (),
            "animal rescue veterinary care career": (target,),
        }
    )
    retrieval_queries = (
        QueryExpansion(query="What career would suit me?", reason="original_query"),
        QueryExpansion(
            query="animal rescue veterinary care career",
            reason="animal_career_inference_bridge",
        ),
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=retrieval_queries,
            total_limit=2,
        )
    )

    assert repository.queries == [query.query for query in retrieval_queries]
    assert result.batch_api_used is False
    assert [str(match.fact.id) for match in result.matches] == ["target"]


def test_fact_projection_retains_winning_query_reason_and_relevance() -> None:
    target = _fact(
        "target",
        "I feel fulfilled helping injured animals through rescue and veterinary care.",
    )
    repository = _ScalarFacts({"animal rescue veterinary care career": (target,)})
    retrieval_query = QueryExpansion(
        query="animal rescue veterinary care career",
        reason="animal_career_inference_bridge",
    )
    retrieval = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(retrieval_query,),
            total_limit=2,
        )
    )
    match = retrieval.matches[0]

    item = _fact_context_item(
        target,
        now=datetime(2026, 7, 30, tzinfo=UTC),
        query_text=match.query,
        query_expansion_reason=match.reason,
        relevance=match.relevance,
    )

    diagnostics = dict(item.diagnostics or {})
    score_signals = dict(diagnostics["score_signals"])
    assert diagnostics["query_expansion_reason"] == "animal_career_inference_bridge"
    assert diagnostics["query_expansion_query"] == "animal rescue veterinary care career"
    assert score_signals["query_expansion_reason"] == "animal_career_inference_bridge"
    assert score_signals["distinctive_term_hits"] >= 3
    rerank_query, rerank_reason, rerank_relevance = _best_query_relevance_for_rerank(
        QueryExpansionPlan(
            original_query="What career would suit me?",
            expansions=(retrieval_query,),
        ),
        item=item,
        cache={},
    )
    assert rerank_query == match.query
    assert rerank_reason == match.reason
    assert rerank_relevance == match.relevance


def test_original_query_head_survives_protected_derived_pool_pressure() -> None:
    original = _fact(
        "original",
        "Local interview canary current model uses GPT-5.4 mini.",
    )
    repository = _BatchFacts(
        {
            "GPT-5.4 mini local interview canary current model": (original,),
            "current active state latest valid now": tuple(
                _fact(
                    f"derived_{index}",
                    f"Current active state latest valid now evidence {index}.",
                )
                for index in range(4)
            ),
            "current latest now": tuple(
                _fact(
                    f"temporal_{index}",
                    f"Current latest now active evidence {index}.",
                )
                for index in range(4)
            ),
        }
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion(
                    "GPT-5.4 mini local interview canary current model",
                    "original_query",
                ),
                QueryExpansion(
                    "current active state latest valid now",
                    "current_state_temporal_bridge",
                ),
                QueryExpansion(
                    "current latest now",
                    "decomposition_knowledge_update_current",
                ),
            ),
            total_limit=1,
        )
    )

    assert str(result.matches[0].fact.id) == "original"
    assert result.matches[0].reason == "original_query"


def test_current_truth_fact_match_preserves_original_query_provenance() -> None:
    target = _fact(
        "target",
        "Current active state latest valid now: local interview canary uses GPT-5.4 mini.",
    )
    repository = _BatchFacts(
        {
            "GPT-5.4 mini local interview canary current model": (target,),
            "current active state latest valid now": (target,),
        }
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion(
                    "GPT-5.4 mini local interview canary current model",
                    "original_query",
                ),
                QueryExpansion(
                    "current active state latest valid now",
                    "current_state_temporal_bridge",
                ),
            ),
            total_limit=1,
        )
    )

    assert len(result.matches) == 1
    match = result.matches[0]
    assert str(match.fact.id) == "target"
    assert match.reason == "original_query"
    assert match.query == "GPT-5.4 mini local interview canary current model"
    projected = _fact_context_item(
        target,
        now=datetime(2026, 7, 30, tzinfo=UTC),
        query_text=match.query,
        query_expansion_reason=match.reason,
        relevance=match.relevance,
    )
    assert projected.diagnostics["query_expansion_reason"] == "original_query"
    assert projected.diagnostics["score_signals"]["unique_term_hits"] >= 6


def test_domain_specific_derived_match_beats_original_match() -> None:
    target = _fact("target", "Melanie identifies as part of the LGBTQ community.")
    original = canonical_fact_match(
        target,
        retrieval_query=QueryExpansion(
            "Would Melanie be considered a member of the LGBTQ community?",
            "original_query",
        ),
    )
    derived = canonical_fact_match(
        target,
        retrieval_query=QueryExpansion(
            "Melanie LGBTQ part identify member community",
            "community_membership_bridge",
        ),
    )

    assert _fact_match_is_preferred(derived, current=original)


def test_fair_derived_heads_preserve_strong_candidate_from_one_plan_lane() -> None:
    shared = tuple(
        _fact(
            f"shared_{index}",
            f"Shared common alpha beta gamma overlap evidence {index}.",
        )
        for index in range(40)
    )
    lane_heads = tuple(
        _fact(
            f"lane_{index}",
            f"Orchid cobalt amber quartz meadow signal evidence {index}.",
        )
        for index in range(6)
    )
    target = _fact(
        "lane_target",
        "Orchid cobalt amber quartz meadow signal target evidence.",
    )
    repository = _BatchFacts(
        {
            "shared common alpha beta gamma": shared,
            "shared common alpha beta gamma overlap": shared,
            "orchid cobalt amber quartz meadow signal": (*lane_heads, target),
        }
    )
    retrieval_queries = (
        QueryExpansion("shared common alpha beta gamma", "original_query"),
        QueryExpansion(
            "shared common alpha beta gamma overlap",
            "derived_overlap_lane",
        ),
        QueryExpansion(
            "orchid cobalt amber quartz meadow signal",
            "derived_unique_lane",
        ),
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=retrieval_queries,
            total_limit=10,
        )
    )

    selected_ids = [str(match.fact.id) for match in result.matches]
    assert len(selected_ids) == 40
    assert selected_ids.index("lane_target") < 20
    target_match = next(match for match in result.matches if str(match.fact.id) == "lane_target")
    assert target_match.reason == "derived_unique_lane"


def test_fair_derived_heads_do_not_reserve_weak_lane_noise() -> None:
    shared = tuple(
        _fact(
            f"shared_{index}",
            f"Shared common alpha beta gamma overlap evidence {index}.",
        )
        for index in range(40)
    )
    weak = _fact("weak_lane_noise", "Orchid cobalt unrelated memory.")
    repository = _BatchFacts(
        {
            "shared common alpha beta gamma": shared,
            "shared common alpha beta gamma overlap": shared,
            "orchid cobalt amber quartz meadow signal": (weak,),
        }
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion("shared common alpha beta gamma", "original_query"),
                QueryExpansion(
                    "shared common alpha beta gamma overlap",
                    "derived_overlap_lane",
                ),
                QueryExpansion(
                    "orchid cobalt amber quartz meadow signal",
                    "derived_weak_lane",
                ),
            ),
            total_limit=10,
        )
    )

    assert "weak_lane_noise" not in {str(match.fact.id) for match in result.matches}


def test_weak_unprioritized_derived_fact_is_not_admitted() -> None:
    weak = _fact("weak_transcript", "Alex meeting decision.")
    query = (
        "alex conversation meeting call transcript notes discussed mentioned decision action item"
    )
    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            _BatchFacts({query: (weak,)}),
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion(
                    query,
                    "conversation_transcript_evidence_bridge",
                ),
            ),
            total_limit=5,
        )
    )

    assert result.query_results[0].facts == (weak,)
    assert result.matches == ()


def test_weak_current_truth_derived_fact_is_not_admitted() -> None:
    weak = _fact("weak_current", "Active coding session uses retry strategy.")
    query = "model current latest active final selected provider tool option"
    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            _BatchFacts({query: (weak,)}),
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(QueryExpansion(query, "decomposition_knowledge_update_current"),),
            total_limit=5,
        )
    )

    assert result.query_results[0].facts == (weak,)
    assert result.matches == ()


def test_strong_current_truth_derived_fact_is_admitted() -> None:
    current = _fact("current_model", "Local interview canary uses GPT-5.4 mini.")
    query = "GPT mini local interview canary current latest active model"
    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            _BatchFacts({query: (current,)}),
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(QueryExpansion(query, "decomposition_knowledge_update_current"),),
            total_limit=5,
        )
    )

    assert [str(match.fact.id) for match in result.matches] == ["current_model"]
    assert result.matches[0].reason == "decomposition_knowledge_update_current"


def test_broad_fact_request_preserves_full_ranked_candidate_window() -> None:
    facts = tuple(
        _fact(
            f"candidate_{index}",
            f"Orchid cobalt amber quartz meadow evidence {index}.",
        )
        for index in range(150)
    )
    repository = _BatchFacts({"orchid cobalt amber quartz meadow": facts})

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion(
                    "orchid cobalt amber quartz meadow",
                    "original_query",
                ),
            ),
            total_limit=200,
        )
    )

    assert canonical_fact_candidate_limit(200) == 200
    assert canonical_fact_candidate_limit(30) == 100
    assert canonical_fact_rerank_pool_limit(200) == 200
    assert canonical_fact_rerank_pool_limit(30) == 40
    assert len(result.matches) == 150
    assert str(result.matches[-1].fact.id) == "candidate_149"


def test_fair_derived_lane_dedupes_before_per_query_cap() -> None:
    shared = tuple(
        _fact(
            f"shared_{index}",
            f"Shared common alpha beta gamma overlap evidence {index}.",
        )
        for index in range(40)
    )
    duplicate = _fact(
        "duplicate_lane_head",
        "Orchid cobalt amber quartz meadow signal repeated evidence.",
    )
    unique_rank_nine = _fact(
        "unique_rank_nine",
        "Orchid cobalt amber quartz meadow signal unique evidence.",
    )
    repository = _BatchFacts(
        {
            "shared common alpha beta gamma": shared,
            "shared common alpha beta gamma overlap": shared,
            "orchid cobalt amber quartz meadow signal": (
                *((duplicate,) * 8),
                unique_rank_nine,
            ),
        }
    )

    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion("shared common alpha beta gamma", "original_query"),
                QueryExpansion(
                    "shared common alpha beta gamma overlap",
                    "derived_overlap_lane",
                ),
                QueryExpansion(
                    "orchid cobalt amber quartz meadow signal",
                    "derived_duplicate_heavy_lane",
                ),
            ),
            total_limit=10,
        )
    )

    selected_ids = tuple(str(match.fact.id) for match in result.matches)
    assert selected_ids.count("duplicate_lane_head") == 1
    assert "unique_rank_nine" in selected_ids[:20]


def test_protected_then_fair_derived_prefix_is_stable_and_round_robin() -> None:
    protected_lane = (
        _fact("protected_head", "Protected coral silver forest river evidence."),
        _fact("protected_second", "Protected coral silver forest river detail."),
    )
    second_lane = (
        _fact("second_head", "Orchid cobalt amber quartz meadow signal evidence."),
        _fact("second_next", "Orchid cobalt amber quartz meadow signal detail."),
    )
    repository = _BatchFacts(
        {
            "baseline original query": (),
            "protected coral silver forest river": protected_lane,
            "orchid cobalt amber quartz meadow signal": second_lane,
        }
    )
    retrieval_queries = (
        QueryExpansion("baseline original query", "original_query"),
        QueryExpansion(
            "protected coral silver forest river",
            "family_swimming_activity_bridge",
        ),
        QueryExpansion(
            "orchid cobalt amber quartz meadow signal",
            "derived_second_lane",
        ),
    )

    first = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=retrieval_queries,
            total_limit=10,
        )
    )
    second = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=retrieval_queries,
            total_limit=10,
        )
    )

    first_ids = tuple(str(match.fact.id) for match in first.matches)
    second_ids = tuple(str(match.fact.id) for match in second.matches)
    assert first_ids[:4] == (
        "protected_head",
        "second_head",
        "protected_second",
        "second_next",
    )
    assert second_ids == first_ids


def test_empty_duplicate_queries_are_deduped_without_candidates() -> None:
    repository = _ScalarFacts({})
    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            repository,
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion("  orchid cobalt  ", "original_query"),
                QueryExpansion("ORCHID COBALT", "duplicate_query"),
            ),
            total_limit=20,
        )
    )

    assert repository.queries == ["  orchid cobalt  "]
    assert result.matches == ()
    assert result.raw_fact_count == 0


def test_candidate_and_fusion_windows_are_hard_capped_at_two_hundred() -> None:
    facts = tuple(
        _fact(
            f"candidate_{index}",
            f"Orchid cobalt amber quartz meadow evidence {index}.",
        )
        for index in range(250)
    )
    result = asyncio.run(
        retrieve_plan_aware_active_facts(
            _BatchFacts({"orchid cobalt amber quartz meadow": facts}),
            space_id="space_test",
            memory_scope_ids=("scope_test",),
            thread_id=None,
            retrieval_queries=(
                QueryExpansion("orchid cobalt amber quartz meadow", "original_query"),
            ),
            total_limit=500,
        )
    )

    assert canonical_fact_candidate_limit(500) == 200
    assert canonical_fact_rerank_pool_limit(500) == 200
    assert len(result.matches) == 200
    assert result.raw_fact_count == 200


def test_fusion_rank_floor_is_optional_and_preserves_default_behavior() -> None:
    rankings = {"0:original_query": tuple(f"fact_{index}" for index in range(80))}

    default = _fused_ranked_keys(rankings, limit=80)
    explicit_default = _fused_ranked_keys(rankings, limit=80, max_rank_floor=0)
    widened = _fused_ranked_keys(rankings, limit=80, max_rank_floor=80)

    assert explicit_default == default
    assert len(default) < 80
    assert widened == rankings["0:original_query"]


class _BatchFacts:
    def __init__(self, results: dict[str, tuple[MemoryFact, ...]]) -> None:
        self._results = results
        self.call_count = 0

    async def find_active_many(self, searches: tuple[object, ...]) -> list[list[MemoryFact]]:
        self.call_count += 1
        return [
            list(self._results.get(str(search.query), ()))[: int(search.limit)]
            for search in searches
        ]

    async def find_active(self, **_: object) -> list[MemoryFact]:
        raise AssertionError("scalar lookup must not run when batching is available")


class _ScalarFacts:
    def __init__(self, results: dict[str, tuple[MemoryFact, ...]]) -> None:
        self._results = results
        self.queries: list[str] = []

    async def find_active(self, *, query: str, limit: int, **_: object) -> list[MemoryFact]:
        self.queries.append(query)
        return list(self._results.get(query, ()))[:limit]


class _Chunks:
    async def keyword_search(self, **_: object) -> list[object]:
        return []


class _Anchors:
    async def list_for_scopes(self, searches: tuple[object, ...]) -> list[list[object]]:
        return [[] for _ in searches]

    async def find_active_by_keys(self, searches: tuple[object, ...]) -> list[None]:
        return [None for _ in searches]


class _Uow:
    def __init__(self, *, facts: object) -> None:
        self.facts = facts
        self.chunks = _Chunks()
        self.anchors = _Anchors()

    async def __aenter__(self) -> _Uow:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _UowFactory:
    def __init__(self, uow: _Uow) -> None:
        self._uow = uow

    def __call__(self) -> _Uow:
        return self._uow


def _fact(fact_id: str, text: str) -> MemoryFact:
    return MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space_test"),
        memory_scope_id=MemoryScopeId("scope_test"),
        text=text,
        kind=MemoryKind.NOTE,
        source_refs=(SourceRef(source_type="manual", source_id=f"{fact_id}_source"),),
        now=datetime(2026, 7, 1, tzinfo=UTC),
    )
