"""Build prompt-safe memory context from canonical and derived candidates."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter

import infinity_context_core.application.context_source_siblings as _source_siblings_module
from infinity_context_core.application import (
    context_aggregation_evidence_text as _aggregation_evidence_module,
)
from infinity_context_core.application.context_anchor_relations import related_anchor_context_items
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
from infinity_context_core.application.context_link_expansion import ApprovedContextLinkExpander
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_policy import (
    is_context_anchor_visible,
    is_context_fact_visible,
)
from infinity_context_core.application.context_query_decomposition import (
    build_query_decomposition_plan,
)
from infinity_context_core.application.context_query_expansion import build_query_expansion_plan
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
    dedupe_rank_items,
    keyword_chunk_score,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_chunk_candidate_relevance_sufficient,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_requirement_guard import (
    _apply_explicit_requirement_guard,
)
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _pre_pack_candidate_source_ref_diagnostics,
    _restore_exact_source_sibling_answer_evidence_items,
    _source_sibling_answer_evidence_stage_diagnostics,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_related_turn_anchor_evidence as _related_turn_anchor_evidence,
)
from infinity_context_core.application.context_temporal_query import (
    apply_temporal_query_intent_boosts,
    build_temporal_query_intent,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import (
    BuildContextQuery,
    ConsistencyMode,
    ContextBundle,
    ContextItem,
)
from infinity_context_core.application.use_cases import (
    build_context_item_projection as _item_projection_module,
)
from infinity_context_core.application.use_cases import (
    build_context_keyword_aggregation as _keyword_aggregation_module,
)
from infinity_context_core.application.use_cases import (
    build_context_source_selection as _source_selection_module,
)
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _best_query_relevance_cached,
    _chunk_context_item,
    _exact_source_ref_hydration_items,
    _fact_context_item,
    _partition_aggregation_continuity_items,
)
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _aggregation_admission_seed_chunks,
    _context_item_aggregation_source_groups,
    _dedupe_chunks_by_id,
    _keyword_aggregation_chunk_items,
    _keyword_anchor_conflict_allowed,
    _prioritized_chunks_for_source_groups,
    _ranked_keyword_chunk_scores,
    _selected_keyword_prompt_items,
    _source_sibling_answer_evidence_query_match,
    _strict_query_term_variant_sets,
    _strict_query_variant_hits,
)
from infinity_context_core.application.use_cases.build_context_source_selection import (
    _apply_temporal_relation_signals,
    _keyword_neighbor_chunk_items,
    _keyword_source_sibling_chunk_items,
    _pending_conflict_items,
    _stale_review_items,
)
from infinity_context_core.domain.entities import MemoryAnchor, MemoryChunk
from infinity_context_core.ports.adapters import EmbeddingPort, GraphMemoryPort, VectorMemoryPort
from infinity_context_core.ports.assets import BlobStoragePort
from infinity_context_core.ports.capabilities import RagRecallPort
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_ScoredKeywordPromptItem = tuple[int, int, int, float, float, int, str, ContextItem]


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
        stage_started_at = perf_counter()
        (
            aggregation_seed_chunks,
            aggregation_seed_diagnostics,
        ) = await _aggregation_admission_seed_chunks(
            uow_factory=self._uow_factory,
            query=query,
            query_plan=query_expansion_plan,
            canonical_chunks=canonical.keyword_chunks,
        )
        diagnostics.update(aggregation_seed_diagnostics)
        _record_stage_timing(diagnostics, "keyword_aggregation_seed", stage_started_at)
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
            seed_chunks=aggregation_seed_chunks,
            ordinary_seed_ids=frozenset(str(chunk.id) for chunk in used_keyword_chunks),
            query_relevance_cache=query_relevance_cache,
        )
        _record_stage_timing(diagnostics, "keyword_aggregation", stage_started_at)
        diagnostics.update(aggregation_diagnostics)
        ranked_aggregation_items, aggregation_continuity_items = (
            _partition_aggregation_continuity_items(aggregation_items)
        )
        promoted_continuity_items = _item_projection_module._promote_aggregation_continuity_items(
            aggregation_continuity_items,
            intent=_keyword_aggregation_module._keyword_aggregation_intent(
                query.query, query_plan=query_expansion_plan
            ),
            ordinary_count=len(ranked_aggregation_items),
        )
        diagnostics["keyword_aggregation_continuity_items_promoted"] = len(
            promoted_continuity_items
        )
        diagnostics["keyword_aggregation_continuity_items_suppressed"] = len(
            aggregation_continuity_items
        ) - len(promoted_continuity_items)
        items.extend(ranked_aggregation_items)
        aggregation_source_groups = _context_item_aggregation_source_groups(
            ranked_aggregation_items
        )
        stage_started_at = perf_counter()
        neighbor_items, neighbor_diagnostics = await _keyword_neighbor_chunk_items(
            uow_factory=self._uow_factory,
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
            chunk for _, _, _, _, _, _, chunk in _ranked_keyword_chunk_scores(scored_keyword_chunks)
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
        sibling_items, sibling_diagnostics = await _keyword_source_sibling_chunk_items(
            uow_factory=self._uow_factory,
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
        (
            exact_source_ref_items,
            exact_source_ref_diagnostics,
        ) = await _exact_source_ref_hydration_items(
            uow_factory=self._uow_factory,
            query=query,
            query_plan=query_expansion_plan,
            memory_scope_ids=memory_scope_ids,
            source_items=tuple(items),
            query_relevance_cache=query_relevance_cache,
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
        items.extend(promoted_continuity_items)

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
        temporal_items, temporal_diagnostics = await _apply_temporal_relation_signals(
            uow_factory=self._uow_factory,
            clock=self._clock,
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
            await _stale_review_items(
                uow_factory=self._uow_factory,
                clock=self._clock,
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
        pending_review_items = await _pending_conflict_items(
            uow_factory=self._uow_factory,
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
        ) = await _apply_temporal_relation_signals(
            uow_factory=self._uow_factory,
            clock=self._clock,
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
        guarded_items, requirement_guard_diagnostics = _apply_explicit_requirement_guard(
            query=query.query,
            query_anchor_intent=query_anchor_intent,
            items=candidate_items,
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


_COMPATIBILITY_HELPER_MODULES = (
    _aggregation_evidence_module,
    _source_siblings_module,
    _item_projection_module,
    _keyword_aggregation_module,
    _source_selection_module,
)


def __getattr__(name: str) -> object:
    """Keep moved private test seams available while orchestration stays small."""

    if name.startswith("_"):
        for helper_module in _COMPATIBILITY_HELPER_MODULES:
            if hasattr(helper_module, name):
                return getattr(helper_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
