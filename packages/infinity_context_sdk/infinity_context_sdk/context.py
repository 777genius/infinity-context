"""Typed context response helpers for the public Infinity Context SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_sdk._redaction import redact_sensitive_text

MAX_RETRIEVAL_SOURCES = 8
MAX_SOURCE_REFS = 20
MAX_MAPPING_ITEMS = 24
MAX_BUNDLE_DIAGNOSTIC_ITEMS = 128
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
class ContextCitation:
    citation_id: str
    label: str
    source_type: str
    source_id: str
    chunk_id: str | None = None
    quote_preview: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    evidence_kind: str | None = None
    evidence_modality: str | None = None
    evidence_confidence: float | None = None
    retrieval_source: str | None = None
    ranking_reason: str | None = None


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
    citations_total: int = 0
    citations_returned: int = 0
    citations_truncated: bool = False


@dataclass(frozen=True)
class ContextRetrievalTraceEntry:
    retrieval_source: str
    item_count: int
    item_types: Mapping[str, int]
    source_ref_count: int
    multimodal_source_ref_count: int
    evidence_kind_counts: Mapping[str, int]
    evidence_modality_counts: Mapping[str, int]
    max_score: float
    review_only_count: int = 0
    stale_count: int = 0


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    item_type: str
    memory_scope_id: str | None
    text: str
    score: float
    source_refs: tuple[ContextSourceRef, ...]
    citations: tuple[ContextCitation, ...]
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
    artifact_evidence_status: str = "unknown"
    facts_considered: int = 0
    anchors_considered: int = 0
    anchors_used: int = 0
    keyword_chunks_considered: int = 0
    vector_candidate_count: int = 0
    vector_hydrated_count: int = 0
    graph_candidate_count: int = 0
    graph_hydrated_count: int = 0
    artifact_evidence_jobs_considered: int = 0
    artifact_evidence_manifests_considered: int = 0
    artifact_evidence_manifests_used: int = 0
    artifact_evidence_items_considered: int = 0
    artifact_evidence_items_used: int = 0
    artifact_evidence_ranked_candidate_count: int = 0
    artifact_evidence_candidate_cap_reached_count: int = 0
    artifact_evidence_confidence_signal_count: int = 0
    artifact_evidence_coordinate_signal_count: int = 0
    artifact_evidence_invalid_time_range_count: int = 0
    artifact_evidence_invalid_bbox_count: int = 0
    artifact_evidence_query_drop_count: int = 0
    artifact_evidence_sensitive_drop_count: int = 0
    artifact_evidence_prompt_injection_drop_count: int = 0
    artifact_evidence_manifest_too_large_count: int = 0
    artifact_evidence_read_error_count: int = 0
    artifact_evidence_parse_error_count: int = 0
    artifact_evidence_schema_skip_count: int = 0
    artifact_evidence_stale_asset_drop_count: int = 0
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
    pending_duplicate_merge_suggestions_considered: int = 0
    approved_context_links_considered: int = 0
    approved_context_links_used: int = 0
    approved_context_linked_chunks_used: int = 0
    approved_context_linked_facts_used: int = 0
    approved_context_linked_anchors_used: int = 0
    approved_context_linked_assets_used: int = 0
    approved_context_linked_extraction_artifacts_used: int = 0
    approved_context_linked_extraction_artifact_manifest_items_used: int = 0
    approved_context_linked_extraction_artifact_blob_storage_disabled_count: int = 0
    approved_context_linked_extraction_artifact_manifest_too_large_count: int = 0
    approved_context_linked_extraction_artifact_read_error_count: int = 0
    approved_context_linked_extraction_artifact_parse_error_count: int = 0
    approved_context_linked_extraction_artifact_schema_skip_count: int = 0
    stale_context_linked_chunk_drop_count: int = 0
    stale_context_linked_fact_drop_count: int = 0
    stale_context_linked_anchor_drop_count: int = 0
    stale_context_linked_asset_drop_count: int = 0
    stale_context_linked_extraction_artifact_drop_count: int = 0
    diversity_families_considered: int = 0
    diversity_families_used: int = 0
    diversity_items_used: int = 0
    chunk_sources_considered: int = 0
    chunk_sources_used: int = 0
    max_chunks_used_per_source: int = 0
    source_capped_sources_considered: int = 0
    source_capped_sources_used: int = 0
    max_source_capped_items_used_per_source: int = 0
    source_diversity_chunks_reordered: int = 0
    multimodal_source_ref_count: int = 0
    items_with_multimodal_source_refs: int = 0
    source_refs_with_page_count: int = 0
    source_refs_with_bbox_count: int = 0
    source_refs_with_time_range_count: int = 0
    source_refs_with_char_range_count: int = 0
    query_snippet_items_used: int = 0
    query_snippet_source_refs_enriched: int = 0
    source_refs_total: int = 0
    source_refs_returned: int = 0
    source_refs_truncated: bool = False
    citations_rendered: int = 0
    citations_total: int = 0
    citations_returned: int = 0
    citations_truncated: bool = False
    items_with_citations: int = 0
    citation_quote_previews_rendered: int = 0
    sensitive_citation_quote_previews_skipped: int = 0
    sensitive_item_text_redacted: int = 0
    rendered_chars: int = 0
    max_rendered_chars: int = 0
    provenance_summary: Mapping[str, object] | None = None
    retrieval_quality_summary: Mapping[str, object] | None = None
    retrieval_trace: tuple[ContextRetrievalTraceEntry, ...] = ()


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
        citations=tuple(
            _citation_from_payload(citation)
            for citation in _as_list(payload.get("citations"))[:MAX_SOURCE_REFS]
            if isinstance(citation, Mapping)
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


def _citation_from_payload(payload: Mapping[str, object]) -> ContextCitation:
    char_range = _as_mapping(payload.get("char_range"))
    time_range_ms = _as_mapping(payload.get("time_range_ms"))
    return ContextCitation(
        citation_id=_safe_text(payload.get("citation_id"), default="", limit=MAX_STRING_CHARS),
        label=_safe_text(payload.get("label"), default="", limit=MAX_STRING_CHARS),
        source_type=_safe_text(payload.get("source_type"), default=""),
        source_id=_safe_text(payload.get("source_id"), default=""),
        chunk_id=_optional_text(payload.get("chunk_id")),
        quote_preview=_optional_text(payload.get("quote_preview")),
        char_start=_optional_int(char_range.get("start")),
        char_end=_optional_int(char_range.get("end")),
        page_number=_optional_int(payload.get("page_number")),
        time_start_ms=_optional_int(time_range_ms.get("start")),
        time_end_ms=_optional_int(time_range_ms.get("end")),
        bbox=_optional_bbox(payload.get("bbox")),
        evidence_kind=_optional_text(payload.get("evidence_kind"), limit=MAX_KEY_CHARS),
        evidence_modality=_optional_text(payload.get("evidence_modality"), limit=MAX_KEY_CHARS),
        evidence_confidence=_optional_float(payload.get("evidence_confidence")),
        retrieval_source=_optional_text(payload.get("retrieval_source"), limit=MAX_KEY_CHARS),
        ranking_reason=_optional_text(
            payload.get("ranking_reason"),
            limit=MAX_RANKING_REASON_CHARS,
        ),
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
    retrieval_sources_truncated = (
        _safe_bool(raw.get("retrieval_sources_truncated"))
        or retrieval_sources_total > retrieval_sources_returned
    )
    safe_raw["retrieval_sources_total"] = retrieval_sources_total
    safe_raw["retrieval_sources_returned"] = retrieval_sources_returned
    safe_raw["retrieval_sources_truncated"] = retrieval_sources_truncated
    safe_raw["review_only"] = review_only
    if stale_reason:
        safe_raw["stale_reason"] = stale_reason
    citations_total = _non_negative_int(raw.get("citations_total"))
    citations_returned = _non_negative_int(raw.get("citations_returned"))
    citations_truncated = _safe_bool(raw.get("citations_truncated"))
    safe_raw["citations_total"] = citations_total
    safe_raw["citations_returned"] = citations_returned
    safe_raw["citations_truncated"] = citations_truncated
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
        citations_total=citations_total,
        citations_returned=citations_returned,
        citations_truncated=citations_truncated,
    )


def _bundle_diagnostics_from_payload(value: object) -> ContextBundleDiagnostics:
    payload = _as_mapping(value)
    raw = _bounded_mapping(value, max_items=MAX_BUNDLE_DIAGNOSTIC_ITEMS)
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
    retrieval_sources_truncated = (
        _safe_bool(raw.get("retrieval_sources_truncated"))
        or retrieval_sources_total > retrieval_sources_returned
    )
    safe_raw["retrieval_sources_total"] = retrieval_sources_total
    safe_raw["retrieval_sources_returned"] = retrieval_sources_returned
    safe_raw["retrieval_sources_truncated"] = retrieval_sources_truncated
    retrieval_trace = tuple(
        _retrieval_trace_entry_from_payload(entry)
        for entry in _as_list(payload.get("retrieval_trace"))[:MAX_RETRIEVAL_SOURCES]
        if isinstance(entry, Mapping)
    )
    safe_raw["retrieval_trace"] = [
        _retrieval_trace_entry_to_raw(entry) for entry in retrieval_trace
    ]
    return ContextBundleDiagnostics(
        context_assembly_version=_safe_text(raw.get("context_assembly_version"), default="unknown"),
        consistency_mode=_safe_text(raw.get("consistency_mode"), default="unknown"),
        retrieval_sources_used=retrieval_sources_used,
        retrieval_sources_total=retrieval_sources_total,
        retrieval_sources_returned=retrieval_sources_returned,
        retrieval_sources_truncated=retrieval_sources_truncated,
        hybrid_items_used=_non_negative_int(raw.get("hybrid_items_used")),
        temporal_replacements_applied=_non_negative_int(raw.get("temporal_replacements_applied")),
        temporal_relations_skipped_by_validity=_non_negative_int(
            raw.get("temporal_relations_skipped_by_validity")
        ),
        items_considered=_non_negative_int(raw.get("items_considered")),
        items_used=_non_negative_int(raw.get("items_used")),
        dropped_by_instruction_flag=_non_negative_int(raw.get("dropped_by_instruction_flag")),
        dropped_by_budget=_non_negative_int(raw.get("dropped_by_budget")),
        dropped_by_source_cap=_non_negative_int(raw.get("dropped_by_source_cap")),
        dropped_by_char_cap=_non_negative_int(raw.get("dropped_by_char_cap")),
        diagnostics_truncated=bool(raw.get("diagnostics_truncated")),
        raw=safe_raw,
        vector_status=_safe_text(raw.get("vector_status"), default="unknown"),
        graph_status=_safe_text(raw.get("graph_status"), default="unknown"),
        rag_status=_safe_text(raw.get("rag_status"), default="unknown"),
        artifact_evidence_status=_safe_text(
            raw.get("artifact_evidence_status"),
            default="unknown",
        ),
        facts_considered=_non_negative_int(raw.get("facts_considered")),
        anchors_considered=_non_negative_int(raw.get("anchors_considered")),
        anchors_used=_non_negative_int(raw.get("anchors_used")),
        keyword_chunks_considered=_non_negative_int(raw.get("keyword_chunks_considered")),
        vector_candidate_count=_non_negative_int(raw.get("vector_candidate_count")),
        vector_hydrated_count=_non_negative_int(raw.get("vector_hydrated_count")),
        graph_candidate_count=_non_negative_int(raw.get("graph_candidate_count")),
        graph_hydrated_count=_non_negative_int(raw.get("graph_hydrated_count")),
        artifact_evidence_jobs_considered=_non_negative_int(
            raw.get("artifact_evidence_jobs_considered")
        ),
        artifact_evidence_manifests_considered=_non_negative_int(
            raw.get("artifact_evidence_manifests_considered")
        ),
        artifact_evidence_manifests_used=_non_negative_int(
            raw.get("artifact_evidence_manifests_used")
        ),
        artifact_evidence_items_considered=_non_negative_int(
            raw.get("artifact_evidence_items_considered")
        ),
        artifact_evidence_items_used=_non_negative_int(raw.get("artifact_evidence_items_used")),
        artifact_evidence_ranked_candidate_count=_non_negative_int(
            raw.get("artifact_evidence_ranked_candidate_count")
        ),
        artifact_evidence_candidate_cap_reached_count=_non_negative_int(
            raw.get("artifact_evidence_candidate_cap_reached_count")
        ),
        artifact_evidence_confidence_signal_count=_non_negative_int(
            raw.get("artifact_evidence_confidence_signal_count")
        ),
        artifact_evidence_coordinate_signal_count=_non_negative_int(
            raw.get("artifact_evidence_coordinate_signal_count")
        ),
        artifact_evidence_invalid_time_range_count=_non_negative_int(
            raw.get("artifact_evidence_invalid_time_range_count")
        ),
        artifact_evidence_invalid_bbox_count=_non_negative_int(
            raw.get("artifact_evidence_invalid_bbox_count")
        ),
        artifact_evidence_query_drop_count=_non_negative_int(
            raw.get("artifact_evidence_query_drop_count")
        ),
        artifact_evidence_sensitive_drop_count=_non_negative_int(
            raw.get("artifact_evidence_sensitive_drop_count")
        ),
        artifact_evidence_prompt_injection_drop_count=_non_negative_int(
            raw.get("artifact_evidence_prompt_injection_drop_count")
        ),
        artifact_evidence_manifest_too_large_count=_non_negative_int(
            raw.get("artifact_evidence_manifest_too_large_count")
        ),
        artifact_evidence_read_error_count=_non_negative_int(
            raw.get("artifact_evidence_read_error_count")
        ),
        artifact_evidence_parse_error_count=_non_negative_int(
            raw.get("artifact_evidence_parse_error_count")
        ),
        artifact_evidence_schema_skip_count=_non_negative_int(
            raw.get("artifact_evidence_schema_skip_count")
        ),
        artifact_evidence_stale_asset_drop_count=_non_negative_int(
            raw.get("artifact_evidence_stale_asset_drop_count")
        ),
        stale_vector_drop_count=_non_negative_int(raw.get("stale_vector_drop_count")),
        stale_graph_drop_count=_non_negative_int(raw.get("stale_graph_drop_count")),
        stale_rag_drop_count=_non_negative_int(raw.get("stale_rag_drop_count")),
        stale_facts_considered=_non_negative_int(raw.get("stale_facts_considered")),
        stale_facts_used=_non_negative_int(raw.get("stale_facts_used")),
        superseded_facts_considered=_non_negative_int(raw.get("superseded_facts_considered")),
        superseded_facts_used=_non_negative_int(raw.get("superseded_facts_used")),
        temporal_relations_considered=_non_negative_int(raw.get("temporal_relations_considered")),
        temporal_contradictions_considered=_non_negative_int(
            raw.get("temporal_contradictions_considered")
        ),
        pending_conflict_suggestions_considered=_non_negative_int(
            raw.get("pending_conflict_suggestions_considered")
        ),
        pending_duplicate_merge_suggestions_considered=_non_negative_int(
            raw.get("pending_duplicate_merge_suggestions_considered")
        ),
        approved_context_links_considered=_non_negative_int(
            raw.get("approved_context_links_considered")
        ),
        approved_context_links_used=_non_negative_int(raw.get("approved_context_links_used")),
        approved_context_linked_chunks_used=_non_negative_int(
            raw.get("approved_context_linked_chunks_used")
        ),
        approved_context_linked_facts_used=_non_negative_int(
            raw.get("approved_context_linked_facts_used")
        ),
        approved_context_linked_anchors_used=_non_negative_int(
            raw.get("approved_context_linked_anchors_used")
        ),
        approved_context_linked_assets_used=_non_negative_int(
            raw.get("approved_context_linked_assets_used")
        ),
        approved_context_linked_extraction_artifacts_used=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifacts_used")
        ),
        approved_context_linked_extraction_artifact_manifest_items_used=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_manifest_items_used")
        ),
        approved_context_linked_extraction_artifact_blob_storage_disabled_count=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_blob_storage_disabled_count")
        ),
        approved_context_linked_extraction_artifact_manifest_too_large_count=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_manifest_too_large_count")
        ),
        approved_context_linked_extraction_artifact_read_error_count=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_read_error_count")
        ),
        approved_context_linked_extraction_artifact_parse_error_count=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_parse_error_count")
        ),
        approved_context_linked_extraction_artifact_schema_skip_count=_non_negative_int(
            raw.get("approved_context_linked_extraction_artifact_schema_skip_count")
        ),
        stale_context_linked_chunk_drop_count=_non_negative_int(
            raw.get("stale_context_linked_chunk_drop_count")
        ),
        stale_context_linked_fact_drop_count=_non_negative_int(
            raw.get("stale_context_linked_fact_drop_count")
        ),
        stale_context_linked_anchor_drop_count=_non_negative_int(
            raw.get("stale_context_linked_anchor_drop_count")
        ),
        stale_context_linked_asset_drop_count=_non_negative_int(
            raw.get("stale_context_linked_asset_drop_count")
        ),
        stale_context_linked_extraction_artifact_drop_count=_non_negative_int(
            raw.get("stale_context_linked_extraction_artifact_drop_count")
        ),
        diversity_families_considered=_non_negative_int(raw.get("diversity_families_considered")),
        diversity_families_used=_non_negative_int(raw.get("diversity_families_used")),
        diversity_items_used=_non_negative_int(raw.get("diversity_items_used")),
        chunk_sources_considered=_non_negative_int(raw.get("chunk_sources_considered")),
        chunk_sources_used=_non_negative_int(raw.get("chunk_sources_used")),
        max_chunks_used_per_source=_non_negative_int(raw.get("max_chunks_used_per_source")),
        source_capped_sources_considered=_non_negative_int(
            raw.get("source_capped_sources_considered")
        ),
        source_capped_sources_used=_non_negative_int(raw.get("source_capped_sources_used")),
        max_source_capped_items_used_per_source=_non_negative_int(
            raw.get("max_source_capped_items_used_per_source")
        ),
        source_diversity_chunks_reordered=_non_negative_int(
            raw.get("source_diversity_chunks_reordered")
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
        source_refs_with_char_range_count=_non_negative_int(
            raw.get("source_refs_with_char_range_count")
        ),
        query_snippet_items_used=_non_negative_int(raw.get("query_snippet_items_used")),
        query_snippet_source_refs_enriched=_non_negative_int(
            raw.get("query_snippet_source_refs_enriched")
        ),
        source_refs_total=_non_negative_int(raw.get("source_refs_total")),
        source_refs_returned=_non_negative_int(raw.get("source_refs_returned")),
        source_refs_truncated=_safe_bool(raw.get("source_refs_truncated")),
        citations_rendered=_non_negative_int(raw.get("citations_rendered")),
        citations_total=_non_negative_int(raw.get("citations_total")),
        citations_returned=_non_negative_int(raw.get("citations_returned")),
        citations_truncated=_safe_bool(raw.get("citations_truncated")),
        items_with_citations=_non_negative_int(raw.get("items_with_citations")),
        citation_quote_previews_rendered=_non_negative_int(
            raw.get("citation_quote_previews_rendered")
        ),
        sensitive_citation_quote_previews_skipped=_non_negative_int(
            raw.get("sensitive_citation_quote_previews_skipped")
        ),
        sensitive_item_text_redacted=_non_negative_int(raw.get("sensitive_item_text_redacted")),
        rendered_chars=_non_negative_int(raw.get("rendered_chars")),
        max_rendered_chars=_non_negative_int(raw.get("max_rendered_chars")),
        provenance_summary=_bounded_mapping(raw.get("provenance_summary")),
        retrieval_quality_summary=_bounded_mapping(raw.get("retrieval_quality_summary")),
        retrieval_trace=retrieval_trace,
    )


def _retrieval_trace_entry_from_payload(
    payload: Mapping[str, object],
) -> ContextRetrievalTraceEntry:
    return ContextRetrievalTraceEntry(
        retrieval_source=_safe_text(
            payload.get("retrieval_source"),
            default="unknown",
            limit=MAX_KEY_CHARS,
        ),
        item_count=_non_negative_int(payload.get("item_count")),
        item_types=_int_mapping(payload.get("item_types")),
        source_ref_count=_non_negative_int(payload.get("source_ref_count")),
        multimodal_source_ref_count=_non_negative_int(payload.get("multimodal_source_ref_count")),
        evidence_kind_counts=_int_mapping(payload.get("evidence_kind_counts")),
        evidence_modality_counts=_int_mapping(payload.get("evidence_modality_counts")),
        max_score=_safe_float(payload.get("max_score")),
        review_only_count=_non_negative_int(payload.get("review_only_count")),
        stale_count=_non_negative_int(payload.get("stale_count")),
    )


def _retrieval_trace_entry_to_raw(entry: ContextRetrievalTraceEntry) -> dict[str, object]:
    return {
        "retrieval_source": entry.retrieval_source,
        "item_count": entry.item_count,
        "item_types": dict(entry.item_types),
        "source_ref_count": entry.source_ref_count,
        "multimodal_source_ref_count": entry.multimodal_source_ref_count,
        "evidence_kind_counts": dict(entry.evidence_kind_counts),
        "evidence_modality_counts": dict(entry.evidence_modality_counts),
        "max_score": entry.max_score,
        "review_only_count": entry.review_only_count,
        "stale_count": entry.stale_count,
    }


def _int_mapping(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _bounded_mapping(value).items():
        if not isinstance(key, str):
            continue
        result[key] = _non_negative_int(item)
    return result


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


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
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
