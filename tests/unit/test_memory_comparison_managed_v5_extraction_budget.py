from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_managed_v5_extraction_budget import (
    MANAGED_V5_FULL_ANSWER_JUDGE_CALL_COUNT,
    MANAGED_V5_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION,
    MANAGED_V5_REQUESTED_OUTPUT_TOKENS_PER_CALL,
    ManagedV5ExtractionBudgetError,
    ManagedV5ExtractionReservationUnit,
    ManagedV5ExtractionTokenBudget,
)
from infinity_context_server.memory_comparison_publishable_profile import (
    PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET,
    PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION,
    public_publishable_comparison_profile,
    publishable_priority_comparison_profile_v4,
)


def _units(count: int) -> tuple[ManagedV5ExtractionReservationUnit, ...]:
    return tuple(ManagedV5ExtractionReservationUnit(100, 4096) for _ in range(count))


@pytest.mark.parametrize("operation_count", [419, 277])
def test_operator_caps_must_cover_the_exact_planned_reservation(
    operation_count: int,
) -> None:
    reservation = operation_count * (100 + 4096)
    with pytest.raises(ManagedV5ExtractionBudgetError) as extraction:
        ManagedV5ExtractionTokenBudget.reserve(
            _units(operation_count),
            operator_extraction_token_ceiling=reservation - 1,
            operator_total_token_ceiling=reservation + 10_000,
        )
    assert extraction.value.code == "managed_v5_extraction_token_budget_invalid"

    with pytest.raises(ManagedV5ExtractionBudgetError) as total:
        ManagedV5ExtractionTokenBudget.reserve(
            _units(operation_count),
            operator_extraction_token_ceiling=reservation,
            operator_total_token_ceiling=reservation,
        )
    assert total.value.code == "managed_v5_extraction_token_budget_invalid"


def test_reservation_subtracts_extraction_from_total_benchmark_budget() -> None:
    budget = ManagedV5ExtractionTokenBudget.reserve(
        _units(2),
        operator_extraction_token_ceiling=9000,
        operator_total_token_ceiling=20_000,
    )
    assert budget.planned_extraction_token_reservation == 8392
    assert budget.answer_judge_reserved_token_ceiling == 11_000
    assert budget.public_payload()["tokenizer_exact"] is False
    assert budget.public_payload()["output_limit_enforcement"] == "requested_not_provider_verified"
    assert len(budget.commitment_sha256) == 64


def test_extraction_headroom_is_subtracted_from_the_total_ceiling() -> None:
    budget = ManagedV5ExtractionTokenBudget.reserve(
        _units(1),
        operator_extraction_token_ceiling=5000,
        operator_total_token_ceiling=9000,
    )
    assert budget.planned_extraction_token_reservation == 4196
    assert budget.answer_judge_reserved_token_ceiling == 4000


def test_answer_judge_remainder_is_rejected_before_readiness_when_too_large() -> None:
    with pytest.raises(ManagedV5ExtractionBudgetError):
        ManagedV5ExtractionTokenBudget.reserve(
            _units(1),
            operator_extraction_token_ceiling=5000,
            operator_total_token_ceiling=(
                5_000 + MANAGED_V5_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION + 1
            ),
        )


def test_full_answer_judge_requested_output_reservation_is_the_exact_cap() -> None:
    extraction_ceiling = 5_000
    full_reservation = 8_160 * 4_096
    budget = ManagedV5ExtractionTokenBudget.reserve(
        _units(1),
        operator_extraction_token_ceiling=extraction_ceiling,
        operator_total_token_ceiling=extraction_ceiling + full_reservation,
    )

    assert MANAGED_V5_FULL_ANSWER_JUDGE_CALL_COUNT == 8_160
    assert MANAGED_V5_FULL_ANSWER_JUDGE_CALL_COUNT == PUBLISHABLE_FULL_ANSWER_JUDGE_CALL_BUDGET
    assert MANAGED_V5_REQUESTED_OUTPUT_TOKENS_PER_CALL == 4_096
    assert (
        MANAGED_V5_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION
        == PUBLISHABLE_FULL_ANSWER_JUDGE_REQUESTED_OUTPUT_TOKEN_RESERVATION
        == full_reservation
        == 33_423_360
    )
    assert budget.answer_judge_reserved_token_ceiling == full_reservation
    assert budget.public_payload()["output_limit_enforcement"] == (
        "requested_not_provider_verified"
    )
    priority_reservation = public_publishable_comparison_profile(
        publishable_priority_comparison_profile_v4()
    )["full_run_requested_output_token_reservation"]
    assert priority_reservation["answer_judge_requested_output_tokens"] == full_reservation
    assert priority_reservation["output_limit_enforcement"] == "requested_not_provider_enforced"
    assert priority_reservation["hard_token_budget_claimed"] is False

    with pytest.raises(ManagedV5ExtractionBudgetError) as caught:
        ManagedV5ExtractionTokenBudget.reserve(
            _units(1),
            operator_extraction_token_ceiling=extraction_ceiling,
            operator_total_token_ceiling=extraction_ceiling + full_reservation + 1,
        )
    assert caught.value.code == "managed_v5_extraction_token_budget_invalid"


def test_observed_receipt_tokens_are_bounded_by_operator_extraction_cap() -> None:
    budget = ManagedV5ExtractionTokenBudget.reserve(
        _units(1),
        operator_extraction_token_ceiling=5000,
        operator_total_token_ceiling=10_000,
    )
    budget.require_observed_extraction_tokens(
        provider_observed_request_tokens=3000,
        provider_observed_response_tokens=2000,
    )
    with pytest.raises(ManagedV5ExtractionBudgetError) as caught:
        budget.require_observed_extraction_tokens(
            provider_observed_request_tokens=3001,
            provider_observed_response_tokens=2000,
        )
    assert caught.value.code == "managed_v5_extraction_observed_token_ceiling_exceeded"
