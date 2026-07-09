"""Evidence support signals for deterministic context reranking."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.application.context_diagnostics import (
    diagnostic_retrieval_sources,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY,
    QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_requirement_signals import (
    RequirementCoverageSignals,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST = 0.018
_CITATION_EVIDENCE_RERANK_MAX_BOOST = 0.024
_ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST = 0.028
_DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST = 0.022
_LOCALIZED_EVIDENCE_RERANK_MAX_BOOST = 0.022
_BROAD_DECOMPOSITION_COVERAGE_REASONS = frozenset(
    {
        "decomposition_clause",
        "decomposition_inventory_list",
        "decomposition_quantity_count",
        "decomposition_temporal_answer",
    }
)
_ARTIFACT_INVENTORY_RERANK_SOURCES = frozenset(
    {
        "approved_context_linked_asset_manifest_evidence",
        "approved_context_linked_assets",
        "approved_context_linked_extraction_artifacts",
        "artifact_evidence",
    }
)
_ARTIFACT_INVENTORY_SOURCE_REF_TYPES = frozenset(
    {
        "asset",
        "extraction_artifact",
    }
)


def localized_evidence_support_signal(
    *,
    item: ContextItem,
    relevance: QueryRelevance,
    coverage_ratio: float,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str]:
    localized_refs = tuple(ref for ref in item.source_refs if _source_ref_has_precise_location(ref))
    if not localized_refs:
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and coverage_ratio <= 0
        and not anchor_matched
        and strong_source_count <= 0
    ):
        return 0.0, ""
    source_count = len({(ref.source_type, ref.source_id) for ref in localized_refs})
    feature_count = len(
        {
            feature
            for ref in localized_refs
            for feature in _source_ref_location_features(ref)
        }
    )
    boost = 0.008
    boost += min(0.006, 0.003 * max(0, len(localized_refs) - 1))
    boost += min(0.004, 0.002 * max(0, source_count - 1))
    boost += min(0.004, 0.002 * max(0, feature_count - 1))
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    if _safe_evidence_kind_or_modality(diagnostics):
        boost += 0.003
    reason = (
        "multi_localized_evidence_source"
        if len(localized_refs) >= 2 or source_count >= 2 or feature_count >= 2
        else "localized_evidence_source"
    )
    return round(min(_LOCALIZED_EVIDENCE_RERANK_MAX_BOOST, boost), 4), reason


def decomposition_coverage_support_signal(
    *,
    plan: QueryExpansionPlan,
    text: str,
    query_reason: str,
) -> tuple[float, str, dict[str, float]]:
    if len(plan.decompositions) < 2:
        return 0.0, "", {}
    if (
        not query_reason.startswith("decomposition_")
        or query_reason in _BROAD_DECOMPOSITION_COVERAGE_REASONS
    ):
        return 0.0, "", {}
    matched_reasons: set[str] = set()
    priority_total = 0
    distinctive_hit_total = 0
    for decomposition in plan.decompositions:
        reason = decomposition.reason
        if (
            reason in _BROAD_DECOMPOSITION_COVERAGE_REASONS
            or not reason.startswith("decomposition_")
        ):
            continue
        relevance = score_query_relevance(query=decomposition.query, text=text)
        priority = _query_reason_priority_for_relevance(reason, relevance)
        if priority <= 0 and reason.startswith("decomposition_"):
            priority = 3
        min_distinctive_hits = max(
            4,
            QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0),
        )
        if (
            priority <= 0
            or relevance.distinctive_term_hits < min_distinctive_hits
            or (relevance.hit_ratio < 0.12 and relevance.phrase_bigram_hits <= 0)
        ):
            continue
        matched_reasons.add(reason)
        priority_total += priority
        distinctive_hit_total += relevance.distinctive_term_hits
    if len(matched_reasons) < 2:
        return 0.0, "", {}

    boost = 0.006 + min(0.012, 0.005 * len(matched_reasons))
    if priority_total >= 8:
        boost += 0.002
    if distinctive_hit_total >= 8:
        boost += 0.002
    boost = round(min(_DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST, boost), 4)
    return (
        boost,
        "query_decomposition_multi_intent_covered",
        {
            "query_decomposition_covered_reason_count": float(len(matched_reasons)),
            "query_decomposition_coverage_boost": boost,
        },
    )


def canonical_anchor_summary_support_signal(
    *,
    item: ContextItem,
    coverage: RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    anchor_conflict: bool,
    sources: tuple[str, ...],
    strong_source_count: int,
) -> tuple[float, str]:
    if anchor_conflict or "summary" not in coverage.requested_answer_shapes:
        return 0.0, ""
    if not coverage.requested_anchor_kinds & coverage.covered_anchor_kinds:
        return 0.0, ""
    if not _is_canonical_anchor_source(item=item, sources=sources):
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and not anchor_matched
        and coverage.ratio <= 0
    ):
        return 0.0, ""
    if not _has_canonical_anchor_profile_evidence(item):
        return 0.0, ""

    boost = 0.01
    if item.item_type == "anchor":
        boost += 0.003
    if anchor_matched:
        boost += 0.003
    if strong_source_count:
        boost += 0.002
    return (
        round(min(_CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST, boost), 4),
        "canonical_anchor_summary_profile",
    )


def citation_evidence_support_signal(
    *,
    item: ContextItem,
    coverage: RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str]:
    if "citation" not in coverage.requested_evidence_features:
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and coverage.ratio <= 0
        and not anchor_matched
        and strong_source_count <= 0
    ):
        return 0.0, ""
    quote_count = sum(1 for ref in item.source_refs if (ref.quote_preview or "").strip())
    localized_count = sum(1 for ref in item.source_refs if _source_ref_has_precise_location(ref))
    if quote_count <= 0 and localized_count <= 0:
        return 0.0, ""
    boost = 0.01
    boost += min(0.008, quote_count * 0.004)
    boost += min(0.006, localized_count * 0.003)
    reason = "citation_quote_evidence" if quote_count > 0 else "citation_localized_evidence"
    return round(min(_CITATION_EVIDENCE_RERANK_MAX_BOOST, boost), 4), reason


def artifact_inventory_evidence_support_signal(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
    query_reason: str,
    relevance: QueryRelevance,
    coverage_ratio: float,
    anchor_matched: bool,
) -> tuple[float, float, str, dict[str, float]]:
    has_artifact_inventory_query = any(
        expansion.reason == "artifact_inventory_bridge"
        for expansion in plan.retrieval_queries
    )
    if not has_artifact_inventory_query and not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="artifact_inventory_bridge",
    ):
        return 0.0, 0.0, "", {}
    if not (
        is_query_relevance_sufficient(relevance)
        or coverage_ratio > 0
        or anchor_matched
    ):
        return 0.0, 0.0, "", {}

    sources = set(diagnostic_retrieval_sources(item.diagnostics))
    source_ref_types = {ref.source_type for ref in item.source_refs}
    has_document_evidence_ref = any(
        ref.source_type == "document"
        and (_source_ref_has_precise_location(ref) or (ref.quote_preview or "").strip())
        for ref in item.source_refs
    )
    has_first_party_artifact = (
        item.item_type == "extraction_artifact"
        or bool(sources.intersection(_ARTIFACT_INVENTORY_RERANK_SOURCES))
        or bool(source_ref_types.intersection(_ARTIFACT_INVENTORY_SOURCE_REF_TYPES))
        or has_document_evidence_ref
    )
    if not has_first_party_artifact:
        return (
            0.0,
            0.018,
            "artifact_inventory_unbacked_reference",
            {
                "artifact_inventory_first_party_evidence": 0.0,
                "artifact_inventory_unbacked_reference": 1.0,
            },
        )

    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    evidence_signal_count = 1
    if _safe_evidence_kind_or_modality(diagnostics):
        evidence_signal_count += 1
    if any(_source_ref_has_precise_location(ref) for ref in item.source_refs):
        evidence_signal_count += 1
    if any((ref.quote_preview or "").strip() for ref in item.source_refs):
        evidence_signal_count += 1
    if len(sources) >= 2:
        evidence_signal_count += 1

    boost = 0.016 + min(0.012, 0.003 * evidence_signal_count)
    if "artifact_evidence" in sources:
        boost += 0.003

    return (
        round(min(_ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST, boost), 4),
        0.0,
        "artifact_inventory_first_party_evidence",
        {
            "artifact_inventory_first_party_evidence": 1.0,
            "artifact_inventory_evidence_signal_count": float(evidence_signal_count),
        },
    )


def _query_reason_priority_for_relevance(
    reason: str,
    relevance: QueryRelevance,
) -> int:
    min_hits = QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0)
    if relevance.distinctive_term_hits < min_hits:
        return 0
    return QUERY_REASON_PRIORITY.get(reason, 0)


def _is_canonical_anchor_source(*, item: ContextItem, sources: tuple[str, ...]) -> bool:
    if item.item_type == "anchor":
        return True
    return bool(
        set(sources).intersection(
            {
                "approved_context_linked_anchors",
                "canonical_anchor_relations",
                "canonical_anchors",
            }
        )
    )


def _has_canonical_anchor_profile_evidence(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    profile = safe_diagnostic_mapping(
        diagnostics.get("anchor_identity_profile")
        or provenance.get("anchor_identity_profile")
    )
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    identity_term_count = max(
        _coverage_int(profile.get("identity_term_count")),
        _coverage_int(score_signals.get("anchor_identity_term_count")),
    )
    alias_identity_term_count = max(
        _coverage_int(profile.get("alias_identity_term_count")),
        _coverage_int(score_signals.get("anchor_alias_identity_term_count")),
    )
    source_ref_count = max(
        len(item.source_refs),
        _coverage_int(provenance.get("source_ref_count")),
    )
    text = item.text.casefold()
    has_rendered_profile_text = any(
        marker in text for marker in ("aliases:", "description:", "identity:")
    )
    return (
        has_rendered_profile_text
        or identity_term_count > 0
        or alias_identity_term_count > 0
        or source_ref_count > 0
    )


def _source_ref_has_precise_location(ref: SourceRef) -> bool:
    return bool(_source_ref_location_features(ref))


def _source_ref_location_features(ref: SourceRef) -> tuple[str, ...]:
    features: list[str] = []
    if ref.page_number is not None:
        features.append("page")
    if ref.char_start is not None or ref.char_end is not None:
        features.append("char")
    if ref.time_start_ms is not None or ref.time_end_ms is not None:
        features.append("time")
    if ref.bbox is not None:
        features.append("bbox")
    return tuple(features)


def _safe_evidence_kind_or_modality(diagnostics: Mapping[str, object]) -> bool:
    for key in ("evidence_kind", "evidence_modality", "artifact_type"):
        value = diagnostics.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    if query_reason == target_reason:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return str(signals.get("query_expansion_reason") or "") == target_reason


def _coverage_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0
