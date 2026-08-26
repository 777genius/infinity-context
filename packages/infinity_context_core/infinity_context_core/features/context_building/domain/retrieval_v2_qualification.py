"""Package-owned qualification policy and preregistered Retrieval V2 anchors."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.locator_retrieval_v2 import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    LOCATOR_RETRIEVAL_RANKING_POLICY_V2,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_canonical import (
    canonical_sha256,
    evaluation_dataset_digest,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_evaluation import (
    JsonValue,
    Rational,
    RetrievalEvaluationDataset,
    RetrievalEvaluationMetrics,
    RetrievalObservation,
    _bounded_opaque,
    _nonnegative_int,
    evaluate_retrieval,
)

DEFAULT_QUALIFICATION_PROFILE_ID = "consumer-retrieval-qualification.v1"
SYNTHETIC_QUALIFICATION_SPEC_ID = "generic-records-synthetic-qualification.v1"


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    service_revision: str | None
    core_revision: str | None
    contract_version: str | None
    ranking_policy: str | None
    capability_fingerprint: str | None
    retrieval_profile: str | None
    index_identity: str | None
    dataset_digest: str | None
    cleanup_receipt: str | None

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            if value is not None:
                _bounded_opaque(f"qualification binding {name}", value, maximum=512)

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "capability_fingerprint": self.capability_fingerprint,
            "cleanup_receipt": self.cleanup_receipt,
            "contract_version": self.contract_version,
            "core_revision": self.core_revision,
            "dataset_digest": self.dataset_digest,
            "index_identity": self.index_identity,
            "ranking_policy": self.ranking_policy,
            "retrieval_profile": self.retrieval_profile,
            "service_revision": self.service_revision,
        }


@dataclass(frozen=True, slots=True)
class ConsumerQualificationProfile:
    profile_id: str = DEFAULT_QUALIFICATION_PROFILE_ID
    minimum_recall_at_5: Rational = Rational(9, 10)
    minimum_mrr_at_10: Rational = Rational(4, 5)
    maximum_cross_scope_leakage_count: int = 0
    maximum_topology_violation_count: int = 0
    maximum_p95_latency_us: int = 3_000_000
    minimum_recall_at_10: Rational | None = None
    minimum_ndcg_at_10: Rational | None = None
    maximum_failure_count: int | None = 0
    maximum_timeout_count: int | None = 0
    maximum_no_gold_with_results_count: int | None = 0

    def __post_init__(self) -> None:
        _bounded_opaque("qualification profile_id", self.profile_id)
        for name in (
            "maximum_cross_scope_leakage_count",
            "maximum_topology_violation_count",
            "maximum_p95_latency_us",
            "maximum_failure_count",
            "maximum_timeout_count",
            "maximum_no_gold_with_results_count",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonnegative_int(name, value)
        if self.profile_id == DEFAULT_QUALIFICATION_PROFILE_ID:
            actual = tuple(getattr(self, name) for name in _DEFAULT_PROFILE_VALUES)
            if actual != tuple(_DEFAULT_PROFILE_VALUES.values()):
                raise ValueError(
                    "the default qualification profile ID has immutable exact thresholds"
                )

    @property
    def threshold_fingerprint(self) -> str:
        return canonical_sha256(profile_payload(self))


_DEFAULT_PROFILE_VALUES = {
    "profile_id": DEFAULT_QUALIFICATION_PROFILE_ID,
    "minimum_recall_at_5": Rational(9, 10),
    "minimum_mrr_at_10": Rational(4, 5),
    "maximum_cross_scope_leakage_count": 0,
    "maximum_topology_violation_count": 0,
    "maximum_p95_latency_us": 3_000_000,
    "minimum_recall_at_10": None,
    "minimum_ndcg_at_10": None,
    "maximum_failure_count": 0,
    "maximum_timeout_count": 0,
    "maximum_no_gold_with_results_count": 0,
}
_DEFAULT_PROFILE = ConsumerQualificationProfile()


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    passed: bool
    observed: Rational | int
    threshold: Rational | int


@dataclass(frozen=True, slots=True)
class QualificationResult:
    qualified: bool
    binding_issue_codes: tuple[str, ...]
    gates: tuple[GateResult, ...]


@dataclass(frozen=True, slots=True)
class _QualificationTrustAnchor:
    spec_id: str
    dataset_id: str
    dataset_schema: str
    dataset_digest: str
    profile: ConsumerQualificationProfile
    binding: QualificationBinding


_SYNTHETIC_DATASET_DIGEST = (
    "sha256:d058704de0a0b8ebb2faa6c080bafddf41b216c6d3f8419292245a6365d7c84f"
)
_SYNTHETIC_BINDING = QualificationBinding(
    service_revision="service:0123456789",
    core_revision="core:0123456789",
    contract_version=LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    ranking_policy=LOCATOR_RETRIEVAL_RANKING_POLICY_V2,
    capability_fingerprint="sha256:capability",
    retrieval_profile="retrieval:synthetic",
    index_identity="index:synthetic:1",
    dataset_digest=_SYNTHETIC_DATASET_DIGEST,
    cleanup_receipt="sha256:cleanup",
)


def evaluate_qualification(
    metrics: RetrievalEvaluationMetrics,
    binding: QualificationBinding,
    dataset: RetrievalEvaluationDataset,
    profile: ConsumerQualificationProfile = _DEFAULT_PROFILE,
) -> QualificationResult:
    """Score qualification gates without conveying certification authority."""

    if type(metrics) is not RetrievalEvaluationMetrics:
        raise ValueError("reporting metrics have an invalid runtime type")
    if type(binding) is not QualificationBinding:
        raise ValueError("reporting binding has an invalid runtime type")
    if type(dataset) is not RetrievalEvaluationDataset:
        raise ValueError("reporting dataset has an invalid runtime type")
    if type(profile) is not ConsumerQualificationProfile:
        raise ValueError("reporting profile has an invalid runtime type")
    return _qualification_result(metrics, binding, dataset, profile, anchor=None)


def certify_qualification(
    *,
    qualification_spec_id: str,
    dataset: RetrievalEvaluationDataset,
    observations: tuple[RetrievalObservation, ...],
    binding: QualificationBinding,
) -> QualificationResult:
    """Recompute and certify only against a package-owned released specification.

    Metrics, profiles, fingerprints and registries are deliberately absent from
    this authority-bearing API.  Callers may supply only the measured inputs;
    the released profile and binding authority are resolved inside this module.
    """

    _strict_certification_inputs(dataset, observations, binding)
    anchor = _resolve_anchor(qualification_spec_id)
    profile = _profile_for_certification(anchor)
    return _qualification_result(
        evaluate_retrieval(dataset, observations),
        binding,
        dataset,
        profile,
        anchor=anchor,
    )


def _qualification_result(metrics, binding, dataset, profile, *, anchor):
    current_digest = evaluation_dataset_digest(dataset)
    issues = list(_binding_issues(binding, current_digest))
    if anchor is None:
        issues.append("missing:trusted_qualification_spec")
    else:
        if dataset.dataset_id != anchor.dataset_id:
            issues.append("drift:dataset_id")
        if dataset.schema_version != anchor.dataset_schema:
            issues.append("drift:dataset_schema")
        if current_digest != anchor.dataset_digest:
            issues.append("drift:trusted_dataset")
        anchor_binding = anchor.binding.to_dict()
        issues.extend(
            f"drift:{name}"
            for name, value in binding.to_dict().items()
            if value != anchor_binding[name]
        )
    gates = _evaluate_gates(metrics, profile)
    return QualificationResult(
        qualified=not issues and all(item.passed for item in gates),
        binding_issue_codes=tuple(sorted(set(issues))),
        gates=tuple(gates),
    )


def _resolve_anchor(spec_id: str) -> _QualificationTrustAnchor | None:
    if type(spec_id) is not str:
        raise ValueError("qualification_spec_id has an invalid runtime type")
    _bounded_opaque("qualification_spec_id", spec_id)
    return next((item for item in _TRUSTED_QUALIFICATION_SPECS if item.spec_id == spec_id), None)


def _profile_for_certification(
    anchor: _QualificationTrustAnchor | None,
) -> ConsumerQualificationProfile:
    """Return only package-constructed policy, including for unknown-spec reports."""

    return anchor.profile if anchor is not None else _DEFAULT_PROFILE


def _certification_profile(spec_id: str) -> ConsumerQualificationProfile:
    """Resolve a profile for evidence rendering, never caller authority."""

    return _profile_for_certification(_resolve_anchor(spec_id))


def _strict_certification_inputs(dataset, observations, binding) -> None:
    if type(dataset) is not RetrievalEvaluationDataset:
        raise ValueError("certification dataset has an invalid runtime type")
    if type(binding) is not QualificationBinding:
        raise ValueError("certification binding has an invalid runtime type")
    if type(observations) is not tuple or any(
        type(item) is not RetrievalObservation for item in observations
    ):
        raise ValueError("certification observations have an invalid runtime type")
    actual_order = tuple(item.case_id for item in observations)
    expected_order = tuple(case.case_id for case in dataset.cases)
    if actual_order != expected_order:
        raise ValueError("certification observations must follow canonical dataset case order")


def _binding_issues(binding: QualificationBinding, current_digest: str) -> tuple[str, ...]:
    values = binding.to_dict()
    issues = [f"missing:{name}" for name, value in values.items() if not value]
    if binding.dataset_digest != current_digest:
        issues.append("drift:dataset_digest")
    if binding.contract_version != LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2:
        issues.append("drift:contract_version")
    if binding.ranking_policy != LOCATOR_RETRIEVAL_RANKING_POLICY_V2:
        issues.append("drift:ranking_policy")
    return tuple(sorted(set(issues)))


def _evaluate_gates(
    metrics: RetrievalEvaluationMetrics, profile: ConsumerQualificationProfile
) -> list[GateResult]:
    gates = [
        GateResult(
            "recall_at_5",
            metrics.recall_at_5.at_least(profile.minimum_recall_at_5),
            metrics.recall_at_5,
            profile.minimum_recall_at_5,
        ),
        GateResult(
            "mrr_at_10",
            metrics.mrr_at_10.at_least(profile.minimum_mrr_at_10),
            metrics.mrr_at_10,
            profile.minimum_mrr_at_10,
        ),
        GateResult(
            "cross_scope_leakage_count",
            metrics.cross_scope_leakage_count <= profile.maximum_cross_scope_leakage_count,
            metrics.cross_scope_leakage_count,
            profile.maximum_cross_scope_leakage_count,
        ),
        GateResult(
            "topology_violation_count",
            metrics.topology_violation_count <= profile.maximum_topology_violation_count,
            metrics.topology_violation_count,
            profile.maximum_topology_violation_count,
        ),
        GateResult(
            "p95_latency_us",
            metrics.latency.p95_us <= profile.maximum_p95_latency_us,
            metrics.latency.p95_us,
            profile.maximum_p95_latency_us,
        ),
    ]
    _optional_ratio_gate(gates, "recall_at_10", metrics.recall_at_10, profile.minimum_recall_at_10)
    _optional_ratio_gate(gates, "ndcg_at_10", metrics.ndcg_at_10, profile.minimum_ndcg_at_10)
    # Certification is always zero-tolerance for execution failures and timeouts.
    gates.append(GateResult("failure_count", metrics.failure_count == 0, metrics.failure_count, 0))
    gates.append(GateResult("timeout_count", metrics.timeout_count == 0, metrics.timeout_count, 0))
    _optional_max_gate(
        gates,
        "no_gold_with_results_count",
        metrics.no_gold_with_results_count,
        profile.maximum_no_gold_with_results_count,
    )
    return gates


def _optional_ratio_gate(
    gates: list[GateResult], gate_id: str, observed: Rational, threshold: Rational | None
) -> None:
    if threshold is not None:
        gates.append(GateResult(gate_id, observed.at_least(threshold), observed, threshold))


def _optional_max_gate(
    gates: list[GateResult], gate_id: str, observed: int, threshold: int | None
) -> None:
    if threshold is not None:
        gates.append(GateResult(gate_id, observed <= threshold, observed, threshold))


def profile_payload(profile: ConsumerQualificationProfile) -> dict[str, JsonValue]:
    return {
        "maximum_cross_scope_leakage_count": profile.maximum_cross_scope_leakage_count,
        "maximum_failure_count": profile.maximum_failure_count,
        "maximum_no_gold_with_results_count": profile.maximum_no_gold_with_results_count,
        "maximum_p95_latency_us": profile.maximum_p95_latency_us,
        "maximum_timeout_count": profile.maximum_timeout_count,
        "maximum_topology_violation_count": profile.maximum_topology_violation_count,
        "minimum_mrr_at_10": profile.minimum_mrr_at_10.to_dict(),
        "minimum_ndcg_at_10": (
            profile.minimum_ndcg_at_10.to_dict() if profile.minimum_ndcg_at_10 else None
        ),
        "minimum_recall_at_10": (
            profile.minimum_recall_at_10.to_dict() if profile.minimum_recall_at_10 else None
        ),
        "minimum_recall_at_5": profile.minimum_recall_at_5.to_dict(),
        "profile_id": profile.profile_id,
    }


_TRUSTED_QUALIFICATION_SPECS = (
    _QualificationTrustAnchor(
        spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset_id="generic-records-synthetic-v1",
        dataset_schema="generic-retrieval-v2-dataset.v1",
        dataset_digest=_SYNTHETIC_DATASET_DIGEST,
        profile=_DEFAULT_PROFILE,
        binding=_SYNTHETIC_BINDING,
    ),
)


__all__ = (
    "ConsumerQualificationProfile",
    "DEFAULT_QUALIFICATION_PROFILE_ID",
    "GateResult",
    "QualificationBinding",
    "QualificationResult",
    "SYNTHETIC_QUALIFICATION_SPEC_ID",
    "certify_qualification",
    "evaluate_qualification",
    "profile_payload",
)
