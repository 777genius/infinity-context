"""Actionable gap ranking for memory-comparison fast-gate diagnostics."""

from __future__ import annotations

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


def actionable_gap_summary(
    *,
    evaluation_count: int,
    expected_case_count: int,
    failed_gates: Sequence[str],
    query_overlap_count: int,
    profile_overlap_count: int,
    intent_overlap_count: int,
    ref_gate: Mapping[str, object],
    bundle_quality_failure_breakdown: Mapping[str, object],
    bundle_gap_breakdown: Mapping[str, object],
    answerability_gap_breakdown: Mapping[str, object],
    selected_evidence_weakness: Mapping[str, object],
    query_role_gap_breakdown: Mapping[str, object],
    query_plan_gap_breakdown: Mapping[str, object],
    source_ref_provenance: Mapping[str, object],
) -> dict[str, object]:
    failed_gate_set = set(failed_gates)
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
            samples=_samples_for_gap(_sequence(breakdown.get("samples")), str(gap)),
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
        case_id = str(sample.get("case_id") or "").strip()
        if case_id and case_id not in case_ids:
            case_ids.append(case_id)
        if len(case_ids) >= _MAX_SAMPLE_CASE_IDS:
            break
    return case_ids


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
    compact_samples = tuple(
        sample
        for sample in _sequence(breakdown.get("compact_samples"))
        if isinstance(sample, Mapping)
    )
    if compact_samples:
        return compact_samples
    return tuple(
        sample
        for sample in _sequence(breakdown.get("samples"))
        if isinstance(sample, Mapping)
    )


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


def _role_family_label(family: str) -> str:
    return family.strip().replace("_", " ")
