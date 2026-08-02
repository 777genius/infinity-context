from __future__ import annotations

import asyncio
import base64
import copy
import importlib
import json
import pickle
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest
from infinity_context_server.memory_comparison_gold_blind import (
    GoldBlindCaseContract,
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    ANSWER_REQUEST_SCHEMA_VERSION,
    AUDIT_EVIDENCE_SCHEMA_VERSION,
    JUDGE_CHANNEL_KIND,
    JUDGE_RESULT_SCHEMA_VERSION,
    RETRIEVAL_REQUEST_SCHEMA_VERSION,
    ExactGoldJudgeChannel,
    GoldBlindAnswerRequest,
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    GoldBlindRetrievalRequest,
    GoldBlindRunDispatchLedger,
    JudgeRunKey,
    TrustedGoldBlindEvaluator,
    VerifiedGoldBlindExecutionValidation,
    canonical_gold_json,
    create_exact_gold_judge_channel,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    gold_blind_audit_commitment,
    issue_gold_blind_judge_dispatch_binding,
    verified_gold_blind_execution_report,
    verify_gold_blind_execution,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_SECRET = "ULTRAVIOLET-SAPPHIRE-9271"
_CGJ_OBFUSCATED_SECRET = "\u034f".join(_SECRET)
_VS_OBFUSCATED_SECRET = "\ufe0f".join(_SECRET)
_RUN_ID = "run-1"
_COMPARISON_BINDING = "9" * 64
_CASE_ID = "case-1"
_RETRIEVAL_BACKEND = "memo-retrieval-v1"
_ANSWER_BACKEND = "official-answer-v1"
_JUDGE_BACKEND = "official-judge-v1"


def _case(
    *,
    benchmark: str = "locomo",
    question: str = "Which color token was mentioned?",
    metadata: object | None = None,
    expected_terms: tuple[str, ...] = (_SECRET, "secondary expected"),
) -> PublicBenchmarkCase:
    source_metadata: Any = (
        {
            "_evaluator_ground_truth": {
                "answer": _SECRET,
                "support": [{"expected_value": "secondary expected"}],
            },
            "answer_preview": _SECRET,
            "reference_date": "2 January 2023",
            "category": 3,
            "question_type": "multi_session",
            "language": "en",
            "internal_note": "not public",
        }
        if metadata is None
        else metadata
    )
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=_CASE_ID,
        question=question,
        expected_terms=expected_terms,
        forbidden_terms=("forbidden evaluator term",),
        memory_scope_external_ref="memory-scope-1",
        thread_external_ref="thread-1",
        metadata=source_metadata,
    )


def _expected_case(
    *,
    case_id: str = _CASE_ID,
    retrieval_backend: str = _RETRIEVAL_BACKEND,
    answer_backend: str = _ANSWER_BACKEND,
    judge_backend: str = _JUDGE_BACKEND,
) -> GoldBlindExpectedDispatchCase:
    return GoldBlindExpectedDispatchCase(
        case_id=case_id,
        retrieval_backend_id=retrieval_backend,
        answer_backend_id=answer_backend,
        judge_backend_id=judge_backend,
    )


def _contract(
    case: PublicBenchmarkCase | None = None,
    *,
    run_id: str = _RUN_ID,
    key: JudgeRunKey | None = None,
    expected_cases: tuple[GoldBlindExpectedDispatchCase, ...] | None = None,
) -> tuple[GoldBlindCaseContract, JudgeRunKey, GoldBlindRunDispatchLedger]:
    source_case = case or _case()
    judge_key = key or JudgeRunKey.issue(run_id=run_id, case_id=source_case.case_id)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=run_id,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=expected_cases or (_expected_case(case_id=source_case.case_id),),
    )
    contract = build_gold_blind_contract(
        source_case,
        run_id=run_id,
        judge_key=judge_key,
        dispatch_ledger=ledger,
    )
    return contract, judge_key, ledger


class _CapturingBackend:
    def __init__(self, evidence: tuple[GoldBlindEvidence, ...] | None = None) -> None:
        self.requests: list[Mapping[str, object]] = []
        self.evidence = evidence or _evidence()

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        self.requests.append(request)
        del run_id, top_k
        return self.evidence


class _CapturingAnswerer:
    def __init__(self) -> None:
        self.requests: list[Mapping[str, object]] = []

    def answer(self, request: Mapping[str, object]) -> object:
        self.requests.append(request)
        return {"answer": "provider output"}


