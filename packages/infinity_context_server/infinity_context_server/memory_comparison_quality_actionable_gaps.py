"""Actionable gap ranking for memory-comparison fast-gate diagnostics."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    count_mapping as _count_mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import ratio as _ratio
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)

_MAX_RANKED_GAPS = 10
_MAX_SAMPLE_CASE_IDS = 5
_MAX_QUERY_PLAN_ACTIONABLE_SAMPLES = 3
_MAX_QUERY_PLAN_ACTIONABLE_SAMPLE_VALUES = 5
_MAX_QUERY_PLAN_ACTIONABLE_SAMPLE_TEXT = 128
_MAX_SELECTED_EVIDENCE_ACTIONABLE_SAMPLES = 3
_MAX_SELECTED_EVIDENCE_ACTIONABLE_SAMPLE_VALUES = 5
_MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLES = 3
_MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLE_VALUES = 5
_MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLES = 3
_MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLE_VALUES = 5
_MAX_EVIDENCE_RECALL_ACTIONABLE_SAMPLES = 3
_MAX_EVIDENCE_RECALL_ACTIONABLE_SAMPLE_VALUES = 5
_MAX_TEMPORAL_GROUNDING_ACTIONABLE_SAMPLES = 3
_MAX_TEMPORAL_GROUNDING_ACTIONABLE_SAMPLE_VALUES = 5
_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+:\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session_\d+):"
    r"(?P<session_turn_ref>D\d+:\d+))$",
    re.IGNORECASE,
)


def actionable_gap_summary(
    *,
    evaluation_count: int,
    expected_case_count: int,
    failed_gates: Sequence[str],
    query_overlap_count: int,
    profile_overlap_count: int,
    intent_overlap_count: int,
    ref_gate: Mapping[str, object] | None = None,
    bundle_quality_failure_breakdown: Mapping[str, object] | None = None,
    bundle_gap_breakdown: Mapping[str, object] | None = None,
    answerability_gap_breakdown: Mapping[str, object] | None = None,
    selected_evidence_weakness: Mapping[str, object] | None = None,
    evidence_recall_gap_summary: Mapping[str, object] | None = None,
    query_role_gap_breakdown: Mapping[str, object] | None = None,
    query_plan_gap_breakdown: Mapping[str, object] | None = None,
    rerank_signal_gap_breakdown: Mapping[str, object] | None = None,
    temporal_grounding: Mapping[str, object] | None = None,
    source_ref_provenance: Mapping[str, object] | None = None,
    answer_context_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    failed_gate_set = set(failed_gates)
    ref_gate = _mapping(ref_gate)
    bundle_quality_failure_breakdown = _mapping(bundle_quality_failure_breakdown)
    bundle_gap_breakdown = _mapping(bundle_gap_breakdown)
    answerability_gap_breakdown = _mapping(answerability_gap_breakdown)
    selected_evidence_weakness = _mapping(selected_evidence_weakness)
    evidence_recall_gap_summary = _mapping(evidence_recall_gap_summary)
    query_role_gap_breakdown = _mapping(query_role_gap_breakdown)
    query_plan_gap_breakdown = _mapping(query_plan_gap_breakdown)
    rerank_signal_gap_breakdown = _mapping(rerank_signal_gap_breakdown)
    temporal_grounding = _mapping(temporal_grounding)
    source_ref_provenance = _mapping(source_ref_provenance)
    answer_context_provenance = _mapping(answer_context_provenance)
    gaps: list[dict[str, object]] = []
    _append_bundle_quality_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        breakdown=bundle_quality_failure_breakdown,
    )
    _append_counted_gap_map(
        gaps,
        evaluation_count=evaluation_count,
        category="bundle_gap",
        source_metric="bundle_gap_breakdown.reason_counts",
        counts=_count_mapping(bundle_gap_breakdown.get("reason_counts")),
        failed_gate=(
            "evidence_bundle_complete"
            if "evidence_bundle_complete" in failed_gate_set
            else ""
        ),
        action="Improve bundle planning so required evidence roles are selected.",
        samples=_sequence(bundle_gap_breakdown.get("samples")),
    )
    _append_selected_evidence_weakness_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        breakdown=selected_evidence_weakness,
    )
    _append_evidence_recall_gaps(
        gaps,
        evaluation_count=evaluation_count,
        summary=evidence_recall_gap_summary,
    )
    _append_answerability_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        breakdown=answerability_gap_breakdown,
    )
    _append_query_plan_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        breakdown=query_plan_gap_breakdown,
    )
    _append_query_leakage_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        query_overlap_count=query_overlap_count,
        profile_overlap_count=profile_overlap_count,
        intent_overlap_count=intent_overlap_count,
    )
    _append_query_role_gaps(
        gaps,
        evaluation_count=evaluation_count,
        breakdown=query_role_gap_breakdown,
    )
    _append_temporal_grounding_gaps(
        gaps,
        evaluation_count=evaluation_count,
        temporal_grounding=temporal_grounding,
    )
    _append_rerank_signal_gaps(
        gaps,
        evaluation_count=evaluation_count,
        breakdown=rerank_signal_gap_breakdown,
    )
    _append_observed_ref_rank_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate_set=failed_gate_set,
        ref_gate=ref_gate,
    )
    _append_source_ref_gap(
        gaps,
        evaluation_count=evaluation_count,
        source_ref_provenance=source_ref_provenance,
    )
    _append_answer_context_provenance_gap(
        gaps,
        evaluation_count=evaluation_count,
        answer_context_provenance=answer_context_provenance,
    )
    ranked = _rank_actionable_gaps(gaps)
    return {
        "schema_version": "actionable_gap_summary.v1",
        "evaluation_count": evaluation_count,
        "expected_case_count": expected_case_count,
        "gap_count": len(ranked),
        "blocking_gap_count": sum(1 for gap in ranked if gap["severity"] == "blocking"),
        "diagnostic_gap_count": sum(
            1 for gap in ranked if gap["severity"] == "diagnostic"
        ),
        "rank_basis": "observed_impact_desc_blocking_tie_break",
        "top_gap": ranked[0] if ranked else None,
        "ranked_gaps": ranked[:_MAX_RANKED_GAPS],
    }


def _append_bundle_quality_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    breakdown: Mapping[str, object],
) -> None:
    weak_count = _positive_int(breakdown.get("weak_bundle_count")) or 0
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="bundle_quality",
        gap="weak_bundle_quality",
        impact_count=weak_count,
        failed_gate=(
            "bundle_quality_medium_or_high"
            if "bundle_quality_medium_or_high" in failed_gate_set
            else ""
        ),
        source_metric="bundle_quality_failure_breakdown.weak_bundle_count",
        action="Raise weak bundles to medium or high quality before expanding evaluation.",
        evidence={
            "risk_reason_counts": _count_mapping(breakdown.get("risk_reason_counts")),
            "top_reason_counts": _count_mapping(breakdown.get("top_reason_counts")),
        },
        samples=_sequence(breakdown.get("weak_samples")),
    )
    _append_counted_gap_map(
        gaps,
        evaluation_count=evaluation_count,
        category="bundle_quality_risk",
        source_metric="bundle_quality_failure_breakdown.risk_reason_counts",
        counts=_count_mapping(breakdown.get("risk_reason_counts")),
        failed_gate=(
            "bundle_quality_medium_or_high"
            if "bundle_quality_medium_or_high" in failed_gate_set
            else ""
        ),
        action="Reduce bundle quality risk reasons in selected evidence.",
        samples=_sequence(breakdown.get("weak_samples")),
    )


def _append_answerability_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    breakdown: Mapping[str, object],
) -> None:
    lifted_counts = _count_mapping(breakdown.get("lifted_reason_counts"))
    _append_counted_gap_map(
        gaps,
        evaluation_count=evaluation_count,
        category="lifted_answerability_gap",
        source_metric="answerability_gap_breakdown.lifted_reason_counts",
        counts=lifted_counts,
        failed_gate=(
            "lifted_answerability_gaps_clear"
            if "lifted_answerability_gaps_clear" in failed_gate_set
            else ""
        ),
        action="Stop lifting candidates that still lack required answerability evidence.",
        samples=_sequence(breakdown.get("samples")),
    )
    residual_counts = {
        reason: count
        for reason, count in _count_mapping(breakdown.get("reason_counts")).items()
        if reason not in lifted_counts
    }
    _append_counted_gap_map(
        gaps,
        evaluation_count=evaluation_count,
        category="answerability_gap",
        source_metric="answerability_gap_breakdown.reason_counts",
        counts=residual_counts,
        failed_gate="",
        action="Add retrieval or rerank signals for missing answerability evidence.",
        samples=_sequence(breakdown.get("samples")),
    )


def _append_selected_evidence_weakness_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    breakdown: Mapping[str, object],
) -> None:
    failed_gate_by_gap = {
        "selected_low_answerability": "selected_low_answerability_clear",
        "selected_weak_source_locality": "selected_weak_source_locality_clear",
        "selected_broad_summary": "selected_broad_summary_clear",
        "selected_conflict_or_stale": "selected_conflict_or_stale_clear",
    }
    for gap, count in _count_mapping(breakdown.get("reason_counts")).items():
        failed_gate = failed_gate_by_gap.get(str(gap), "")
        matched_samples = _samples_for_gap(
            _sequence(breakdown.get("samples")),
            str(gap),
        )
        compact_samples = _compact_selected_evidence_actionable_samples(
            matched_samples
        )
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="selected_evidence_weakness",
            gap=str(gap),
            impact_count=count,
            failed_gate=failed_gate if failed_gate in failed_gate_set else "",
            source_metric="selected_evidence_weakness.reason_counts",
            action=_action_for_gap(
                "selected_evidence_weakness",
                str(gap),
                default=(
                    "Tighten selected evidence filters for answerability, locality, "
                    "and provenance."
                ),
            ),
            samples=matched_samples,
            sample_payloads=compact_samples,
        )


def _append_evidence_recall_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    summary: Mapping[str, object],
) -> None:
    samples = _compact_evidence_recall_actionable_samples(
        _sequence(summary.get("samples"))
    )
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="evidence_recall",
        gap="missing_evidence_refs",
        impact_count=(
            _positive_int(summary.get("missing_evidence_ref_case_count")) or 0
        ),
        source_metric="evidence_recall_gap_summary.missing_evidence_ref_case_count",
        action=(
            "Inspect sampled missing evidence refs and add retrieval coverage "
            "for the absent source turns."
        ),
        evidence={
            "top_missing_evidence_terms": _compact_evidence_recall_count_mapping(
                summary.get("top_missing_evidence_terms")
            ),
            "measured_evidence_recall_count": (
                _positive_int(summary.get("measured_evidence_recall_count")) or 0
            ),
            "avg_evidence_term_recall": _number(
                summary.get("avg_evidence_term_recall")
            ),
        },
        samples=_evidence_recall_samples_for_missing(samples),
        sample_payloads=_evidence_recall_samples_for_missing(samples),
    )
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="evidence_recall",
        gap="weak_evidence_term_recall",
        impact_count=(
            _positive_int(summary.get("weak_evidence_recall_case_count")) or 0
        ),
        source_metric="evidence_recall_gap_summary.weak_evidence_recall_case_count",
        action=(
            "Improve retrieval coverage for cases with partial evidence-term "
            "recall before expanding evaluation."
        ),
        evidence={
            "zero_evidence_recall_case_count": (
                _positive_int(summary.get("zero_evidence_recall_case_count")) or 0
            ),
            "measured_evidence_recall_count": (
                _positive_int(summary.get("measured_evidence_recall_count")) or 0
            ),
            "avg_evidence_term_recall": _number(
                summary.get("avg_evidence_term_recall")
            ),
        },
        samples=_evidence_recall_samples_for_weak_recall(samples),
        sample_payloads=_evidence_recall_samples_for_weak_recall(samples),
    )


def _append_query_plan_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    breakdown: Mapping[str, object],
) -> None:
    failed_gate = (
        "query_plan_evidence_roles_clear"
        if "query_plan_evidence_roles_clear" in failed_gate_set
        else ""
    )
    _append_query_plan_missing_role_family_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate=failed_gate,
        counts=_count_mapping(
            breakdown.get("missing_evidence_role_query_family_counts")
        ),
        details=_mapping(
            breakdown.get("missing_evidence_role_query_family_details")
        ),
        samples=_query_plan_samples(breakdown),
    )
    _append_query_plan_reason_gaps(
        gaps,
        evaluation_count=evaluation_count,
        failed_gate=failed_gate,
        counts=_count_mapping(breakdown.get("gap_reason_counts")),
        samples=_query_plan_samples(breakdown),
    )


def _append_query_plan_missing_role_family_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate: str,
    counts: Mapping[str, int],
    details: Mapping[str, object],
    samples: Sequence[object],
) -> None:
    for family, count in sorted(counts.items()):
        detail = _mapping(details.get(family))
        accepted_families = _str_tuple(detail.get("accepted_query_families"))
        evidence: dict[str, object] = {
            "role_family": str(family),
            "role_family_label": str(
                detail.get("role_family_label") or _role_family_label(str(family))
            ),
        }
        if accepted_families:
            evidence["accepted_query_families"] = list(accepted_families)
        action = str(detail.get("action") or "").strip() or (
            "Add query-plan coverage for required evidence role families."
        )
        matched_samples = _query_plan_samples_for_gap(
            samples,
            str(family),
            key="missing_evidence_role_query_families",
        )
        compact_samples = _compact_query_plan_actionable_samples(
            matched_samples,
            limit=_MAX_SAMPLE_CASE_IDS,
        )
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="query_plan",
            gap=str(family),
            impact_count=count,
            failed_gate=failed_gate,
            source_metric=(
                "query_plan_gap_breakdown."
                "missing_evidence_role_query_family_counts"
            ),
            action=action,
            evidence=evidence,
            samples=compact_samples,
            sample_payloads=compact_samples,
        )


def _append_query_plan_reason_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate: str,
    counts: Mapping[str, int],
    samples: Sequence[object],
) -> None:
    for reason, count in sorted(counts.items()):
        matched_samples = _query_plan_samples_for_gap(
            samples,
            str(reason),
            key="gap_reasons",
        )
        compact_samples = _compact_query_plan_actionable_samples(
            matched_samples,
            limit=_MAX_SAMPLE_CASE_IDS,
        )
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="query_plan",
            gap=str(reason),
            impact_count=count,
            failed_gate=failed_gate,
            source_metric="query_plan_gap_breakdown.gap_reason_counts",
            action=_query_plan_reason_action(str(reason)),
            samples=compact_samples,
            sample_payloads=compact_samples,
        )


def _append_query_role_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    breakdown: Mapping[str, object],
) -> None:
    for family, payload in _mapping(breakdown.get("role_family_gaps")).items():
        role_gap = _mapping(payload)
        selected_evidence_count = (
            _positive_int(
                role_gap.get("selected_evidence_query_role_family_count")
            )
            or 0
        )
        selected_count = max(
            _positive_int(role_gap.get("selected_item_count")) or 0,
            selected_evidence_count,
        )
        candidate_count = _positive_int(role_gap.get("candidate_count")) or 0
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="query_role_family",
            gap=str(family),
            impact_count=max(0, candidate_count - selected_count),
            source_metric="query_role_gap_breakdown.role_family_gaps",
            action=(
                "Select evidence for query role families that have candidates "
                "but no bundle coverage."
            ),
            evidence={"gap_reasons": list(_str_tuple(role_gap.get("gap_reasons")))},
        )


def _append_temporal_grounding_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    temporal_grounding: Mapping[str, object],
) -> None:
    reason_counts = _count_mapping(
        temporal_grounding.get("selected_temporal_grounding_issue_reason_counts")
    )
    if not reason_counts:
        return
    samples = _sequence(
        temporal_grounding.get("selected_temporal_grounding_issue_samples")
    )
    for reason, count in sorted(reason_counts.items()):
        matched_samples = _samples_for_gap(samples, str(reason))
        compact_samples = _compact_temporal_grounding_actionable_samples(
            matched_samples
        )
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="temporal_grounding",
            gap=str(reason),
            impact_count=count,
            source_metric=(
                "temporal_grounding_table."
                "selected_temporal_grounding_issue_reason_counts"
            ),
            action=_temporal_grounding_action(str(reason)),
            evidence={
                "temporal_case_count": (
                    _positive_int(temporal_grounding.get("temporal_case_count")) or 0
                ),
                "selected_temporal_grounding_issue_item_count": (
                    _positive_int(
                        temporal_grounding.get(
                            "selected_temporal_grounding_issue_item_count"
                        )
                    )
                    or 0
                ),
                "selected_strong_temporal_grounding_item_count": (
                    _positive_int(
                        temporal_grounding.get(
                            "selected_strong_temporal_grounding_item_count"
                        )
                    )
                    or 0
                ),
            },
            samples=matched_samples,
            sample_payloads=compact_samples,
        )


def _append_query_leakage_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    query_overlap_count: int,
    profile_overlap_count: int,
    intent_overlap_count: int,
) -> None:
    failed_gate = (
        "query_profile_leakage_zero"
        if "query_profile_leakage_zero" in failed_gate_set
        else ""
    )
    for gap, count in (
        ("expected_answer_query_overlap", query_overlap_count),
        ("expected_answer_query_profile_overlap", profile_overlap_count),
        ("expected_answer_retrieval_intent_overlap", intent_overlap_count),
    ):
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="query_leakage",
            gap=gap,
            impact_count=count,
            failed_gate=failed_gate,
            source_metric=f"query_integrity.{gap}_count",
            action=(
                "Remove expected-answer terms from query text, query profile, "
                "and retrieval intent."
            ),
        )


def _append_rerank_signal_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    breakdown: Mapping[str, object],
) -> None:
    conflict_samples = _compact_rerank_signal_actionable_samples(
        _sequence(breakdown.get("selection_conflict_samples"))
    )
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="rerank_signal_selection",
        gap="selection_conflict",
        impact_count=(
            _positive_int(breakdown.get("selection_conflict_case_count")) or 0
        ),
        source_metric="rerank_signal_gap_breakdown.selection_conflict_case_count",
        action=(
            "Inspect cases where positively reranked candidates were not selected "
            "while selected evidence lacked positive rerank support."
        ),
        evidence={
            "selection_conflict_pair_count": (
                _positive_int(breakdown.get("selection_conflict_pair_count")) or 0
            ),
            "positive_unselected_signal_counts": _compact_rerank_signal_mapping(
                _count_mapping(
                    breakdown.get("selection_conflict_positive_signal_counts")
                )
            ),
            "selected_without_positive_reason_counts": _compact_rerank_signal_mapping(
                _count_mapping(breakdown.get("selected_without_positive_reason_counts"))
            ),
        },
        samples=conflict_samples,
        sample_payloads=conflict_samples,
    )


def _append_observed_ref_rank_gaps(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    failed_gate_set: set[str],
    ref_gate: Mapping[str, object],
) -> None:
    ref_eval_count = _positive_int(ref_gate.get("evaluation_count")) or 0
    if not ref_eval_count:
        return
    for metric, failed_gate, action in (
        (
            "all_refs_top5_count",
            "all_refs_top5",
            "Move all required evidence refs into the observed top five.",
        ),
        (
            "focused_refs_top5_count",
            "focused_refs_top5",
            "Move focused required evidence refs into the observed top five.",
        ),
        (
            "all_refs_top3_count",
            "all_refs_top3",
            "Move all required evidence refs into the observed top three.",
        ),
    ):
        passing_count = _positive_int(ref_gate.get(metric)) or 0
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category="evidence_ref_rank",
            gap=metric.removesuffix("_count"),
            impact_count=max(0, ref_eval_count - passing_count),
            failed_gate=failed_gate if failed_gate in failed_gate_set else "",
            source_metric=f"evidence_ref_rank_gate.{metric}",
            action=action,
            evidence={"evidence_ref_evaluation_count": ref_eval_count},
            samples=_sequence(ref_gate.get("samples")),
        )


def _append_source_ref_gap(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    source_ref_provenance: Mapping[str, object],
) -> None:
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="source_ref_provenance",
        gap="selected_bundle_missing_source_refs",
        impact_count=(
            _positive_int(
                source_ref_provenance.get("selected_bundle_source_refless_item_count")
            )
            or 0
        ),
        source_metric=(
            "source_ref_provenance.selected_bundle_source_refless_item_count"
        ),
        action="Keep source refs on selected bundle items so evidence remains auditable.",
        samples=_sequence(source_ref_provenance.get("source_refless_selected_samples")),
    )


def _append_answer_context_provenance_gap(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    answer_context_provenance: Mapping[str, object],
) -> None:
    source_refless_item_count = (
        _positive_int(answer_context_provenance.get("source_refless_item_count"))
        or 0
    )
    source_refless_samples = _compact_answer_context_actionable_samples(
        _sequence(answer_context_provenance.get("source_refless_context_samples"))
    )
    _append_actionable_gap(
        gaps,
        evaluation_count=evaluation_count,
        category="answer_context_provenance",
        gap="answer_context_missing_source_refs",
        impact_count=source_refless_item_count,
        source_metric="answer_context_provenance.source_refless_item_count",
        action=(
            "Keep source refs when selected evidence is rendered into answer "
            "context so prompt evidence remains auditable."
        ),
        evidence={
            "source_refless_context_count": (
                _positive_int(
                    answer_context_provenance.get("source_refless_context_count")
                )
                or 0
            ),
            "source_ref_item_coverage_rate": _number(
                answer_context_provenance.get("source_ref_item_coverage_rate")
            ),
            "source_counts": _count_mapping(
                answer_context_provenance.get("source_counts")
            ),
        },
        samples=source_refless_samples,
        sample_payloads=source_refless_samples,
    )


def _append_counted_gap_map(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    category: str,
    source_metric: str,
    counts: Mapping[str, int],
    failed_gate: str,
    action: str,
    samples: Sequence[object] = (),
) -> None:
    for gap, count in sorted(counts.items()):
        _append_actionable_gap(
            gaps,
            evaluation_count=evaluation_count,
            category=category,
            gap=str(gap),
            impact_count=count,
            failed_gate=failed_gate,
            source_metric=source_metric,
            action=_action_for_gap(category, str(gap), default=action),
            samples=_samples_for_gap(samples, str(gap)),
        )


def _append_actionable_gap(
    gaps: list[dict[str, object]],
    *,
    evaluation_count: int,
    category: str,
    gap: str,
    impact_count: int,
    source_metric: str,
    action: str,
    failed_gate: str = "",
    evidence: Mapping[str, object] | None = None,
    samples: Sequence[object] = (),
    sample_payloads: Sequence[Mapping[str, object]] = (),
) -> None:
    if impact_count <= 0:
        return
    payload: dict[str, object] = {
        "category": category,
        "gap": gap,
        "impact_count": impact_count,
        "impact_rate": _ratio(impact_count, evaluation_count),
        "severity": "blocking" if failed_gate else "diagnostic",
        "failed_gate": failed_gate,
        "source_metric": source_metric,
        "action": action,
        "sample_case_ids": _sample_case_ids(samples),
        "evidence": dict(evidence or {}),
    }
    compact_samples = [
        dict(sample)
        for sample in sample_payloads
        if isinstance(sample, Mapping)
    ][:3]
    if compact_samples:
        payload["samples"] = compact_samples
    gaps.append(payload)


def _rank_actionable_gaps(
    gaps: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ranked = [
        dict(gap)
        for gap in sorted(
            gaps,
            key=lambda gap: (
                -(_positive_int(gap.get("impact_count")) or 0),
                0 if gap.get("severity") == "blocking" else 1,
                str(gap.get("category") or ""),
                str(gap.get("gap") or ""),
                str(gap.get("source_metric") or ""),
            ),
        )
    ]
    for index, gap in enumerate(ranked, start=1):
        gap["rank"] = index
    return ranked


def _samples_for_gap(
    samples: Sequence[object],
    gap: str,
) -> tuple[Mapping[str, object], ...]:
    matched = [
        sample
        for sample in samples
        if isinstance(sample, Mapping)
        and (
            gap in _str_tuple(sample.get("reasons"))
            or gap in _str_tuple(sample.get("reason_codes"))
            or gap in _str_tuple(sample.get("gap_reasons"))
            or gap in _str_tuple(sample.get("issue_reasons"))
        )
    ]
    if matched:
        return tuple(matched)
    return tuple(sample for sample in samples if isinstance(sample, Mapping))


def _sample_case_ids(samples: Sequence[object]) -> list[str]:
    case_ids: list[str] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        case_id = _compact_query_plan_sample_text(sample.get("case_id"))
        if case_id and case_id not in case_ids:
            case_ids.append(case_id)
        if len(case_ids) >= _MAX_SAMPLE_CASE_IDS:
            break
    return case_ids


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _action_for_gap(category: str, gap: str, *, default: str) -> str:
    if gap.startswith("missing_required_"):
        role = gap.removeprefix("missing_required_")
        return f"Ensure required bundle role '{role}' is planned and selected."
    if gap.startswith("missing_"):
        need = gap.removeprefix("missing_")
        return f"Add retrieval and bundle coverage for '{need}'."
    if category == "selected_evidence_weakness":
        return (
            "Reject or demote selected evidence with weak answerability, locality, "
            "or provenance."
        )
    if category == "bundle_quality_risk":
        return f"Reduce bundle quality risk '{gap}' in selected evidence."
    return default


def _query_plan_samples(
    breakdown: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    raw_samples = tuple(
        sample
        for sample in _sequence(breakdown.get("samples"))
        if isinstance(sample, Mapping)
    )
    if raw_samples:
        return raw_samples
    compact_samples = tuple(
        sample
        for sample in _sequence(breakdown.get("compact_samples"))
        if isinstance(sample, Mapping)
    )
    return compact_samples


def _query_plan_samples_for_gap(
    samples: Sequence[object],
    gap: str,
    *,
    key: str,
) -> tuple[Mapping[str, object], ...]:
    matched = [
        sample
        for sample in samples
        if isinstance(sample, Mapping) and gap in _str_tuple(sample.get(key))
    ]
    if matched:
        return tuple(matched)
    return tuple(sample for sample in samples if isinstance(sample, Mapping))


def _compact_query_plan_actionable_samples(
    samples: Sequence[Mapping[str, object]],
    *,
    limit: int = _MAX_QUERY_PLAN_ACTIONABLE_SAMPLES,
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for sample in samples:
        compact: dict[str, object] = {}
        for key in ("case_id", "group"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in (
            "gap_reasons",
            "missing_evidence_role_query_families",
            "missing_recommended_role_families",
            "selected_role_families",
            "required_evidence_roles",
            "dropped_roles",
            "dropped_type_limit_roles",
            "replaced_type_limit_roles",
            "type_limit_replacement_roles",
        ):
            values = tuple(
                value
                for value in (
                    _compact_query_plan_sample_text(raw_value)
                    for raw_value in _str_tuple(sample.get(key))
                )
                if value
            )
            if values:
                compact[key] = list(values[:_MAX_QUERY_PLAN_ACTIONABLE_SAMPLE_VALUES])
        for key in (
            "selected_query_count",
            "dropped_query_count",
            "empty_query_candidate_count",
        ):
            value = _positive_int(sample.get(key)) or 0
            if value:
                compact[key] = value
        for key in ("fanout_limit_hit", "type_limit_hit"):
            if sample.get(key) is True:
                compact[key] = True
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= limit:
            break
    return tuple(compact_samples)


def _compact_selected_evidence_actionable_samples(
    samples: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for sample in samples:
        compact: dict[str, object] = {}
        for key in ("case_id", "group", "item_id", "role"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in (
            "reasons",
            "risk_reason_codes",
            "planner_reason_codes",
            "query_roles",
            "source_refs",
            "answerability_reason_codes",
            "source_locality_reason_codes",
            "retrieval_sources",
            "source_types",
        ):
            values = tuple(
                value
                for value in (
                    _compact_query_plan_sample_text(raw_value)
                    for raw_value in _str_tuple(sample.get(key))
                )
                if value
            )
            if values:
                compact[key] = list(
                    values[:_MAX_SELECTED_EVIDENCE_ACTIONABLE_SAMPLE_VALUES]
                )
        for key in ("retrieval_order", "source_ref_count"):
            value = _positive_int(sample.get(key)) or 0
            if value:
                compact[key] = value
        for key in ("answerability_score", "source_locality_score"):
            value = sample.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                compact[key] = round(float(value), 6)
        for key in ("broad_summary", "conflict_or_stale"):
            if sample.get(key) is True:
                compact[key] = True
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_SELECTED_EVIDENCE_ACTIONABLE_SAMPLES:
            break
    return tuple(compact_samples)


def _compact_answer_context_actionable_samples(
    samples: Sequence[object],
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for raw_sample in samples:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in ("case_id", "cutoff", "source", "fallback_reason"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in (
            "item_ids",
            "missing_required_roles",
            "risk_reason_codes",
        ):
            values = tuple(
                value
                for value in (
                    _compact_query_plan_sample_text(raw_value)
                    for raw_value in _str_tuple(sample.get(key))
                )
                if value
            )
            if values:
                compact[key] = list(
                    values[:_MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLE_VALUES]
                )
        source_identity_refs = _compact_answer_context_source_identity_refs(
            sample.get("source_identity_refs")
        )
        if source_identity_refs:
            compact["source_identity_refs"] = list(source_identity_refs)
        retrieval_orders = tuple(
            order
            for raw_order in _sequence(sample.get("retrieval_orders"))
            for order in (_positive_int(raw_order),)
            if order is not None
        )
        if retrieval_orders:
            compact["retrieval_orders"] = list(
                retrieval_orders[:_MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLE_VALUES]
            )
        for key in (
            "memory_count",
            "source_ref_count",
            "source_ref_item_count",
            "source_refless_item_count",
            "source_identity_ref_count",
            "source_identity_item_count",
        ):
            value = _positive_int(sample.get(key)) or 0
            if value:
                compact[key] = value
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLES:
            break
    return tuple(compact_samples)


def _compact_answer_context_source_identity_refs(value: object) -> tuple[str, ...]:
    refs = tuple(
        dict.fromkeys(
            ref
            for raw_ref in _str_tuple(value)
            for ref in (_safe_answer_context_source_identity_ref(raw_ref),)
            if ref
        )
    )
    return refs[:_MAX_ANSWER_CONTEXT_ACTIONABLE_SAMPLE_VALUES]


def _safe_answer_context_source_identity_ref(value: object) -> str | None:
    ref = str(value or "").strip()
    if not ref or len(ref) > 80:
        return None
    match = _SAFE_SOURCE_IDENTITY_REF_RE.fullmatch(ref)
    if match is None:
        return None
    if match.group("turn_ref"):
        return f"source_turn_refs:{match.group('turn_ref').upper()}"
    return (
        "source_session_turn_refs:"
        f"{match.group('session').lower()}:{match.group('session_turn_ref').upper()}"
    )


def _compact_evidence_recall_actionable_samples(
    samples: Sequence[object],
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for raw_sample in samples:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in ("case_id", "group"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in ("expected_term_recall", "evidence_term_recall"):
            value = sample.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                compact[key] = round(float(value), 6)
        if sample.get("evidence_term_recall_measured") is not None:
            compact["evidence_term_recall_measured"] = (
                sample.get("evidence_term_recall_measured") is True
            )
        missing_terms = tuple(
            value
            for value in (
                _compact_query_plan_sample_text(raw_value)
                for raw_value in _str_tuple(sample.get("missing_evidence_terms"))
            )
            if value
        )
        if missing_terms:
            compact["missing_evidence_terms"] = list(
                missing_terms[:_MAX_EVIDENCE_RECALL_ACTIONABLE_SAMPLE_VALUES]
            )
        missing_count = _positive_int(sample.get("missing_evidence_term_count")) or 0
        if missing_count:
            compact["missing_evidence_term_count"] = missing_count
        if "bundle_complete" in sample:
            compact["bundle_complete"] = sample.get("bundle_complete") is True
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_EVIDENCE_RECALL_ACTIONABLE_SAMPLES:
            break
    return tuple(compact_samples)


def _compact_evidence_recall_count_mapping(value: object) -> dict[str, int]:
    compact: dict[str, int] = {}
    for key, raw_count in _mapping(value).items():
        compact_key = _compact_query_plan_sample_text(key)
        if not compact_key:
            continue
        count = _positive_int(raw_count) or 0
        compact[compact_key] = count
        if len(compact) >= _MAX_EVIDENCE_RECALL_ACTIONABLE_SAMPLE_VALUES:
            break
    return compact


def _compact_temporal_grounding_actionable_samples(
    samples: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for sample in samples:
        compact: dict[str, object] = {}
        for key in ("case_id", "group", "item_id", "role"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in (
            "query_roles",
            "issue_reasons",
            "source_identity_gap_codes",
        ):
            values = tuple(
                value
                for value in (
                    _compact_query_plan_sample_text(raw_value)
                    for raw_value in _str_tuple(sample.get(key))
                )
                if value
            )
            if values:
                compact[key] = list(
                    values[:_MAX_TEMPORAL_GROUNDING_ACTIONABLE_SAMPLE_VALUES]
                )
        source_refs = _compact_temporal_grounding_source_refs(sample.get("source_refs"))
        if source_refs:
            compact["source_refs"] = list(source_refs)
        source_ref_count = _positive_int(sample.get("source_ref_count")) or 0
        if source_ref_count:
            compact["source_ref_count"] = source_ref_count
        signals = _mapping(sample.get("grounding_signals"))
        signal_values = {
            key: bool(signals.get(key))
            for key in (
                "source_window",
                "session_boundary",
                "date_or_range",
                "relative_date",
                "temporal_order",
            )
            if key in signals
        }
        if signal_values:
            compact["grounding_signals"] = signal_values
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_TEMPORAL_GROUNDING_ACTIONABLE_SAMPLES:
            break
    return tuple(compact_samples)


def _compact_temporal_grounding_source_refs(value: object) -> tuple[str, ...]:
    refs: list[str] = []
    for raw_ref in _str_tuple(value):
        for ref in (
            _safe_answer_context_source_identity_ref(raw_ref),
            _safe_turn_ref(raw_ref),
        ):
            if ref and ref not in refs:
                refs.append(ref)
            if len(refs) >= _MAX_TEMPORAL_GROUNDING_ACTIONABLE_SAMPLE_VALUES:
                return tuple(refs)
    return tuple(refs)


def _safe_turn_ref(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    day, separator, turn = text.partition(":")
    if (
        separator
        and len(day) > 1
        and day.startswith("D")
        and day[1:].isdigit()
        and turn.isdigit()
    ):
        return text
    return ""


def _evidence_recall_samples_for_missing(
    samples: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    matched = [
        sample
        for sample in samples
        if (_positive_int(sample.get("missing_evidence_term_count")) or 0) > 0
    ]
    return tuple(matched or samples)


def _evidence_recall_samples_for_weak_recall(
    samples: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    matched = []
    for sample in samples:
        if sample.get("evidence_term_recall_measured") is not True:
            continue
        value = sample.get("evidence_term_recall")
        if isinstance(value, bool):
            continue
        try:
            if float(value) < 1.0:
                matched.append(sample)
        except (TypeError, ValueError):
            continue
    return tuple(matched or samples)


def _compact_rerank_signal_actionable_samples(
    samples: Sequence[object],
) -> tuple[dict[str, object], ...]:
    compact_samples: list[dict[str, object]] = []
    for raw_sample in samples:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in ("case_id", "group"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        for key in (
            "positive_unselected_candidate_count",
            "selected_without_positive_rerank_count",
        ):
            value = _positive_int(sample.get(key)) or 0
            if value:
                compact[key] = value
        signal_counts = _compact_rerank_signal_mapping(
            _mapping(sample.get("positive_unselected_signal_counts"))
        )
        if signal_counts:
            compact["positive_unselected_signal_counts"] = signal_counts
        candidate_ids = _compact_rerank_signal_item_ids(
            _sequence(sample.get("positive_unselected_candidates"))
        )
        if candidate_ids:
            compact["positive_unselected_candidate_ids"] = candidate_ids
        selected_items = _compact_rerank_signal_selected_samples(
            _sequence(sample.get("selected_without_positive_items"))
        )
        if selected_items:
            compact["selected_without_positive_items"] = selected_items
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLES:
            break
    return tuple(compact_samples)


def _compact_rerank_signal_item_ids(
    samples: Sequence[object],
) -> list[str]:
    item_ids: list[str] = []
    for raw_sample in samples:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        item_id = _compact_query_plan_sample_text(sample.get("item_id"))
        if item_id:
            item_ids.append(item_id)
        if len(item_ids) >= _MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLE_VALUES:
            break
    return item_ids


def _compact_rerank_signal_selected_samples(
    samples: Sequence[object],
) -> list[dict[str, object]]:
    compact_samples: list[dict[str, object]] = []
    for raw_sample in samples:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in ("item_id", "reason", "role"):
            value = _compact_query_plan_sample_text(sample.get(key))
            if value:
                compact[key] = value
        if "matched_retrieval_candidate" in sample:
            compact["matched_retrieval_candidate"] = (
                sample.get("matched_retrieval_candidate") is True
            )
        if compact:
            compact_samples.append(compact)
        if len(compact_samples) >= _MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLE_VALUES:
            break
    return compact_samples


def _compact_rerank_signal_mapping(
    values: Mapping[str, object],
) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key, raw_value in sorted(values.items()):
        compact_key = _compact_query_plan_sample_text(key)
        if not compact_key:
            continue
        if isinstance(raw_value, bool):
            if raw_value:
                compact[compact_key] = True
        elif isinstance(raw_value, int):
            compact[compact_key] = raw_value
        elif isinstance(raw_value, float):
            compact[compact_key] = round(float(raw_value), 6)
        else:
            compact_value = _compact_query_plan_sample_text(raw_value)
            if compact_value:
                compact[compact_key] = compact_value
        if len(compact) >= _MAX_RERANK_SIGNAL_ACTIONABLE_SAMPLE_VALUES:
            break
    return compact


def _compact_query_plan_sample_text(value: object) -> str:
    text = str(value or "").strip()
    if len(text) <= _MAX_QUERY_PLAN_ACTIONABLE_SAMPLE_TEXT:
        return text
    return f"{text[: _MAX_QUERY_PLAN_ACTIONABLE_SAMPLE_TEXT - 3]}..."


def _query_plan_reason_action(reason: str) -> str:
    return {
        "missing_evidence_role_query_family": (
            "Add selected query families that satisfy required evidence role "
            "families."
        ),
        "missing_recommended_role_family": (
            "Add selected queries for recommended role families reported by "
            "the query plan."
        ),
        "dropped_queries": (
            "Preserve or replace dropped query roles before query-plan fanout "
            "removes required coverage."
        ),
        "fanout_limit_hit": (
            "Rebalance query-plan fanout so required role families survive "
            "selection."
        ),
        "type_limit_hit": (
            "Rebalance per-type query limits so semantic and lexical slots keep "
            "required role-family coverage."
        ),
        "type_limit_replacement": (
            "Verify type-limit replacements keep the required role-family "
            "coverage they replaced."
        ),
        "empty_query_candidate": (
            "Suppress empty query candidates or backfill valid query text before "
            "selection."
        ),
    }.get(reason, "Fix query-plan gaps that drop required retrieval routes.")


def _temporal_grounding_action(reason: str) -> str:
    return {
        "missing_source_window": (
            "Keep session/turn source-window refs on temporal evidence."
        ),
        "missing_session_boundary": (
            "Preserve session or turn boundaries for selected temporal evidence."
        ),
        "missing_date_or_range": (
            "Preserve explicit or relative date/range evidence on selected "
            "temporal items."
        ),
        "missing_temporal_grounding": (
            "Add temporal evidence with source windows plus explicit or relative "
            "date/range grounding."
        ),
        "weak_source_window_without_date_or_range": (
            "Pair temporal source windows with explicit or relative date/range text."
        ),
        "weak_session_boundary_without_date_or_range": (
            "Pair session-bound temporal evidence with explicit or relative "
            "date/range text."
        ),
        "weak_date_or_range_without_session_boundary": (
            "Pair date/range temporal evidence with session or turn boundaries."
        ),
        "source_identity_mismatch": (
            "Fix selected temporal evidence whose text and source identity disagree."
        ),
        "conflicting_or_stale": (
            "Avoid stale or conflicting selected evidence for temporal answers."
        ),
        "weak_broad_summary": (
            "Prefer localized temporal turns over broad summary evidence."
        ),
    }.get(reason, "Fix temporal grounding issues in selected evidence.")


def _role_family_label(family: str) -> str:
    return family.strip().replace("_", " ")
