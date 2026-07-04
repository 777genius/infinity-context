"""Query-role gap helpers for memory-comparison quality diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    bundle_items as _bundle_items,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    candidate_features as _candidate_features,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    count_mapping as _count_mapping,
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
from infinity_context_server.memory_comparison_quality_accessors import ratio as _ratio
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)
from infinity_context_server.memory_comparison_quality_query_roles import (
    _query_role_families,
)

_QUERY_ROLE_GAP_SAMPLE_LIMIT = 10
_QUERY_ROLE_GAP_SELECTED_LIST_LIMIT = 6


def query_role_gap_breakdown(
    query_role_effectiveness: Mapping[str, object],
    *,
    candidate_fusion_summary: Mapping[str, object] | None = None,
    items: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    candidate_role_counts = _count_mapping(
        query_role_effectiveness.get("candidate_role_counts")
    )
    lifted_candidate_role_counts = _count_mapping(
        query_role_effectiveness.get("lifted_candidate_role_counts")
    )
    selected_item_role_counts = _count_mapping(
        query_role_effectiveness.get("selected_item_role_counts")
    )
    typed_relation_hit_role_counts = _count_mapping(
        query_role_effectiveness.get("typed_relation_hit_role_counts")
    )
    typed_relation_lifted_hit_role_counts = _count_mapping(
        query_role_effectiveness.get("typed_relation_lifted_hit_role_counts")
    )
    candidate_role_family_counts = _count_mapping(
        query_role_effectiveness.get("candidate_role_family_counts")
    )
    lifted_candidate_role_family_counts = _count_mapping(
        query_role_effectiveness.get("lifted_candidate_role_family_counts")
    )
    selected_item_role_family_counts = _count_mapping(
        query_role_effectiveness.get("selected_item_role_family_counts")
    )
    bridge_hit_candidate_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_candidate_counts")
    )
    bridge_hit_selected_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_selected_counts")
    )
    candidate_fusion = _mapping(candidate_fusion_summary)
    fusion_query_role_counts = _count_mapping(candidate_fusion.get("query_role_counts"))
    selected_evidence_query_role_counts = _count_mapping(
        candidate_fusion.get("selected_evidence_query_role_counts")
    )
    selected_evidence_query_role_family_counts = (
        _selected_evidence_query_role_family_counts(
            selected_evidence_query_role_counts
        )
    )
    role_family_gap_summary = query_role_family_gap_summary(
        query_role_effectiveness,
        selected_evidence_query_role_family_counts=(
            selected_evidence_query_role_family_counts
        ),
    )
    required_evidence_role_counts = _count_mapping(
        query_role_effectiveness.get("required_evidence_role_counts")
    )
    required_role_selected_evidence_query_counts = _count_mapping(
        query_role_effectiveness.get("required_role_selected_evidence_query_counts")
    )
    missing_required_evidence_role_counts = _count_mapping(
        query_role_effectiveness.get("missing_required_evidence_role_counts")
    )
    missing_required_role_candidate_query_counts = _count_mapping(
        query_role_effectiveness.get("missing_required_role_candidate_query_counts")
    )
    missing_required_role_selected_query_counts = _count_mapping(
        query_role_effectiveness.get("missing_required_role_selected_query_counts")
    )
    missing_required_role_selected_evidence_query_counts = _count_mapping(
        query_role_effectiveness.get(
            "missing_required_role_selected_evidence_query_counts"
        )
    )
    candidate_roles = sorted(
        role for role, count in candidate_role_counts.items() if count > 0
    )
    role_stats = _mapping(query_role_effectiveness.get("role_stats"))
    role_gaps: dict[str, dict[str, object]] = {}

    for role in candidate_roles:
        stats = _mapping(role_stats.get(role))
        candidate_count = candidate_role_counts.get(role, 0)
        lifted_count = lifted_candidate_role_counts.get(role, 0)
        selected_count = selected_item_role_counts.get(role, 0)
        selected_evidence_count = selected_evidence_query_role_counts.get(role, 0)
        bridge_candidate_count = bridge_hit_candidate_counts.get(role, 0)
        bridge_selected_count = bridge_hit_selected_counts.get(role, 0)
        typed_relation_hit_count = typed_relation_hit_role_counts.get(role, 0)
        typed_relation_lifted_hit_count = typed_relation_lifted_hit_role_counts.get(
            role,
            0,
        )
        gap_reasons: list[str] = []
        if selected_count <= 0 and selected_evidence_count <= 0:
            gap_reasons.append("not_selected")
        if selected_count <= 0 and selected_evidence_count > 0:
            gap_reasons.append("selected_evidence_not_bundle_tagged")
        if lifted_count <= 0:
            gap_reasons.append("not_lifted")
        if bridge_candidate_count > bridge_selected_count:
            gap_reasons.append("bridge_hit_not_selected")
        if role in _typed_relation_roles_without_hits(
            query_role_effectiveness,
            candidate_role_counts=candidate_role_counts,
        ):
            gap_reasons.append("typed_relation_not_hit")
        if not gap_reasons:
            continue

        role_gaps[role] = {
            "candidate_count": candidate_count,
            "lifted_candidate_count": lifted_count,
            "selected_item_count": selected_count,
            "typed_relation_hit_count": typed_relation_hit_count,
            "typed_relation_lifted_hit_count": typed_relation_lifted_hit_count,
            "selection_rate": round(_metric_value(stats, "selection_rate"), 4),
            "lifted_rate": round(_metric_value(stats, "lifted_rate"), 4),
            "typed_relation_hit_rate": round(
                _metric_value(stats, "typed_relation_hit_rate"),
                4,
            ),
            "bridge_query_hit_candidate_count": bridge_candidate_count,
            "bridge_query_hit_selected_count": bridge_selected_count,
            "avg_candidate_answerability_score": round(
                _metric_value(stats, "avg_candidate_answerability_score"),
                4,
            ),
            "avg_measured_candidate_answerability_score": round(
                _metric_value(stats, "avg_measured_candidate_answerability_score"),
                4,
            ),
            "candidate_unmeasured_answerability_count": _positive_int(
                stats.get("candidate_unmeasured_answerability_count")
            )
            or 0,
            "avg_candidate_source_locality_score": round(
                _metric_value(stats, "avg_candidate_source_locality_score"),
                4,
            ),
            "avg_measured_candidate_source_locality_score": round(
                _metric_value(stats, "avg_measured_candidate_source_locality_score"),
                4,
            ),
            "candidate_unmeasured_source_locality_count": _positive_int(
                stats.get("candidate_unmeasured_source_locality_count")
            )
            or 0,
            "avg_selected_answerability_score": round(
                _metric_value(stats, "avg_selected_answerability_score"),
                4,
            ),
            "avg_measured_selected_answerability_score": round(
                _metric_value(stats, "avg_measured_selected_answerability_score"),
                4,
            ),
            "selected_unmeasured_answerability_count": _positive_int(
                stats.get("selected_unmeasured_answerability_count")
            )
            or 0,
            "avg_selected_source_locality_score": round(
                _metric_value(stats, "avg_selected_source_locality_score"),
                4,
            ),
            "avg_measured_selected_source_locality_score": round(
                _metric_value(stats, "avg_measured_selected_source_locality_score"),
                4,
            ),
            "selected_unmeasured_source_locality_count": _positive_int(
                stats.get("selected_unmeasured_source_locality_count")
            )
            or 0,
            "selected_bundle_role_counts": _count_mapping(
                stats.get("selected_bundle_role_counts")
            ),
            "gap_reasons": gap_reasons,
        }
        if role in fusion_query_role_counts or selected_evidence_count > 0:
            role_gaps[role]["selected_evidence_query_role_count"] = (
                selected_evidence_count
            )

    return {
        "schema_version": "query_role_gap_breakdown.v1",
        "role_count": _positive_int(query_role_effectiveness.get("role_count"))
        or len(
            set(candidate_role_counts)
            | set(lifted_candidate_role_counts)
            | set(selected_item_role_counts)
        ),
        "role_family_count": _positive_int(
            query_role_effectiveness.get("role_family_count")
        )
        or len(
            set(candidate_role_family_counts)
            | set(lifted_candidate_role_family_counts)
            | set(selected_item_role_family_counts)
        ),
        "candidate_role_count": len(candidate_roles),
        "role_gap_count": len(role_gaps),
        "candidate_role_counts": candidate_role_counts,
        "lifted_candidate_role_counts": lifted_candidate_role_counts,
        "selected_item_role_counts": selected_item_role_counts,
        "candidate_fusion_query_role_counts": fusion_query_role_counts,
        "selected_evidence_query_role_counts": selected_evidence_query_role_counts,
        "typed_relation_hit_role_counts": typed_relation_hit_role_counts,
        "typed_relation_lifted_hit_role_counts": (
            typed_relation_lifted_hit_role_counts
        ),
        "candidate_role_family_counts": candidate_role_family_counts,
        "lifted_candidate_role_family_counts": lifted_candidate_role_family_counts,
        "selected_item_role_family_counts": selected_item_role_family_counts,
        "bridge_query_hit_candidate_counts": bridge_hit_candidate_counts,
        "bridge_query_hit_selected_counts": bridge_hit_selected_counts,
        **role_family_gap_summary,
        "required_evidence_role_counts": required_evidence_role_counts,
        "required_role_selected_evidence_query_counts": (
            required_role_selected_evidence_query_counts
        ),
        "missing_required_evidence_role_counts": missing_required_evidence_role_counts,
        "missing_required_role_candidate_query_counts": (
            missing_required_role_candidate_query_counts
        ),
        "missing_required_role_selected_query_counts": (
            missing_required_role_selected_query_counts
        ),
        "missing_required_role_selected_evidence_query_counts": (
            missing_required_role_selected_evidence_query_counts
        ),
        "required_roles_without_candidate_queries": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("required_roles_without_candidate_queries")
            )
            if missing_required_role_candidate_query_counts.get(role, 0) > 0
        ],
        "required_roles_without_selected_queries": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("required_roles_without_selected_queries")
            )
            if missing_required_role_selected_query_counts.get(role, 0) > 0
        ],
        "required_roles_without_selected_evidence_queries": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get(
                    "required_roles_without_selected_evidence_queries"
                )
            )
            if missing_required_role_selected_evidence_query_counts.get(role, 0) > 0
        ],
        "missing_required_evidence_roles": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("missing_required_evidence_roles")
            )
            if missing_required_evidence_role_counts.get(role, 0) > 0
        ],
        "roles_without_selected_items": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("roles_without_selected_items")
            )
            if candidate_role_counts.get(role, 0) > 0
        ],
        "roles_without_selected_evidence": [
            role
            for role in candidate_roles
            if selected_item_role_counts.get(role, 0) <= 0
            and selected_evidence_query_role_counts.get(role, 0) <= 0
        ],
        "roles_with_selected_evidence_only_in_fusion": [
            role
            for role in candidate_roles
            if selected_item_role_counts.get(role, 0) <= 0
            and selected_evidence_query_role_counts.get(role, 0) > 0
        ],
        "roles_without_lifted_candidates": [
            role
            for role in _str_tuple(
                query_role_effectiveness.get("roles_without_lifted_candidates")
            )
            if candidate_role_counts.get(role, 0) > 0
        ],
        "bridge_hit_roles_without_selected_items": [
            role
            for role in candidate_roles
            if bridge_hit_candidate_counts.get(role, 0) > 0
            and bridge_hit_selected_counts.get(role, 0) <= 0
        ],
        "roles_without_typed_relation_hits": _typed_relation_roles_without_hits(
            query_role_effectiveness,
            candidate_role_counts=candidate_role_counts,
        ),
        "role_gaps": role_gaps,
        "samples": _query_role_gap_samples(items or (), role_gaps),
    }


def query_role_family_gap_summary(
    query_role_effectiveness: Mapping[str, object],
    *,
    selected_evidence_query_role_family_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    candidate_family_counts = _count_mapping(
        query_role_effectiveness.get("candidate_role_family_counts")
    )
    lifted_family_counts = _count_mapping(
        query_role_effectiveness.get("lifted_candidate_role_family_counts")
    )
    selected_family_counts = _count_mapping(
        query_role_effectiveness.get("selected_item_role_family_counts")
    )
    bridge_candidate_family_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_candidate_family_counts")
    )
    bridge_selected_family_counts = _count_mapping(
        query_role_effectiveness.get("bridge_query_hit_selected_family_counts")
    )
    selected_evidence_family_counts = _count_mapping(
        selected_evidence_query_role_family_counts
    )
    role_family_gaps = _query_role_family_gaps(
        candidate_family_counts=candidate_family_counts,
        lifted_family_counts=lifted_family_counts,
        selected_family_counts=selected_family_counts,
        selected_evidence_family_counts=selected_evidence_family_counts,
        bridge_candidate_family_counts=bridge_candidate_family_counts,
        bridge_selected_family_counts=bridge_selected_family_counts,
    )
    return {
        "bridge_query_hit_candidate_family_counts": bridge_candidate_family_counts,
        "bridge_query_hit_selected_family_counts": bridge_selected_family_counts,
        "selected_evidence_query_role_family_counts": selected_evidence_family_counts,
        "role_families_without_selected_items": [
            family
            for family, count in sorted(candidate_family_counts.items())
            if count > 0 and selected_family_counts.get(family, 0) <= 0
        ],
        "role_families_without_selected_evidence": [
            family
            for family, count in sorted(candidate_family_counts.items())
            if count > 0
            and selected_family_counts.get(family, 0) <= 0
            and selected_evidence_family_counts.get(family, 0) <= 0
        ],
        "role_families_with_selected_evidence_only_in_fusion": [
            family
            for family, count in sorted(candidate_family_counts.items())
            if count > 0
            and selected_family_counts.get(family, 0) <= 0
            and selected_evidence_family_counts.get(family, 0) > 0
        ],
        "role_families_without_lifted_candidates": [
            family
            for family, count in sorted(candidate_family_counts.items())
            if count > 0 and lifted_family_counts.get(family, 0) <= 0
        ],
        "bridge_hit_role_families_without_selected_items": [
            family
            for family, count in sorted(bridge_candidate_family_counts.items())
            if count > 0 and bridge_selected_family_counts.get(family, 0) <= 0
        ],
        "role_family_gap_count": len(role_family_gaps),
        "role_family_gaps": role_family_gaps,
    }


def _query_role_family_gaps(
    *,
    candidate_family_counts: Mapping[str, int],
    lifted_family_counts: Mapping[str, int],
    selected_family_counts: Mapping[str, int],
    selected_evidence_family_counts: Mapping[str, int],
    bridge_candidate_family_counts: Mapping[str, int],
    bridge_selected_family_counts: Mapping[str, int],
) -> dict[str, dict[str, object]]:
    role_family_gaps: dict[str, dict[str, object]] = {}
    for family, candidate_count in sorted(candidate_family_counts.items()):
        if candidate_count <= 0:
            continue
        lifted_count = lifted_family_counts.get(family, 0)
        selected_count = selected_family_counts.get(family, 0)
        selected_evidence_count = selected_evidence_family_counts.get(family, 0)
        bridge_candidate_count = bridge_candidate_family_counts.get(family, 0)
        bridge_selected_count = bridge_selected_family_counts.get(family, 0)
        gap_reasons: list[str] = []
        if selected_count <= 0 and selected_evidence_count <= 0:
            gap_reasons.append("not_selected")
        if selected_count <= 0 and selected_evidence_count > 0:
            gap_reasons.append("selected_evidence_not_bundle_tagged")
        if lifted_count <= 0:
            gap_reasons.append("not_lifted")
        if bridge_candidate_count > bridge_selected_count:
            gap_reasons.append("bridge_hit_not_selected")
        if not gap_reasons:
            continue
        role_family_gaps[family] = {
            "candidate_count": candidate_count,
            "lifted_candidate_count": lifted_count,
            "selected_item_count": selected_count,
            "selection_rate": round(_ratio(selected_count, candidate_count), 4),
            "lifted_rate": round(_ratio(lifted_count, candidate_count), 4),
            "bridge_query_hit_candidate_count": bridge_candidate_count,
            "bridge_query_hit_selected_count": bridge_selected_count,
            "gap_reasons": gap_reasons,
        }
        if selected_evidence_count > 0:
            role_family_gaps[family]["selected_evidence_query_role_family_count"] = (
                selected_evidence_count
            )
    return role_family_gaps


def _selected_evidence_query_role_family_counts(
    selected_evidence_query_role_counts: Mapping[str, int],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for role, count in selected_evidence_query_role_counts.items():
        if count <= 0:
            continue
        for family in _query_role_families(role):
            counts[family] += count
    return dict(sorted(counts.items()))


def _typed_relation_roles_without_hits(
    query_role_effectiveness: Mapping[str, object],
    *,
    candidate_role_counts: Mapping[str, int],
) -> list[str]:
    return [
        role
        for role in _str_tuple(
            query_role_effectiveness.get("roles_without_typed_relation_hits")
        )
        if candidate_role_counts.get(role, 0) > 0
    ]


def _query_role_gap_samples(
    items: Sequence[Mapping[str, object]],
    role_gaps: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    if not role_gaps:
        return []
    samples: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    gap_roles = set(role_gaps)
    for item in items:
        case_id = str(item.get("case_id") or "")
        group = str(item.get("group") or "")
        selected_roles = _selected_bundle_roles(item)
        selected_query_roles = _selected_bundle_query_roles(item)
        retrieval = _mapping(item.get("retrieval"))
        for memory in _sequence(retrieval.get("results")):
            if not isinstance(memory, Mapping):
                continue
            features = _candidate_features(memory)
            candidate_roles = tuple(
                role
                for role in _str_tuple(features.get("query_roles"))
                if role in gap_roles
            )
            if not candidate_roles:
                continue
            diagnostics = _memory_diagnostics(memory)
            for query_role in candidate_roles:
                key = (case_id, query_role)
                if key in seen:
                    continue
                seen.add(key)
                samples.append(
                    {
                        "case_id": case_id,
                        "group": group,
                        "query_role": query_role,
                        "query_role_families": list(
                            _query_role_families(query_role)
                        ),
                        "gap_reasons": list(
                            _str_tuple(
                                _mapping(role_gaps.get(query_role)).get(
                                    "gap_reasons"
                                )
                            )
                        ),
                        "memory_id": _memory_id(memory),
                        "rank": _positive_int(memory.get("rank")) or 0,
                        "lifted": _candidate_lifted(diagnostics),
                        "positive_policy_score": round(
                            _positive_policy_score(diagnostics),
                            6,
                        ),
                        "answerability_score": round(
                            _metric_value(features, "answerability_score"),
                            6,
                        ),
                        "source_locality_score": round(
                            _metric_value(features, "source_locality_score"),
                            6,
                        ),
                        "bridge_query_hit": features.get("bridge_query_hit") is True,
                        "selected_bundle_roles": list(selected_roles)[
                            :_QUERY_ROLE_GAP_SELECTED_LIST_LIMIT
                        ],
                        "selected_bundle_query_roles": list(selected_query_roles)[
                            :_QUERY_ROLE_GAP_SELECTED_LIST_LIMIT
                        ],
                    }
                )
                if len(samples) >= _QUERY_ROLE_GAP_SAMPLE_LIMIT:
                    return samples
    return samples


def _selected_bundle_roles(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    return tuple(
        dict.fromkeys(
            role
            for bundle_item in _bundle_items(bundle)
            for role in _str_tuple(bundle_item.get("role"))
        )
    )


def _selected_bundle_query_roles(item: Mapping[str, object]) -> tuple[str, ...]:
    bundle = _mapping(item.get("evidence_bundle"))
    return tuple(
        dict.fromkeys(
            role
            for bundle_item in _bundle_items(bundle)
            for role in _str_tuple(bundle_item.get("query_roles"))
        )
    )


def _candidate_lifted(diagnostics: Mapping[str, object]) -> bool:
    return (
        diagnostics.get("benchmark_rerank_boosted") is True
        or _positive_policy_score(diagnostics) > 0
    )
