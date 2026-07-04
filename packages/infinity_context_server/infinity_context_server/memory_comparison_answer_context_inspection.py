"""Compact inspection flags for answer-context diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_low_answerability,
    is_measured_weak_source_locality,
)

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_answer_context import AnswerContext


def answer_context_inspection_flags(
    context: AnswerContext,
    *,
    source_ref_stats: Mapping[str, object],
    backfill_risk_stats: Mapping[str, object],
    quality_score_stats: Mapping[str, object],
) -> tuple[str, ...]:
    flags: list[str] = []
    if context.fallback_reason:
        flags.append("retrieval_slice_fallback")
    source_ref_item_count = _nonnegative_int(source_ref_stats.get("source_ref_item_count"))
    source_refless_item_count = _nonnegative_int(
        source_ref_stats.get("source_refless_item_count")
    )
    if context.memories and source_ref_item_count <= 0:
        flags.append("missing_context_source_refs")
    elif source_refless_item_count > 0:
        flags.append("partial_context_source_refs")
    if context.role_requirement_complete is False or context.missing_required_roles:
        flags.append("missing_required_roles")
    if _has_low_bundle_confidence(context):
        flags.append("low_bundle_confidence")
    if _has_weak_bundle_source_support(context):
        flags.append("weak_bundle_source_support")
    if _positive_int(backfill_risk_stats.get("backfilled_low_answerability_count")):
        flags.append("low_answerability_backfill")
    if _positive_int(
        backfill_risk_stats.get("backfilled_weak_source_locality_count")
    ):
        flags.append("weak_source_locality_backfill")
    if is_measured_low_answerability(
        quality_score_stats.get("avg_measured_answerability_score")
    ):
        flags.append("low_context_answerability")
    if is_measured_weak_source_locality(
        quality_score_stats.get("avg_measured_source_locality_score")
    ):
        flags.append("weak_context_source_locality")
    return tuple(dict.fromkeys(flags))


def _has_low_bundle_confidence(context: AnswerContext) -> bool:
    confidence_band = context.bundle_confidence_band.strip().lower()
    return confidence_band == "low" or 0 < context.bundle_confidence_score < 0.55


def _has_weak_bundle_source_support(context: AnswerContext) -> bool:
    if context.source != "evidence_bundle" or not _has_bundle_quality_signal(context):
        return False
    return (
        context.bundle_source_ref_support_item_count <= 0
        and context.bundle_source_identity_support_item_count <= 0
    )


def _has_bundle_quality_signal(context: AnswerContext) -> bool:
    return any(
        (
            context.bundle_confidence_score > 0,
            bool(context.bundle_confidence_band.strip()),
            context.bundle_bridge_count > 0,
            context.bundle_source_type_diversity > 0,
            context.bundle_retrieval_source_diversity > 0,
            context.bundle_source_type_support_diversity > 0,
            context.bundle_retrieval_source_support_diversity > 0,
        )
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
