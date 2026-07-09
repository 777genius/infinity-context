"""Context candidate collectors."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import TypeVar

from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.context_relevance import (
    has_project_identity_mismatch,
    is_fact_candidate_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.domain.entities import MemoryAnchor, MemoryChunk, MemoryFact
from infinity_context_core.ports.adapters import (
    EmbeddingPort,
    GraphMemoryPort,
    PortStatus,
    VectorMemoryPort,
)
from infinity_context_core.ports.capabilities import (
    CapabilityRecallCandidate,
    CapabilityRecallQuery,
    CapabilityStatus,
    MemoryScopeFilter,
    RagRecallPort,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SAFE_RECALL_METADATA_KEYS = frozenset(
    {
        "provider",
        "adapter_name",
        "projection_version",
        "collection",
        "dataset_id",
    }
)
_SENSITIVE_VALUE_MARKERS = (
    "bearer ",
    "sk-",
    "api_key",
    "password",
    "secret",
    "token",
    "private_",
)
_MAX_DERIVED_RETRIEVAL_QUERIES = 8
_FUSION_RANK_CONSTANT = 60.0
_FUSION_MAX_RANK_PER_QUERY = 50
_HIGH_SIGNAL_DECOMPOSITION_REASONS = frozenset(
    {
        "decomposition_activity_duration",
        "decomposition_activity_participation",
        "decomposition_artifact_evidence",
        "decomposition_commonality",
        "decomposition_counterfactual_evidence",
        "decomposition_event_context",
        "decomposition_event_sequence",
        "decomposition_evidence_reason",
        "decomposition_frequency_recurrence",
        "decomposition_inventory_list",
        "decomposition_knowledge_update_current",
        "decomposition_knowledge_update_previous",
        "decomposition_lgbtq_pride_event",
        "decomposition_lgbtq_school_speech_event",
        "decomposition_lgbtq_support_group_event",
        "decomposition_relative_time",
        "decomposition_relocation_context",
        "decomposition_relocation_destination",
        "decomposition_relationship_status",
        "decomposition_source_evidence",
        "decomposition_state_transition",
        "decomposition_temporal_change",
    }
)
_HIGH_SIGNAL_EXPANSION_REASONS = frozenset(
    {
        "activity_aggregation_bridge",
        "activity_visual_selfcare_bridge",
        "adoption_current_goal_bridge",
        "allergy_condition_inference_bridge",
        "animal_affinity_pet_store_bridge",
        "animal_care_instruction_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "attribute_calm_resourcefulness_bridge",
        "attribute_family_support_bridge",
        "attribute_rescue_purpose_bridge",
        "attribute_service_helpfulness_bridge",
        "audio_transcript_evidence_bridge",
        "ally_support_bridge",
        "birdwatching_city_schedule_bridge",
        "book_reading_list_bridge",
        "beach_count_activity_bridge",
        "beach_or_mountains_inference_bridge",
        "business_commonality_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "business_start_reason_bridge",
        "store_promotion_inventory_bridge",
        "camping_detail_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
        "charity_brand_sponsorship_bridge",
        "charity_tournament_count_bridge",
        "children_preference_bridge",
        "community_membership_bridge",
        "community_membership_support_bridge",
        "commonality_interest_bridge",
        "conversation_transcript_evidence_bridge",
        "counseling_workshop_bridge",
        "current_state_temporal_bridge",
        "degree_policy_inference_bridge",
        "endorsement_gear_brand_bridge",
        "education_career_field_bridge",
        "event_participation_bridge",
        "event_participation_help_bridge",
        "exercise_activity_inventory_bridge",
        "family_activity_bridge",
        "food_recipe_recommendation_bridge",
        "family_hike_detail_bridge",
        "family_hike_activity_bridge",
        "family_museum_activity_bridge",
        "family_motivation_context_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
        "food_preference_bridge",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "friends_team_inference_bridge",
        "generic_behavior_inference_bridge",
        "gaming_medium_bridge",
        "hiking_trail_count_bridge",
        "hobby_interest_bridge",
        "instrument_play_bridge",
        "item_purchase_bridge",
        "letter_count_bridge",
        "lgbtq_community_participation_bridge",
        "lgbtq_pride_event_bridge",
        "lgbtq_school_event_bridge",
        "lgbtq_support_group_event_bridge",
        "meteor_shower_feeling_bridge",
        "national_park_inference_bridge",
        "military_service_willingness_bridge",
        "patriotic_service_inference_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
        "political_inference_bridge",
        "pottery_type_bridge",
        "post_athletic_career_bridge",
        "public_office_service_bridge",
        "relocation_willingness_inference_bridge",
        "relationship_duration_bridge",
        "relationship_origin_bridge",
        "relationship_status_bridge",
        "religious_inference_bridge",
        "screenplay_count_bridge",
        "shelter_comfort_reason_bridge",
        "source_evidence_bridge",
        "speaker_turn_bridge",
        "state_residence_inference_bridge",
        "state_transition_bridge",
        "stale_state_temporal_bridge",
        "support_career_motivation_bridge",
        "support_counterfactual_bridge",
        "support_network_bridge",
        "support_origin_bridge",
        "support_role_fit_bridge",
        "symbol_importance_bridge",
        "temporal_event_detail_bridge",
        "transgender_conference_event_bridge",
        "transgender_poetry_event_bridge",
        "transgender_youth_center_event_bridge",
        "tournament_count_bridge",
        "travel_country_inventory_bridge",
        "video_transcript_evidence_bridge",
        "visual_text_evidence_bridge",
        "volunteer_career_inference_bridge",
        "yoga_delay_gaming_bridge",
    }
)
_BROAD_AGGREGATION_EXPANSION_REASONS = frozenset(
    {
        "event_participation_bridge",
    }
)
_MULTI_EVIDENCE_PROTECTED_HEAD_REASONS = frozenset(
    {
        "animal_affinity_pet_store_bridge",
        "animal_care_instruction_bridge",
        "animal_diet_evidence_bridge",
        "animal_habitat_setup_bridge",
        "birdwatching_city_schedule_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "family_activity_bridge",
        "item_purchase_bridge",
        "post_athletic_career_bridge",
        "store_promotion_inventory_bridge",
        "symbol_importance_bridge",
        "food_recipe_recommendation_bridge",
        "wellness_activity_effect_bridge",
    }
)
_PROTECTED_EXPANSION_HEAD_REASONS = frozenset(
    {
        "adverse_trip_bridge",
        "adoption_current_milestone_bridge",
        "age_birthday_bridge",
        "allergy_inventory_bridge",
        "animal_career_inference_bridge",
        "art_style_bridge",
        "artifact_inventory_bridge",
        "attribute_trait_inventory_bridge",
        "birthplace_origin_bridge",
        "book_suggestion_bridge",
        "career_intent_bridge",
        "children_books_inference_bridge",
        "children_count_event_bridge",
        "classical_music_preference_bridge",
        "current_occupation_bridge",
        "current_recommendation_bridge",
        "current_residence_bridge",
        "deadline_commitment_bridge",
        "entity_relation_inventory_bridge",
        "family_origin_bridge",
        "followup_task_bridge",
        "gotcha_failure_bridge",
        "hike_count_activity_bridge",
        "music_artist_answer_bridge",
        "music_artist_band_bridge",
        "negative_experience_support_bridge",
        "negative_preference_bridge",
        "organization_summary_bridge",
        "painting_inventory_bridge",
        "person_summary_bridge",
        "event_summary_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "project_summary_bridge",
        "post_event_activity_timing_bridge",
        "possession_gift_object_bridge",
        "recommendation_source_bridge",
        "relocation_destination_bridge",
        "relocation_origin_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "shared_painted_subject_bridge",
        "shoe_usage_bridge",
        "trip_destination_bridge",
    }
)
_T = TypeVar("_T")


@dataclass(frozen=True)
class ContextRetrievalDeadlines:
    vector_capabilities_seconds: float | None = 2.0
    vector_embedding_seconds: float | None = 8.0
    vector_search_seconds: float | None = 5.0
    vector_hydration_seconds: float | None = 5.0
    graph_capabilities_seconds: float | None = 2.0
    graph_search_seconds: float | None = 5.0
    graph_hydration_seconds: float | None = 5.0
    rag_recall_seconds: float | None = 5.0
    rag_hydration_seconds: float | None = 5.0


@dataclass(frozen=True)
class CanonicalCollectionResult:
    facts: tuple[MemoryFact, ...]
    keyword_chunks: tuple[MemoryChunk, ...]
    anchors: tuple[MemoryAnchor, ...] = ()
    keyword_query_count: int = 0
    keyword_query_reasons: tuple[str, ...] = ()
    anchor_lookup_keys_considered: int = 0
    anchors_loaded_by_lookup: int = 0


class CanonicalContextCollector:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        keyword_query_plan: QueryExpansionPlan | None = None,
        anchor_lookup_keys: tuple[tuple[str, str], ...] | None = None,
    ) -> CanonicalCollectionResult:
        async with self._uow_factory() as uow:
            facts = await uow.facts.find_active(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                query=query.query,
                limit=_canonical_fact_candidate_limit(query.max_facts),
                category=query.category,
                tags_any=query.tags_any,
                tags_all=query.tags_all,
                tags_none=query.tags_none,
            )
            facts = _rank_facts_for_query(
                tuple(facts),
                query_text=query.query,
                limit=_canonical_fact_rerank_pool_limit(query.max_facts),
            )
            keyword_retrieval_queries = _bounded_derived_retrieval_queries(
                keyword_query_plan,
                fallback=query.query,
            )
            keyword_chunks = await _keyword_search_chunks(
                uow,
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                retrieval_queries=keyword_retrieval_queries,
                limit=query.max_chunks,
            )
            anchors: list[MemoryAnchor] = []
            anchor_limit = min(100, max(query.max_facts * 2, 20))
            for memory_scope_id in memory_scope_ids:
                anchors.extend(
                    await uow.anchors.list_for_scope(
                        space_id=str(query.space_id),
                        memory_scope_id=memory_scope_id,
                        kind=None,
                        status="active",
                        limit=anchor_limit,
                    )
                )
            anchors_by_id = {str(anchor.id): anchor for anchor in anchors}
            lookup_keys_considered = 0
            anchors_loaded_by_lookup = 0
            for memory_scope_id in memory_scope_ids:
                for kind, normalized_key in _bounded_anchor_lookup_keys(
                    anchor_lookup_keys or (),
                ):
                    if lookup_keys_considered >= 64:
                        break
                    lookup_keys_considered += 1
                    anchor = await uow.anchors.find_active_by_key(
                        space_id=str(query.space_id),
                        memory_scope_id=memory_scope_id,
                        kind=kind,
                        normalized_key=normalized_key,
                    )
                    if anchor is None or str(anchor.id) in anchors_by_id:
                        continue
                    anchors_by_id[str(anchor.id)] = anchor
                    anchors_loaded_by_lookup += 1
                if lookup_keys_considered >= 64:
                    break
        return CanonicalCollectionResult(
            facts=tuple(facts),
            keyword_chunks=tuple(keyword_chunks),
            anchors=tuple(anchors_by_id.values()),
            keyword_query_count=len(keyword_retrieval_queries),
            keyword_query_reasons=tuple(
                query.reason for query in keyword_retrieval_queries
            ),
            anchor_lookup_keys_considered=lookup_keys_considered,
            anchors_loaded_by_lookup=anchors_loaded_by_lookup,
        )


async def _keyword_search_chunks(
    uow: object,
    *,
    space_id: str,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
    retrieval_queries: tuple[QueryExpansion, ...],
    limit: int,
) -> tuple[MemoryChunk, ...]:
    if limit <= 0:
        return ()
    chunks_by_id: dict[str, MemoryChunk] = {}
    rankings: dict[str, tuple[str, ...]] = {}
    seen_queries: set[str] = set()
    candidate_limit = _keyword_candidate_pool_limit(limit)
    search_limit = _keyword_query_search_limit(
        total_limit=limit,
        candidate_limit=candidate_limit,
    )
    for index, retrieval_query in enumerate(retrieval_queries):
        normalized_query = " ".join(retrieval_query.query.split()).casefold()
        if not normalized_query or normalized_query in seen_queries:
            continue
        seen_queries.add(normalized_query)
        chunks = await uow.chunks.keyword_search(
            space_id=space_id,
            memory_scope_ids=memory_scope_ids,
            thread_id=thread_id,
            query=retrieval_query.query,
            limit=search_limit,
        )
        ranking_ids: list[str] = []
        for chunk in chunks:
            chunk_id = str(chunk.id)
            chunks_by_id.setdefault(chunk_id, chunk)
            ranking_ids.append(chunk_id)
        rankings[_retrieval_query_rank_key(index, retrieval_query)] = tuple(ranking_ids)
    protected_ids = _protected_query_head_keys(rankings)
    ranked_ids = tuple(
        dict.fromkeys(
            (
                *protected_ids,
                *_fused_ranked_keys(rankings, limit=candidate_limit),
            )
        )
    )[:candidate_limit]
    return tuple(chunks_by_id[chunk_id] for chunk_id in ranked_ids if chunk_id in chunks_by_id)


def _keyword_candidate_pool_limit(total_limit: int) -> int:
    if total_limit <= 0:
        return 0
    return min(360, max(total_limit * 6, total_limit))


def _keyword_query_search_limit(*, total_limit: int, candidate_limit: int) -> int:
    if total_limit <= 0 or candidate_limit <= 0:
        return 0
    return min(candidate_limit, max(20, candidate_limit // 2))


def _canonical_fact_candidate_limit(max_facts: int) -> int:
    if max_facts <= 0:
        return 0
    return min(100, max(max_facts * 4, max_facts + 8))


def _canonical_fact_rerank_pool_limit(max_facts: int) -> int:
    if max_facts <= 0:
        return 0
    return min(40, max(max_facts * 4, max_facts + 3))


def _bounded_anchor_lookup_keys(
    keys: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, normalized_key in keys:
        safe_kind = kind.strip().casefold()
        safe_key = " ".join(normalized_key.split()).casefold()
        if not safe_kind or not safe_key:
            continue
        key = (safe_kind, safe_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
        if len(deduped) >= 32:
            break
    return tuple(deduped)


def _rank_facts_for_query(
    facts: tuple[MemoryFact, ...],
    *,
    query_text: str,
    limit: int,
) -> tuple[MemoryFact, ...]:
    if limit <= 0 or not facts:
        return ()
    ranked = []
    for index, fact in enumerate(facts):
        if has_project_identity_mismatch(query=query_text, text=fact.text):
            continue
        relevance = score_query_relevance(query=query_text, text=fact.text)
        if not is_fact_candidate_relevance_sufficient(relevance):
            continue
        ranked.append((relevance, index, fact))
    ranked.sort(
        key=lambda item: (
            -item[0].phrase_bigram_hits,
            -item[0].phrase_boost,
            -item[0].score_boost,
            -item[0].unique_term_hits,
            -item[0].hit_ratio,
            -item[0].capped_frequency_hits,
            item[1],
        )
    )
    return tuple(fact for _, _, fact in ranked[:limit])


class VectorContextCollector:
    def __init__(
        self,
        *,
        vector_index: VectorMemoryPort,
        embedder: EmbeddingPort,
        hydrator: ContextHydrator,
        deadlines: ContextRetrievalDeadlines | None = None,
    ) -> None:
        self._vector_index = vector_index
        self._embedder = embedder
        self._hydrator = hydrator
        self._deadlines = deadlines or ContextRetrievalDeadlines()

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
        query_plan: QueryExpansionPlan | None = None,
    ) -> tuple[MemoryChunk, ...]:
        if query.max_chunks <= 0:
            diagnostics["vector_status"] = "skipped"
            return ()
        retrieval_queries = _bounded_derived_retrieval_queries(query_plan, fallback=query.query)
        diagnostics["vector_query_count"] = len(retrieval_queries)
        try:
            capabilities = await _await_with_deadline(
                self._vector_index.capabilities(),
                timeout_seconds=self._deadlines.vector_capabilities_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="vector",
                reason=_exception_code("vector", exc),
                step="capabilities",
                deadline_seconds=self._deadlines.vector_capabilities_seconds,
            )
            return ()
        if not capabilities.enabled:
            diagnostics["vector_status"] = (
                "disabled" if capabilities.degraded_reason == "disabled" else "degraded"
            )
            if capabilities.degraded_reason:
                diagnostics["vector_degraded_reason"] = capabilities.degraded_reason
            return ()
        if not capabilities.healthy or not capabilities.supports_search:
            diagnostics["vector_status"] = "degraded"
            if capabilities.degraded_reason:
                diagnostics["vector_degraded_reason"] = capabilities.degraded_reason
            return ()

        try:
            embedding = await _await_with_deadline(
                self._embedder.embed_texts(
                    tuple(item.query for item in retrieval_queries)
                ),
                timeout_seconds=self._deadlines.vector_embedding_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="vector",
                reason=_exception_code("embeddings", exc),
                step="embedding",
                deadline_seconds=self._deadlines.vector_embedding_seconds,
            )
            return ()
        if embedding.status != PortStatus.OK or not embedding.vectors:
            diagnostics["vector_status"] = embedding.status.value
            if embedding.diagnostics:
                diagnostics["vector_degraded_reason"] = embedding.diagnostics[0].code
            return ()
        vector_queries = tuple(
            zip(retrieval_queries, embedding.vectors, strict=False)
        )
        diagnostics["vector_embedding_vector_count"] = len(embedding.vectors)
        diagnostics["vector_search_count"] = len(vector_queries)
        diagnostics["vector_query_limit"] = _per_query_retrieval_limit(
            total_limit=query.max_chunks,
            query_count=len(vector_queries),
        )
        rankings: dict[str, tuple[str, ...]] = {}
        total_candidates = 0
        degraded_count = 0
        degraded_reason: str | None = None
        for index, (retrieval_query, vector) in enumerate(vector_queries):
            try:
                result = await _await_with_deadline(
                    self._vector_index.search_chunks(
                        space_id=str(query.space_id),
                        memory_scope_ids=memory_scope_ids,
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        query_vector=vector,
                        query_text=retrieval_query.query,
                        limit=int(diagnostics["vector_query_limit"]),
                    ),
                    timeout_seconds=self._deadlines.vector_search_seconds,
                )
            except Exception as exc:
                degraded_count += 1
                degraded_reason = _exception_code("vector", exc)
                if degraded_reason == "vector.timeout":
                    _mark_derived_retrieval_degraded(
                        diagnostics,
                        component="vector",
                        reason=degraded_reason,
                        step="search",
                        deadline_seconds=self._deadlines.vector_search_seconds,
                    )
                continue
            if result.status != PortStatus.OK:
                degraded_count += 1
                if result.diagnostics:
                    degraded_reason = result.diagnostics[0].code
                continue
            total_candidates += len(result.items)
            rankings[_retrieval_query_rank_key(index, retrieval_query)] = tuple(
                candidate.chunk_id for candidate in result.items
            )
        diagnostics["vector_candidate_count"] = total_candidates
        diagnostics["vector_query_degraded_count"] = degraded_count
        if degraded_reason:
            diagnostics["vector_degraded_reason"] = degraded_reason
        chunk_ids = _fused_ranked_keys(rankings, limit=_candidate_pool_limit(query.max_chunks))
        if not chunk_ids:
            diagnostics["vector_status"] = "degraded" if degraded_count else "ok"
            return ()
        diagnostics["vector_status"] = "ok"
        try:
            chunks = await _await_with_deadline(
                self._hydrator.hydrate_visible_chunks(
                    chunk_ids=chunk_ids,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                ),
                timeout_seconds=self._deadlines.vector_hydration_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="vector",
                reason=_exception_code("vector", exc),
                step="hydration",
                deadline_seconds=self._deadlines.vector_hydration_seconds,
            )
            return ()
        hydrated_ids = {str(chunk.id) for chunk in chunks}
        diagnostics["vector_hydrated_count"] = len(chunks)
        diagnostics["stale_vector_drop_count"] = sum(
            1 for chunk_id in chunk_ids if chunk_id not in hydrated_ids
        )
        return chunks


class GraphContextCollector:
    def __init__(
        self,
        *,
        graph_index: GraphMemoryPort,
        hydrator: ContextHydrator,
        deadlines: ContextRetrievalDeadlines | None = None,
    ) -> None:
        self._graph_index = graph_index
        self._hydrator = hydrator
        self._deadlines = deadlines or ContextRetrievalDeadlines()

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
        query_plan: QueryExpansionPlan | None = None,
    ) -> tuple[ContextItem, ...]:
        if not query.include_graph or query.max_facts <= 0:
            diagnostics["graph_status"] = "skipped"
            return ()
        retrieval_queries = _bounded_derived_retrieval_queries(query_plan, fallback=query.query)
        diagnostics["graph_query_count"] = len(retrieval_queries)
        diagnostics["graph_query_limit"] = _per_query_retrieval_limit(
            total_limit=query.max_facts,
            query_count=len(retrieval_queries),
        )
        try:
            capabilities = await _await_with_deadline(
                self._graph_index.capabilities(),
                timeout_seconds=self._deadlines.graph_capabilities_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="graph",
                reason=_exception_code("graph", exc),
                step="capabilities",
                deadline_seconds=self._deadlines.graph_capabilities_seconds,
            )
            return ()
        if not capabilities.enabled:
            diagnostics["graph_status"] = (
                "disabled" if capabilities.degraded_reason == "disabled" else "degraded"
            )
            if capabilities.degraded_reason:
                diagnostics["graph_degraded_reason"] = capabilities.degraded_reason
            return ()
        if not capabilities.healthy or not capabilities.supports_search:
            diagnostics["graph_status"] = "degraded"
            if capabilities.degraded_reason:
                diagnostics["graph_degraded_reason"] = capabilities.degraded_reason
            return ()
        rankings: dict[str, tuple[str, ...]] = {}
        orphan_candidate_count = 0
        total_candidates = 0
        degraded_count = 0
        degraded_reason: str | None = None
        for index, retrieval_query in enumerate(retrieval_queries):
            try:
                result = await _await_with_deadline(
                    self._graph_index.search(
                        space_id=str(query.space_id),
                        memory_scope_ids=memory_scope_ids,
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        query=retrieval_query.query,
                        limit=int(diagnostics["graph_query_limit"]),
                    ),
                    timeout_seconds=self._deadlines.graph_search_seconds,
                )
            except Exception as exc:
                degraded_count += 1
                degraded_reason = _exception_code("graph", exc)
                if degraded_reason == "graph.timeout":
                    _mark_derived_retrieval_degraded(
                        diagnostics,
                        component="graph",
                        reason=degraded_reason,
                        step="search",
                        deadline_seconds=self._deadlines.graph_search_seconds,
                    )
                continue
            if result.status != PortStatus.OK:
                degraded_count += 1
                if result.diagnostics:
                    degraded_reason = result.diagnostics[0].code
                continue
            total_candidates += len(result.items)
            orphan_candidate_count += sum(
                1
                for candidate in result.items
                if not candidate.source_fact_ids and not candidate.source_chunk_ids
            )
            rankings[_retrieval_query_rank_key(index, retrieval_query)] = tuple(
                fact_id
                for candidate in result.items
                for fact_id in candidate.source_fact_ids
            )
        diagnostics["graph_candidate_count"] = total_candidates
        diagnostics["graph_query_degraded_count"] = degraded_count
        if degraded_reason:
            diagnostics["graph_degraded_reason"] = degraded_reason
        fact_ids = _fused_ranked_keys(rankings, limit=_candidate_pool_limit(query.max_facts))
        if not fact_ids:
            diagnostics["graph_status"] = "degraded" if degraded_count else "ok"
            diagnostics["stale_graph_drop_count"] = orphan_candidate_count
            return ()
        diagnostics["graph_status"] = "ok"
        try:
            items, stale_count = await _await_with_deadline(
                self._hydrator.hydrate_graph_facts(
                    fact_ids=fact_ids,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                ),
                timeout_seconds=self._deadlines.graph_hydration_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="graph",
                reason=_exception_code("graph", exc),
                step="hydration",
                deadline_seconds=self._deadlines.graph_hydration_seconds,
            )
            return ()
        diagnostics["graph_hydrated_count"] = len(items)
        diagnostics["stale_graph_drop_count"] = stale_count + orphan_candidate_count
        return items[: query.max_facts]


class RagContextCollector:
    def __init__(
        self,
        *,
        rag_recall: RagRecallPort | None,
        hydrator: ContextHydrator,
        deadlines: ContextRetrievalDeadlines | None = None,
    ) -> None:
        self._rag_recall = rag_recall
        self._hydrator = hydrator
        self._deadlines = deadlines or ContextRetrievalDeadlines()

    async def collect(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
        diagnostics: dict[str, object],
        query_plan: QueryExpansionPlan | None = None,
    ) -> tuple[ContextItem, ...]:
        if self._rag_recall is None or query.max_chunks <= 0:
            diagnostics["rag_status"] = "skipped"
            return ()
        retrieval_queries = _bounded_derived_retrieval_queries(query_plan, fallback=query.query)
        diagnostics["rag_query_count"] = len(retrieval_queries)
        diagnostics["rag_query_limit"] = _per_query_retrieval_limit(
            total_limit=query.max_chunks,
            query_count=len(retrieval_queries),
        )
        rankings: dict[str, tuple[str, ...]] = {}
        candidates_by_key: dict[str, tuple[CapabilityRecallCandidate, QueryExpansion]] = {}
        total_candidates = 0
        degraded_count = 0
        degraded_reason: str | None = None
        for index, retrieval_query in enumerate(retrieval_queries):
            try:
                result = await _await_with_deadline(
                    self._rag_recall.recall(
                        CapabilityRecallQuery(
                            scope=MemoryScopeFilter(
                                space_id=str(query.space_id),
                                memory_scope_ids=memory_scope_ids,
                                thread_id=str(query.thread_id) if query.thread_id else None,
                            ),
                            query=retrieval_query.query,
                            limit=int(diagnostics["rag_query_limit"]),
                        )
                    ),
                    timeout_seconds=self._deadlines.rag_recall_seconds,
                )
            except Exception as exc:
                degraded_count += 1
                degraded_reason = _exception_code("rag", exc)
                if degraded_reason == "rag.timeout":
                    _mark_derived_retrieval_degraded(
                        diagnostics,
                        component="rag",
                        reason=degraded_reason,
                        step="recall",
                        deadline_seconds=self._deadlines.rag_recall_seconds,
                    )
                continue
            if result.status != CapabilityStatus.OK:
                degraded_count += 1
                if result.diagnostics:
                    degraded_reason = result.diagnostics[0].code
                continue
            total_candidates += len(result.items)
            ranking_keys: list[str] = []
            for candidate in result.items:
                candidate_key = _candidate_primary_chunk_key(candidate)
                if not candidate_key:
                    continue
                ranking_keys.append(candidate_key)
                existing = candidates_by_key.get(candidate_key)
                if existing is None or candidate.score > existing[0].score:
                    candidates_by_key[candidate_key] = (candidate, retrieval_query)
            rankings[_retrieval_query_rank_key(index, retrieval_query)] = tuple(ranking_keys)
        diagnostics["rag_candidate_count"] = total_candidates
        diagnostics["rag_query_degraded_count"] = degraded_count
        if degraded_reason:
            diagnostics["rag_degraded_reason"] = degraded_reason
        candidate_keys = _fused_ranked_keys(
            rankings,
            limit=_candidate_pool_limit(query.max_chunks),
        )
        if not candidate_keys:
            diagnostics["rag_status"] = "degraded" if degraded_count else "ok"
            return ()

        chunk_ids = tuple(
            dict.fromkeys(
                chunk_id
                for candidate_key in candidate_keys
                for candidate, _ in (candidates_by_key[candidate_key],)
                for chunk_id in _candidate_chunk_ids(candidate)
            )
        )
        try:
            chunks = await _await_with_deadline(
                self._hydrator.hydrate_visible_chunks(
                    chunk_ids=chunk_ids,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                ),
                timeout_seconds=self._deadlines.rag_hydration_seconds,
            )
        except Exception as exc:
            _mark_derived_retrieval_degraded(
                diagnostics,
                component="rag",
                reason=_exception_code("rag", exc),
                step="hydration",
                deadline_seconds=self._deadlines.rag_hydration_seconds,
            )
            return ()
        chunks_by_id = {str(chunk.id): chunk for chunk in chunks}
        items: list[ContextItem] = []
        dropped = 0
        for candidate_key in candidate_keys:
            candidate, retrieval_query = candidates_by_key[candidate_key]
            visible_chunk = next(
                (
                    chunks_by_id[chunk_id]
                    for chunk_id in _candidate_chunk_ids(candidate)
                    if chunk_id in chunks_by_id
                ),
                None,
            )
            if visible_chunk is None:
                dropped += 1
                continue
            items.append(
                _rag_chunk_item(
                    candidate,
                    visible_chunk,
                    query_text=retrieval_query.query,
                    query_reason=retrieval_query.reason,
                )
            )
        diagnostics["rag_status"] = "ok"
        diagnostics["rag_hydrated_count"] = len(items)
        diagnostics["stale_rag_drop_count"] = dropped
        return tuple(items)


def _candidate_chunk_ids(candidate: CapabilityRecallCandidate) -> tuple[str, ...]:
    chunk_ids: list[str] = []
    if candidate.item_type == "chunk":
        chunk_ids.append(candidate.item_id)
    for source_ref in candidate.source_refs:
        if source_ref.chunk_id:
            chunk_ids.append(source_ref.chunk_id)
        elif source_ref.source_type == "chunk":
            chunk_ids.append(source_ref.source_id)
    return tuple(dict.fromkeys(chunk_id for chunk_id in chunk_ids if chunk_id.strip()))


def _candidate_primary_chunk_key(candidate: CapabilityRecallCandidate) -> str | None:
    chunk_ids = _candidate_chunk_ids(candidate)
    if chunk_ids:
        return chunk_ids[0]
    candidate_id = candidate.item_id.strip()
    return candidate_id or None


def _rag_chunk_item(
    candidate: CapabilityRecallCandidate,
    chunk: MemoryChunk,
    *,
    query_text: str,
    query_reason: str = "original_query",
) -> ContextItem:
    chunk_text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
    snippet = query_focused_snippet(query=query_text, text=chunk_text)
    evidence_text = snippet.text if snippet is not None else chunk_text
    source_refs = source_refs_with_query_snippet(
        chunk_source_refs(chunk, text_preview=(snippet.text if snippet else chunk_text)),
        snippet,
        include_char_range=True,
    )
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(chunk.id),
            item_type="chunk",
            text=evidence_text,
            score=candidate.score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(chunk.memory_scope_id),
                "retrieval_source": "rag_recall",
                "retrieval_sources": ["rag_recall"],
                "ranking_reason": "matched via external RAG recall and canonical hydration",
                "score_signals": {
                    "base_score": candidate.score,
                    "retrieval_channel": "rag_recall",
                    "rag_query_reason": query_reason,
                    "source_ref_count": len(source_refs),
                    **query_snippet_score_signals(snippet),
                },
                "provenance": {
                    "retrieval_sources": ["rag_recall"],
                    "rag_query_reason": query_reason,
                    "source_ref_count": len(source_refs),
                    "adapter_name": _safe_adapter_name(candidate.adapter_name),
                    "chunk_id": str(chunk.id),
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                },
                "adapter_name": _safe_adapter_name(candidate.adapter_name),
                **source_ref_location_summary(source_refs),
                **query_snippet_diagnostics(snippet),
                **_safe_recall_metadata(candidate.metadata),
            },
        ),
        query_text=query_text,
    )


def _safe_recall_metadata(metadata: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = str(raw_key).strip()
        if key not in _SAFE_RECALL_METADATA_KEYS:
            continue
        value = _safe_metadata_value(raw_value)
        if _looks_sensitive(value):
            continue
        safe[key] = value
    return safe


def _safe_adapter_name(value: object) -> str:
    safe_value = _safe_metadata_value(value)
    if not safe_value or _looks_sensitive(safe_value):
        return "unknown"
    return safe_value


def _safe_metadata_value(value: object) -> str:
    return str(value).strip()[:160]


def _looks_sensitive(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS)


def _bounded_derived_retrieval_queries(
    plan: QueryExpansionPlan | None,
    *,
    fallback: str,
    limit: int = _MAX_DERIVED_RETRIEVAL_QUERIES,
) -> tuple[QueryExpansion, ...]:
    raw_queries = tuple(
        plan.retrieval_queries
        if plan is not None
        else (QueryExpansion(query=fallback, reason="original_query"),)
    )
    raw_queries = _drop_ally_support_identity_noise(raw_queries)
    ranked_queries = sorted(
        enumerate(raw_queries),
        key=lambda item: (_retrieval_query_selection_priority(item[1]), item[0]),
    )
    raw_queries = tuple(query for _, query in ranked_queries)
    selected: list[QueryExpansion] = []
    seen: set[str] = set()
    for raw_query in raw_queries:
        query_text = " ".join(raw_query.query.split())
        key = query_text.casefold()
        if not query_text or key in seen:
            continue
        seen.add(key)
        selected.append(QueryExpansion(query=query_text, reason=raw_query.reason))
        if len(selected) >= limit:
            break
    if selected:
        return tuple(selected)
    return (QueryExpansion(query=fallback, reason="original_query"),)


def _drop_ally_support_identity_noise(
    queries: tuple[QueryExpansion, ...],
) -> tuple[QueryExpansion, ...]:
    reasons = {query.reason for query in queries}
    if not {
        "ally_support_bridge",
        "decomposition_ally_support_evidence",
        "identity_bridge",
    }.issubset(reasons):
        return queries
    return tuple(query for query in queries if query.reason != "identity_bridge")


def _retrieval_query_selection_priority(query: QueryExpansion) -> int:
    if query.reason == "original_query":
        return 0
    if query.reason in {
        "activity_visual_selfcare_bridge",
        "family_activity_bridge",
        "family_museum_activity_bridge",
        "family_painting_activity_bridge",
        "family_swimming_activity_bridge",
    }:
        return 1
    if query.reason == "exercise_activity_inventory_bridge":
        return 1
    if query.reason in _HIGH_SIGNAL_DECOMPOSITION_REASONS:
        return 1
    if query.reason in _BROAD_AGGREGATION_EXPANSION_REASONS:
        return 1
    if query.reason in {
        "activity_aggregation_bridge",
        "family_motivation_context_bridge",
        "hobby_interest_bridge",
    }:
        return 3
    if query.reason in _HIGH_SIGNAL_EXPANSION_REASONS:
        return 2
    if query.reason.startswith("decomposition_"):
        return 4
    return 3


def _per_query_retrieval_limit(*, total_limit: int, query_count: int) -> int:
    if total_limit <= 0:
        return 0
    if query_count <= 1:
        return total_limit
    return min(total_limit, max(4, (total_limit + 1) // 2))


def _candidate_pool_limit(total_limit: int) -> int:
    if total_limit <= 0:
        return 0
    return min(240, max(total_limit * 4, total_limit))


def _retrieval_query_rank_key(index: int, query: QueryExpansion) -> str:
    return f"{index}:{query.reason}"


def _protected_query_head_keys(rankings: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    protected: list[str] = []
    seen: set[str] = set()
    for ranking_key, ranked_keys in rankings.items():
        _, _, reason = ranking_key.partition(":")
        head_limit = _protected_query_head_limit_for_reason(reason)
        if head_limit <= 0:
            continue
        head_count = 0
        for raw_key in ranked_keys:
            key = raw_key.strip()
            if key and key not in seen:
                seen.add(key)
                protected.append(key)
                head_count += 1
                if head_count >= head_limit:
                    break
    return tuple(protected)


def _protected_query_head_limit_for_reason(reason: str) -> int:
    if reason == "food_recipe_recommendation_bridge":
        return 3
    if reason == "store_promotion_inventory_bridge":
        return 4
    if reason == "business_networking_event_bridge":
        return 2
    if reason == "business_promotion_event_bridge":
        return 3
    if reason == "business_store_promotion_event_bridge":
        return 2
    if reason == "business_opening_timeline_bridge":
        return 2
    if reason in _MULTI_EVIDENCE_PROTECTED_HEAD_REASONS:
        return 2
    if _protect_query_head_for_reason(reason):
        return 1
    return 0


def _protect_query_head_for_reason(reason: str) -> bool:
    return (
        reason in _HIGH_SIGNAL_EXPANSION_REASONS
        or reason in _PROTECTED_EXPANSION_HEAD_REASONS
        or reason in _BROAD_AGGREGATION_EXPANSION_REASONS
        or reason
        in {
            "decomposition_activity_participation",
            "decomposition_activity_duration",
            "decomposition_artifact_evidence",
            "decomposition_commonality",
            "decomposition_counterfactual_evidence",
            "decomposition_frequency_recurrence",
            "decomposition_inventory_list",
            "decomposition_knowledge_update_current",
            "decomposition_knowledge_update_previous",
            "decomposition_lgbtq_pride_event",
            "decomposition_lgbtq_school_speech_event",
            "decomposition_lgbtq_support_group_event",
            "decomposition_relationship_status",
            "decomposition_source_evidence",
            "decomposition_state_transition",
        }
    )


def _fused_ranked_keys(
    rankings: dict[str, tuple[str, ...]],
    *,
    limit: int,
) -> tuple[str, ...]:
    if limit <= 0:
        return ()
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    sequence = 0
    for ranking_key, ranked_keys in rankings.items():
        query_weight = _retrieval_query_fusion_weight(ranking_key)
        seen_in_ranking: set[str] = set()
        for rank, raw_key in enumerate(ranked_keys, start=1):
            if rank > _FUSION_MAX_RANK_PER_QUERY:
                break
            key = raw_key.strip()
            if not key or key in seen_in_ranking:
                continue
            seen_in_ranking.add(key)
            if key not in first_seen:
                first_seen[key] = sequence
                sequence += 1
            scores[key] = scores.get(key, 0.0) + query_weight / (
                _FUSION_RANK_CONSTANT + rank
            )
    return tuple(
        key
        for key, _ in sorted(
            scores.items(),
            key=lambda item: (-item[1], first_seen[item[0]], item[0]),
        )[:limit]
    )


def _retrieval_query_fusion_weight(ranking_key: str) -> float:
    _, _, reason = ranking_key.partition(":")
    if reason == "original_query":
        return 1.5
    if reason in _HIGH_SIGNAL_EXPANSION_REASONS:
        return 1.12
    if reason in _HIGH_SIGNAL_DECOMPOSITION_REASONS:
        return 1.0
    if reason.startswith("decomposition_"):
        return 0.7
    return 1.0


async def _await_with_deadline(
    awaitable: Awaitable[_T],
    *,
    timeout_seconds: float | None,
) -> _T:
    if timeout_seconds is None:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _mark_derived_retrieval_degraded(
    diagnostics: dict[str, object],
    *,
    component: str,
    reason: str,
    step: str,
    deadline_seconds: float | None,
) -> None:
    diagnostics[f"{component}_status"] = "degraded"
    diagnostics[f"{component}_degraded_reason"] = reason
    diagnostics[f"{component}_degraded_step"] = step
    if deadline_seconds is not None:
        diagnostics[f"{component}_deadline_seconds"] = round(float(deadline_seconds), 4)


def _exception_code(adapter: str, exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return f"{adapter}.timeout"
    return f"{adapter}.exception"
