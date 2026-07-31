from __future__ import annotations

import json
from copy import deepcopy

import pytest
from infinity_context_server.memory_comparison_token_budget_contract import (
    AnswerTokenBudgetPolicy,
    answer_token_budget_contract,
    token_budget_methodology_contract,
)


def test_token_budget_contract_reports_paired_prompt_and_retrieval_statistics() -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1", prompt_tokens=90, context_tokens=70),
        _evaluation("mem0", "case-1", prompt_tokens=100, context_tokens=80),
        _evaluation("infinity-context", "case-2", prompt_tokens=100, context_tokens=80),
        _evaluation("mem0", "case-2", prompt_tokens=100, context_tokens=90),
    ]

    contract = answer_token_budget_contract(
        evaluations,
        expected_pair_count=2,
        policy=AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6956),
    )

    assert contract["matches"] is True
    assert contract["publishable"] is False
    assert contract["blockers"] == []
    assert contract["answerer_prompt_tokens"] == {
        "infinity-context": {
            "count": 2,
            "mean": 95.0,
            "p50": 90,
            "p95": 100,
            "max": 100,
        },
        "mem0": {
            "count": 2,
            "mean": 100.0,
            "p50": 100,
            "p95": 100,
            "max": 100,
        },
    }
    assert contract["retrieval_context_tokens"]["infinity-context"] == {
        "count": 2,
        "mean": 75.0,
        "p50": 70,
        "p95": 80,
        "max": 80,
        "missing_count": 0,
    }
    assert contract["infinity_to_mem0_answerer_prompt_token_ratios"] == {
        "mean": 0.95,
        "p50": 0.9,
        "p95": 1.0,
        "max": 1.0,
    }


def test_published_mem0_token_number_is_explicitly_reference_only() -> None:
    methodology = token_budget_methodology_contract(
        AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6787)
    )

    assert methodology["published_mem0_reference"] == {
        "mean_tokens": 6787,
        "reported_metric": "mean_tokens_per_retrieval_call",
        "source": "https://docs.mem0.ai/core-concepts/memory-evaluation",
        "comparison_role": "reference_only",
        "comparable_to_primary_budget_metric": False,
        "reason": (
            "The pinned upstream harness declares prompt-token fields but its answer "
            "path does not capture provider usage; the later published retrieval-call "
            "mean therefore cannot be mapped exactly."
        ),
    }


@pytest.mark.parametrize(
    ("scored_value", "expected_reason"),
    (
        (False, "false"),
        (None, "invalid"),
        (1, "invalid"),
        ("true", "invalid"),
    ),
)
def test_only_explicit_boolean_true_is_admitted_as_scored(
    scored_value: object,
    expected_reason: str,
) -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1"),
        _evaluation("mem0", "case-1"),
    ]
    evaluations[0]["scored"] = scored_value

    contract = _contract(evaluations, expected_pair_count=1)

    assert contract["matches"] is False
    assert contract["invalid_scored_status"] == {
        "count": 1,
        "reason_counts": {expected_reason: 1},
    }
    assert "incomplete_paired_answerer_token_budget" in _blocker_codes(contract)


def test_missing_scored_status_is_fail_closed_and_diagnosed_separately() -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1"),
        _evaluation("mem0", "case-1"),
    ]
    evaluations[0].pop("scored")

    contract = _contract(evaluations, expected_pair_count=1)

    assert contract["invalid_scored_status"]["reason_counts"] == {"missing": 1}
    assert contract["matches"] is False


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    (
        ("prompt_tokens", None, "invalid_answerer_token_usage"),
        ("prompt_tokens", 0, "invalid_answerer_token_usage"),
        ("prompt_tokens", -1, "invalid_answerer_token_usage"),
        ("prompt_tokens", 1.5, "invalid_answerer_token_usage"),
        ("prompt_tokens", 1_000_000_001, "invalid_answerer_token_usage"),
        ("completion_tokens", 0, "invalid_answerer_token_usage"),
        ("token_usage_source", "", "untrusted_answerer_token_usage_source"),
        ("token_usage_source", "fallback_approximation", "untrusted_answerer_token_usage_source"),
        ("finish_reason", "", "truncated_or_unverified_answerer_completion"),
        ("finish_reason", "length", "truncated_or_unverified_answerer_completion"),
        ("finish_reason_source", "", "truncated_or_unverified_answerer_completion"),
        ("finish_reason", "content_filter", "truncated_or_unverified_answerer_completion"),
    ),
)
def test_invalid_or_untrusted_answerer_usage_blocks_publication(
    field: str,
    value: object,
    blocker: str,
) -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1"),
        _evaluation("mem0", "case-1"),
    ]
    generation = evaluations[0]["generation"]
    target = (
        generation["metadata"]
        if field in {"token_usage_source", "finish_reason", "finish_reason_source"}
        else generation["token_usage"]
    )
    target[field] = value

    contract = _contract(evaluations, expected_pair_count=1)

    assert blocker in _blocker_codes(contract)
    assert contract["matches"] is False


