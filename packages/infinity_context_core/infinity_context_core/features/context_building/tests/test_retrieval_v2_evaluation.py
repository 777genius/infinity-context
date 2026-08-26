from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from infinity_context_core.features.context_building.domain.locator_retrieval_v2 import (
    LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
    LOCATOR_RETRIEVAL_RANKING_POLICY_V2,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_canonical import (
    canonical_json,
    canonical_sha256,
    evaluation_dataset_digest,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_dataset import (
    load_retrieval_evaluation_dataset,
    parse_retrieval_evaluation_dataset,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_evaluation import (
    GoldLocator,
    RankedLocator,
    Rational,
    RetrievalEvaluationCase,
    RetrievalEvaluationDataset,
    RetrievalObservation,
    evaluate_retrieval,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_evidence import (
    build_evaluation_evidence,
    verify_evaluation_evidence,
)
from infinity_context_core.features.context_building.domain.retrieval_v2_qualification import (
    DEFAULT_QUALIFICATION_PROFILE_ID,
    SYNTHETIC_QUALIFICATION_SPEC_ID,
    ConsumerQualificationProfile,
    QualificationBinding,
    certify_qualification,
    evaluate_qualification,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
FIXTURE = REPO_ROOT / "tests/fixtures/retrieval_eval/locator-eval-synthetic-v1.json"


def _case(
    case_id: str,
    *,
    gold: tuple[GoldLocator, ...] = (GoldLocator("loc:a"),),
    forbidden: tuple[str, ...] = (),
) -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id=case_id,
        variation_family_id=f"family:{case_id}",
        query_variant_ids=(f"query:{case_id}",),
        gold_locators=gold,
        forbidden_scope_locators=forbidden,
        filter_ids=("filter:scope-test",),
        filter_specs=(("filter:scope-test", "scope_id", "scope:test"),),
        scenario_tags=("synthetic_test",),
    )


def _dataset(*cases: RetrievalEvaluationCase) -> RetrievalEvaluationDataset:
    referenced = {
        "loc:a",
        "loc:b",
        "loc:c",
        "loc:d",
        "loc:e",
        "loc:f",
        "loc:forbidden",
        "loc:other",
    }
    referenced.update(item.locator for case in cases for item in case.gold_locators)
    referenced.update(locator for case in cases for locator in case.forbidden_scope_locators)
    return RetrievalEvaluationDataset("dataset:test", tuple(referenced), tuple(cases))


def _observation(
    case_id: str,
    *ranked: tuple[str, int],
    status: str = "success",
    latency_us: int = 100,
    request_bytes: int = 10,
    response_bytes: int = 20,
) -> RetrievalObservation:
    return RetrievalObservation(
        case_id,
        status,
        tuple(RankedLocator(locator, rank) for locator, rank in ranked),
        latency_us,
        request_bytes,
        response_bytes,
    )


def _binding(dataset: RetrievalEvaluationDataset) -> QualificationBinding:
    return QualificationBinding(
        service_revision="service:0123456789",
        core_revision="core:0123456789",
        contract_version=LOCATOR_RETRIEVAL_CONTRACT_VERSION_V2,
        ranking_policy=LOCATOR_RETRIEVAL_RANKING_POLICY_V2,
        capability_fingerprint="sha256:capability",
        retrieval_profile="retrieval:synthetic",
        index_identity="index:synthetic:1",
        dataset_digest=evaluation_dataset_digest(dataset),
        cleanup_receipt="sha256:cleanup",
    )


def _load_fixture() -> RetrievalEvaluationDataset:
    return load_retrieval_evaluation_dataset(FIXTURE)


def _perfect_observations(dataset: RetrievalEvaluationDataset) -> tuple[RetrievalObservation, ...]:
    return tuple(
        _observation(
            case.case_id,
            *((gold.locator, index) for index, gold in enumerate(case.gold_locators, 1)),
        )
        for case in dataset.cases
    )


def test_ranked_inputs_accept_explicit_ranks_through_ten_and_missing_ranks() -> None:
    observation = _observation(
        "case",
        ("loc:a", 1),
        ("loc:b", 3),
        ("loc:c", 10),
    )
    assert tuple(item.rank for item in observation.ranked_locators) == (1, 3, 10)

    with pytest.raises(ValueError, match="1..10"):
        RankedLocator("loc:a", 11)


def test_multiple_golds_use_micro_recall_and_graded_exact_ndcg() -> None:
    dataset = _dataset(
        _case(
            "multi",
            gold=(GoldLocator("loc:a", 3), GoldLocator("loc:b", 1)),
        )
    )
    metrics = evaluate_retrieval(
        dataset,
        (_observation("multi", ("loc:b", 1), ("loc:a", 2)),),
    )

    assert metrics.recall_at_5 == Rational(2, 2)
    assert metrics.recall_at_10 == Rational(2, 2)
    assert metrics.mrr_at_10 == Rational(1, 1)
    exact = Fraction(1_000_000_000_000 + 7 * 630_929_753_571, 7_000_000_000_000 + 630_929_753_571)
    assert metrics.ndcg_at_10 == Rational.from_fraction(exact)


def test_no_gold_is_reported_without_diluting_ranked_metric_denominators() -> None:
    dataset = _dataset(
        _case("gold"),
        _case("unsupported", gold=(), forbidden=("loc:forbidden",)),
    )
    metrics = evaluate_retrieval(
        dataset,
        (
            _observation("gold", ("loc:a", 1)),
            _observation("unsupported", ("loc:other", 1)),
        ),
    )

    assert metrics.ranked_gold_case_count == 1
    assert metrics.no_gold_case_count == 1
    assert metrics.no_gold_with_results_count == 1
    assert metrics.recall_at_5 == Rational(1, 1)


def test_all_no_gold_dataset_exposes_zero_metric_denominators() -> None:
    dataset = _dataset(_case("unsupported", gold=()))
    metrics = evaluate_retrieval(dataset, (_observation("unsupported"),))

    assert metrics.recall_at_5 == Rational(0, 0)
    assert metrics.recall_at_10 == Rational(0, 0)
    assert metrics.mrr_at_10 == Rational(0, 0)
    assert metrics.ndcg_at_10 == Rational(0, 0)
    result = evaluate_qualification(
        metrics,
        _binding(dataset),
        dataset,
    )
    assert result.qualified is False


def test_failures_and_timeouts_remain_zero_scored_in_ranking_denominators() -> None:
    dataset = _dataset(_case("ok"), _case("failed"), _case("timed-out"))
    metrics = evaluate_retrieval(
        dataset,
        (
            _observation("ok", ("loc:a", 2)),
            _observation("failed", status="failure", latency_us=200),
            _observation("timed-out", status="timeout", latency_us=3_000_000),
        ),
    )

    assert metrics.recall_at_5 == Rational(1, 3)
    assert metrics.recall_at_10 == Rational(1, 3)
    assert metrics.mrr_at_10 == Rational(1, 6)
    assert metrics.failure_count == 1
    assert metrics.timeout_count == 1
    assert metrics.latency.p95_us == 3_000_000


def test_ties_are_order_independent_and_use_competition_rank_discount() -> None:
    dataset = _dataset(_case("tie", gold=(GoldLocator("loc:a", 2),)))
    first = _observation("tie", ("loc:a", 1), ("loc:b", 1), ("loc:c", 3))
    second = _observation("tie", ("loc:c", 3), ("loc:b", 1), ("loc:a", 1))

    assert (
        evaluate_retrieval(dataset, (first,)).ndcg_at_10
        == evaluate_retrieval(dataset, (second,)).ndcg_at_10
    )
    with pytest.raises(ValueError, match="non-overlapping competition ranks"):
        _observation("tie", ("loc:a", 1), ("loc:b", 1), ("loc:c", 2))


def test_duplicate_ranked_or_gold_locators_fail_closed() -> None:
    with pytest.raises(ValueError, match="duplicate locators"):
        _observation("duplicate", ("loc:a", 1), ("loc:a", 2))
    with pytest.raises(ValueError, match="gold_locators must not contain duplicates"):
        _case("duplicate-gold", gold=(GoldLocator("loc:a"), GoldLocator("loc:a", 2)))


def test_forbidden_locator_occurrences_are_counted_as_cross_scope_leakage() -> None:
    dataset = _dataset(
        _case("attack", forbidden=("loc:forbidden",)),
        _case("control", gold=(GoldLocator("loc:b"),), forbidden=("loc:forbidden",)),
    )
    metrics = evaluate_retrieval(
        dataset,
        (
            _observation("attack", ("loc:forbidden", 1), ("loc:a", 2)),
            _observation("control", ("loc:forbidden", 4), ("loc:b", 5)),
        ),
    )

    assert metrics.cross_scope_leakage_count == 2


@pytest.mark.parametrize(
    ("latencies", "expected"),
    [
        ((7,), (7, 7, 7)),
        ((1, 2), (1, 2, 2)),
        (tuple(range(1, 101)), (50, 95, 99)),
    ],
)
def test_nearest_rank_percentile_edges(
    latencies: tuple[int, ...], expected: tuple[int, int, int]
) -> None:
    cases = tuple(_case(f"case-{index}") for index in range(len(latencies)))
    dataset = _dataset(*cases)
    observations = tuple(
        _observation(case.case_id, ("loc:a", 1), latency_us=latency)
        for case, latency in zip(cases, latencies, strict=True)
    )

    latency = evaluate_retrieval(dataset, observations).latency
    assert (latency.p50_us, latency.p95_us, latency.p99_us) == expected


def test_request_response_bytes_are_exactly_accounted_for_all_outcomes() -> None:
    dataset = _dataset(_case("ok"), _case("failure"))
    metrics = evaluate_retrieval(
        dataset,
        (
            _observation("ok", ("loc:a", 1), request_bytes=11, response_bytes=31),
            _observation("failure", status="failure", request_bytes=13, response_bytes=7),
        ),
    )

    assert metrics.bytes.total_request_bytes == 24
    assert metrics.bytes.total_response_bytes == 38
    assert metrics.bytes.maximum_request_bytes == 13
    assert metrics.bytes.maximum_response_bytes == 31


def test_observations_must_cover_each_case_exactly_once() -> None:
    dataset = _dataset(_case("a"), _case("b"))
    with pytest.raises(ValueError, match="match dataset case ids exactly"):
        evaluate_retrieval(dataset, (_observation("a", ("loc:a", 1)),))
    with pytest.raises(ValueError, match="case ids must be unique"):
        evaluate_retrieval(
            dataset,
            (
                _observation("a", ("loc:a", 1)),
                _observation("a", ("loc:a", 1)),
            ),
        )


def test_default_consumer_profile_has_immutable_exact_zero_failure_gates() -> None:
    dataset = _load_fixture()
    observations = _perfect_observations(dataset)
    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=observations,
        binding=_binding(dataset),
    )

    assert result.qualified is True
    assert tuple(item.gate_id for item in result.gates) == (
        "recall_at_5",
        "mrr_at_10",
        "cross_scope_leakage_count",
        "topology_violation_count",
        "p95_latency_us",
        "failure_count",
        "timeout_count",
        "no_gold_with_results_count",
    )
    assert ConsumerQualificationProfile().minimum_recall_at_5 == Rational(9, 10)
    assert ConsumerQualificationProfile().minimum_mrr_at_10 == Rational(4, 5)
    assert ConsumerQualificationProfile().maximum_failure_count == 0
    assert ConsumerQualificationProfile().maximum_timeout_count == 0


def test_recall_at_10_ndcg_and_accounting_gates_are_configurable() -> None:
    dataset = _dataset(_case("failure"))
    metrics = evaluate_retrieval(dataset, (_observation("failure", status="failure"),))
    profile = ConsumerQualificationProfile(
        profile_id="consumer-retrieval-qualification.strict-test.v1",
        minimum_recall_at_10=Rational(1, 1),
        minimum_ndcg_at_10=Rational(1, 1),
        maximum_failure_count=0,
        maximum_timeout_count=0,
        maximum_no_gold_with_results_count=0,
    )
    result = evaluate_qualification(
        metrics,
        _binding(dataset),
        dataset,
        profile,
    )

    gates = {item.gate_id: item.passed for item in result.gates}
    assert gates["recall_at_10"] is False
    assert gates["ndcg_at_10"] is False
    assert gates["failure_count"] is False
    assert gates["timeout_count"] is True


@pytest.mark.parametrize(
    "field",
    [
        "service_revision",
        "core_revision",
        "contract_version",
        "ranking_policy",
        "capability_fingerprint",
        "retrieval_profile",
        "index_identity",
        "dataset_digest",
        "cleanup_receipt",
    ],
)
def test_missing_qualification_binding_fields_are_unqualified(field: str) -> None:
    dataset = _dataset(_case("case"))
    metrics = evaluate_retrieval(dataset, (_observation("case", ("loc:a", 1)),))
    binding = replace(_binding(dataset), **{field: None})

    result = evaluate_qualification(
        metrics,
        binding,
        dataset,
    )
    assert result.qualified is False
    assert f"missing:{field}" in result.binding_issue_codes


def test_registered_binding_drift_and_dataset_mutation_are_unqualified() -> None:
    dataset = _load_fixture()
    observations = _perfect_observations(dataset)
    expected = _binding(dataset)
    drifted = replace(expected, service_revision="service:other")
    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=observations,
        binding=drifted,
    )
    assert "drift:service_revision" in result.binding_issue_codes

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["records"][0]["text"] += " changed"
    mutated = parse_retrieval_evaluation_dataset(json.dumps(payload))
    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=mutated,
        observations=observations,
        binding=expected,
    )
    assert "drift:dataset_digest" in result.binding_issue_codes


def test_scoring_without_registered_spec_is_explicitly_unqualified() -> None:
    dataset = _dataset(_case("case"))
    metrics = evaluate_retrieval(dataset, (_observation("case", ("loc:a", 1)),))

    result = evaluate_qualification(metrics, _binding(dataset), dataset)

    assert result.qualified is False
    assert "missing:trusted_qualification_spec" in result.binding_issue_codes


@pytest.mark.parametrize(
    "field",
    [
        "service_revision",
        "core_revision",
        "contract_version",
        "ranking_policy",
        "capability_fingerprint",
        "retrieval_profile",
        "index_identity",
        "dataset_digest",
        "cleanup_receipt",
    ],
)
def test_every_trusted_binding_and_cleanup_drift_is_unqualified(field: str) -> None:
    dataset = _load_fixture()
    expected = _binding(dataset)
    actual = replace(expected, **{field: f"drifted:{field}"})
    observations = _perfect_observations(dataset)

    result = certify_qualification(
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
        dataset=dataset,
        observations=observations,
        binding=actual,
    )

    assert result.qualified is False
    assert f"drift:{field}" in result.binding_issue_codes


def test_default_profile_rejects_threshold_substitution_and_custom_profiles_get_new_digest() -> (
    None
):
    default = ConsumerQualificationProfile()
    with pytest.raises(ValueError, match="immutable exact thresholds"):
        replace(default, minimum_recall_at_5=Rational(0, 1))
    with pytest.raises(ValueError, match="immutable exact thresholds"):
        replace(default, maximum_failure_count=1)

    custom = replace(
        default,
        profile_id="consumer-retrieval-qualification.custom.v1",
        minimum_recall_at_5=Rational(4, 5),
    )
    assert custom.profile_id != DEFAULT_QUALIFICATION_PROFILE_ID
    assert custom.threshold_fingerprint != default.threshold_fingerprint

    dataset = _dataset(_case("custom"))
    binding = _binding(dataset)
    metrics = evaluate_retrieval(dataset, (_observation("custom", ("loc:a", 1)),))
    untrusted = evaluate_qualification(
        metrics,
        binding,
        dataset,
        custom,
    )
    assert untrusted.qualified is False
    assert "missing:trusted_qualification_spec" in untrusted.binding_issue_codes
    with pytest.raises(TypeError, match="profile"):
        certify_qualification(
            qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
            dataset=dataset,
            observations=(_observation("custom", ("loc:a", 1)),),
            binding=binding,
            profile=custom,  # type: ignore[call-arg]
        )


def test_default_profile_rejects_failures_and_timeouts_even_when_ranking_gates_pass() -> None:
    dataset = _dataset(_case("ok"), _case("failed"), _case("timeout"))
    expected = _binding(dataset)
    metrics = evaluate_retrieval(
        dataset,
        (
            _observation("ok", ("loc:a", 1)),
            _observation("failed", status="failure"),
            _observation("timeout", status="timeout"),
        ),
    )
    result = evaluate_qualification(
        metrics,
        expected,
        dataset,
    )
    gates = {gate.gate_id: gate.passed for gate in result.gates}
    assert result.qualified is False
    assert gates["failure_count"] is False
    assert gates["timeout_count"] is False


def test_binding_invalid_runtime_values_fail_closed() -> None:
    dataset = _dataset(_case("case"))
    with pytest.raises(ValueError, match="normalized opaque string"):
        replace(_binding(dataset), service_revision=" service ")


def test_strict_fixture_rejects_schema_unknown_missing_and_float_substitution() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["schema_version"] = "attacker-substituted.v999"
    with pytest.raises(ValueError, match="schema_version"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["authority"] = "caller"
    with pytest.raises(ValueError, match="unknown=.*authority"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del payload["cases"][0]["queries"]
    with pytest.raises(ValueError, match="missing=.*queries"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    raw = FIXTURE.read_text(encoding="utf-8").replace('"relevance": 3', '"relevance": 3.0', 1)
    with pytest.raises(ValueError, match="floating-point"):
        parse_retrieval_evaluation_dataset(raw)


def test_strict_fixture_rejects_malformed_references_relevance_duplicates_and_authority_drift() -> (
    None
):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["gold_locators"][0]["locator"] = "lx-missing"
    with pytest.raises(ValueError, match="frozen corpus"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][0]["gold_locators"][0]["relevance"] = 0
    with pytest.raises(ValueError, match="1..30"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["records"][1]["locator"] = payload["records"][0]["locator"]
    with pytest.raises(ValueError, match="duplicate record locator"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["neighbors"][0]["right_locator"] = "lx-missing"
    with pytest.raises(ValueError, match="nonexistent record"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][1]["queries"][0]["query_id"] = "q-001"
    with pytest.raises(ValueError, match="duplicate query ID"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][1]["filters"][0]["value"] = "scope-b"
    with pytest.raises(ValueError, match="filter authority substitution"):
        parse_retrieval_evaluation_dataset(json.dumps(payload))

    with pytest.raises(ValueError, match="malformed JSON"):
        parse_retrieval_evaluation_dataset("{")


def test_manifest_is_canonical_under_input_reordering_and_changes_on_mutation() -> None:
    case_a = _case("a", gold=(GoldLocator("loc:a", 2), GoldLocator("loc:b")))
    case_b = _case("b", gold=(GoldLocator("loc:c"),))
    first_dataset = _dataset(case_a, case_b)
    second_dataset = RetrievalEvaluationDataset(
        first_dataset.dataset_id,
        tuple(reversed(first_dataset.corpus_locators)),
        (case_b, case_a),
    )
    first_observations = (
        _observation("a", ("loc:b", 2), ("loc:a", 1)),
        _observation("b", ("loc:c", 3)),
    )
    second_observations = tuple(reversed(first_observations))
    first = build_evaluation_evidence(first_dataset, first_observations, _binding(first_dataset))
    second = build_evaluation_evidence(
        second_dataset, second_observations, _binding(second_dataset)
    )

    assert first.canonical_json == second.canonical_json
    assert first.manifest_digest == second.manifest_digest
    mutated_observations = (
        replace(first_observations[0], response_bytes=21),
        first_observations[1],
    )
    mutated = build_evaluation_evidence(
        first_dataset, mutated_observations, _binding(first_dataset)
    )
    assert mutated.manifest_digest != first.manifest_digest
    assert mutated.component_digest("observations") != first.component_digest("observations")

    rank_mutation = build_evaluation_evidence(
        first_dataset,
        (
            _observation("a", ("loc:b", 1), ("loc:a", 2)),
            first_observations[1],
        ),
        _binding(first_dataset),
    )
    assert rank_mutation.component_digest("observations") != first.component_digest("observations")


def test_retained_evidence_is_deeply_immutable_and_hash_substitution_fails_verification() -> None:
    dataset = _dataset(_case("case"))
    expected = _binding(dataset)
    evidence = build_evaluation_evidence(
        dataset,
        (_observation("case", ("loc:a", 1)),),
        expected,
    )
    verified = verify_evaluation_evidence(evidence)
    assert verified == evidence
    assert verified is not evidence
    assert not hasattr(evidence, "manifest")
    with pytest.raises(TypeError):
        evidence.component_digests[0][1] = "sha256:mutated"  # type: ignore[index]

    with pytest.raises(ValueError, match="manifest digest mismatch"):
        verify_evaluation_evidence(
            replace(evidence, manifest_digest="sha256:substituted"),
        )
    substituted = replace(
        evidence,
        component_digests=tuple(
            (name, "sha256:substituted" if name == "observations" else digest)
            for name, digest in evidence.component_digests
        ),
    )
    with pytest.raises(ValueError, match="component digest mismatch"):
        verify_evaluation_evidence(
            substituted,
        )


def test_qualified_retained_evidence_resolves_only_package_owned_trust_anchor() -> None:
    dataset = _load_fixture()
    expected = _binding(dataset)
    evidence = build_evaluation_evidence(
        dataset,
        _perfect_observations(dataset),
        expected,
        qualification_spec_id=SYNTHETIC_QUALIFICATION_SPEC_ID,
    )
    verified = verify_evaluation_evidence(evidence)
    assert json.loads(verified.canonical_json)["qualification"]["qualified"] is True

    manifest = json.loads(evidence.canonical_json)
    manifest["qualification_profile"]["maximum_failure_count"] = 99
    substituted_profile_digest = canonical_sha256(manifest["qualification_profile"])
    manifest["component_digests"]["profile"] = substituted_profile_digest
    encoded = canonical_json(manifest)
    consistently_rehashed = replace(
        evidence,
        canonical_json=encoded,
        manifest_digest=canonical_sha256(manifest),
        component_digests=tuple(
            (name, substituted_profile_digest if name == "profile" else digest)
            for name, digest in evidence.component_digests
        ),
    )
    with pytest.raises(
        ValueError,
        match="immutable exact thresholds|qualification contradicts|not package-owned",
    ):
        verify_evaluation_evidence(consistently_rehashed)


def test_hashed_evidence_has_no_floats_and_reports_recall_10_and_ndcg() -> None:
    dataset = _dataset(_case("case"))
    evidence = build_evaluation_evidence(
        dataset, (_observation("case", ("loc:a", 1)),), _binding(dataset)
    )
    decoded = json.loads(evidence.canonical_json)

    assert decoded["metrics"]["recall_at_10"] == {"denominator": 1, "numerator": 1}
    assert decoded["metrics"]["ndcg_at_10"] == {"denominator": 1, "numerator": 1}
    assert not _contains_float(decoded)
    with pytest.raises(ValueError, match="floating-point"):
        canonical_json({"unsafe": 0.9})  # type: ignore[dict-item]


def test_frozen_fixture_is_small_non_meeting_and_covers_required_generic_scenarios() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    payload = json.loads(raw)
    dataset = _load_fixture()
    tags = {tag for case in dataset.cases for tag in case.scenario_tags}
    filters = {filter_id for case in dataset.cases for filter_id in case.filter_ids}
    families: dict[str, int] = {}
    for case in dataset.cases:
        families[case.variation_family_id] = families.get(case.variation_family_id, 0) + 1

    assert len(dataset.corpus_locators) == 16
    assert len(dataset.cases) == 10
    payload["records"][0]["text"] += " Updated."
    mutated = parse_retrieval_evaluation_dataset(json.dumps(payload))
    assert evaluation_dataset_digest(dataset) != evaluation_dataset_digest(mutated)
    assert families["family-retention"] == 2
    assert {
        "generic_reuse",
        "natural_query_variation",
        "hard_scope_filter",
        "hard_source_filter",
        "temporal_filter",
        "metadata_filter",
        "neighbors",
        "unsupported_no_result",
        "leakage_attack",
    }.issubset(tags)
    assert {"f-scope-a", "f-source-guide", "f-date-current", "f-status-active"}.issubset(filters)
    assert all(locator.startswith("lx-") for locator in dataset.corpus_locators)
    assert all(
        "scope" not in locator and "retention" not in locator for locator in dataset.corpus_locators
    )
    assert all(case.query_texts for case in dataset.cases)
    assert any(case.filter_excluded_locators for case in dataset.cases)
    assert all(
        set(case.filter_excluded_locators).isdisjoint(case.forbidden_scope_locators)
        for case in dataset.cases
    )
    assert all(token not in raw.lower() for token in ("meeting", "speaker", "discord", "citation"))


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, list):
        return any(_contains_float(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    return False
