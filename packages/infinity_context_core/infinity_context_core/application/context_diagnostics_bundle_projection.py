"""Bundle-level context diagnostics projection helpers."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application.context_diagnostics_bundle_keys import (
    _BUNDLE_COUNTER_DEFAULTS,
    _BUNDLE_COUNTER_KEYS,
    _BUNDLE_KEYWORD_AGGREGATION_TEXT_KEYS,
    _BUNDLE_PROVIDER_STATUS_FLOAT_KEYS,
    _BUNDLE_PROVIDER_STATUS_TEXT_KEYS,
    _BUNDLE_QUERY_ANCHOR_LIST_KEYS,
    _BUNDLE_QUERY_ANCHOR_TEXT_KEYS,
    _BUNDLE_QUERY_PLAN_COUNTER_KEYS,
    _BUNDLE_QUERY_PLAN_LIST_KEYS,
    _BUNDLE_QUERY_PLAN_TEXT_KEYS,
    _BUNDLE_STATUS_DEFAULTS,
    _BUNDLE_TEMPORAL_QUERY_BOOL_KEYS,
    _BUNDLE_TEMPORAL_QUERY_LIST_KEYS,
    _BUNDLE_TEMPORAL_QUERY_TEXT_KEYS,
)
from infinity_context_core.application.context_diagnostics_primitives import (
    _MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS,
    _MAX_DIAGNOSTIC_KEY_CHARS,
    _MAX_DIAGNOSTIC_LIST_ITEMS,
    _MAX_EVIDENCE_LOCATION_GAPS,
    _MAX_RETRIEVAL_SOURCE_CANDIDATES,
    _MAX_RETRIEVAL_SOURCES,
    _MAX_RETRIEVAL_TRACE_ENTRIES,
    _as_dict,
    _bounded_mapping,
    _non_negative_int,
    _optional_non_negative_float,
    _optional_non_negative_int,
    _ordered_unique,
    _safe_optional_text,
)
from infinity_context_core.application.context_diagnostics_sources import (
    _prioritized_retrieval_sources,
    diagnostic_retrieval_sources,
)
from infinity_context_core.application.context_quality import retrieval_quality_summary
from infinity_context_core.application.context_requirement_coverage import (
    sanitize_context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.safe_payload import safe_metadata


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
            _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS) or default
        )
    normalized.update(_safe_bundle_provider_status_diagnostics(raw))
    normalized.update(_safe_bundle_query_anchor_diagnostics(raw))
    normalized.update(_safe_bundle_keyword_aggregation_diagnostics(raw))
    normalized.update(_safe_bundle_query_plan_diagnostics(raw))
    normalized.update(_safe_bundle_temporal_query_diagnostics(raw))
    all_retrieval_sources = _bundle_retrieval_sources(
        items,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized["retrieval_sources_used"] = list(retrieval_sources)
    normalized["retrieval_sources_total"] = len(all_retrieval_sources)
    normalized["retrieval_sources_returned"] = len(retrieval_sources)
    normalized["retrieval_sources_truncated"] = len(all_retrieval_sources) > len(retrieval_sources)
    normalized["diagnostics_truncated"] = len(raw) > _MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS
    for key in _BUNDLE_COUNTER_KEYS:
        if key in raw or key in _BUNDLE_COUNTER_DEFAULTS:
            normalized[key] = _non_negative_int(
                raw.get(key),
                default=_BUNDLE_COUNTER_DEFAULTS.get(key, 0),
            )
    normalized["item_type_counts"] = _item_type_counts(items)
    normalized.update(_source_ref_counts(items))
    normalized.update(_multimodal_source_ref_counts(items))
    normalized.update(_evidence_kind_modality_counts(items))
    normalized["evidence_coverage_profile"] = _evidence_coverage_profile(items)
    normalized["context_requirement_coverage"] = sanitize_context_requirement_coverage(
        raw.get("context_requirement_coverage")
    )
    normalized.update(_query_snippet_counts(items))
    normalized.update(_media_time_query_counts(items))
    normalized["retrieval_trace"] = _retrieval_trace(
        items,
        retrieval_sources=retrieval_sources,
    )
    normalized["provenance_summary"] = _provenance_summary(normalized, items)
    normalized["retrieval_quality_summary"] = retrieval_quality_summary(
        normalized,
        items,
    )
    return normalized

def _safe_bundle_query_plan_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_QUERY_PLAN_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_QUERY_PLAN_COUNTER_KEYS:
        if key in raw:
            diagnostics[key] = _non_negative_int(raw.get(key), default=0)
    for key in _BUNDLE_QUERY_PLAN_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics


def _safe_bundle_provider_status_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_PROVIDER_STATUS_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_PROVIDER_STATUS_FLOAT_KEYS:
        value = _optional_non_negative_float(raw.get(key))
        if value is not None:
            diagnostics[key] = value
    return diagnostics


def _safe_bundle_query_anchor_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_QUERY_ANCHOR_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_QUERY_ANCHOR_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics


def _safe_bundle_keyword_aggregation_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_KEYWORD_AGGREGATION_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value is not None:
            diagnostics[key] = value
    return diagnostics


def _safe_bundle_temporal_query_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_TEMPORAL_QUERY_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_TEMPORAL_QUERY_BOOL_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            diagnostics[key] = value
    for key in _BUNDLE_TEMPORAL_QUERY_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics

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
        "citations_total": total,
        "citations_returned": returned,
        "citations_truncated": total > returned,
        "items_with_citations": sum(1 for item in items if item.source_refs),
    }


def _provenance_summary(
    diagnostics: dict[str, object],
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    item_count = len(items)
    refs = tuple(ref for item in items for ref in item.source_refs)
    items_with_citations = _non_negative_int(
        diagnostics.get("items_with_citations"),
        default=0,
    )
    items_with_quote_previews = sum(
        1
        for item in items
        if any(ref.quote_preview and ref.quote_preview.strip() for ref in item.source_refs)
    )
    items_with_precise_locations = sum(
        1
        for item in items
        if any(_source_ref_has_precise_location(ref) for ref in item.source_refs)
    )
    review_only_items = sum(
        1 for item in items if bool(_as_dict(item.diagnostics).get("review_only"))
    )
    pending_review_items = sum(
        1
        for item in items
        if any(
            source
            in {
                "pending_conflict_suggestion",
                "pending_duplicate_merge_suggestion",
            }
            for source in diagnostic_retrieval_sources(item.diagnostics)
        )
    )
    stale_items = sum(
        1
        for item in items
        if _safe_optional_text(
            _as_dict(item.diagnostics).get("stale_reason"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
    )
    quote_preview_refs = sum(
        1 for ref in refs if ref.quote_preview is not None and ref.quote_preview.strip()
    )
    precise_location_refs = sum(1 for ref in refs if _source_ref_has_precise_location(ref))
    return {
        "items_total": item_count,
        "items_with_citations": items_with_citations,
        "uncited_items": max(0, item_count - items_with_citations),
        "citation_coverage_ratio": _ratio(items_with_citations, item_count),
        "citation_density": _ratio(
            _non_negative_int(diagnostics.get("citations_returned"), default=0),
            item_count,
        ),
        "items_with_quote_previews": items_with_quote_previews,
        "quote_preview_coverage_ratio": _ratio(items_with_quote_previews, item_count),
        "items_with_precise_locations": items_with_precise_locations,
        "precise_location_coverage_ratio": _ratio(items_with_precise_locations, item_count),
        "source_refs_total": _non_negative_int(
            diagnostics.get("source_refs_total"),
            default=0,
        ),
        "source_refs_returned": _non_negative_int(
            diagnostics.get("source_refs_returned"),
            default=0,
        ),
        "source_refs_with_quote_preview_count": quote_preview_refs,
        "source_refs_with_precise_location_count": precise_location_refs,
        "review_only_items": review_only_items,
        "pending_review_items": pending_review_items,
        "stale_items": stale_items,
        "active_default_items": max(0, item_count - review_only_items),
    }


def _source_ref_has_precise_location(ref: object) -> bool:
    return (
        getattr(ref, "char_start", None) is not None
        or getattr(ref, "char_end", None) is not None
        or getattr(ref, "page_number", None) is not None
        or getattr(ref, "time_start_ms", None) is not None
        or getattr(ref, "time_end_ms", None) is not None
        or getattr(ref, "bbox", None) is not None
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)

def _item_type_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = _safe_optional_text(item.item_type, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _evidence_kind_modality_counts(items: tuple[ContextItem, ...]) -> dict[str, object]:
    kind_counts: dict[str, int] = {}
    modality_counts: dict[str, int] = {}
    for item in items:
        kind = _diagnostic_text(item, "evidence_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        modality = _diagnostic_text(item, "evidence_modality")
        if modality:
            modality_counts[modality] = modality_counts.get(modality, 0) + 1
    return {
        "evidence_kind_counts": dict(sorted(kind_counts.items())),
        "evidence_modality_counts": dict(sorted(modality_counts.items())),
        "items_with_evidence_kind": sum(kind_counts.values()),
        "items_with_evidence_modality": sum(modality_counts.values()),
    }


def _evidence_coverage_profile(items: tuple[ContextItem, ...]) -> dict[str, object]:
    evidence_items = tuple(item for item in items if _has_evidence_identity(item))
    precise_evidence_items = sum(1 for item in evidence_items if _item_has_precise_location(item))
    transcript_items = tuple(item for item in evidence_items if _is_transcript_evidence(item))
    image_region_items = tuple(item for item in evidence_items if _is_image_region_evidence(item))
    video_frame_items = tuple(item for item in evidence_items if _is_video_frame_evidence(item))
    document_items = tuple(item for item in evidence_items if _is_document_evidence(item))
    gaps = _evidence_location_gaps(
        transcript_items=transcript_items,
        image_region_items=image_region_items,
        video_frame_items=video_frame_items,
        document_items=document_items,
    )
    return {
        "schema_version": "evidence-coverage-v1",
        "items_total": len(items),
        "evidence_items_total": len(evidence_items),
        "precise_evidence_items": precise_evidence_items,
        "precise_evidence_location_coverage_ratio": _ratio(
            precise_evidence_items,
            len(evidence_items),
        ),
        "transcript_items_total": len(transcript_items),
        "transcript_time_range_coverage_ratio": _ratio(
            sum(1 for item in transcript_items if _item_has_time_range(item)),
            len(transcript_items),
        ),
        "image_region_items_total": len(image_region_items),
        "image_bbox_coverage_ratio": _ratio(
            sum(1 for item in image_region_items if _item_has_bbox(item)),
            len(image_region_items),
        ),
        "video_frame_items_total": len(video_frame_items),
        "video_time_range_coverage_ratio": _ratio(
            sum(1 for item in video_frame_items if _item_has_time_range(item)),
            len(video_frame_items),
        ),
        "document_items_total": len(document_items),
        "document_page_or_char_coverage_ratio": _ratio(
            sum(1 for item in document_items if _item_has_page_or_char_range(item)),
            len(document_items),
        ),
        "evidence_location_gap_count": len(gaps),
        "evidence_location_gaps": list(gaps[:_MAX_EVIDENCE_LOCATION_GAPS]),
        "prompt_ready_multimodal_evidence": len(gaps) == 0,
    }


def _has_evidence_identity(item: ContextItem) -> bool:
    return bool(
        _diagnostic_text(item, "evidence_kind")
        or _diagnostic_text(item, "evidence_modality")
    )


def _is_transcript_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "audio" or any(marker in kind for marker in ("transcript", "speech", "word"))


def _is_image_region_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "image" and any(
        marker in kind for marker in ("ocr", "region", "bbox", "vision")
    )


def _is_video_frame_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "video" and any(marker in kind for marker in ("keyframe", "frame"))


def _is_document_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality in {"document", "pdf"} or any(
        marker in kind for marker in ("document", "pdf", "page")
    )


def _evidence_location_gaps(
    *,
    transcript_items: tuple[ContextItem, ...],
    image_region_items: tuple[ContextItem, ...],
    video_frame_items: tuple[ContextItem, ...],
    document_items: tuple[ContextItem, ...],
) -> tuple[str, ...]:
    gaps: list[str] = []
    if any(not _item_has_time_range(item) for item in transcript_items):
        gaps.append("transcript_without_time_range")
    if any(not _item_has_bbox(item) for item in image_region_items):
        gaps.append("image_region_without_bbox")
    if any(not _item_has_time_range(item) for item in video_frame_items):
        gaps.append("video_frame_without_time_range")
    if any(not _item_has_page_or_char_range(item) for item in document_items):
        gaps.append("document_without_page_or_char_range")
    return tuple(gaps)


def _item_has_precise_location(item: ContextItem) -> bool:
    return any(_source_ref_has_precise_location(ref) for ref in item.source_refs)


def _item_has_time_range(item: ContextItem) -> bool:
    return any(
        ref.time_start_ms is not None or ref.time_end_ms is not None
        for ref in item.source_refs
    )


def _item_has_bbox(item: ContextItem) -> bool:
    return any(ref.bbox is not None for ref in item.source_refs)


def _item_has_page_or_char_range(item: ContextItem) -> bool:
    return any(
        ref.page_number is not None
        or ref.char_start is not None
        or ref.char_end is not None
        for ref in item.source_refs
    )


def _diagnostic_text(item: ContextItem, key: str) -> str:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    value = diagnostics.get(key) or provenance.get(key)
    text = _safe_optional_text(value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
    if not text or "[redacted]" in text:
        return ""
    return text


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
        1 for ref in refs if ref.time_start_ms is not None or ref.time_end_ms is not None
    )
    char_range_count = sum(
        1 for ref in refs if ref.char_start is not None or ref.char_end is not None
    )
    return {
        "multimodal_source_ref_count": sum(1 for ref in refs if _is_multimodal_source_ref(ref)),
        "items_with_multimodal_source_refs": sum(
            1 for item in items if any(_is_multimodal_source_ref(ref) for ref in item.source_refs)
        ),
        "source_refs_with_page_count": page_count,
        "source_refs_with_bbox_count": bbox_count,
        "source_refs_with_time_range_count": time_count,
        "source_refs_with_char_range_count": char_range_count,
    }


def _query_snippet_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    items_with_snippets = 0
    enriched_refs = 0
    for item in items:
        diagnostics = _as_dict(item.diagnostics)
        snippet = diagnostics.get("query_snippet")
        if not isinstance(snippet, str) or not snippet.strip():
            continue
        items_with_snippets += 1
        enriched_refs += sum(
            1
            for ref in item.source_refs
            if ref.quote_preview
            and (snippet in ref.quote_preview or ref.quote_preview in snippet)
        )
    return {
        "query_snippet_items_used": items_with_snippets,
        "query_snippet_source_refs_enriched": enriched_refs,
    }


def _media_time_query_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    query_items = 0
    matched_items = 0
    for item in items:
        diagnostics = _as_dict(item.diagnostics)
        score_signals = _as_dict(diagnostics.get("score_signals"))
        if _optional_non_negative_int(diagnostics.get("media_time_query_count")):
            query_items += 1
        if _optional_non_negative_int(score_signals.get("media_time_matched_window_count")):
            matched_items += 1
    return {
        "media_time_query_items_used": query_items,
        "media_time_query_matched_items_used": matched_items,
    }


def _retrieval_trace(
    items: tuple[ContextItem, ...],
    *,
    retrieval_sources: tuple[str, ...],
) -> list[dict[str, object]]:
    by_source: dict[str, dict[str, object]] = {}
    source_order = retrieval_sources or ("unknown",)
    for source in source_order:
        by_source[source] = _empty_retrieval_trace_entry(source)

    for item in items:
        item_sources = diagnostic_retrieval_sources(item.diagnostics)
        if not item_sources:
            item_sources = ("unknown",)
            by_source.setdefault("unknown", _empty_retrieval_trace_entry("unknown"))
        for source in item_sources:
            entry = by_source.setdefault(source, _empty_retrieval_trace_entry(source))
            _add_item_to_retrieval_trace_entry(entry, item)

    return [
        _finalize_retrieval_trace_entry(entry)
        for source in source_order[:_MAX_RETRIEVAL_TRACE_ENTRIES]
        if (entry := by_source.get(source)) and entry["item_count"] > 0
    ]


def _empty_retrieval_trace_entry(source: str) -> dict[str, object]:
    return {
        "retrieval_source": _safe_optional_text(
            source,
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown",
        "item_count": 0,
        "item_types": {},
        "source_ref_count": 0,
        "multimodal_source_ref_count": 0,
        "source_refs_with_char_range_count": 0,
        "source_refs_with_page_count": 0,
        "source_refs_with_bbox_count": 0,
        "source_refs_with_time_range_count": 0,
        "media_time_query_match_count": 0,
        "evidence_kind_counts": {},
        "evidence_modality_counts": {},
        "max_score": 0.0,
        "review_only_count": 0,
        "stale_count": 0,
    }


def _add_item_to_retrieval_trace_entry(
    entry: dict[str, object],
    item: ContextItem,
) -> None:
    diagnostics = _as_dict(item.diagnostics)
    entry["item_count"] = int(entry["item_count"]) + 1
    entry["source_ref_count"] = int(entry["source_ref_count"]) + len(item.source_refs)
    entry["multimodal_source_ref_count"] = int(entry["multimodal_source_ref_count"]) + sum(
        1 for ref in item.source_refs if _is_multimodal_source_ref(ref)
    )
    entry["source_refs_with_char_range_count"] = int(
        entry["source_refs_with_char_range_count"]
    ) + sum(
        1
        for ref in item.source_refs
        if ref.char_start is not None or ref.char_end is not None
    )
    entry["source_refs_with_page_count"] = int(entry["source_refs_with_page_count"]) + sum(
        1 for ref in item.source_refs if ref.page_number is not None
    )
    entry["source_refs_with_bbox_count"] = int(entry["source_refs_with_bbox_count"]) + sum(
        1 for ref in item.source_refs if ref.bbox is not None
    )
    entry["source_refs_with_time_range_count"] = int(
        entry["source_refs_with_time_range_count"]
    ) + sum(
        1
        for ref in item.source_refs
        if ref.time_start_ms is not None or ref.time_end_ms is not None
    )
    entry["media_time_query_match_count"] = int(entry["media_time_query_match_count"]) + int(
        _optional_non_negative_int(
            _as_dict(diagnostics.get("score_signals")).get("media_time_matched_window_count")
        )
        or 0
    )
    entry["max_score"] = max(float(entry["max_score"]), round(float(item.score), 4))
    if diagnostics.get("review_only") is True:
        entry["review_only_count"] = int(entry["review_only_count"]) + 1
    if _safe_optional_text(diagnostics.get("stale_reason"), limit=_MAX_DIAGNOSTIC_KEY_CHARS):
        entry["stale_count"] = int(entry["stale_count"]) + 1
    _increment_count_mapping(entry, "item_types", item.item_type)
    _increment_count_mapping(entry, "evidence_kind_counts", _diagnostic_text(item, "evidence_kind"))
    _increment_count_mapping(
        entry,
        "evidence_modality_counts",
        _diagnostic_text(item, "evidence_modality"),
    )


def _increment_count_mapping(
    entry: dict[str, object],
    key: str,
    raw_value: object,
) -> None:
    value = _safe_optional_text(raw_value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
    if not value or "[redacted]" in value:
        return
    counts = entry[key]
    if not isinstance(counts, dict):
        counts = {}
        entry[key] = counts
    counts[value] = int(counts.get(value, 0)) + 1


def _finalize_retrieval_trace_entry(entry: dict[str, object]) -> dict[str, object]:
    finalized = dict(entry)
    for key in ("item_types", "evidence_kind_counts", "evidence_modality_counts"):
        counts = finalized.get(key)
        finalized[key] = dict(sorted(counts.items())) if isinstance(counts, dict) else {}
    finalized["max_score"] = round(float(finalized.get("max_score") or 0.0), 4)
    return finalized


def _is_multimodal_source_ref(ref: Any) -> bool:
    return (
        ref.page_number is not None
        or ref.bbox is not None
        or ref.time_start_ms is not None
        or ref.time_end_ms is not None
    )
