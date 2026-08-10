from __future__ import annotations

import copy
import pickle

import pytest
from infinity_context_server.memory_comparison_full_profiles import (
    LOCOMO_OFFICIAL_DATASET_SHA256,
    LONGMEMEVAL_OFFICIAL_DATASET_SHA256,
)
from infinity_context_server.memory_comparison_paired_superiority_policy import (
    paired_superiority_policy_payload,
)
from infinity_context_server.memory_comparison_publishable_contracts import (
    BenchmarkSpec,
    freeze_publishable_payload,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
    LEGACY_PUBLISHABLE_PROFILE_ID,
    LONGMEMEVAL_EXPECTED_MESSAGE_COUNT,
    LONGMEMEVAL_EXTRACTION_CALL_BUDGET,
    LONGMEMEVAL_FULLY_INVALID_PAIR_COUNT,
    LONGMEMEVAL_INVALID_MESSAGE_COUNT,
    LONGMEMEVAL_NORMALIZED_ODD_SESSION_COUNT,
    LONGMEMEVAL_ORIGINAL_PAIR_SLOT_COUNT,
    LONGMEMEVAL_RAW_MESSAGE_COUNT,
    LONGMEMEVAL_RAW_ODD_SESSION_COUNT,
    PUBLISHABLE_ACTIVATION_BLOCKERS,
    PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET,
    PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION,
    PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET,
    PUBLISHABLE_FULL_EXTRACTION_REQUESTED_OUTPUT_TOKEN_RESERVATION,
    PUBLISHABLE_FULL_REQUESTED_OUTPUT_TOKEN_RESERVATION,
    PUBLISHABLE_FULL_TOTAL_CALL_BUDGET,
    PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256,
    PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
    PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
    PUBLISHABLE_PROFILE_ID,
    frozen_publishable_comparison_profile,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
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
    assert "full_run_extraction_equivalence" in public["activation_blockers"]


def test_profile_references_independently_committed_methodology() -> None:
    methodology = _public()["methodology"]

    assert methodology["schema_version"] == "memory-comparison-publishable-methodology.v3"
    assert methodology["methodology_id"] == "ic-vs-mem0-oss-keyless-methodology-v3"
    assert methodology["commitment_sha256"] == (
        "78f7fee652c128378f03cbf3e0e8450334d05e70f76e1322ba082ee007fe2ba1"
    )
    assert methodology["observed"] is False


def test_profile_versions_preserve_exact_distinguishable_commitments() -> None:
    current = resolve_publishable_comparison_profile()
    legacy = resolve_publishable_comparison_profile(LEGACY_PUBLISHABLE_PROFILE_ID)
    assert current is not None and legacy is not None

    legacy_refrozen = frozen_publishable_comparison_profile(legacy)
    legacy_public = public_publishable_comparison_profile(legacy)
    assert current.commitment_sha256 == PUBLISHABLE_PROFILE_COMMITMENT_SHA256
    assert current.commitment_sha256 == (
        "f5f754847bd25ad43feab2ff6325af04c7f760dec690f30ede121dd629c0b8e1"
    )
    assert legacy.commitment_sha256 == LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256
    assert legacy.commitment_sha256 == (
        "9256c235cb5e90a8954caebd26a92011c67dc78772e8403233df5d4ebbfbce32"
    )
    assert legacy_refrozen.profile_id == LEGACY_PUBLISHABLE_PROFILE_ID
    assert legacy_refrozen.commitment_sha256 == legacy.commitment_sha256
    assert public_publishable_comparison_profile(legacy_refrozen) == legacy_public
    assert legacy.commitment_sha256 != current.commitment_sha256
    assert legacy_public["schema_version"] == "memory-comparison-publishable-profile.v2"
    assert legacy_public["profile_id"] == LEGACY_PUBLISHABLE_PROFILE_ID
    assert "full_run_call_budget" not in legacy_public
    assert "full_run_requested_output_token_reservation" not in legacy_public


def test_priority_profile_v4_is_explicit_exact_and_keeps_v3_as_default() -> None:
    default = resolve_publishable_comparison_profile()
    selected = resolve_publishable_comparison_profile(PUBLISHABLE_PRIORITY_PROFILE_V4_ID)
    priority = publishable_priority_comparison_profile_v4()
    assert default is not None and selected is not None
    default_public = public_publishable_comparison_profile(default)
    public = public_publishable_comparison_profile(priority)

    assert default.profile_id == PUBLISHABLE_PROFILE_ID
    assert default.commitment_sha256 == PUBLISHABLE_PROFILE_COMMITMENT_SHA256
    assert selected.profile_id == PUBLISHABLE_PRIORITY_PROFILE_V4_ID
    assert selected.commitment_sha256 == priority.commitment_sha256
    assert priority.commitment_sha256 == PUBLISHABLE_PRIORITY_PROFILE_V4_COMMITMENT_SHA256
    assert priority.commitment_sha256 == (
        "a25c0b9a5cf51aa968872c94729cd02e8f0af7eb74b0f9d1930d4aa4ae9353c2"
    )
    assert priority.commitment_sha256 not in {
        LEGACY_PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
        PUBLISHABLE_PROFILE_COMMITMENT_SHA256,
    }
    assert public["schema_version"] == "memory-comparison-publishable-profile.v4"
    assert public["profile_id"] == PUBLISHABLE_PRIORITY_PROFILE_V4_ID
    assert public["methodology"] == {
        "schema_version": "memory-comparison-publishable-methodology.v4",
        "methodology_id": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_ID,
        "commitment_sha256": PUBLISHABLE_PRIORITY_METHODOLOGY_V4_COMMITMENT_SHA256,
        "observed": False,
    }
    locomo = public["benchmarks"]["locomo"]
    longmemeval = public["benchmarks"]["longmemeval"]
    call_budget = public["full_run_call_budget"]
    output_reservation = public["full_run_requested_output_token_reservation"]
    extraction_calls = locomo["extraction_call_budget"] + longmemeval["extraction_call_budget"]
    answer_judge_calls = (
        locomo["answer_judge_call_budget"] + longmemeval["answer_judge_call_budget"]
    )
    assert locomo["expected_case_count"] == 1_540
    assert longmemeval["expected_case_count"] == 500
    assert locomo["expected_case_count"] + longmemeval["expected_case_count"] == 2_040
    assert call_budget == {
        "extraction_call_budget": 130_226,
        "answer_judge_call_budget": 8_160,
        "total_call_budget": 138_386,
    }
    assert extraction_calls == 130_226
    assert answer_judge_calls == 8_160
    assert call_budget["extraction_call_budget"] == extraction_calls
    assert call_budget["answer_judge_call_budget"] == answer_judge_calls
    assert call_budget["total_call_budget"] == extraction_calls + answer_judge_calls == 138_386
    assert 130_226 * 4_096 == 533_405_696
    assert 8_160 * 4_096 == 33_423_360
    assert 138_386 * 4_096 == 566_829_056
    assert output_reservation == {
        "requested_max_output_tokens_per_call": 4_096,
        "extraction_requested_output_tokens": 533_405_696,
        "answer_judge_requested_output_tokens": 33_423_360,
        "total_requested_output_tokens": 566_829_056,
        "output_limit_enforcement": "requested_not_provider_enforced",
        "hard_token_budget_claimed": False,
    }
    assert set(default_public) == set(public)
    assert {key for key in public if public[key] != default_public[key]} == {
        "schema_version",
        "profile_id",
        "methodology",
    }


def test_default_and_priority_profiles_reject_crosswired_methodologies() -> None:
    default = resolve_publishable_comparison_profile()
    priority = publishable_priority_comparison_profile_v4()
    assert default is not None
    default_public = public_publishable_comparison_profile(default)
    priority_public = public_publishable_comparison_profile(priority)

    priority_with_default_methodology = dict(priority_public)
    priority_with_default_methodology["methodology"] = default_public["methodology"]
    priority_crosswire = freeze_publishable_payload(
        profile_id=PUBLISHABLE_PRIORITY_PROFILE_V4_ID,
        payload=priority_with_default_methodology,
    )
    with pytest.raises(BenchmarkValidationError, match="differs from frozen primitives"):
        public_publishable_comparison_profile(priority_crosswire)

    default_with_priority_methodology = dict(default_public)
    default_with_priority_methodology["methodology"] = priority_public["methodology"]
    default_crosswire = freeze_publishable_payload(
        profile_id=PUBLISHABLE_PROFILE_ID,
        payload=default_with_priority_methodology,
    )
    with pytest.raises(BenchmarkValidationError, match="differs from frozen primitives"):
        public_publishable_comparison_profile(default_crosswire)


def test_priority_profile_v4_suite_matches_paired_superiority_policy_coverage() -> None:
    public = public_publishable_comparison_profile(publishable_priority_comparison_profile_v4())
    policy = paired_superiority_policy_payload()
    benchmarks = public["benchmarks"]
    profile_strata = [
        {"benchmark": benchmark, "category": category, "pair_count": count}
        for benchmark in ("locomo", "longmemeval")
        for category, count in benchmarks[benchmark]["expected_grouping"].items()
    ]

    pair_count = (
        benchmarks["locomo"]["expected_case_count"]
        + benchmarks["longmemeval"]["expected_case_count"]
    )
    assert public["primary_metric_id"] == "paired_answer_accuracy"
    assert pair_count == 2_040
    assert policy["expected_pair_count"] == pair_count
    assert profile_strata == policy["expected_strata"]


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
    raw_message_count = 246_750
    invalid_message_count = 12
    raw_odd_session_count = 1_940
    normalized_odd_session_count = 1_944
    fully_invalid_pair_count = 1
    paired_raw_messages = raw_message_count - raw_odd_session_count
    original_pair_slots = paired_raw_messages // 2 + raw_odd_session_count
    authoritative_extraction_calls = original_pair_slots - fully_invalid_pair_count

    assert spec["dataset_sha256"] == LONGMEMEVAL_OFFICIAL_DATASET_SHA256
    assert spec["expected_case_count"] == 500
    assert spec["expected_corpus_count"] == 500
    assert paired_raw_messages % 2 == 0
    assert original_pair_slots == 124345
    assert authoritative_extraction_calls == 124344
    assert raw_message_count == LONGMEMEVAL_RAW_MESSAGE_COUNT
    assert invalid_message_count == LONGMEMEVAL_INVALID_MESSAGE_COUNT
    assert raw_odd_session_count == LONGMEMEVAL_RAW_ODD_SESSION_COUNT
    assert normalized_odd_session_count == LONGMEMEVAL_NORMALIZED_ODD_SESSION_COUNT
    assert original_pair_slots == LONGMEMEVAL_ORIGINAL_PAIR_SLOT_COUNT
    assert fully_invalid_pair_count == LONGMEMEVAL_FULLY_INVALID_PAIR_COUNT
    assert (
        spec["expected_message_count"]
        == LONGMEMEVAL_EXPECTED_MESSAGE_COUNT
        == raw_message_count - invalid_message_count
        == 246738
    )
    assert spec["ingestion_contract"] == "official_user_assistant_pairs"
    assert (
        spec["extraction_call_budget"]
        == LONGMEMEVAL_EXTRACTION_CALL_BUDGET
        == authoritative_extraction_calls
    )
    assert spec["answer_judge_call_budget"] == 500 * 2 * 2
    assert spec["total_call_budget"] == LONGMEMEVAL_EXTRACTION_CALL_BUDGET + 2000
    assert spec["readiness_probe_calls"] == 1
    assert spec["readiness_probe_in_total"] is False
    assert spec["execution_enabled"] is False


def test_full_run_call_and_requested_output_arithmetic_is_exact() -> None:
    public = _public()
    locomo = public["benchmarks"]["locomo"]
    longmemeval = public["benchmarks"]["longmemeval"]
    call_budget = public["full_run_call_budget"]
    output_reservation = public["full_run_requested_output_token_reservation"]

    assert locomo["extraction_call_budget"] == 5_882
    assert locomo["answer_judge_call_budget"] == 6_160
    assert longmemeval["extraction_call_budget"] == 124_344
    assert longmemeval["answer_judge_call_budget"] == 2_000
    assert PUBLISHABLE_FULL_EXTRACTION_CALL_BUDGET == 5_882 + 124_344 == 130_226
    assert PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET == 6_160 + 2_000 == 8_160
    assert PUBLISHABLE_FULL_TOTAL_CALL_BUDGET == 130_226 + 8_160 == 138_386
    assert call_budget == {
        "extraction_call_budget": 130_226,
        "answer_judge_call_budget": 8_160,
        "total_call_budget": 138_386,
    }
    assert (
        PUBLISHABLE_FULL_EXTRACTION_REQUESTED_OUTPUT_TOKEN_RESERVATION
        == 130_226 * 4_096
        == 533_405_696
    )
    assert (
        PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION
        == 8_160 * 4_096
        == 33_423_360
    )
    assert PUBLISHABLE_FULL_REQUESTED_OUTPUT_TOKEN_RESERVATION == 138_386 * 4_096 == 566_829_056
    assert output_reservation == {
        "requested_max_output_tokens_per_call": 4_096,
        "extraction_requested_output_tokens": 533_405_696,
        "answer_judge_requested_output_tokens": 33_423_360,
        "total_requested_output_tokens": 566_829_056,
        "output_limit_enforcement": "requested_not_provider_enforced",
        "hard_token_budget_claimed": False,
    }


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
