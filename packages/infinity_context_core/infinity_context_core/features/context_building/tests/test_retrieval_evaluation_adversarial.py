"""Focused adversarial probes for Retrieval qualification integrity."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from infinity_context_core.features.context_building.domain.locator_retrieval import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION,
    LOCATOR_RETRIEVAL_RANKING_POLICY,
)
from infinity_context_core.features.context_building.domain.retrieval_canonical import (
    canonical_json,
    canonical_sha256,
    evaluation_dataset_digest,
)
from infinity_context_core.features.context_building.domain.retrieval_dataset import (
    load_retrieval_evaluation_dataset,
    parse_retrieval_evaluation_dataset,
)
from infinity_context_core.features.context_building.domain.retrieval_evaluation import (
    GoldLocator,
    RankedLocator,
    Rational,
    RetrievalEvaluationCase,
    RetrievalEvaluationDataset,
    RetrievalObservation,
    evaluate_retrieval,
)
from infinity_context_core.features.context_building.domain.retrieval_evidence import (
    build_evaluation_evidence,
    verify_evaluation_evidence,
)
from infinity_context_core.features.context_building.domain.retrieval_qualification import (
    SYNTHETIC_QUALIFICATION_SPEC_ID,
    ConsumerQualificationProfile,
    QualificationBinding,
    certify_qualification,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_eval/locator-eval-synthetic-v1.json"


def _load_fixture() -> RetrievalEvaluationDataset:
    return load_retrieval_evaluation_dataset(FIXTURE)


def _observation(case_id: str, *ranked: tuple[str, int]) -> RetrievalObservation:
    return RetrievalObservation(
        case_id,
        "success",
        tuple(RankedLocator(locator, rank) for locator, rank in ranked),
        100,
        10,
        20,
    )


def _perfect_observations(dataset: RetrievalEvaluationDataset) -> tuple[RetrievalObservation, ...]:
    return tuple(
        _observation(
            case.case_id,
            *((gold.locator, index) for index, gold in enumerate(case.gold_locators, 1)),
        )
        for case in dataset.cases
    )


def _binding(dataset: RetrievalEvaluationDataset) -> QualificationBinding:
    return QualificationBinding(
        service_revision="service:0123456789",
        core_revision="core:0123456789",
        contract_version=LOCATOR_RETRIEVAL_CONTRACT_VERSION,
        ranking_policy=LOCATOR_RETRIEVAL_RANKING_POLICY,
        capability_fingerprint="sha256:capability",
        retrieval_profile="retrieval:synthetic",
        index_identity="index:synthetic:1",
        dataset_digest=evaluation_dataset_digest(dataset),
        cleanup_receipt="sha256:cleanup",
    )


def test_caller_created_dataset_and_digest_shaped_spec_cannot_certify() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["dataset_id"] = "caller-created-dataset"
    dataset = parse_retrieval_evaluation_dataset(json.dumps(payload))
    observations = _perfect_observations(dataset)

    result = certify_qualification(
        qualification_spec_id=evaluation_dataset_digest(dataset),
        dataset=dataset,
        observations=observations,
        binding=_binding(dataset),
    )

    assert result.qualified is False
    assert "missing:trusted_qualification_spec" in result.binding_issue_codes


def test_certification_recomputes_failed_observations_and_rejects_forged_metrics() -> None:
    dataset = _load_fixture()
    failed = tuple(
        RetrievalObservation(case.case_id, "failure", (), 100, 10, 20) for case in dataset.cases
    )
    honest = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=failed,
        binding=_binding(dataset),
    )
    forged = replace(
        evaluate_retrieval(dataset, _perfect_observations(dataset)),
        failure_count=0,
        timeout_count=0,
        recall_at_5=Rational(1, 1),
        mrr_at_10=Rational(1, 1),
    )

    assert sum(item.status == "failure" for item in failed) == 10
    assert honest.qualified is False
    assert {gate.gate_id: gate.passed for gate in honest.gates}["failure_count"] is False
    with pytest.raises(TypeError, match="metrics"):
        certify_qualification(
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            dataset=dataset,
            observations=failed,
            binding=_binding(dataset),
            metrics=forged,  # type: ignore[call-arg]
        )


def test_certification_rejects_duck_typed_profile_and_binding_authority() -> None:
    dataset = _load_fixture()
    observations = _perfect_observations(dataset)

    class CallerProfile:
        profile_id = "consumer-retrieval-qualification.v1"
        threshold_fingerprint = "sha256:alleged"
        minimum_recall_at_5 = Rational(0, 1)
        minimum_mrr_at_10 = Rational(0, 1)

    class CallerBinding:
        def to_dict(self):
            return _binding(dataset).to_dict()

    with pytest.raises(TypeError, match="profile"):
        certify_qualification(
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            dataset=dataset,
            observations=observations,
            binding=_binding(dataset),
            profile=CallerProfile(),  # type: ignore[call-arg]
        )
    with pytest.raises(ValueError, match="binding.*runtime type"):
        certify_qualification(
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            dataset=dataset,
            observations=observations,
            binding=CallerBinding(),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="reporting profile cannot be used"):
        build_evaluation_evidence(
            dataset,
            observations,
            _binding(dataset),
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            reporting_profile=ConsumerQualificationProfile(
                profile_id="caller-forged-profile.v1",
                minimum_recall_at_5=Rational(0, 1),
                minimum_mrr_at_10=Rational(0, 1),
            ),
        )


@pytest.mark.parametrize(
    ("field", "expected", "candidate_value"),
    [
        ("source_id", "source:approved", "source:wrong"),
        ("attribute:status", "active", "inactive"),
        ("occurred_on", "2026-08-20", "2025-08-20"),
    ],
)
def test_neighbor_cannot_launder_source_attribute_or_time_filter_exclusions(
    field: str, expected: str, candidate_value: str
) -> None:
    dataset = _neighbor_filter_dataset(field, expected, candidate_value, excluded=True)
    metrics = evaluate_retrieval(
        dataset,
        (_observation("neighbor-hard-filter", ("loc:seed", 1), ("loc:neighbor", 2)),),
    )

    assert metrics.topology_violation_count == 1


def test_explicit_filter_exclusion_survives_legal_same_filter_adjacency() -> None:
    dataset = _neighbor_filter_dataset(
        "source_id", "source:approved", "source:approved", excluded=True
    )

    metrics = evaluate_retrieval(
        dataset,
        (_observation("neighbor-hard-filter", ("loc:seed", 1), ("loc:neighbor", 2)),),
    )

    assert metrics.topology_violation_count == 1


def test_legal_same_filter_neighbor_context_remains_allowed() -> None:
    dataset = _neighbor_filter_dataset(
        "source_id", "source:approved", "source:approved", excluded=False
    )

    metrics = evaluate_retrieval(
        dataset,
        (_observation("neighbor-hard-filter", ("loc:seed", 1), ("loc:neighbor", 2)),),
    )

    assert metrics.topology_violation_count == 0


def test_filter_excluded_locators_are_zero_tolerance_topology_failures() -> None:
    dataset = _load_fixture()
    observations = tuple(
        _observation(
            case.case_id,
            *((item.locator, index) for index, item in enumerate(case.gold_locators, 1)),
            *(
                (locator, len(case.gold_locators) + index)
                for index, locator in enumerate(
                    case.filter_excluded_locators if case.gold_locators else (), 1
                )
            ),
        )
        for case in dataset.cases
    )
    metrics = evaluate_retrieval(dataset, observations)
    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=observations,
        binding=_binding(dataset),
    )

    assert metrics.topology_violation_count == 7
    assert metrics.cross_scope_leakage_count == 0
    assert result.qualified is False
    assert {gate.gate_id: gate.passed for gate in result.gates}["topology_violation_count"] is False


def test_unlisted_wrong_scope_corpus_rows_are_zero_tolerance_topology_failures() -> None:
    dataset = _load_fixture()
    records = dict(dataset.records_payload)
    observations = []
    injected = 0
    for case in dataset.cases:
        scope = next(value for _, field, value in case.filter_specs if field == "scope_id")
        wrong_scope = next(
            (
                locator
                for locator, record in records.items()
                if record["scope_id"] != scope and locator not in case.forbidden_scope_locators
            ),
            None,
        )
        ranked = [(item.locator, index) for index, item in enumerate(case.gold_locators, 1)]
        if case.gold_locators:
            assert wrong_scope is not None
            ranked.append((wrong_scope, len(ranked) + 1))
            injected += 1
        observations.append(_observation(case.case_id, *ranked))
    canonical_observations = tuple(observations)
    metrics = evaluate_retrieval(dataset, canonical_observations)
    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=canonical_observations,
        binding=_binding(dataset),
    )

    assert injected == 9
    assert metrics.topology_violation_count == 9
    assert metrics.cross_scope_leakage_count == 9
    assert result.qualified is False


def test_unknown_stale_and_illegal_neighbor_locators_fail_topology_gate() -> None:
    dataset = _load_fixture()
    observations = list(_perfect_observations(dataset))
    target = next(
        index for index, row in enumerate(observations) if row.case_id == "neighbor-expansion"
    )
    observations[target] = _observation(
        "neighbor-expansion",
        ("lx-001", 1),
        ("lx-003", 2),
        ("lx-002", 3),
        ("stale:missing", 4),
    )

    metrics = evaluate_retrieval(dataset, tuple(observations))

    assert (
        next(case for case in dataset.cases if case.case_id == "neighbor-expansion").neighbor_radius
        == 1
    )
    assert metrics.topology_violation_count == 2


def test_dataset_records_and_nested_attributes_are_deeply_detached_and_frozen() -> None:
    record = {
        "attributes": {"status": "active", "tags": ["one", "two"]},
        "locator": "loc:a",
        "occurred_on": "date:unspecified",
        "scope_id": "scope:test",
        "source_id": "source:test",
        "text": "Detached record",
    }
    case = RetrievalEvaluationCase(
        case_id="detach",
        variation_family_id="family:detach",
        query_variant_ids=("query:detach",),
        gold_locators=(GoldLocator("loc:a"),),
        filter_ids=("filter:scope-test",),
        filter_specs=(("filter:scope-test", "scope_id", "scope:test"),),
        scenario_tags=("synthetic_test",),
    )
    dataset = RetrievalEvaluationDataset(
        "dataset:test", ("loc:a",), (case,), records_payload=(("loc:a", record),)
    )
    digest = evaluation_dataset_digest(dataset)
    frozen_record = dict(dataset.records_payload)["loc:a"]

    record["scope_id"] = "scope:caller-mutated"
    record["attributes"]["status"] = "retired"
    record["attributes"]["tags"].append("three")
    with pytest.raises(TypeError):
        frozen_record["scope_id"] = "scope:forbidden"  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen_record["attributes"]["status"] = "retired"  # type: ignore[index]

    assert frozen_record["scope_id"] == "scope:test"
    assert frozen_record["attributes"]["tags"] == ("one", "two")
    assert evaluation_dataset_digest(dataset) == digest
    assert (
        evaluate_retrieval(
            dataset, (_observation("detach", ("loc:a", 1)),)
        ).topology_violation_count
        == 0
    )


def test_semantically_forged_evidence_fails_after_all_hashes_are_recomputed() -> None:
    dataset = _load_fixture()
    evidence = build_evaluation_evidence(
        dataset,
        _perfect_observations(dataset),
        _binding(dataset),
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
    )
    mutations = (
        lambda manifest: manifest["dataset"]["cases"][0]["gold_locators"][0].__setitem__(
            "relevance", 2
        ),
        lambda manifest: manifest["metrics"].__setitem__("failure_count", 7),
        lambda manifest: manifest["metrics"].__setitem__("timeout_count", 3),
        lambda manifest: manifest["qualification"]["gates"][3].__setitem__("passed", False),
        lambda manifest: manifest["observations"][0].__setitem__("status", "failure"),
        lambda manifest: manifest["binding"].__setitem__("dataset_digest", "sha256:substituted"),
    )
    for mutate in mutations:
        manifest = json.loads(evidence.canonical_json)
        mutate(manifest)
        forged = _rehash_manifest(evidence, manifest)
        with pytest.raises(ValueError):
            verify_evaluation_evidence(forged)


def test_rehashed_reordered_or_duplicate_observations_fail_closed() -> None:
    dataset = _load_fixture()
    with pytest.raises(ValueError, match="canonical dataset case order"):
        certify_qualification(
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            dataset=dataset,
            observations=tuple(reversed(_perfect_observations(dataset))),
            binding=_binding(dataset),
        )
    evidence = build_evaluation_evidence(
        dataset,
        _perfect_observations(dataset),
        _binding(dataset),
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
    )

    reordered = json.loads(evidence.canonical_json)
    reordered["observations"].reverse()
    with pytest.raises(ValueError, match="canonical dataset case order"):
        verify_evaluation_evidence(_rehash_manifest(evidence, reordered))

    duplicated = json.loads(evidence.canonical_json)
    duplicated["observations"][-1] = duplicated["observations"][0]
    with pytest.raises(ValueError, match="case ids must be unique"):
        verify_evaluation_evidence(_rehash_manifest(evidence, duplicated))


def _neighbor_filter_dataset(
    field: str,
    expected: str,
    candidate_value: str,
    *,
    excluded: bool,
) -> RetrievalEvaluationDataset:
    def record(locator: str, value: str):
        payload = {
            "attributes": {"status": "active"},
            "locator": locator,
            "occurred_on": "2026-08-20",
            "scope_id": "scope:test",
            "source_id": "source:approved",
            "text": f"Synthetic {locator}",
        }
        if field == "attribute:status":
            payload["attributes"]["status"] = value
        else:
            payload[field] = value
        return payload

    case = RetrievalEvaluationCase(
        case_id="neighbor-hard-filter",
        variation_family_id="family:neighbor-hard-filter",
        query_variant_ids=("query:neighbor-hard-filter",),
        gold_locators=(GoldLocator("loc:seed"),),
        filter_excluded_locators=("loc:neighbor",) if excluded else (),
        filter_ids=("filter:hard", "filter:scope"),
        filter_specs=(
            ("filter:hard", field, expected),
            ("filter:scope", "scope_id", "scope:test"),
        ),
        neighbor_radius=1,
        scenario_tags=("neighbors", "hard_filter"),
    )
    return RetrievalEvaluationDataset(
        "dataset:neighbor-hard-filter",
        ("loc:seed", "loc:neighbor"),
        (case,),
        records_payload=(
            ("loc:seed", record("loc:seed", expected)),
            ("loc:neighbor", record("loc:neighbor", candidate_value)),
        ),
        neighbor_pairs=(("loc:seed", "loc:neighbor"),),
    )


def _rehash_manifest(evidence, manifest):
    components = {
        "binding": canonical_sha256(manifest["binding"]),
        "dataset": canonical_sha256(manifest["dataset"]),
        "metrics": canonical_sha256(manifest["metrics"]),
        "observations": canonical_sha256(manifest["observations"]),
        "profile": canonical_sha256(manifest["qualification_profile"]),
        "qualification": canonical_sha256(manifest["qualification"]),
    }
    manifest["component_digests"] = components
    encoded = canonical_json(manifest)
    return replace(
        evidence,
        canonical_json=encoded,
        manifest_digest=canonical_sha256(manifest),
        component_digests=tuple(sorted(components.items())),
    )
