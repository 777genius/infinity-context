from __future__ import annotations

import copy
import pickle

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    BenchmarkSpec,
    freeze_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_ACTIVATION_BLOCKERS,
    PUBLISHABLE_PROFILE_ID,
    public_publishable_comparison_profile,
    resolve_publishable_comparison_profile,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError


def _public() -> dict[str, object]:
    profile = resolve_publishable_comparison_profile()
    assert profile is not None
    return public_publishable_comparison_profile(profile)


def test_top_profile_is_contract_only_and_cannot_be_published_or_executed() -> None:
    public = _public()

    assert public["profile_id"] == PUBLISHABLE_PROFILE_ID
    assert public["implementation_status"] == "contract_only"
    assert public["execution_enabled"] is False
    assert public["publishable"] is False
    assert public["claim_scope"] == "same_run_pinned_oss_only"
    assert public["activation_blockers"] == list(PUBLISHABLE_ACTIVATION_BLOCKERS)


def test_profile_references_independently_committed_methodology() -> None:
    methodology = _public()["methodology"]

    assert methodology["schema_version"] == "memory-comparison-publishable-methodology.v1"
    assert methodology["methodology_id"] == "ic-vs-mem0-oss-keyless-methodology-v1"
    assert len(methodology["commitment_sha256"]) == 64
    assert methodology["observed"] is False


def test_locomo_spec_has_exact_authoritative_counts_and_arithmetic() -> None:
    spec = _public()["benchmarks"]["locomo"]

    assert spec["dataset_sha256"] == LOCOMO_OFFICIAL_DATASET_SHA256
    assert spec["expected_case_count"] == 1540
    assert spec["expected_corpus_count"] == 10
    assert spec["expected_message_count"] == 5882
    assert spec["ingestion_contract"] == "official-turns"
    assert spec["expected_grouping"] == {
        "multi-hop": 282,
        "temporal": 321,
        "open-domain": 96,
        "single-hop": 841,
    }
    assert spec["answer_judge_call_budget"] == 1540 * 2 * 2
    assert spec["total_call_budget"] == 5882 + 6160
    assert spec["readiness_probe_calls"] == 1
    assert spec["readiness_probe_in_total"] is False
    assert spec["execution_enabled"] is False
    assert len(spec["commitment_sha256"]) == 64


def test_longmemeval_spec_has_exact_authoritative_counts_and_arithmetic() -> None:
    spec = _public()["benchmarks"]["longmemeval"]

    assert spec["dataset_sha256"] == LONGMEMEVAL_OFFICIAL_DATASET_SHA256
    assert spec["expected_case_count"] == 500
    assert spec["expected_corpus_count"] == 500
    assert spec["expected_message_count"] == 246738
    assert spec["ingestion_contract"] == "official_user_assistant_pairs"
    assert spec["answer_judge_call_budget"] == 500 * 2 * 2
    assert spec["total_call_budget"] == 124344 + 2000
    assert spec["readiness_probe_calls"] == 1
    assert spec["readiness_probe_in_total"] is False
    assert spec["execution_enabled"] is False


@pytest.mark.parametrize(
    "updates",
    (
        {"answer_judge_call_budget": 1},
        {"total_call_budget": 1},
        {"readiness_probe_calls": 2},
        {"readiness_probe_in_total": True},
    ),
)
def test_benchmark_spec_rejects_budget_or_readiness_drift(updates: dict[str, object]) -> None:
    values: dict[str, object] = {
        "benchmark": "fixture",
        "dataset_sha256": "a" * 64,
        "prompt_file_sha256": "b" * 64,
        "expected_case_count": 2,
        "expected_corpus_count": 1,
        "expected_message_count": 3,
        "grouping_field": "kind",
        "expected_grouping": (("one", 2),),
        "ingestion_contract": "fixture_pairs",
        "extraction_call_budget": 3,
        "answer_judge_call_budget": 8,
        "total_call_budget": 11,
        "readiness_probe_calls": 1,
        "readiness_probe_in_total": False,
    }
    values.update(updates)

    with pytest.raises(BenchmarkValidationError):
        BenchmarkSpec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "updates",
    (
        {"dataset_sha256": "A" * 64},
        {"dataset_sha256": "a" * 63},
        {"prompt_file_sha256": "B" * 64},
        {"prompt_file_sha256": "b" * 63},
        {"ingestion_contract": ""},
        {"expected_grouping": ()},
        {"expected_grouping": (("", 2),)},
        {"expected_grouping": (("one", 1), ("one", 1))},
        {"expected_grouping": (("one", 1),)},
        {"expected_grouping": (("one", True), ("two", 1))},
    ),
)
def test_benchmark_spec_rejects_malformed_dataset_or_grouping(
    updates: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "benchmark": "fixture",
        "dataset_sha256": "a" * 64,
        "prompt_file_sha256": "b" * 64,
        "expected_case_count": 2,
        "expected_corpus_count": 1,
        "expected_message_count": 3,
        "grouping_field": "kind",
        "expected_grouping": (("one", 2),),
        "ingestion_contract": "fixture_pairs",
        "extraction_call_budget": 3,
        "answer_judge_call_budget": 8,
        "total_call_budget": 11,
    }
    values.update(updates)

    with pytest.raises(BenchmarkValidationError):
        BenchmarkSpec(**values)  # type: ignore[arg-type]


def test_benchmark_spec_is_copy_stable_sealed_and_unpicklable() -> None:
    spec = BenchmarkSpec(
        benchmark="fixture",
        dataset_sha256="a" * 64,
        prompt_file_sha256="b" * 64,
        expected_case_count=2,
        expected_corpus_count=1,
        expected_message_count=3,
        grouping_field="kind",
        expected_grouping=(("one", 2),),
        ingestion_contract="fixture_pairs",
        extraction_call_budget=3,
        answer_judge_call_budget=8,
        total_call_budget=11,
    )

    assert copy.copy(spec) is spec
    assert copy.deepcopy(spec) is spec
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(spec)
    with pytest.raises(TypeError, match="sealed"):
        type("MutableBenchmarkSpec", (BenchmarkSpec,), {})


def test_profile_is_copy_stable_and_forbids_pickle() -> None:
    profile = resolve_publishable_comparison_profile()
    assert profile is not None

    assert copy.copy(profile) is profile
    assert copy.deepcopy(profile) is profile
    with pytest.raises(TypeError, match="cannot be pickled"):
        pickle.dumps(profile)


def test_profile_rejects_tampered_activation_or_commitments() -> None:
    public = _public()
    public["execution_enabled"] = True
    tampered = freeze_publishable_payload(profile_id=PUBLISHABLE_PROFILE_ID, payload=public)

    with pytest.raises(BenchmarkValidationError, match="differs from frozen primitives"):
        public_publishable_comparison_profile(tampered)


def test_profile_public_projection_is_fresh() -> None:
    profile = resolve_publishable_comparison_profile()
    assert profile is not None
    first = public_publishable_comparison_profile(profile)
    first["activation_blockers"].clear()

    assert public_publishable_comparison_profile(profile)["activation_blockers"] == list(
        PUBLISHABLE_ACTIVATION_BLOCKERS
    )
