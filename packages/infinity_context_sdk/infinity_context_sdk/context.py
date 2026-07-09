"""Typed context response helpers for the public Infinity Context SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_sdk.context_bundle_diagnostics import (
    ContextBundleDiagnostics,
)
from infinity_context_sdk.context_bundle_diagnostics import (
    bundle_diagnostics_from_payload as _bundle_diagnostics_from_payload,
)
from infinity_context_sdk.context_payload_utils import (
    MAX_BUNDLE_DIAGNOSTIC_ITEMS,
    MAX_KEY_CHARS,
    MAX_LIST_ITEMS,
    MAX_MAPPING_ITEMS,
    MAX_RANKING_REASON_CHARS,
    MAX_RETRIEVAL_SOURCES,
    MAX_SOURCE_REFS,
    MAX_STRING_CHARS,
    _as_list,
    _as_mapping,
    _bounded_mapping,
    _non_negative_int,
    _optional_bbox,
    _optional_float,
    _optional_int,
    _optional_text,
    _ranking_reason_for,
    _safe_bool,
    _safe_float,
    _safe_review_resolution_options,
    _safe_text,
    _safe_text_tuple,
    _scalar_mapping,
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
    review_recommended_action: str | None = None
    review_recommended_resolution_action: str | None = None
    review_default_resolution: str | None = None
    review_risk: str | None = None
    review_recommendation_confidence: str | None = None
    review_policy_version: str | None = None
    review_requires_review: bool = False
    review_auto_merge_eligible: bool = False
    review_recommendation_reason_codes: tuple[str, ...] = ()
    review_resolution_options: tuple[Mapping[str, str], ...] = ()


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
class ContextEvidenceSelection:
    item: ContextItem
    citation: ContextCitation | None
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ContextAnswerSupport:
    status: str
    items_returned: int
    coverage: Mapping[str, object]
    policy: Mapping[str, object]
    warnings: tuple[str, ...]
    raw: Mapping[str, object]


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    rendered_text: str
    items: tuple[ContextItem, ...]
    diagnostics: ContextBundleDiagnostics
    meta: Mapping[str, object]
    answer_support: ContextAnswerSupport

    def top_evidence(
        self,
        *,
        limit: int = 5,
        include_uncited: bool = False,
        include_review_only: bool = False,
        include_stale: bool = False,
    ) -> tuple[ContextEvidenceSelection, ...]:
        """Return frontend-ready evidence selections without reimplementing ranking."""

        if limit <= 0:
            return ()
        candidates: list[ContextEvidenceSelection] = []
        for item in self.items:
            if not include_review_only and item.diagnostics.review_only:
                continue
            if not include_stale and item.diagnostics.stale_reason:
                continue
            if item.citations:
                candidates.extend(
                    _evidence_selection(item=item, citation=citation)
                    for citation in item.citations
                )
            elif include_uncited:
                candidates.append(_evidence_selection(item=item, citation=None))
        return tuple(sorted(candidates, key=_evidence_selection_rank_key)[:limit])


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
        answer_support=_answer_support_from_payload(data.get("answer_support")),
    )


def _evidence_selection(
    *,
    item: ContextItem,
    citation: ContextCitation | None,
) -> ContextEvidenceSelection:
    reasons = _evidence_selection_reasons(item=item, citation=citation)
    return ContextEvidenceSelection(
        item=item,
        citation=citation,
        score=_evidence_selection_score(item=item, citation=citation),
        reasons=reasons,
    )


def _evidence_selection_score(
    *,
    item: ContextItem,
    citation: ContextCitation | None,
) -> float:
    citation_boost = _citation_quality_score(citation)
    retrieval_boost = 0.035 if len(item.diagnostics.retrieval_sources) > 1 else 0.0
    review_penalty = 0.08 if item.diagnostics.review_only else 0.0
    stale_penalty = 0.12 if item.diagnostics.stale_reason else 0.0
    raw_score = item.score + citation_boost + retrieval_boost - review_penalty - stale_penalty
    return round(
        max(0.0, min(1.0, raw_score)),
        4,
    )


def _citation_quality_score(citation: ContextCitation | None) -> float:
    if citation is None:
        return 0.0
    score = 0.04
    if citation.quote_preview:
        score += 0.08
    if citation.char_start is not None or citation.char_end is not None:
        score += 0.045
    if citation.page_number is not None:
        score += 0.045
    if citation.time_start_ms is not None or citation.time_end_ms is not None:
        score += 0.055
    if citation.bbox is not None:
        score += 0.06
    if citation.evidence_kind:
        score += 0.025
    if citation.evidence_modality:
        score += 0.025
    if citation.evidence_confidence is not None:
        score += min(0.045, max(0.0, citation.evidence_confidence) * 0.045)
    return min(0.24, round(score, 4))


def _evidence_selection_reasons(
    *,
    item: ContextItem,
    citation: ContextCitation | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if citation is None:
        reasons.append("uncited_item")
    else:
        reasons.append("cited_evidence")
        if citation.quote_preview:
            reasons.append("quote_preview")
        if _citation_has_precise_location(citation):
            reasons.append("precise_location")
        if citation.evidence_kind:
            reasons.append(f"kind:{citation.evidence_kind}")
        if citation.evidence_modality:
            reasons.append(f"modality:{citation.evidence_modality}")
    if len(item.diagnostics.retrieval_sources) > 1:
        reasons.append("hybrid_retrieval")
    if item.diagnostics.review_only:
        reasons.append("review_only")
    if item.diagnostics.stale_reason:
        reasons.append("stale")
    return tuple(reasons)


def _citation_has_precise_location(citation: ContextCitation) -> bool:
    return (
        citation.char_start is not None
        or citation.char_end is not None
        or citation.page_number is not None
        or citation.time_start_ms is not None
        or citation.time_end_ms is not None
        or citation.bbox is not None
    )


def _evidence_selection_rank_key(
    selection: ContextEvidenceSelection,
) -> tuple[float, float, str, str, str, str]:
    citation = selection.citation
    citation_id = citation.citation_id if citation is not None else ""
    source_id = citation.source_id if citation is not None else ""
    return (
        -selection.score,
        -selection.item.score,
        selection.item.item_type,
        selection.item.item_id,
        source_id,
        citation_id,
    )


def _answer_support_from_payload(payload: object) -> ContextAnswerSupport:
    raw = _bounded_mapping(payload, max_items=MAX_BUNDLE_DIAGNOSTIC_ITEMS)
    warnings = tuple(
        warning
        for raw_warning in _as_list(raw.get("warnings"))[:MAX_LIST_ITEMS]
        if (warning := _safe_text(raw_warning, default="", limit=MAX_STRING_CHARS))
    )
    return ContextAnswerSupport(
        status=_safe_text(raw.get("status"), default="missing", limit=MAX_KEY_CHARS),
        items_returned=_non_negative_int(raw.get("items_returned")),
        coverage=_bounded_mapping(raw.get("coverage"), max_items=MAX_MAPPING_ITEMS),
        policy=_bounded_mapping(raw.get("policy"), max_items=MAX_MAPPING_ITEMS),
        warnings=warnings,
        raw=raw,
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
    review_recommended_action = _optional_text(
        raw.get("review_recommended_action"),
        limit=MAX_KEY_CHARS,
    )
    review_recommended_resolution_action = _optional_text(
        raw.get("review_recommended_resolution_action"),
        limit=MAX_KEY_CHARS,
    )
    review_default_resolution = _optional_text(
        raw.get("review_default_resolution"),
        limit=MAX_KEY_CHARS,
    )
    review_risk = _optional_text(raw.get("review_risk"), limit=MAX_KEY_CHARS)
    review_recommendation_confidence = _optional_text(
        raw.get("review_recommendation_confidence"),
        limit=MAX_KEY_CHARS,
    )
    review_policy_version = _optional_text(raw.get("review_policy_version"), limit=MAX_KEY_CHARS)
    review_requires_review = _safe_bool(raw.get("review_requires_review"))
    review_auto_merge_eligible = _safe_bool(raw.get("review_auto_merge_eligible"))
    review_recommendation_reason_codes = _safe_text_tuple(
        raw.get("review_recommendation_reason_codes"),
        limit=MAX_LIST_ITEMS,
    )
    review_resolution_options = _safe_review_resolution_options(
        raw.get("review_resolution_options")
    )
    for key, value in (
        ("review_recommended_action", review_recommended_action),
        ("review_recommended_resolution_action", review_recommended_resolution_action),
        ("review_default_resolution", review_default_resolution),
        ("review_risk", review_risk),
        ("review_recommendation_confidence", review_recommendation_confidence),
        ("review_policy_version", review_policy_version),
    ):
        if value:
            safe_raw[key] = value
    safe_raw["review_requires_review"] = review_requires_review
    safe_raw["review_auto_merge_eligible"] = review_auto_merge_eligible
    safe_raw["review_recommendation_reason_codes"] = list(review_recommendation_reason_codes)
    safe_raw["review_resolution_options"] = [dict(option) for option in review_resolution_options]
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
        review_recommended_action=review_recommended_action,
        review_recommended_resolution_action=review_recommended_resolution_action,
        review_default_resolution=review_default_resolution,
        review_risk=review_risk,
        review_recommendation_confidence=review_recommendation_confidence,
        review_policy_version=review_policy_version,
        review_requires_review=review_requires_review,
        review_auto_merge_eligible=review_auto_merge_eligible,
        review_recommendation_reason_codes=review_recommendation_reason_codes,
        review_resolution_options=review_resolution_options,
    )