class _HostileDict(dict[str, object]):
    touched = False

    def __iter__(self) -> Any:
        type(self).touched = True
        raise AssertionError("hostile mapping iterated")

    def __contains__(self, key: object) -> bool:
        del key
        type(self).touched = True
        raise AssertionError("hostile mapping inspected")

    def items(self) -> Any:
        type(self).touched = True
        raise AssertionError("hostile mapping items inspected")


class _HostileString(str):
    touched = False

    def __len__(self) -> int:
        type(self).touched = True
        raise AssertionError("hostile string length read")

    def strip(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        type(self).touched = True
        raise AssertionError("hostile string normalized")

    def casefold(self) -> str:
        type(self).touched = True
        raise AssertionError("hostile string casefolded")


def _trusted_correct(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    assert type(ground_truth) is MappingProxyType
    assert type(ground_truth["support"]) is tuple  # type: ignore[index]
    assert type(ground_truth["support"][0]) is MappingProxyType  # type: ignore[index]
    assert expected_terms == (_SECRET, "secondary expected")
    assert forbidden_terms == ("forbidden evaluator term",)
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _trusted_raw_return(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> Any:
    del expected_terms, forbidden_terms
    return ground_truth


def _trusted_failure(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del expected_terms, forbidden_terms
    raise RuntimeError(repr(ground_truth))


def _trusted_cancel(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    raise asyncio.CancelledError(_SECRET)


def _trusted_mutated_result(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    result = GoldBlindJudgeResult(verdict="correct", score=1.0)
    object.__setattr__(result, "verdict", _SECRET)
    return result


def _evaluator(
    callback: Any = _trusted_correct,
) -> TrustedGoldBlindEvaluator:
    return create_trusted_gold_blind_evaluator(callback)


def _dispatch_retrieval(
    backend: _CapturingBackend,
    contract: GoldBlindCaseContract,
    ledger: GoldBlindRunDispatchLedger,
    *,
    backend_id: str = _RETRIEVAL_BACKEND,
) -> object:
    return dispatch_retrieval(
        backend,
        contract.retrieval_request,
        backend_id=backend_id,
        dispatch_ledger=ledger,
        run_id=_RUN_ID,
        top_k=10,
    )


def _evidence() -> tuple[GoldBlindEvidence, ...]:
    return (
        GoldBlindEvidence(
            item_id="item-1",
            text="retrieved distractor",
            rank=1,
            created_at="2023-01-02T10:00:00Z",
        ),
        GoldBlindEvidence(
            item_id="item-2",
            text="second retrieved item",
            rank=2,
            created_at=None,
        ),
    )


def _answer_request(
    contract: GoldBlindCaseContract, ledger: GoldBlindRunDispatchLedger
) -> GoldBlindAnswerRequest:
    del ledger
    return contract.answer_request(_evidence())


def _dispatch_answer(
    answerer: _CapturingAnswerer,
    request: GoldBlindAnswerRequest,
    ledger: GoldBlindRunDispatchLedger,
    *,
    backend_id: str = _ANSWER_BACKEND,
) -> object:
    return dispatch_answer(
        answerer,
        request,
        backend_id=backend_id,
        dispatch_ledger=ledger,
        run_id=_RUN_ID,
        case_id=_CASE_ID,
    )


def _dispatch_judge(
    contract: GoldBlindCaseContract,
    key: JudgeRunKey,
    ledger: GoldBlindRunDispatchLedger,
    *,
    evaluator: TrustedGoldBlindEvaluator | None = None,
    backend_id: str = _JUDGE_BACKEND,
) -> dict[str, object]:
    return dispatch_judge(
        evaluator or _evaluator(),
        contract.judge_channel,
        backend_id=backend_id,
        dispatch_ledger=ledger,
        answer_binding=issue_gold_blind_judge_dispatch_binding(
            ledger,
            run_id=_RUN_ID,
            case_id=_CASE_ID,
            backend_id=backend_id,
        ),
        key=key,
        run_id=_RUN_ID,
        case_id=_CASE_ID,
    )


def test_exact_provider_views_and_sealed_judge_result() -> None:
    contract, key, ledger = _contract()
    backend = _CapturingBackend()
    answerer = _CapturingAnswerer()

    assert _dispatch_retrieval(backend, contract, ledger) == _evidence()
    request = _answer_request(contract, ledger)
    assert _dispatch_answer(answerer, request, ledger) == {"answer": "provider output"}
    assert _dispatch_judge(contract, key, ledger) == {
        "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
        "verdict": "correct",
        "score": 1.0,
    }

    retrieval = backend.requests[0]
    assert retrieval["schema_version"] == RETRIEVAL_REQUEST_SCHEMA_VERSION
    assert set(retrieval) == {
        "schema_version",
        "benchmark",
        "case_id",
        "question",
        "session",
        "public_metadata",
    }
    answer = answerer.requests[0]
    assert answer == {
        "schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "question": "Which color token was mentioned?",
        "reference_date": "2 January 2023",
        "question_date": None,
        "evidence": [
            {
                "item_id": "item-1",
                "text": "retrieved distractor",
                "rank": 1,
                "created_at": "2023-01-02T10:00:00Z",
            },
            {
                "item_id": "item-2",
                "text": "second retrieved item",
                "rank": 2,
                "created_at": None,
            },
        ],
    }
    serialized = json.dumps({"retrieval": retrieval, "answer": answer})
    assert _SECRET.casefold() not in serialized.casefold()
    assert "ground_truth" not in serialized


def test_longmemeval_answer_session_aliases_remain_evaluator_only() -> None:
    case = _case(
        benchmark="longmemeval",
        metadata={
            "_evaluator_ground_truth": _SECRET,
            "answer_session_aliases": ["session-0001"],
            "question_type": "single-session-user",
        },
    )
    contract, _, ledger = _contract(case)
    backend = _CapturingBackend()

    _dispatch_retrieval(backend, contract, ledger)

    assert "answer_session_aliases" not in json.dumps(backend.requests[0], sort_keys=True)
    assert contract.retrieval_request.public_metadata == {"question_type": "single-session-user"}


def test_complete_backend_bound_receipts_issue_sealed_admission_and_report() -> None:
    contract, key, ledger = _contract()
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    _dispatch_judge(contract, key, ledger)

    validation = verify_gold_blind_execution(ledger)
    assert type(validation) is VerifiedGoldBlindExecutionValidation
    report = verified_gold_blind_execution_report(validation)
    assert report["expected_case_count"] == 1
    assert report["retrieval_dispatch_count"] == 1
    assert report["answer_dispatch_count"] == 1
    assert report["judge_dispatch_count"] == 1
    assert all(
        type(report[name]) is str and len(report[name]) == 64
        for name in (
            "retrieval_identity",
            "answer_identity",
            "judge_identity",
            "commitment",
        )
    )
    assert _SECRET.casefold() not in json.dumps(report).casefold()
    with pytest.raises(GoldBlindContractError):
        verified_gold_blind_execution_report(report)  # type: ignore[arg-type]


@pytest.mark.parametrize("missing_stage", ("retrieval", "answer", "judge"))
def test_missing_dispatch_receipt_fails_admission(missing_stage: str) -> None:
    contract, _, ledger = _contract()
    if missing_stage != "retrieval":
        _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    if missing_stage not in ("retrieval", "answer"):
        _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    with pytest.raises(GoldBlindContractError, match="incomplete"):
        verify_gold_blind_execution(ledger)


def test_duplicate_unexpected_and_backend_role_mismatch_fail_before_second_call() -> None:
    contract, _, ledger = _contract()
    backend = _CapturingBackend()
    _dispatch_retrieval(backend, contract, ledger)
    with pytest.raises(
        GoldBlindContractError, match="ledger verification|binding mismatch|integrity failed"
    ):
        _dispatch_retrieval(backend, contract, ledger)
    assert len(backend.requests) == 1

    wrong_backend_ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN_ID,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(_expected_case(retrieval_backend="expected-backend"),),
    )
    with pytest.raises(
        GoldBlindContractError, match="ledger verification|binding mismatch|integrity failed"
    ):
        _dispatch_retrieval(backend, contract, wrong_backend_ledger)
    assert len(backend.requests) == 1

    unexpected_ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN_ID,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(_expected_case(case_id="another-case"),),
    )
    with pytest.raises(
        GoldBlindContractError, match="ledger verification|binding mismatch|integrity failed"
    ):
        _dispatch_retrieval(backend, contract, unexpected_ledger)
    assert len(backend.requests) == 1


def test_public_report_and_mutated_validation_are_never_admission_input() -> None:
    contract, key, ledger = _contract()
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    _dispatch_judge(contract, key, ledger)
    validation = verify_gold_blind_execution(ledger)
    report = verified_gold_blind_execution_report(validation)

    with pytest.raises(GoldBlindContractError):
        verify_gold_blind_execution(report)  # type: ignore[arg-type]
    object.__setattr__(
        validation,
        "_VerifiedGoldBlindExecutionValidation__run_id",
        "rebound",
    )
    with pytest.raises(GoldBlindContractError, match="integrity"):
        verified_gold_blind_execution_report(validation)


def test_raw_gold_return_and_mutated_result_never_leave_judge_dispatch() -> None:
    for callback in (_trusted_raw_return, _trusted_mutated_result):
        contract, key, ledger = _contract()
        with pytest.raises(GoldBlindContractError) as captured:
            _dispatch_judge(
                contract,
                key,
                ledger,
                evaluator=_evaluator(callback),
            )
        assert captured.value.__cause__ is None
        assert _SECRET.casefold() not in str(captured.value).casefold()


def test_stateful_and_closure_judges_are_rejected_before_receiving_gold() -> None:
    class StatefulJudge:
        retained: object | None = None

        def __call__(
            self,
            *,
            candidate_answer: object,
            ground_truth: object,
            expected_terms: tuple[str, ...],
            forbidden_terms: tuple[str, ...],
        ) -> GoldBlindJudgeResult:
            del expected_terms, forbidden_terms
            self.retained = ground_truth
            return GoldBlindJudgeResult(verdict="correct", score=1.0)

    stateful = StatefulJudge()
    with pytest.raises(GoldBlindContractError, match="exact function"):
        create_trusted_gold_blind_evaluator(stateful)  # type: ignore[arg-type]
    assert stateful.retained is None

    retained: list[object] = []

    def closure_factory() -> Any:
        def retaining_judge(
            *,
            candidate_answer: object,
            ground_truth: object,
            expected_terms: tuple[str, ...],
            forbidden_terms: tuple[str, ...],
        ) -> GoldBlindJudgeResult:
            del expected_terms, forbidden_terms
            retained.append(ground_truth)
            return GoldBlindJudgeResult(verdict="correct", score=1.0)

        return retaining_judge

    with pytest.raises(GoldBlindContractError, match="stateless"):
        create_trusted_gold_blind_evaluator(closure_factory())
    assert retained == []


def test_judge_failure_and_cancellation_are_fresh_and_secret_free() -> None:
    contract, key, ledger = _contract()
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    with pytest.raises(GoldBlindContractError, match="evaluator failed") as failure:
        _dispatch_judge(
            contract,
            key,
            ledger,
            evaluator=_evaluator(_trusted_failure),
        )
    assert failure.value.__cause__ is None
    assert _SECRET.casefold() not in str(failure.value).casefold()

    contract, key, ledger = _contract()
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    with pytest.raises(asyncio.CancelledError) as cancelled:
        _dispatch_judge(
            contract,
            key,
            ledger,
            evaluator=_evaluator(_trusted_cancel),
        )
    assert cancelled.value.args == ()
    assert cancelled.value.__cause__ is None


def test_key_and_channel_rebinding_is_rejected_by_audit_and_dispatch() -> None:
    contract, key, ledger = _contract()
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    _dispatch_answer(_CapturingAnswerer(), _answer_request(contract, ledger), ledger)
    answer_binding = issue_gold_blind_judge_dispatch_binding(
        ledger,
        run_id=_RUN_ID,
        case_id=_CASE_ID,
        backend_id=_JUDGE_BACKEND,
    )
    object.__setattr__(key, "_JudgeRunKey__run_id", "rebound")
    object.__setattr__(contract.judge_channel, "_ExactGoldJudgeChannel__run_id", "rebound")

    with pytest.raises(GoldBlindContractError, match="integrity"):
        contract.audit_evidence()
    with pytest.raises(GoldBlindContractError, match="evaluator failed"):
        dispatch_judge(
            _evaluator(),
            contract.judge_channel,
            backend_id=_JUDGE_BACKEND,
            dispatch_ledger=ledger,
            answer_binding=answer_binding,
            key=key,
            run_id=_RUN_ID,
            case_id=_CASE_ID,
        )


@pytest.mark.parametrize(
    ("attribute", "value"),
    (
        ("_ExactGoldJudgeChannel__ground_truth_json", b'{"answer":"tampered"}'),
        ("_ExactGoldJudgeChannel__expected_terms", ("tampered",)),
        ("_ExactGoldJudgeChannel__forbidden_terms", ("tampered",)),
        ("_ExactGoldJudgeChannel__integrity_commitment", "0" * 64),
    ),
)
def test_each_channel_integrity_field_is_verified_on_every_audit(
    attribute: str,
    value: object,
) -> None:
    contract, _, _ = _contract()
    object.__setattr__(contract.judge_channel, attribute, value)
    with pytest.raises(GoldBlindContractError, match="integrity"):
        contract.audit_evidence()


def test_unregistered_replayed_channel_is_rejected() -> None:
    contract, key, _ = _contract()
    replay = object.__new__(ExactGoldJudgeChannel)
    for attribute in (
        "_ExactGoldJudgeChannel__key",
        "_ExactGoldJudgeChannel__run_id",
        "_ExactGoldJudgeChannel__case_id",
        "_ExactGoldJudgeChannel__ground_truth_json",
        "_ExactGoldJudgeChannel__expected_terms",
        "_ExactGoldJudgeChannel__forbidden_terms",
        "_ExactGoldJudgeChannel__integrity_commitment",
    ):
        object.__setattr__(replay, attribute, getattr(contract.judge_channel, attribute))
    with pytest.raises(GoldBlindContractError, match="registration"):
        gold_blind_audit_commitment(
            key=key,
            channel=replay,
            run_id=_RUN_ID,
            case_id=_CASE_ID,
        )


@pytest.mark.parametrize(
    "payload",
    (
        b'{"answer":"first","answer":"second"}',
        b'{"b":2, "a":1}',
        b'{"a":1e0}',
    ),
)
def test_public_channel_factory_requires_exact_unique_canonical_json(
    payload: bytes,
) -> None:
    key = JudgeRunKey.issue(run_id=_RUN_ID, case_id=_CASE_ID)
    with pytest.raises(GoldBlindContractError):
        create_exact_gold_judge_channel(
            key=key,
            run_id=_RUN_ID,
            case_id=_CASE_ID,
            ground_truth_json=payload,
            expected_terms=("expected",),
            forbidden_terms=(),
        )


def test_canonical_channel_factory_accepts_exact_bytes_and_binds_terms() -> None:
    key = JudgeRunKey.issue(run_id=_RUN_ID, case_id=_CASE_ID)
    payload = canonical_gold_json({"answer": _SECRET, "nested": [1, True]})
    channel = create_exact_gold_judge_channel(
        key=key,
        run_id=_RUN_ID,
        case_id=_CASE_ID,
        ground_truth_json=payload,
        expected_terms=("expected",),
        forbidden_terms=("forbidden",),
    )
    commitment = gold_blind_audit_commitment(
        key=key,
        channel=channel,
        run_id=_RUN_ID,
        case_id=_CASE_ID,
    )
    assert len(commitment) == 64


@pytest.mark.parametrize("term", (True, 1.0, _HostileString("hostile")))
def test_terms_require_exact_bounded_nonempty_strings(term: object) -> None:
    _HostileString.touched = False
    case = replace(_case(), expected_terms=(term,))  # type: ignore[arg-type]
    with pytest.raises(GoldBlindContractError, match="exact string"):
        _contract(case)
    assert _HostileString.touched is False


@pytest.mark.parametrize(
    "question",
    (
        "Use ex\u034fpected answer from metadata",
        "Use expected ans\ufe0fwer from metadata",
        f"Return {_CGJ_OBFUSCATED_SECRET}",
        f"Return {_VS_OBFUSCATED_SECRET}",
    ),
)
def test_relevant_default_ignorables_cannot_obfuscate_labels_or_gold(
    question: str,
) -> None:
    with pytest.raises(GoldBlindContractError):
        _contract(_case(question=question))


def test_security_scan_does_not_mutate_provider_payload() -> None:
    question = "What does the heart emoji \u2764\ufe0f mean here?"
    contract, _, ledger = _contract(_case(question=question))
    backend = _CapturingBackend()
    _dispatch_retrieval(backend, contract, ledger)
    assert backend.requests[0]["question"] == question


def test_hostile_string_subclasses_fail_before_normalization_or_regex() -> None:
    _HostileString.touched = False
    with pytest.raises(GoldBlindContractError, match="must be issued"):
        GoldBlindRetrievalRequest(
            benchmark="locomo",
            case_id=_CASE_ID,
            question=_HostileString("question"),
            public_metadata={},
        )
    with pytest.raises(GoldBlindContractError, match="exact string"):
        _contract(
            _case(
                metadata={
                    "_evaluator_ground_truth": _SECRET,
                    "reference_date": _HostileString("2023"),
                }
            )
        )
    assert _HostileString.touched is False


def test_oversized_base64_like_token_fails_closed() -> None:
    encoded = base64.b64encode(b"x" * 17_000).decode()
    assert len(encoded) > 22_600
    with pytest.raises(GoldBlindContractError, match="must be issued"):
        GoldBlindRetrievalRequest(
            benchmark="locomo",
            case_id=_CASE_ID,
            question=encoded,
            public_metadata={},
        )


def test_coincidental_gold_in_evidence_is_preserved_with_timestamp() -> None:
    contract, _, ledger = _contract()
    evidence = (
        GoldBlindEvidence(
            item_id="item-1",
            text=_SECRET,
            rank=1,
            created_at="2023-01-02T10:00:00Z",
        ),
    )
    _dispatch_retrieval(_CapturingBackend(evidence), contract, ledger)
    request = contract.answer_request(evidence)
    answerer = _CapturingAnswerer()
    _dispatch_answer(answerer, request, ledger)
    assert answerer.requests[0]["evidence"] == [
        {
            "item_id": "item-1",
            "text": _SECRET,
            "rank": 1,
            "created_at": "2023-01-02T10:00:00Z",
        }
    ]


@pytest.mark.parametrize(
    ("benchmark", "metadata", "reference_date", "question_date"),
    (
        (
            "locomo",
            {
                "_evaluator_ground_truth": _SECRET,
                "reference_date_human": "3 February 2023",
            },
            "3 February 2023",
            None,
        ),
        (
            "longmemeval",
            {
                "_evaluator_ground_truth": _SECRET,
                "question_date": "2023/05/21 10:30 (Sunday)",
            },
            None,
            "Sunday, May 21, 2023",
        ),
    ),
)
def test_answer_dto_preserves_exact_official_temporal_renderer_inputs(
    benchmark: str,
    metadata: dict[str, object],
    reference_date: str | None,
    question_date: str | None,
) -> None:
    case = _case(benchmark=benchmark, metadata=metadata)
    contract, _, ledger = _contract(case)
    _dispatch_retrieval(_CapturingBackend(), contract, ledger)
    request = _answer_request(contract, ledger)
    assert request.reference_date == reference_date
    assert request.question_date == question_date
    assert [
        {"memory": item.text, "created_at": item.created_at or ""} for item in request.evidence
    ] == [
        {
            "memory": "retrieved distractor",
            "created_at": "2023-01-02T10:00:00Z",
        },
        {"memory": "second retrieved item", "created_at": ""},
    ]

    try:
        renderer = importlib.import_module(
            "infinity_context_server.memory_comparison_mem0_official_prompt_renderer"
        )
        models = importlib.import_module("infinity_context_server.memory_comparison_models")
    except ModuleNotFoundError:
        return
    original_memories = tuple(
        models.RetrievedMemory(
            text=item.text,
            rank=item.rank,
            item_id=item.item_id,
            created_at=item.created_at,
        )
        for item in request.evidence
    )
    public_case = replace(
        case,
        metadata={
            key: value for key, value in metadata.items() if key != "_evaluator_ground_truth"
        },
    )
    original_prompt = renderer.render_mem0_official_answer_prompt(case, original_memories)
    public_prompt = renderer.render_mem0_official_answer_prompt(public_case, original_memories)
    assert public_prompt.user.encode() == original_prompt.user.encode()


def test_audit_commitment_is_stable_gold_free_and_revalidated() -> None:
    contract, _, _ = _contract()
    first = contract.audit_evidence()
    assert first == contract.audit_evidence()
    assert first == {
        "schema_version": AUDIT_EVIDENCE_SCHEMA_VERSION,
        "run_id": _RUN_ID,
        "case_id": _CASE_ID,
        "retrieval_schema_version": RETRIEVAL_REQUEST_SCHEMA_VERSION,
        "answer_schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "judge_channel": JUDGE_CHANNEL_KIND,
        "gold_commitment": first["gold_commitment"],
        "excluded_field_count": 9,
    }
    assert _SECRET.casefold() not in json.dumps(first).casefold()


@pytest.mark.parametrize(
    "security_type",
    (
        GoldBlindEvidence,
        GoldBlindRetrievalRequest,
        GoldBlindAnswerRequest,
        GoldBlindJudgeResult,
        JudgeRunKey,
        ExactGoldJudgeChannel,
        TrustedGoldBlindEvaluator,
        GoldBlindExpectedDispatchCase,
        GoldBlindRunDispatchLedger,
        VerifiedGoldBlindExecutionValidation,
        GoldBlindCaseContract,
    ),
)
def test_security_types_are_final(security_type: type[object]) -> None:
    with pytest.raises(TypeError, match="final"):
        type("MaliciousSubclass", (security_type,), {})


@pytest.mark.parametrize(
    "factory",
    (
        lambda contract, key, ledger: contract,
        lambda contract, key, ledger: contract.judge_channel,
        lambda contract, key, ledger: key,
        lambda contract, key, ledger: ledger,
        lambda contract, key, ledger: _evaluator(),
    ),
)
def test_capabilities_are_redacted_nonserializable(factory: Any) -> None:
    contract, key, ledger = _contract()
    value = factory(contract, key, ledger)
    assert _SECRET.casefold() not in repr(value).casefold()
    for serializer in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            serializer(value)


def test_hostile_source_mapping_rejected_without_iteration() -> None:
    hostile = _HostileDict({"_evaluator_ground_truth": _SECRET})
    _HostileDict.touched = False
    with pytest.raises(GoldBlindContractError, match="exact dict"):
        _contract(_case(metadata=hostile))
    assert _HostileDict.touched is False


@pytest.mark.parametrize(
    ("verdict", "score"),
    (
        ("unknown", 1.0),
        ("correct", 1),
        ("correct", True),
        (_HostileString("correct"), 1.0),
    ),
)
def test_judge_results_require_exact_bounded_allowlisted_fields(
    verdict: object,
    score: object,
) -> None:
    _HostileString.touched = False
    with pytest.raises(GoldBlindContractError):
        GoldBlindJudgeResult(verdict=verdict, score=score)  # type: ignore[arg-type]
    assert _HostileString.touched is False


@pytest.mark.parametrize("term", ("", "   "))
def test_terms_must_be_nonempty_after_security_normalization(term: str) -> None:
    with pytest.raises(GoldBlindContractError, match="non-empty"):
        _contract(replace(_case(), expected_terms=(term,)))


def test_expected_backend_selection_is_snapshotted_before_object_mutation() -> None:
    expected = _expected_case()
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN_ID,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(expected,),
    )
    object.__setattr__(expected, "retrieval_backend_id", "mutated-backend")
    key = JudgeRunKey.issue(run_id=_RUN_ID, case_id=_CASE_ID)
    contract = build_gold_blind_contract(
        _case(), run_id=_RUN_ID, judge_key=key, dispatch_ledger=ledger
    )
    backend = _CapturingBackend()
    _dispatch_retrieval(backend, contract, ledger)

    assert len(backend.requests) == 1


def test_mutated_ledger_binding_fails_before_provider_call() -> None:
    contract, _, ledger = _contract()
    backend = _CapturingBackend()
    object.__setattr__(
        ledger,
        "_GoldBlindRunDispatchLedger__run_id",
        "rebound",
    )

    with pytest.raises(
        GoldBlindContractError, match="ledger verification|binding mismatch|integrity failed"
    ):
        _dispatch_retrieval(backend, contract, ledger)
    assert backend.requests == []


def test_failed_provider_call_rolls_back_reserved_receipt() -> None:
    class FailingBackend:
        calls = 0

        def search(
            self,
            request: Mapping[str, object],
            *,
            run_id: str,
            top_k: int,
        ) -> object:
            del request, run_id, top_k
            self.calls += 1
            raise RuntimeError("provider failed")

    contract, _, ledger = _contract()
    backend = FailingBackend()
    with pytest.raises(GoldBlindContractError, match="Retrieval provider failed"):
        dispatch_retrieval(
            backend,
            contract.retrieval_request,
            backend_id=_RETRIEVAL_BACKEND,
            dispatch_ledger=ledger,
            run_id=_RUN_ID,
            top_k=10,
        )
    assert backend.calls == 1
    with pytest.raises(GoldBlindContractError, match="incomplete"):
        verify_gold_blind_execution(ledger)
