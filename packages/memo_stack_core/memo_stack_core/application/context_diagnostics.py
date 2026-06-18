"""Bounded context diagnostics policy."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from memo_stack_core.application.dto import ContextItem
from memo_stack_core.application.safe_payload import safe_metadata, safe_metadata_text

_MAX_RETRIEVAL_SOURCES = 8
_MAX_RETRIEVAL_SOURCE_CANDIDATES = 64
_MAX_DIAGNOSTIC_MAPPING_ITEMS = 24
_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS = 64
_MAX_DIAGNOSTIC_LIST_ITEMS = 8
_MAX_DIAGNOSTIC_KEY_CHARS = 80
_MAX_DIAGNOSTIC_STRING_CHARS = 240
_MAX_RANKING_REASON_CHARS = 240
_BUNDLE_COUNTER_KEYS = (
    "facts_considered",
    "keyword_chunks_considered",
    "vector_candidate_count",
    "vector_hydrated_count",
    "graph_candidate_count",
    "graph_hydrated_count",
    "stale_vector_drop_count",
    "stale_graph_drop_count",
    "stale_rag_drop_count",
    "stale_facts_considered",
    "stale_facts_used",
    "superseded_facts_considered",
    "superseded_facts_used",
    "temporal_relations_considered",
    "temporal_replacements_applied",
    "temporal_contradictions_considered",
    "temporal_relations_skipped_by_validity",
    "pending_conflict_suggestions_considered",
    "hybrid_items_used",
    "items_considered",
    "items_used",
    "dropped_by_instruction_flag",
    "dropped_by_budget",
    "dropped_by_source_cap",
    "dropped_by_char_cap",
    "multimodal_source_ref_count",
    "items_with_multimodal_source_refs",
    "source_refs_with_page_count",
    "source_refs_with_bbox_count",
    "source_refs_with_time_range_count",
    "rendered_chars",
    "max_rendered_chars",
)
_BUNDLE_COUNTER_DEFAULTS = {
    "facts_considered": 0,
    "keyword_chunks_considered": 0,
    "vector_candidate_count": 0,
    "vector_hydrated_count": 0,
    "graph_candidate_count": 0,
    "graph_hydrated_count": 0,
    "stale_vector_drop_count": 0,
    "stale_graph_drop_count": 0,
    "stale_rag_drop_count": 0,
    "temporal_relations_considered": 0,
    "temporal_replacements_applied": 0,
    "temporal_contradictions_considered": 0,
    "temporal_relations_skipped_by_validity": 0,
    "stale_facts_considered": 0,
    "stale_facts_used": 0,
    "superseded_facts_considered": 0,
    "superseded_facts_used": 0,
    "pending_conflict_suggestions_considered": 0,
    "hybrid_items_used": 0,
    "items_considered": 0,
    "items_used": 0,
    "dropped_by_instruction_flag": 0,
    "dropped_by_budget": 0,
    "dropped_by_source_cap": 0,
    "dropped_by_char_cap": 0,
    "multimodal_source_ref_count": 0,
    "items_with_multimodal_source_refs": 0,
    "source_refs_with_page_count": 0,
    "source_refs_with_bbox_count": 0,
    "source_refs_with_time_range_count": 0,
    "rendered_chars": 0,
    "max_rendered_chars": 0,
}
_BUNDLE_STATUS_DEFAULTS = {
    "vector_status": "unknown",
    "graph_status": "unknown",
    "rag_status": "unknown",
}
_RETRIEVAL_SOURCE_PRIORITY = {
    "vector_chunks": 0,
    "rag_recall": 1,
    "keyword_chunks": 2,
    "graph_hydrated": 3,
    "temporal_supersedes_relation": 4,
    "pending_conflict_suggestion": 5,
    "superseded_review": 6,
    "disputed_review": 7,
    "stale_review": 8,
    "postgres_facts": 9,
}


def context_rank_key(item: ContextItem) -> tuple[float, str, str, str, int, int, str, str]:
    return (
        -round(item.score, 8),
        item.item_type,
        _memory_scope_id(item),
        _source_key(item),
        _chunk_sequence(item),
        _char_start(item),
        _updated_at(item),
        item.item_id,
    )


def context_duplicate_primary_key(
    item: ContextItem,
) -> tuple[int, tuple[float, str, str, str, int, int, str, str], str]:
    sources = _prioritized_retrieval_sources(diagnostic_retrieval_sources(item.diagnostics))
    selected_source = sources[0] if sources else ""
    return (
        _RETRIEVAL_SOURCE_PRIORITY.get(selected_source, 10_000),
        context_rank_key(item),
        item.text,
    )


def normalize_context_item_diagnostics(item: ContextItem) -> ContextItem:
    return replace(item, diagnostics=normalize_context_diagnostics(item.diagnostics))


def normalize_context_diagnostics(diagnostics: object) -> dict[str, object]:
    raw = _as_dict(diagnostics)
    listed_retrieval_sources = diagnostic_retrieval_sources(
        raw,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    selected_source = _safe_retrieval_source(raw.get("retrieval_source"))
    all_retrieval_sources = (
        _ordered_unique(
            (selected_source, *listed_retrieval_sources),
            limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
        )
        if selected_source
        else listed_retrieval_sources
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized = safe_diagnostic_mapping(raw)
    normalized["retrieval_sources"] = list(retrieval_sources)
    if len(all_retrieval_sources) > len(retrieval_sources):
        normalized["retrieval_sources_total"] = len(all_retrieval_sources)
        normalized["retrieval_sources_returned"] = len(retrieval_sources)
        normalized["retrieval_sources_truncated"] = True
    if retrieval_sources and not selected_source:
        selected_source = retrieval_sources[0]
    if selected_source:
        normalized["retrieval_source"] = selected_source
    else:
        normalized.pop("retrieval_source", None)
    ranking_reason = _safe_optional_text(raw.get("ranking_reason"), limit=_MAX_RANKING_REASON_CHARS)
    normalized["ranking_reason"] = ranking_reason or ranking_reason_for(retrieval_sources)
    normalized["score_signals"] = safe_score_signals(raw.get("score_signals"))
    provenance = safe_diagnostic_mapping(raw.get("provenance"))
    if retrieval_sources:
        provenance["retrieval_sources"] = list(retrieval_sources)
    normalized["provenance"] = provenance
    return normalized


def normalize_context_bundle_diagnostics(
    diagnostics: object,
    *,
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    raw = _as_dict(diagnostics)
    normalized = _bounded_mapping(
        safe_metadata(raw, max_items=_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS),
        max_items=_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS,
    )
    normalized["context_assembly_version"] = (
        _safe_optional_text(
            raw.get("context_assembly_version"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown"
    )
    normalized["consistency_mode"] = (
        _safe_optional_text(
            raw.get("consistency_mode"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown"
    )
    for key, default in _BUNDLE_STATUS_DEFAULTS.items():
        normalized[key] = (
            _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
            or default
        )
    all_retrieval_sources = _bundle_retrieval_sources(
        items,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized["retrieval_sources_used"] = list(retrieval_sources)
    normalized["retrieval_sources_total"] = len(all_retrieval_sources)
    normalized["retrieval_sources_returned"] = len(retrieval_sources)
    normalized["retrieval_sources_truncated"] = len(all_retrieval_sources) > len(
        retrieval_sources
    )
    normalized["diagnostics_truncated"] = len(raw) > _MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS
    for key in _BUNDLE_COUNTER_KEYS:
        if key in raw or key in _BUNDLE_COUNTER_DEFAULTS:
            normalized[key] = _non_negative_int(
                raw.get(key),
                default=_BUNDLE_COUNTER_DEFAULTS.get(key, 0),
            )
    normalized.update(_source_ref_counts(items))
    normalized.update(_multimodal_source_ref_counts(items))
    return normalized


def diagnostic_retrieval_sources(
    diagnostics: object,
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    raw = _as_dict(diagnostics)
    raw_sources = raw.get("retrieval_sources")
    if isinstance(raw_sources, (list, tuple)):
        return _ordered_unique(
            tuple(source for value in raw_sources if (source := _safe_retrieval_source(value))),
            limit=limit,
        )
    raw_source = _safe_retrieval_source(raw.get("retrieval_source"))
    return (raw_source,) if raw_source else ()


def merge_diagnostic_retrieval_sources(*diagnostics: object) -> tuple[str, ...]:
    return _ordered_unique(
        tuple(
            source
            for diagnostic in diagnostics
            for source in diagnostic_retrieval_sources(diagnostic)
        )
    )


def merge_context_diagnostics(
    *,
    primary: object,
    secondary: object,
    retrieval_sources: tuple[str, ...],
    source_ref_count: int,
    primary_score: float,
    secondary_score: float,
    hybrid_boost: float,
) -> dict[str, object]:
    primary_raw = _as_dict(primary)
    secondary_raw = _as_dict(secondary)
    merged = safe_diagnostic_mapping({**secondary_raw, **primary_raw})
    prioritized_sources = _prioritized_retrieval_sources(retrieval_sources)
    selected_source = prioritized_sources[0] if prioritized_sources else None
    if selected_source:
        merged["retrieval_source"] = selected_source
    merged["retrieval_sources"] = list(prioritized_sources)
    merged["merged_candidate_count"] = _candidate_count(primary_raw) + _candidate_count(
        secondary_raw
    )
    merged["ranking_reason"] = ranking_reason_for(prioritized_sources)
    merged["score_signals"] = {
        **safe_score_signals(secondary_raw.get("score_signals")),
        **safe_score_signals(primary_raw.get("score_signals")),
        "dedupe_primary_score": round(primary_score, 4),
        "dedupe_secondary_score": round(secondary_score, 4),
        "hybrid_source_count": len(prioritized_sources),
        "hybrid_boost": round(hybrid_boost, 4),
        "source_ref_count": source_ref_count,
    }
    merged["provenance"] = {
        **safe_diagnostic_mapping(secondary_raw.get("provenance")),
        **safe_diagnostic_mapping(primary_raw.get("provenance")),
        "retrieval_sources": list(prioritized_sources),
        "source_ref_count": source_ref_count,
        "selected_retrieval_source": selected_source or "unknown",
    }
    return normalize_context_diagnostics(merged)


def safe_score_signals(value: object) -> dict[str, object]:
    safe = safe_diagnostic_mapping(value)
    return {
        key: item
        for key, item in safe.items()
        if isinstance(item, (int, float, str, bool)) or item is None
    }


def safe_diagnostic_mapping(value: object) -> dict[str, object]:
    return _bounded_mapping(
        safe_metadata(value, max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS),
        max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS,
    )


def ranking_reason_for(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        reason = f"hybrid match via {', '.join(retrieval_sources)}"
    elif retrieval_sources:
        reason = f"matched via {retrieval_sources[0]}"
    else:
        reason = "matched without retrieval channel diagnostics"
    return safe_metadata_text(reason, limit=_MAX_RANKING_REASON_CHARS)


def _bounded_mapping(
    value: object,
    *,
    depth: int = 0,
    max_items: int = _MAX_DIAGNOSTIC_MAPPING_ITEMS,
) -> dict[str, object]:
    if not isinstance(value, dict) or depth > 2:
        return {}
    bounded: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:max_items]:
        key = safe_metadata_text(str(raw_key), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
        if not key or "[redacted]" in key:
            continue
        item = _bounded_value(raw_value, depth=depth, max_items=max_items)
        if _is_safe_diagnostic_value(item):
            bounded[key] = item
    return bounded


def _bounded_value(
    value: object,
    *,
    depth: int,
    max_items: int,
) -> object:
    if isinstance(value, str):
        return safe_metadata_text(value, limit=_MAX_DIAGNOSTIC_STRING_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return _bounded_mapping(value, depth=depth + 1, max_items=max_items)
    if isinstance(value, list):
        safe_items: list[object] = []
        for raw_item in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]:
            item = _bounded_value(raw_item, depth=depth + 1, max_items=max_items)
            if _is_safe_diagnostic_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_safe_diagnostic_value(value: object) -> bool:
    return isinstance(value, (str, int, float, bool, dict, list)) or value is None


def _safe_retrieval_source(value: object) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
    if "[redacted]" in text:
        return None
    return text or None


def _safe_optional_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=limit).strip()
    return text or None


def _candidate_count(diagnostics: dict[str, Any]) -> int:
    value = diagnostics.get("merged_candidate_count")
    return value if isinstance(value, int) and value > 0 else 1


def _bundle_retrieval_sources(
    items: tuple[ContextItem, ...],
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    sources = _ordered_unique(
        tuple(
            source
            for item in items
            for source in diagnostic_retrieval_sources(item.diagnostics, limit=limit)
        ),
        limit=limit,
    )
    return _prioritized_retrieval_sources(sources)


def _source_ref_counts(items: tuple[ContextItem, ...]) -> dict[str, int | bool]:
    returned = sum(len(item.source_refs) for item in items)
    total = sum(max(len(item.source_refs), _diagnostic_source_ref_count(item)) for item in items)
    return {
        "source_refs_total": total,
        "source_refs_returned": returned,
        "source_refs_truncated": total > returned,
    }


def _diagnostic_source_ref_count(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    score_signals = _as_dict(diagnostics.get("score_signals"))
    for value in (
        diagnostics.get("source_ref_count"),
        provenance.get("source_ref_count"),
        score_signals.get("source_ref_count"),
    ):
        count = _optional_non_negative_int(value)
        if count is not None:
            return count
    return len(item.source_refs)


def _multimodal_source_ref_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    refs = tuple(ref for item in items for ref in item.source_refs)
    page_count = sum(1 for ref in refs if ref.page_number is not None)
    bbox_count = sum(1 for ref in refs if ref.bbox is not None)
    time_count = sum(
        1
        for ref in refs
        if ref.time_start_ms is not None or ref.time_end_ms is not None
    )
    return {
        "multimodal_source_ref_count": sum(1 for ref in refs if _is_multimodal_source_ref(ref)),
        "items_with_multimodal_source_refs": sum(
            1 for item in items if any(_is_multimodal_source_ref(ref) for ref in item.source_refs)
        ),
        "source_refs_with_page_count": page_count,
        "source_refs_with_bbox_count": bbox_count,
        "source_refs_with_time_range_count": time_count,
    }


def _is_multimodal_source_ref(ref: Any) -> bool:
    return (
        ref.page_number is not None
        or ref.bbox is not None
        or ref.time_start_ms is not None
        or ref.time_end_ms is not None
    )


def _prioritized_retrieval_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    indexed = {source: index for index, source in enumerate(sources)}
    return tuple(
        sorted(
            sources,
            key=lambda source: (
                _RETRIEVAL_SOURCE_PRIORITY.get(source, 10_000),
                indexed[source],
            ),
        )
    )


def _non_negative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return default


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return None


def _updated_at(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    if not isinstance(diagnostics, dict):
        return ""
    value = diagnostics.get("updated_at") or diagnostics.get("created_at") or ""
    return str(value)


def _memory_scope_id(item: ContextItem) -> str:
    diagnostics = _as_dict(item.diagnostics)
    return str(diagnostics.get("memory_scope_id") or "")


def _source_key(item: ContextItem) -> str:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    source_type = diagnostics.get("source_type") or provenance.get("source_type")
    source_id = diagnostics.get("source_id") or provenance.get("source_id")
    if (source_type is None or source_id is None) and item.source_refs:
        ref = item.source_refs[0]
        source_type = source_type or ref.source_type
        source_id = source_id or ref.source_id
    return f"{source_type or ''}:{source_id or ''}"


def _chunk_sequence(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    return _rank_int(diagnostics.get("chunk_sequence") or provenance.get("sequence"))


def _char_start(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    value = diagnostics.get("char_start") or provenance.get("char_start")
    if value is None and item.source_refs:
        value = item.source_refs[0].char_start
    return _rank_int(value)


def _rank_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 2_147_483_647


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ordered_unique(
    values: tuple[str, ...],
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return tuple(result)
