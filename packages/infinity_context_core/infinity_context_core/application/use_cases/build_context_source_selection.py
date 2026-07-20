"""Source-neighbor selection helpers for build-context orchestration."""

from __future__ import annotations

from infinity_context_core.application.context_policy import (
    is_context_fact_visible,
    is_context_review_fact_visible,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_review_items import (
    pending_review_suggestion_item,
    stale_review_item,
    suggestion_conflict_fact_id,
)
from infinity_context_core.application.context_source_siblings import (
    _ObligationEvidenceProjection,
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
    project_source_sibling_obligation_evidence as _project_obligation_evidence,
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
    source_sibling_relevance_allowed as _source_sibling_relevance_allowed,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_score as _source_sibling_score,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_score_cap as _source_sibling_score_cap,
)
from infinity_context_core.application.context_source_siblings import (
    with_source_sibling_score_signals as _with_source_sibling_score_signals,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _annotate_temporal_relation,
    _chunk_context_item,
    _is_neighbor_chunk_visible,
    _temporal_relation_is_current,
    _temporal_replacement_item,
)
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _aggregation_source_group,
    _best_query_relevance_cached,
    _prioritize_source_sibling_answer_evidence_seed_chunks,
    _prioritized_source_sibling_seed_groups,
    _query_plan_requests_list_source_sibling_depth,
    _query_plan_requests_named_preference_source_sibling_diversity,
    _query_plan_requests_place_source_sibling_diversity,
    _query_plan_requests_relationship_status_source_sibling_diversity,
    _source_sibling_answer_evidence_extra_key,
    _source_sibling_group_backfill_plan,
    _source_sibling_group_limit_for_request,
)
from infinity_context_core.domain.entities import MemoryChunk
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_KEYWORD_NEIGHBOR_SEQUENCE_OFFSETS = (1, -1, 2, -2, 3, -3)
_LIST_SOURCE_SIBLING_ITEM_LIMIT = 48


async def _keyword_neighbor_chunk_items(
    *,
    uow_factory: UnitOfWorkFactoryPort,
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
    async with uow_factory() as uow:
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
                    expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
                        query_plan,
                        text=chunk_text,
                        cache=query_relevance_cache,
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
    *,
    uow_factory: UnitOfWorkFactoryPort,
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
    async with uow_factory() as uow:
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
        source_groups = _prioritized_source_sibling_seed_groups(
            source_groups=source_groups,
            seed_chunks=seed_chunks,
            evidence_chunks=tuple(candidates),
            query_plan=query_plan,
            query_relevance_cache=query_relevance_cache,
            limit=source_group_limit,
        )
        admitted_groups = set(source_groups)
        candidates = [
            chunk for chunk in candidates if _aggregation_source_group(chunk) in admitted_groups
        ]
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
            bool,
            _ObligationEvidenceProjection,
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
            expansion_query=expansion_query,
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
        obligation_evidence = (
            _project_obligation_evidence(
                query_text=query.query,
                semantic_query_text=expansion_query,
                relevance=relevance,
                text=chunk.text,
            )
            if rank.group_level_seed
            else _ObligationEvidenceProjection(rank=1, text=chunk_text)
        )
        if obligation_evidence.rank == 2:
            skipped += 1
            continue
        answer_evidence = obligation_evidence.rank == 0 or (
            obligation_evidence.rank == 1
            and _source_sibling_answer_evidence(
                expansion_query=expansion_query,
                expansion_reason=expansion_reason,
                text=chunk_text,
            )
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
                    obligation_evidence_rank=obligation_evidence.rank,
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
                obligation_evidence,
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
        obligation_evidence,
    ) in ranked_candidates:
        companion_slot = ""
        answer_evidence_extra_key = _source_sibling_answer_evidence_extra_key(
            chunk,
            deep_list_coverage=answer_evidence_group_diversity,
        )
        answer_evidence_extra_limit = 24 if answer_evidence_group_diversity else 12
        answer_evidence_extra_key_limit = 2 if answer_evidence_group_diversity else 1
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
            text=obligation_evidence.text if obligation_evidence.applied else chunk_text,
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
                answer_evidence_query=(
                    query.query
                    if obligation_evidence.rank == 0
                    else expansion_query
                    if answer_evidence
                    else ""
                ),
                obligation_evidence_rank=obligation_evidence.rank,
                obligation_projection=obligation_evidence,
                canonical_text_length=len(chunk.text),
            )
        )

    return tuple(items), {
        "keyword_source_sibling_chunks_considered": considered,
        "keyword_source_sibling_chunks_used": len(items),
        "keyword_source_sibling_chunks_skipped": skipped,
        "keyword_source_sibling_group_count": len(source_groups),
        "keyword_source_sibling_candidate_limit": candidate_limit,
        "keyword_source_sibling_deep_list_coverage": deep_list_coverage,
        "keyword_source_sibling_place_list_answer_diversity": place_list_answer_diversity,
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


async def _apply_temporal_relation_signals(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort | None,
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

    now = clock.now() if clock is not None else None
    by_fact_id = {item.item_id: item for item in items}
    invalidated_fact_ids: set[str] = set()
    replacement_items: dict[str, ContextItem] = {}
    relations_considered = 0
    relations_skipped_by_validity = 0
    contradictions_considered = 0
    async with uow_factory() as uow:
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
    *,
    uow_factory: UnitOfWorkFactoryPort,
    clock: ClockPort | None,
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

    now = clock.now() if clock is not None else None
    candidate_limit = min(200, max(query.max_facts * 4, query.max_facts))
    items: list[ContextItem] = []
    considered = 0
    superseded_considered = 0
    superseded_used = 0
    statuses = ("superseded", "disputed") if query.include_stale else ("superseded",)
    async with uow_factory() as uow:
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
    *,
    uow_factory: UnitOfWorkFactoryPort,
    query: BuildContextQuery,
    visible_fact_ids: tuple[str, ...],
) -> tuple[ContextItem, ...]:
    max_items = max(0, query.max_conflicting_suggestions)
    visible_fact_id_set = set(visible_fact_ids)
    if max_items <= 0 or not visible_fact_id_set:
        return ()

    items: list[ContextItem] = []
    async with uow_factory() as uow:
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
