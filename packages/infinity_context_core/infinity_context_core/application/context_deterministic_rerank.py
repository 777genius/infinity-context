"""Deterministic rerank policy; one implementation authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from infinity_context_core.application.context_deterministic_rerank_policy import (
    _deterministic_rerank_signals,
)
from infinity_context_core.application.context_diagnostics import (
    normalize_context_item_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_internal_diagnostics import (
    provenance_flag_is_true as _provenance_flag_is_true,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_requirement_signals import _coverage_int
from infinity_context_core.application.context_rerank_relevance import _non_negative_float_signal
from infinity_context_core.application.context_temporal_query import TemporalQueryIntent
from infinity_context_core.application.dto import ContextItem

_DETERMINISTIC_RERANK_MAX_BOOST = 0.055


_DETERMINISTIC_RERANK_MAX_PENALTY = 0.11


def _with_deterministic_rerank_adjustment(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
    best_query_relevance_fn: Callable[..., tuple[str, str, QueryRelevance]],
    normalize_context_diagnostics_fn: Callable[[object], dict[str, object]],
) -> ContextItem:
    normalized_item = normalize_context_item_diagnostics(item)
    if _deterministic_rerank_already_applied_in_diagnostics(normalized_item.diagnostics):
        return item
    signals = _deterministic_rerank_signals(
        normalized_item,
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        temporal_query_intent=temporal_query_intent,
        requested_total=requested_total,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
        query_relevance_cache=query_relevance_cache,
        max_boost=max_boost,
        max_penalty=max_penalty,
        best_query_relevance_fn=best_query_relevance_fn,
    )
    if signals.net_adjustment == 0 and (not signals.rank_signals):
        return item
    diagnostics = normalize_context_diagnostics_fn(normalized_item.diagnostics)
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "deterministic_rerank_boost": signals.boost,
        "deterministic_rerank_penalty": signals.penalty,
        "deterministic_rerank_net_adjustment": signals.net_adjustment,
        "deterministic_rerank_source_count": signals.source_count,
        "deterministic_rerank_strong_source_count": signals.strong_source_count,
        "deterministic_rerank_requirement_coverage": signals.coverage_ratio,
        "deterministic_rerank_query_reason": signals.query_reason,
        **{key: value for key, value in signals.rank_signals},
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(signals.reasons[:8]),
        "deterministic_rerank_anchor_conflict": signals.anchor_conflict,
    }
    reranked_score = min(0.99, max(0.0, round(normalized_item.score + signals.net_adjustment, 4)))
    reranked_score = max(reranked_score, _strong_artifact_evidence_score_floor(diagnostics))
    return replace(
        normalized_item,
        score=reranked_score,
        diagnostics=normalize_context_diagnostics_fn(diagnostics),
    )


def _strong_artifact_evidence_score_floor(diagnostics: dict[str, object]) -> float:
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    evidence_confidence = _non_negative_float_signal(score_signals.get("evidence_confidence"))
    coordinate_boost = _non_negative_float_signal(score_signals.get("coordinate_boost"))
    if (
        diagnostics.get("retrieval_source") == "artifact_evidence"
        and diagnostics.get("evidence_kind") in {"ocr_region", "transcript_segment"}
        and evidence_confidence is not None
        and evidence_confidence >= 0.9
        and coordinate_boost is not None
        and coordinate_boost > 0
        and (
            _coverage_int(score_signals.get("unique_term_hits")) >= 3
            or _coverage_int(score_signals.get("phrase_bigram_hits")) >= 1
        )
    ):
        return 0.9
    return 0.0


def _deterministic_rerank_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "deterministic_rerank_applied")


def _deterministic_rerank_already_applied_in_diagnostics(
    diagnostics: object,
) -> bool:
    return _provenance_flag_is_true(
        diagnostics,
        "deterministic_rerank_applied",
    )
