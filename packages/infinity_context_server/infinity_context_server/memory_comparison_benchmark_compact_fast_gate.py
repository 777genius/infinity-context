"""Fast gate compact report projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _compact_actionable_gaps,
    _compact_answer_context_support_gap_samples,
    _compact_answerability_gap_samples,
    _compact_count_mapping,
    _compact_rerank_signal_gap_samples,
    _compact_sample_values,
    _compact_selected_evidence_weakness_samples,
    _compact_temporal_grounding_issue_samples,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _mapping,
    _positive_int,
    _str_tuple,
)
from infinity_context_server.memory_comparison_compact_gap_report import (
    compact_evidence_bundle_gap_report as _compact_evidence_bundle_gap_report,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics as _fast_gate_metrics,
)


def _compact_fast_gate_summary(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    gate = _fast_gate_metrics(items)
    selected_weakness = _mapping(gate.get("selected_evidence_weakness"))
    query_role_gaps = _mapping(gate.get("query_role_gap_breakdown"))
    query_plan_gaps = _mapping(gate.get("query_plan_gap_breakdown"))
    bundle_gaps = _mapping(gate.get("bundle_gap_breakdown"))
    answerability_gaps = _mapping(gate.get("answerability_gap_breakdown"))
    rerank_signal_gaps = _mapping(gate.get("rerank_signal_gap_breakdown"))
    answer_context_gaps = _mapping(gate.get("answer_context_support_gap_summary"))
    temporal_grounding = _mapping(gate.get("temporal_grounding_table"))
    actionable = _mapping(gate.get("actionable_gap_summary"))
    top_actionable_gaps = _compact_actionable_gaps(actionable.get("ranked_gaps"))
    compact_top_gap = (
        top_actionable_gaps[:1]
        or _compact_actionable_gaps((actionable.get("top_gap"),), limit=1)
    )
    return {
        "schema_version": "compact_fast_gate_summary.v1",
        "source_schema_versions": _nested_schema_versions(gate),
        "ready_for_full_locomo": bool(gate.get("ready_for_full_locomo")),
        "failed_gates": list(_str_tuple(gate.get("failed_gates"))),
        "evaluation_count": _positive_int(gate.get("evaluation_count")) or 0,
        "expected_case_count": _positive_int(gate.get("expected_case_count")) or 0,
        "top_gap": compact_top_gap[0] if compact_top_gap else None,
        "top_actionable_gaps": top_actionable_gaps,
        "blocking_gap_count": _positive_int(actionable.get("blocking_gap_count")) or 0,
        "diagnostic_gap_count": _positive_int(actionable.get("diagnostic_gap_count")) or 0,
        "evidence_bundle_gap_report": _compact_evidence_bundle_gap_report(
            gate.get("evidence_bundle_gap_report")
        ),
        "selected_evidence_weakness_counts": {
            "weak_case_count": _positive_int(selected_weakness.get("weak_case_count"))
            or 0,
            "low_answerability_item_count": _positive_int(
                selected_weakness.get("low_answerability_item_count")
            )
            or 0,
            "weak_source_locality_item_count": _positive_int(
                selected_weakness.get("weak_source_locality_item_count")
            )
            or 0,
            "broad_summary_item_count": _positive_int(
                selected_weakness.get("broad_summary_item_count")
            )
            or 0,
            "conflict_or_stale_item_count": _positive_int(
                selected_weakness.get("conflict_or_stale_item_count")
            )
            or 0,
            "reason_counts": _compact_count_mapping(
                selected_weakness.get("reason_counts")
            ),
            "risk_reason_counts": _compact_count_mapping(
                selected_weakness.get("risk_reason_counts")
            ),
        },
        "selected_evidence_weakness_samples": {
            "samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("samples")
            ),
            "low_answerability_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("low_answerability_samples")
            ),
            "weak_source_locality_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("weak_source_locality_samples")
            ),
            "broad_summary_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("broad_summary_samples")
            ),
            "conflict_or_stale_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("conflict_or_stale_samples")
            ),
        },
        "query_role_gap_counts": {
            "role_gap_count": _positive_int(query_role_gaps.get("role_gap_count")) or 0,
            "role_family_gap_count": _positive_int(
                query_role_gaps.get("role_family_gap_count")
            )
            or 0,
            "required_role_coverage_gap_count": _positive_int(
                query_role_gaps.get("required_role_coverage_gap_count")
            )
            or 0,
            "bridge_hit_roles_without_selected_items": _compact_sample_values(
                query_role_gaps.get("bridge_hit_roles_without_selected_items"),
                limit=8,
            ),
            "bridge_hit_role_families_without_selected_items": _compact_sample_values(
                query_role_gaps.get("bridge_hit_role_families_without_selected_items"),
                limit=8,
            ),
        },
        "query_plan_gap_counts": {
            "plan_gap_case_count": _positive_int(
                query_plan_gaps.get("plan_gap_case_count")
            )
            or 0,
            "missing_evidence_role_query_family_total": _positive_int(
                query_plan_gaps.get("missing_evidence_role_query_family_total")
            )
            or 0,
            "missing_evidence_role_query_family_counts": _compact_count_mapping(
                query_plan_gaps.get("missing_evidence_role_query_family_counts")
            ),
            "gap_reason_counts": _compact_count_mapping(
                query_plan_gaps.get("gap_reason_counts")
            ),
        },
        "bundle_gap_counts": {
            "incomplete_case_count": _positive_int(
                bundle_gaps.get("incomplete_case_count")
            )
            or 0,
            "reason_counts": _compact_count_mapping(bundle_gaps.get("reason_counts")),
            "bridge_gap_reason_counts": _compact_count_mapping(
                bundle_gaps.get("bridge_gap_reason_counts")
            ),
        },
        "answerability_gap_counts": {
            "gap_candidate_count": _positive_int(
                answerability_gaps.get("gap_candidate_count")
            )
            or 0,
            "gap_case_count": _positive_int(answerability_gaps.get("gap_case_count"))
            or 0,
            "lifted_gap_candidate_count": _positive_int(
                answerability_gaps.get("lifted_gap_candidate_count")
            )
            or 0,
            "lifted_gap_case_count": _positive_int(
                answerability_gaps.get("lifted_gap_case_count")
            )
            or 0,
            "low_answerability_candidate_count": _positive_int(
                answerability_gaps.get("low_answerability_candidate_count")
            )
            or 0,
            "low_answerability_case_count": _positive_int(
                answerability_gaps.get("low_answerability_case_count")
            )
            or 0,
            "lifted_low_answerability_candidate_count": _positive_int(
                answerability_gaps.get("lifted_low_answerability_candidate_count")
            )
            or 0,
            "lifted_low_answerability_case_count": _positive_int(
                answerability_gaps.get("lifted_low_answerability_case_count")
            )
            or 0,
            "reason_counts": _compact_count_mapping(
                answerability_gaps.get("reason_counts")
            ),
            "lifted_reason_counts": _compact_count_mapping(
                answerability_gaps.get("lifted_reason_counts")
            ),
            "category_counts": _compact_count_mapping(
                answerability_gaps.get("category_counts")
            ),
            "lifted_category_counts": _compact_count_mapping(
                answerability_gaps.get("lifted_category_counts")
            ),
        },
        "answerability_gap_samples": {
            "samples": _compact_answerability_gap_samples(
                answerability_gaps.get("samples")
            ),
            "low_answerability_samples": _compact_answerability_gap_samples(
                answerability_gaps.get("low_answerability_samples")
            ),
        },
        "answer_context_support_gap_counts": {
            "expected_context_count": _positive_int(
                answer_context_gaps.get("expected_context_count")
            )
            or 0,
            "context_count": _positive_int(answer_context_gaps.get("context_count"))
            or 0,
            "support_gap_context_count": _positive_int(
                answer_context_gaps.get("support_gap_context_count")
            )
            or 0,
            "answer_context_availability_gap_count": _positive_int(
                answer_context_gaps.get("answer_context_availability_gap_count")
            )
            or 0,
            "missing_answer_context_count": _positive_int(
                answer_context_gaps.get("missing_answer_context_count")
            )
            or 0,
            "unsupported_answer_context_count": _positive_int(
                answer_context_gaps.get("unsupported_answer_context_count")
            )
            or 0,
            "gap_reason_counts": _compact_count_mapping(
                answer_context_gaps.get("gap_reason_counts")
            ),
            "missing_required_role_counts": _compact_count_mapping(
                answer_context_gaps.get("missing_required_role_counts")
            ),
            "risk_reason_counts": _compact_count_mapping(
                answer_context_gaps.get("risk_reason_counts")
            ),
        },
        "answer_context_support_gap_samples": (
            _compact_answer_context_support_gap_samples(
                answer_context_gaps.get("samples")
            )
        ),
        "answer_context_availability_gap_samples": (
            _compact_answer_context_support_gap_samples(
                answer_context_gaps.get("availability_gap_samples")
            )
        ),
        "temporal_grounding_counts": {
            "temporal_case_count": _positive_int(
                temporal_grounding.get("temporal_case_count")
            )
            or 0,
            "temporal_scored_case_count": _positive_int(
                temporal_grounding.get("temporal_scored_case_count")
            )
            or 0,
            "retrieval_relative_date_grounded_candidate_count": _positive_int(
                temporal_grounding.get(
                    "retrieval_relative_date_grounded_candidate_count"
                )
            )
            or 0,
            "retrieval_bounded_window_grounded_candidate_count": _positive_int(
                temporal_grounding.get(
                    "retrieval_bounded_window_grounded_candidate_count"
                )
            )
            or 0,
            "selected_item_count": _positive_int(
                temporal_grounding.get("selected_item_count")
            )
            or 0,
            "selected_source_window_item_count": _positive_int(
                temporal_grounding.get("selected_source_window_item_count")
            )
            or 0,
            "selected_relative_date_grounded_item_count": _positive_int(
                temporal_grounding.get("selected_relative_date_grounded_item_count")
            )
            or 0,
            "selected_bounded_window_grounded_item_count": _positive_int(
                temporal_grounding.get("selected_bounded_window_grounded_item_count")
            )
            or 0,
            "selected_strong_temporal_grounding_item_count": _positive_int(
                temporal_grounding.get(
                    "selected_strong_temporal_grounding_item_count"
                )
            )
            or 0,
            "selected_temporal_grounding_issue_item_count": _positive_int(
                temporal_grounding.get(
                    "selected_temporal_grounding_issue_item_count"
                )
            )
            or 0,
            "selected_missing_temporal_grounding_issue_item_count": _positive_int(
                temporal_grounding.get(
                    "selected_missing_temporal_grounding_issue_item_count"
                )
            )
            or 0,
            "selected_weak_temporal_grounding_issue_item_count": _positive_int(
                temporal_grounding.get(
                    "selected_weak_temporal_grounding_issue_item_count"
                )
            )
            or 0,
            "selected_conflicting_temporal_grounding_issue_item_count": (
                _positive_int(
                    temporal_grounding.get(
                        "selected_conflicting_temporal_grounding_issue_item_count"
                    )
                )
                or 0
            ),
            "issue_reason_counts": _compact_count_mapping(
                temporal_grounding.get(
                    "selected_temporal_grounding_issue_reason_counts"
                )
            ),
        },
        "temporal_grounding_issue_samples": (
            _compact_temporal_grounding_issue_samples(
                temporal_grounding.get("selected_temporal_grounding_issue_samples")
            )
        ),
        "rerank_signal_gap_counts": {
            "candidate_count": _positive_int(rerank_signal_gaps.get("candidate_count"))
            or 0,
            "selected_item_count": _positive_int(
                rerank_signal_gaps.get("selected_item_count")
            )
            or 0,
            "positive_rerank_candidate_count": _positive_int(
                rerank_signal_gaps.get("positive_rerank_candidate_count")
            )
            or 0,
            "positive_unselected_candidate_count": _positive_int(
                rerank_signal_gaps.get("positive_unselected_candidate_count")
            )
            or 0,
            "positive_unselected_case_count": _positive_int(
                rerank_signal_gaps.get("positive_unselected_case_count")
            )
            or 0,
            "selected_with_positive_rerank_count": _positive_int(
                rerank_signal_gaps.get("selected_with_positive_rerank_count")
            )
            or 0,
            "selected_without_positive_rerank_count": _positive_int(
                rerank_signal_gaps.get("selected_without_positive_rerank_count")
            )
            or 0,
            "selected_without_positive_rerank_case_count": _positive_int(
                rerank_signal_gaps.get(
                    "selected_without_positive_rerank_case_count"
                )
            )
            or 0,
            "positive_signal_counts": _compact_count_mapping(
                rerank_signal_gaps.get("positive_signal_counts")
            ),
            "positive_unselected_signal_counts": _compact_count_mapping(
                rerank_signal_gaps.get("positive_unselected_signal_counts")
            ),
            "selected_without_positive_reason_counts": _compact_count_mapping(
                rerank_signal_gaps.get("selected_without_positive_reason_counts")
            ),
        },
        "rerank_signal_gap_samples": _compact_rerank_signal_gap_samples(
            rerank_signal_gaps
        ),
    }


def _nested_schema_versions(payload: Mapping[str, object]) -> dict[str, str]:
    versions: dict[str, str] = {}
    root_version = str(payload.get("schema_version") or "").strip()
    if root_version:
        versions["."] = root_version
    for key, value in sorted(payload.items()):
        if not isinstance(value, Mapping):
            continue
        schema_version = str(value.get("schema_version") or "").strip()
        if schema_version:
            versions[str(key)] = schema_version
    return versions


