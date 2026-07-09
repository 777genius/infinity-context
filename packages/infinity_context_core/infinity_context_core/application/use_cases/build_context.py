"""Build prompt-safe memory context from canonical and derived candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from time import perf_counter

from infinity_context_core.application.context_aggregation_evidence_text import (
    _aggregation_evidence_text,
    _strict_query_window_match_counts,
    _strict_token_variants,
    _StrictQueryTermVariants,
    _weighted_aggregation_query_variant_sets,
    _WeightedAggregationQueryVariants,
)
from infinity_context_core.application.context_anchor_relations import (
    related_anchor_context_items,
)
from infinity_context_core.application.context_anchors import (
    anchor_context_item,
    anchor_identity_retrieval_text,
    anchor_retrieval_text,
)
from infinity_context_core.application.context_artifact_evidence import (
    ArtifactEvidenceContextCollector,
)
from infinity_context_core.application.context_collectors import (
    CanonicalContextCollector,
    ContextRetrievalDeadlines,
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
)
from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
    normalize_context_bundle_diagnostics,
)
from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_link_expansion import ApprovedContextLinkExpander
from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_policy import (
    is_context_anchor_visible,
    is_context_fact_visible,
    is_context_review_fact_visible,
)
from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion import (
    QueryExpansionPlan,
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    match_query_anchor_intent,
    query_anchor_intent_conflicts,
    query_anchor_intent_text_conflicts,
    query_anchor_lookup_keys,
)
from infinity_context_core.application.context_ranking import (
    apply_context_requirement_boosts,
    apply_deterministic_rerank_adjustments,
    apply_keyword_chunk_source_score_boost,
    apply_query_anchor_intent_boosts,
    apply_query_plan_bm25_lexical_boosts,
    apply_rank_fusion_boosts,
    best_query_relevance,
    dedupe_rank_items,
    keyword_chunk_score,
    query_expansion_reason_priority,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_reason as _is_relationship_status_reason,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_chunk_candidate_relevance_sufficient,
    is_query_relevance_sufficient,
    query_relevance_score_signals,
    score_query_relevance,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_requirement_guard import (
    _apply_explicit_requirement_guard,
)
from infinity_context_core.application.context_review_items import (
    pending_review_suggestion_item,
    stale_review_item,
    suggestion_conflict_fact_id,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _focused_exact_source_repair_text,
    _pre_pack_candidate_source_ref_diagnostics,
    _restore_exact_source_sibling_answer_evidence_items,
    _source_sibling_answer_continuation_hydration_request_items,
    _source_sibling_answer_evidence_stage_diagnostics,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank as _country_destination_answer_support_rank,
)
from infinity_context_core.application.context_source_siblings import (
    _SourceSiblingRank,
)
from infinity_context_core.application.context_source_siblings import (
    is_dialogue_visual_reference_source_sibling as _is_dialogue_visual_reference_source_sibling,
)
from infinity_context_core.application.context_source_siblings import (
    is_pottery_type_evidence_text as _is_pottery_type_evidence_text,
)
from infinity_context_core.application.context_source_siblings import (
    is_pottery_type_observation_companion as _is_pottery_type_observation_companion,
)
from infinity_context_core.application.context_source_siblings import (
    is_pottery_type_retrieval_scope as _is_pottery_type_retrieval_scope,
)
from infinity_context_core.application.context_source_siblings import (
    is_precise_source_sibling_turn as _is_precise_source_sibling_turn,
)
from infinity_context_core.application.context_source_siblings import (
    is_same_document_answer_companion as _is_same_document_answer_companion,
)
from infinity_context_core.application.context_source_siblings import (
    is_visual_continuation_source_sibling as _is_visual_continuation_source_sibling,
)
from infinity_context_core.application.context_source_siblings import (
    source_group_seed_turns as _source_group_seed_turns,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence as _source_sibling_answer_evidence,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence_role_rank as _source_sibling_answer_evidence_role_rank,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_candidate_limit as _source_sibling_candidate_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_candidate_rank_key as _source_sibling_candidate_rank_key,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_companion_extra_item_limit as _source_sibling_companion_extra_item_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_companion_extra_slot as _source_sibling_companion_extra_slot,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_distant_answer_evidence_rank as _source_sibling_distant_answer_evidence_rank,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_group_limit as _source_sibling_group_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_item_limit as _source_sibling_item_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_marker_coverage_count as _source_sibling_marker_coverage_count,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_max_candidate_limit as _source_sibling_max_candidate_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_rank as _source_sibling_rank,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_related_turn_anchor_evidence as _related_turn_anchor_evidence,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_relevance_allowed as _source_sibling_relevance_allowed,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_score as _source_sibling_score,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_score_cap as _source_sibling_score_cap,
)
from infinity_context_core.application.context_source_siblings import (
    source_turn_marker as _source_turn_marker,
)
from infinity_context_core.application.context_source_siblings import (
    with_source_sibling_score_signals as _with_source_sibling_score_signals,
)
from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import (
    BuildContextQuery,
    ConsistencyMode,
    ContextBundle,
    ContextItem,
)
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.application.temporal_validity import is_temporal_window_current
from infinity_context_core.domain.entities import (
    DataClassification,
    LifecycleStatus,
    MemoryAnchor,
    MemoryChunk,
    MemoryFact,
    MemoryFactRelation,
)
from infinity_context_core.ports.adapters import EmbeddingPort, GraphMemoryPort, VectorMemoryPort
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.capabilities import RagRecallPort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_KEYWORD_NEIGHBOR_SEQUENCE_OFFSETS = (1, -1, 2, -2, 3, -3)
_MAX_AGGREGATION_KEYWORD_ITEMS = 20
_MAX_EXACT_SOURCE_SIBLING_ANSWER_EVIDENCE_REPAIRS = 48
_STRICT_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_QUESTION_OR_REQUEST_TURN_RE = re.compile(
    r"\?|"
    r"\b(?:who|what|where|when|why|how|which)\b|"
    r"\b(?:can|could|would|will|do|does|did|is|are|was|were|have|has|had)\s+"
    r"(?:you|they|these|those|it|that|he|she|we|i)\b|"
    r"\b(?:tell\s+me|show\s+me|let\s+me\s+know|any\s+"
    r"(?:pointers?|recommendations?|suggestions?))\b",
    re.IGNORECASE,
)
_COUNT_AGGREGATION_QUERY_RE = re.compile(
    r"\b(how many|number of|count|total)\b",
    re.IGNORECASE,
)
_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+"
    r"(?:[\w+.-]+\s+){0,4}"
    r"(?:areas?|causes?|cities|countries|events?|activities?|hobbies|"
    r"instruments?|items?|martial\s+arts|people|places?|shelters?|states?|"
    r"traits?|books?|songs?|artists?|bands?|foods?|desserts?|pets?|projects?|tasks?|"
    r"types?|kinds?)\b|"
    r"\b(?:list|name|show)\b(?=.{0,100}\b(?:all|both|areas?|causes?|cities|"
    r"countries|events?|activities?|hobbies|instruments?|items?|martial\s+arts|"
    r"people|places?|shelters?|states?|traits?|books?|songs?|artists?|bands?|"
    r"foods?|desserts?|pets?|projects?|tasks?|types?|kinds?)\b)|"
    r"\b(?:all|both)\b(?=.{0,100}\b(?:areas?|causes?|cities|countries|events?|"
    r"activities?|hobbies|instruments?|items?|martial\s+arts|people|places?|"
    r"shelters?|states?|traits?|books?|songs?|artists?|bands?|foods?|desserts?|"
    r"pets?|projects?|tasks?|types?|kinds?)\b)|"
    r"\bwho\b(?=.{0,120}\b(?:friends?|people|person|volunteer(?:s|ed|ing)?|"
    r"met|helped|worked\s+with|customers?|clients?|colleagues?|teammates?)\b)|"
    r"\b(?:has|have|did|does)\s+\w{2,40}\s+"
    r"(?:bought|attended|joined|visited|played|shared|mentioned|done|used)\b|"
    r"\b(?:какие|какие\s+именно|что\s+за)\s+"
    r"(?:вещи|события|активности|занятия|инструменты|черты|места|книги|задачи)\b",
    re.IGNORECASE,
)
_WHERE_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\bwhere\b(?=.{0,100}\b(?:been|friend|friends|go|gone|made|meet|met|"
    r"vacation(?:ed)?|visited|went)\b)|"
    r"\bгде\b(?=.{0,100}\b(?:друз|ездил|ездила|ездили|посещал|посещала|"
    r"посещали|познакомил|познакомила|познакомили)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EN_PLACE_LIST_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|states?|places?|locations?|"
    r"destinations?|areas?)\b",
    re.IGNORECASE,
)
_EN_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:would|enjoy|enjoys?|prefer|prefers?|favorite|favourite|"
    r"related|recommend|interested)\b",
    re.IGNORECASE,
)
_EN_NAMED_ENTITY_PHRASE_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9'-]+(?:[-\s]+[A-Z][A-Za-z0-9'-]+)+\b"
)
_MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS = 80
_MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS = 16
_MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS = 8
_MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS = 8
_MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS = 4
_LIST_SOURCE_SIBLING_GROUP_LIMIT = 32
_LIST_SOURCE_SIBLING_ITEM_LIMIT = 48
_LIST_SOURCE_SIBLING_GROUP_BACKFILL_LIMIT = 96
_EXTRA_INVENTORY_PROMPT_REASONS = frozenset(
    {
        "decomposition_inventory_list",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "travel_country_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
        "volunteering_people_inventory_bridge",
        "volunteering_inventory_bridge",
    }
)
_LIST_SOURCE_SIBLING_DEEP_REASONS = _EXTRA_INVENTORY_PROMPT_REASONS | frozenset(
    {
        "activity_aggregation_bridge",
        "book_reading_list_bridge",
        "church_friend_activity_inventory_bridge",
        "decomposition_activity_participation",
        "event_participation_bridge",
        "exercise_activity_inventory_bridge",
        "music_artist_answer_bridge",
        "music_artist_band_bridge",
        "outdoor_activity_inventory_bridge",
    }
)
_ScoredKeywordPromptItem = tuple[int, int, int, float, float, int, str, ContextItem]
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})


@dataclass(frozen=True)
class _ExactTurnHydrationRequestPlan:
    reason_by_id: Mapping[str, str]
    next_answer_source_ids: frozenset[str]
    previous_question_source_ids: frozenset[str]


@dataclass(frozen=True)
class _KeywordAggregationCandidate:
    rank_key: tuple[int, int, int, float, int]
    group: str
    chunk: MemoryChunk
    chunk_text: str
    relevance: QueryRelevance
    strict_hits: int
    aggregation_query: str
    aggregation_reason: str
    query_variant_sets: _WeightedAggregationQueryVariants





class BuildContextUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        ids: IdGeneratorPort,
        vector_index: VectorMemoryPort,
        graph_index: GraphMemoryPort,
        embedder: EmbeddingPort,
        clock: ClockPort | None = None,
        rag_recall: RagRecallPort | None = None,
        packer: ContextPacker | None = None,
        blob_storage: BlobStoragePort | None = None,
        retrieval_deadlines: ContextRetrievalDeadlines | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._vector_index = vector_index
        self._graph_index = graph_index
        self._embedder = embedder
        self._clock = clock
        self._packer = packer or ContextPacker()
        self._hydrator = ContextHydrator(uow_factory=uow_factory, clock=clock)
        self._retrieval_deadlines = retrieval_deadlines or ContextRetrievalDeadlines()
        self._canonical_collector = CanonicalContextCollector(uow_factory=uow_factory)
        self._vector_collector = VectorContextCollector(
            vector_index=vector_index,
            embedder=embedder,
            hydrator=self._hydrator,
            deadlines=self._retrieval_deadlines,
        )
        self._graph_collector = GraphContextCollector(
            graph_index=graph_index,
            hydrator=self._hydrator,
            deadlines=self._retrieval_deadlines,
        )
        self._rag_collector = RagContextCollector(
            rag_recall=rag_recall,
            hydrator=self._hydrator,
            deadlines=self._retrieval_deadlines,
        )
        self._context_link_expander = ApprovedContextLinkExpander(
            uow_factory=uow_factory,
            hydrator=self._hydrator,
            clock=clock,
            blob_storage=blob_storage,
        )
        self._artifact_evidence_collector = ArtifactEvidenceContextCollector(
            uow_factory=uow_factory,
            blob_storage=blob_storage,
        )

    async def execute(self, query: BuildContextQuery) -> ContextBundle:
        request_started_at = perf_counter()
        memory_scope_ids = tuple(str(memory_scope_id) for memory_scope_id in query.memory_scope_ids)
        query_anchor_intent = build_query_anchor_intent(query.query)
        temporal_query_intent = build_temporal_query_intent(query.query)
        query_decomposition_plan = build_query_decomposition_plan(
            query.query,
            anchor_intent=query_anchor_intent,
            temporal_intent=temporal_query_intent,
        )
        query_expansion_plan = build_query_expansion_plan(
            query.query,
            decomposition_plan=query_decomposition_plan,
        )
        canonical_started_at = perf_counter()
        canonical = await self._canonical_collector.collect(
            query=query,
            memory_scope_ids=memory_scope_ids,
            keyword_query_plan=query_expansion_plan,
            anchor_lookup_keys=tuple(
                (key.kind.value, key.normalized_key)
                for key in query_anchor_lookup_keys(query_anchor_intent)
            ),
        )

        diagnostics: dict[str, object] = {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "consistency_mode": query.consistency_mode.value,
            "facts_considered": len(canonical.facts),
            "keyword_chunks_considered": len(canonical.keyword_chunks),
            "keyword_query_count": canonical.keyword_query_count,
            "keyword_query_reasons": list(canonical.keyword_query_reasons),
            "keyword_chunks_dropped_by_relevance": 0,
            "keyword_neighbor_chunks_considered": 0,
            "keyword_neighbor_chunks_used": 0,
            "keyword_neighbor_chunks_skipped": 0,
            "keyword_source_sibling_chunks_considered": 0,
            "keyword_source_sibling_chunks_used": 0,
            "keyword_source_sibling_chunks_skipped": 0,
            "keyword_source_sibling_group_count": 0,
            "keyword_source_sibling_candidate_limit": 0,
            "keyword_aggregation_chunks_considered": 0,
            "keyword_aggregation_chunks_used": 0,
            "keyword_aggregation_chunks_skipped": 0,
            "keyword_aggregation_query_kind": "",
            "keyword_aggregation_relaxed_relevance_used": 0,
            "stage_timings_ms": {},
            "anchors_considered": len(canonical.anchors),
            "anchor_lookup_keys_considered": canonical.anchor_lookup_keys_considered,
            "anchors_loaded_by_lookup": canonical.anchors_loaded_by_lookup,
            "anchors_used": 0,
            "anchors_used_by_query_intent": 0,
            "anchors_dropped_by_query_intent_conflict": 0,
            "anchor_relation_candidates_considered": 0,
            "anchor_relation_items_used": 0,
            "vector_status": "disabled",
            "graph_status": "disabled",
            "rag_status": "disabled",
            "artifact_evidence_status": "unknown",
            "vector_candidate_count": 0,
            "vector_hydrated_count": 0,
            "graph_candidate_count": 0,
            "graph_hydrated_count": 0,
            "artifact_evidence_jobs_considered": 0,
            "artifact_evidence_manifests_considered": 0,
            "artifact_evidence_manifests_used": 0,
            "artifact_evidence_items_considered": 0,
            "artifact_evidence_items_used": 0,
            "artifact_evidence_query_drop_count": 0,
            "artifact_evidence_sensitive_drop_count": 0,
            "artifact_evidence_prompt_injection_drop_count": 0,
            "artifact_evidence_manifest_too_large_count": 0,
            "artifact_evidence_read_error_count": 0,
            "artifact_evidence_parse_error_count": 0,
            "artifact_evidence_schema_skip_count": 0,
            "artifact_evidence_stale_asset_drop_count": 0,
            "stale_vector_drop_count": 0,
            "stale_graph_drop_count": 0,
            "stale_rag_drop_count": 0,
            "include_superseded": query.include_superseded,
            "include_stale": query.include_stale,
            "stale_facts_considered": 0,
            "stale_facts_used": 0,
            "superseded_facts_considered": 0,
            "superseded_facts_used": 0,
            "pending_duplicate_merge_suggestions_considered": 0,
        }
        _record_stage_timing(diagnostics, "canonical_collect", canonical_started_at)
        if query.consistency_mode == ConsistencyMode.CANONICAL_ONLY:
            diagnostics["vector_status"] = "skipped"
            diagnostics["vector_skip_reason"] = "canonical_only"
            diagnostics["graph_status"] = "skipped"
            diagnostics["graph_skip_reason"] = "canonical_only"
            diagnostics["rag_status"] = "skipped"
            diagnostics["rag_skip_reason"] = "canonical_only"
            vector_chunks = ()
            graph_items = ()
            rag_items = ()
        else:
            stage_started_at = perf_counter()
            vector_chunks = await self._vector_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
                query_plan=query_expansion_plan,
            )
            _record_stage_timing(diagnostics, "vector_collect", stage_started_at)
            stage_started_at = perf_counter()
            graph_items = await self._graph_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
                query_plan=query_expansion_plan,
            )
            _record_stage_timing(diagnostics, "graph_collect", stage_started_at)
            stage_started_at = perf_counter()
            rag_items = await self._rag_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
                query_plan=query_expansion_plan,
            )
            _record_stage_timing(diagnostics, "rag_collect", stage_started_at)

        items: list[ContextItem] = []
        now = self._clock.now() if self._clock is not None else None
        diagnostics.update(query_anchor_intent.diagnostics())
        diagnostics.update(query_expansion_plan.diagnostics())
        diagnostics.update(temporal_query_intent.diagnostics())
        for fact in canonical.facts:
            if not is_context_fact_visible(
                fact,
                query=query,
                memory_scope_ids=memory_scope_ids,
                now=now,
            ):
                continue
            items.append(_fact_context_item(fact, now=now, query_text=query.query))
        anchors_used = 0
        anchors_used_by_query_intent = 0
        anchors_dropped_by_query_intent_conflict = 0
        selected_anchor_items: list[tuple[MemoryAnchor, ContextItem]] = []
        for anchor in canonical.anchors:
            if not is_context_anchor_visible(
                anchor,
                query=query,
                memory_scope_ids=memory_scope_ids,
                now=now,
            ):
                continue
            if has_project_identity_mismatch(
                query=query.query,
                text=anchor_retrieval_text(anchor),
            ):
                continue
            if query_anchor_intent_conflicts(query_anchor_intent, anchor):
                anchors_dropped_by_query_intent_conflict += 1
                continue
            query_anchor_match = match_query_anchor_intent(query_anchor_intent, anchor)
            relevance = score_query_relevance(
                query=query.query,
                text=anchor_retrieval_text(anchor),
            )
            if query_anchor_match is None and not is_query_relevance_sufficient(relevance):
                continue
            identity_relevance = score_query_relevance(
                query=query.query,
                text=anchor_identity_retrieval_text(anchor),
            )
            anchor_item = anchor_context_item(
                anchor,
                relevance=relevance,
                identity_relevance=identity_relevance,
                now=now,
                query_anchor_match=query_anchor_match,
            )
            items.append(anchor_item)
            selected_anchor_items.append((anchor, anchor_item))
            anchors_used += 1
            if query_anchor_match is not None:
                anchors_used_by_query_intent += 1
        diagnostics["anchors_used"] = anchors_used
        diagnostics["anchors_used_by_query_intent"] = anchors_used_by_query_intent
        diagnostics["anchors_dropped_by_query_intent_conflict"] = (
            anchors_dropped_by_query_intent_conflict
        )
        related_anchor_items, related_anchor_candidates = related_anchor_context_items(
            anchors=canonical.anchors,
            selected_anchor_items=tuple(selected_anchor_items),
            query=query,
            memory_scope_ids=memory_scope_ids,
            now=now,
        )
        diagnostics["anchor_relation_candidates_considered"] = related_anchor_candidates
        diagnostics["anchor_relation_items_used"] = len(related_anchor_items)
        items.extend(related_anchor_items)
        query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] = {}
        strict_query_term_variants = _strict_query_term_variant_sets(query=query.query)
        used_keyword_chunks: list[MemoryChunk] = []
        sibling_anchor_chunks: list[MemoryChunk] = []
        scored_keyword_chunks: list[tuple[int, int, int, float, float, int, MemoryChunk]] = []
        scored_keyword_items: list[_ScoredKeywordPromptItem] = []
        stage_started_at = perf_counter()
        for chunk in canonical.keyword_chunks:
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            if has_project_identity_mismatch(query=query.query, text=chunk_text):
                diagnostics["keyword_chunks_dropped_by_relevance"] = (
                    int(diagnostics["keyword_chunks_dropped_by_relevance"]) + 1
                )
                continue
            expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
                query_expansion_plan,
                text=chunk_text,
                cache=query_relevance_cache,
            )
            if query_anchor_intent_text_conflicts(
                query_anchor_intent,
                chunk_text,
            ) and not _keyword_anchor_conflict_allowed(
                expansion_reason=expansion_reason,
                relevance=relevance,
                text=chunk_text,
            ):
                diagnostics["keyword_chunks_dropped_by_relevance"] = (
                    int(diagnostics["keyword_chunks_dropped_by_relevance"]) + 1
                )
                continue
            if not is_chunk_candidate_relevance_sufficient(
                query=expansion_query,
                text=chunk_text,
                relevance=relevance,
            ):
                if (
                    _related_turn_anchor_evidence(relevance=relevance, text=chunk_text)
                    or _source_sibling_answer_evidence_query_match(
                    query_plan=query_expansion_plan,
                    text=chunk_text,
                    preferred_query=expansion_query,
                    preferred_reason=expansion_reason,
                    )
                    is not None
                ):
                    sibling_anchor_chunks.append(chunk)
                diagnostics["keyword_chunks_dropped_by_relevance"] = (
                    int(diagnostics["keyword_chunks_dropped_by_relevance"]) + 1
                )
                continue
            score = keyword_chunk_score(
                relevance,
                query_expansion_reason=expansion_reason,
            )
            source_score_boost = 0.0
            score, source_score_boost = apply_keyword_chunk_source_score_boost(
                score,
                relevance,
                query_expansion_reason=expansion_reason,
                source_external_id=chunk.source_external_id,
            )
            strict_query_hits = _strict_query_variant_hits(
                query_term_variants=strict_query_term_variants,
                text=chunk_text,
            )
            used_keyword_chunks.append(chunk)
            scored_keyword_chunks.append(
                (
                    strict_query_hits,
                    relevance.distinctive_term_hits,
                    relevance.unique_term_hits,
                    relevance.hit_ratio,
                    score,
                    len(scored_keyword_chunks),
                    chunk,
                )
            )
            keyword_item = _chunk_context_item(
                chunk=chunk,
                text=chunk_text,
                retrieval_source="keyword_chunks",
                base_score=0.75,
                score=score,
                relevance=relevance,
                query_text=expansion_query,
                query_expansion_reason=expansion_reason,
                keyword_source_score_boost=source_score_boost,
            )
            scored_keyword_items.append(
                (
                    strict_query_hits,
                    relevance.distinctive_term_hits,
                    relevance.unique_term_hits,
                    relevance.hit_ratio,
                    score,
                    len(scored_keyword_items),
                    expansion_reason,
                    keyword_item,
                )
            )
        items.extend(_selected_keyword_prompt_items(scored_keyword_items, limit=query.max_chunks))
        _record_stage_timing(diagnostics, "keyword_chunk_rank", stage_started_at)
        stage_started_at = perf_counter()
        aggregation_items, aggregation_diagnostics = _keyword_aggregation_chunk_items(
            query=query,
            query_plan=query_expansion_plan,
            seed_chunks=tuple(used_keyword_chunks),
            query_relevance_cache=query_relevance_cache,
        )
        _record_stage_timing(diagnostics, "keyword_aggregation", stage_started_at)
        diagnostics.update(aggregation_diagnostics)
        items.extend(aggregation_items)
        aggregation_source_groups = _context_item_aggregation_source_groups(aggregation_items)
        stage_started_at = perf_counter()
        neighbor_items, neighbor_diagnostics = await self._keyword_neighbor_chunk_items(
            query=query,
            query_plan=query_expansion_plan,
            memory_scope_ids=memory_scope_ids,
            seed_chunks=tuple(used_keyword_chunks),
            query_relevance_cache=query_relevance_cache,
        )
        _record_stage_timing(diagnostics, "keyword_neighbors", stage_started_at)
        diagnostics.update(neighbor_diagnostics)
        items.extend(neighbor_items)
        ranked_keyword_chunks = tuple(
            chunk
            for _, _, _, _, _, _, chunk in _ranked_keyword_chunk_scores(scored_keyword_chunks)
        )
        sibling_seed_chunks = _dedupe_chunks_by_id(
            (
                *sibling_anchor_chunks,
                *_prioritized_chunks_for_source_groups(
                    tuple(used_keyword_chunks),
                    source_groups=aggregation_source_groups,
                ),
                *ranked_keyword_chunks,
                *used_keyword_chunks,
            )
        )
        stage_started_at = perf_counter()
        sibling_items, sibling_diagnostics = await self._keyword_source_sibling_chunk_items(
            query=query,
            query_plan=query_expansion_plan,
            memory_scope_ids=memory_scope_ids,
            seed_chunks=sibling_seed_chunks,
            query_relevance_cache=query_relevance_cache,
        )
        _record_stage_timing(diagnostics, "keyword_source_siblings", stage_started_at)
        diagnostics.update(sibling_diagnostics)
        items.extend(sibling_items)
        stage_started_at = perf_counter()
        exact_source_ref_items, exact_source_ref_diagnostics = (
            await self._exact_source_ref_hydration_items(
                query=query,
                query_plan=query_expansion_plan,
                memory_scope_ids=memory_scope_ids,
                source_items=tuple(items),
                query_relevance_cache=query_relevance_cache,
            )
        )
        _record_stage_timing(diagnostics, "exact_source_ref_hydration", stage_started_at)
        diagnostics.update(exact_source_ref_diagnostics)
        items.extend(exact_source_ref_items)
        for chunk in vector_chunks:
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            items.append(
                _chunk_context_item(
                    chunk=chunk,
                    text=chunk_text,
                    retrieval_source="vector_chunks",
                    base_score=0.82,
                    score=0.82,
                    relevance=None,
                    query_text=query.query,
                )
            )
        items.extend(graph_items)
        items.extend(rag_items)

        bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] = {}
        stage_started_at = perf_counter()
        deduped = await self._hydrator.revalidate_visible_items(
            dedupe_rank_items(
                apply_rank_fusion_boosts(
                    apply_query_plan_bm25_lexical_boosts(
                        tuple(items),
                        plan=query_expansion_plan,
                        bm25_text_stats_cache=bm25_text_stats_cache,
                    )
                )
            ),
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        _record_stage_timing(diagnostics, "dedupe_hydrate", stage_started_at)
        diagnostics.update(
            _source_sibling_answer_evidence_stage_diagnostics(
                "post_dedupe_hydrate",
                deduped,
            )
        )
        stage_started_at = perf_counter()
        temporal_items, temporal_diagnostics = await self._apply_temporal_relation_signals(
            items=deduped,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        _record_stage_timing(diagnostics, "temporal_relations", stage_started_at)
        stage_started_at = perf_counter()
        artifact_evidence_items = await self._artifact_evidence_collector.collect(
            query=query,
            memory_scope_ids=memory_scope_ids,
            diagnostics=diagnostics,
            query_expansion_plan=query_expansion_plan,
        )
        _record_stage_timing(diagnostics, "artifact_evidence", stage_started_at)
        include_stale_review = (
            query.include_stale
            or query.include_superseded
            or temporal_query_intent.include_superseded_review
        )
        stage_started_at = perf_counter()
        stale_review_items, stale_diagnostics = (
            await self._stale_review_items(
                query=query,
                memory_scope_ids=memory_scope_ids,
            )
            if include_stale_review
            else (
                (),
                {
                    "stale_facts_considered": 0,
                    "stale_facts_used": 0,
                    "superseded_facts_considered": 0,
                    "superseded_facts_used": 0,
                },
            )
        )
        _record_stage_timing(diagnostics, "stale_review", stage_started_at)
        stage_started_at = perf_counter()
        pending_review_items = await self._pending_conflict_items(
            query=query,
            visible_fact_ids=tuple(
                item.item_id for item in temporal_items if item.item_type == "fact"
            ),
        )
        _record_stage_timing(diagnostics, "pending_review", stage_started_at)
        stage_started_at = perf_counter()
        linked_context = await self._context_link_expander.collect(
            items=(*temporal_items, *artifact_evidence_items),
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        _record_stage_timing(diagnostics, "context_links", stage_started_at)
        stage_started_at = perf_counter()
        (
            linked_temporal_items,
            linked_temporal_diagnostics,
        ) = await self._apply_temporal_relation_signals(
            items=linked_context.items,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        _record_stage_timing(diagnostics, "linked_temporal_relations", stage_started_at)
        final_rank_started_at = perf_counter()
        stage_started_at = perf_counter()
        final_source_items = (
            *temporal_items,
            *artifact_evidence_items,
            *linked_temporal_items,
            *stale_review_items,
            *pending_review_items,
        )
        diagnostics["final_rank_source_item_count"] = len(final_source_items)
        diagnostics.update(
            _source_sibling_answer_evidence_stage_diagnostics(
                "final_source",
                final_source_items,
            )
        )
        _record_stage_timing(diagnostics, "final_rank_source_merge", stage_started_at)
        stage_started_at = perf_counter()
        temporally_boosted_items = apply_temporal_query_intent_boosts(
            final_source_items,
            intent=temporal_query_intent,
        )
        _record_stage_timing(diagnostics, "final_rank_temporal_boost", stage_started_at)
        stage_started_at = perf_counter()
        anchor_boosted_items = apply_query_anchor_intent_boosts(
            temporally_boosted_items,
            intent=query_anchor_intent,
        )
        _record_stage_timing(diagnostics, "final_rank_anchor_boost", stage_started_at)
        stage_started_at = perf_counter()
        requirement_boosted_items = apply_context_requirement_boosts(
            anchor_boosted_items,
            query=query.query,
            query_anchor_intent=query_anchor_intent,
        )
        _record_stage_timing(diagnostics, "final_rank_requirement_boost", stage_started_at)
        stage_started_at = perf_counter()
        lexical_boosted_items = apply_query_plan_bm25_lexical_boosts(
            requirement_boosted_items,
            plan=query_expansion_plan,
            bm25_text_stats_cache=bm25_text_stats_cache,
        )
        _record_stage_timing(diagnostics, "final_rank_bm25", stage_started_at)
        stage_started_at = perf_counter()
        fused_items = apply_rank_fusion_boosts(lexical_boosted_items)
        _record_stage_timing(diagnostics, "final_rank_fusion", stage_started_at)
        stage_started_at = perf_counter()
        reranked_items = apply_deterministic_rerank_adjustments(
            fused_items,
            query=query.query,
            plan=query_expansion_plan,
            query_anchor_intent=query_anchor_intent,
            query_relevance_cache=query_relevance_cache,
        )
        _record_stage_timing(diagnostics, "final_rank_deterministic", stage_started_at)
        stage_started_at = perf_counter()
        candidate_items = dedupe_rank_items(reranked_items)
        candidate_items, answer_evidence_repair_diagnostics = (
            _restore_exact_source_sibling_answer_evidence_items(
                candidates=candidate_items,
                source_items=final_source_items,
            )
        )
        diagnostics.update(answer_evidence_repair_diagnostics)
        candidate_items = _trim_primary_fact_items(
            candidate_items,
            max_facts=query.max_facts,
        )
        diagnostics["final_rank_candidate_item_count"] = len(candidate_items)
        diagnostics.update(
            _source_sibling_answer_evidence_stage_diagnostics(
                "final_candidate",
                candidate_items,
            )
        )
        _record_stage_timing(diagnostics, "final_rank_dedupe", stage_started_at)
        _record_stage_timing(diagnostics, "final_rank", final_rank_started_at)
        guarded_items, requirement_guard_diagnostics = (
            _apply_explicit_requirement_guard(
                query=query.query,
                query_anchor_intent=query_anchor_intent,
                items=candidate_items,
            )
        )
        diagnostics.update(requirement_guard_diagnostics)
        diagnostics.update(
            _source_sibling_answer_evidence_stage_diagnostics(
                "guarded",
                guarded_items,
            )
        )
        diagnostics.update(_pre_pack_candidate_source_ref_diagnostics(guarded_items))
        stage_started_at = perf_counter()
        result = self._packer.pack(
            bundle_id=self._ids.new_id("ctx"),
            items=guarded_items,
            token_budget=query.token_budget,
            query=query.query,
            max_rendered_chars=query.max_rendered_chars,
        )
        _record_stage_timing(diagnostics, "pack", stage_started_at)
        diagnostics.update(temporal_diagnostics)
        diagnostics.update(stale_diagnostics)
        diagnostics.update(linked_context.diagnostics)
        diagnostics.update(
            {f"linked_{key}": value for key, value in linked_temporal_diagnostics.items()}
        )
        diagnostics.update(result.bundle.diagnostics)
        diagnostics["pending_conflict_suggestions_considered"] = sum(
            1
            for item in pending_review_items
            if (item.diagnostics or {}).get("retrieval_source") == "pending_conflict_suggestion"
        )
        diagnostics["pending_duplicate_merge_suggestions_considered"] = sum(
            1
            for item in pending_review_items
            if (item.diagnostics or {}).get("retrieval_source")
            == "pending_duplicate_merge_suggestion"
        )
        diagnostics["hybrid_items_used"] = sum(
            1
            for item in result.bundle.items
            if len((item.diagnostics or {}).get("retrieval_sources") or ()) > 1
        )
        diagnostics["context_requirement_coverage"] = context_requirement_coverage(
            query=query.query,
            query_anchor_intent=query_anchor_intent,
            items=result.bundle.items,
        )
        _record_stage_timing(diagnostics, "total", request_started_at)
        bundle_diagnostics = normalize_context_bundle_diagnostics(
            diagnostics,
            items=result.bundle.items,
        )
        return ContextBundle(
            bundle_id=result.bundle.bundle_id,
            rendered_text=result.bundle.rendered_text,
            items=result.bundle.items,
            token_estimate=result.bundle.token_estimate,
            diagnostics=bundle_diagnostics,
        )

    async def _keyword_neighbor_chunk_items(
        self,
        *,
        query: BuildContextQuery,
        query_plan: QueryExpansionPlan,
        memory_scope_ids: tuple[str, ...],
        seed_chunks: tuple[MemoryChunk, ...],
        query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        if query.max_chunks <= 0 or not seed_chunks:
            return (
                (),
                {
                    "keyword_neighbor_chunks_considered": 0,
                    "keyword_neighbor_chunks_used": 0,
                    "keyword_neighbor_chunks_skipped": 0,
                    "keyword_neighbor_answer_companion_extra_used": 0,
                },
            )

        seed_ids = {str(chunk.id) for chunk in seed_chunks}
        document_ids = tuple(
            dict.fromkeys(str(chunk.document_id) for chunk in seed_chunks if chunk.document_id)
        )
        if not document_ids:
            return (
                (),
                {
                    "keyword_neighbor_chunks_considered": 0,
                    "keyword_neighbor_chunks_used": 0,
                    "keyword_neighbor_chunks_skipped": 0,
                    "keyword_neighbor_answer_companion_extra_used": 0,
                },
            )

        max_neighbor_items = min(8, max(2, query.max_chunks // 3))
        items: list[ContextItem] = []
        used_neighbor_ids: set[str] = set()
        answer_companion_slots: set[str] = set()
        answer_companion_extra_used = 0
        considered = 0
        skipped = 0
        async with self._uow_factory() as uow:
            for document_id in document_ids:
                chunks = await uow.documents.list_chunks(document_id, limit=400)
                by_sequence = {chunk.sequence: chunk for chunk in chunks}
                seed_sequences = tuple(
                    chunk.sequence
                    for chunk in seed_chunks
                    if chunk.document_id is not None and str(chunk.document_id) == document_id
                )
                for sequence in seed_sequences:
                    for offset in _KEYWORD_NEIGHBOR_SEQUENCE_OFFSETS:
                        neighbor_sequence = sequence + offset
                        neighbor = by_sequence.get(neighbor_sequence)
                        if neighbor is None:
                            continue
                        neighbor_id = str(neighbor.id)
                        if neighbor_id in seed_ids or neighbor_id in used_neighbor_ids:
                            continue
                        considered += 1
                        if not _is_neighbor_chunk_visible(
                            neighbor,
                            query=query,
                            memory_scope_ids=memory_scope_ids,
                        ):
                            skipped += 1
                            continue
                        used_neighbor_ids.add(neighbor_id)
                        chunk_text = document_chunk_retrieval_text(
                            text=neighbor.text,
                            metadata=neighbor.metadata,
                        )
                        expansion_query, expansion_reason, relevance = (
                            _best_query_relevance_cached(
                                query_plan,
                                text=chunk_text,
                                cache=query_relevance_cache,
                            )
                        )
                        if _is_pottery_type_retrieval_scope(
                            expansion_reason=expansion_reason,
                            expansion_query=expansion_query,
                        ) and not _is_pottery_type_evidence_text(chunk_text):
                            skipped += 1
                            continue
                        answer_companion_slot = ""
                        if _is_same_document_answer_companion(
                            chunk=neighbor,
                            expansion_reason=expansion_reason,
                            text=chunk_text,
                        ):
                            answer_companion_slot = _source_sibling_companion_extra_slot(
                                chunk=neighbor,
                                text=chunk_text,
                            )
                        use_answer_companion_extra = (
                            bool(answer_companion_slot)
                            and answer_companion_slot not in answer_companion_slots
                            and answer_companion_extra_used
                            < _source_sibling_companion_extra_item_limit()
                        )
                        if len(items) >= max_neighbor_items and not use_answer_companion_extra:
                            skipped += 1
                            continue
                        if use_answer_companion_extra:
                            answer_companion_slots.add(answer_companion_slot)
                            answer_companion_extra_used += 1
                            item_score = 0.982
                            item_relevance: QueryRelevance | None = relevance
                            item_query = expansion_query
                            item_reason = expansion_reason
                        else:
                            item_score = 0.68
                            item_relevance = None
                            item_query = query.query
                            item_reason = "original_query"
                        items.append(
                            _chunk_context_item(
                                chunk=neighbor,
                                text=chunk_text,
                                retrieval_source="keyword_neighbor_chunks",
                                base_score=0.68,
                                score=item_score,
                                relevance=item_relevance,
                                query_text=item_query,
                                query_expansion_reason=item_reason,
                            )
                        )

        return tuple(items), {
            "keyword_neighbor_chunks_considered": considered,
            "keyword_neighbor_chunks_used": len(items),
            "keyword_neighbor_chunks_skipped": skipped,
            "keyword_neighbor_answer_companion_extra_used": answer_companion_extra_used,
        }

    async def _keyword_source_sibling_chunk_items(
        self,
        *,
        query: BuildContextQuery,
        query_plan: QueryExpansionPlan,
        memory_scope_ids: tuple[str, ...],
        seed_chunks: tuple[MemoryChunk, ...],
        query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        empty_diagnostics = {
            "keyword_source_sibling_chunks_considered": 0,
            "keyword_source_sibling_chunks_used": 0,
            "keyword_source_sibling_chunks_skipped": 0,
            "keyword_source_sibling_group_count": 0,
            "keyword_source_sibling_candidate_limit": 0,
            "keyword_source_sibling_companion_extra_used": 0,
            "keyword_source_sibling_named_preference_answer_diversity": False,
            "keyword_source_sibling_group_backfill_limit": 0,
            "keyword_source_sibling_group_backfill_chunks_used": 0,
            "keyword_source_sibling_groups_sample": [],
            "keyword_source_sibling_selected_sources_sample": [],
        }
        if query.max_chunks <= 0 or not seed_chunks:
            return (), empty_diagnostics

        seed_chunks = _prioritize_source_sibling_answer_evidence_seed_chunks(
            seed_chunks=seed_chunks,
            query_plan=query_plan,
            query_relevance_cache=query_relevance_cache,
        )
        source_groups = _source_group_seed_turns(seed_chunks)
        if not source_groups:
            return (), empty_diagnostics
        seed_groups_sample = list(source_groups.keys())[:40]
        deep_list_coverage = _query_plan_requests_list_source_sibling_depth(
            query_text=query.query,
            query_plan=query_plan,
        )
        place_list_answer_diversity = _query_plan_requests_place_source_sibling_diversity(
            query_text=query.query,
            query_plan=query_plan,
        )
        named_preference_answer_diversity = (
            _query_plan_requests_named_preference_source_sibling_diversity(
                query_text=query.query,
                query_plan=query_plan,
            )
        )
        relationship_status_answer_diversity = (
            _query_plan_requests_relationship_status_source_sibling_diversity(
                query_text=query.query,
                query_plan=query_plan,
            )
        )
        answer_evidence_group_diversity = (
            place_list_answer_diversity
            or named_preference_answer_diversity
            or relationship_status_answer_diversity
        )
        source_group_limit = _source_sibling_group_limit_for_request(
            source_group_count=len(source_groups),
            deep_list_coverage=deep_list_coverage,
            answer_evidence_group_diversity=answer_evidence_group_diversity,
        )
        source_groups = _prioritized_source_sibling_seed_groups(
            source_groups=source_groups,
            seed_chunks=seed_chunks,
            query_plan=query_plan,
            query_relevance_cache=query_relevance_cache,
            limit=source_group_limit,
        )
        source_sibling_item_limit = _source_sibling_item_limit()
        if deep_list_coverage:
            source_sibling_item_limit = max(
                source_sibling_item_limit,
                _LIST_SOURCE_SIBLING_ITEM_LIMIT,
            )
        max_items = min(
            source_sibling_item_limit,
            max(8, query.max_chunks * (3 if deep_list_coverage else 2)),
        )
        candidate_limit = _source_sibling_candidate_limit(
            max_items=max_items,
            source_group_count=len(source_groups),
        )
        if answer_evidence_group_diversity:
            candidate_limit = max(candidate_limit, _source_sibling_max_candidate_limit())
        items: list[ContextItem] = []
        used_ids: set[str] = set()
        considered = 0
        skipped = 0
        group_backfill_limit = 0
        group_backfill_chunks_used = 0
        async with self._uow_factory() as uow:
            list_source_group_chunks = getattr(
                uow.chunks,
                "list_by_source_external_id_groups",
                None,
            )
            if list_source_group_chunks is None:
                return (), empty_diagnostics
            candidates = await list_source_group_chunks(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                source_external_id_groups=tuple(source_groups.keys()),
                exclude_chunk_ids=(),
                limit=candidate_limit,
            )
            backfill_groups, group_backfill_limit = _source_sibling_group_backfill_plan(
                deep_list_coverage=answer_evidence_group_diversity,
                source_groups=source_groups,
            )
            if backfill_groups and group_backfill_limit > 0:
                candidate_ids = {str(chunk.id) for chunk in candidates}
                backfill_chunks: list[MemoryChunk] = []
                for group in backfill_groups:
                    group_candidates = await list_source_group_chunks(
                        space_id=str(query.space_id),
                        memory_scope_ids=memory_scope_ids,
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        source_external_id_groups=(group,),
                        exclude_chunk_ids=(),
                        limit=group_backfill_limit,
                    )
                    for chunk in group_candidates:
                        chunk_id = str(chunk.id)
                        if chunk_id in candidate_ids:
                            continue
                        candidate_ids.add(chunk_id)
                        backfill_chunks.append(chunk)
                if backfill_chunks:
                    candidates = [*candidates, *backfill_chunks]
                    group_backfill_chunks_used = len(backfill_chunks)
        ranked_candidates: list[
            tuple[
                tuple[float | int | str, ...],
                str,
                _SourceSiblingRank,
                MemoryChunk,
                str,
                str,
                str,
                QueryRelevance,
                float,
                float | None,
                bool,
                bool,
                bool,
            ]
        ] = []
        for chunk in candidates:
            rank = _source_sibling_rank(chunk, source_groups=source_groups)
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
                query_plan,
                text=chunk_text,
                cache=query_relevance_cache,
            )
            if rank is None:
                rank = _source_sibling_distant_answer_evidence_rank(
                    chunk,
                    source_groups=source_groups,
                    expansion_query=expansion_query,
                    expansion_reason=expansion_reason,
                    text=chunk_text,
                )
                if rank is None:
                    continue
            score = _source_sibling_score(
                rank=rank,
                relevance=relevance,
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            score_cap = _source_sibling_score_cap(
                expansion_reason=expansion_reason,
                relevance=relevance,
                text=chunk_text,
            )
            if not _source_sibling_relevance_allowed(
                rank=rank,
                relevance=relevance,
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            ):
                skipped += 1
                continue
            visual_continuation = _is_visual_continuation_source_sibling(
                rank=rank,
                relevance=relevance,
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            dialogue_visual_reference = _is_dialogue_visual_reference_source_sibling(
                rank=rank,
                relevance=relevance,
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            observation_companion = _is_pottery_type_observation_companion(
                chunk=chunk,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            precise_turn = _is_precise_source_sibling_turn(
                chunk=chunk,
                expansion_reason=expansion_reason,
            )
            marker_coverage = _source_sibling_marker_coverage_count(
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            answer_evidence = _source_sibling_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            answer_evidence_role_rank = _source_sibling_answer_evidence_role_rank(
                query_text=query.query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
            ranked_candidates.append(
                (
                    _source_sibling_candidate_rank_key(
                        precise_turn=precise_turn,
                        dialogue_visual_reference=dialogue_visual_reference,
                        visual_continuation=visual_continuation,
                        observation_companion=observation_companion,
                        answer_evidence=answer_evidence,
                        answer_evidence_role_rank=answer_evidence_role_rank,
                        marker_coverage=marker_coverage,
                        relevance=relevance,
                        score=score,
                        rank=rank,
                        chunk=chunk,
                    ),
                    str(chunk.id),
                    rank,
                    chunk,
                    chunk_text,
                    expansion_query,
                    expansion_reason,
                    relevance,
                    score,
                    score_cap,
                    dialogue_visual_reference,
                    visual_continuation,
                    observation_companion,
                    answer_evidence,
                )
            )
        ranked_candidates.sort(key=lambda item: item[0])
        companion_extra_used = 0
        companion_extra_slots: set[str] = set()
        answer_evidence_extra_used = 0
        answer_evidence_extra_counts: dict[str, int] = {}
        answer_evidence_selected_sources: list[str] = []
        precise_support_extra_used = 0
        precise_support_extra_sources: set[str] = set()
        for (
            _,
            chunk_id,
            rank,
            chunk,
            chunk_text,
            expansion_query,
            expansion_reason,
            relevance,
            score,
            score_cap,
            dialogue_visual_reference,
            visual_continuation,
            observation_companion,
            answer_evidence,
        ) in ranked_candidates:
            companion_slot = ""
            answer_evidence_extra_key = _source_sibling_answer_evidence_extra_key(
                chunk,
                deep_list_coverage=answer_evidence_group_diversity,
            )
            answer_evidence_extra_limit = 24 if answer_evidence_group_diversity else 12
            answer_evidence_extra_key_limit = (
                2 if answer_evidence_group_diversity else 1
            )
            use_companion_extra_slot = False
            use_answer_evidence_extra_slot = False
            use_precise_support_extra_slot = False
            if len(items) >= max_items:
                source_external_id = str(chunk.source_external_id or "")
                use_precise_support_extra_slot = (
                    precise_turn
                    and _is_pottery_type_retrieval_scope(
                        expansion_reason=expansion_reason,
                        expansion_query=expansion_query,
                    )
                    and source_external_id
                    and source_external_id not in precise_support_extra_sources
                    and precise_support_extra_used < 8
                )
                use_answer_evidence_extra_slot = (
                    answer_evidence
                    and answer_evidence_extra_key
                    and answer_evidence_extra_counts.get(answer_evidence_extra_key, 0)
                    < answer_evidence_extra_key_limit
                    and answer_evidence_extra_used < answer_evidence_extra_limit
                )
                if (
                    not observation_companion
                    and not use_answer_evidence_extra_slot
                    and not use_precise_support_extra_slot
                ):
                    continue
                companion_slot = _source_sibling_companion_extra_slot(
                    chunk=chunk,
                    text=chunk_text,
                )
                use_companion_extra_slot = (
                    bool(companion_slot)
                    and companion_slot not in companion_extra_slots
                    and companion_extra_used < _source_sibling_companion_extra_item_limit()
                )
                if (
                    not use_companion_extra_slot
                    and not use_answer_evidence_extra_slot
                    and not use_precise_support_extra_slot
                ):
                    continue
            considered += 1
            if chunk_id in used_ids:
                skipped += 1
                continue
            if not _is_neighbor_chunk_visible(
                chunk,
                query=query,
                memory_scope_ids=memory_scope_ids,
            ):
                skipped += 1
                continue
            used_ids.add(chunk_id)
            if use_companion_extra_slot:
                companion_extra_slots.add(companion_slot)
                companion_extra_used += 1
            if use_answer_evidence_extra_slot:
                answer_evidence_extra_counts[answer_evidence_extra_key] = (
                    answer_evidence_extra_counts.get(answer_evidence_extra_key, 0) + 1
                )
                answer_evidence_extra_used += 1
            if use_precise_support_extra_slot:
                precise_support_extra_sources.add(str(chunk.source_external_id or ""))
                precise_support_extra_used += 1
            if answer_evidence and chunk.source_external_id:
                answer_evidence_selected_sources.append(str(chunk.source_external_id))
            item = _chunk_context_item(
                chunk=chunk,
                text=chunk_text,
                retrieval_source="keyword_source_sibling_chunks",
                base_score=0.74,
                score=score,
                relevance=relevance,
                query_text=expansion_query,
                query_expansion_reason=expansion_reason,
                use_query_snippet=not observation_companion,
            )
            items.append(
                _with_source_sibling_score_signals(
                    item,
                    rank=rank,
                    score_cap=score_cap,
                    dialogue_visual_reference=dialogue_visual_reference,
                    visual_continuation=visual_continuation,
                    answer_evidence=answer_evidence,
                    answer_evidence_query=expansion_query if answer_evidence else "",
                )
            )

        return tuple(items), {
            "keyword_source_sibling_chunks_considered": considered,
            "keyword_source_sibling_chunks_used": len(items),
            "keyword_source_sibling_chunks_skipped": skipped,
            "keyword_source_sibling_group_count": len(source_groups),
            "keyword_source_sibling_candidate_limit": candidate_limit,
            "keyword_source_sibling_deep_list_coverage": deep_list_coverage,
            "keyword_source_sibling_place_list_answer_diversity": (
                place_list_answer_diversity
            ),
            "keyword_source_sibling_named_preference_answer_diversity": (
                named_preference_answer_diversity
            ),
            "keyword_source_sibling_companion_extra_used": companion_extra_used,
            "keyword_source_sibling_group_backfill_limit": group_backfill_limit,
            "keyword_source_sibling_group_backfill_chunks_used": group_backfill_chunks_used,
            "keyword_source_sibling_answer_evidence_extra_used": answer_evidence_extra_used,
            "keyword_source_sibling_precise_support_extra_used": precise_support_extra_used,
            "keyword_source_sibling_answer_evidence_selected_sources_sample": (
                answer_evidence_selected_sources[:40]
            ),
            "keyword_source_sibling_seed_groups_sample": seed_groups_sample,
            "keyword_source_sibling_groups_sample": list(source_groups.keys())[:40],
            "keyword_source_sibling_selected_sources_sample": [
                chunk.source_external_id for _, _, _, chunk, *_ in ranked_candidates[:80]
            ],
        }

    async def _exact_source_ref_hydration_items(
        self,
        *,
        query: BuildContextQuery,
        query_plan: QueryExpansionPlan,
        memory_scope_ids: tuple[str, ...],
        source_items: tuple[ContextItem, ...],
        query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        request_plan = _exact_turn_source_ref_hydration_request_plan(source_items)
        source_reason_by_id = request_plan.reason_by_id
        source_ids = tuple(source_reason_by_id)[:_MAX_EXACT_SOURCE_SIBLING_ANSWER_EVIDENCE_REPAIRS]
        diagnostics: dict[str, object] = {
            "exact_source_ref_hydration_requested": len(source_ids),
            "exact_source_ref_hydration_chunks_found": 0,
            "exact_source_ref_hydration_items_used": 0,
            "exact_source_ref_hydration_sources_sample": list(source_ids[:24]),
        }
        if not source_ids:
            return (), diagnostics
        async with self._uow_factory() as uow:
            list_source_group_chunks = getattr(
                uow.chunks,
                "list_by_source_external_id_groups",
                None,
            )
            if list_source_group_chunks is None:
                return (), diagnostics
            chunks = await list_source_group_chunks(
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
                source_external_id_groups=source_ids,
                exclude_chunk_ids=(),
                limit=max(len(source_ids), 1),
            )
        chunks_by_source_id: dict[str, MemoryChunk] = {}
        for chunk in chunks:
            source_id = str(chunk.source_external_id or "")
            if source_id in source_reason_by_id and source_id not in chunks_by_source_id:
                chunks_by_source_id[source_id] = chunk
        hydrated_items: list[ContextItem] = []
        for source_id in source_ids:
            chunk = chunks_by_source_id.get(source_id)
            if chunk is None:
                continue
            reason = source_reason_by_id[source_id] or "original_query"
            expansion_query = _query_expansion_text_for_reason(
                query_plan,
                reason=reason,
                fallback=query.query,
            )
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            _, _, relevance = _best_query_relevance_cached(
                query_plan,
                text=chunk_text,
                cache=query_relevance_cache,
            )
            answer_evidence = _source_sibling_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=reason,
                text=chunk_text,
            )
            if not _should_use_exact_source_ref_hydration_item(
                source_id=source_id,
                request_plan=request_plan,
                answer_evidence=answer_evidence,
                text=chunk_text,
            ):
                continue
            item = _chunk_context_item(
                chunk=chunk,
                text=chunk_text,
                retrieval_source="keyword_source_sibling_chunks",
                base_score=0.74,
                score=0.99 if answer_evidence else 0.93,
                relevance=relevance,
                query_text=expansion_query,
                query_expansion_reason=reason,
                use_query_snippet=False,
            )
            hydrated_items.append(
                _with_exact_source_ref_hydration_signals(
                    item,
                    answer_evidence=answer_evidence,
                )
            )
        diagnostics["exact_source_ref_hydration_chunks_found"] = len(chunks_by_source_id)
        diagnostics["exact_source_ref_hydration_items_used"] = len(hydrated_items)
        return tuple(hydrated_items), diagnostics

    async def _apply_temporal_relation_signals(
        self,
        *,
        items: tuple[ContextItem, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        fact_items = [item for item in items if item.item_type == "fact"]
        if not fact_items:
            return items, {
                "temporal_relations_considered": 0,
                "temporal_replacements_applied": 0,
                "temporal_contradictions_considered": 0,
                "temporal_relations_skipped_by_validity": 0,
            }

        now = self._clock.now() if self._clock is not None else None
        by_fact_id = {item.item_id: item for item in items}
        invalidated_fact_ids: set[str] = set()
        replacement_items: dict[str, ContextItem] = {}
        relations_considered = 0
        relations_skipped_by_validity = 0
        contradictions_considered = 0
        async with self._uow_factory() as uow:
            relations_by_fact_id = await uow.fact_relations.list_for_facts(
                fact_ids=tuple(item.item_id for item in fact_items),
                status="active",
                limit_per_fact=50,
            )
            for item in fact_items:
                relations = relations_by_fact_id.get(item.item_id, [])
                for relation in relations:
                    if not _temporal_relation_is_current(relation, now=now):
                        relations_skipped_by_validity += 1
                        continue
                    relation_type = relation.relation_type.value
                    if relation_type == "supersedes":
                        relations_considered += 1
                        if str(relation.target_fact_id) == item.item_id:
                            source = await uow.facts.get_by_id(str(relation.source_fact_id))
                            if source is not None and is_context_fact_visible(
                                source,
                                query=query,
                                memory_scope_ids=memory_scope_ids,
                                now=now,
                            ):
                                invalidated_fact_ids.add(item.item_id)
                                replacement_items[str(source.id)] = _temporal_replacement_item(
                                    source,
                                    relation=relation,
                                    now=now,
                                    query_text=query.query,
                                )
                        elif str(relation.source_fact_id) == item.item_id:
                            by_fact_id[item.item_id] = _annotate_temporal_relation(
                                item,
                                relation=relation,
                                role="supersedes",
                                score_delta=0.025,
                            )
                    elif relation_type == "contradicts":
                        contradictions_considered += 1
                        by_fact_id[item.item_id] = _annotate_temporal_relation(
                            by_fact_id[item.item_id],
                            relation=relation,
                            role="contradicts",
                            score_delta=0.01,
                        )

        for fact_id, replacement_item in replacement_items.items():
            existing_item = by_fact_id.get(fact_id)
            if existing_item is None or replacement_item.score >= existing_item.score:
                by_fact_id[fact_id] = replacement_item

        next_items = [
            by_fact_id.get(item.item_id, item)
            for item in items
            if item.item_id not in invalidated_fact_ids
        ]
        existing_ids = {item.item_id for item in next_items}
        next_items.extend(
            item for fact_id, item in replacement_items.items() if fact_id not in existing_ids
        )
        return tuple(next_items), {
            "temporal_relations_considered": relations_considered,
            "temporal_replacements_applied": len(invalidated_fact_ids),
            "temporal_contradictions_considered": contradictions_considered,
            "temporal_relations_skipped_by_validity": relations_skipped_by_validity,
        }

    async def _stale_review_items(
        self,
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
        if query.max_facts <= 0:
            return (), {
                "stale_facts_considered": 0,
                "stale_facts_used": 0,
                "superseded_facts_considered": 0,
                "superseded_facts_used": 0,
            }

        now = self._clock.now() if self._clock is not None else None
        candidate_limit = min(200, max(query.max_facts * 4, query.max_facts))
        items: list[ContextItem] = []
        considered = 0
        superseded_considered = 0
        superseded_used = 0
        statuses = ("superseded", "disputed") if query.include_stale else ("superseded",)
        async with self._uow_factory() as uow:
            for memory_scope_id in query.memory_scope_ids:
                for status in statuses:
                    if len(items) >= query.max_facts:
                        break
                    facts = await uow.facts.list_for_scope(
                        space_id=str(query.space_id),
                        memory_scope_id=str(memory_scope_id),
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        status=status,
                        limit=candidate_limit,
                        category=query.category,
                        tag=None,
                    )
                    considered += len(facts)
                    if status == "superseded":
                        superseded_considered += len(facts)
                    for fact in facts:
                        if not is_context_review_fact_visible(
                            fact,
                            query=query,
                            memory_scope_ids=memory_scope_ids,
                            statuses=(status,),
                            now=now,
                        ):
                            continue
                        relevance = score_query_relevance(query=query.query, text=fact.text)
                        if not is_query_relevance_sufficient(relevance):
                            continue
                        items.append(
                            stale_review_item(
                                fact,
                                relevance=relevance,
                                query_text=query.query,
                            )
                        )
                        if status == "superseded":
                            superseded_used += 1
                        if len(items) >= query.max_facts:
                            break
                if len(items) >= query.max_facts:
                    break

        return tuple(items), {
            "stale_facts_considered": considered,
            "stale_facts_used": len(items),
            "superseded_facts_considered": superseded_considered,
            "superseded_facts_used": superseded_used,
        }

    async def _pending_conflict_items(
        self,
        *,
        query: BuildContextQuery,
        visible_fact_ids: tuple[str, ...],
    ) -> tuple[ContextItem, ...]:
        max_items = max(0, query.max_conflicting_suggestions)
        visible_fact_id_set = set(visible_fact_ids)
        if max_items <= 0 or not visible_fact_id_set:
            return ()

        items: list[ContextItem] = []
        async with self._uow_factory() as uow:
            for memory_scope_id in query.memory_scope_ids:
                if len(items) >= max_items:
                    break
                suggestions = await uow.suggestions.list_for_scope(
                    space_id=str(query.space_id),
                    memory_scope_id=str(memory_scope_id),
                    status="pending",
                    operation=None,
                    category=None,
                    tag=None,
                    limit=max(20, max_items * 4),
                )
                for suggestion in suggestions:
                    conflict_fact_id = suggestion_conflict_fact_id(suggestion)
                    if conflict_fact_id not in visible_fact_id_set:
                        continue
                    target_fact = await uow.facts.get_by_id(conflict_fact_id)
                    items.append(
                        pending_review_suggestion_item(
                            suggestion=suggestion,
                            target_fact_id=conflict_fact_id,
                            target_fact_text=target_fact.text if target_fact else None,
                        )
                    )
                    if len(items) >= max_items:
                        return tuple(items)
        return tuple(items)


def _fact_context_item(
    fact: MemoryFact,
    *,
    now: datetime | None,
    query_text: str,
) -> ContextItem:
    relevance = score_query_relevance(query=query_text, text=fact.text, max_boost=0.03)
    fact_score, fact_signals = _fact_score_signals(
        fact,
        now=now,
        relevance=relevance,
    )
    if _has_cyrillic(query_text) and _has_cyrillic(fact.text):
        fact_score = min(0.995, round(fact_score + 0.012, 4))
        fact_signals = {
            **fact_signals,
            "same_script_query_boost": 0.012,
        }
    snippet = query_focused_snippet(query=query_text, text=fact.text)
    source_refs = source_refs_with_query_snippet(fact.source_refs, snippet)
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(fact.id),
            item_type="fact",
            text=fact.text,
            score=fact_score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(fact.memory_scope_id),
                "retrieval_source": "postgres_facts",
                "retrieval_sources": ["postgres_facts"],
                "ranking_reason": "canonical active fact matched query and filters",
                "score_signals": {
                    **fact_signals,
                    **query_snippet_score_signals(snippet),
                },
                "provenance": {
                    "retrieval_sources": ["postgres_facts"],
                    "source_ref_count": len(source_refs),
                    "fact_status": fact.status.value,
                    "fact_version": fact.version,
                    **query_snippet_diagnostics(snippet),
                },
                "confidence": fact.confidence.value,
                "trust_level": fact.trust_level.value,
                "updated_at": fact.updated_at.isoformat(),
                **query_snippet_diagnostics(snippet),
            },
        ),
        query_text=query_text,
    )


def _temporal_relation_is_current(
    relation: MemoryFactRelation,
    *,
    now: datetime | None,
) -> bool:
    return is_temporal_window_current(
        valid_from=relation.valid_from,
        valid_to=relation.valid_to,
        now=now,
    )


def _temporal_replacement_item(
    fact: MemoryFact,
    *,
    relation: MemoryFactRelation,
    now: datetime | None,
    query_text: str,
) -> ContextItem:
    item = _fact_context_item(fact, now=now, query_text=query_text)
    diagnostics = dict(item.diagnostics or {})
    diagnostics["retrieval_source"] = "temporal_supersedes_relation"
    diagnostics["retrieval_sources"] = [
        "temporal_supersedes_relation",
        *[
            source
            for source in diagnostics.get("retrieval_sources", [])
            if source != "temporal_supersedes_relation"
        ],
    ]
    diagnostics["ranking_reason"] = "active fact supersedes a matched older fact"
    diagnostics["temporal_replacement_for_fact_id"] = str(relation.target_fact_id)
    diagnostics["temporal_relation_id"] = str(relation.id)
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "temporal_supersedes_boost": 0.04,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "temporal_relation_id": str(relation.id),
        "supersedes_fact_id": str(relation.target_fact_id),
        "observed_at": relation.observed_at.isoformat(),
        "valid_from": relation.valid_from.isoformat() if relation.valid_from else None,
        "valid_to": relation.valid_to.isoformat() if relation.valid_to else None,
    }
    replacement_score = min(0.99, round(item.score + 0.04, 4))
    if _is_weak_non_temporal_replacement(query_text, diagnostics):
        replacement_score = min(replacement_score, 0.92)
    return replace(
        item,
        score=replacement_score,
        diagnostics=diagnostics,
    )


def _annotate_temporal_relation(
    item: ContextItem,
    *,
    relation: MemoryFactRelation,
    role: str,
    score_delta: float,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    temporal_relations = list(diagnostics.get("temporal_relations") or [])
    temporal_relations.append(
        {
            "relation_id": str(relation.id),
            "relation_type": relation.relation_type.value,
            "role": role,
            "source_fact_id": str(relation.source_fact_id),
            "target_fact_id": str(relation.target_fact_id),
            "observed_at": relation.observed_at.isoformat(),
            "valid_from": relation.valid_from.isoformat() if relation.valid_from else None,
            "valid_to": relation.valid_to.isoformat() if relation.valid_to else None,
        }
    )
    diagnostics["temporal_relations"] = temporal_relations[-8:]
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        f"temporal_{role}_boost": score_delta,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "temporal_relation_count": len(temporal_relations),
    }
    return replace(
        item,
        score=min(0.99, round(item.score + score_delta, 4)),
        diagnostics=diagnostics,
    )


def _with_keyword_aggregation_score_signals(
    item: ContextItem,
    *,
    strict_hits: int,
    source_group: str,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "keyword_aggregation_strict_term_hits": strict_hits,
        "keyword_aggregation_group_match": 1,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "keyword_aggregation_source_group": source_group,
    }
    return replace(item, diagnostics=diagnostics)


def _chunk_context_item(
    *,
    chunk: MemoryChunk,
    text: str,
    retrieval_source: str,
    base_score: float,
    score: float,
    relevance: QueryRelevance | None,
    query_text: str,
    query_expansion_reason: str = "original_query",
    use_query_snippet: bool = True,
    keyword_source_score_boost: float = 0.0,
) -> ContextItem:
    snippet = query_focused_snippet(query=query_text, text=text) if use_query_snippet else None
    evidence_text = snippet.text if snippet is not None else text
    source_refs = source_refs_with_query_snippet(
        chunk_source_refs(chunk, text_preview=(snippet.text if snippet else text[:200])),
        snippet,
        include_char_range=True,
    )
    score_signals = {
        "base_score": base_score,
        "final_score": score,
        "retrieval_channel": retrieval_source,
        "source_type": chunk.source_type,
        "source_ref_count": len(source_refs),
        **query_snippet_score_signals(snippet),
    }
    if relevance is not None:
        score_signals.update(query_relevance_score_signals(relevance))
    if query_expansion_reason != "original_query":
        score_signals["query_expansion_reason"] = query_expansion_reason
    reason_priority = query_expansion_reason_priority(query_expansion_reason)
    if reason_priority > 0:
        score_signals["query_expansion_reason_priority"] = reason_priority
    if keyword_source_score_boost > 0:
        score_signals["keyword_source_score_boost"] = keyword_source_score_boost
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(chunk.id),
            item_type="chunk",
            text=evidence_text,
            score=score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(chunk.memory_scope_id),
                "retrieval_source": retrieval_source,
                "retrieval_sources": [retrieval_source],
                "ranking_reason": f"matched via {retrieval_source}",
                "query_expansion_reason": query_expansion_reason,
                "score_signals": score_signals,
                "provenance": {
                    "retrieval_sources": [retrieval_source],
                    "source_ref_count": len(source_refs),
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_external_id,
                    "chunk_id": str(chunk.id),
                    "sequence": chunk.sequence,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                    "query_expansion_reason": query_expansion_reason,
                },
                "source_type": chunk.source_type,
                "source_id": chunk.source_external_id,
                "chunk_sequence": chunk.sequence,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                **source_ref_location_summary(source_refs),
                **query_snippet_diagnostics(snippet),
            },
        ),
        query_text=query_text,
    )


def _is_neighbor_chunk_visible(
    chunk: MemoryChunk,
    *,
    query: BuildContextQuery,
    memory_scope_ids: tuple[str, ...],
) -> bool:
    if chunk.status != LifecycleStatus.ACTIVE:
        return False
    if chunk.classification == DataClassification.RESTRICTED.value:
        return False
    if str(chunk.space_id) != str(query.space_id):
        return False
    if str(chunk.memory_scope_id) not in memory_scope_ids:
        return False
    if query.thread_id is None:
        return chunk.thread_id is None
    return chunk.thread_id is None or str(chunk.thread_id) == str(query.thread_id)


def _ranked_keyword_chunk_scores(
    scored_keyword_chunks: list[tuple[int, int, int, float, float, int, MemoryChunk]],
) -> tuple[tuple[int, int, int, float, float, int, MemoryChunk], ...]:
    return tuple(
        sorted(
            scored_keyword_chunks,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )


def _context_item_aggregation_source_groups(items: tuple[ContextItem, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    seen: set[str] = set()
    for item in items:
        diagnostics = item.diagnostics or {}
        provenance = diagnostics.get("provenance")
        raw_group = (
            provenance.get("keyword_aggregation_source_group")
            if isinstance(provenance, dict)
            else None
        )
        group = str(raw_group or "").strip()
        if group and group not in seen:
            seen.add(group)
            groups.append(group)
    return tuple(groups)


def _prioritized_chunks_for_source_groups(
    chunks: tuple[MemoryChunk, ...],
    *,
    source_groups: tuple[str, ...],
) -> tuple[MemoryChunk, ...]:
    if not chunks or not source_groups:
        return ()
    source_group_set = set(source_groups)
    return tuple(
        chunk
        for chunk in chunks
        if _aggregation_source_group(chunk) in source_group_set
    )


def _prioritized_source_sibling_seed_groups(
    *,
    source_groups: dict[str, object],
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
    limit: int,
) -> dict[str, object]:
    if limit <= 0:
        return {}
    if len(source_groups) <= limit:
        return dict(source_groups)
    answer_evidence_group_rank: dict[str, tuple[int, int, int, float]] = {}
    for chunk in seed_chunks:
        group = _aggregation_source_group(chunk)
        if not group or group not in source_groups:
            continue
        chunk_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
            query_plan,
            text=chunk_text,
            cache=query_relevance_cache,
        )
        answer_evidence = _source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=chunk_text,
        )
        related_turn_anchor = _related_turn_anchor_evidence(
            relevance=relevance,
            text=chunk_text,
        )
        if answer_evidence or related_turn_anchor:
            rank = (
                1 if answer_evidence else 0,
                relevance.distinctive_term_hits,
                relevance.unique_term_hits,
                relevance.hit_ratio,
            )
            answer_evidence_group_rank[group] = max(
                rank,
                answer_evidence_group_rank.get(group, (0, 0, 0, 0.0)),
            )
    ordered_groups = tuple(source_groups.items())
    prioritized = sorted(
        (
            (group, seed)
            for group, seed in ordered_groups
            if group in answer_evidence_group_rank
        ),
        key=lambda item: (
            -answer_evidence_group_rank[item[0]][0],
            -answer_evidence_group_rank[item[0]][1],
            -answer_evidence_group_rank[item[0]][2],
            -answer_evidence_group_rank[item[0]][3],
        ),
    )
    prioritized.extend(
        (group, seed)
        for group, seed in ordered_groups
        if group not in answer_evidence_group_rank
    )
    return dict(prioritized[:limit])


def _prioritize_source_sibling_answer_evidence_seed_chunks(
    *,
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
) -> tuple[MemoryChunk, ...]:
    answer_evidence_chunks: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    remaining_chunks: list[tuple[int, MemoryChunk]] = []
    for index, chunk in enumerate(seed_chunks):
        chunk_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
            query_plan,
            text=chunk_text,
            cache=query_relevance_cache,
        )
        answer_evidence = _source_sibling_answer_evidence_query_match(
            query_plan=query_plan,
            text=chunk_text,
            preferred_query=expansion_query,
            preferred_reason=expansion_reason,
        )
        related_turn_anchor = _related_turn_anchor_evidence(
            relevance=relevance,
            text=chunk_text,
        )
        if answer_evidence or related_turn_anchor:
            answer_evidence_chunks.append(
                (
                    1 if answer_evidence else 0,
                    relevance.distinctive_term_hits,
                    relevance.unique_term_hits,
                    relevance.hit_ratio,
                    index,
                    _aggregation_source_group(chunk),
                    chunk,
                )
            )
            continue
        remaining_chunks.append((index, chunk))
    if not answer_evidence_chunks:
        return seed_chunks
    ordered_answer_evidence_chunks = sorted(
        (chunk for chunk in answer_evidence_chunks if chunk[0] > 0),
        key=lambda item: (-item[1], -item[2], -item[3], item[4]),
    )
    ordered_related_anchor_chunks = sorted(
        (chunk for chunk in answer_evidence_chunks if chunk[0] <= 0),
        key=lambda item: (-item[1], -item[2], -item[3], item[4]),
    )
    prioritized_entries = (
        *_source_group_diverse_answer_evidence_chunks(ordered_answer_evidence_chunks),
        *_source_group_diverse_answer_evidence_chunks(ordered_related_anchor_chunks),
    )
    prioritized = tuple(chunk for *_, chunk in prioritized_entries)
    remaining = tuple(chunk for _, chunk in remaining_chunks)
    return (*prioritized, *remaining)


def _source_group_diverse_answer_evidence_chunks(
    chunks: list[tuple[int, int, int, float, int, str, MemoryChunk]],
) -> tuple[tuple[int, int, int, float, int, str, MemoryChunk], ...]:
    primary: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    extra: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    seen_groups: set[str] = set()
    for chunk in chunks:
        source_group = chunk[5]
        if source_group and source_group not in seen_groups:
            seen_groups.add(source_group)
            primary.append(chunk)
            continue
        extra.append(chunk)
    return (*primary, *extra)


def _source_sibling_answer_evidence_query_match(
    *,
    query_plan: QueryExpansionPlan,
    text: str,
    preferred_query: str,
    preferred_reason: str,
) -> tuple[str, str] | None:
    if _source_sibling_answer_evidence(
        expansion_query=preferred_query,
        expansion_reason=preferred_reason,
        text=text,
    ):
        return preferred_query, preferred_reason
    for expansion in query_plan.retrieval_queries:
        if expansion.query == preferred_query and expansion.reason == preferred_reason:
            continue
        if _source_sibling_answer_evidence(
            expansion_query=expansion.query,
            expansion_reason=expansion.reason,
            text=text,
        ):
            return expansion.query, expansion.reason
    return None


def _query_plan_requests_list_source_sibling_depth(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    if _LIST_AGGREGATION_QUERY_RE.search(query_text) is not None:
        return True
    if _WHERE_LIST_AGGREGATION_QUERY_RE.search(query_text) is not None:
        return True
    return any(
        expansion.reason in _LIST_SOURCE_SIBLING_DEEP_REASONS
        for expansion in query_plan.retrieval_queries
    )


def _query_plan_requests_place_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    if _EN_PLACE_LIST_SOURCE_SIBLING_QUERY_RE.search(query_text) is not None:
        return True
    return any(
        expansion.reason
        in {
            "friend_place_inventory_bridge",
            "friend_place_shelter_inventory_bridge",
            "friend_place_gym_inventory_bridge",
            "friend_place_church_inventory_bridge",
            "place_area_inventory_bridge",
            "travel_country_inventory_bridge",
            "trip_destination_bridge",
        }
        for expansion in query_plan.retrieval_queries
    )


def _query_plan_requests_named_preference_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    if _EN_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE.search(query_text) is None:
        return False
    if _EN_NAMED_ENTITY_PHRASE_RE.search(query_text) is None:
        return False
    return any(
        expansion.reason == "decomposition_inference_support"
        for expansion in query_plan.retrieval_queries
    )


def _query_plan_requests_relationship_status_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    del query_text
    return any(
        _is_relationship_status_reason(expansion.reason)
        for expansion in query_plan.retrieval_queries
    )


def _source_sibling_group_limit_for_request(
    *,
    source_group_count: int,
    deep_list_coverage: bool,
    answer_evidence_group_diversity: bool,
) -> int:
    source_group_limit = _source_sibling_group_limit()
    if deep_list_coverage or answer_evidence_group_diversity:
        return max(
            source_group_limit,
            min(source_group_count, _LIST_SOURCE_SIBLING_GROUP_LIMIT),
        )
    return source_group_limit


def _source_sibling_group_backfill_plan(
    *,
    deep_list_coverage: bool,
    source_groups: Mapping[str, object],
) -> tuple[tuple[str, ...], int]:
    if not deep_list_coverage or not source_groups:
        return (), 0
    return tuple(source_groups), _LIST_SOURCE_SIBLING_GROUP_BACKFILL_LIMIT


def _dedupe_chunks_by_id(chunks: tuple[MemoryChunk, ...]) -> tuple[MemoryChunk, ...]:
    selected: list[MemoryChunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.id)
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        selected.append(chunk)
    return tuple(selected)


def _exact_turn_source_ref_hydration_requests(
    items: tuple[ContextItem, ...],
) -> dict[str, str]:
    return dict(_exact_turn_source_ref_hydration_request_plan(items).reason_by_id)


def _exact_turn_source_ref_hydration_request_plan(
    items: tuple[ContextItem, ...],
) -> _ExactTurnHydrationRequestPlan:
    hydrated_source_ids = _exact_turn_source_ids_with_body(items)
    request_entries: list[tuple[int, int, int, str, str]] = []
    for item_index, item in enumerate(items):
        if not _context_item_source_sibling_answer_evidence(item):
            continue
        reason = _context_item_query_expansion_reason(item)
        query = _context_item_source_sibling_answer_evidence_query(item)
        item_entries: list[tuple[int, int, int, str, str]] = []
        for ref_index, ref in enumerate(item.source_refs):
            source_id = str(ref.source_id or "")
            if (
                not source_id.casefold().endswith(":turn")
                or source_id in hydrated_source_ids
                or not _source_ref_needs_exact_turn_body_hydration(
                    item,
                    source_id=source_id,
                )
            ):
                continue
            rank = _source_ref_country_destination_hydration_rank(
                item,
                source_id=source_id,
                reason=reason,
                query=query,
            )
            item_entries.append((rank, item_index, ref_index, source_id, reason))
        if _is_country_destination_hydration_scope(reason=reason, query=query):
            has_supported_source_ref = any(entry[0] < 5 for entry in item_entries)
            if has_supported_source_ref or _item_has_supported_country_destination_marker(
                item,
                query=query,
            ):
                item_entries = [entry for entry in item_entries if entry[0] < 5]
        request_entries.extend(item_entries)
    requests: dict[str, str] = {}
    for _, _, _, source_id, reason in sorted(request_entries):
        requests.setdefault(source_id, reason)
    continuation_requests = _source_sibling_answer_continuation_hydration_request_items(
        items,
        existing_source_ids=hydrated_source_ids,
    )
    next_answer_source_ids: set[str] = set()
    previous_question_source_ids: set[str] = set()
    for source_id, (reason, request_kind) in continuation_requests.items():
        if source_id in requests:
            continue
        requests[source_id] = reason
        if request_kind == "next_answer":
            next_answer_source_ids.add(source_id)
        elif request_kind == "previous_question":
            previous_question_source_ids.add(source_id)
    return _ExactTurnHydrationRequestPlan(
        reason_by_id=requests,
        next_answer_source_ids=frozenset(next_answer_source_ids),
        previous_question_source_ids=frozenset(previous_question_source_ids),
    )


def _should_use_exact_source_ref_hydration_item(
    *,
    source_id: str,
    request_plan: _ExactTurnHydrationRequestPlan,
    answer_evidence: bool,
    text: str,
) -> bool:
    if source_id in request_plan.next_answer_source_ids:
        return answer_evidence
    if source_id in request_plan.previous_question_source_ids:
        return _is_question_or_request_dialogue_turn(text)
    return True


def _is_question_or_request_dialogue_turn(text: str) -> bool:
    body = _dialogue_turn_body(text)
    return _QUESTION_OR_REQUEST_TURN_RE.search(body) is not None


def _dialogue_turn_body(text: str) -> str:
    marker_match = _DIALOGUE_MARKER_RE.search(text)
    if marker_match is not None:
        text = text[marker_match.end() :]
    speaker_match = re.match(r"\s*[^:\n]{1,48}:\s*", text)
    if speaker_match is not None:
        text = text[speaker_match.end() :]
    return text.strip()


def _exact_turn_source_ids_with_body(items: tuple[ContextItem, ...]) -> frozenset[str]:
    source_ids: set[str] = set()
    for item in items:
        for ref in item.source_refs:
            source_id = str(ref.source_id or "")
            marker = _dialogue_marker_from_source_id(source_id)
            if marker and _text_has_dialogue_turn_body(item.text, marker=marker):
                source_ids.add(source_id)
    return frozenset(source_ids)


def _source_ref_needs_exact_turn_body_hydration(
    item: ContextItem,
    *,
    source_id: str,
) -> bool:
    marker = _dialogue_marker_from_source_id(source_id)
    if not marker:
        return False
    return not _text_has_dialogue_turn_body(item.text, marker=marker)


def _text_has_dialogue_turn_body(text: str, *, marker: str) -> bool:
    for match in re.finditer(rf"\b{re.escape(marker)}\b", text):
        following = text[match.end() : match.end() + 64]
        if re.match(r"\s+(?!\.\.\.)[A-Z][^:\n]{0,40}:", following):
            return True
    return False


def _dialogue_marker_from_source_id(source_id: str) -> str:
    match = _DIALOGUE_MARKER_RE.search(str(source_id or ""))
    return match.group(0) if match is not None else ""


def _context_item_source_sibling_answer_evidence(item: ContextItem) -> bool:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if not isinstance(score_signals, dict):
        return False
    value = score_signals.get("source_sibling_answer_evidence")
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _context_item_query_expansion_reason(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    reason = str(diagnostics.get("query_expansion_reason") or "")
    if reason and reason != "original_query":
        return reason
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        signal_reason = str(score_signals.get("query_expansion_reason") or "")
        if signal_reason:
            return signal_reason
    return reason or "original_query"


def _context_item_source_sibling_answer_evidence_query(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        query = str(score_signals.get("source_sibling_answer_evidence_query") or "")
        if query:
            return query
    provenance = diagnostics.get("provenance")
    if isinstance(provenance, dict):
        return str(provenance.get("source_sibling_answer_evidence_query") or "")
    return ""


def _source_ref_country_destination_hydration_rank(
    item: ContextItem,
    *,
    source_id: str,
    reason: str,
    query: str,
) -> int:
    if not _is_country_destination_hydration_scope(reason=reason, query=query):
        return 5
    return _country_destination_answer_support_rank(
        expansion_query=query,
        text=_focused_exact_source_repair_text(text=item.text, source_id=source_id),
        has_exact_turn=True,
    )


def _item_has_supported_country_destination_marker(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    for marker in dict.fromkeys(_DIALOGUE_MARKER_RE.findall(item.text)):
        if (
            _country_destination_answer_support_rank(
                expansion_query=query,
                text=_focused_exact_source_repair_text(
                    text=item.text,
                    source_id=f"synthetic:{marker}:turn",
                ),
                has_exact_turn=True,
            )
            < 5
        ):
            return True
    return False


def _is_country_destination_hydration_scope(*, reason: str, query: str) -> bool:
    return bool(query) and reason.replace("_", "-") == "decomposition-country-destination"


def _query_expansion_text_for_reason(
    plan: QueryExpansionPlan,
    *,
    reason: str,
    fallback: str,
) -> str:
    for expansion in plan.expansions:
        if expansion.reason == reason:
            return expansion.query
    return fallback


def _with_exact_source_ref_hydration_signals(
    item: ContextItem,
    *,
    answer_evidence: bool,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    retrieval_sources = list(diagnostic_retrieval_sources(diagnostics))
    if "exact_source_ref_hydration" not in retrieval_sources:
        retrieval_sources.append("exact_source_ref_hydration")
    diagnostics["retrieval_sources"] = retrieval_sources
    score_signals = diagnostics.get("score_signals")
    score_signal_dict = dict(score_signals) if isinstance(score_signals, dict) else {}
    score_signal_dict["exact_source_ref_hydration"] = 1
    if answer_evidence:
        score_signal_dict["source_sibling_answer_evidence"] = 1
    diagnostics["score_signals"] = score_signal_dict
    diagnostics["ranking_reason"] = (
        "hydrated exact source turn referenced by answer-evidence source group"
    )
    return replace(item, diagnostics=diagnostics)


def _strict_query_term_hits(*, query: str, text: str) -> int:
    return _strict_query_variant_hits(
        query_term_variants=_strict_query_term_variant_sets(query=query),
        text=text,
    )


def _strict_query_term_variant_sets(*, query: str) -> _StrictQueryTermVariants:
    return tuple(frozenset(_strict_token_variants(term.raw)) for term in query_terms(query))


def _strict_query_variant_hits(
    *,
    query_term_variants: _StrictQueryTermVariants,
    text: str,
) -> int:
    if not query_term_variants:
        return 0
    text_variants: set[str] = set()
    for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
        text_variants.update(_strict_token_variants(match.group(0)))
    return sum(
        1
        for term_variants in query_term_variants
        if text_variants.intersection(term_variants)
    )


def _keyword_anchor_conflict_allowed(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
) -> bool:
    if expansion_reason != "travel_country_inventory_bridge":
        return False
    if relevance.distinctive_term_hits < 3 or relevance.unique_term_hits < 3:
        return False
    return has_travel_place_inventory_evidence(text)


def _selected_keyword_prompt_items(
    scored_items: list[_ScoredKeywordPromptItem],
    *,
    limit: int,
) -> tuple[ContextItem, ...]:
    if limit <= 0 or not scored_items:
        return ()
    ordered = tuple(
        sorted(
            scored_items,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )
    selected: list[ContextItem] = []
    selected_keys: set[tuple[str, str]] = set()
    for scored_item in _source_diverse_keyword_prompt_items(ordered, limit=limit):
        item = scored_item[7]
        selected.append(item)
        selected_keys.add((item.item_type, item.item_id))
    if (
        limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS
        and limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS
    ):
        return tuple(selected)
    if limit >= _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS:
        inventory_extra_count = 0
        inventory_extra_limit = min(limit, _MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS)
        for scored_item in ordered[limit:]:
            reason = scored_item[6]
            if reason not in _EXTRA_INVENTORY_PROMPT_REASONS:
                continue
            if scored_item[1] < _MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS:
                continue
            item = scored_item[7]
            key = (item.item_type, item.item_id)
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            inventory_extra_count += 1
            if inventory_extra_count >= inventory_extra_limit:
                break
    if limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS:
        return tuple(selected)
    extra_count = 0
    extra_limit = limit
    if limit >= 32:
        extra_limit = _MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS
    for scored_item in ordered[limit:]:
        reason = scored_item[6]
        if reason not in _ACTIVITY_OBSERVATION_SOURCE_REASONS:
            continue
        item = scored_item[7]
        key = (item.item_type, item.item_id)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        extra_count += 1
        if extra_count >= extra_limit:
            break
    return tuple(selected)


def _source_diverse_keyword_prompt_items(
    ordered: tuple[_ScoredKeywordPromptItem, ...],
    *,
    limit: int,
) -> tuple[_ScoredKeywordPromptItem, ...]:
    selected: list[_ScoredKeywordPromptItem] = []
    used_sources: set[str] = set()
    for scored_item in ordered:
        source_key = _keyword_prompt_item_source_key(scored_item[7])
        if source_key in used_sources:
            continue
        selected.append(scored_item)
        used_sources.add(source_key)
        if len(selected) >= limit:
            return tuple(selected)
    if len(selected) >= limit:
        return tuple(selected)
    selected_keys = {(item[7].item_type, item[7].item_id) for item in selected}
    for scored_item in ordered:
        item = scored_item[7]
        key = (item.item_type, item.item_id)
        if key in selected_keys:
            continue
        selected.append(scored_item)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _keyword_prompt_item_source_key(item: ContextItem) -> str:
    if item.source_refs:
        ref = item.source_refs[0]
        return f"{ref.source_type}:{ref.source_id}"
    return f"{item.item_type}:{item.item_id}"



def _keyword_aggregation_chunk_items(
    *,
    query: BuildContextQuery,
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan | None = None,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    diagnostics = {
        "keyword_aggregation_chunks_considered": 0,
        "keyword_aggregation_chunks_used": 0,
        "keyword_aggregation_chunks_skipped": 0,
        "keyword_aggregation_query_kind": "",
        "keyword_aggregation_relaxed_relevance_used": 0,
    }
    aggregation_kind = _keyword_aggregation_query_kind(query.query)
    diagnostics["keyword_aggregation_query_kind"] = aggregation_kind
    if query.max_chunks <= 0 or not seed_chunks or not aggregation_kind:
        return (), diagnostics

    query_identity_terms = _aggregation_identity_terms(query.query)
    max_items = min(
        _MAX_AGGREGATION_KEYWORD_ITEMS,
        max(4, query.max_chunks // 2),
    )
    candidates: list[_KeywordAggregationCandidate] = []
    skipped = 0
    for order, chunk in enumerate(seed_chunks):
        diagnostics["keyword_aggregation_chunks_considered"] = (
            int(diagnostics["keyword_aggregation_chunks_considered"]) + 1
        )
        chunk_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        aggregation_query, aggregation_reason, relevance = _aggregation_query_relevance(
            query=query.query,
            query_plan=query_plan,
            text=chunk_text,
            query_relevance_cache=query_relevance_cache,
        )
        weighted_query_terms = _weighted_aggregation_query_variant_sets(
            aggregation_query,
            identity_terms=query_identity_terms,
        )
        weighted_hits, _ = _strict_query_window_match_counts(
            text=chunk_text,
            query_variant_sets=weighted_query_terms,
        )
        strict_hits = int(weighted_hits)
        if weighted_hits <= 0:
            skipped += 1
            continue
        if not _is_keyword_aggregation_relevance_acceptable(
            relevance,
            aggregation_kind=aggregation_kind,
            strict_hits=strict_hits,
        ):
            skipped += 1
            continue
        if not is_query_relevance_sufficient(relevance):
            diagnostics["keyword_aggregation_relaxed_relevance_used"] = (
                int(diagnostics["keyword_aggregation_relaxed_relevance_used"]) + 1
            )
        group = _aggregation_source_group(chunk)
        rank_key = (
            -strict_hits,
            _aggregation_source_kind_rank(chunk),
            -relevance.distinctive_term_hits,
            -relevance.hit_ratio,
            order,
        )
        candidates.append(
            _KeywordAggregationCandidate(
                rank_key=rank_key,
                group=group,
                chunk=chunk,
                chunk_text=chunk_text,
                relevance=relevance,
                strict_hits=strict_hits,
                aggregation_query=aggregation_query,
                aggregation_reason=aggregation_reason,
                query_variant_sets=weighted_query_terms,
            )
        )

    items: list[ContextItem] = []
    group_counts: dict[str, int] = {}
    for candidate in sorted(candidates, key=lambda item: item.rank_key):
        if len(items) >= max_items:
            break
        if group_counts.get(candidate.group, 0) >= 3:
            skipped += 1
            continue
        group_counts[candidate.group] = group_counts.get(candidate.group, 0) + 1
        item = _chunk_context_item(
            chunk=candidate.chunk,
            text=_aggregation_evidence_text(
                query=candidate.aggregation_query,
                text=candidate.chunk_text,
                identity_terms=query_identity_terms,
                query_variant_sets=candidate.query_variant_sets,
            ),
            retrieval_source="keyword_aggregation_chunks",
            base_score=0.78,
            score=0.985,
            relevance=candidate.relevance,
            query_text=candidate.aggregation_query,
            query_expansion_reason=candidate.aggregation_reason,
            use_query_snippet=False,
        )
        items.append(
            _with_keyword_aggregation_score_signals(
                item,
                strict_hits=candidate.strict_hits,
                source_group=candidate.group,
            )
        )

    diagnostics["keyword_aggregation_chunks_used"] = len(items)
    diagnostics["keyword_aggregation_chunks_skipped"] = skipped
    return tuple(items), diagnostics


def _keyword_aggregation_query_kind(query: str) -> str:
    if _COUNT_AGGREGATION_QUERY_RE.search(query):
        return "count"
    if _LIST_AGGREGATION_QUERY_RE.search(query) or _WHERE_LIST_AGGREGATION_QUERY_RE.search(query):
        return "list"
    return ""


def _aggregation_identity_terms(query: str) -> frozenset[str]:
    intent = build_query_anchor_intent(query)
    terms: set[str] = set()
    for hint in intent.hints:
        if hint.kind.value != "person":
            continue
        terms.update(term for term in hint.canonical_key.split() if term)
    return frozenset(terms)


def _aggregation_query_relevance(
    *,
    query: str,
    query_plan: QueryExpansionPlan | None,
    text: str,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[str, str, QueryRelevance]:
    if query_plan is None:
        return query, "original_query", score_query_relevance(query=query, text=text)
    if query_relevance_cache is None:
        return best_query_relevance(query_plan, text=text)
    return _best_query_relevance_cached(query_plan, text=text, cache=query_relevance_cache)


def _best_query_relevance_cached(
    query_plan: QueryExpansionPlan,
    *,
    text: str,
    cache: dict[str, tuple[str, str, QueryRelevance]],
) -> tuple[str, str, QueryRelevance]:
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance(query_plan, text=text)
    cache[text] = result
    return result


def _record_stage_timing(
    diagnostics: dict[str, object],
    stage: str,
    started_at: float,
) -> None:
    timings = diagnostics.get("stage_timings_ms")
    if not isinstance(timings, dict):
        timings = {}
        diagnostics["stage_timings_ms"] = timings
    if len(timings) >= 32 and stage not in timings:
        return
    timings[stage] = round((perf_counter() - started_at) * 1000, 2)


def _is_keyword_aggregation_relevance_acceptable(
    relevance: QueryRelevance,
    *,
    aggregation_kind: str,
    strict_hits: int,
) -> bool:
    if is_query_relevance_sufficient(relevance):
        return True
    return (
        aggregation_kind == "list"
        and strict_hits > 0
        and relevance.unique_term_hits > 0
    )


def _aggregation_source_group(chunk: MemoryChunk) -> str:
    marker = _source_turn_marker(chunk.source_external_id)
    if marker is not None:
        return marker[0]
    source_id = " ".join(str(chunk.source_external_id).split())
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1] in _SOURCE_GROUP_SUFFIXES:
        return ":".join(parts[:-1])
    return source_id or str(chunk.document_id or chunk.id)


def _source_sibling_answer_evidence_extra_key(
    chunk: MemoryChunk,
    *,
    deep_list_coverage: bool,
) -> str:
    source_id = str(chunk.source_external_id or "")
    if not deep_list_coverage:
        return source_id
    return _aggregation_source_group(chunk) or source_id


def _aggregation_source_kind_rank(chunk: MemoryChunk) -> int:
    if _source_turn_marker(chunk.source_external_id) is not None:
        return 1
    parts = " ".join(str(chunk.source_external_id).split()).split(":")
    if parts and parts[-1] == "observation":
        return 0
    if parts and parts[-1] in {"events", "summary"}:
        return 3
    return 2



def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _is_weak_non_temporal_replacement(query_text: str, diagnostics: dict[str, object]) -> bool:
    if _query_requests_temporal_replacement(query_text):
        return False
    score_signals = _score_signals(diagnostics)
    unique_hits = score_signals.get("unique_term_hits")
    phrase_hits = score_signals.get("phrase_bigram_hits")
    return (
        isinstance(unique_hits, int)
        and unique_hits < 3
        and (not isinstance(phrase_hits, int) or phrase_hits <= 0)
    )


def _query_requests_temporal_replacement(query_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:current|currently|latest|recent|now|previous|prior|last|changed|superseded)\b|"
            r"\b(?:сейчас|текущ|последн|недел|час|изменил|замен)\b",
            query_text,
            re.IGNORECASE,
        )
    )


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", text))


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}





def _trim_primary_fact_items(
    items: tuple[ContextItem, ...],
    *,
    max_facts: int,
) -> tuple[ContextItem, ...]:
    if max_facts <= 0:
        return tuple(item for item in items if not _is_primary_postgres_fact_item(item))
    primary_fact_count = 0
    selected: list[ContextItem] = []
    for item in items:
        if not _is_primary_postgres_fact_item(item):
            selected.append(item)
            continue
        if primary_fact_count >= max_facts:
            continue
        primary_fact_count += 1
        selected.append(item)
    return tuple(selected)


def _is_primary_postgres_fact_item(item: ContextItem) -> bool:
    return item.item_type == "fact" and diagnostic_retrieval_sources(item.diagnostics) == (
        "postgres_facts",
    )




def _fact_score_signals(
    fact: MemoryFact,
    *,
    now: datetime | None,
    relevance: QueryRelevance,
) -> tuple[float, dict[str, object]]:
    confidence_boost = _level_boost(fact.confidence.value, low=0.012, medium=0.03, high=0.05)
    trust_boost = _level_boost(fact.trust_level.value, low=0.01, medium=0.03, high=0.045)
    freshness_boost = _freshness_boost(fact.updated_at, now=now)
    ttl_penalty = -0.015 if fact.expires_at is not None else 0.0
    score = min(
        0.99,
        max(
            0.0,
            round(
                0.88
                + confidence_boost
                + trust_boost
                + freshness_boost
                + ttl_penalty
                + relevance.score_boost,
                4,
            ),
        ),
    )
    return score, {
        "base_score": 0.88,
        "confidence_boost": round(confidence_boost, 4),
        "trust_boost": round(trust_boost, 4),
        "freshness_boost": round(freshness_boost, 4),
        "ttl_penalty": round(ttl_penalty, 4),
        **query_relevance_score_signals(relevance),
        "classification": fact.classification,
        "category": fact.category,
    }


def _level_boost(value: str, *, low: float, medium: float, high: float) -> float:
    if value == "high":
        return high
    if value == "low":
        return low
    return medium


def _freshness_boost(updated_at: datetime, *, now: datetime | None) -> float:
    if now is None:
        return 0.0
    comparable_updated_at = updated_at
    comparable_now = now
    if comparable_updated_at.tzinfo is None and comparable_now.tzinfo is not None:
        comparable_updated_at = comparable_updated_at.replace(tzinfo=comparable_now.tzinfo)
    elif comparable_updated_at.tzinfo is not None and comparable_now.tzinfo is None:
        comparable_now = comparable_now.replace(tzinfo=comparable_updated_at.tzinfo)
    age_days = max(0.0, (comparable_now - comparable_updated_at).total_seconds() / 86400)
    if age_days <= 7:
        return 0.02
    if age_days <= 30:
        return 0.012
    if age_days <= 180:
        return 0.006
    return 0.0
