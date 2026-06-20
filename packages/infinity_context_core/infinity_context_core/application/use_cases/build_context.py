"""Build prompt-safe memory context from canonical and derived candidates."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

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
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
)
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)
from infinity_context_core.application.context_hydration import ContextHydrator
from infinity_context_core.application.context_link_expansion import ApprovedContextLinkExpander
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_policy import (
    is_context_anchor_visible,
    is_context_fact_visible,
    is_context_review_fact_visible,
)
from infinity_context_core.application.context_ranking import dedupe_rank_items
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    query_relevance_score_signals,
    score_query_relevance,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
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
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._vector_index = vector_index
        self._graph_index = graph_index
        self._embedder = embedder
        self._clock = clock
        self._packer = packer or ContextPacker()
        self._hydrator = ContextHydrator(uow_factory=uow_factory, clock=clock)
        self._canonical_collector = CanonicalContextCollector(uow_factory=uow_factory)
        self._vector_collector = VectorContextCollector(
            vector_index=vector_index,
            embedder=embedder,
            hydrator=self._hydrator,
        )
        self._graph_collector = GraphContextCollector(
            graph_index=graph_index,
            hydrator=self._hydrator,
        )
        self._rag_collector = RagContextCollector(
            rag_recall=rag_recall,
            hydrator=self._hydrator,
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
        memory_scope_ids = tuple(str(memory_scope_id) for memory_scope_id in query.memory_scope_ids)
        canonical = await self._canonical_collector.collect(
            query=query, memory_scope_ids=memory_scope_ids
        )

        diagnostics: dict[str, object] = {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "consistency_mode": query.consistency_mode.value,
            "facts_considered": len(canonical.facts),
            "keyword_chunks_considered": len(canonical.keyword_chunks),
            "anchors_considered": len(canonical.anchors),
            "anchors_used": 0,
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
            vector_chunks = await self._vector_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
            )
            graph_items = await self._graph_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
            )
            rag_items = await self._rag_collector.collect(
                query=query,
                memory_scope_ids=memory_scope_ids,
                diagnostics=diagnostics,
            )

        items: list[ContextItem] = []
        now = self._clock.now() if self._clock is not None else None
        for fact in canonical.facts:
            items.append(_fact_context_item(fact, now=now, query_text=query.query))
        anchors_used = 0
        selected_anchor_items: list[tuple[MemoryAnchor, ContextItem]] = []
        for anchor in canonical.anchors:
            if not is_context_anchor_visible(
                anchor,
                query=query,
                memory_scope_ids=memory_scope_ids,
                now=now,
            ):
                continue
            relevance = score_query_relevance(
                query=query.query,
                text=anchor_retrieval_text(anchor),
            )
            if not is_query_relevance_sufficient(relevance):
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
            )
            items.append(anchor_item)
            selected_anchor_items.append((anchor, anchor_item))
            anchors_used += 1
        diagnostics["anchors_used"] = anchors_used
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
        for chunk in canonical.keyword_chunks:
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            relevance = score_query_relevance(query=query.query, text=chunk_text)
            score = min(0.87, round(0.75 + relevance.score_boost, 4))
            items.append(
                _chunk_context_item(
                    chunk=chunk,
                    text=chunk_text,
                    retrieval_source="keyword_chunks",
                    base_score=0.75,
                    score=score,
                    relevance=relevance,
                    query_text=query.query,
                )
            )
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

        deduped = await self._hydrator.revalidate_visible_items(
            dedupe_rank_items(tuple(items)),
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        temporal_items, temporal_diagnostics = await self._apply_temporal_relation_signals(
            items=deduped,
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        artifact_evidence_items = await self._artifact_evidence_collector.collect(
            query=query,
            memory_scope_ids=memory_scope_ids,
            diagnostics=diagnostics,
        )
        include_stale_review = query.include_stale or query.include_superseded
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
        pending_review_items = await self._pending_conflict_items(
            query=query,
            visible_fact_ids=tuple(
                item.item_id for item in temporal_items if item.item_type == "fact"
            ),
        )
        linked_context = await self._context_link_expander.collect(
            items=(*temporal_items, *artifact_evidence_items),
            query=query,
            memory_scope_ids=memory_scope_ids,
        )
        linked_temporal_items, linked_temporal_diagnostics = (
            await self._apply_temporal_relation_signals(
                items=linked_context.items,
                query=query,
                memory_scope_ids=memory_scope_ids,
            )
        )
        result = self._packer.pack(
            bundle_id=self._ids.new_id("ctx"),
            items=dedupe_rank_items(
                (
                    *temporal_items,
                    *artifact_evidence_items,
                    *linked_temporal_items,
                    *stale_review_items,
                    *pending_review_items,
                )
            ),
            token_budget=query.token_budget,
            max_rendered_chars=query.max_rendered_chars,
        )
        diagnostics.update(temporal_diagnostics)
        diagnostics.update(stale_diagnostics)
        diagnostics.update(linked_context.diagnostics)
        diagnostics.update(
            {
                f"linked_{key}": value
                for key, value in linked_temporal_diagnostics.items()
            }
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
                            _stale_review_item(
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
                    conflict_fact_id = _suggestion_conflict_fact_id(suggestion)
                    if conflict_fact_id not in visible_fact_id_set:
                        continue
                    items.append(
                        _pending_review_suggestion_item(
                            suggestion=suggestion,
                            target_fact_id=conflict_fact_id,
                        )
                    )
                    if len(items) >= max_items:
                        return tuple(items)
        return tuple(items)


def _suggestion_conflict_fact_id(suggestion) -> str | None:
    payload = suggestion.review_payload or {}
    for key in ("conflicting_fact_id", "conflict_fact_id", "possible_conflict_fact_id"):
        value = payload.get(key)
        if value:
            return str(value)
    if suggestion.target_fact_id:
        return str(suggestion.target_fact_id)
    return None


def _conflict_suggestion_text(
    *,
    candidate_text: str,
    operation: str,
    conflict_fact_id: str,
) -> str:
    return (
        f"Pending review {operation} suggestion for active fact {conflict_fact_id}: "
        f"{candidate_text}"
    )


def _pending_review_suggestion_item(
    *,
    suggestion,
    target_fact_id: str,
) -> ContextItem:
    review_kind = _suggestion_review_kind(suggestion)
    retrieval_source = _pending_suggestion_retrieval_source(review_kind)
    score = _pending_suggestion_score(review_kind)
    review_resolution = _suggestion_review_resolution_diagnostics(suggestion)
    review_match = _suggestion_review_match_diagnostics(suggestion)
    return ContextItem(
        item_id=str(suggestion.id),
        item_type="suggestion",
        text=_pending_suggestion_text(
            candidate_text=suggestion.candidate_text,
            operation=suggestion.operation.value,
            review_kind=review_kind,
            target_fact_id=target_fact_id,
        ),
        score=score,
        source_refs=suggestion.source_refs,
        diagnostics={
            "memory_scope_id": str(suggestion.memory_scope_id),
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "ranking_reason": _pending_suggestion_ranking_reason(review_kind),
            "review_kind": review_kind,
            "score_signals": {
                "base_score": score,
                "review_status_boost": 0.0,
                "canonical": False,
            },
            "provenance": {
                "retrieval_sources": [retrieval_source],
                "source_ref_count": len(suggestion.source_refs),
                "target_fact_id": target_fact_id,
                "review_kind": review_kind,
                "candidate_fingerprint": suggestion.candidate_fingerprint,
                **review_match,
            },
            "status": suggestion.status.value,
            "operation": suggestion.operation.value,
            "canonical": False,
            "target_fact_id": target_fact_id,
            "conflicting_fact_id": target_fact_id,
            **review_match,
            **review_resolution,
        },
    )


def _suggestion_review_kind(suggestion) -> str:
    payload = suggestion.review_payload or {}
    value = payload.get("review_kind")
    return str(value).strip() if value else "conflict_review"


def _suggestion_review_resolution_diagnostics(suggestion) -> dict[str, object]:
    payload = suggestion.review_payload or {}
    diagnostics: dict[str, object] = {}
    recommended_action = _bounded_metadata_text(payload.get("recommended_action"), limit=80)
    default_resolution = _bounded_metadata_text(payload.get("default_resolution"), limit=80)
    if recommended_action:
        diagnostics["review_recommended_action"] = recommended_action
    if default_resolution:
        diagnostics["review_default_resolution"] = default_resolution
    options = payload.get("resolution_options")
    if not isinstance(options, list):
        return diagnostics
    safe_options: list[dict[str, str]] = []
    for option in options[:8]:
        if not isinstance(option, dict):
            continue
        safe_option = {
            key: value
            for key, value in (
                ("id", _bounded_metadata_text(option.get("id"), limit=80)),
                ("review_action", _bounded_metadata_text(option.get("review_action"), limit=40)),
                ("effect", _bounded_metadata_text(option.get("effect"), limit=120)),
                ("availability", _bounded_metadata_text(option.get("availability"), limit=40)),
            )
            if value
        }
        if safe_option:
            safe_options.append(safe_option)
    if safe_options:
        diagnostics["review_resolution_options"] = safe_options
    return diagnostics


def _suggestion_review_match_diagnostics(suggestion) -> dict[str, object]:
    payload = suggestion.review_payload or {}
    diagnostics: dict[str, object] = {}
    for key in (
        "dedupe_match_type",
        "conflict_match_type",
        "duplicate_fact_id",
        "duplicate_fact_version",
        "target_fact_version",
    ):
        value = _bounded_metadata_text(payload.get(key), limit=120)
        if value:
            diagnostics[key] = value
    score = _optional_float(payload.get("dedupe_score") or payload.get("conflict_score"))
    if score is not None:
        diagnostics["review_match_score"] = score
    for key in (
        "dedupe_reason_codes",
        "dedupe_overlap_terms",
        "conflict_reason_codes",
        "conflict_overlap_terms",
    ):
        values = _bounded_metadata_text_list(payload.get(key), limit=80, max_items=12)
        if values:
            diagnostics[key] = values
    reason_codes = _bounded_metadata_text_list(
        payload.get("dedupe_reason_codes") or payload.get("conflict_reason_codes"),
        limit=80,
        max_items=12,
    )
    if reason_codes:
        diagnostics["review_reason_codes"] = reason_codes
    return diagnostics


def _bounded_metadata_text_list(
    value: object,
    *,
    limit: int,
    max_items: int,
) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    safe_values: list[str] = []
    for item in value[:max_items]:
        text = _bounded_metadata_text(item, limit=limit)
        if text:
            safe_values.append(text)
    return safe_values


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bounded_metadata_text(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _pending_suggestion_retrieval_source(review_kind: str) -> str:
    if review_kind == "duplicate_fact_merge":
        return "pending_duplicate_merge_suggestion"
    return "pending_conflict_suggestion"


def _pending_suggestion_score(review_kind: str) -> float:
    if review_kind == "duplicate_fact_merge":
        return 0.93
    return 0.94


def _pending_suggestion_ranking_reason(review_kind: str) -> str:
    if review_kind == "duplicate_fact_merge":
        return "pending duplicate merge can update visible active fact without duplicating memory"
    return "pending suggestion contradicts visible active fact"


def _pending_suggestion_text(
    *,
    candidate_text: str,
    operation: str,
    review_kind: str,
    target_fact_id: str,
) -> str:
    if review_kind == "duplicate_fact_merge":
        return (
            f"Pending duplicate merge {operation} suggestion for active fact "
            f"{target_fact_id}: {candidate_text}"
        )
    return _conflict_suggestion_text(
        candidate_text=candidate_text,
        operation=operation,
        conflict_fact_id=target_fact_id,
    )


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
    return ContextItem(
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
    )


def _stale_review_item(
    fact: MemoryFact,
    *,
    relevance: QueryRelevance,
    query_text: str,
) -> ContextItem:
    score = min(0.64, round(0.44 + relevance.score_boost, 4))
    status = fact.status.value
    retrieval_source = _stale_review_retrieval_source(status)
    stale_reason = f"fact_status_{status}"
    snippet = query_focused_snippet(query=query_text, text=fact.text)
    source_refs = source_refs_with_query_snippet(fact.source_refs, snippet)
    return ContextItem(
        item_id=str(fact.id),
        item_type="fact",
        text=fact.text,
        score=score,
        source_refs=source_refs,
        diagnostics={
            "memory_scope_id": str(fact.memory_scope_id),
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "ranking_reason": _stale_review_ranking_reason(status),
            "review_only": True,
            "stale_reason": stale_reason,
            "score_signals": {
                "base_score": 0.44,
                "final_score": score,
                "retrieval_channel": retrieval_source,
                "fact_status": fact.status.value,
                **query_relevance_score_signals(relevance),
                **query_snippet_score_signals(snippet),
            },
            "provenance": {
                "retrieval_sources": [retrieval_source],
                "source_ref_count": len(source_refs),
                "fact_status": fact.status.value,
                "fact_version": fact.version,
                "visibility": "review_only",
                **query_snippet_diagnostics(snippet),
            },
            "confidence": fact.confidence.value,
            "trust_level": fact.trust_level.value,
            "updated_at": fact.updated_at.isoformat(),
            **query_snippet_diagnostics(snippet),
        },
    )


def _stale_review_retrieval_source(status: str) -> str:
    if status == "superseded":
        return "superseded_review"
    if status == "disputed":
        return "disputed_review"
    return "stale_review"


def _stale_review_ranking_reason(status: str) -> str:
    if status == "superseded":
        return "included only for review because include_superseded is true"
    return f"included only for stale memory review because status is {status}"


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


def _chunk_context_item(
    *,
    chunk: MemoryChunk,
    text: str,
    retrieval_source: str,
    base_score: float,
    score: float,
    relevance: QueryRelevance | None,
    query_text: str,
) -> ContextItem:
    snippet = query_focused_snippet(query=query_text, text=text)
    source_refs = source_refs_with_query_snippet(
        chunk_source_refs(chunk, text_preview=(snippet.text if snippet else text[:200])),
        snippet,
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
    return ContextItem(
        item_id=str(chunk.id),
        item_type="chunk",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics={
            "memory_scope_id": str(chunk.memory_scope_id),
            "retrieval_source": retrieval_source,
            "retrieval_sources": [retrieval_source],
            "ranking_reason": f"matched via {retrieval_source}",
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
            },
            "source_type": chunk.source_type,
            "source_id": chunk.source_external_id,
            "chunk_sequence": chunk.sequence,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            **source_ref_location_summary(source_refs),
            **query_snippet_diagnostics(snippet),
        },
    )


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


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
