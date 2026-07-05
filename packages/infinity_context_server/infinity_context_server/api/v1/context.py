"""Search and prompt-context API."""

from __future__ import annotations

import re
from collections.abc import Iterable
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application import BuildContextQuery, ConsistencyMode
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
    normalize_context_diagnostics,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_metadata, safe_public_text
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_context_scope,
)
from infinity_context_server.api.v1.source_refs import source_ref_to_response
from infinity_context_server.composition import Container
from infinity_context_server.features.context_building import public as context_building_server

router = APIRouter(tags=["context"], dependencies=[Depends(require_service_token)])

_MAX_PUBLIC_CONTEXT_SOURCE_REFS = 20
_MAX_PUBLIC_TOP_EVIDENCE = 5
_MAX_PUBLIC_CONTEXT_DIAGNOSTICS = 260
_MAX_PUBLIC_ANSWER_SUPPORT_WARNINGS = 8
_MAX_ANSWER_SUPPORT_BREAKDOWN_ITEMS = 12


class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    memory_scope_external_refs: list[str] | None = Field(default=None, min_length=1, max_length=20)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=12000)
    consistency_mode: ConsistencyMode = Field(default=ConsistencyMode.BEST_EFFORT)
    token_budget: int = Field(default=1800, ge=64, le=16000)
    max_facts: int = Field(default=20, ge=0, le=100)
    max_chunks: int = Field(default=30, ge=0, le=200)
    max_evidence_items: int = Field(default=12, ge=0, le=100)
    max_conflicting_suggestions: int = Field(default=5, ge=0, le=20)
    include_superseded: bool = False
    include_stale: bool = False
    category: str | None = Field(default=None, max_length=80)
    tags_any: list[str] = Field(default_factory=list, max_length=10)
    tags_all: list[str] = Field(default_factory=list, max_length=10)
    tags_none: list[str] = Field(default_factory=list, max_length=10)


class BenchmarkContextRequest(ContextRequest):
    token_budget: int = Field(default=16000, ge=64, le=64000)
    max_facts: int = Field(default=200, ge=0, le=1000)
    max_chunks: int = Field(default=400, ge=0, le=2000)


def context_item_to_response(item) -> dict[str, Any]:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    source_refs = tuple(item.source_refs)
    public_source_refs = source_refs[:_MAX_PUBLIC_CONTEXT_SOURCE_REFS]
    citations = [
        _source_ref_to_citation(
            ref,
            item_id=str(item.item_id),
            item_type=str(item.item_type),
            index=index,
            diagnostics=diagnostics,
        )
        for index, ref in enumerate(public_source_refs)
    ]
    diagnostics["source_refs_total"] = len(source_refs)
    diagnostics["source_refs_returned"] = len(public_source_refs)
    diagnostics["source_refs_truncated"] = len(source_refs) > len(public_source_refs)
    diagnostics["citations_total"] = len(source_refs)
    diagnostics["citations_returned"] = len(citations)
    diagnostics["citations_truncated"] = len(source_refs) > len(citations)
    return {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "memory_scope_id": diagnostics.get("memory_scope_id"),
        "text": item.text,
        "score": item.score,
        "source_refs": [source_ref_to_response(ref) for ref in public_source_refs],
        "citations": citations,
        "is_instruction": item.is_instruction,
        "diagnostics": diagnostics,
    }


