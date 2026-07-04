"""Answer-context risk reason helpers for memory comparison diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_candidate_risks import (
    memory_has_broad_summary,
    memory_has_conflict_or_stale,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory

_RISK_METADATA_KEY = "answer_context_risk_reason_codes"


def is_measured_low_answerability(value: object) -> bool:
    score = _metric_scalar(value)
    return 0 < score < 0.55


def is_measured_weak_source_locality(value: object) -> bool:
    score = _metric_scalar(value)
    return 0 < score < 0.45


def backfill_risk_reason_codes(
    memory: RetrievedMemory,
    features: Mapping[str, object],
) -> tuple[str, ...]:
    codes = ["risk:retrieval_backfill"]
    if memory_has_broad_summary(memory, features):
        codes.append("risk:backfilled_broad_summary")
    if memory_has_conflict_or_stale(memory, features):
        codes.append("risk:backfilled_conflict_or_stale")
    if is_measured_low_answerability(features.get("answerability_score")):
        codes.append("risk:backfilled_low_answerability")
    if is_measured_weak_source_locality(features.get("source_locality_score")):
        codes.append("risk:backfilled_weak_source_locality")
    return tuple(codes)


def context_risk_reason_codes(
    *,
    bundle_risk_reason_codes: Sequence[str],
    skipped_duplicate_source_bundle_item_count: int,
    skipped_noisy_overlap_bundle_item_count: int,
    backfilled_retrieval_item_count: int,
    skipped_redundant_risky_backfill_count: int,
    skipped_redundant_source_backfill_count: int,
    skipped_redundant_role_backfill_count: int,
    backfill_risk_stats: Mapping[str, object],
    memory_metadata: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    return merge_risk_reason_codes(
        bundle_risk_reason_codes,
        _positive_count_codes(
            (
                (
                    skipped_duplicate_source_bundle_item_count,
                    "risk:skipped_duplicate_source_bundle_item",
                ),
                (
                    skipped_noisy_overlap_bundle_item_count,
                    "risk:skipped_noisy_overlap_bundle_item",
                ),
                (backfilled_retrieval_item_count, "risk:retrieval_backfill"),
                (
                    _positive_count(
                        backfill_risk_stats,
                        "backfilled_broad_summary_count",
                    ),
                    "risk:backfilled_broad_summary",
                ),
                (
                    _positive_count(
                        backfill_risk_stats,
                        "backfilled_conflict_or_stale_count",
                    ),
                    "risk:backfilled_conflict_or_stale",
                ),
                (
                    _positive_count(
                        backfill_risk_stats,
                        "backfilled_low_answerability_count",
                    ),
                    "risk:backfilled_low_answerability",
                ),
                (
                    _positive_count(
                        backfill_risk_stats,
                        "backfilled_weak_source_locality_count",
                    ),
                    "risk:backfilled_weak_source_locality",
                ),
                (
                    skipped_redundant_risky_backfill_count,
                    "risk:skipped_redundant_risky_backfill",
                ),
                (
                    skipped_redundant_source_backfill_count,
                    "risk:skipped_redundant_source_backfill",
                ),
                (
                    skipped_redundant_role_backfill_count,
                    "risk:skipped_redundant_role_backfill",
                ),
            )
        ),
        *(
            _string_tuple(metadata.get(_RISK_METADATA_KEY))
            for metadata in memory_metadata
        ),
    )


def add_answer_context_risk_codes(
    metadata: dict[str, object],
    codes: Sequence[str],
) -> None:
    merged = merge_risk_reason_codes(
        _string_tuple(metadata.get(_RISK_METADATA_KEY)),
        codes,
    )
    if merged:
        metadata[_RISK_METADATA_KEY] = merged


def merge_risk_reason_codes(*sources: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            code
            for source in sources
            for code in _string_tuple(source)
        )
    )


def _positive_count_codes(pairs: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    return tuple(code for count, code in pairs if count > 0)


def _positive_count(values: Mapping[str, object], key: str) -> int:
    return _positive_int(values.get(key)) or 0


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _metric_scalar(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(
        str(item).strip()
        for item in value
        if str(item).strip()
    )
