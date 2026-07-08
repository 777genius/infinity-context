"""Answer-context support gap summaries for memory comparison diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite

from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_low_answerability as _is_measured_low_answerability,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_weak_source_locality as _is_measured_weak_source_locality,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    mapping as _mapping,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)
from infinity_context_server.memory_comparison_quality_accessors import (
    ratio as _ratio,
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
from infinity_context_server.memory_comparison_source_identity import (
    safe_item_id_for_output as _safe_item_id_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_identity_ref as _canonical_safe_source_identity_ref,
)

_MAX_SAMPLE_SOURCE_IDENTITY_REFS = 8
_MAX_SAMPLE_SOURCE_IDENTITY_ITEMS = 5


def answer_context_support_gap_summary(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    context_count = 0
    support_gap_context_count = 0
    missing_answer_context_count = 0
    unsupported_answer_context_count = 0
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    missing_required_role_counts: Counter[str] = Counter()
    risk_reason_counts: Counter[str] = Counter()
    samples: list[dict[str, object]] = []
    availability_gap_samples: list[dict[str, object]] = []

    for item in items:
        for cutoff, raw_payload in _cutoff_payloads(item):
            availability_gap_reason = _answer_context_availability_gap_reason(
                raw_payload
            )
            if availability_gap_reason:
                if availability_gap_reason == "missing_answer_context":
                    missing_answer_context_count += 1
                else:
                    unsupported_answer_context_count += 1
                if len(availability_gap_samples) < 10:
                    availability_gap_samples.append(
                        _availability_gap_sample(
                            item,
                            cutoff=cutoff,
                            gap_reason=availability_gap_reason,
                        )
                    )
                continue

            context = _mapping(_mapping(raw_payload).get("answer_context"))
            context_count += 1
            gap_reasons = _support_gap_reasons(context)
            if not gap_reasons:
                continue

            support_gap_context_count += 1
            reason_counts.update(gap_reasons)
            source = str(context.get("source") or "unknown").strip() or "unknown"
            source_counts[source] += 1
            missing_required_roles = _str_tuple(context.get("missing_required_roles"))
            missing_required_role_counts.update(missing_required_roles)
            risk_reasons = _str_tuple(context.get("risk_reason_codes"))
            risk_reason_counts.update(risk_reasons)

            if len(samples) < 10:
                samples.append(
                    _support_gap_sample(
                        item,
                        cutoff=cutoff,
                        context=context,
                        gap_reasons=gap_reasons,
                        source=source,
                        missing_required_roles=missing_required_roles,
                        risk_reasons=risk_reasons,
                    )
                )

    return {
        "schema_version": "answer_context_support_gaps.v1",
        "expected_context_count": (
            context_count
            + missing_answer_context_count
            + unsupported_answer_context_count
        ),
        "context_count": context_count,
        "support_gap_context_count": support_gap_context_count,
        "support_gap_context_rate": _ratio(support_gap_context_count, context_count),
        "answer_context_availability_gap_count": (
            missing_answer_context_count + unsupported_answer_context_count
        ),
        "missing_answer_context_count": missing_answer_context_count,
        "unsupported_answer_context_count": unsupported_answer_context_count,
        "gap_reason_counts": _top_counts(reason_counts),
        "source_counts": _top_counts(source_counts),
        "missing_required_role_counts": _top_counts(missing_required_role_counts),
        "risk_reason_counts": _top_counts(risk_reason_counts),
        "samples": samples,
        "availability_gap_samples": availability_gap_samples,
    }


def _cutoff_payloads(item: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
    payloads: list[tuple[str, object]] = []
    for cutoff, payload in _mapping(item.get("cutoff_results")).items():
        payloads.append((str(cutoff), payload))
    return tuple(
        sorted(
            payloads,
            key=lambda pair: (
                _positive_int(pair[0]) or 999999,
                pair[0],
            ),
        )
    )


def _answer_context_availability_gap_reason(raw_payload: object) -> str:
    if not isinstance(raw_payload, Mapping):
        return "unsupported_answer_context"
    if "answer_context" not in raw_payload:
        return "missing_answer_context"
    raw_context = raw_payload.get("answer_context")
    if not isinstance(raw_context, Mapping):
        return "unsupported_answer_context"
    if not raw_context:
        return "missing_answer_context"
    return ""


def _support_gap_reasons(context: Mapping[str, object]) -> tuple[str, ...]:
    flags = list(_str_tuple(context.get("inspection_flags")))
    source = str(context.get("source") or "").strip()
    fallback_reason = str(context.get("fallback_reason") or "").strip()
    memory_count = _positive_int(context.get("memory_count")) or 0
    source_ref_item_count = _positive_int(context.get("source_ref_item_count")) or 0
    source_identity_item_count = (
        _positive_int(context.get("source_identity_item_count")) or 0
    )
    source_refless_item_count = (
        _positive_int(context.get("source_refless_item_count")) or 0
    )
    source_grounded_item_count = max(source_ref_item_count, source_identity_item_count)
    inferred_ungrounded_item_count = (
        max(0, memory_count - source_grounded_item_count)
        if memory_count > 0
        else 0
    )
    explicit_refless_ungrounded_item_count = max(
        0,
        source_refless_item_count - source_identity_item_count,
    )
    source_ungrounded_item_count = max(
        inferred_ungrounded_item_count,
        explicit_refless_ungrounded_item_count,
    )

    if (
        (source and source != "evidence_bundle") or fallback_reason
    ) and "retrieval_slice_fallback" not in flags:
        flags.append("retrieval_slice_fallback")
    if (
        memory_count > 0
        and source_grounded_item_count <= 0
        and "missing_context_source_refs" not in flags
    ):
        flags.append("missing_context_source_refs")
    elif (
        source_ungrounded_item_count > 0
        and "partial_context_source_refs" not in flags
    ):
        flags.append("partial_context_source_refs")
    if (
        _str_tuple(context.get("missing_required_roles"))
        and "missing_required_roles" not in flags
    ):
        flags.append("missing_required_roles")
    if (
        _has_low_bundle_confidence(context)
        and "low_bundle_confidence" not in flags
    ):
        flags.append("low_bundle_confidence")
    if _has_weak_bundle_source_support(context):
        flags.append("weak_bundle_source_support")
    if _positive_int(context.get("backfilled_low_answerability_count")):
        flags.append("low_answerability_backfill")
    if _positive_int(context.get("backfilled_weak_source_locality_count")):
        flags.append("weak_source_locality_backfill")
    if _is_measured_low_answerability(
        context.get("avg_measured_answerability_score")
    ):
        flags.append("low_context_answerability")
    if _is_measured_weak_source_locality(
        context.get("avg_measured_source_locality_score")
    ):
        flags.append("weak_context_source_locality")
    if _positive_int(context.get("skipped_redundant_risky_backfill_count")):
        flags.append("skipped_redundant_risky_backfill")
    if _positive_int(context.get("skipped_redundant_source_backfill_count")):
        flags.append("skipped_redundant_source_backfill")
    if _positive_int(context.get("skipped_redundant_role_backfill_count")):
        flags.append("skipped_redundant_role_backfill")
    if _positive_int(context.get("skipped_target_limit_backfill_count")):
        flags.append("skipped_target_limit_backfill")
    if _positive_int(context.get("skipped_duplicate_source_bundle_item_count")):
        flags.append("skipped_duplicate_source_bundle_item")
    if _positive_int(context.get("skipped_noisy_overlap_bundle_item_count")):
        flags.append("skipped_noisy_overlap_bundle_item")
    return tuple(dict.fromkeys(flags))


def _has_low_bundle_confidence(context: Mapping[str, object]) -> bool:
    confidence_band = str(context.get("bundle_confidence_band") or "").strip().lower()
    return (
        confidence_band == "low"
        or 0 < _metric_scalar(context.get("bundle_confidence_score")) < 0.55
    )


def _has_weak_bundle_source_support(context: Mapping[str, object]) -> bool:
    if str(context.get("source") or "").strip() != "evidence_bundle":
        return False
    if not _has_bundle_quality_signal(context):
        return False
    return (
        (_positive_int(context.get("bundle_source_ref_support_item_count")) or 0) <= 0
        and (
            _positive_int(context.get("bundle_source_identity_support_item_count"))
            or 0
        )
        <= 0
    )


def _has_bundle_quality_signal(context: Mapping[str, object]) -> bool:
    return any(
        (
            _metric_scalar(context.get("bundle_confidence_score")) > 0,
            bool(str(context.get("bundle_confidence_band") or "").strip()),
            _positive_int(context.get("bundle_bridge_count")) is not None,
            _positive_int(context.get("bundle_source_type_diversity")) is not None,
            _positive_int(context.get("bundle_retrieval_source_diversity")) is not None,
            _positive_int(context.get("bundle_source_type_support_diversity"))
            is not None,
            _positive_int(context.get("bundle_retrieval_source_support_diversity"))
            is not None,
        )
    )


def _support_gap_sample(
    item: Mapping[str, object],
    *,
    cutoff: str,
    context: Mapping[str, object],
    gap_reasons: Sequence[str],
    source: str,
    missing_required_roles: Sequence[str],
    risk_reasons: Sequence[str],
) -> dict[str, object]:
    sample: dict[str, object] = {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "cutoff": cutoff,
        "source": source,
        "gap_reasons": list(gap_reasons),
        "memory_count": _positive_int(context.get("memory_count")) or 0,
        "source_ref_item_count": (
            _positive_int(context.get("source_ref_item_count")) or 0
        ),
        "source_refless_item_count": (
            _positive_int(context.get("source_refless_item_count")) or 0
        ),
        "backfilled_retrieval_item_count": (
            _positive_int(context.get("backfilled_retrieval_item_count")) or 0
        ),
        "skipped_redundant_risky_backfill_count": (
            _positive_int(context.get("skipped_redundant_risky_backfill_count")) or 0
        ),
        "avg_measured_answerability_score": round(
            _metric_scalar(context.get("avg_measured_answerability_score")),
            6,
        ),
        "avg_measured_source_locality_score": round(
            _metric_scalar(context.get("avg_measured_source_locality_score")),
            6,
        ),
    }
    skipped_duplicate_source_bundle_item_count = (
        _positive_int(context.get("skipped_duplicate_source_bundle_item_count")) or 0
    )
    if skipped_duplicate_source_bundle_item_count:
        sample["skipped_duplicate_source_bundle_item_count"] = (
            skipped_duplicate_source_bundle_item_count
        )
    skipped_noisy_overlap_bundle_item_count = (
        _positive_int(context.get("skipped_noisy_overlap_bundle_item_count")) or 0
    )
    if skipped_noisy_overlap_bundle_item_count:
        sample["skipped_noisy_overlap_bundle_item_count"] = (
            skipped_noisy_overlap_bundle_item_count
        )
    for key in (
        "skipped_redundant_source_backfill_count",
        "skipped_redundant_role_backfill_count",
        "skipped_target_limit_backfill_count",
    ):
        value = _positive_int(context.get(key)) or 0
        if value:
            sample[key] = value
    fallback_reason = str(context.get("fallback_reason") or "").strip()
    if fallback_reason:
        sample["fallback_reason"] = fallback_reason
    sample.update(_answer_context_sample_identity(context))
    if missing_required_roles:
        sample["missing_required_roles"] = list(missing_required_roles)
    if risk_reasons:
        sample["risk_reason_codes"] = list(risk_reasons)
    return sample


def _availability_gap_sample(
    item: Mapping[str, object],
    *,
    cutoff: str,
    gap_reason: str,
) -> dict[str, object]:
    source = "missing" if gap_reason == "missing_answer_context" else "unsupported"
    return {
        "case_id": str(item.get("case_id") or ""),
        "group": str(item.get("group") or ""),
        "cutoff": cutoff,
        "source": source,
        "gap_reasons": [gap_reason],
    }


def _answer_context_sample_identity(context: Mapping[str, object]) -> dict[str, object]:
    item_ids = tuple(
        item_id
        for raw_item_id in _str_tuple(context.get("item_ids"))
        for item_id in (_safe_item_id_for_output(raw_item_id),)
        if item_id
    )[:8]
    retrieval_orders = tuple(
        order
        for raw_order in _sequence(context.get("retrieval_orders"))
        for order in (_positive_int(raw_order),)
        if order is not None
    )[:8]
    identity: dict[str, object] = {}
    if item_ids:
        identity["item_ids"] = list(item_ids)
    if retrieval_orders:
        identity["retrieval_orders"] = list(retrieval_orders)
    source_identity_refs = _safe_source_identity_refs(context.get("source_identity_refs"))
    source_identity_ref_count = _positive_int(context.get("source_identity_ref_count"))
    if source_identity_ref_count is not None or source_identity_refs:
        identity["source_identity_ref_count"] = (
            source_identity_ref_count or len(source_identity_refs)
        )
    source_identity_item_count = _positive_int(context.get("source_identity_item_count"))
    if source_identity_item_count is not None:
        identity["source_identity_item_count"] = source_identity_item_count
    if source_identity_refs:
        identity["source_identity_refs"] = list(source_identity_refs)
    source_identity_items = _safe_source_identity_items(
        context.get("source_identity_items")
    )
    if source_identity_items:
        identity["source_identity_items"] = list(source_identity_items)
    return identity


def _safe_source_identity_items(value: object) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    for raw_item in _sequence(value):
        item = _mapping(raw_item)
        if not item:
            continue
        compact: dict[str, object] = {}
        source_identity_refs = _safe_source_identity_refs(
            item.get("source_identity_refs")
        )
        if source_identity_refs:
            compact["source_identity_refs"] = list(source_identity_refs)
        item_id = _safe_item_id_for_output(item.get("item_id"))
        if item_id:
            compact["item_id"] = item_id
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is not None:
            compact["retrieval_order"] = retrieval_order
        if compact:
            items.append(compact)
        if len(items) >= _MAX_SAMPLE_SOURCE_IDENTITY_ITEMS:
            break
    return tuple(items)


def _safe_source_identity_refs(value: object) -> tuple[str, ...]:
    refs = tuple(
        dict.fromkeys(
            ref
            for raw_ref in _sequence(value)
            for ref in (_safe_source_identity_ref(raw_ref),)
            if ref
        )
    )
    return refs[:_MAX_SAMPLE_SOURCE_IDENTITY_REFS]


def _safe_source_identity_ref(value: object) -> str | None:
    return _canonical_safe_source_identity_ref(value)


def _metric_scalar(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return parsed if isfinite(parsed) else 0.0