def _source_ref_to_citation(
    ref: object,
    *,
    item_id: str,
    item_type: str,
    index: int,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    source = source_ref_to_response(ref)
    citation_id = _citation_id(
        item_id=item_id,
        item_type=item_type,
        index=index,
    )
    evidence = _citation_evidence_context(diagnostics)
    char_range = _range_payload(source.get("char_start"), source.get("char_end"))
    time_range_ms = _range_payload(source.get("time_start_ms"), source.get("time_end_ms"))
    return {
        "citation_id": citation_id,
        "label": _citation_label(source, index=index, evidence=evidence),
        "source_type": source["source_type"],
        "source_id": source["source_id"],
        "chunk_id": source["chunk_id"],
        "quote_preview": source["quote_preview"],
        "char_range": char_range,
        "page_number": source["page_number"],
        "time_range_ms": time_range_ms,
        "bbox": source["bbox"],
        "evidence_kind": evidence["evidence_kind"],
        "evidence_modality": evidence["evidence_modality"],
        "evidence_confidence": evidence["evidence_confidence"],
        "retrieval_source": evidence["retrieval_source"],
        "ranking_reason": evidence["ranking_reason"],
    }


def _citation_id(*, item_id: str, item_type: str, index: int) -> str:
    safe_item_type = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", item_type)[:80] or "item"
    safe_item_id = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", item_id)[:120] or "unknown"
    return f"{safe_item_type}:{safe_item_id}:citation:{index + 1}"


def _citation_label(
    source: dict[str, Any],
    *,
    index: int,
    evidence: dict[str, Any],
) -> str:
    parts = [f"[{index + 1}]"]
    if evidence.get("evidence_kind"):
        parts.append(str(evidence["evidence_kind"]))
    if evidence.get("evidence_modality"):
        parts.append(str(evidence["evidence_modality"]))
    parts.append(str(source.get("source_type") or "source"))
    source_id = str(source.get("source_id") or "")
    if source_id:
        parts.append(source_id)
    if source.get("page_number") is not None:
        parts.append(f"p.{source['page_number']}")
    if source.get("time_start_ms") is not None or source.get("time_end_ms") is not None:
        parts.append(
            f"{source.get('time_start_ms') or 0}-{source.get('time_end_ms') or 0}ms"
        )
    if source.get("bbox") is not None:
        parts.append("bbox")
    return safe_public_text(" ".join(parts))[:240]


def _citation_evidence_context(diagnostics: dict[str, Any]) -> dict[str, Any]:
    provenance = diagnostics.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "evidence_kind": _optional_safe_text(
            diagnostics.get("evidence_kind") or provenance.get("evidence_kind")
        ),
        "evidence_modality": _optional_safe_text(
            diagnostics.get("evidence_modality") or provenance.get("evidence_modality")
        ),
        "evidence_confidence": _optional_float(
            diagnostics.get("evidence_confidence") or provenance.get("evidence_confidence")
        ),
        "retrieval_source": _optional_safe_text(diagnostics.get("retrieval_source")),
        "ranking_reason": _optional_safe_text(diagnostics.get("ranking_reason")),
    }


def _optional_safe_text(value: object) -> str | None:
    if value is None:
        return None
    text = safe_public_text(str(value)).strip()
    return text[:240] if text else None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _range_payload(start: object, end: object) -> dict[str, int | None] | None:
    if start is None and end is None:
        return None
    return {
        "start": int(start) if isinstance(start, int) else None,
        "end": int(end) if isinstance(end, int) else None,
    }


