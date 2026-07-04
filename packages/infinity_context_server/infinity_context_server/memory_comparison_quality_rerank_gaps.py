"""Rerank signal gap diagnostics for memory-comparison quality reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    active_policy_reasons as _active_policy_reasons,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    candidate_features as _candidate_features,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    memory_diagnostics as _memory_diagnostics,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    memory_id as _memory_id,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    metric_value as _metric_value,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_policy_score as _positive_policy_score,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_signal_names as _positive_signal_names,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    top_counts as _top_counts,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    top_signal_values as _top_signal_values,
)


def rerank_signal_gap_breakdown(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    candidate_count = 0
    positive_candidate_count = 0
    positive_unselected_candidate_count = 0
    selected_item_count = 0
    selected_with_positive_rerank_count = 0
    selected_without_positive_rerank_count = 0
    positive_unselected_case_ids: set[str] = set()
    selected_without_positive_case_ids: set[str] = set()
    positive_signal_counts: Counter[str] = Counter()
    positive_unselected_signal_counts: Counter[str] = Counter()
    cap_signal_counts: Counter[str] = Counter()
    penalty_signal_counts: Counter[str] = Counter()
    positive_unselected_cap_signal_counts: Counter[str] = Counter()
    positive_unselected_penalty_signal_counts: Counter[str] = Counter()
    selected_without_positive_reason_counts: Counter[str] = Counter()
    selected_without_positive_penalty_signal_counts: Counter[str] = Counter()
    selection_conflict_case_count = 0
    selection_conflict_pair_count = 0
    selection_conflict_positive_signal_counts: Counter[str] = Counter()
    positive_unselected_samples: list[dict[str, object]] = []
    selected_without_positive_samples: list[dict[str, object]] = []
    selection_conflict_samples: list[dict[str, object]] = []

    for item in items:
        case_id = str(item.get("case_id") or "")
        selected_items = _bundle_items(_mapping(item.get("evidence_bundle")))
        selected_ids = tuple(
            item_id
            for item_id in (_bundle_item_id(bundle_item) for bundle_item in selected_items)
            if item_id
        )
        selected_id_set = set(selected_ids)
        candidate_by_id: dict[str, Mapping[str, object]] = {}
        positive_candidate_ids: set[str] = set()
        case_positive_unselected_count = 0
        case_selected_without_positive_count = 0
        case_positive_unselected_signal_counts: Counter[str] = Counter()
        case_positive_unselected_samples: list[dict[str, object]] = []
        case_selected_without_positive_samples: list[dict[str, object]] = []

        for memory in _sequence(_mapping(item.get("retrieval")).get("results")):
            if not isinstance(memory, Mapping):
                continue
            candidate_count += 1
            memory_item_id = _memory_id(memory)
            if memory_item_id and memory_item_id not in candidate_by_id:
                candidate_by_id[memory_item_id] = memory
            diagnostics = _memory_diagnostics(memory)
            score_signals = _mapping(diagnostics.get("score_signals"))
            if not _candidate_lifted(diagnostics):
                continue

            positive_candidate_count += 1
            positive_signal_names = _positive_signal_names(score_signals)
            positive_signal_counts.update(positive_signal_names)
            cap_signals = _visible_signal_values(score_signals, "cap")
            penalty_signals = _visible_signal_values(score_signals, "penalty")
            cap_signal_counts.update(cap_signals.keys())
            penalty_signal_counts.update(penalty_signals.keys())
            if memory_item_id:
                positive_candidate_ids.add(memory_item_id)
            if memory_item_id in selected_id_set:
                continue

            positive_unselected_candidate_count += 1
            case_positive_unselected_count += 1
            if case_id:
                positive_unselected_case_ids.add(case_id)
            positive_unselected_signal_counts.update(positive_signal_names)
            case_positive_unselected_signal_counts.update(positive_signal_names)
            positive_unselected_cap_signal_counts.update(cap_signals.keys())
            positive_unselected_penalty_signal_counts.update(penalty_signals.keys())
            positive_unselected_sample: dict[str, object] | None = None
            if (
                len(positive_unselected_samples) < 10
                or len(case_positive_unselected_samples) < 3
            ):
                positive_unselected_sample = _positive_unselected_rerank_sample(
                    item,
                    memory,
                    selected_item_ids=selected_ids,
                )
            if (
                positive_unselected_sample is not None
                and len(positive_unselected_samples) < 10
            ):
                positive_unselected_samples.append(positive_unselected_sample)
            if (
                positive_unselected_sample is not None
                and len(case_positive_unselected_samples) < 3
            ):
                case_positive_unselected_samples.append(positive_unselected_sample)

        for selected_item in selected_items:
            selected_item_count += 1
            selected_item_id = _bundle_item_id(selected_item)
            matched_memory = (
                candidate_by_id.get(selected_item_id) if selected_item_id else None
            )
            if selected_item_id and selected_item_id in positive_candidate_ids:
                selected_with_positive_rerank_count += 1
                continue

            selected_without_positive_rerank_count += 1
            case_selected_without_positive_count += 1
            if case_id:
                selected_without_positive_case_ids.add(case_id)
            reason = (
                "no_positive_rerank_signal"
                if matched_memory is not None
                else "missing_retrieval_match"
            )
            selected_without_positive_reason_counts[reason] += 1
            if matched_memory is not None:
                selected_without_positive_penalty_signal_counts.update(
                    _visible_signal_values(
                        _mapping(
                            _memory_diagnostics(matched_memory).get("score_signals")
                        ),
                        "penalty",
                    ).keys()
                )
            selected_without_positive_sample: dict[str, object] | None = None
            if (
                len(selected_without_positive_samples) < 10
                or len(case_selected_without_positive_samples) < 3
            ):
                selected_without_positive_sample = (
                    _selected_without_positive_rerank_sample(
                        item,
                        selected_item,
                        matched_memory=matched_memory,
                        reason=reason,
                    )
                )
            if (
                selected_without_positive_sample is not None
                and len(selected_without_positive_samples) < 10
            ):
                selected_without_positive_samples.append(selected_without_positive_sample)
            if (
                selected_without_positive_sample is not None
                and len(case_selected_without_positive_samples) < 3
            ):
                case_selected_without_positive_samples.append(
                    selected_without_positive_sample
                )

        if case_positive_unselected_count and case_selected_without_positive_count:
            selection_conflict_case_count += 1
            selection_conflict_pair_count += (
                case_positive_unselected_count * case_selected_without_positive_count
            )
            selection_conflict_positive_signal_counts.update(
                case_positive_unselected_signal_counts
            )
            if len(selection_conflict_samples) < 10:
                selection_conflict_samples.append(
                    {
                        "case_id": case_id,
                        "group": str(item.get("group") or ""),
                        "positive_unselected_candidate_count": (
                            case_positive_unselected_count
                        ),
                        "selected_without_positive_rerank_count": (
                            case_selected_without_positive_count
                        ),
                        "positive_unselected_signal_counts": _top_counts(
                            case_positive_unselected_signal_counts,
                            limit=8,
                        ),
                        "positive_unselected_candidates": (
                            case_positive_unselected_samples
                        ),
                        "selected_without_positive_items": (
                            case_selected_without_positive_samples
                        ),
                    }
                )

    return {
        "schema_version": "rerank_signal_gaps.v1",
        "candidate_count": candidate_count,
        "selected_item_count": selected_item_count,
        "positive_rerank_candidate_count": positive_candidate_count,
        "positive_unselected_candidate_count": positive_unselected_candidate_count,
        "positive_unselected_case_count": len(positive_unselected_case_ids),
        "selected_with_positive_rerank_count": selected_with_positive_rerank_count,
        "selected_without_positive_rerank_count": (
            selected_without_positive_rerank_count
        ),
        "selected_without_positive_rerank_case_count": len(
            selected_without_positive_case_ids
        ),
        "positive_signal_counts": _top_counts(positive_signal_counts),
        "positive_unselected_signal_counts": _top_counts(
            positive_unselected_signal_counts
        ),
        "cap_signal_counts": _top_counts(cap_signal_counts),
        "penalty_signal_counts": _top_counts(penalty_signal_counts),
        "positive_unselected_cap_signal_counts": _top_counts(
            positive_unselected_cap_signal_counts
        ),
        "positive_unselected_penalty_signal_counts": _top_counts(
            positive_unselected_penalty_signal_counts
        ),
        "selected_without_positive_reason_counts": dict(
            sorted(selected_without_positive_reason_counts.items())
        ),
        "selected_without_positive_penalty_signal_counts": _top_counts(
            selected_without_positive_penalty_signal_counts
        ),
        "selection_conflict_case_count": selection_conflict_case_count,
        "selection_conflict_pair_count": selection_conflict_pair_count,
        "selection_conflict_positive_signal_counts": _top_counts(
            selection_conflict_positive_signal_counts
        ),
        "positive_unselected_samples": positive_unselected_samples,
        "selected_without_positive_samples": selected_without_positive_samples,
        "selection_conflict_samples": selection_conflict_samples,
    }


def _positive_unselected_rerank_sample(
    item: Mapping[str, object],
    memory: Mapping[str, object],
    *,
    selected_item_ids: Sequence[str],
) -> dict[str, object]:
    diagnostics = _memory_diagnostics(memory)
    features = _candidate_features(memory)
    score_signals = _mapping(diagnostics.get("score_signals"))
    sample = _rerank_gap_candidate_sample(
        item,
        memory,
        features=features,
        diagnostics=diagnostics,
        score_signals=score_signals,
    )
    sample["selected_item_ids"] = list(selected_item_ids[:8])
    return sample


def _selected_without_positive_rerank_sample(
    item: Mapping[str, object],
    selected_item: Mapping[str, object],
    *,
    matched_memory: Mapping[str, object] | None,
    reason: str,
) -> dict[str, object]:
    score_signals: Mapping[str, object] = {}
    positive_policy_score = 0.0
    top_signals: dict[str, object] = {}
    if matched_memory is not None:
        diagnostics = _memory_diagnostics(matched_memory)
        score_signals = _mapping(diagnostics.get("score_signals"))
        positive_policy_score = _positive_policy_score(diagnostics)
        top_signals = _top_signal_values(score_signals)

    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": _bundle_item_id(selected_item),
        "reason": reason,
        "matched_retrieval_candidate": matched_memory is not None,
        "role": str(selected_item.get("role") or ""),
        "retrieval_order": _positive_int(selected_item.get("retrieval_order")) or 0,
        "positive_policy_score": round(positive_policy_score, 6),
        "top_signals": top_signals,
        "answerability_score": round(
            _metric_value(selected_item, "answerability_score"),
            6,
        ),
        "source_locality_score": round(
            _metric_value(selected_item, "source_locality_score"),
            6,
        ),
        "source_type": str(selected_item.get("source_type") or "unknown"),
        "query_roles": _str_tuple(selected_item.get("query_roles")),
        "planner_reason_codes": _str_tuple(selected_item.get("planner_reason_codes")),
    }
    penalty_signals = _visible_signal_values(score_signals, "penalty")
    if penalty_signals:
        sample["penalty_signals"] = penalty_signals
    cap_signals = _visible_signal_values(score_signals, "cap")
    if cap_signals:
        sample["cap_signals"] = cap_signals
    return sample


def _rerank_gap_candidate_sample(
    item: Mapping[str, object],
    memory: Mapping[str, object],
    *,
    features: Mapping[str, object],
    diagnostics: Mapping[str, object],
    score_signals: Mapping[str, object],
) -> dict[str, object]:
    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "item_id": _memory_id(memory),
        "rank": _positive_int(memory.get("rank")) or 0,
        "score": round(_metric_value(memory, "score"), 6),
        "benchmark_rerank_boosted": diagnostics.get("benchmark_rerank_boosted")
        is True,
        "positive_policy_score": round(_positive_policy_score(diagnostics), 6),
        "policy_reasons": {
            policy: list(reasons)
            for policy, reasons in sorted(_active_policy_reasons(diagnostics).items())
        },
        "top_signals": _top_signal_values(score_signals),
        "answerability_score": round(
            _metric_value(features, "answerability_score"),
            6,
        ),
        "source_locality_score": round(
            _metric_value(features, "source_locality_score"),
            6,
        ),
        "source_type": str(features.get("source_type") or "unknown"),
        "query_roles": _str_tuple(features.get("query_roles")),
        "relation_category_hits": _str_tuple(features.get("relation_category_hits")),
    }
    cap_signals = _visible_signal_values(score_signals, "cap")
    if cap_signals:
        sample["cap_signals"] = cap_signals
    penalty_signals = _visible_signal_values(score_signals, "penalty")
    if penalty_signals:
        sample["penalty_signals"] = penalty_signals
    return sample


def _candidate_lifted(diagnostics: Mapping[str, object]) -> bool:
    score_signals = _mapping(diagnostics.get("score_signals"))
    return (
        diagnostics.get("benchmark_rerank_boosted") is True
        or _positive_policy_score(diagnostics) > 0
        or bool(_positive_signal_names(score_signals))
    )


def _bundle_item_id(selected_item: Mapping[str, object]) -> str:
    return str(selected_item.get("id") or selected_item.get("item_id") or "").strip()


def _visible_signal_values(
    score_signals: Mapping[str, object],
    name_fragment: str,
) -> dict[str, object]:
    values: dict[str, object] = {}
    for name, value in score_signals.items():
        signal_name = str(name)
        if name_fragment not in signal_name:
            continue
        if isinstance(value, bool):
            if value:
                values[signal_name] = value
            continue
        metric = _metric_value(score_signals, signal_name)
        if metric != 0:
            values[signal_name] = round(metric, 6)
    return dict(sorted(values.items()))
