"""Build prompt-safe memory context from canonical and derived candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from time import perf_counter

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
    QueryAnchorIntent,
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
    source_sibling_candidate_rank_key as _source_sibling_candidate_rank_key,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_companion_extra_item_limit as _source_sibling_companion_extra_item_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_companion_extra_slot as _source_sibling_companion_extra_slot,
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
    source_sibling_rank as _source_sibling_rank,
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
_STRICT_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_COUNT_AGGREGATION_QUERY_RE = re.compile(
    r"\b(how many|number of|count|total)\b",
    re.IGNORECASE,
)
_LIST_AGGREGATION_QUERY_RE = re.compile(
    r"\b(?:what|which)\s+"
    r"(?:[\w+.-]+\s+){0,4}"
    r"(?:areas?|causes?|cities|countries|events?|activities?|hobbies|"
    r"instruments?|items?|martial\s+arts|people|places?|shelters?|states?|"
    r"traits?|books?|songs?|artists?|bands?|foods?|pets?|projects?|tasks?|"
    r"types?|kinds?)\b|"
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
_AGGREGATION_DIALOGUE_WINDOW_AFTER = 5
_MAX_AGGREGATION_DIALOGUE_WINDOWS = 4
_MAX_AGGREGATION_EVIDENCE_TEXT_CHARS = 2400
_MAX_AGGREGATION_MARKER_COVERAGE_IDS = 24
_MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS = 80
_MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS = 16
_MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS = 8
_MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS = 8
_MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS = 4
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
    }
)
_ScoredKeywordPromptItem = tuple[int, int, int, float, float, int, str, ContextItem]
_StrictQueryTermVariants = tuple[frozenset[str], ...]
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})
_LOW_SIGNAL_COUNT_AGGREGATION_TERMS = frozenset(
    {"many", "time", "times", "gone", "go", "going", "went"}
)
_LOW_SIGNAL_INVENTORY_AGGREGATION_TERMS = frozenset(
    {
        "answer",
        "evidence",
        "inventory",
        "list",
        "mention",
        "mentioned",
        "observed",
        "option",
        "options",
    }
)
_OBJECT_KIND_MISMATCH_RERANK_REASON = "object_kind_species_mismatch"
_OBJECT_KIND_MATCH_RERANK_REASON = "object_kind_match"
_RELATION_REQUIREMENT_MISMATCH_RERANK_REASONS = frozenset(
    {
        "relation_requirement_missing_relation",
        "relation_requirement_object_mismatch",
    }
)
_RELATION_REQUIREMENT_MATCH_RERANK_REASON = "relation_requirement_match"
_RELATION_REQUIREMENT_SUPPORT_RERANK_REASONS = frozenset(
    {
        "inventory_list_exact_evidence",
    }
)
_ANSWER_SHAPE_MISSING_RERANK_REASON = "explicit_answer_shape_missing"


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
                *_prioritized_chunks_for_source_groups(
                    tuple(used_keyword_chunks),
                    source_groups=aggregation_source_groups,
                ),
                *used_keyword_chunks,
                *ranked_keyword_chunks,
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
        candidate_items = _trim_primary_fact_items(
            candidate_items,
            max_facts=query.max_facts,
        )
        diagnostics["final_rank_candidate_item_count"] = len(candidate_items)
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
        stage_started_at = perf_counter()
        result = self._packer.pack(
            bundle_id=self._ids.new_id("ctx"),
            items=guarded_items,
            token_budget=query.token_budget,
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
        }
        if query.max_chunks <= 0 or not seed_chunks:
            return (), empty_diagnostics

        source_groups = _source_group_seed_turns(seed_chunks)
        if not source_groups:
            return (), empty_diagnostics
        source_groups = dict(tuple(source_groups.items())[:_source_sibling_group_limit()])
        max_items = min(
            _source_sibling_item_limit(),
            max(8, query.max_chunks * 2),
        )
        candidate_limit = min(
            512,
            max(max_items * 12, len(source_groups) * 32),
        )
        items: list[ContextItem] = []
        used_ids: set[str] = set()
        considered = 0
        skipped = 0
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
            if rank is None:
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
            ranked_candidates.append(
                (
                    _source_sibling_candidate_rank_key(
                        precise_turn=precise_turn,
                        dialogue_visual_reference=dialogue_visual_reference,
                        visual_continuation=visual_continuation,
                        observation_companion=observation_companion,
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
                )
            )
        ranked_candidates.sort(key=lambda item: item[0])
        companion_extra_used = 0
        companion_extra_slots: set[str] = set()
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
        ) in ranked_candidates:
            companion_slot = ""
            use_companion_extra_slot = False
            if len(items) >= max_items:
                if not observation_companion:
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
                if not use_companion_extra_slot:
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
                )
            )

        return tuple(items), {
            "keyword_source_sibling_chunks_considered": considered,
            "keyword_source_sibling_chunks_used": len(items),
            "keyword_source_sibling_chunks_skipped": skipped,
            "keyword_source_sibling_group_count": len(source_groups),
            "keyword_source_sibling_candidate_limit": candidate_limit,
            "keyword_source_sibling_companion_extra_used": companion_extra_used,
        }

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
                    items.append(
                        pending_review_suggestion_item(
                            suggestion=suggestion,
                            target_fact_id=conflict_fact_id,
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
    return replace(
        item,
        score=min(0.99, round(item.score + 0.04, 4)),
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
    for scored_item in ordered[:limit]:
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


def _strict_token_variants(token: str) -> tuple[str, ...]:
    normalized = token.casefold().replace("ё", "е").strip("_")
    if not normalized:
        return ()
    variants = {normalized}
    if len(normalized) > 5 and normalized.endswith("ing"):
        stem = normalized[:-3]
        variants.add(stem)
        variants.add(f"{stem}e")
        if len(stem) > 3 and stem[-1:] == stem[-2:-1]:
            variants.add(stem[:-1])
    if len(normalized) > 4 and normalized.endswith("ed"):
        variants.add(normalized[:-2])
    if len(normalized) > 4 and normalized.endswith("es"):
        variants.add(normalized[:-2])
    if len(normalized) > 3 and normalized.endswith("s"):
        variants.add(normalized[:-1])
    return tuple(sorted(variant for variant in variants if len(variant) >= 2))


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
    candidates: list[
        tuple[
            tuple[int, int, int, float, int],
            str,
            MemoryChunk,
            str,
            QueryRelevance,
            int,
            str,
            str,
        ]
    ] = []
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
            (
                rank_key,
                group,
                chunk,
                chunk_text,
                relevance,
                strict_hits,
                aggregation_query,
                aggregation_reason,
            )
        )

    items: list[ContextItem] = []
    group_counts: dict[str, int] = {}
    for (
        _,
        group,
        chunk,
        chunk_text,
        relevance,
        strict_hits,
        aggregation_query,
        aggregation_reason,
    ) in sorted(
        candidates,
        key=lambda item: item[0],
    ):
        if len(items) >= max_items:
            break
        if group_counts.get(group, 0) >= 3:
            skipped += 1
            continue
        group_counts[group] = group_counts.get(group, 0) + 1
        item = _chunk_context_item(
            chunk=chunk,
            text=_aggregation_evidence_text(
                query=aggregation_query,
                text=chunk_text,
                identity_terms=query_identity_terms,
            ),
            retrieval_source="keyword_aggregation_chunks",
            base_score=0.78,
            score=0.985,
            relevance=relevance,
            query_text=aggregation_query,
            query_expansion_reason=aggregation_reason,
            use_query_snippet=False,
        )
        items.append(
            _with_keyword_aggregation_score_signals(
                item,
                strict_hits=strict_hits,
                source_group=group,
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


def _aggregation_source_kind_rank(chunk: MemoryChunk) -> int:
    if _source_turn_marker(chunk.source_external_id) is not None:
        return 1
    parts = " ".join(str(chunk.source_external_id).split()).split(":")
    if parts and parts[-1] == "observation":
        return 0
    if parts and parts[-1] in {"events", "summary"}:
        return 3
    return 2


def _aggregation_evidence_text(
    *,
    query: str,
    text: str,
    identity_terms: frozenset[str] = frozenset(),
) -> str:
    markers = tuple(_DIALOGUE_MARKER_RE.finditer(text))
    if not markers:
        return text
    multi_window_text = _multi_window_aggregation_evidence_text(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
    )
    if multi_window_text:
        return _with_aggregation_marker_coverage(rendered=multi_window_text, full_text=text)
    bounds = _best_aggregation_dialogue_window(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
    )
    if bounds is None:
        match_start = _first_strict_query_match_start(query=query, text=text)
        if match_start is None:
            return text
        marker_index = max(
            (index for index, marker in enumerate(markers) if marker.start() <= match_start),
            default=0,
        )
        start_index = max(0, marker_index - 1)
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        bounds = (
            markers[start_index].start(),
            markers[end_index + 1].start()
            if end_index + 1 < len(markers)
            else len(text),
        )
    start, end = bounds
    window = text[start:end].strip()
    if start > 0:
        window = f"... {window}"
    if end < len(text):
        window = f"{window} ..."
    return _with_aggregation_marker_coverage(rendered=window or text, full_text=text)


def _with_aggregation_marker_coverage(*, rendered: str, full_text: str) -> str:
    if not rendered or rendered == full_text:
        return rendered
    markers = tuple(
        dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(full_text))
    )
    if not markers:
        return rendered
    missing = tuple(marker for marker in markers if marker not in rendered)
    if not missing:
        return rendered
    coverage = (
        "omitted source evidence markers: "
        + " ".join(missing[:_MAX_AGGREGATION_MARKER_COVERAGE_IDS])
    )
    if len(missing) > _MAX_AGGREGATION_MARKER_COVERAGE_IDS:
        coverage = f"{coverage} ..."
    candidate = f"{rendered}\n{coverage}".strip()
    if len(candidate) > _MAX_AGGREGATION_EVIDENCE_TEXT_CHARS:
        return rendered
    return candidate


def _multi_window_aggregation_evidence_text(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
) -> str:
    bounds = _aggregation_dialogue_windows(
        query=query,
        text=text,
        markers=markers,
        identity_terms=identity_terms,
    )
    if len(bounds) <= 1:
        return ""
    rendered = _render_aggregation_windows(text=text, bounds=bounds)
    return rendered if rendered and len(rendered) < len(text) else ""


def _aggregation_dialogue_windows(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
) -> tuple[tuple[int, int], ...]:
    query_variant_sets = _weighted_aggregation_query_variant_sets(
        query,
        identity_terms=identity_terms,
    )
    if not query_variant_sets:
        return ()

    candidates: list[tuple[tuple[float, float, int, int], int, int]] = []
    for marker_index, _marker in enumerate(markers):
        segment_start = markers[marker_index].start()
        segment_end = (
            markers[marker_index + 1].start() if marker_index + 1 < len(markers) else len(text)
        )
        segment_matched_terms, segment_total_hits = _strict_query_window_match_counts(
            text=text[segment_start:segment_end],
            query_variant_sets=query_variant_sets,
        )
        if segment_matched_terms <= 0:
            continue
        start_index = marker_index
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        start = markers[start_index].start()
        end = markers[end_index + 1].start() if end_index + 1 < len(markers) else len(text)
        window_matched_terms, window_total_hits = _strict_query_window_match_counts(
            text=text[start:end],
            query_variant_sets=query_variant_sets,
        )
        key = (
            window_matched_terms,
            window_total_hits,
            -(end - start),
            -start,
        )
        candidates.append((key, start, end))

    selected: list[tuple[int, int]] = []
    selected_chars = 0
    for _key, start, end in sorted(candidates, key=lambda item: item[0], reverse=True):
        if len(selected) >= _MAX_AGGREGATION_DIALOGUE_WINDOWS:
            break
        if any(
            _bounds_overlap(start, end, selected_start, selected_end)
            for selected_start, selected_end in selected
        ):
            continue
        window_chars = end - start
        if selected_chars + window_chars > _MAX_AGGREGATION_EVIDENCE_TEXT_CHARS:
            continue
        selected.append((start, end))
        selected_chars += window_chars

    return tuple(sorted(selected))


def _bounds_overlap(
    start: int,
    end: int,
    selected_start: int,
    selected_end: int,
) -> bool:
    return start < selected_end and selected_start < end


def _render_aggregation_windows(
    *,
    text: str,
    bounds: tuple[tuple[int, int], ...],
) -> str:
    parts: list[str] = []
    for start, end in bounds:
        window = text[start:end].strip()
        if not window:
            continue
        if start > 0:
            window = f"... {window}"
        if end < len(text):
            window = f"{window} ..."
        parts.append(window)
    rendered = " ".join(parts).strip()
    return rendered[:_MAX_AGGREGATION_EVIDENCE_TEXT_CHARS].strip()


def _best_aggregation_dialogue_window(
    *,
    query: str,
    text: str,
    markers: tuple[re.Match[str], ...],
    identity_terms: frozenset[str],
) -> tuple[int, int] | None:
    query_variant_sets = _weighted_aggregation_query_variant_sets(
        query,
        identity_terms=identity_terms,
    )
    if not query_variant_sets:
        return None

    best_bounds: tuple[int, int] | None = None
    best_key: tuple[float, float, int, int] = (-1.0, -1.0, 0, 0)
    for marker_index, _marker in enumerate(markers):
        start_index = max(0, marker_index - 1)
        end_index = min(len(markers) - 1, marker_index + _AGGREGATION_DIALOGUE_WINDOW_AFTER)
        start = markers[start_index].start()
        end = markers[end_index + 1].start() if end_index + 1 < len(markers) else len(text)
        matched_terms, total_hits = _strict_query_window_match_counts(
            text=text[start:end],
            query_variant_sets=query_variant_sets,
        )
        if matched_terms <= 0:
            continue
        start = _first_positive_aggregation_marker_start(
            text=text,
            markers=markers,
            start_index=start_index,
            end_index=end_index,
            query_variant_sets=query_variant_sets,
        )
        key = (matched_terms, total_hits, -(end - start), -start)
        if key > best_key:
            best_key = key
            best_bounds = (start, end)
    return best_bounds


def _first_positive_aggregation_marker_start(
    *,
    text: str,
    markers: tuple[re.Match[str], ...],
    start_index: int,
    end_index: int,
    query_variant_sets: tuple[tuple[set[str], float], ...],
) -> int:
    for index in range(start_index, end_index + 1):
        segment_start = markers[index].start()
        segment_end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        matched_terms, _ = _strict_query_window_match_counts(
            text=text[segment_start:segment_end],
            query_variant_sets=query_variant_sets,
        )
        if matched_terms > 0:
            return segment_start
    return markers[start_index].start()


def _weighted_aggregation_query_variant_sets(
    query: str,
    *,
    identity_terms: frozenset[str] = frozenset(),
) -> tuple[tuple[set[str], float], ...]:
    identity_terms = {
        match.group(0).casefold()
        for match in _STRICT_QUERY_TOKEN_RE.finditer(query)
        if match.group(0)[:1].isupper() and not match.group(0).isupper()
    }.union(identity_terms)
    weighted: list[tuple[set[str], float]] = []
    for term in query_terms(query):
        variants = set(_strict_token_variants(term.raw))
        if not variants:
            continue
        if (
            term.raw.isdigit()
            or term.raw.casefold() in identity_terms
            or variants.intersection(_LOW_SIGNAL_COUNT_AGGREGATION_TERMS)
            or variants.intersection(_LOW_SIGNAL_INVENTORY_AGGREGATION_TERMS)
        ):
            weight = 0.0
        else:
            weight = 1.0
        weighted.append((variants, weight))
    return tuple(weighted)


def _strict_query_window_match_counts(
    *,
    text: str,
    query_variant_sets: tuple[tuple[set[str], float], ...],
) -> tuple[float, float]:
    matched_indexes: set[int] = set()
    matched_score = 0.0
    total_score = 0.0
    for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
        token_variants = set(_strict_token_variants(match.group(0)))
        if not token_variants:
            continue
        for index, (variants, weight) in enumerate(query_variant_sets):
            if token_variants.intersection(variants):
                if index not in matched_indexes:
                    matched_score += weight
                matched_indexes.add(index)
                total_score += weight
                break
    return matched_score, total_score


def _first_strict_query_match_start(*, query: str, text: str) -> int | None:
    query_variant_sets = tuple(
        sorted(
            (set(_strict_token_variants(term.raw)) for term in query_terms(query)),
            key=lambda variants: (len(variants) <= 1, sorted(variants)),
        )
    )
    if not query_variant_sets:
        return None
    for variants in query_variant_sets:
        for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
            token_variants = set(_strict_token_variants(match.group(0)))
            if token_variants.intersection(variants):
                return match.start()
    return None


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _apply_explicit_requirement_guard(
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    items: tuple[ContextItem, ...],
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=items,
    )
    requested_anchor_kinds = set(_coverage_strings(coverage.get("requested_anchor_kinds")))
    missing_anchor_kinds = set(_coverage_strings(coverage.get("missing_anchor_kinds")))
    requested_answer_shapes = set(_coverage_strings(coverage.get("requested_answer_shapes")))
    missing_answer_shapes = set(_coverage_strings(coverage.get("missing_answer_shapes")))
    diagnostics: dict[str, object] = {
        "requirement_guard_items_considered": len(items),
        "requirement_guard_items_dropped": 0,
        "requirement_guard_object_kind_mismatch_drop_count": 0,
        "requirement_guard_relation_mismatch_drop_count": 0,
        "requirement_guard_count_answer_shape_missing_drop_count": 0,
    }
    if "project" in requested_anchor_kinds and "project" in missing_anchor_kinds:
        diagnostics.update(
            {
                "requirement_guard_status": "dropped_missing_project_anchor",
                "requirement_guard_items_dropped": len(items),
            }
        )
        return (), diagnostics
    kept_items = tuple(item for item in items if not _has_object_kind_mismatch(item))
    object_kind_mismatch_drop_count = len(items) - len(kept_items)
    if object_kind_mismatch_drop_count > 0:
        diagnostics["requirement_guard_items_dropped"] = object_kind_mismatch_drop_count
        diagnostics["requirement_guard_object_kind_mismatch_drop_count"] = (
            object_kind_mismatch_drop_count
        )
        diagnostics["requirement_guard_status"] = (
            "dropped_object_kind_mismatch" if not kept_items else "filtered_object_kind_mismatch"
        )
        return kept_items, diagnostics
    kept_items = tuple(item for item in items if not _has_relation_requirement_mismatch(item))
    relation_mismatch_drop_count = len(items) - len(kept_items)
    if relation_mismatch_drop_count > 0:
        diagnostics["requirement_guard_items_dropped"] = relation_mismatch_drop_count
        diagnostics["requirement_guard_relation_mismatch_drop_count"] = (
            relation_mismatch_drop_count
        )
        diagnostics["requirement_guard_status"] = (
            "dropped_relation_requirement_mismatch"
            if not kept_items
            else "filtered_relation_requirement_mismatch"
        )
        return kept_items, diagnostics
    if "count" in requested_answer_shapes and "count" in missing_answer_shapes:
        count_shape_missing_items = tuple(
            item for item in items if _has_explicit_answer_shape_missing(item)
        )
        if len(count_shape_missing_items) == len(items):
            diagnostics["requirement_guard_items_dropped"] = len(items)
            diagnostics["requirement_guard_count_answer_shape_missing_drop_count"] = len(items)
            diagnostics["requirement_guard_status"] = "dropped_missing_count_answer_shape"
            return (), diagnostics
    diagnostics["requirement_guard_status"] = "satisfied"
    return items, diagnostics


def _has_object_kind_mismatch(item: ContextItem) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    return (
        _OBJECT_KIND_MISMATCH_RERANK_REASON in reasons
        and _OBJECT_KIND_MATCH_RERANK_REASON not in reasons
    )


def _has_relation_requirement_mismatch(item: ContextItem) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    return (
        bool(_RELATION_REQUIREMENT_MISMATCH_RERANK_REASONS.intersection(reasons))
        and _RELATION_REQUIREMENT_MATCH_RERANK_REASON not in reasons
        and not _RELATION_REQUIREMENT_SUPPORT_RERANK_REASONS.intersection(reasons)
    )


def _has_explicit_answer_shape_missing(item: ContextItem) -> bool:
    return _ANSWER_SHAPE_MISSING_RERANK_REASON in _deterministic_rerank_reasons(item)


def _deterministic_rerank_reasons(item: ContextItem) -> frozenset[str]:
    provenance = _provenance(dict(item.diagnostics or {}))
    raw_reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(raw_reasons, list | tuple):
        return frozenset()
    return frozenset(str(reason) for reason in raw_reasons if isinstance(reason, str))


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


def _coverage_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


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
