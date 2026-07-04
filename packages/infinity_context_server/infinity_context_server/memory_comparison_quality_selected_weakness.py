"""Selected evidence weakness diagnostics for memory comparison reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_low_answerability as _is_measured_low_answerability,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_weak_source_locality as _is_measured_weak_source_locality,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    metric_value as _metric_value,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    source_refs_from_bundle_item as _source_refs_from_bundle_item,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)

_SELECTED_WEAKNESS_SAMPLE_LIMIT = 10
_SELECTED_WEAKNESS_REASON_LIMIT = 6
_SELECTED_WEAKNESS_QUERY_ROLE_LIMIT = 6
_SELECTED_WEAKNESS_SOURCE_REF_LIMIT = 5
_SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT = 5


def selected_evidence_weakness_breakdown(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    low_answerability_case_ids: set[str] = set()
    weak_source_locality_case_ids: set[str] = set()
    broad_summary_case_ids: set[str] = set()
    conflict_or_stale_case_ids: set[str] = set()
    group_case_ids: dict[str, set[str]] = defaultdict(set)
    reason_group_counts: dict[str, Counter[str]] = defaultdict(Counter)
    group_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    query_role_counts: Counter[str] = Counter()
    low_answerability_query_role_counts: Counter[str] = Counter()
    weak_source_locality_query_role_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    risk_reason_counts: Counter[str] = Counter()
    low_answerability_item_count = 0
    weak_source_locality_item_count = 0
    broad_summary_item_count = 0
    conflict_or_stale_item_count = 0
    samples: list[dict[str, object]] = []
    low_answerability_samples: list[dict[str, object]] = []
    weak_source_locality_samples: list[dict[str, object]] = []
    broad_summary_samples: list[dict[str, object]] = []
    conflict_or_stale_samples: list[dict[str, object]] = []

    for item in items:
        if item.get("scored") is not True:
            continue
        case_id = str(item.get("case_id") or "")
        group = str(item.get("group") or "")
        for bundle_item in _bundle_items(_mapping(item.get("evidence_bundle"))):
            reasons: list[str] = []
            answerability_score = _metric_value(bundle_item, "answerability_score")
            source_locality_score = _metric_value(bundle_item, "source_locality_score")
            planner_reasons = _str_tuple(bundle_item.get("planner_reason_codes"))
            risk_reasons = _selected_evidence_risk_reasons(
                planner_reasons,
                _str_tuple(bundle_item.get("risk_reason_codes")),
            )
            if _is_measured_low_answerability(answerability_score):
                low_answerability_item_count += 1
                if case_id:
                    low_answerability_case_ids.add(case_id)
                reasons.append("selected_low_answerability")
            if _is_measured_weak_source_locality(source_locality_score):
                weak_source_locality_item_count += 1
                if case_id:
                    weak_source_locality_case_ids.add(case_id)
                reasons.append("selected_weak_source_locality")
            if (
                bundle_item.get("broad_summary") is True
                or "broad_summary" in planner_reasons
                or "risk:broad_summary" in risk_reasons
            ):
                broad_summary_item_count += 1
                if case_id:
                    broad_summary_case_ids.add(case_id)
                reasons.append("selected_broad_summary")
            if (
                bundle_item.get("conflict_or_stale") is True
                or "conflict_or_stale" in planner_reasons
                or "risk:conflict_or_stale" in risk_reasons
            ):
                conflict_or_stale_item_count += 1
                if case_id:
                    conflict_or_stale_case_ids.add(case_id)
                reasons.append("selected_conflict_or_stale")
            if not reasons:
                continue
            group_label = group or "unknown"
            if case_id:
                group_case_ids[group_label].add(case_id)
            group_counts[group_label] += 1
            for reason in reasons:
                reason_group_counts[reason][group_label] += 1
            role = str(bundle_item.get("role") or "unknown").strip() or "unknown"
            query_roles = _str_tuple(bundle_item.get("query_roles"))
            role_counts[role] += 1
            query_role_counts.update(query_roles)
            if "selected_low_answerability" in reasons:
                low_answerability_query_role_counts.update(query_roles)
            if "selected_weak_source_locality" in reasons:
                weak_source_locality_query_role_counts.update(query_roles)
            reason_counts.update(reasons)
            risk_reason_counts.update(risk_reasons)
            sample = _selected_evidence_weakness_sample(
                bundle_item,
                case_id=case_id,
                group=group,
                role=role,
                query_roles=query_roles,
                reasons=tuple(reasons),
                risk_reasons=risk_reasons,
                planner_reasons=planner_reasons,
                answerability_score=answerability_score,
                source_locality_score=source_locality_score,
            )
            if len(samples) < _SELECTED_WEAKNESS_SAMPLE_LIMIT:
                samples.append(sample)
            if (
                "selected_low_answerability" in reasons
                and len(low_answerability_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                low_answerability_samples.append(sample)
            if (
                "selected_weak_source_locality" in reasons
                and len(weak_source_locality_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                weak_source_locality_samples.append(sample)
            if (
                "selected_broad_summary" in reasons
                and len(broad_summary_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                broad_summary_samples.append(sample)
            if (
                "selected_conflict_or_stale" in reasons
                and len(conflict_or_stale_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                conflict_or_stale_samples.append(sample)

    weak_case_ids = (
        low_answerability_case_ids
        | weak_source_locality_case_ids
        | broad_summary_case_ids
        | conflict_or_stale_case_ids
    )
    return {
        "schema_version": "selected_evidence_weakness.v2",
        "weak_case_count": len(weak_case_ids),
        "low_answerability_case_count": len(low_answerability_case_ids),
        "weak_source_locality_case_count": len(weak_source_locality_case_ids),
        "broad_summary_case_count": len(broad_summary_case_ids),
        "conflict_or_stale_case_count": len(conflict_or_stale_case_ids),
        "low_answerability_item_count": low_answerability_item_count,
        "weak_source_locality_item_count": weak_source_locality_item_count,
        "broad_summary_item_count": broad_summary_item_count,
        "conflict_or_stale_item_count": conflict_or_stale_item_count,
        "reason_counts": dict(sorted(reason_counts.items())),
        "risk_reason_counts": dict(sorted(risk_reason_counts.items())),
        "group_counts": dict(sorted(group_counts.items())),
        "group_case_counts": {
            group: len(case_ids) for group, case_ids in sorted(group_case_ids.items())
        },
        "reason_group_counts": {
            reason: dict(sorted(group_counts.items()))
            for reason, group_counts in sorted(reason_group_counts.items())
        },
        "role_counts": dict(sorted(role_counts.items())),
        "query_role_counts": dict(sorted(query_role_counts.items())),
        "low_answerability_query_role_counts": dict(
            sorted(low_answerability_query_role_counts.items())
        ),
        "weak_source_locality_query_role_counts": dict(
            sorted(weak_source_locality_query_role_counts.items())
        ),
        "samples": samples,
        "low_answerability_samples": low_answerability_samples,
        "weak_source_locality_samples": weak_source_locality_samples,
        "broad_summary_samples": broad_summary_samples,
        "conflict_or_stale_samples": conflict_or_stale_samples,
    }


def _selected_evidence_weakness_sample(
    bundle_item: Mapping[str, object],
    *,
    case_id: str,
    group: str,
    role: str,
    query_roles: Sequence[str],
    reasons: Sequence[str],
    risk_reasons: Sequence[str],
    planner_reasons: Sequence[str],
    answerability_score: float,
    source_locality_score: float,
) -> dict[str, object]:
    source_refs = _source_refs_from_bundle_item(bundle_item)
    sample: dict[str, object] = {
        "case_id": case_id,
        "group": group,
        "item_id": str(bundle_item.get("id") or bundle_item.get("item_id") or ""),
        "role": role,
        "query_roles": list(query_roles)[:_SELECTED_WEAKNESS_QUERY_ROLE_LIMIT],
        "retrieval_order": (
            _positive_int(bundle_item.get("retrieval_order"))
            or _positive_int(bundle_item.get("rank"))
            or 0
        ),
        "reasons": list(reasons),
        "answerability_score": round(answerability_score, 6),
        "source_locality_score": round(source_locality_score, 6),
        "broad_summary": (
            bundle_item.get("broad_summary") is True
            or "broad_summary" in planner_reasons
        ),
        "conflict_or_stale": (
            bundle_item.get("conflict_or_stale") is True
            or "conflict_or_stale" in planner_reasons
        ),
        "source_refs": list(source_refs)[:_SELECTED_WEAKNESS_SOURCE_REF_LIMIT],
        "source_ref_count": len(source_refs),
    }
    _add_compact_sample_list(
        sample,
        "risk_reason_codes",
        risk_reasons,
        limit=_SELECTED_WEAKNESS_REASON_LIMIT,
    )
    _add_compact_sample_list(
        sample,
        "planner_reason_codes",
        planner_reasons,
        limit=_SELECTED_WEAKNESS_REASON_LIMIT,
    )
    for key in (
        "answerability_reason_codes",
        "source_locality_reason_codes",
        "retrieval_sources",
        "source_types",
        "relation_categories",
        "relation_category_hits",
    ):
        _add_compact_sample_list(
            sample,
            key,
            _str_tuple(bundle_item.get(key)),
            limit=_SELECTED_WEAKNESS_REASON_LIMIT,
        )
    for key in ("source_type", "stale_reason", "conflict_reason"):
        value = str(bundle_item.get(key) or "").strip()
        if value:
            sample[key] = value
    return sample


def _selected_evidence_risk_reasons(
    *sources: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            reason
            for source in sources
            for reason in source
            if reason.startswith("risk:")
        )
    )


def _add_compact_sample_list(
    sample: dict[str, object],
    key: str,
    values: Sequence[str],
    *,
    limit: int,
) -> None:
    compact = tuple(dict.fromkeys(value for value in values if value.strip()))[:limit]
    if compact:
        sample[key] = list(compact)
