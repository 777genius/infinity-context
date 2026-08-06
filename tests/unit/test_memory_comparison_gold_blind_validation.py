from __future__ import annotations

import base64
from collections.abc import Mapping

import pytest
from infinity_context_server.memory_comparison_gold_blind import build_gold_blind_contract
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    dispatch_retrieval,
    validate_provider_text,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN_ID = "run-1"
_CASE_ID = "case-1"
_RETRIEVAL_BACKEND = "retrieval-v1"
_ANSWER_BACKEND = "answer-v1"
_JUDGE_BACKEND = "judge-v1"
_NATURAL_LOCOMO_TOKEN = "feelings"
_GROUND_TRUTH = "evaluator secret"


class _CapturingRetriever:
    def __init__(self) -> None:
        self.request: Mapping[str, object] | None = None

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del run_id, top_k
        self.request = request
        return (GoldBlindEvidence(item_id="item-1", text="public evidence", rank=1),)


def _build_contract(
    *,
    question: str,
    expected_terms: tuple[str, ...] = ("expected answer",),
    ground_truth: str = _GROUND_TRUTH,
):
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id=_CASE_ID,
        question=question,
        expected_terms=expected_terms,
        metadata={
            "_evaluator_ground_truth": {"answer": ground_truth},
            "reference_date": "2 January 2023",
        },
    )
    key = JudgeRunKey.issue(run_id=_RUN_ID, case_id=_CASE_ID)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN_ID,
        comparison_binding_commitment_sha256="9" * 64,
        expected_cases=(
            GoldBlindExpectedDispatchCase(
                case_id=_CASE_ID,
                retrieval_backend_id=_RETRIEVAL_BACKEND,
                answer_backend_id=_ANSWER_BACKEND,
                judge_backend_id=_JUDGE_BACKEND,
            ),
        ),
    )
    return build_gold_blind_contract(
        case,
        run_id=_RUN_ID,
        judge_key=key,
        dispatch_ledger=ledger,
    ), ledger


def test_natural_locomo_base64_shaped_token_reaches_retrieval_dispatch() -> None:
    question = f"How did they describe their {_NATURAL_LOCOMO_TOKEN}?"
    assert base64.b64decode(_NATURAL_LOCOMO_TOKEN, validate=True).decode("utf-8")

    validate_provider_text(question, field_name="Public provider field")
    contract, ledger = _build_contract(question=question)
    retriever = _CapturingRetriever()

    result = dispatch_retrieval(
        retriever,
        contract.retrieval_request,
        backend_id=_RETRIEVAL_BACKEND,
        dispatch_ledger=ledger,
        run_id=_RUN_ID,
        top_k=1,
    )

    assert len(result) == 1
    assert retriever.request is not None
    assert retriever.request["question"] == question


def test_decoded_evaluator_label_remains_rejected() -> None:
    encoded_label = base64.b64encode(b"expectedAnswer").decode("ascii")

    with pytest.raises(GoldBlindContractError, match="evaluator-label"):
        validate_provider_text(encoded_label, field_name="Public provider field")


def test_base64_expected_answer_is_rejected_from_public_view() -> None:
    expected_answer = "green tea"
    encoded_answer = base64.b64encode(expected_answer.encode("utf-8")).decode("ascii")

    with pytest.raises(GoldBlindContractError, match="contains evaluator gold"):
        _build_contract(question=encoded_answer, expected_terms=(expected_answer,))


def test_base64_evaluator_ground_truth_is_rejected_from_public_view() -> None:
    encoded_ground_truth = base64.b64encode(_GROUND_TRUTH.encode("utf-8")).decode("ascii")

    with pytest.raises(GoldBlindContractError, match="contains evaluator gold"):
        _build_contract(question=encoded_ground_truth)


def test_oversized_base64_like_token_remains_rejected() -> None:
    oversized_token = base64.b64encode(b"x" * 7_000).decode("ascii")

    with pytest.raises(GoldBlindContractError, match="oversized base64-like token"):
        validate_provider_text(oversized_token, field_name="Public provider field")
