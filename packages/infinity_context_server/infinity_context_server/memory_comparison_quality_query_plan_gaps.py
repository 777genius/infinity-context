"""Query-plan gap helpers for memory-comparison quality diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    count_mapping as _count_mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    sequence as _sequence,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    str_tuple as _str_tuple,
)

_PROFILE_SUPPORT_ROLES = frozenset(
    {
        "action_support",
        "activity_support",
        "age_support",
        "alias_support",
        "commitment_support",
        "contact_support",
        "current_goal_support",
        "date_support",
        "diet_support",
        "education_support",
        "employment_support",
        "favorite_support",
        "health_support",
        "identity_support",
        "pet_support",
        "skill_support",
        "status_support",
        "support_goal_support",
        "vehicle_support",
    }
)


def query_plan_gap_breakdown(
    query_plan_integrity: Mapping[str, object],
) -> dict[str, object]:
    samples = list(_sequence(query_plan_integrity.get("samples")))[:5]
    missing_evidence_role_counts = _count_mapping(
        query_plan_integrity.get("missing_evidence_role_query_family_counts")
    )
    return {
        "schema_version": "query_plan_gap_breakdown.v1",
        "plan_count": _positive_int(query_plan_integrity.get("plan_count")) or 0,
        "plan_gap_case_count": (
            _positive_int(query_plan_integrity.get("plan_gap_case_count")) or 0
        ),
        "missing_recommended_role_family_total": (
            _positive_int(
                query_plan_integrity.get(
                    "missing_recommended_role_family_total"
                )
            )
            or 0
        ),
        "dropped_query_count": (
            _positive_int(query_plan_integrity.get("dropped_query_count")) or 0
        ),
        "fanout_limit_hit_count": (
            _positive_int(query_plan_integrity.get("fanout_limit_hit_count")) or 0
        ),
        "type_limit_hit_count": (
            _positive_int(query_plan_integrity.get("type_limit_hit_count")) or 0
        ),
        "empty_query_candidate_count": (
            _positive_int(query_plan_integrity.get("empty_query_candidate_count"))
            or 0
        ),
        "gap_reason_counts": _count_mapping(
            query_plan_integrity.get("gap_reason_counts")
        ),
        "missing_recommended_role_family_counts": _count_mapping(
            query_plan_integrity.get("missing_recommended_role_family_counts")
        ),
        "missing_evidence_role_query_family_total": (
            _positive_int(
                query_plan_integrity.get(
                    "missing_evidence_role_query_family_total"
                )
            )
            or 0
        ),
        "required_evidence_role_counts": _count_mapping(
            query_plan_integrity.get("required_evidence_role_counts")
        ),
        "missing_evidence_role_query_family_counts": missing_evidence_role_counts,
        "missing_evidence_role_query_family_details": (
            _missing_evidence_role_query_family_details(
                missing_evidence_role_counts,
                samples=samples,
            )
        ),
        "dropped_role_family_counts": _count_mapping(
            query_plan_integrity.get("dropped_role_family_counts")
        ),
        "selected_role_family_counts": _count_mapping(
            query_plan_integrity.get("selected_role_family_counts")
        ),
        "dropped_type_limit_role_counts": _count_mapping(
            query_plan_integrity.get("dropped_type_limit_role_counts")
        ),
        "replaced_type_limit_role_counts": _count_mapping(
            query_plan_integrity.get("replaced_type_limit_role_counts")
        ),
        "type_limit_replacement_role_counts": _count_mapping(
            query_plan_integrity.get("type_limit_replacement_role_counts")
        ),
        "compact_samples": [
            _compact_query_plan_gap_sample(sample)
            for sample in samples
            if isinstance(sample, Mapping)
        ],
        "samples": samples,
    }


def evidence_role_query_families(role: str) -> tuple[str, ...]:
    if role in _PROFILE_SUPPORT_ROLES:
        return ("relation_compact", "expanded_focus")
    return {
        "primary": ("base_query", "expanded_focus", "relation_compact"),
        "supporting": ("base_query", "expanded_focus", "relation_compact"),
        "bridge": ("multi_hop", "relation_compact", "expanded_focus"),
        "count_support": ("count_support", "expanded_focus"),
        "list_support": ("list_support", "expanded_focus"),
        "value_support": ("value_support", "expanded_focus"),
        "temporal_support": ("temporal_support", "expanded_focus"),
        "location_support": (
            "location_support",
            "relation_compact",
            "expanded_focus",
        ),
        "causal_support": ("multi_hop", "relation_compact", "expanded_focus"),
        "communication_support": ("relation_compact", "expanded_focus"),
        "event_support": ("relation_compact", "expanded_focus"),
        "exchange_support": ("relation_compact", "expanded_focus"),
        "emotion_response_support": ("relation_compact", "expanded_focus"),
        "symbolic_meaning_support": ("relation_compact", "expanded_focus"),
        "inference_support": ("relation_compact", "expanded_focus", "base_query"),
        "preference_support": ("relation_compact", "expanded_focus", "base_query"),
        "visual_support": ("visual_support", "expanded_focus", "relation_compact"),
        "contrast": ("contrast_support", "relation_compact", "expanded_focus"),
        "entity_disambiguation": (
            "base_query",
            "expanded_focus",
            "relation_compact",
        ),
    }.get(role, ())


def _missing_evidence_role_query_family_details(
    missing_evidence_role_counts: Mapping[str, int],
    *,
    samples: Sequence[object],
) -> dict[str, dict[str, object]]:
    details: dict[str, dict[str, object]] = {}
    for role, count in sorted(missing_evidence_role_counts.items()):
        accepted_families = evidence_role_query_families(role)
        matching_samples = [
            sample
            for sample in samples
            if isinstance(sample, Mapping)
            and role in _str_tuple(sample.get("missing_evidence_role_query_families"))
        ]
        details[role] = {
            "role_family": role,
            "role_family_label": _role_family_label(role),
            "impact_count": count,
            "accepted_query_families": list(accepted_families),
            "accepted_query_family_labels": [
                _role_family_label(family) for family in accepted_families
            ],
            "action": _missing_evidence_role_query_family_action(
                role,
                accepted_query_families=accepted_families,
            ),
            "sample_case_ids": _sample_case_ids(matching_samples),
        }
    return details


def _compact_query_plan_gap_sample(sample: Mapping[str, object]) -> dict[str, object]:
    compact: dict[str, object] = {
        "case_id": str(sample.get("case_id") or ""),
        "group": str(sample.get("group") or ""),
    }
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
        values = _str_tuple(sample.get(key))
        if values:
            compact[key] = list(values[:5])
    for key in ("selected_query_count", "dropped_query_count"):
        value = _positive_int(sample.get(key)) or 0
        if value:
            compact[key] = value
    for key in ("fanout_limit_hit", "type_limit_hit"):
        if sample.get(key) is True:
            compact[key] = True
    empty_count = _positive_int(sample.get("empty_query_candidate_count")) or 0
    if empty_count:
        compact["empty_query_candidate_count"] = empty_count
    return compact


def _sample_case_ids(samples: Sequence[object]) -> list[str]:
    case_ids: list[str] = []
    for sample in samples:
        if not isinstance(sample, Mapping):
            continue
        case_id = str(sample.get("case_id") or "").strip()
        if case_id and case_id not in case_ids:
            case_ids.append(case_id)
        if len(case_ids) >= 5:
            break
    return case_ids


def _missing_evidence_role_query_family_action(
    role: str,
    *,
    accepted_query_families: Sequence[str],
) -> str:
    role_label = _role_family_label(role)
    if accepted_query_families:
        family_text = _family_text(accepted_query_families)
        return (
            f"Add query-plan coverage for the {role_label} role family "
            f"using {family_text} queries."
        )
    return (
        f"Add query-plan coverage for the {role_label} role family or map it "
        "to an accepted query family."
    )


def _family_text(families: Sequence[str]) -> str:
    labels = [_role_family_label(family) for family in families if family]
    if not labels:
        return "accepted role-family"
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} or {labels[1]}"
    return f"{', '.join(labels[:-1])}, or {labels[-1]}"


def _role_family_label(family: str) -> str:
    return str(family).strip().replace("_", " ")
