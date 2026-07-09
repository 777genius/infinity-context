"""Selected evidence weakness diagnostics for memory comparison reports."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from math import isfinite

from infinity_context_core.application.sensitive_text import redact_sensitive_text

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
from infinity_context_server.memory_comparison_source_identity import (
    looks_like_raw_source_ref as _looks_like_raw_source_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_item_id_for_output as _safe_item_id_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output as _safe_source_refs_for_output,
)

_SELECTED_WEAKNESS_SAMPLE_LIMIT = 10
_SELECTED_WEAKNESS_REASON_LIMIT = 6
_SELECTED_WEAKNESS_QUERY_ROLE_LIMIT = 6
_SELECTED_WEAKNESS_SOURCE_REF_LIMIT = 6
_SELECTED_WEAKNESS_CATEGORY_SOURCE_REF_LIMIT = 5
_SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT = 5
_SELECTED_WEAKNESS_TEXT_VALUE_LIMIT = 120
_BROAD_SUMMARY_RISK_CODES = frozenset(
    {"risk:broad_summary", "risk:backfilled_broad_summary"}
)
_CONFLICT_OR_STALE_RISK_CODES = frozenset(
    {"risk:conflict_or_stale", "risk:backfilled_conflict_or_stale"}
)


def selected_evidence_weakness_breakdown(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    low_answerability_case_ids: set[str] = set()
    weak_source_locality_case_ids: set[str] = set()
    broad_summary_case_ids: set[str] = set()
    conflict_or_stale_case_ids: set[str] = set()
    group_case_ids: dict[str, set[str]] = defaultdict(set)
    reason_group_counts: dict[str, Counter[str]] = defaultdict(Counter)
    reason_role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    weak_support_role_reason_counts: dict[str, Counter[str]] = defaultdict(Counter)
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
            if _has_selected_broad_summary_risk(
                bundle_item,
                planner_reasons=planner_reasons,
                risk_reasons=risk_reasons,
            ):
                broad_summary_item_count += 1
                if case_id:
                    broad_summary_case_ids.add(case_id)
                reasons.append("selected_broad_summary")
            if _has_selected_conflict_or_stale_risk(
                bundle_item,
                planner_reasons=planner_reasons,
                risk_reasons=risk_reasons,
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
            for reason in reasons:
                reason_role_counts[reason][role] += 1
                if _is_support_role(role):
                    weak_support_role_reason_counts[role][reason] += 1
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
                low_answerability_samples.append(
                    _selected_evidence_weakness_category_sample(sample)
                )
            if (
                "selected_weak_source_locality" in reasons
                and len(weak_source_locality_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                weak_source_locality_samples.append(
                    _selected_evidence_weakness_category_sample(sample)
                )
            if (
                "selected_broad_summary" in reasons
                and len(broad_summary_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                broad_summary_samples.append(
                    _selected_evidence_weakness_category_sample(sample)
                )
            if (
                "selected_conflict_or_stale" in reasons
                and len(conflict_or_stale_samples)
                < _SELECTED_WEAKNESS_CATEGORY_SAMPLE_LIMIT
            ):
                conflict_or_stale_samples.append(
                    _selected_evidence_weakness_category_sample(sample)
                )

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
        "reason_role_counts": {
            reason: dict(sorted(role_counts.items()))
            for reason, role_counts in sorted(reason_role_counts.items())
        },
        "weak_support_role_reason_counts": {
            role: dict(sorted(reason_counts.items()))
            for role, reason_counts in sorted(weak_support_role_reason_counts.items())
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
    explicit_source_refs = _explicit_selected_source_ref_values(bundle_item)
    source_ref_count = len(_compact_sample_values(explicit_source_refs or source_refs))
    compact_query_roles = _compact_sample_values(query_roles)
    compact_source_refs = _safe_selected_source_refs(
        source_refs,
        explicit_values=explicit_source_refs,
    )
    sample: dict[str, object] = {
        "case_id": _compact_sample_text(case_id),
        "group": _compact_sample_text(group),
        "item_id": _compact_sample_text(
            _safe_item_id_for_output(
                bundle_item.get("id") or bundle_item.get("item_id")
            )
        ),
        "role": _compact_sample_text(role),
        "query_roles": _sample_value_list(compact_query_roles)[
            :_SELECTED_WEAKNESS_QUERY_ROLE_LIMIT
        ],
        "query_role_count": len(compact_query_roles),
        "retrieval_order": (
            _positive_int(bundle_item.get("retrieval_order"))
            or _positive_int(bundle_item.get("rank"))
            or 0
        ),
        "reasons": list(reasons),
        "answerability_score": _sample_metric_value(answerability_score),
        "source_locality_score": _sample_metric_value(source_locality_score),
        "broad_summary": (
            _has_selected_broad_summary_risk(
                bundle_item,
                planner_reasons=planner_reasons,
                risk_reasons=risk_reasons,
            )
        ),
        "conflict_or_stale": (
            _has_selected_conflict_or_stale_risk(
                bundle_item,
                planner_reasons=planner_reasons,
                risk_reasons=risk_reasons,
            )
        ),
        "source_refs": _sample_value_list(compact_source_refs)[
            :_SELECTED_WEAKNESS_SOURCE_REF_LIMIT
        ],
        "source_ref_count": source_ref_count,
    }
    _add_compact_sample_list(
        sample,
        "risk_reason_codes",
        risk_reasons,
        limit=_SELECTED_WEAKNESS_REASON_LIMIT,
        count_key="risk_reason_count",
    )
    _add_compact_sample_list(
        sample,
        "planner_reason_codes",
        planner_reasons,
        limit=_SELECTED_WEAKNESS_REASON_LIMIT,
        count_key="planner_reason_count",
    )
    for key, count_key in (
        ("answerability_reason_codes", "answerability_reason_count"),
        ("source_locality_reason_codes", "source_locality_reason_count"),
        ("retrieval_sources", "retrieval_source_count"),
        ("source_types", "source_type_count"),
        ("relation_categories", "relation_category_count"),
        ("relation_category_hits", "relation_category_hit_count"),
    ):
        _add_compact_sample_list(
            sample,
            key,
            _str_tuple(bundle_item.get(key)),
            limit=_SELECTED_WEAKNESS_REASON_LIMIT,
            count_key=count_key,
        )
    for key in ("source_type", "stale_reason", "conflict_reason"):
        value = _compact_sample_text(str(bundle_item.get(key) or ""))
        if value:
            sample[key] = value
    return sample


def _selected_evidence_weakness_category_sample(
    sample: Mapping[str, object],
) -> dict[str, object]:
    category_sample = dict(sample)
    source_refs = category_sample.get("source_refs")
    if isinstance(source_refs, Sequence) and not isinstance(source_refs, str | bytes):
        category_sample["source_refs"] = list(source_refs)[
            :_SELECTED_WEAKNESS_CATEGORY_SOURCE_REF_LIMIT
        ]
    return category_sample


def _is_support_role(role: str) -> bool:
    role_key = role.strip()
    return role_key in {"bridge", "support", "supporting"} or role_key.endswith(
        "_support"
    )


def _has_selected_broad_summary_risk(
    bundle_item: Mapping[str, object],
    *,
    planner_reasons: Sequence[str],
    risk_reasons: Sequence[str],
) -> bool:
    return (
        bundle_item.get("broad_summary") is True
        or "broad_summary" in planner_reasons
        or bool(_BROAD_SUMMARY_RISK_CODES.intersection(risk_reasons))
    )


def _has_selected_conflict_or_stale_risk(
    bundle_item: Mapping[str, object],
    *,
    planner_reasons: Sequence[str],
    risk_reasons: Sequence[str],
) -> bool:
    return (
        bundle_item.get("conflict_or_stale") is True
        or "conflict_or_stale" in planner_reasons
        or bool(_CONFLICT_OR_STALE_RISK_CODES.intersection(risk_reasons))
    )


def _selected_evidence_risk_reasons(
    *sources: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            stripped
            for source in sources
            for reason in source
            if (stripped := reason.strip()).startswith("risk:")
        )
    )


def _add_compact_sample_list(
    sample: dict[str, object],
    key: str,
    values: Sequence[str],
    *,
    limit: int,
    count_key: str | None = None,
) -> None:
    compact = _compact_sample_values(values)
    if not compact:
        return
    sample[key] = _sample_value_list(compact[:limit])
    if count_key:
        sample[count_key] = len(compact)


def _compact_sample_values(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(stripped for value in values if (stripped := value.strip()))
    )


def _explicit_selected_source_ref_values(
    bundle_item: Mapping[str, object],
) -> tuple[str, ...]:
    refs: list[str] = list(_str_tuple(bundle_item.get("source_refs")))
    refs.extend(_str_tuple(bundle_item.get("source_identity_refs")))
    source_identity_ref = str(bundle_item.get("source_identity_ref") or "").strip()
    if source_identity_ref:
        refs.append(source_identity_ref)
    for key in ("source_ref_dedupe_key", "dedupe_key"):
        value = str(bundle_item.get(key) or "").strip()
        if value.lower().startswith(
            (
                "source_identity:",
                "source_refs:",
                "source_session_turn_refs:",
                "source_turn_refs:",
            )
        ):
            refs.append(value)
    return tuple(refs)


def _safe_selected_source_refs(
    values: Sequence[str],
    *,
    explicit_values: Sequence[str] | None = None,
) -> tuple[str, ...]:
    refs: list[str] = []
    explicit_source_values = values if explicit_values is None else explicit_values
    has_explicit_identity_input = False
    explicit_turn_refs: set[str] = set()
    for raw_ref in explicit_source_values:
        raw_text = str(raw_ref or "").strip()
        raw_lower = raw_text.lower()
        if raw_lower.startswith(("source_session_turn_refs:", "source_turn_refs:")):
            has_explicit_identity_input = True
        if raw_lower.startswith("source_turn_refs:"):
            explicit_turn_refs.update(
                ref.removeprefix("source_turn_refs:")
                for ref in _safe_source_refs_for_output((raw_text,))
                if ref.startswith("source_turn_refs:")
            )
    for raw_ref in values:
        for ref in _safe_selected_source_refs_for_value(raw_ref):
            if ref and ref not in refs:
                refs.append(ref)
    if has_explicit_identity_input:
        refs = _drop_derived_turn_refs_covered_by_session_refs(
            refs,
            explicit_turn_refs=explicit_turn_refs,
        )
    return tuple(refs)


def _drop_derived_turn_refs_covered_by_session_refs(
    refs: Sequence[str],
    *,
    explicit_turn_refs: set[str],
) -> list[str]:
    session_turn_refs = {
        session_ref.split(":", 1)[1]
        for ref in refs
        if ref.startswith("source_session_turn_refs:")
        for session_ref in (ref.removeprefix("source_session_turn_refs:"),)
        if ":" in session_ref
    }
    if not session_turn_refs:
        return list(refs)
    return [
        ref
        for ref in refs
        if not (
            (turn_ref := _selected_turn_ref_identity(ref)) in session_turn_refs
            and turn_ref not in explicit_turn_refs
        )
    ]


def _selected_turn_ref_identity(value: str) -> str:
    if value.startswith("source_turn_refs:"):
        return value.removeprefix("source_turn_refs:")
    if re.fullmatch(r"D\d+[:-]\d+", value, re.IGNORECASE):
        return value
    return ""


def _safe_selected_source_refs_for_value(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    safe_refs = _safe_source_refs_for_output((text,))
    if safe_refs:
        return safe_refs
    if not text or _looks_like_raw_source_ref(text):
        return ()
    return (_compact_sample_text(text),)


def _sample_value_list(values: Sequence[str]) -> list[str]:
    return [
        compact
        for value in values
        if (compact := _compact_sample_text(value))
    ]


def _sample_metric_value(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return round(value, 6)


def _compact_sample_text(value: str) -> str:
    stripped = redact_sensitive_text(value.strip())
    if _looks_like_raw_source_ref(stripped):
        return ""
    if len(stripped) <= _SELECTED_WEAKNESS_TEXT_VALUE_LIMIT:
        return stripped
    return f"{stripped[:_SELECTED_WEAKNESS_TEXT_VALUE_LIMIT - 3]}..."
