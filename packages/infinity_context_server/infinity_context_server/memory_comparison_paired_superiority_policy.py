"""Predeclared provider-free statistics for the 2,040-pair comparison."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import final

from infinity_context_server.memory_comparison_publishable_contracts import (
    canonical_payload_sha256,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    resolve_publishable_methodology,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    public_publishable_comparison_profile,
    resolve_publishable_comparison_profile,
)

PAIRED_SUPERIORITY_POLICY_SCHEMA_VERSION = "memory-comparison-paired-superiority-policy.v1"
PAIRED_SUPERIORITY_DECISION_SCHEMA_VERSION = "memory-comparison-paired-superiority-decision.v1"
_ALPHA = Fraction(1, 40)
_OVERALL_EFFECT_BPS = 200
_CATEGORY_MARGIN_BPS = 500
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EXPECTED_STRATA = (
    ("locomo", "multi-hop", 282),
    ("locomo", "temporal", 321),
    ("locomo", "open-domain", 96),
    ("locomo", "single-hop", 841),
    ("longmemeval", "knowledge-update", 78),
    ("longmemeval", "multi-session", 133),
    ("longmemeval", "single-session-assistant", 56),
    ("longmemeval", "single-session-preference", 30),
    ("longmemeval", "single-session-user", 70),
    ("longmemeval", "temporal", 133),
)


class PairedSuperiorityPolicyError(ValueError):
    """Fail-closed error containing no benchmark result material."""


@final
@dataclass(frozen=True, slots=True)
class PairedBinaryStratum:
    benchmark: str
    category: str
    both_correct: int
    infinity_only_correct: int
    mem0_only_correct: int
    both_incorrect: int

    def __post_init__(self) -> None:
        if (
            type(self.benchmark) is not str
            or type(self.category) is not str
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.both_correct,
                    self.infinity_only_correct,
                    self.mem0_only_correct,
                    self.both_incorrect,
                )
            )
        ):
            _fail("paired_superiority_stratum_invalid")

    @property
    def total(self) -> int:
        return (
            self.both_correct
            + self.infinity_only_correct
            + self.mem0_only_correct
            + self.both_incorrect
        )

    def material(self) -> dict[str, object]:
        return {
            "benchmark": self.benchmark,
            "category": self.category,
            "pair_count": self.total,
            "both_correct": self.both_correct,
            "infinity_only_correct": self.infinity_only_correct,
            "mem0_only_correct": self.mem0_only_correct,
            "both_incorrect": self.both_incorrect,
        }


def paired_superiority_dataset_counts_sha256(
    *, benchmark: str, strata: tuple[PairedBinaryStratum, ...]
) -> str:
    """Commit exact ordered paired counts for one frozen dataset run."""

    if type(benchmark) is not str or benchmark not in {"locomo", "longmemeval"}:
        _fail("paired_superiority_dataset_counts_invalid")
    expected = tuple(item for item in _EXPECTED_STRATA if item[0] == benchmark)
    if type(strata) is not tuple or len(strata) != len(expected):
        _fail("paired_superiority_dataset_counts_invalid")
    materials: list[dict[str, object]] = []
    for value, expected_item in zip(strata, expected, strict=True):
        if type(value) is PairedBinaryStratum:
            PairedBinaryStratum.__post_init__(value)
        if (
            type(value) is not PairedBinaryStratum
            or (value.benchmark, value.category, value.total) != expected_item
        ):
            _fail("paired_superiority_dataset_counts_invalid")
        materials.append(value.material())
    return canonical_payload_sha256(
        {
            "schema_version": "memory-comparison-paired-dataset-counts.v1",
            "benchmark": benchmark,
            "ordered_strata": materials,
        }
    )


@final
@dataclass(frozen=True, slots=True)
class PairedDatasetRunAuthority:
    benchmark: str
    profile_commitment_sha256: str
    binding_commitment_sha256: str
    case_manifest_sha256: str
    judge_outcomes_sha256: str
    paired_counts_sha256: str
    terminal_report_sha256: str
    terminal_receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.benchmark) is not str
            or self.benchmark not in {"locomo", "longmemeval"}
            or any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.profile_commitment_sha256,
                    self.binding_commitment_sha256,
                    self.case_manifest_sha256,
                    self.judge_outcomes_sha256,
                    self.paired_counts_sha256,
                    self.terminal_report_sha256,
                    self.terminal_receipt_sha256,
                )
            )
        ):
            _fail("paired_superiority_run_authority_invalid")

    def material(self) -> dict[str, str]:
        return {
            "schema_version": "memory-comparison-paired-dataset-run-authority.v1",
            "benchmark": self.benchmark,
            "profile_commitment_sha256": self.profile_commitment_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "case_manifest_sha256": self.case_manifest_sha256,
            "judge_outcomes_sha256": self.judge_outcomes_sha256,
            "paired_counts_sha256": self.paired_counts_sha256,
            "terminal_report_sha256": self.terminal_report_sha256,
            "terminal_receipt_sha256": self.terminal_receipt_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class PairedSuperiorityEvidence:
    profile_commitment_sha256: str
    methodology_commitment_sha256: str
    policy_sha256: str
    dataset_runs: tuple[PairedDatasetRunAuthority, ...]
    publication_bundle_sha256: str
    strata: tuple[PairedBinaryStratum, ...]

    def __post_init__(self) -> None:
        profile_sha, methodology_sha = _authority_digests()
        if (
            any(
                type(value) is not str or _SHA256.fullmatch(value) is None
                for value in (
                    self.profile_commitment_sha256,
                    self.methodology_commitment_sha256,
                    self.policy_sha256,
                    self.publication_bundle_sha256,
                )
            )
            or self.profile_commitment_sha256 != profile_sha
            or self.methodology_commitment_sha256 != methodology_sha
            or self.policy_sha256 != PAIRED_SUPERIORITY_POLICY_SHA256
            or type(self.dataset_runs) is not tuple
            or len(self.dataset_runs) != 2
            or type(self.strata) is not tuple
            or len(self.strata) != len(_EXPECTED_STRATA)
        ):
            _fail("paired_superiority_evidence_invalid")
        for value, expected in zip(self.strata, _EXPECTED_STRATA, strict=True):
            if type(value) is PairedBinaryStratum:
                PairedBinaryStratum.__post_init__(value)
            if (
                type(value) is not PairedBinaryStratum
                or (value.benchmark, value.category, value.total) != expected
            ):
                _fail("paired_superiority_coverage_invalid")
        for run, benchmark in zip(self.dataset_runs, ("locomo", "longmemeval"), strict=True):
            if type(run) is PairedDatasetRunAuthority:
                PairedDatasetRunAuthority.__post_init__(run)
            if (
                type(run) is not PairedDatasetRunAuthority
                or run.benchmark != benchmark
                or run.profile_commitment_sha256 != self.profile_commitment_sha256
            ):
                _fail("paired_superiority_run_authority_invalid")
            dataset_strata = tuple(item for item in self.strata if item.benchmark == benchmark)
            if run.paired_counts_sha256 != paired_superiority_dataset_counts_sha256(
                benchmark=benchmark,
                strata=dataset_strata,
            ):
                _fail("paired_superiority_run_authority_invalid")
        if self.publication_bundle_sha256 != paired_superiority_publication_bundle_sha256(
            profile_commitment_sha256=self.profile_commitment_sha256,
            methodology_commitment_sha256=self.methodology_commitment_sha256,
            policy_sha256=self.policy_sha256,
            dataset_runs=self.dataset_runs,
        ):
            _fail("paired_superiority_publication_bundle_invalid")


def paired_superiority_policy_payload() -> dict[str, object]:
    """Return the result-independent policy committed before execution."""

    return {
        "schema_version": PAIRED_SUPERIORITY_POLICY_SCHEMA_VERSION,
        "claim": "infinity_beats_mem0_on_exact_paired_2040",
        "expected_pair_count": 2040,
        "expected_strata": [
            {"benchmark": benchmark, "category": category, "pair_count": count}
            for benchmark, category, count in _EXPECTED_STRATA
        ],
        "alpha": {"numerator": _ALPHA.numerator, "denominator": _ALPHA.denominator},
        "primary": {
            "test": "one_sided_exact_mcnemar",
            "minimum_accuracy_delta_basis_points": _OVERALL_EFFECT_BPS,
        },
        "dataset_guardrail": {"measure": "observed_accuracy_delta", "minimum_basis_points": 0},
        "category_guardrail": {
            "measure": "observed_accuracy_delta",
            "minimum_basis_points": -_CATEGORY_MARGIN_BPS,
        },
        "multiplicity": "intersection_union_all_components_required",
        "decision_scope": "statistical_criterion_only_not_publication_authority",
    }


PAIRED_SUPERIORITY_POLICY_SHA256 = canonical_payload_sha256(paired_superiority_policy_payload())


def paired_superiority_publication_bundle_sha256(
    *,
    profile_commitment_sha256: str,
    methodology_commitment_sha256: str,
    policy_sha256: str,
    dataset_runs: tuple[PairedDatasetRunAuthority, ...],
) -> str:
    """Bind the two ordered terminal run authorities used by the decision."""

    if (
        any(
            type(value) is not str or _SHA256.fullmatch(value) is None
            for value in (
                profile_commitment_sha256,
                methodology_commitment_sha256,
                policy_sha256,
            )
        )
        or type(dataset_runs) is not tuple
        or len(dataset_runs) != 2
    ):
        _fail("paired_superiority_publication_bundle_invalid")
    materials: list[dict[str, str]] = []
    for run, benchmark in zip(dataset_runs, ("locomo", "longmemeval"), strict=True):
        if type(run) is PairedDatasetRunAuthority:
            PairedDatasetRunAuthority.__post_init__(run)
        if (
            type(run) is not PairedDatasetRunAuthority
            or run.benchmark != benchmark
            or run.profile_commitment_sha256 != profile_commitment_sha256
        ):
            _fail("paired_superiority_publication_bundle_invalid")
        materials.append(run.material())
    return canonical_payload_sha256(
        {
            "schema_version": "memory-comparison-paired-publication-bundle.v1",
            "profile_commitment_sha256": profile_commitment_sha256,
            "methodology_commitment_sha256": methodology_commitment_sha256,
            "policy_sha256": policy_sha256,
            "ordered_dataset_runs": materials,
        }
    )


def evaluate_paired_superiority(evidence: PairedSuperiorityEvidence) -> dict[str, object]:
    """Evaluate exact counts without provider, random, or serialized aggregate input."""

    if type(evidence) is not PairedSuperiorityEvidence:
        _fail("paired_superiority_evidence_invalid")
    PairedSuperiorityEvidence.__post_init__(evidence)
    datasets = tuple(
        _aggregate(evidence.strata, benchmark=benchmark) for benchmark in ("locomo", "longmemeval")
    )
    overall = _aggregate(evidence.strata)
    primary = _superiority(overall)
    dataset_results = tuple(_observed_guardrail(item, 0) for item in datasets)
    category_results = tuple(
        _observed_guardrail(_counts((item,), item.benchmark, item.category), -_CATEGORY_MARGIN_BPS)
        for item in evidence.strata
    )
    failures: list[str] = []
    if not primary["minimum_effect_met"]:
        failures.append("overall_minimum_effect_not_met")
    if not primary["exact_superiority_met"]:
        failures.append("overall_exact_superiority_not_met")
    for result in dataset_results:
        if not result["observed_delta_guardrail_met"]:
            failures.append(f"{result['benchmark']}_observed_regression")
    for result in category_results:
        if not result["observed_delta_guardrail_met"]:
            failures.append(f"{result['benchmark']}:{result['category']}_observed_harm_exceeded")
    body = {
        "schema_version": PAIRED_SUPERIORITY_DECISION_SCHEMA_VERSION,
        "policy_sha256": PAIRED_SUPERIORITY_POLICY_SHA256,
        "profile_commitment_sha256": evidence.profile_commitment_sha256,
        "methodology_commitment_sha256": evidence.methodology_commitment_sha256,
        "publication_bundle_sha256": evidence.publication_bundle_sha256,
        "ordered_dataset_runs": [run.material() for run in evidence.dataset_runs],
        "criterion_met": not failures,
        "publishable": False,
        "failures": failures,
        "overall": primary,
        "datasets": list(dataset_results),
        "categories": list(category_results),
    }
    return {**body, "decision_sha256": canonical_payload_sha256(body)}


def _aggregate(
    strata: tuple[PairedBinaryStratum, ...], benchmark: str | None = None
) -> dict[str, object]:
    selected = tuple(item for item in strata if benchmark is None or item.benchmark == benchmark)
    return _counts(selected, benchmark or "combined", None)


def _counts(
    selected: tuple[PairedBinaryStratum, ...], benchmark: str, category: str | None
) -> dict[str, object]:
    values = {
        name: sum(getattr(item, name) for item in selected)
        for name in (
            "both_correct",
            "infinity_only_correct",
            "mem0_only_correct",
            "both_incorrect",
        )
    }
    total = sum(values.values())
    return {
        "benchmark": benchmark,
        "category": category,
        "pair_count": total,
        **values,
        "discordant_count": values["infinity_only_correct"] + values["mem0_only_correct"],
        "net_win_count": values["infinity_only_correct"] - values["mem0_only_correct"],
        "accuracy_delta": _decimal(
            Fraction(
                values["infinity_only_correct"] - values["mem0_only_correct"],
                total,
            )
        ),
    }


def _superiority(counts: dict[str, object]) -> dict[str, object]:
    total = _integer(counts["pair_count"])
    infinity_wins = _integer(counts["infinity_only_correct"])
    discordant = _integer(counts["discordant_count"])
    net = _integer(counts["net_win_count"])
    p_value = _binomial_upper_tail(discordant, infinity_wins, Fraction(1, 2))
    return {
        **counts,
        "minimum_effect_basis_points": _OVERALL_EFFECT_BPS,
        "minimum_effect_met": net * 10_000 >= _OVERALL_EFFECT_BPS * total,
        "exact_mcnemar_p_value": _decimal(p_value),
        "exact_superiority_met": p_value <= _ALPHA,
    }


def _observed_guardrail(counts: dict[str, object], minimum_bps: int) -> dict[str, object]:
    total = _integer(counts["pair_count"])
    net = _integer(counts["net_win_count"])
    return {
        **counts,
        "minimum_observed_delta_basis_points": minimum_bps,
        "observed_delta_guardrail_met": net * 10_000 >= minimum_bps * total,
    }


def _binomial_upper_tail(trials: int, successes: int, probability: Fraction) -> Fraction:
    if not 0 <= successes <= trials or not 0 <= probability <= 1:
        _fail("paired_superiority_statistics_invalid")
    if successes == 0:
        return Fraction(1)
    if probability == 0:
        return Fraction(0)
    if probability == 1:
        return Fraction(1)
    numerator = sum(
        math.comb(trials, value)
        * probability.numerator**value
        * (probability.denominator - probability.numerator) ** (trials - value)
        for value in range(successes, trials + 1)
    )
    return Fraction(numerator, probability.denominator**trials)


def _authority_digests() -> tuple[str, str]:
    profile = resolve_publishable_comparison_profile()
    methodology = resolve_publishable_methodology()
    if profile is None or methodology is None:
        _fail("paired_superiority_authority_missing")
    try:
        public = public_publishable_comparison_profile(profile)
        benchmarks = public["benchmarks"]
        observed = tuple(
            (benchmark, category, count)
            for benchmark in ("locomo", "longmemeval")
            for category, count in benchmarks[benchmark]["expected_grouping"].items()
        )
    except (AttributeError, KeyError, TypeError):
        _fail("paired_superiority_authority_invalid")
    if observed != _EXPECTED_STRATA:
        _fail("paired_superiority_authority_invalid")
    return profile.commitment_sha256, methodology.commitment_sha256


def _decimal(value: Fraction) -> str:
    with localcontext() as context:
        context.prec = 24
        return format(Decimal(value.numerator) / Decimal(value.denominator), ".12E")


def _integer(value: object) -> int:
    if type(value) is not int:
        _fail("paired_superiority_statistics_invalid")
    return value


def _fail(code: str) -> None:
    raise PairedSuperiorityPolicyError(code)


__all__ = (
    "PAIRED_SUPERIORITY_DECISION_SCHEMA_VERSION",
    "PAIRED_SUPERIORITY_POLICY_SCHEMA_VERSION",
    "PAIRED_SUPERIORITY_POLICY_SHA256",
    "PairedBinaryStratum",
    "PairedDatasetRunAuthority",
    "PairedSuperiorityEvidence",
    "PairedSuperiorityPolicyError",
    "evaluate_paired_superiority",
    "paired_superiority_dataset_counts_sha256",
    "paired_superiority_policy_payload",
    "paired_superiority_publication_bundle_sha256",
)
