"""Provider-free semantic cutoff metrics for ranked benchmark evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

_TELEMETRY_KEYS = (
    "ranked_evidence_candidate_count",
    "ranked_evidence_selectable_candidate_count",
    "ranked_evidence_eligible_candidate_count",
    "ranked_evidence_returned_count",
    "ranked_evidence_source_diversity_count",
)
_CHECK_KEYS = frozenset(
    {
        "input_valid",
        "cutoffs_strictly_increasing",
        "reference_cutoff_is_max",
        "item_ids_stable_prefix",
        "coverage_monotonic",
        "telemetry_coherent",
        "telemetry_population_invariant",
        "telemetry_eligible_monotonic",
        "source_diversity_monotonic",
    }
)
_CUTOFF_KEYS = frozenset(
    {
        "cutoff",
        "item_count",
        "recall",
        "covered_refs",
        "covered_ref_count",
        "missing_refs",
        "missing_ref_count",
        "crowd_out_refs",
        "crowd_out_ref_count",
        "source_diversity_count",
        "matches",
    }
)


@dataclass(frozen=True, slots=True)
class RankedEvidenceCutoffSnapshot:
    """Immutable post-retrieval observation without a gold-answer payload."""

    cutoff: int
    item_ids: tuple[str, ...]
    covered_refs: tuple[str, ...]
    ranked_telemetry: Mapping[str, object]

    def __post_init__(self) -> None:
        if not _is_sequence(self.item_ids) or not _is_sequence(self.covered_refs):
            raise TypeError("snapshot identifiers must be sequences")
        if not isinstance(self.ranked_telemetry, Mapping):
            raise TypeError("ranked telemetry must be a mapping")
        object.__setattr__(self, "item_ids", tuple(self.item_ids))
        object.__setattr__(self, "covered_refs", tuple(self.covered_refs))
        object.__setattr__(
            self,
            "ranked_telemetry",
            MappingProxyType(dict(self.ranked_telemetry)),
        )


def ranked_evidence_semantic_metrics(
    snapshots: Sequence[RankedEvidenceCutoffSnapshot],
    *,
    expected_refs: Sequence[str],
    reference_cutoff: int,
) -> dict[str, object]:
    """Compare semantic coverage at ordered cutoffs against the widest slice."""

    checks = {
        "input_valid": True,
        "cutoffs_strictly_increasing": True,
        "reference_cutoff_is_max": True,
        "item_ids_stable_prefix": True,
        "coverage_monotonic": True,
        "telemetry_coherent": True,
        "telemetry_population_invariant": True,
        "telemetry_eligible_monotonic": True,
        "source_diversity_monotonic": True,
    }
    expected = _unique_identifiers(expected_refs)
    if (
        expected is None
        or not expected
        or not _is_exact_positive_int(reference_cutoff)
        or not _is_sequence(snapshots)
        or not snapshots
    ):
        checks["input_valid"] = False
        return _contract(checks=checks, reference_cutoff=reference_cutoff)

    validated: list[
        tuple[RankedEvidenceCutoffSnapshot, tuple[str, ...], tuple[str, ...], dict[str, int]]
    ] = []
    expected_set = frozenset(expected)
    for snapshot in snapshots:
        if not isinstance(snapshot, RankedEvidenceCutoffSnapshot):
            checks["input_valid"] = False
            checks["reference_cutoff_is_max"] = False
            return _contract(checks=checks, reference_cutoff=reference_cutoff)
        item_ids = _unique_identifiers(snapshot.item_ids)
        covered_refs = _unique_identifiers(snapshot.covered_refs)
        telemetry = _ranked_telemetry(snapshot.ranked_telemetry)
        if (
            not _is_exact_positive_int(snapshot.cutoff)
            or item_ids is None
            or covered_refs is None
            or telemetry is None
            or not frozenset(covered_refs) <= expected_set
        ):
            checks["input_valid"] = False
            checks["cutoffs_strictly_increasing"] &= _is_exact_positive_int(snapshot.cutoff)
            checks["telemetry_coherent"] &= telemetry is not None
            return _contract(checks=checks, reference_cutoff=reference_cutoff)
        validated.append((snapshot, item_ids, covered_refs, telemetry))

    pairs = tuple(zip(validated, validated[1:], strict=False))
    checks["cutoffs_strictly_increasing"] = all(
        left[0].cutoff < right[0].cutoff for left, right in pairs
    )
    checks["reference_cutoff_is_max"] = validated[-1][0].cutoff == reference_cutoff
    checks["item_ids_stable_prefix"] = all(
        len(right[1]) >= len(left[1]) and right[1][: len(left[1])] == left[1]
        for left, right in pairs
    )
    checks["coverage_monotonic"] = all(
        frozenset(left[2]) <= frozenset(right[2]) for left, right in pairs
    )
    checks["telemetry_coherent"] = all(
        _telemetry_is_coherent(
            telemetry,
            item_count=len(item_ids),
            cutoff=snapshot.cutoff,
        )
        for snapshot, item_ids, _, telemetry in validated
    )
    checks["telemetry_population_invariant"] = all(
        _telemetry_population(left[3]) == _telemetry_population(right[3]) for left, right in pairs
    )
    checks["telemetry_eligible_monotonic"] = all(
        left[3]["ranked_evidence_eligible_candidate_count"]
        >= right[3]["ranked_evidence_eligible_candidate_count"]
        for left, right in pairs
    )
    checks["source_diversity_monotonic"] = all(
        left[3]["ranked_evidence_source_diversity_count"]
        <= right[3]["ranked_evidence_source_diversity_count"]
        for left, right in pairs
    )

    if not all(checks.values()):
        return _contract(checks=checks, reference_cutoff=reference_cutoff)

    reference_refs = validated[-1][2]
    reference_coverage = frozenset(reference_refs)
    retrieval_miss_refs = _ordered_difference(expected, reference_coverage)
    cutoff_metrics: list[dict[str, object]] = []
    for snapshot, item_ids, covered_refs, telemetry in validated:
        covered_set = frozenset(covered_refs)
        missing_refs = _ordered_difference(expected, covered_set)
        crowd_out_refs = _ordered_difference(reference_refs, covered_set)
        cutoff_metrics.append(
            {
                "cutoff": snapshot.cutoff,
                "item_count": len(item_ids),
                "recall": len(covered_set) / len(expected),
                "covered_refs": [
                    identifier for identifier in expected if identifier in covered_set
                ],
                "covered_ref_count": len(covered_set),
                "missing_refs": list(missing_refs),
                "missing_ref_count": len(missing_refs),
                "crowd_out_refs": list(crowd_out_refs),
                "crowd_out_ref_count": len(crowd_out_refs),
                "source_diversity_count": telemetry["ranked_evidence_source_diversity_count"],
                "matches": True,
            }
        )

    return _contract(
        checks=checks,
        reference_cutoff=reference_cutoff,
        expected_ref_count=len(expected),
        retrieval_miss_refs=retrieval_miss_refs,
        cutoffs=cutoff_metrics,
    )


def ranked_evidence_semantic_metrics_contract_valid(
    metrics: object,
    *,
    expected_cutoffs: Sequence[int],
    reference_cutoff: int,
) -> bool:
    """Validate the exact public metrics schema before gate aggregation."""

    top_level_keys = frozenset(
        {
            "schema_version",
            "reference_cutoff",
            "expected_ref_count",
            "retrieval_miss_refs",
            "retrieval_miss_ref_count",
            "cutoffs",
            "checks",
            "matches",
        }
    )
    if not isinstance(metrics, Mapping) or frozenset(metrics) != top_level_keys:
        return False
    checks = metrics["checks"]
    retrieval_refs = metrics["retrieval_miss_refs"]
    cutoffs = metrics["cutoffs"]
    if (
        metrics["schema_version"] != "ranked-evidence-semantic-metrics.v1"
        or metrics["reference_cutoff"] != reference_cutoff
        or not _is_exact_non_negative_int(metrics["expected_ref_count"])
        or not _is_exact_non_negative_int(metrics["retrieval_miss_ref_count"])
        or not isinstance(retrieval_refs, list)
        or _unique_identifiers(retrieval_refs) is None
        or metrics["retrieval_miss_ref_count"] != len(retrieval_refs)
        or not isinstance(cutoffs, list)
        or not isinstance(checks, Mapping)
        or frozenset(checks) != _CHECK_KEYS
        or any(not isinstance(value, bool) for value in checks.values())
        or not isinstance(metrics["matches"], bool)
        or metrics["matches"] is not all(checks.values())
    ):
        return False
    if metrics["matches"] is True:
        cutoff_ids = [cutoff.get("cutoff") for cutoff in cutoffs if isinstance(cutoff, Mapping)]
        if (
            not cutoffs
            or len(cutoffs) != len(expected_cutoffs)
            or cutoff_ids != list(expected_cutoffs)
        ):
            return False
    return all(
        _cutoff_metric_is_valid(cutoff, expected_ref_count=metrics["expected_ref_count"])
        for cutoff in cutoffs
    )


def _cutoff_metric_is_valid(cutoff: object, *, expected_ref_count: int) -> bool:
    if not isinstance(cutoff, Mapping) or frozenset(cutoff) != _CUTOFF_KEYS:
        return False
    identifier_fields = ("covered_refs", "missing_refs", "crowd_out_refs")
    count_fields = (
        "item_count",
        "covered_ref_count",
        "missing_ref_count",
        "crowd_out_ref_count",
        "source_diversity_count",
    )
    if any(not _is_exact_non_negative_int(cutoff[field]) for field in count_fields):
        return False
    if not _is_exact_positive_int(cutoff["cutoff"]):
        return False
    if any(
        not isinstance(cutoff[field], list) or _unique_identifiers(cutoff[field]) is None
        for field in identifier_fields
    ):
        return False
    recall = cutoff["recall"]
    return (
        isinstance(recall, float)
        and 0.0 <= recall <= 1.0
        and cutoff["matches"] is True
        and cutoff["item_count"] <= cutoff["cutoff"]
        and cutoff["covered_ref_count"] == len(cutoff["covered_refs"])
        and cutoff["missing_ref_count"] == len(cutoff["missing_refs"])
        and cutoff["crowd_out_ref_count"] == len(cutoff["crowd_out_refs"])
        and cutoff["covered_ref_count"] + cutoff["missing_ref_count"] == expected_ref_count
    )


def _contract(
    *,
    checks: Mapping[str, bool],
    reference_cutoff: object,
    expected_ref_count: int = 0,
    retrieval_miss_refs: Sequence[str] = (),
    cutoffs: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    matches = all(checks.values())
    return {
        "schema_version": "ranked-evidence-semantic-metrics.v1",
        "reference_cutoff": (
            reference_cutoff if _is_exact_positive_int(reference_cutoff) else None
        ),
        "expected_ref_count": expected_ref_count,
        "retrieval_miss_refs": list(retrieval_miss_refs),
        "retrieval_miss_ref_count": len(retrieval_miss_refs),
        "cutoffs": list(cutoffs),
        "checks": dict(checks),
        "matches": matches,
    }


def _ranked_telemetry(value: Mapping[str, object]) -> dict[str, int] | None:
    counts: dict[str, int] = {}
    for key in _TELEMETRY_KEYS:
        count = value.get(key)
        if not _is_exact_non_negative_int(count):
            return None
        counts[key] = count
    return counts


def _telemetry_is_coherent(
    telemetry: Mapping[str, int],
    *,
    item_count: int,
    cutoff: int,
) -> bool:
    candidate = telemetry["ranked_evidence_candidate_count"]
    selectable = telemetry["ranked_evidence_selectable_candidate_count"]
    eligible = telemetry["ranked_evidence_eligible_candidate_count"]
    returned = telemetry["ranked_evidence_returned_count"]
    source_diversity = telemetry["ranked_evidence_source_diversity_count"]
    return (
        selectable >= candidate
        and eligible <= selectable
        and returned <= cutoff
        and returned == item_count
        and returned <= eligible
        and (returned > 0 or source_diversity == 0)
    )


def _telemetry_population(telemetry: Mapping[str, int]) -> tuple[int, int]:
    return (
        telemetry["ranked_evidence_candidate_count"],
        telemetry["ranked_evidence_selectable_candidate_count"],
    )


def _unique_identifiers(value: object) -> tuple[str, ...] | None:
    if not _is_sequence(value):
        return None
    identifiers = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in identifiers) or len(
        frozenset(identifiers)
    ) != len(identifiers):
        return None
    return identifiers


def _ordered_difference(
    identifiers: Sequence[str],
    excluded: frozenset[str],
) -> tuple[str, ...]:
    return tuple(identifier for identifier in identifiers if identifier not in excluded)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    )


def _is_exact_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_exact_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
