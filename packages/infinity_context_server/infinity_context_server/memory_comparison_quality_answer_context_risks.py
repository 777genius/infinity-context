"""Answer-context risk samples for memory-comparison diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_quality_accessors import (
    positive_int as _positive_int,
)


def answer_context_risk_sample(
    *,
    item: Mapping[str, object],
    cutoff: str,
    source: str,
    context: Mapping[str, object],
    risk_reasons: Sequence[str],
    missing_required_roles: Sequence[str],
) -> dict[str, object]:
    backfilled_count = _positive_int(context.get("backfilled_retrieval_item_count")) or 0
    skipped_bundle_item_count = (
        (_positive_int(context.get("skipped_duplicate_source_bundle_item_count")) or 0)
        + (_positive_int(context.get("skipped_noisy_overlap_bundle_item_count")) or 0)
    )
    skipped_backfill_item_count = (
        (_positive_int(context.get("skipped_redundant_risky_backfill_count")) or 0)
        + (_positive_int(context.get("skipped_redundant_source_backfill_count")) or 0)
        + (_positive_int(context.get("skipped_redundant_role_backfill_count")) or 0)
    )
    fallback_reason = str(context.get("fallback_reason") or "").strip()
    risk_score = (
        len(tuple(risk_reasons))
        + (2 * len(tuple(missing_required_roles)))
        + backfilled_count
        + skipped_bundle_item_count
        + skipped_backfill_item_count
        + (2 if source != "evidence_bundle" else 0)
        + (1 if fallback_reason else 0)
    )
    return {
        "case_id": str(item.get("case_id") or ""),
        "cutoff": cutoff,
        "source": source,
        **({"fallback_reason": fallback_reason} if fallback_reason else {}),
        "memory_count": _positive_int(context.get("memory_count")) or 0,
        "risk_score": risk_score,
        "risk_reason_codes": list(risk_reasons),
        **(
            {"missing_required_roles": list(missing_required_roles)}
            if missing_required_roles
            else {}
        ),
        "backfilled_retrieval_item_count": backfilled_count,
        "skipped_bundle_item_count": skipped_bundle_item_count,
        "skipped_redundant_backfill_item_count": skipped_backfill_item_count,
    }


def ranked_answer_context_risk_samples(
    samples: Sequence[Mapping[str, object]],
    *,
    limit: int = 10,
) -> list[dict[str, object]]:
    return [
        dict(sample)
        for sample in sorted(
            samples,
            key=lambda sample: (
                -(_positive_int(sample.get("risk_score")) or 0),
                str(sample.get("case_id") or ""),
                str(sample.get("cutoff") or ""),
            ),
        )[:limit]
    ]
