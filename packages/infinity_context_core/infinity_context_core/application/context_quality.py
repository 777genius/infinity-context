"""Retrieval quality diagnostics for prompt context bundles."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application.dto import ContextItem

_MAX_ACTIONABLE_GAPS = 8


def retrieval_quality_summary(
    diagnostics: dict[str, object],
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    item_count = len(items)
    provenance = _as_dict(diagnostics.get("provenance_summary"))
    citation_coverage = _ratio_float(provenance.get("citation_coverage_ratio"))
    precise_location_coverage = _ratio_float(provenance.get("precise_location_coverage_ratio"))
    retrieval_source_count = _non_negative_int(
        diagnostics.get("retrieval_sources_total"),
        default=0,
    )
    hybrid_items = _non_negative_int(diagnostics.get("hybrid_items_used"), default=0)
    multimodal_items = _non_negative_int(
        diagnostics.get("items_with_multimodal_source_refs"),
        default=0,
    )
    query_snippet_items = _non_negative_int(
        diagnostics.get("query_snippet_items_used"),
        default=0,
    )
    evidence_profile = _as_dict(diagnostics.get("evidence_coverage_profile"))
    evidence_items_total = _non_negative_int(
        evidence_profile.get("evidence_items_total"),
        default=0,
    )
    evidence_location_gap_count = _non_negative_int(
        evidence_profile.get("evidence_location_gap_count"),
        default=0,
    )
    evidence_location_coverage = _ratio_float(
        evidence_profile.get("precise_evidence_location_coverage_ratio"),
    )
    review_only_items = _non_negative_int(provenance.get("review_only_items"), default=0)
    pending_review_items = _non_negative_int(
        provenance.get("pending_review_items"),
        default=0,
    )
    stale_items = _non_negative_int(provenance.get("stale_items"), default=0)
    stale_filtered_count = _stale_filtered_count(diagnostics)
    temporal_replacement_count = _non_negative_int(
        diagnostics.get("temporal_replacements_applied"),
        default=0,
    ) + _non_negative_int(
        diagnostics.get("linked_temporal_replacements_applied"),
        default=0,
    )
    superseded_review_items = _non_negative_int(
        diagnostics.get("superseded_facts_used"),
        default=0,
    )
    scores = tuple(_safe_item_score(item) for item in items)
    high_confidence_items = sum(1 for score in scores if score >= 0.82)
    medium_confidence_items = sum(1 for score in scores if 0.65 <= score < 0.82)
    low_confidence_items = sum(1 for score in scores if score < 0.65)
    evidence_strength = _evidence_strength(
        item_count=item_count,
        citation_coverage=citation_coverage,
        retrieval_source_count=retrieval_source_count,
        review_only_items=review_only_items,
        pending_review_items=pending_review_items,
        stale_items=stale_items,
        low_confidence_items=low_confidence_items,
    )
    freshness_status = _freshness_status(
        item_count=item_count,
        stale_items=stale_items,
        stale_filtered_count=stale_filtered_count,
        temporal_replacement_count=temporal_replacement_count,
    )
    actionable_gaps = _retrieval_quality_gaps(
        diagnostics=diagnostics,
        item_count=item_count,
        citation_coverage=citation_coverage,
        precise_location_coverage=precise_location_coverage,
        retrieval_source_count=retrieval_source_count,
        multimodal_items=multimodal_items,
        query_snippet_items=query_snippet_items,
        evidence_items_total=evidence_items_total,
        evidence_location_coverage=evidence_location_coverage,
        evidence_location_gap_count=evidence_location_gap_count,
        review_only_items=review_only_items,
        pending_review_items=pending_review_items,
        stale_items=stale_items,
        low_confidence_items=low_confidence_items,
    )
    answerability_status = _answerability_status(
        item_count=item_count,
        evidence_strength=evidence_strength,
        review_only_items=review_only_items,
        pending_review_items=pending_review_items,
        stale_items=stale_items,
    )
    return {
        "schema_version": "retrieval-quality-v1",
        "evidence_strength": evidence_strength,
        "answerability_status": answerability_status,
        "recommended_response_policy": _recommended_response_policy(answerability_status),
        "retrieval_mode": _retrieval_mode(
            item_count=item_count,
            retrieval_source_count=retrieval_source_count,
            multimodal_items=multimodal_items,
        ),
        "freshness_status": freshness_status,
        "items_total": item_count,
        "retrieval_source_count": retrieval_source_count,
        "hybrid_item_ratio": _ratio(hybrid_items, item_count),
        "citation_coverage_ratio": citation_coverage,
        "precise_location_coverage_ratio": precise_location_coverage,
        "query_snippet_coverage_ratio": _ratio(query_snippet_items, item_count),
        "multimodal_item_ratio": _ratio(multimodal_items, item_count),
        "evidence_location_coverage_ratio": evidence_location_coverage,
        "evidence_location_gap_count": evidence_location_gap_count,
        "review_pressure_ratio": _ratio(
            review_only_items + pending_review_items,
            item_count,
        ),
        "stale_item_ratio": _ratio(stale_items, item_count),
        "stale_filtered_count": stale_filtered_count,
        "temporal_replacement_count": temporal_replacement_count,
        "superseded_review_ratio": _ratio(superseded_review_items, item_count),
        "default_context_excludes_stale": stale_items == 0
        and not bool(diagnostics.get("include_stale"))
        and not bool(diagnostics.get("include_superseded")),
        "high_confidence_items": high_confidence_items,
        "medium_confidence_items": medium_confidence_items,
        "low_confidence_items": low_confidence_items,
        "evidence_kind_count": len(_as_dict(diagnostics.get("evidence_kind_counts"))),
        "evidence_modality_count": len(_as_dict(diagnostics.get("evidence_modality_counts"))),
        "actionable_gaps": actionable_gaps,
        "answerability_reasons": _answerability_reasons(
            answerability_status=answerability_status,
            actionable_gaps=actionable_gaps,
        ),
    }


def _evidence_strength(
    *,
    item_count: int,
    citation_coverage: float,
    retrieval_source_count: int,
    review_only_items: int,
    pending_review_items: int,
    stale_items: int,
    low_confidence_items: int,
) -> str:
    if item_count <= 0:
        return "empty"
    if review_only_items + pending_review_items >= item_count or stale_items >= item_count:
        return "weak"
    if low_confidence_items > item_count // 2:
        return "weak"
    if citation_coverage < 0.34:
        return "weak"
    if (
        citation_coverage >= 0.8
        and low_confidence_items == 0
        and stale_items == 0
        and review_only_items == 0
        and pending_review_items == 0
        and (retrieval_source_count >= 2 or item_count == 1)
    ):
        return "strong"
    return "usable"


def _retrieval_mode(
    *,
    item_count: int,
    retrieval_source_count: int,
    multimodal_items: int,
) -> str:
    if item_count <= 0:
        return "empty"
    if retrieval_source_count > 1 and multimodal_items > 0:
        return "hybrid_multimodal"
    if retrieval_source_count > 1:
        return "hybrid"
    if multimodal_items > 0:
        return "multimodal_single_source"
    return "single_source"


def _freshness_status(
    *,
    item_count: int,
    stale_items: int,
    stale_filtered_count: int,
    temporal_replacement_count: int,
) -> str:
    if item_count <= 0:
        return "empty"
    if stale_items > 0:
        return "stale_present"
    if temporal_replacement_count > 0:
        return "fresh_with_temporal_replacements"
    if stale_filtered_count > 0:
        return "fresh_with_stale_filtered"
    return "fresh"


def _answerability_status(
    *,
    item_count: int,
    evidence_strength: str,
    review_only_items: int,
    pending_review_items: int,
    stale_items: int,
) -> str:
    if item_count <= 0:
        return "insufficient_context"
    if review_only_items + pending_review_items >= item_count or stale_items >= item_count:
        return "needs_review"
    if evidence_strength == "strong":
        return "grounded"
    if evidence_strength == "weak":
        return "insufficient_evidence"
    return "usable_with_caveats"


def _recommended_response_policy(answerability_status: str) -> str:
    if answerability_status == "grounded":
        return "answer_with_citations"
    if answerability_status == "usable_with_caveats":
        return "answer_with_caveat_and_citations"
    if answerability_status == "needs_review":
        return "review_before_answering"
    return "ask_for_more_context"


def _answerability_reasons(
    *,
    answerability_status: str,
    actionable_gaps: list[str],
) -> list[str]:
    if answerability_status == "grounded":
        return []
    if answerability_status == "usable_with_caveats":
        return actionable_gaps[:4] or ["limited_context_evidence"]
    if answerability_status == "needs_review":
        review_gaps = [
            gap
            for gap in actionable_gaps
            if gap in {"review_items_present", "stale_items_present"}
        ]
        return (review_gaps or actionable_gaps or ["review_required"])[
            :_MAX_ACTIONABLE_GAPS
        ]
    return (actionable_gaps or ["insufficient_context"])[
        :_MAX_ACTIONABLE_GAPS
    ]


def _retrieval_quality_gaps(
    *,
    diagnostics: dict[str, object],
    item_count: int,
    citation_coverage: float,
    precise_location_coverage: float,
    retrieval_source_count: int,
    multimodal_items: int,
    query_snippet_items: int,
    evidence_items_total: int,
    evidence_location_coverage: float,
    evidence_location_gap_count: int,
    review_only_items: int,
    pending_review_items: int,
    stale_items: int,
    low_confidence_items: int,
) -> list[str]:
    gaps: list[str] = []
    if item_count <= 0:
        gaps.append("no_context_items")
        return gaps
    if citation_coverage < 0.5:
        gaps.append("low_citation_coverage")
    if multimodal_items > 0 and precise_location_coverage < 0.5:
        gaps.append("low_precise_location_coverage")
    if evidence_items_total > 0 and evidence_location_coverage < 0.5:
        gaps.append("low_evidence_location_coverage")
    if evidence_location_gap_count > 0:
        gaps.append("evidence_location_gaps_present")
    if retrieval_source_count <= 1 and item_count > 1:
        gaps.append("single_retrieval_channel")
    if query_snippet_items <= 0 and item_count > 1:
        gaps.append("no_query_focused_snippets")
    if low_confidence_items > 0:
        gaps.append("low_confidence_items_present")
    if stale_items > 0:
        gaps.append("stale_items_present")
    if review_only_items + pending_review_items > 0:
        gaps.append("review_items_present")
    if _non_negative_int(diagnostics.get("dropped_by_budget"), default=0) > 0:
        gaps.append("budget_drops_present")
    if _non_negative_int(diagnostics.get("dropped_by_source_cap"), default=0) > 0:
        gaps.append("source_cap_drops_present")
    if (
        _non_negative_int(
            diagnostics.get("sensitive_item_text_redacted"),
            default=0,
        )
        > 0
    ):
        gaps.append("sensitive_text_redacted")
    if (
        _non_negative_int(
            diagnostics.get("sensitive_source_identity_parts_redacted"),
            default=0,
        )
        > 0
    ):
        gaps.append("sensitive_source_identity_redacted")
    if (
        _non_negative_int(
            diagnostics.get("unsafe_source_identity_parts_sanitized"),
            default=0,
        )
        > 0
    ):
        gaps.append("unsafe_source_identity_sanitized")
    return gaps[:_MAX_ACTIONABLE_GAPS]


def _safe_item_score(item: ContextItem) -> float:
    try:
        score = float(item.score)
    except (TypeError, ValueError):
        return 0.0
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return round(score, 4)


def _stale_filtered_count(diagnostics: dict[str, object]) -> int:
    keys = (
        "stale_vector_drop_count",
        "stale_graph_drop_count",
        "stale_rag_drop_count",
        "artifact_evidence_stale_asset_drop_count",
        "stale_context_linked_chunk_drop_count",
        "stale_context_linked_fact_drop_count",
        "stale_context_linked_anchor_drop_count",
        "stale_context_linked_asset_drop_count",
        "stale_context_linked_extraction_artifact_drop_count",
    )
    return sum(_non_negative_int(diagnostics.get(key), default=0) for key in keys)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _ratio_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return max(0.0, min(1.0, round(float(value), 4)))
    return 0.0


def _non_negative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(value)
    return default


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
