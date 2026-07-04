"""Answer-context support gap summaries for memory comparison diagnostics."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence

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

_SAFE_SOURCE_IDENTITY_REF_RE = re.compile(
    r"^(?:(?P<turn_prefix>source_turn_refs):(?P<turn_ref>D\d+:\d+)|"
    r"(?P<session_prefix>source_session_turn_refs):(?P<session>session_\d+):"
    r"(?P<session_turn_ref>D\d+:\d+))$",
    re.IGNORECASE,
)
_MAX_SAMPLE_SOURCE_IDENTITY_REFS = 8


def answer_context_support_gap_summary(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    context_count = 0
    support_gap_context_count = 0
    reason_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    missing_required_role_counts: Counter[str] = Counter()
    risk_reason_counts: Counter[str] = Counter()
    samples: list[dict[str, object]] = []

    for item in items:
        for cutoff, context in _answer_contexts(item):
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
        "context_count": context_count,
        "support_gap_context_count": support_gap_context_count,
        "support_gap_context_rate": _ratio(support_gap_context_count, context_count),
        "gap_reason_counts": _top_counts(reason_counts),
        "source_counts": _top_counts(source_counts),
        "missing_required_role_counts": _top_counts(missing_required_role_counts),
        "risk_reason_counts": _top_counts(risk_reason_counts),
        "samples": samples,
    }


def _answer_contexts(
    item: Mapping[str, object],
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    contexts: list[tuple[str, Mapping[str, object]]] = []
    for cutoff, payload in _mapping(item.get("cutoff_results")).items():
        context = _mapping(_mapping(payload).get("answer_context"))
        if context:
            contexts.append((str(cutoff), context))
    return tuple(
        sorted(
            contexts,
            key=lambda pair: (
                _positive_int(pair[0]) or 999999,
                pair[0],
            ),
        )
    )


def _support_gap_reasons(context: Mapping[str, object]) -> tuple[str, ...]:
    flags = list(_str_tuple(context.get("inspection_flags")))
    source = str(context.get("source") or "").strip()
    fallback_reason = str(context.get("fallback_reason") or "").strip()
    memory_count = _positive_int(context.get("memory_count")) or 0
    source_ref_item_count = _positive_int(context.get("source_ref_item_count")) or 0
    source_refless_item_count = (
        _positive_int(context.get("source_refless_item_count")) or 0
    )

    if (
        (source and source != "evidence_bundle") or fallback_reason
    ) and "retrieval_slice_fallback" not in flags:
        flags.append("retrieval_slice_fallback")
    if (
        memory_count > 0
        and source_ref_item_count <= 0
        and "missing_context_source_refs" not in flags
    ):
        flags.append("missing_context_source_refs")
    elif (
        source_refless_item_count > 0
        and "partial_context_source_refs" not in flags
    ):
        flags.append("partial_context_source_refs")
    if (
        _str_tuple(context.get("missing_required_roles"))
        and "missing_required_roles" not in flags
    ):
        flags.append("missing_required_roles")
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
    if _positive_int(context.get("skipped_duplicate_source_bundle_item_count")):
        flags.append("skipped_duplicate_source_bundle_item")
    if _positive_int(context.get("skipped_noisy_overlap_bundle_item_count")):
        flags.append("skipped_noisy_overlap_bundle_item")
    return tuple(dict.fromkeys(flags))


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
    fallback_reason = str(context.get("fallback_reason") or "").strip()
    if fallback_reason:
        sample["fallback_reason"] = fallback_reason
    sample.update(_answer_context_sample_identity(context))
    if missing_required_roles:
        sample["missing_required_roles"] = list(missing_required_roles)
    if risk_reasons:
        sample["risk_reason_codes"] = list(risk_reasons)
    return sample


def _answer_context_sample_identity(context: Mapping[str, object]) -> dict[str, object]:
    item_ids = _str_tuple(context.get("item_ids"))[:8]
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
    return identity


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


def _metric_scalar(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