def _context_diagnostics_to_response(
    diagnostics: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    top_evidence: list[dict[str, Any]] | None = None,
    answer_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = safe_public_metadata(
        diagnostics,
        max_items=_MAX_PUBLIC_CONTEXT_DIAGNOSTICS,
    )
    top_evidence_items = top_evidence or []
    support = answer_support or {}
    support_coverage = (
        support.get("coverage") if isinstance(support.get("coverage"), dict) else {}
    )
    item_diagnostics = [
        item.get("diagnostics")
        for item in items
        if isinstance(item.get("diagnostics"), dict)
    ]
    source_refs_total = sum(
        _non_negative_int(item.get("source_refs_total")) for item in item_diagnostics
    )
    source_refs_returned = sum(
        _non_negative_int(item.get("source_refs_returned")) for item in item_diagnostics
    )
    citations_total = sum(
        _non_negative_int(item.get("citations_total")) for item in item_diagnostics
    )
    citations_returned = sum(len(item.get("citations") or []) for item in items)
    response.update(
        {
            "source_refs_total": source_refs_total,
            "source_refs_returned": source_refs_returned,
            "source_refs_truncated": source_refs_total > source_refs_returned,
            "citations_total": citations_total,
            "citations_returned": citations_returned,
            "citations_truncated": citations_total > citations_returned,
            "items_with_citations": sum(1 for item in items if item.get("citations")),
            "top_evidence_returned": len(top_evidence_items),
            "top_evidence_cited_count": sum(
                1 for item in top_evidence_items if item.get("citation") is not None
            ),
            "answer_support_status": _optional_safe_text(support.get("status")) or "missing",
            "answer_support_items_returned": _non_negative_int(support.get("items_returned")),
            "answer_support_cited_count": _non_negative_int(
                support_coverage.get("cited_support_count")
            ),
            "answer_support_precise_location_count": _non_negative_int(
                support_coverage.get("precise_location_support_count")
            ),
            "answer_support_multimodal_count": _non_negative_int(
                support_coverage.get("multimodal_support_count")
            ),
            "answer_support_coverage_ratio": _safe_float(
                support_coverage.get("supported_item_ratio")
            ),
            "answer_support_source_type_count": _non_negative_int(
                support_coverage.get("source_type_count")
            ),
            "answer_support_evidence_kind_count": _non_negative_int(
                support_coverage.get("evidence_kind_count")
            ),
            "answer_support_evidence_modality_count": _non_negative_int(
                support_coverage.get("evidence_modality_count")
            ),
            "answer_support_warnings": [
                warning
                for raw_warning in (support.get("warnings") or [])[
                    :_MAX_PUBLIC_ANSWER_SUPPORT_WARNINGS
                ]
                if isinstance(raw_warning, str)
                if (warning := safe_public_text(raw_warning, limit=120))
            ],
        }
    )
    return response


def _top_evidence_to_response(
    items: list[dict[str, Any]],
    *,
    limit: int = _MAX_PUBLIC_TOP_EVIDENCE,
    include_review_only: bool = False,
    include_stale: bool = False,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    candidates: list[dict[str, Any]] = []
    for item in items:
        diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
        if not include_review_only and diagnostics.get("review_only") is True:
            continue
        if not include_stale and diagnostics.get("stale_reason"):
            continue
        citations = item.get("citations")
        if isinstance(citations, list) and citations:
            for citation in citations:
                if isinstance(citation, dict):
                    candidates.append(_top_evidence_candidate(item, citation=citation))
    candidates.sort(
        key=lambda candidate: (
            -_safe_float(candidate.get("score")),
            str(candidate.get("item_type") or ""),
            str(candidate.get("item_id") or ""),
            str((candidate.get("citation") or {}).get("citation_id") or ""),
        )
    )
    return candidates[:limit]


def _answer_support_to_response(
    *,
    items: list[dict[str, Any]],
    top_evidence: list[dict[str, Any]],
    diagnostics: dict[str, Any] | None = None,
    limit: int = _MAX_PUBLIC_TOP_EVIDENCE,
) -> dict[str, Any]:
    evidence_items = top_evidence[: max(0, limit)]
    coverage = _answer_support_coverage(items=items, top_evidence=evidence_items)
    warnings = _answer_support_warnings(
        items=items,
        coverage=coverage,
        diagnostics=diagnostics or {},
    )
    return {
        "status": _answer_support_status(coverage=coverage, warnings=warnings),
        "items": evidence_items,
        "items_returned": len(evidence_items),
        "coverage": coverage,
        "policy": {
            "requires_citations": True,
            "excludes_review_only_by_default": True,
            "excludes_stale_by_default": True,
            "max_items": limit,
        },
        "warnings": warnings,
    }


def _answer_support_coverage(
    *,
    items: list[dict[str, Any]],
    top_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    item_count = len(items)
    supported_item_ids = {
        str(item.get("item_id"))
        for item in top_evidence
        if item.get("item_id") is not None
    }
    cited_support = [item for item in top_evidence if item.get("citation") is not None]
    precise_support = [
        item
        for item in cited_support
        if _citation_has_precise_location(item.get("citation"))
    ]
    quote_support = [
        item for item in cited_support if _citation_has_quote_preview(item.get("citation"))
    ]
    multimodal_support = [
        item for item in cited_support if _citation_has_multimodal_evidence(item.get("citation"))
    ]
    location_counts = _answer_support_location_counts(cited_support)
    source_type_counts = _support_citation_counts(cited_support, "source_type")
    evidence_kind_counts = _support_citation_counts(cited_support, "evidence_kind")
    evidence_modality_counts = _support_citation_counts(cited_support, "evidence_modality")
    return {
        "context_item_count": item_count,
        "supported_item_count": len(supported_item_ids),
        "supported_item_ratio": _ratio(len(supported_item_ids), item_count),
        "cited_support_count": len(cited_support),
        "precise_location_support_count": len(precise_support),
        "quote_preview_support_count": len(quote_support),
        "multimodal_support_count": len(multimodal_support),
        "uncited_context_item_count": max(0, item_count - len(supported_item_ids)),
        "supported_item_types": _support_item_type_counts(top_evidence),
        "support_source_types": source_type_counts,
        "support_evidence_kinds": evidence_kind_counts,
        "support_evidence_modalities": evidence_modality_counts,
        "location_support_counts": location_counts,
        "source_type_count": len(_non_empty_keys(source_type_counts)),
        "evidence_kind_count": len(_non_empty_keys(evidence_kind_counts)),
        "evidence_modality_count": len(_non_empty_keys(evidence_modality_counts)),
    }


def _answer_support_warnings(
    *,
    items: list[dict[str, Any]],
    coverage: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not items:
        warnings.append("no_context_items")
    if _non_negative_int(coverage.get("cited_support_count")) <= 0:
        warnings.append("no_cited_support")
    if _safe_float(coverage.get("supported_item_ratio")) < 0.5 and items:
        warnings.append("low_supported_item_ratio")
    if _non_negative_int(coverage.get("quote_preview_support_count")) <= 0 and items:
        warnings.append("missing_quote_preview")
    if _non_negative_int(coverage.get("precise_location_support_count")) <= 0 and items:
        warnings.append("missing_precise_location")
    excluded_review = sum(
        1
        for item in items
        if isinstance(item.get("diagnostics"), dict)
        and item["diagnostics"].get("review_only") is True
    )
    excluded_stale = sum(
        1
        for item in items
        if isinstance(item.get("diagnostics"), dict)
        and item["diagnostics"].get("stale_reason")
    )
    if excluded_review:
        warnings.append("review_only_items_excluded")
    if excluded_stale:
        warnings.append("stale_items_excluded")
    warnings.extend(_answer_support_requirement_warnings(diagnostics))
    return warnings[:_MAX_PUBLIC_ANSWER_SUPPORT_WARNINGS]


def _answer_support_status(
    *,
    coverage: dict[str, Any],
    warnings: list[str],
) -> str:
    if any(warning in warnings for warning in _CRITICAL_REQUIREMENT_WARNINGS):
        return "missing"
    if "no_context_items" in warnings or "no_cited_support" in warnings:
        return "missing"
    if "explicit_requirements_missing" in warnings:
        return "partial"
    if "missing_quote_preview" in warnings or "missing_precise_location" in warnings:
        return "partial"
    if _safe_float(coverage.get("supported_item_ratio")) >= 0.5:
        return "strong"
    return "partial"


_CRITICAL_REQUIREMENT_WARNINGS = frozenset(
    {
        "missing_citation_requirement",
        "missing_extracted_text_requirement",
        "missing_page_or_char_requirement",
        "missing_time_range_requirement",
        "missing_visual_region_requirement",
    }
)


def _answer_support_requirement_warnings(diagnostics: dict[str, Any]) -> list[str]:
    coverage = diagnostics.get("context_requirement_coverage")
    if not isinstance(coverage, dict):
        return []
    if _non_negative_int(coverage.get("missing_total")) <= 0:
        return []

    warnings = ["explicit_requirements_missing"]
    for feature in _safe_requirement_values(coverage.get("missing_evidence_features")):
        warnings.append(f"missing_{feature}_requirement")
    for modality in _safe_requirement_values(coverage.get("missing_modalities")):
        warnings.append(f"missing_{modality}_modality_requirement")
    for kind in _safe_requirement_values(coverage.get("missing_anchor_kinds")):
        warnings.append(f"missing_{kind}_anchor_requirement")
    return warnings


def _safe_requirement_values(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    safe_values: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower().replace("-", "_")
        if not normalized or not normalized.replace("_", "").isalnum():
            continue
        safe_values.append(normalized[:64])
    return safe_values


def _citation_has_precise_location(citation: object) -> bool:
    if not isinstance(citation, dict):
        return False
    return any(
        citation.get(key) is not None
        for key in ("char_range", "page_number", "time_range_ms", "bbox")
    )


def _citation_has_quote_preview(citation: object) -> bool:
    return isinstance(citation, dict) and bool(citation.get("quote_preview"))


def _citation_has_multimodal_evidence(citation: object) -> bool:
    if not isinstance(citation, dict):
        return False
    modality = citation.get("evidence_modality")
    kind = citation.get("evidence_kind")
    return bool(modality) or kind in {"ocr_region", "transcript_segment", "keyframe"}


def _answer_support_location_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "char_range": 0,
        "page_number": 0,
        "time_range_ms": 0,
        "bbox": 0,
    }
    for item in items:
        citation = item.get("citation")
        if not isinstance(citation, dict):
            continue
        if citation.get("char_range") is not None:
            counts["char_range"] += 1
        if citation.get("page_number") is not None:
            counts["page_number"] += 1
        if citation.get("time_range_ms") is not None:
            counts["time_range_ms"] += 1
        if citation.get("bbox") is not None:
            counts["bbox"] += 1
    return counts


def _support_item_type_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    return _bounded_counts(
        safe_public_text(str(item.get("item_type") or ""), limit=80)
        for item in items
    )


def _support_citation_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    return _bounded_counts(
        safe_public_text(str((item.get("citation") or {}).get(key) or ""), limit=80)
        for item in items
        if isinstance(item.get("citation"), dict)
    )


def _bounded_counts(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(
        sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:_MAX_ANSWER_SUPPORT_BREAKDOWN_ITEMS]
    )


def _non_empty_keys(counts: dict[str, int]) -> tuple[str, ...]:
    return tuple(key for key, count in counts.items() if count > 0)


def _top_evidence_candidate(
    item: dict[str, Any],
    *,
    citation: dict[str, Any] | None,
) -> dict[str, Any]:
    diagnostics = item.get("diagnostics") if isinstance(item.get("diagnostics"), dict) else {}
    return {
        "item_id": item.get("item_id"),
        "item_type": item.get("item_type"),
        "memory_scope_id": item.get("memory_scope_id"),
        "text": item.get("text"),
        "score": _top_evidence_score(
            item=item,
            citation=citation,
            diagnostics=diagnostics,
        ),
        "reasons": _top_evidence_reasons(
            item=item,
            citation=citation,
            diagnostics=diagnostics,
        ),
        "citation": citation,
    }


def _top_evidence_score(
    *,
    item: dict[str, Any],
    citation: dict[str, Any] | None,
    diagnostics: dict[str, Any],
) -> float:
    score = _safe_float(item.get("score"))
    if citation is not None:
        score += _citation_quality_boost(citation)
    retrieval_sources = diagnostics.get("retrieval_sources")
    if isinstance(retrieval_sources, list) and len(retrieval_sources) > 1:
        score += 0.035
    if diagnostics.get("review_only") is True:
        score -= 0.08
    if diagnostics.get("stale_reason"):
        score -= 0.12
    return round(max(0.0, min(1.0, score)), 4)


def _citation_quality_boost(citation: dict[str, Any]) -> float:
    boost = 0.0
    if citation.get("time_range_ms") is not None:
        boost += 0.035
    if citation.get("bbox") is not None:
        boost += 0.035
    if citation.get("page_number") is not None:
        boost += 0.02
    if citation.get("quote_preview"):
        boost += 0.015
    confidence = _safe_float(citation.get("evidence_confidence"))
    if confidence > 0:
        boost += min(0.04, confidence * 0.04)
    return boost


def _top_evidence_reasons(
    *,
    item: dict[str, Any],
    citation: dict[str, Any] | None,
    diagnostics: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if _safe_float(item.get("score")) >= 0.85:
        reasons.append("high_context_score")
    retrieval_source = diagnostics.get("retrieval_source")
    if isinstance(retrieval_source, str) and retrieval_source:
        reasons.append(f"retrieved_by:{safe_public_text(retrieval_source, limit=80)}")
    retrieval_sources = diagnostics.get("retrieval_sources")
    if isinstance(retrieval_sources, list) and len(retrieval_sources) > 1:
        reasons.append("hybrid_retrieval")
    if citation is not None:
        if citation.get("quote_preview"):
            reasons.append("quote_preview")
        if citation.get("page_number") is not None:
            reasons.append("page_citation")
        if citation.get("time_range_ms") is not None:
            reasons.append("time_range_citation")
        if citation.get("bbox") is not None:
            reasons.append("bbox_citation")
        if citation.get("evidence_kind"):
            reasons.append(f"kind:{safe_public_text(str(citation['evidence_kind']), limit=80)}")
        if citation.get("evidence_modality"):
            reasons.append(
                f"modality:{safe_public_text(str(citation['evidence_modality']), limit=80)}"
            )
    return reasons[:10]


def _safe_float(value: object) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _legacy_build_context_query_from_feature_seam(
    request: ContextRequest,
    *,
    scope,
    max_rendered_chars: int,
) -> BuildContextQuery:
    feature_query = _feature_context_query_for_legacy_request(request, scope=scope)
    memory_scope_ids = scope.memory_scope_ids
    if feature_query is not None and len(memory_scope_ids) == 1:
        memory_scope_ids = (feature_query.query.scope.memory_scope_id,)
    space_id = feature_query.query.scope.space_id if feature_query is not None else scope.space_id
    thread_id = (
        feature_query.query.scope.thread_id if feature_query is not None else scope.thread_id
    )
    token_budget = (
        feature_query.budget.max_prompt_tokens
        if feature_query is not None
        else request.token_budget
    )

    return BuildContextQuery(
        space_id=space_id,
        memory_scope_ids=memory_scope_ids,
        thread_id=thread_id,
        query=request.query,
        consistency_mode=request.consistency_mode,
        token_budget=token_budget,
        max_rendered_chars=max_rendered_chars,
        max_facts=request.max_facts,
        max_chunks=request.max_chunks,
        max_evidence_items=request.max_evidence_items,
        max_conflicting_suggestions=request.max_conflicting_suggestions,
        include_superseded=request.include_superseded,
        include_stale=request.include_stale,
        category=_normalize_label(request.category),
        tags_any=_normalize_tags(request.tags_any),
        tags_all=_normalize_tags(request.tags_all),
        tags_none=_normalize_tags(request.tags_none),
    )


def _feature_context_query_for_legacy_request(request: ContextRequest, *, scope):
    if not scope.memory_scope_ids:
        return None

    try:
        return context_building_server.build_context_query_from_contract(
            context_building_server.BuildContextHttpRequest(
                query=request.query,
                space_id=str(scope.space_id),
                memory_scope_id=str(scope.memory_scope_ids[0]),
                thread_id=str(scope.thread_id) if scope.thread_id else None,
                budget=context_building_server.ContextBudgetHttpRequest(
                    max_context_tokens=request.token_budget,
                ),
                tags=request.tags_any,
            ).to_contract()
        )
    except (ValueError, ValidationError):
        return None


@router.post("/context")
async def build_context(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _empty_context_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_context",
        )
        return response
    bundle = await container.build_context.execute(
        _legacy_build_context_query_from_feature_seam(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    response_items = [context_item_to_response(item) for item in bundle.items]
    top_evidence = _top_evidence_to_response(response_items)
    answer_support = _answer_support_to_response(
        items=response_items,
        top_evidence=top_evidence,
        diagnostics=bundle.diagnostics,
    )
    response_diagnostics = _context_diagnostics_to_response(
        bundle.diagnostics,
        items=response_items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": bundle.bundle_id,
            "rendered_text": bundle.rendered_text,
            "items": response_items,
            "top_evidence": top_evidence,
            "answer_support": answer_support,
            "diagnostics": response_diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response_diagnostics,
        request_id=request_id,
        use_case="build_context",
        scope=_trace_scope(scope),
    )
    return response


@router.post("/search")
async def search_memory(
    request: ContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = {
            "meta": {"request_id": request_id},
            "data": {
                "items": [],
                "top_evidence": [],
                "next_cursor": None,
                "diagnostics": _empty_context_diagnostics(
                    policy_mode=container.settings.policy_mode.value,
                    consistency_mode=request.consistency_mode.value,
                    retrieval_disabled=True,
                ),
            },
        }
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _empty_search_response(
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            consistency_mode=request.consistency_mode.value,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="search_memory",
        )
        return response
    bundle = await container.build_context.execute(
        _legacy_build_context_query_from_feature_seam(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    response_items = [context_item_to_response(item) for item in bundle.items]
    top_evidence = _top_evidence_to_response(response_items)
    answer_support = _answer_support_to_response(
        items=response_items,
        top_evidence=top_evidence,
        diagnostics=bundle.diagnostics,
    )
    response_diagnostics = _context_diagnostics_to_response(
        bundle.diagnostics,
        items=response_items,
        top_evidence=top_evidence,
        answer_support=answer_support,
    )
    response = {
        "meta": {"request_id": request_id},
        "data": {
            "items": response_items,
            "top_evidence": top_evidence,
            "answer_support": answer_support,
            "next_cursor": None,
            "diagnostics": response_diagnostics,
        },
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=response_diagnostics,
        request_id=request_id,
        use_case="search_memory",
        scope=_trace_scope(scope),
    )
    return response


@router.post("/context/benchmark-search", include_in_schema=False)
async def benchmark_search_memory(
    request: BenchmarkContextRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return await search_memory(request, container)  # type: ignore[arg-type]


def _empty_context_response(
    *,
    policy_mode: str,
    request_id: str,
    consistency_mode: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    return {
        "meta": {"request_id": request_id},
        "data": {
            "bundle_id": "ctx_disabled",
            "rendered_text": "",
            "items": [],
            "top_evidence": [],
            "answer_support": _answer_support_to_response(items=[], top_evidence=[]),
            "diagnostics": _empty_context_diagnostics(
                policy_mode=policy_mode,
                consistency_mode=consistency_mode,
                retrieval_disabled=not scope_not_found,
                scope_not_found=scope_not_found,
            ),
        },
    }


def _empty_search_response(
    *,
    policy_mode: str,
    request_id: str,
    consistency_mode: str,
    scope_not_found: bool = False,
) -> dict[str, Any]:
    return {
        "meta": {"request_id": request_id},
        "data": {
            "items": [],
            "top_evidence": [],
            "answer_support": _answer_support_to_response(items=[], top_evidence=[]),
            "next_cursor": None,
            "diagnostics": _empty_context_diagnostics(
                policy_mode=policy_mode,
                consistency_mode=consistency_mode,
                retrieval_disabled=not scope_not_found,
                scope_not_found=scope_not_found,
            ),
        },
    }


def _empty_context_diagnostics(
    *,
    policy_mode: str,
    consistency_mode: str,
    retrieval_disabled: bool,
    scope_not_found: bool = False,
) -> dict[str, object]:
    reason = "scope_not_found" if scope_not_found else "retrieval_disabled"
    return normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "consistency_mode": consistency_mode,
            "policy_mode": policy_mode,
            "retrieval_disabled": retrieval_disabled,
            "scope_not_found": scope_not_found,
            "vector_status": "skipped",
            "vector_skip_reason": reason,
            "graph_status": "skipped",
            "graph_skip_reason": reason,
            "rag_status": "skipped",
            "rag_skip_reason": reason,
        },
        items=(),
    )


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


_LABEL_RE = re.compile(r"[^a-z0-9_-]+")


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _LABEL_RE.sub("_", value.strip().lower()).strip("_-")
    return normalized or None


def _normalize_tags(values: list[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        normalized = _normalize_label(value)
        if normalized and normalized not in tags:
            tags.append(normalized[:48].rstrip("_-"))
    return tuple(tag for tag in tags if tag)


def _trace_scope(scope) -> dict[str, object]:
    return {
        "space_id": str(scope.space_id),
        "memory_scope_ids": tuple(
            str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
        ),
        "thread_id": str(scope.thread_id) if scope.thread_id else None,
    }