def test_per_case_gate_catches_outlier_when_mean_and_p95_pass() -> None:
    evaluations: list[dict[str, object]] = []
    for index in range(21):
        case_id = f"case-{index:02d}"
        infinity_tokens = 101 if index == 0 else 99
        evaluations.extend(
            (
                _evaluation(
                    "infinity-context",
                    case_id,
                    prompt_tokens=infinity_tokens,
                ),
                _evaluation("mem0", case_id, prompt_tokens=100),
            )
        )

    contract = _contract(evaluations, expected_pair_count=21)

    ratios = contract["infinity_to_mem0_answerer_prompt_token_ratios"]
    assert ratios["mean"] < 1.0
    assert ratios["p95"] < 1.0
    assert contract["per_case_budget_violation_count"] == 1
    assert "answerer_prompt_token_budget_exceeded" in _blocker_codes(contract)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("token_usage_source", "fallback_approximation"),
        ("finish_reason", "length"),
        ("finish_reason_source", ""),
        ("prompt_tokens", 0),
        ("completion_tokens", 1.5),
    ),
)
def test_invalid_judge_provider_telemetry_blocks_without_affecting_answer_budget(
    field: str,
    value: object,
) -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1"),
        _evaluation("mem0", "case-1"),
    ]
    judgment = evaluations[0]["judgment"]
    target = (
        judgment["metadata"]
        if field in {"token_usage_source", "finish_reason", "finish_reason_source"}
        else judgment["token_usage"]
    )
    target[field] = value

    contract = _contract(evaluations, expected_pair_count=1)

    assert contract["answerer_prompt_tokens"]["infinity-context"]["mean"] == 100.0
    assert "invalid_judge_provider_call_integrity" in _blocker_codes(contract)


def test_token_diagnostic_samples_are_bounded() -> None:
    evaluations: list[dict[str, object]] = []
    for index in range(25):
        case_id = f"case-{index:02d}"
        invalid = _evaluation("infinity-context", case_id)
        invalid["generation"]["token_usage"]["prompt_tokens"] = 0
        evaluations.extend((invalid, _evaluation("mem0", case_id)))

    contract = _contract(evaluations, expected_pair_count=25)
    diagnostic = contract["invalid_answerer_token_usage"]

    assert diagnostic["count"] == 25
    assert len(diagnostic["samples"]) == 20
    assert diagnostic["truncated_count"] == 5


def test_invalid_samples_are_sorted_before_global_truncation() -> None:
    evaluations: list[dict[str, object]] = []
    for index in reversed(range(25)):
        case_id = f"case-{index:02d}"
        invalid = _evaluation("infinity-context", case_id)
        invalid["generation"]["token_usage"]["prompt_tokens"] = 0
        evaluations.extend((invalid, _evaluation("mem0", case_id)))

    samples = _contract(
        evaluations,
        expected_pair_count=25,
    )["invalid_answerer_token_usage"]["samples"]

    assert [sample["case_id"] for sample in samples] == [f"case-{index:02d}" for index in range(20)]


