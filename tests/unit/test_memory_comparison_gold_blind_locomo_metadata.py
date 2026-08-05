from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_gold_blind import build_gold_blind_contract
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS,
    _load_memory_comparison_cases,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN_ID = "locomo-answer-terms-run"
_CASE_ID = "conv-26:qa:1"
_RETRIEVAL_BACKEND = "retrieval-v1"
_ANSWER_BACKEND = "answer-v1"
_JUDGE_BACKEND = "judge-v1"
_ANSWER_TERM = "green tea"


class _CapturingRetriever:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, object]] = []

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del run_id, top_k
        self.requests.append(request)
        return (
            GoldBlindEvidence(
                item_id="item-1",
                text="public retrieval evidence",
                rank=1,
                created_at="2023-01-01T00:00:00Z",
            ),
        )


class _CapturingAnswerer:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, object]] = []

    def answer(self, request: Mapping[str, object]) -> object:
        self.requests.append(request)
        return {"answer": "generated response"}


def _judge_uses_expected_terms(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del candidate_answer, ground_truth, forbidden_terms
    assert expected_terms == (_ANSWER_TERM,)
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _load_official_locomo_case(tmp_path: Path) -> PublicBenchmarkCase:
    dataset = tmp_path / "locomo-answer-terms.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "sample_id": "conv-26",
                    "conversation": {
                        "speaker_a": "Alice",
                        "session_1": [
                            {
                                "dia_id": "D1:1",
                                "speaker": "Alice",
                                "text": "Alice bought green tea.",
                            }
                        ],
                    },
                    "qa": [
                        {
                            "question": "What did Alice buy?",
                            "answer": _ANSWER_TERM,
                            "evidence": ["D1:1"],
                            "category": 4,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    cases = _load_memory_comparison_cases(
        dataset,
        locomo_ingest_mode=LOCOMO_INGEST_OFFICIAL_TURNS,
    )
    assert len(cases) == 1
    return cases[0]


def _build_contract(case: PublicBenchmarkCase):
    key = JudgeRunKey.issue(run_id=_RUN_ID, case_id=case.case_id)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN_ID,
        comparison_binding_commitment_sha256="9" * 64,
        expected_cases=(
            GoldBlindExpectedDispatchCase(
                case_id=case.case_id,
                retrieval_backend_id=_RETRIEVAL_BACKEND,
                answer_backend_id=_ANSWER_BACKEND,
                judge_backend_id=_JUDGE_BACKEND,
            ),
        ),
    )
    return (
        build_gold_blind_contract(
            case,
            run_id=_RUN_ID,
            judge_key=key,
            dispatch_ledger=ledger,
        ),
        key,
        ledger,
    )


def test_official_locomo_answer_terms_are_private_and_judge_only(tmp_path: Path) -> None:
    case = _load_official_locomo_case(tmp_path)
    assert case.case_id == _CASE_ID
    assert case.expected_terms == (_ANSWER_TERM,)
    assert case.metadata["answer_terms"] == (_ANSWER_TERM,)

    contract, key, ledger = _build_contract(case)
    retriever = _CapturingRetriever()
    answerer = _CapturingAnswerer()
    evidence = dispatch_retrieval(
        retriever,
        contract.retrieval_request,
        backend_id=_RETRIEVAL_BACKEND,
        dispatch_ledger=ledger,
        run_id=_RUN_ID,
        top_k=1,
    )
    answer_request = contract.answer_request(evidence)
    dispatch_answer(
        answerer,
        answer_request,
        backend_id=_ANSWER_BACKEND,
        dispatch_ledger=ledger,
        run_id=_RUN_ID,
        case_id=case.case_id,
    )
    dispatch_judge(
        create_trusted_gold_blind_evaluator(_judge_uses_expected_terms),
        contract.judge_channel,
        backend_id=_JUDGE_BACKEND,
        dispatch_ledger=ledger,
        answer_binding=issue_gold_blind_judge_dispatch_binding(
            ledger,
            run_id=_RUN_ID,
            case_id=case.case_id,
            backend_id=_JUDGE_BACKEND,
        ),
        key=key,
        run_id=_RUN_ID,
        case_id=case.case_id,
    )

    assert contract.retrieval_request.public_metadata == {"category": 4}
    provider_view = json.dumps(
        {"retrieval": retriever.requests[0], "answer": answerer.requests[0]},
        sort_keys=True,
    )
    assert "answer_terms" not in provider_view
    assert _ANSWER_TERM not in provider_view


@pytest.mark.parametrize("alias", ("answer_term", "answer_terms_v2"))
def test_answer_term_metadata_aliases_fail_closed(tmp_path: Path, alias: str) -> None:
    case = _load_official_locomo_case(tmp_path)
    aliased_case = replace(
        case,
        metadata={**case.metadata, alias: (_ANSWER_TERM,)},
    )

    with pytest.raises(GoldBlindContractError, match="Ambiguous evaluator metadata alias"):
        _build_contract(aliased_case)
