"""Gold-safe answer-unit support metrics for ranked activity evidence.

The caller must invoke this policy only after the benchmark response has been
produced.  Expected answer terms are used transiently to derive generic activity
slots and are never included in the returned metrics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infinity_context_core.application import (
    context_ranked_activity_reservation as _activity_policy,
)

SCHEMA_VERSION = "ranked-evidence-answer-support-metrics.v1"

_MAX_CUTOFFS = 8
_MAX_CUTOFF_VALUE = 200
_MAX_EXPECTED_UNITS = 16
_MAX_EXPECTED_TERMS = 16
_MAX_EXPECTED_TERM_CHARS = 512
_MAX_OBSERVATIONS = 2_048
_MAX_OBSERVATIONS_PER_CUTOFF = 256
_MAX_FINGERPRINT_CHARS = 256
_MAX_TEXT_CHARS = 32_768
_MAX_SOURCE_REFS = 64
_MAX_SOURCE_REF_CHARS = 512
_MAX_EVIDENCE_SLOTS = 16

_FALLBACK_REASONS = frozenset(
    {
        "activity_policy_error",
        "ambiguous_expected_unit_slots",
        "expected_unit_overflow",
        "invalid_expected_terms",
        "invalid_observations",
        "invalid_question",
        "non_monotonic_support",
        "unsupported_answer_shape",
        "unsupported_query",
    }
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "applicable",
        "fallback_reason",
        "expected_unit_count",
        "cutoffs",
        "matches",
    }
)
_CUTOFF_KEYS = frozenset(
    {
        "cutoff",
        "supported_unit_count",
        "recall",
        "complete",
    }
)
_ANSWER_UNIT_SEPARATOR_RE = re.compile(
    r"\s*(?:[,;]\s*(?:and\s+)?|\band\b)\s*",
    re.IGNORECASE,
)
_UNSUPPORTED_ANSWER_DELIMITER_RE = re.compile(r"[\r\n|/&]")
_SLOT_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


@dataclass(frozen=True, slots=True)
class RankedEvidenceAnswerSupportObservation:
    """Immutable evidence item observed at one ranked cutoff."""

    cutoff: int
    fingerprint: str
    text: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _is_sequence(self.source_refs):
            raise TypeError("source_refs must be a sequence")
        normalized_refs: list[str] = []
        for value in self.source_refs:
            if not isinstance(value, str):
                raise TypeError("source_refs must contain strings")
            normalized = value.strip()
            if normalized and normalized not in normalized_refs:
                normalized_refs.append(normalized)
        object.__setattr__(self, "source_refs", tuple(normalized_refs))


def ranked_evidence_answer_support_metrics(
    observations: Sequence[RankedEvidenceAnswerSupportObservation],
    *,
    question: str,
    expected_terms: Sequence[str],
) -> dict[str, object]:
    """Measure source-backed generic answer-unit support at ranked cutoffs.

    This is a post-response benchmark policy.  It intentionally emits only
    bounded counts and booleans, never expected answer text or derived slot keys.
    """

    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question) > _MAX_EXPECTED_TERM_CHARS
    ):
        return _fallback("invalid_question")
    try:
        query_supported = _activity_policy.activity_inventory_query_supported(question)
    except Exception:
        return _fallback("activity_policy_error")
    if not isinstance(query_supported, bool):
        return _fallback("activity_policy_error")
    if not query_supported:
        return _fallback("unsupported_query")

    parsed = _expected_activity_slots(expected_terms)
    if isinstance(parsed, str):
        return _fallback(parsed)
    expected_slots = parsed

    grouped = _validated_observation_groups(observations)
    if grouped is None:
        return _fallback("invalid_observations")

    cutoff_metrics: list[dict[str, object]] = []
    previous_supported: frozenset[str] = frozenset()
    for cutoff, cutoff_observations in grouped:
        supported = _supported_slots(
            cutoff_observations,
            question=question,
            expected_slots=frozenset(expected_slots),
        )
        if supported is None:
            return _fallback("activity_policy_error")
        if not previous_supported <= supported:
            return _fallback("non_monotonic_support")
        previous_supported = supported
        supported_count = len(supported)
        expected_count = len(expected_slots)
        cutoff_metrics.append(
            {
                "cutoff": cutoff,
                "supported_unit_count": supported_count,
                "recall": supported_count / expected_count,
                "complete": supported_count == expected_count,
            }
        )

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "applicable": True,
        "fallback_reason": None,
        "expected_unit_count": len(expected_slots),
        "cutoffs": cutoff_metrics,
        "matches": all(cutoff["complete"] is True for cutoff in cutoff_metrics),
    }
    if not ranked_evidence_answer_support_metrics_contract_valid(metrics):
        return _fallback("invalid_observations")
    return metrics


def ranked_evidence_answer_support_metrics_contract_valid(
    metrics: object,
    *,
    expected_cutoffs: Sequence[int] | None = None,
) -> bool:
    """Validate the exact bounded public contract and its monotonic invariants."""

    if not isinstance(metrics, Mapping) or frozenset(metrics) != _TOP_LEVEL_KEYS:
        return False
    if (
        metrics["schema_version"] != SCHEMA_VERSION
        or not isinstance(metrics["applicable"], bool)
        or not _is_exact_non_negative_int(metrics["expected_unit_count"])
        or metrics["expected_unit_count"] > _MAX_EXPECTED_UNITS
        or not isinstance(metrics["cutoffs"], list)
        or len(metrics["cutoffs"]) > _MAX_CUTOFFS
        or not isinstance(metrics["matches"], bool)
    ):
        return False

    applicable = metrics["applicable"]
    fallback_reason = metrics["fallback_reason"]
    expected_count = metrics["expected_unit_count"]
    cutoffs = metrics["cutoffs"]
    if not applicable:
        return (
            isinstance(fallback_reason, str)
            and fallback_reason in _FALLBACK_REASONS
            and expected_count == 0
            and cutoffs == []
            and metrics["matches"] is False
        )
    if fallback_reason is not None or not 2 <= expected_count <= _MAX_EXPECTED_UNITS or not cutoffs:
        return False

    previous_cutoff = 0
    previous_supported = 0
    cutoff_values: list[int] = []
    for metric in cutoffs:
        if not _cutoff_metric_valid(metric, expected_count=expected_count):
            return False
        cutoff = metric["cutoff"]
        supported = metric["supported_unit_count"]
        if cutoff <= previous_cutoff or supported < previous_supported:
            return False
        previous_cutoff = cutoff
        previous_supported = supported
        cutoff_values.append(cutoff)

    if expected_cutoffs is not None:
        validated_expected_cutoffs = _validated_expected_cutoffs(expected_cutoffs)
        if validated_expected_cutoffs is None or cutoff_values != list(validated_expected_cutoffs):
            return False
    return metrics["matches"] is all(metric["complete"] is True for metric in cutoffs)


def ranked_evidence_answer_support(
    observations: Sequence[RankedEvidenceAnswerSupportObservation],
    *,
    question: str,
    expected_terms: Sequence[str],
) -> dict[str, object]:
    """Compatibility spelling for the public policy entry point."""

    return ranked_evidence_answer_support_metrics(
        observations,
        question=question,
        expected_terms=expected_terms,
    )


def ranked_evidence_answer_support_contract_valid(
    metrics: object,
    *,
    expected_cutoffs: Sequence[int] | None = None,
) -> bool:
    """Compatibility spelling for the public contract validator."""

    return ranked_evidence_answer_support_metrics_contract_valid(
        metrics,
        expected_cutoffs=expected_cutoffs,
    )


def _expected_activity_slots(expected_terms: object) -> tuple[str, ...] | str:
    if (
        not _is_sequence(expected_terms)
        or not expected_terms
        or len(expected_terms) > _MAX_EXPECTED_TERMS
    ):
        return "invalid_expected_terms"
    raw_units: list[str] = []
    for term in expected_terms:
        if not isinstance(term, str) or not term.strip() or len(term) > _MAX_EXPECTED_TERM_CHARS:
            return "invalid_expected_terms"
        if _UNSUPPORTED_ANSWER_DELIMITER_RE.search(term):
            return "ambiguous_expected_unit_slots"
        units = _ANSWER_UNIT_SEPARATOR_RE.split(term.strip().strip("."))
        if any(not unit.strip() for unit in units):
            return "ambiguous_expected_unit_slots"
        raw_units.extend(unit.strip() for unit in units)
        if len(raw_units) > _MAX_EXPECTED_UNITS:
            return "expected_unit_overflow"
    if len(raw_units) < 2:
        return "unsupported_answer_shape"

    slots: list[str] = []
    try:
        for unit in raw_units:
            slot = _activity_policy.activity_inventory_slot_key(unit)
            if not _valid_slot(slot) or slot in slots:
                return "ambiguous_expected_unit_slots"
            slots.append(slot)
    except Exception:
        return "activity_policy_error"
    return tuple(slots)


def _validated_observation_groups(
    observations: object,
) -> tuple[tuple[int, tuple[RankedEvidenceAnswerSupportObservation, ...]], ...] | None:
    if not _is_sequence(observations) or not observations or len(observations) > _MAX_OBSERVATIONS:
        return None

    groups: list[tuple[int, list[RankedEvidenceAnswerSupportObservation]]] = []
    immutable_fingerprints: dict[str, tuple[str, tuple[str, ...]]] = {}
    for observation in observations:
        if not _observation_valid(observation):
            return None
        if not groups or groups[-1][0] != observation.cutoff:
            if len(groups) >= _MAX_CUTOFFS or (groups and observation.cutoff <= groups[-1][0]):
                return None
            groups.append((observation.cutoff, []))
        group = groups[-1][1]
        if (
            len(group) >= _MAX_OBSERVATIONS_PER_CUTOFF
            or len(group) >= observation.cutoff
            or any(item.fingerprint == observation.fingerprint for item in group)
        ):
            return None
        payload = (observation.text, observation.source_refs)
        existing_payload = immutable_fingerprints.setdefault(
            observation.fingerprint,
            payload,
        )
        if existing_payload != payload:
            return None
        group.append(observation)
    return tuple((cutoff, tuple(group)) for cutoff, group in groups)


def _observation_valid(value: object) -> bool:
    return (
        isinstance(value, RankedEvidenceAnswerSupportObservation)
        and _is_supported_cutoff(value.cutoff)
        and isinstance(value.fingerprint, str)
        and value.fingerprint == value.fingerprint.strip()
        and 0 < len(value.fingerprint) <= _MAX_FINGERPRINT_CHARS
        and isinstance(value.text, str)
        and bool(value.text.strip())
        and len(value.text) <= _MAX_TEXT_CHARS
        and len(value.source_refs) <= _MAX_SOURCE_REFS
        and all(
            ref == ref.strip() and 0 < len(ref) <= _MAX_SOURCE_REF_CHARS
            for ref in value.source_refs
        )
    )


def _supported_slots(
    observations: Sequence[RankedEvidenceAnswerSupportObservation],
    *,
    question: str,
    expected_slots: frozenset[str],
) -> frozenset[str] | None:
    supported: set[str] = set()
    for observation in observations:
        if not observation.source_refs:
            continue
        try:
            slots = _activity_policy.activity_inventory_evidence_slots(
                query=question,
                text=observation.text,
            )
        except Exception:
            return None
        if (
            not _is_sequence(slots)
            or len(slots) > _MAX_EVIDENCE_SLOTS
            or any(not _valid_slot(slot) for slot in slots)
            or len(frozenset(slots)) != len(slots)
        ):
            return None
        supported.update(slot for slot in slots if slot in expected_slots)
    return frozenset(supported)


def _cutoff_metric_valid(metric: object, *, expected_count: int) -> bool:
    if not isinstance(metric, Mapping) or frozenset(metric) != _CUTOFF_KEYS:
        return False
    cutoff = metric["cutoff"]
    supported = metric["supported_unit_count"]
    recall = metric["recall"]
    complete = metric["complete"]
    return (
        _is_supported_cutoff(cutoff)
        and _is_exact_non_negative_int(supported)
        and supported <= expected_count
        and isinstance(recall, float)
        and 0.0 <= recall <= 1.0
        and recall == supported / expected_count
        and isinstance(complete, bool)
        and complete is (supported == expected_count)
    )


def _validated_expected_cutoffs(value: object) -> tuple[int, ...] | None:
    if not _is_sequence(value) or not value or len(value) > _MAX_CUTOFFS:
        return None
    cutoffs = tuple(value)
    if any(not _is_supported_cutoff(cutoff) for cutoff in cutoffs):
        return None
    if any(left >= right for left, right in zip(cutoffs, cutoffs[1:], strict=False)):
        return None
    return cutoffs


def _fallback(reason: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "applicable": False,
        "fallback_reason": reason,
        "expected_unit_count": 0,
        "cutoffs": [],
        "matches": False,
    }


def _valid_slot(value: object) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip().casefold()
        and _SLOT_KEY_RE.fullmatch(value) is not None
    )


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _is_exact_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_supported_cutoff(value: object) -> bool:
    return _is_exact_positive_int(value) and value <= _MAX_CUTOFF_VALUE


def _is_exact_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = (
    "RankedEvidenceAnswerSupportObservation",
    "SCHEMA_VERSION",
    "ranked_evidence_answer_support",
    "ranked_evidence_answer_support_contract_valid",
    "ranked_evidence_answer_support_metrics",
    "ranked_evidence_answer_support_metrics_contract_valid",
)
