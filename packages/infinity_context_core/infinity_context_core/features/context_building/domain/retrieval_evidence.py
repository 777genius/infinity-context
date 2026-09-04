"""Canonical retained evidence construction and semantic verification."""

from __future__ import annotations

import json
from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.retrieval_canonical import (
    canonical_json,
    canonical_sha256,
    dataset_payload,
    evaluation_dataset_digest,
    sha256_bytes,
)
from infinity_context_core.features.context_building.domain.retrieval_dataset import (
    parse_retrieval_evaluation_dataset,
)
from infinity_context_core.features.context_building.domain.retrieval_evaluation import (
    JsonValue,
    RankedLocator,
    Rational,
    RetrievalEvaluationMetrics,
    RetrievalObservation,
    evaluate_retrieval,
)
from infinity_context_core.features.context_building.domain.retrieval_qualification import (
    ConsumerQualificationProfile,
    QualificationBinding,
    QualificationResult,
    _certification_profile,
    certify_qualification,
    evaluate_qualification,
    profile_payload,
)

RETRIEVAL_EVALUATION_SCHEMA = "locator-retrieval-evaluation.v1"
_MANIFEST_FIELDS = {
    "binding",
    "component_digests",
    "dataset",
    "metrics",
    "observations",
    "qualification",
    "qualification_profile",
    "qualification_spec_id",
    "schema_version",
}
_COMPONENTS = {"binding", "dataset", "metrics", "observations", "profile", "qualification"}


@dataclass(frozen=True, slots=True)
class EvaluationEvidence:
    canonical_json: str
    manifest_digest: str
    component_digests: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_json, str) or not isinstance(self.manifest_digest, str):
            raise ValueError("evidence bytes and digest must be strings")
        rows = tuple(tuple(row) for row in self.component_digests)
        if any(len(row) != 2 or not all(isinstance(item, str) for item in row) for row in rows):
            raise ValueError("evidence component digests are malformed")
        if len(dict(rows)) != len(rows):
            raise ValueError("evidence component digest names must be unique")
        object.__setattr__(self, "component_digests", tuple(sorted(rows)))

    def component_digest(self, name: str) -> str:
        try:
            return dict(self.component_digests)[name]
        except KeyError as error:
            raise ValueError(f"unknown evidence component: {name}") from error


def build_evaluation_evidence(
    dataset,
    observations: tuple[RetrievalObservation, ...],
    binding: QualificationBinding,
    *,
    qualification_spec_id: str | None = None,
    reporting_profile: ConsumerQualificationProfile | None = None,
) -> EvaluationEvidence:
    observation_map = _observation_map(dataset, observations)
    canonical_observations = tuple(observation_map.values())
    observations_payload = [_observation_payload(item) for item in canonical_observations]
    metrics = evaluate_retrieval(dataset, canonical_observations)
    if qualification_spec_id is not None:
        if reporting_profile is not None:
            raise ValueError("a reporting profile cannot be used for certification")
        profile = _certification_profile(qualification_spec_id)
        qualification = certify_qualification(
            qualification_spec_id=qualification_spec_id,
            dataset=dataset,
            observations=canonical_observations,
            binding=binding,
        )
    else:
        profile = reporting_profile or ConsumerQualificationProfile()
        qualification = evaluate_qualification(metrics, binding, dataset, profile)
    manifest = _manifest(
        dataset_payload(dataset),
        observations_payload,
        binding,
        profile,
        metrics,
        qualification,
        qualification_spec_id,
    )
    encoded = canonical_json(manifest)
    evidence = EvaluationEvidence(
        encoded,
        sha256_bytes(encoded.encode("utf-8")),
        tuple(sorted(manifest["component_digests"].items())),  # type: ignore[union-attr]
    )
    return verify_evaluation_evidence(evidence)


