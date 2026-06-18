"""Typed context response helpers for the public Memo Stack SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from memo_stack_sdk._redaction import redact_sensitive_text

MAX_RETRIEVAL_SOURCES = 8
MAX_SOURCE_REFS = 20
MAX_MAPPING_ITEMS = 24
MAX_LIST_ITEMS = 8
MAX_KEY_CHARS = 80
MAX_STRING_CHARS = 240
MAX_RANKING_REASON_CHARS = 240

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "authorization",
    "bearer",
)


@dataclass(frozen=True)
class ContextSourceRef:
    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class ContextItemDiagnostics:
    retrieval_source: str | None
    retrieval_sources: tuple[str, ...]
    retrieval_sources_total: int
    retrieval_sources_returned: int
    retrieval_sources_truncated: bool
    ranking_reason: str
    score_signals: Mapping[str, object]
    provenance: Mapping[str, object]
    raw: Mapping[str, object]
    review_only: bool = False
    stale_reason: str | None = None


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    item_type: str
    memory_scope_id: str | None
    text: str
    score: float
    source_refs: tuple[ContextSourceRef, ...]
    is_instruction: bool
    diagnostics: ContextItemDiagnostics


@dataclass(frozen=True)
class ContextBundleDiagnostics:
    context_assembly_version: str
    consistency_mode: str
    retrieval_sources_used: tuple[str, ...]
    retrieval_sources_total: int
    retrieval_sources_returned: int
    retrieval_sources_truncated: bool
    hybrid_items_used: int
    temporal_replacements_applied: int
    temporal_relations_skipped_by_validity: int
    items_considered: int
    items_used: int
    dropped_by_instruction_flag: int
    dropped_by_budget: int
    dropped_by_source_cap: int
    dropped_by_char_cap: int
    diagnostics_truncated: bool
    raw: Mapping[str, object]
    vector_status: str = "unknown"
    graph_status: str = "unknown"
    rag_status: str = "unknown"
    facts_considered: int = 0
    keyword_chunks_considered: int = 0
    vector_candidate_count: int = 0
    vector_hydrated_count: int = 0
    graph_candidate_count: int = 0
    graph_hydrated_count: int = 0
    stale_vector_drop_count: int = 0
    stale_graph_drop_count: int = 0
    stale_rag_drop_count: int = 0
    stale_facts_considered: int = 0
    stale_facts_used: int = 0
    superseded_facts_considered: int = 0
    superseded_facts_used: int = 0
    temporal_relations_considered: int = 0
    temporal_contradictions_considered: int = 0
    pending_conflict_suggestions_considered: int = 0
    multimodal_source_ref_count: int = 0
    items_with_multimodal_source_refs: int = 0
    source_refs_with_page_count: int = 0
    source_refs_with_bbox_count: int = 0
    source_refs_with_time_range_count: int = 0
    source_refs_total: int = 0
    source_refs_returned: int = 0
    source_refs_truncated: bool = False


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    rendered_text: str
    items: tuple[ContextItem, ...]
    diagnostics: ContextBundleDiagnostics
    meta: Mapping[str, object]


def context_bundle_from_response(payload: Mapping[str, object]) -> ContextBundle:
    meta = _bounded_mapping(payload.get("meta"))
    data = _as_mapping(payload.get("data"))
    items = tuple(
        _context_item_from_payload(item)
        for item in _as_list(data.get("items"))
        if isinstance(item, Mapping)
    )
    return ContextBundle(
        bundle_id=_safe_text(data.get("bundle_id"), default=""),
        rendered_text=_safe_text(data.get("rendered_text"), default="", limit=120_000),
        items=items,
        diagnostics=_bundle_diagnostics_from_payload(data.get("diagnostics")),
        meta=meta,
    )


def _context_item_from_payload(payload: Mapping[str, object]) -> ContextItem:
    diagnostics = _item_diagnostics_from_payload(payload.get("diagnostics"))
    return ContextItem(
        item_id=_safe_text(payload.get("item_id"), default=""),
        item_type=_safe_text(payload.get("item_type"), default=""),
        memory_scope_id=_optional_text(payload.get("memory_scope_id")),
        text=_safe_text(payload.get("text"), default="", limit=120_000),
        score=_safe_float(payload.get("score")),
        source_refs=tuple(
            _source_ref_from_payload(ref)
            for ref in _as_list(payload.get("source_refs"))[:MAX_SOURCE_REFS]
            if isinstance(ref, Mapping)
        ),
        is_instruction=bool(payload.get("is_instruction")),
        diagnostics=diagnostics,
    )


def _source_ref_from_payload(payload: Mapping[str, object]) -> ContextSourceRef:
    return ContextSourceRef(
        source_type=_safe_text(payload.get("source_type"), default=""),
        source_id=_safe_text(payload.get("source_id"), default=""),
        chunk_id=_optional_text(payload.get("chunk_id")),
        char_start=_optional_int(payload.get("char_start")),
        char_end=_optional_int(payload.get("char_end")),
        quote_preview=_optional_text(payload.get("quote_preview")),
        page_number=_optional_int(payload.get("page_number")),
        time_start_ms=_optional_int(payload.get("time_start_ms")),
        time_end_ms=_optional_int(payload.get("time_end_ms")),
        bbox=_optional_bbox(payload.get("bbox")),
    )


def _item_diagnostics_from_payload(value: object) -> ContextItemDiagnostics:
    raw = _bounded_mapping(value)
    retrieval_sources = _safe_text_tuple(raw.get("retrieval_sources"), limit=MAX_RETRIEVAL_SOURCES)
    retrieval_source = _optional_text(raw.get("retrieval_source")) or (
        retrieval_sources[0] if retrieval_sources else None
    )
    if retrieval_source and retrieval_source not in retrieval_sources:
        retrieval_sources = (retrieval_source, *retrieval_sources)[:MAX_RETRIEVAL_SOURCES]
    ranking_reason = _optional_text(
        raw.get("ranking_reason"),
        limit=MAX_RANKING_REASON_CHARS,
    ) or _ranking_reason_for(retrieval_sources)
    review_only = _safe_bool(raw.get("review_only"))
    stale_reason = _optional_text(raw.get("stale_reason"), limit=MAX_KEY_CHARS)
    safe_raw = dict(raw)
    safe_raw["retrieval_sources"] = list(retrieval_sources)
    if retrieval_source:
        safe_raw["retrieval_source"] = retrieval_source
    safe_raw["ranking_reason"] = ranking_reason
    retrieval_sources_total = _non_negative_int(
        raw.get("retrieval_sources_total"),
        default=len(retrieval_sources),
    )
    retrieval_sources_returned = _non_negative_int(
        raw.get("retrieval_sources_returned"),
        default=len(retrieval_sources),
    )
    retrieval_sources_truncated = _safe_bool(
        raw.get("retrieval_sources_truncated")
    ) or retrieval_sources_total > retrieval_sources_returned
    safe_raw["retrieval_sources_total"] = retrieval_sources_total
    safe_raw["retrieval_sources_returned"] = retrieval_sources_returned
    safe_raw["retrieval_sources_truncated"] = retrieval_sources_truncated
    safe_raw["review_only"] = review_only
    if stale_reason:
        safe_raw["stale_reason"] = stale_reason
    return ContextItemDiagnostics(
        retrieval_source=retrieval_source,
        retrieval_sources=retrieval_sources,
        retrieval_sources_total=retrieval_sources_total,
        retrieval_sources_returned=retrieval_sources_returned,
        retrieval_sources_truncated=retrieval_sources_truncated,
        ranking_reason=ranking_reason,
        score_signals=_scalar_mapping(raw.get("score_signals")),
        provenance=_bounded_mapping(raw.get("provenance")),
        raw=safe_raw,
        review_only=review_only,
        stale_reason=stale_reason,
    )


def _bundle_diagnostics_from_payload(value: object) -> ContextBundleDiagnostics:
    raw = _bounded_mapping(value, max_items=64)
    retrieval_sources_used = _safe_text_tuple(
        raw.get("retrieval_sources_used"),
        limit=MAX_RETRIEVAL_SOURCES,
    )
    safe_raw = dict(raw)
    safe_raw["retrieval_sources_used"] = list(retrieval_sources_used)
    retrieval_sources_total = _non_negative_int(
        raw.get("retrieval_sources_total"),
        default=len(retrieval_sources_used),
    )
    retrieval_sources_returned = _non_negative_int(
        raw.get("retrieval_sources_returned"),
        default=len(retrieval_sources_used),
    )
    retrieval_sources_truncated = _safe_bool(
        raw.get("retrieval_sources_truncated")
    ) or retrieval_sources_total > retrieval_sources_returned
    safe_raw["retrieval_sources_total"] = retrieval_sources_total
    safe_raw["retrieval_sources_returned"] = retrieval_sources_returned
    safe_raw["retrieval_sources_truncated"] = retrieval_sources_truncated
    return ContextBundleDiagnostics(
        context_assembly_version=_safe_text(raw.get("context_assembly_version"), default="unknown"),
        consistency_mode=_safe_text(raw.get("consistency_mode"), default="unknown"),
        retrieval_sources_used=retrieval_sources_used,
        retrieval_sources_total=retrieval_sources_total,
        retrieval_sources_returned=retrieval_sources_returned,
        retrieval_sources_truncated=retrieval_sources_truncated,
        hybrid_items_used=_non_negative_int(raw.get("hybrid_items_used")),
        temporal_replacements_applied=_non_negative_int(
            raw.get("temporal_replacements_applied")
        ),
        temporal_relations_skipped_by_validity=_non_negative_int(
            raw.get("temporal_relations_skipped_by_validity")
        ),
        items_considered=_non_negative_int(raw.get("items_considered")),
        items_used=_non_negative_int(raw.get("items_used")),
        dropped_by_instruction_flag=_non_negative_int(
            raw.get("dropped_by_instruction_flag")
        ),
        dropped_by_budget=_non_negative_int(raw.get("dropped_by_budget")),
        dropped_by_source_cap=_non_negative_int(raw.get("dropped_by_source_cap")),
        dropped_by_char_cap=_non_negative_int(raw.get("dropped_by_char_cap")),
        diagnostics_truncated=bool(raw.get("diagnostics_truncated")),
        raw=safe_raw,
        vector_status=_safe_text(raw.get("vector_status"), default="unknown"),
        graph_status=_safe_text(raw.get("graph_status"), default="unknown"),
        rag_status=_safe_text(raw.get("rag_status"), default="unknown"),
        facts_considered=_non_negative_int(raw.get("facts_considered")),
        keyword_chunks_considered=_non_negative_int(raw.get("keyword_chunks_considered")),
        vector_candidate_count=_non_negative_int(raw.get("vector_candidate_count")),
        vector_hydrated_count=_non_negative_int(raw.get("vector_hydrated_count")),
        graph_candidate_count=_non_negative_int(raw.get("graph_candidate_count")),
        graph_hydrated_count=_non_negative_int(raw.get("graph_hydrated_count")),
        stale_vector_drop_count=_non_negative_int(raw.get("stale_vector_drop_count")),
        stale_graph_drop_count=_non_negative_int(raw.get("stale_graph_drop_count")),
        stale_rag_drop_count=_non_negative_int(raw.get("stale_rag_drop_count")),
        stale_facts_considered=_non_negative_int(raw.get("stale_facts_considered")),
        stale_facts_used=_non_negative_int(raw.get("stale_facts_used")),
        superseded_facts_considered=_non_negative_int(
            raw.get("superseded_facts_considered")
        ),
        superseded_facts_used=_non_negative_int(raw.get("superseded_facts_used")),
        temporal_relations_considered=_non_negative_int(
            raw.get("temporal_relations_considered")
        ),
        temporal_contradictions_considered=_non_negative_int(
            raw.get("temporal_contradictions_considered")
        ),
        pending_conflict_suggestions_considered=_non_negative_int(
            raw.get("pending_conflict_suggestions_considered")
        ),
        multimodal_source_ref_count=_non_negative_int(raw.get("multimodal_source_ref_count")),
        items_with_multimodal_source_refs=_non_negative_int(
            raw.get("items_with_multimodal_source_refs")
        ),
        source_refs_with_page_count=_non_negative_int(raw.get("source_refs_with_page_count")),
        source_refs_with_bbox_count=_non_negative_int(raw.get("source_refs_with_bbox_count")),
        source_refs_with_time_range_count=_non_negative_int(
            raw.get("source_refs_with_time_range_count")
        ),
        source_refs_total=_non_negative_int(raw.get("source_refs_total")),
        source_refs_returned=_non_negative_int(raw.get("source_refs_returned")),
        source_refs_truncated=_safe_bool(raw.get("source_refs_truncated")),
    )


def _ranking_reason_for(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        return _safe_text(
            f"hybrid match via {', '.join(retrieval_sources)}",
            default="hybrid match",
            limit=MAX_RANKING_REASON_CHARS,
        )
    if retrieval_sources:
        return _safe_text(
            f"matched via {retrieval_sources[0]}",
            default="matched",
            limit=MAX_RANKING_REASON_CHARS,
        )
    return "matched without retrieval channel diagnostics"


def _bounded_mapping(
    value: object,
    *,
    max_items: int = MAX_MAPPING_ITEMS,
    depth: int = 0,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or depth > 2:
        return {}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:max_items]:
        key = _safe_text(raw_key, default="", limit=MAX_KEY_CHARS).strip()
        if not key or _is_sensitive_key(key):
            continue
        item = _bounded_value(raw_value, max_items=max_items, depth=depth)
        if _is_safe_value(item):
            result[key] = item
    return result


def _bounded_value(value: object, *, max_items: int, depth: int) -> object:
    if isinstance(value, str):
        return _safe_text(value, default="", limit=MAX_STRING_CHARS)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, Mapping):
        return _bounded_mapping(value, max_items=max_items, depth=depth + 1)
    if isinstance(value, list | tuple):
        result: list[object] = []
        for raw_item in list(value)[:MAX_LIST_ITEMS]:
            item = _bounded_value(raw_item, max_items=max_items, depth=depth + 1)
            if _is_safe_value(item):
                result.append(item)
        return result
    return None


def _scalar_mapping(value: object) -> dict[str, object]:
    return {
        key: item
        for key, item in _bounded_mapping(value).items()
        if isinstance(item, str | int | float | bool) or item is None
    }


def _safe_text(value: object, *, default: str, limit: int = MAX_STRING_CHARS) -> str:
    if value is None:
        return default
    text = redact_sensitive_text(str(value)).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 12)].rstrip()}...truncated"


def _optional_text(value: object, *, limit: int = MAX_STRING_CHARS) -> str | None:
    text = _safe_text(value, default="", limit=limit)
    return text or None


def _safe_text_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for item in _as_list(value):
        text = _optional_text(item, limit=MAX_KEY_CHARS)
        if not text or "[redacted]" in text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _optional_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    parsed: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            return None
        parsed.append(float(item))
    return (parsed[0], parsed[1], parsed[2], parsed[3])


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, int | float):
        return value != 0
    return False


def _non_negative_int(value: object, *, default: int = 0) -> int:
    number = _optional_int(value)
    return max(0, number if number is not None else default)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _is_sensitive_key(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _is_safe_value(value: object) -> bool:
    return isinstance(value, str | int | float | bool | dict | list) or value is None
