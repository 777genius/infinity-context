"""Context item projection helpers for build-context orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_ranking import (
    best_query_relevance,
    query_expansion_reason_priority,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    query_relevance_score_signals,
    score_query_relevance,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _focused_exact_source_repair_text,
    _source_sibling_answer_continuation_hydration_request_items,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank as _country_destination_answer_support_rank,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence as _source_sibling_answer_evidence,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.application.temporal_validity import is_temporal_window_current
from infinity_context_core.domain.aggregation_admission import AggregationIntent
from infinity_context_core.domain.entities import (
    DataClassification,
    LifecycleStatus,
    MemoryChunk,
    MemoryFact,
    MemoryFactRelation,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_QUESTION_OR_REQUEST_TURN_RE = re.compile(
    r"\?|\b(?:who|what|where|when|why|how|which)\b|"
    r"\b(?:can|could|would|will|do|does|did|is|are|was|were|have|has|had)\s+"
    r"(?:you|they|these|those|it|that|he|she|we|i)\b|"
    r"\b(?:tell\s+me|show\s+me|let\s+me\s+know|any\s+"
    r"(?:pointers?|recommendations?|suggestions?))\b",
    re.IGNORECASE,
)
_MAX_EXACT_SOURCE_REF_HYDRATION_ITEMS = 48


@dataclass(frozen=True)
class _ExactTurnHydrationRequestPlan:
    reason_by_id: Mapping[str, str]
    next_answer_source_ids: frozenset[str]
    previous_question_source_ids: frozenset[str]


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
    query_plan_slot: str = "",
    admission_reason: str = "",
    relaxed_admission: bool = False,
    numeric_corroboration: bool = False,
    continuity_only: bool = False,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "keyword_aggregation_strict_term_hits": 0 if continuity_only else strict_hits,
        "keyword_aggregation_group_match": int(not continuity_only),
        "keyword_aggregation_relaxed_admission": int(relaxed_admission),
        "keyword_aggregation_numeric_corroboration": int(numeric_corroboration),
        "keyword_aggregation_continuity_only": int(continuity_only),
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "keyword_aggregation_source_group": source_group,
        "keyword_aggregation_query_plan_slot": query_plan_slot,
        "keyword_aggregation_admission_reason": admission_reason,
        "keyword_aggregation_distinctive_hits": strict_hits,
    }
    return replace(item, diagnostics=diagnostics)


def _partition_aggregation_continuity_items(
    items: tuple[ContextItem, ...],
) -> tuple[tuple[ContextItem, ...], tuple[ContextItem, ...]]:
    ranked: list[ContextItem] = []
    continuity: list[ContextItem] = []
    for item in items:
        signals = _score_signals(item.diagnostics)
        target = continuity if signals.get("keyword_aggregation_continuity_only") == 1 else ranked
        target.append(item)
    return tuple(ranked), tuple(continuity)


def _promote_aggregation_continuity_items(
    items: tuple[ContextItem, ...],
    *,
    intent: AggregationIntent | None,
    ordinary_count: int,
) -> tuple[ContextItem, ...]:
    """Promote only the intent-bounded, source-slot selection materialized upstream."""

    if intent is AggregationIntent.COUNT and ordinary_count >= 4:
        return ()
    return tuple(replace(item, score=0.985) for item in items)


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
                or not _source_ref_needs_exact_turn_body_hydration(item, source_id=source_id)
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


async def _exact_source_ref_hydration_items(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    query: BuildContextQuery,
    query_plan: QueryExpansionPlan,
    memory_scope_ids: tuple[str, ...],
    source_items: tuple[ContextItem, ...],
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    """Hydrate exact canonical turn bodies requested by projected source refs."""

    request_plan = _exact_turn_source_ref_hydration_request_plan(source_items)
    source_reason_by_id = request_plan.reason_by_id
    source_ids = tuple(source_reason_by_id)[:_MAX_EXACT_SOURCE_REF_HYDRATION_ITEMS]
    diagnostics: dict[str, object] = {
        "exact_source_ref_hydration_requested": len(source_ids),
        "exact_source_ref_hydration_chunks_found": 0,
        "exact_source_ref_hydration_items_used": 0,
        "exact_source_ref_hydration_sources_sample": list(source_ids[:24]),
    }
    if not source_ids:
        return (), diagnostics
    async with uow_factory() as uow:
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
    return _QUESTION_OR_REQUEST_TURN_RE.search(_dialogue_turn_body(text)) is not None


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
    return bool(marker) and not _text_has_dialogue_turn_body(item.text, marker=marker)


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
    score_signals = (item.diagnostics or {}).get("score_signals")
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
    return (
        str(provenance.get("source_sibling_answer_evidence_query") or "")
        if isinstance(provenance, dict)
        else ""
    )


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
    return any(
        _country_destination_answer_support_rank(
            expansion_query=query,
            text=_focused_exact_source_repair_text(
                text=item.text,
                source_id=f"synthetic:{marker}:turn",
            ),
            has_exact_turn=True,
        )
        < 5
        for marker in dict.fromkeys(_DIALOGUE_MARKER_RE.findall(item.text))
    )


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


def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


def _is_weak_non_temporal_replacement(
    query_text: str,
    diagnostics: dict[str, object],
) -> bool:
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