def test_per_case_violation_samples_are_sorted_before_truncation() -> None:
    evaluations: list[dict[str, object]] = []
    for index in reversed(range(25)):
        case_id = f"case-{index:02d}"
        evaluations.extend(
            (
                _evaluation("infinity-context", case_id, prompt_tokens=101),
                _evaluation("mem0", case_id, prompt_tokens=100),
            )
        )

    contract = _contract(evaluations, expected_pair_count=25)

    assert contract["per_case_budget_violation_count"] == 25
    sample_case_ids = [
        sample["case_id"] for sample in contract["per_case_budget_violation_samples"]
    ]
    assert sample_case_ids == [f"case-{index:02d}" for index in range(20)]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("published_mem0_mean_tokens_reference", True),
        ("published_mem0_mean_tokens_reference", 0),
        ("published_mem0_mean_tokens_reference", 1_000_000_001),
        ("max_infinity_to_mem0_mean_prompt_token_ratio", True),
        ("max_infinity_to_mem0_mean_prompt_token_ratio", -0.1),
        ("max_infinity_to_mem0_p95_prompt_token_ratio", float("inf")),
        ("max_infinity_to_mem0_p95_prompt_token_ratio", float("nan")),
        ("max_infinity_to_mem0_per_case_prompt_token_ratio", 1_000.1),
        ("max_infinity_to_mem0_per_case_prompt_token_ratio", 10**10_000),
    ),
    ids=(
        "bool-reference",
        "zero-reference",
        "huge-reference",
        "bool-ratio",
        "negative-ratio",
        "infinite-ratio",
        "nan-ratio",
        "ratio-over-bound",
        "huge-int-ratio",
    ),
)
def test_token_policy_rejects_nonfinite_negative_or_unbounded_values(
    field: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {"published_mem0_mean_tokens_reference": 6956}
    kwargs[field] = value

    with pytest.raises(ValueError):
        AnswerTokenBudgetPolicy(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize("expected_pair_count", (True, 1.0, -1, 0, 1_000_000_001))
def test_expected_pair_count_is_exact_positive_and_bounded(
    expected_pair_count: object,
) -> None:
    contract = answer_token_budget_contract(
        [_evaluation("infinity-context", "case-1"), _evaluation("mem0", "case-1")],
        expected_pair_count=expected_pair_count,  # type: ignore[arg-type]
        policy=AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6956),
    )

    assert contract["matches"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("benchmark", True),
        ("benchmark", 7),
        ("benchmark", " benchmark "),
        ("benchmark", ""),
        ("case_id", False),
        ("case_id", 9),
        ("case_id", " case-1 "),
        ("case_id", "x" * 513),
    ),
)
def test_benchmark_and_case_ids_require_exact_nonempty_strings(
    field: str,
    value: object,
) -> None:
    evaluations = [
        _evaluation("infinity-context", "case-1"),
        _evaluation("mem0", "case-1"),
    ]
    evaluations[0][field] = value

    contract = _contract(evaluations, expected_pair_count=1)

    assert contract["matches"] is False
    assert contract["blockers"][0]["invalid_identity_count"] == 1


def test_token_budget_rejects_non_mapping_items_without_attribute_errors() -> None:
    contract = answer_token_budget_contract(
        (True, 7, "raw", {}),  # type: ignore[arg-type]
        expected_pair_count=1,
        policy=AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6956),
    )

    assert contract["matches"] is False
    assert contract["invalid_evaluation_count"] == 3


def test_token_budget_rejects_non_sequence_input_without_attribute_errors() -> None:
    contract = answer_token_budget_contract(
        True,  # type: ignore[arg-type]
        expected_pair_count=1,
        policy=AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6956),
    )

    assert contract["matches"] is False
    assert contract["evaluation_input_valid"] is False


def test_token_budget_artifact_is_strict_json() -> None:
    contract = _contract(
        [_evaluation("infinity-context", "case-1"), _evaluation("mem0", "case-1")],
        expected_pair_count=1,
    )

    json.dumps(contract, allow_nan=False, sort_keys=True)


def _evaluation(
    backend: str,
    case_id: str,
    *,
    prompt_tokens: int = 100,
    context_tokens: int = 80,
) -> dict[str, object]:
    return {
        "scored": True,
        "backend": backend,
        "benchmark": "locomo",
        "case_id": case_id,
        "retrieval": {"context_token_count": context_tokens},
        "judgment": {
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
            },
            "metadata": {
                "token_usage_source": "provider_observed",
                "finish_reason": "stop",
                "finish_reason_source": "provider_observed",
            },
        },
        "generation": {
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 5,
            },
            "metadata": {
                "token_usage_source": "provider_observed",
                "finish_reason": "stop",
                "finish_reason_source": "provider_observed",
            },
        },
    }


def _contract(
    evaluations: list[dict[str, object]],
    *,
    expected_pair_count: int,
) -> dict[str, object]:
    return answer_token_budget_contract(
        deepcopy(evaluations),
        expected_pair_count=expected_pair_count,
        policy=AnswerTokenBudgetPolicy(published_mem0_mean_tokens_reference=6956),
    )


def _blocker_codes(contract: dict[str, object]) -> set[str]:
    return {str(item["code"]) for item in contract["blockers"]}
