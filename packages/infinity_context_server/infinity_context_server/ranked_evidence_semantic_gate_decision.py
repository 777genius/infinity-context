"""Fail-closed verdict policy for ranked-evidence semantic gate metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from infinity_context_server.ranked_evidence_answer_support import (
    ranked_evidence_answer_support_metrics_contract_valid,
)
from infinity_context_server.ranked_evidence_semantic_metrics import (
    ranked_evidence_semantic_metrics_contract_valid,
)

RankedEvidenceSemanticGateFailureReason = Literal[
    "invalid_semantic_gate_cutoffs",
    "malformed_answer_support_metrics",
    "malformed_semantic_metrics",
    "semantic_answer_support_miss",
    "semantic_cutoff_crowd_out",
    "semantic_metrics_mismatch",
    "semantic_reference_miss",
]

_MAX_CUTOFFS = 8
_MAX_CUTOFF = 200


@dataclass(frozen=True, slots=True)
class RankedEvidenceSemanticGateDecision:
    """Immutable verdict derived without rewriting either raw metric payload."""

    ok: bool
    failure_reason: RankedEvidenceSemanticGateFailureReason | None


def ranked_evidence_semantic_gate_decision(
    semantic_metrics: object,
    answer_support: object,
    *,
    expected_cutoffs: Sequence[int],
    reference_cutoff: int,
) -> RankedEvidenceSemanticGateDecision:
    """Decide whether raw semantic evidence satisfies the gate.

    Exact-reference misses are not erased. They may only be accepted by the
    verdict when complete answer-unit support is independently observed at the
    exact reference cutoff. Every cutoff with reference-relative crowd-out
    requires complete support at that same cutoff.
    """

    cutoffs = _validated_cutoffs(
        expected_cutoffs,
        reference_cutoff=reference_cutoff,
    )
    if cutoffs is None:
        return _failure("invalid_semantic_gate_cutoffs")
    if not ranked_evidence_semantic_metrics_contract_valid(
        semantic_metrics,
        expected_cutoffs=cutoffs,
        reference_cutoff=reference_cutoff,
    ):
        return _failure("malformed_semantic_metrics")
    if not _answer_support_contract_valid(answer_support, expected_cutoffs=cutoffs):
        return _failure("malformed_answer_support_metrics")

    assert isinstance(semantic_metrics, Mapping)
    assert isinstance(answer_support, Mapping)
    if semantic_metrics["matches"] is not True:
        return _failure("semantic_metrics_mismatch")

    complete_cutoffs = _complete_answer_support_cutoffs(answer_support)
    retrieval_miss_count = semantic_metrics["retrieval_miss_ref_count"]
    if retrieval_miss_count > 0 and reference_cutoff not in complete_cutoffs:
        return _failure("semantic_reference_miss")

    crowded_cutoffs = _crowded_cutoffs(semantic_metrics)
    unsupported_crowd_out = tuple(
        cutoff for cutoff in crowded_cutoffs if cutoff not in complete_cutoffs
    )
    if unsupported_crowd_out:
        if answer_support["applicable"] is True:
            return _failure("semantic_answer_support_miss")
        return _failure("semantic_cutoff_crowd_out")

    return RankedEvidenceSemanticGateDecision(ok=True, failure_reason=None)


def _answer_support_contract_valid(
    answer_support: object,
    *,
    expected_cutoffs: tuple[int, ...],
) -> bool:
    if not ranked_evidence_answer_support_metrics_contract_valid(answer_support):
        return False
    assert isinstance(answer_support, Mapping)
    if answer_support["applicable"] is not True:
        return True
    return ranked_evidence_answer_support_metrics_contract_valid(
        answer_support,
        expected_cutoffs=expected_cutoffs,
    )


def _complete_answer_support_cutoffs(
    answer_support: Mapping[object, object],
) -> frozenset[int]:
    if answer_support["applicable"] is not True:
        return frozenset()
    cutoff_metrics = answer_support["cutoffs"]
    assert isinstance(cutoff_metrics, list)
    return frozenset(
        metric["cutoff"]
        for metric in cutoff_metrics
        if isinstance(metric, Mapping) and metric["complete"] is True
    )


def _crowded_cutoffs(semantic_metrics: Mapping[object, object]) -> tuple[int, ...]:
    cutoff_metrics = semantic_metrics["cutoffs"]
    assert isinstance(cutoff_metrics, list)
    return tuple(
        metric["cutoff"]
        for metric in cutoff_metrics
        if isinstance(metric, Mapping) and metric["crowd_out_ref_count"] > 0
    )


def _validated_cutoffs(
    value: object,
    *,
    reference_cutoff: object,
) -> tuple[int, ...] | None:
    if (
        not _is_sequence(value)
        or not value
        or len(value) > _MAX_CUTOFFS
        or not _is_exact_positive_int(reference_cutoff)
    ):
        return None
    cutoffs = tuple(value)
    if (
        any(not _is_exact_positive_int(cutoff) or cutoff > _MAX_CUTOFF for cutoff in cutoffs)
        or any(left >= right for left, right in zip(cutoffs, cutoffs[1:], strict=False))
        or cutoffs[-1] != reference_cutoff
    ):
        return None
    return cutoffs


def _failure(
    reason: RankedEvidenceSemanticGateFailureReason,
) -> RankedEvidenceSemanticGateDecision:
    return RankedEvidenceSemanticGateDecision(ok=False, failure_reason=reason)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_exact_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