def verify_evaluation_evidence(evidence: EvaluationEvidence) -> EvaluationEvidence:
    """Reconstruct and independently re-evaluate every retained semantic component."""

    if not isinstance(evidence, EvaluationEvidence):
        raise ValueError("evidence has an invalid runtime type")
    try:
        manifest = json.loads(
            evidence.canonical_json,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("evidence canonical JSON is malformed") from error
    if canonical_json(manifest) != evidence.canonical_json:
        raise ValueError("evidence bytes are not canonical")
    if sha256_bytes(evidence.canonical_json.encode("utf-8")) != evidence.manifest_digest:
        raise ValueError("evidence manifest digest mismatch")
    root = _exact_object("evidence manifest", manifest, _MANIFEST_FIELDS)
    if root["schema_version"] != RETRIEVAL_EVALUATION_SCHEMA:
        raise ValueError("evidence schema version mismatch")
    spec_id = root["qualification_spec_id"]
    if spec_id is not None and not isinstance(spec_id, str):
        raise ValueError("qualification_spec_id must be a string or null")

    supplied_components = _string_map("component_digests", root["component_digests"])
    if set(supplied_components) != _COMPONENTS:
        raise ValueError("evidence component digest names mismatch")
    component_hashes = _component_hashes(root)
    if (
        supplied_components != component_hashes
        or dict(evidence.component_digests) != component_hashes
    ):
        raise ValueError("evidence component digest mismatch")

    dataset = parse_retrieval_evaluation_dataset(canonical_json(root["dataset"]))
    if evaluation_dataset_digest(dataset) != supplied_components["dataset"]:
        raise ValueError("evidence dataset reconstruction mismatch")
    observations = _parse_observations(root["observations"])
    _require_canonical_observation_order(dataset, observations)
    binding = _parse_binding(root["binding"])
    metrics = evaluate_retrieval(dataset, observations)
    if spec_id is not None:
        profile = _certification_profile(spec_id)
        if root["qualification_profile"] != profile_payload(profile):
            raise ValueError("evidence certification profile is not package-owned")
        qualification = certify_qualification(
            qualification_spec_id=spec_id,
            dataset=dataset,
            observations=observations,
            binding=binding,
        )
    else:
        profile = _parse_profile(root["qualification_profile"])
        qualification = evaluate_qualification(metrics, binding, dataset, profile)
    if root["metrics"] != _metrics_payload(metrics):
        raise ValueError("evidence metrics contradict reconstructed observations")
    if root["qualification"] != _qualification_payload(qualification):
        raise ValueError("evidence qualification contradicts reconstructed evaluation")

    rebuilt = _manifest(
        dataset_payload(dataset),
        [_observation_payload(item) for item in observations],
        binding,
        profile,
        metrics,
        qualification,
        spec_id,
    )
    encoded = canonical_json(rebuilt)
    if encoded != evidence.canonical_json:
        raise ValueError("evidence canonical reconstruction mismatch")
    # Construct new containers and strings so no retained caller-owned alias survives.
    return EvaluationEvidence(
        encoded.encode("utf-8").decode("utf-8"),
        sha256_bytes(encoded.encode("utf-8")),
        tuple((name, digest) for name, digest in sorted(component_hashes.items())),
    )


def _manifest(dataset, observations, binding, profile, metrics, qualification, spec_id):
    metrics_value = _metrics_payload(metrics)
    qualification_value = _qualification_payload(qualification)
    profile_value = profile_payload(profile)
    components = {
        "binding": canonical_sha256(binding.to_dict()),
        "dataset": canonical_sha256(dataset),
        "metrics": canonical_sha256(metrics_value),
        "observations": canonical_sha256(observations),
        "profile": canonical_sha256(profile_value),
        "qualification": canonical_sha256(qualification_value),
    }
    return {
        "binding": binding.to_dict(),
        "component_digests": dict(sorted(components.items())),
        "dataset": dataset,
        "metrics": metrics_value,
        "observations": observations,
        "qualification": qualification_value,
        "qualification_profile": profile_value,
        "qualification_spec_id": spec_id,
        "schema_version": RETRIEVAL_EVALUATION_SCHEMA,
    }


def _component_hashes(root: dict[str, JsonValue]) -> dict[str, str]:
    return {
        "binding": canonical_sha256(root["binding"]),
        "dataset": canonical_sha256(root["dataset"]),
        "metrics": canonical_sha256(root["metrics"]),
        "observations": canonical_sha256(root["observations"]),
        "profile": canonical_sha256(root["qualification_profile"]),
        "qualification": canonical_sha256(root["qualification"]),
    }


def _observation_map(dataset, observations):
    if isinstance(observations, str | bytes) or any(
        not isinstance(item, RetrievalObservation) for item in observations
    ):
        raise ValueError("observations contains an invalid runtime type")
    result = {item.case_id: item for item in observations}
    if len(result) != len(observations):
        raise ValueError("observation case ids must be unique")
    if set(result) != {case.case_id for case in dataset.cases}:
        raise ValueError("observations must match dataset case ids exactly")
    return {case.case_id: result[case.case_id] for case in dataset.cases}


def _require_canonical_observation_order(dataset, observations) -> None:
    actual = tuple(item.case_id for item in observations)
    expected = tuple(case.case_id for case in dataset.cases)
    if len(set(actual)) != len(actual):
        raise ValueError("evidence observation case ids must be unique")
    if actual != expected:
        raise ValueError("evidence observations are not in canonical dataset case order")


def _parse_observations(value: object) -> tuple[RetrievalObservation, ...]:
    if not isinstance(value, list):
        raise ValueError("evidence observations must be an array")
    observations = []
    for index, raw in enumerate(value):
        row = _exact_object(
            f"observations[{index}]",
            raw,
            {
                "case_id",
                "latency_us",
                "ranked_locators",
                "request_bytes",
                "response_bytes",
                "status",
            },
        )
        ranked_raw = row["ranked_locators"]
        if not isinstance(ranked_raw, list):
            raise ValueError("ranked_locators must be an array")
        ranked = []
        for ranked_index, item in enumerate(ranked_raw):
            ranked_row = _exact_object(
                f"ranked_locators[{ranked_index}]", item, {"locator", "rank"}
            )
            ranked.append(
                RankedLocator(ranked_row["locator"], ranked_row["rank"])  # type: ignore[arg-type]
            )
        observations.append(
            RetrievalObservation(
                row["case_id"],  # type: ignore[arg-type]
                row["status"],  # type: ignore[arg-type]
                tuple(ranked),
                row["latency_us"],  # type: ignore[arg-type]
                row["request_bytes"],  # type: ignore[arg-type]
                row["response_bytes"],  # type: ignore[arg-type]
            )
        )
    return tuple(observations)


def _parse_binding(value: object) -> QualificationBinding:
    fields = {
        "capability_fingerprint",
        "cleanup_receipt",
        "contract_version",
        "core_revision",
        "dataset_digest",
        "index_identity",
        "ranking_policy",
        "retrieval_profile",
        "service_revision",
    }
    row = _exact_object("binding", value, fields)
    return QualificationBinding(
        service_revision=row["service_revision"],
        core_revision=row["core_revision"],
        contract_version=row["contract_version"],
        ranking_policy=row["ranking_policy"],
        capability_fingerprint=row["capability_fingerprint"],
        retrieval_profile=row["retrieval_profile"],
        index_identity=row["index_identity"],
        dataset_digest=row["dataset_digest"],
        cleanup_receipt=row["cleanup_receipt"],  # type: ignore[arg-type]
    )


def _parse_profile(value: object) -> ConsumerQualificationProfile:
    fields = {
        "maximum_cross_scope_leakage_count",
        "maximum_failure_count",
        "maximum_no_gold_with_results_count",
        "maximum_p95_latency_us",
        "maximum_timeout_count",
        "maximum_topology_violation_count",
        "minimum_mrr_at_10",
        "minimum_ndcg_at_10",
        "minimum_recall_at_10",
        "minimum_recall_at_5",
        "profile_id",
    }
    row = _exact_object("qualification_profile", value, fields)
    return ConsumerQualificationProfile(
        profile_id=row["profile_id"],  # type: ignore[arg-type]
        minimum_recall_at_5=_parse_rational("minimum_recall_at_5", row["minimum_recall_at_5"]),
        minimum_mrr_at_10=_parse_rational("minimum_mrr_at_10", row["minimum_mrr_at_10"]),
        maximum_cross_scope_leakage_count=row[  # type: ignore[arg-type]
            "maximum_cross_scope_leakage_count"
        ],
        maximum_topology_violation_count=row[  # type: ignore[arg-type]
            "maximum_topology_violation_count"
        ],
        maximum_p95_latency_us=row["maximum_p95_latency_us"],  # type: ignore[arg-type]
        minimum_recall_at_10=_parse_optional_rational(
            "minimum_recall_at_10", row["minimum_recall_at_10"]
        ),
        minimum_ndcg_at_10=_parse_optional_rational(
            "minimum_ndcg_at_10", row["minimum_ndcg_at_10"]
        ),
        maximum_failure_count=row["maximum_failure_count"],  # type: ignore[arg-type]
        maximum_timeout_count=row["maximum_timeout_count"],  # type: ignore[arg-type]
        maximum_no_gold_with_results_count=row[  # type: ignore[arg-type]
            "maximum_no_gold_with_results_count"
        ],
    )


def _parse_rational(name: str, value: object) -> Rational:
    row = _exact_object(name, value, {"denominator", "numerator"})
    return Rational(row["numerator"], row["denominator"])  # type: ignore[arg-type]


def _parse_optional_rational(name: str, value: object) -> Rational | None:
    return None if value is None else _parse_rational(name, value)


def _observation_payload(item: RetrievalObservation) -> dict[str, JsonValue]:
    return {
        "case_id": item.case_id,
        "latency_us": item.latency_us,
        "ranked_locators": [
            {"locator": row.locator, "rank": row.rank} for row in item.ranked_locators
        ],
        "request_bytes": item.request_bytes,
        "response_bytes": item.response_bytes,
        "status": item.status,
    }


def _metrics_payload(metrics: RetrievalEvaluationMetrics) -> dict[str, JsonValue]:
    return {
        "bytes": {
            "maximum_request_bytes": metrics.bytes.maximum_request_bytes,
            "maximum_response_bytes": metrics.bytes.maximum_response_bytes,
            "total_request_bytes": metrics.bytes.total_request_bytes,
            "total_response_bytes": metrics.bytes.total_response_bytes,
        },
        "case_count": metrics.case_count,
        "cross_scope_leakage_count": metrics.cross_scope_leakage_count,
        "failure_count": metrics.failure_count,
        "latency_us": {
            "p50": metrics.latency.p50_us,
            "p95": metrics.latency.p95_us,
            "p99": metrics.latency.p99_us,
        },
        "mrr_at_10": metrics.mrr_at_10.to_dict(),
        "ndcg_at_10": metrics.ndcg_at_10.to_dict(),
        "no_gold_case_count": metrics.no_gold_case_count,
        "no_gold_with_results_count": metrics.no_gold_with_results_count,
        "ranked_gold_case_count": metrics.ranked_gold_case_count,
        "recall_at_10": metrics.recall_at_10.to_dict(),
        "recall_at_5": metrics.recall_at_5.to_dict(),
        "success_count": metrics.success_count,
        "timeout_count": metrics.timeout_count,
        "topology_violation_count": metrics.topology_violation_count,
    }


def _qualification_payload(result: QualificationResult) -> dict[str, JsonValue]:
    return {
        "binding_issue_codes": list(result.binding_issue_codes),
        "gates": [
            {
                "gate_id": gate.gate_id,
                "observed": (
                    gate.observed.to_dict()
                    if isinstance(gate.observed, Rational)
                    else gate.observed
                ),
                "passed": gate.passed,
                "threshold": (
                    gate.threshold.to_dict()
                    if isinstance(gate.threshold, Rational)
                    else gate.threshold
                ),
            }
            for gate in result.gates
        ],
        "qualified": result.qualified,
    }


def _exact_object(name: str, value: object, fields: set[str]) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if set(value) != fields:
        raise ValueError(f"{name} fields mismatch")
    return value


def _string_map(name: str, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError(f"{name} must be a string map")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_float(value: str):
    raise ValueError(f"floating-point values are forbidden: {value}")


__all__ = (
    "EvaluationEvidence",
    "RETRIEVAL_EVALUATION_SCHEMA",
    "build_evaluation_evidence",
    "verify_evaluation_evidence",
)
