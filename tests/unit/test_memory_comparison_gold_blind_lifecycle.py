from __future__ import annotations

import importlib
import json
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

import pytest
from infinity_context_server.memory_comparison_gold_blind import (
    GoldBlindCaseContract,
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindAnswerRequest,
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    GoldBlindRunDispatchLedger,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    create_trusted_gold_blind_evaluator,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
    verified_gold_blind_execution_report,
    verify_gold_blind_execution,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN = "lifecycle-run"
_COMPARISON_BINDING = "9" * 64
_CASE = "case-1"
_RETRIEVAL = "retrieval-v1"
_ANSWER = "answer-v1"
_JUDGE = "judge-v1"
_SECRET = "PRIVATE-GOLD-441"
_CALLS = 0
_CANDIDATE_CAPTURED = False
_CANDIDATE_SENTINEL = "BOUND-CANDIDATE-783"


def _case(case_id: str = _CASE) -> PublicBenchmarkCase:
    return PublicBenchmarkCase(
        benchmark="locomo",
        case_id=case_id,
        question="What happened?",
        expected_terms=(_SECRET,),
        metadata={
            "_evaluator_ground_truth": {"answer": _SECRET},
            "reference_date": "2 January 2023",
        },
    )


def _expected(case_id: str = _CASE) -> GoldBlindExpectedDispatchCase:
    return GoldBlindExpectedDispatchCase(
        case_id=case_id,
        retrieval_backend_id=_RETRIEVAL,
        answer_backend_id=_ANSWER,
        judge_backend_id=_JUDGE,
    )


def _setup() -> tuple[GoldBlindCaseContract, JudgeRunKey, GoldBlindRunDispatchLedger]:
    key = JudgeRunKey.issue(run_id=_RUN, case_id=_CASE)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(_expected(),),
    )
    contract = build_gold_blind_contract(
        _case(),
        run_id=_RUN,
        judge_key=key,
        dispatch_ledger=ledger,
    )
    return contract, key, ledger


def _evidence(text: str = "retrieved") -> tuple[GoldBlindEvidence, ...]:
    return (
        GoldBlindEvidence(
            item_id="item-1",
            text=text,
            rank=1,
            created_at="2023-01-02T10:00:00Z",
        ),
    )


class _Retriever:
    def __init__(self, evidence: tuple[GoldBlindEvidence, ...] | None = None) -> None:
        self.evidence = evidence or _evidence()
        self.calls = 0

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del request, run_id, top_k
        self.calls += 1
        return self.evidence


class _Answerer:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def answer(self, request: Mapping[str, object]) -> object:
        del request
        self.calls += 1
        if self.fail:
            raise RuntimeError("answer failed")
        return {"answer": "ok"}


class _RichAnswerer:
    def answer(self, request: Mapping[str, object]) -> object:
        del request
        return {
            "answer": _CANDIDATE_SENTINEL,
            "citations": [{"item_id": "item-1", "rank": 1}],
        }


class _WrongAnswerer:
    def answer(self, request: Mapping[str, object]) -> object:
        del request
        return {"answer": "definitely-wrong"}


class _AsyncRetriever:
    calls = 0

    async def _result(self) -> tuple[GoldBlindEvidence, ...]:
        return _evidence()

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> object:
        del request, run_id, top_k
        self.calls += 1
        return self._result()


class _AsyncAnswerer:
    calls = 0

    async def _result(self) -> object:
        return {"answer": "async"}

    def answer(self, request: Mapping[str, object]) -> object:
        del request
        self.calls += 1
        return self._result()


def _retrieve(
    contract: GoldBlindCaseContract,
    ledger: GoldBlindRunDispatchLedger,
    retriever: object | None = None,
    *,
    backend_id: str = _RETRIEVAL,
) -> tuple[GoldBlindEvidence, ...]:
    return dispatch_retrieval(
        retriever or _Retriever(),  # type: ignore[arg-type]
        contract.retrieval_request,
        backend_id=backend_id,
        dispatch_ledger=ledger,
        run_id=_RUN,
        top_k=5,
    )


def _answer_request(
    contract: GoldBlindCaseContract,
    ledger: GoldBlindRunDispatchLedger,
    evidence: tuple[GoldBlindEvidence, ...] | None = None,
) -> GoldBlindAnswerRequest:
    del ledger
    return contract.answer_request(evidence or _evidence())


def _dispatch_answer(
    request: GoldBlindAnswerRequest,
    ledger: GoldBlindRunDispatchLedger,
    answerer: object | None = None,
    *,
    case_id: str = _CASE,
) -> object:
    return dispatch_answer(
        answerer or _Answerer(),  # type: ignore[arg-type]
        request,
        backend_id=_ANSWER,
        dispatch_ledger=ledger,
        run_id=_RUN,
        case_id=case_id,
    )


def _correct(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    global _CALLS
    _CALLS += 1
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _capture_candidate(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    assert type(candidate_answer) is MappingProxyType
    assert candidate_answer["answer"] == _CANDIDATE_SENTINEL  # type: ignore[index]
    citations = candidate_answer["citations"]  # type: ignore[index]
    assert type(citations) is tuple
    assert type(citations[0]) is MappingProxyType
    global _CANDIDATE_CAPTURED
    _CANDIDATE_CAPTURED = True
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _semantic_candidate_judge(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    verdict = (
        "correct"
        if candidate_answer["answer"] == _CANDIDATE_SENTINEL  # type: ignore[index]
        else "incorrect"
    )
    return GoldBlindJudgeResult(verdict=verdict, score=1.0 if verdict == "correct" else 0.0)


async def _async_judge(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    return GoldBlindJudgeResult(verdict="correct", score=1.0)


def _system_exit(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    raise SystemExit(_SECRET)


def _keyboard_interrupt(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    raise KeyboardInterrupt(_SECRET)


class _SecretBaseException(BaseException):
    pass


def _custom_base_exception(
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del ground_truth, expected_terms, forbidden_terms
    raise _SecretBaseException(_SECRET)


def _judge(
    contract: GoldBlindCaseContract,
    key: JudgeRunKey,
    ledger: GoldBlindRunDispatchLedger,
    callback: object = _correct,
    *,
    backend_id: str = _JUDGE,
) -> dict[str, object]:
    return dispatch_judge(
        create_trusted_gold_blind_evaluator(callback),  # type: ignore[arg-type]
        contract.judge_channel,
        backend_id=backend_id,
        dispatch_ledger=ledger,
        answer_binding=issue_gold_blind_judge_dispatch_binding(
            ledger,
            run_id=_RUN,
            case_id=_CASE,
            backend_id=backend_id,
        ),
        key=key,
        run_id=_RUN,
        case_id=_CASE,
    )


def test_receipt_mutation_has_no_public_record_or_rollback_api() -> None:
    module = importlib.import_module(
        "infinity_context_server.memory_comparison_gold_blind_run_proof"
    )
    for name in (
        "record_retrieval_dispatch",
        "record_answer_dispatch",
        "record_judge_dispatch",
        "rollback_provider_dispatch",
    ):
        assert not hasattr(module, name)


def test_judge_wrong_backend_and_duplicate_fail_before_callback() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger = _setup()
    evidence = _retrieve(contract, ledger)
    _dispatch_answer(_answer_request(contract, ledger, evidence), ledger)
    with pytest.raises(GoldBlindContractError, match="binding verification|binding mismatch"):
        _judge(contract, key, ledger, backend_id="wrong")
    assert _CALLS == 0
    _judge(contract, key, ledger)
    with pytest.raises(GoldBlindContractError, match="binding verification|binding mismatch"):
        _judge(contract, key, ledger)
    assert _CALLS == 1


def test_answer_request_requires_retrieval_and_rejects_raw_mutation_and_replay() -> None:
    contract, _, ledger = _setup()
    with pytest.raises(TypeError):
        GoldBlindAnswerRequest(  # type: ignore[call-arg]
            question="What happened?",
            evidence=_evidence(_SECRET),
            reference_date="2 January 2023",
            question_date=None,
        )
    with pytest.raises(GoldBlindContractError, match="Answer retrieval binding failed"):
        _answer_request(contract, ledger)

    evidence = _retrieve(contract, ledger)
    request = _answer_request(contract, ledger, evidence)
    object.__setattr__(request, "evidence", _evidence(_SECRET))
    answerer = _Answerer()
    with pytest.raises(GoldBlindContractError, match="integrity"):
        _dispatch_answer(request, ledger, answerer)
    assert answerer.calls == 0

    request = _answer_request(contract, ledger, evidence)
    with pytest.raises(GoldBlindContractError, match="integrity"):
        _dispatch_answer(request, ledger, answerer, case_id="case-2")
    assert answerer.calls == 0


def test_answer_provider_failure_rolls_back_for_retry() -> None:
    contract, _, ledger = _setup()
    evidence = _retrieve(contract, ledger)
    request = _answer_request(contract, ledger, evidence)
    with pytest.raises(GoldBlindContractError, match="Answer provider failed"):
        _dispatch_answer(request, ledger, _Answerer(fail=True))
    assert _dispatch_answer(request, ledger) == {"answer": "ok"}


def test_sync_dispatch_rejects_awaitables_and_consumes_failed_judge_binding() -> None:
    contract, key, ledger = _setup()
    with pytest.raises(GoldBlindContractError, match="provider failed"):
        _retrieve(contract, ledger, _AsyncRetriever())
    evidence = _retrieve(contract, ledger)
    request = _answer_request(contract, ledger, evidence)
    with pytest.raises(GoldBlindContractError, match="provider failed"):
        _dispatch_answer(request, ledger, _AsyncAnswerer())
    _dispatch_answer(request, ledger)
    with pytest.raises(GoldBlindContractError, match="evaluator failed"):
        _judge(contract, key, ledger, _async_judge)
    with pytest.raises(GoldBlindContractError, match="binding verification"):
        _judge(contract, key, ledger)
    with pytest.raises(GoldBlindContractError, match="incomplete"):
        verify_gold_blind_execution(ledger)


def test_evaluator_callback_swap_is_rejected_before_gold_or_callback() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger = _setup()
    evaluator = create_trusted_gold_blind_evaluator(_correct)
    object.__setattr__(evaluator, "_TrustedGoldBlindEvaluator__callback", _system_exit)
    with pytest.raises(GoldBlindContractError, match="integrity"):
        dispatch_judge(
            evaluator,
            contract.judge_channel,
            backend_id=_JUDGE,
            dispatch_ledger=ledger,
            answer_binding=object(),  # callback integrity fails before capability use
            key=key,
            run_id=_RUN,
            case_id=_CASE,
        )
    assert _CALLS == 0


def test_evaluator_function_code_swap_is_rejected_before_callback() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger = _setup()
    evaluator = create_trusted_gold_blind_evaluator(_correct)
    original_code = _correct.__code__
    _correct.__code__ = _system_exit.__code__
    try:
        with pytest.raises(GoldBlindContractError, match="integrity"):
            dispatch_judge(
                evaluator,
                contract.judge_channel,
                backend_id=_JUDGE,
                dispatch_ledger=ledger,
                answer_binding=object(),  # callback integrity fails before capability use
                key=key,
                run_id=_RUN,
                case_id=_CASE,
            )
    finally:
        _correct.__code__ = original_code
    assert _CALLS == 0


@pytest.mark.parametrize(
    ("callback", "error_type"),
    (
        (_system_exit, SystemExit),
        (_keyboard_interrupt, KeyboardInterrupt),
        (_custom_base_exception, GoldBlindContractError),
    ),
)
def test_judge_base_exceptions_are_fresh_and_secret_free(
    callback: object, error_type: type[BaseException]
) -> None:
    contract, key, ledger = _setup()
    evidence = _retrieve(contract, ledger)
    _dispatch_answer(_answer_request(contract, ledger, evidence), ledger)
    with pytest.raises(error_type) as captured:
        _judge(contract, key, ledger, callback)
    assert captured.value.__cause__ is None
    assert _SECRET not in str(captured.value)
    if error_type in (SystemExit, KeyboardInterrupt):
        assert captured.value.args == ()


def test_verified_execution_seals_ledger_and_report_remains_revalidated() -> None:
    contract, key, ledger = _setup()
    evidence = _retrieve(contract, ledger)
    _dispatch_answer(_answer_request(contract, ledger, evidence), ledger)
    _judge(contract, key, ledger)
    validation = verify_gold_blind_execution(ledger)
    assert verified_gold_blind_execution_report(validation)["run_id"] == _RUN

    retriever = _Retriever()
    with pytest.raises(GoldBlindContractError, match="ledger verification|binding mismatch"):
        _retrieve(contract, ledger, retriever)
    assert retriever.calls == 0
    assert verified_gold_blind_execution_report(validation)["run_id"] == _RUN


def _prepare_bound_judge(
    answerer: object | None = None,
) -> tuple[GoldBlindCaseContract, JudgeRunKey, GoldBlindRunDispatchLedger, object]:
    contract, key, ledger = _setup()
    evidence = _retrieve(contract, ledger)
    _dispatch_answer(
        _answer_request(contract, ledger, evidence),
        ledger,
        answerer or _Answerer(),
    )
    binding = issue_gold_blind_judge_dispatch_binding(
        ledger,
        run_id=_RUN,
        case_id=_CASE,
        backend_id=_JUDGE,
    )
    return contract, key, ledger, binding


def _dispatch_with_binding(
    contract: GoldBlindCaseContract,
    key: JudgeRunKey,
    ledger: GoldBlindRunDispatchLedger,
    binding: object,
    callback: object = _correct,
) -> dict[str, object]:
    return dispatch_judge(
        create_trusted_gold_blind_evaluator(callback),  # type: ignore[arg-type]
        contract.judge_channel,
        backend_id=_JUDGE,
        dispatch_ledger=ledger,
        answer_binding=binding,  # type: ignore[arg-type]
        key=key,
        run_id=_RUN,
        case_id=_CASE,
    )


def test_judge_receives_exact_frozen_answer_and_public_report_stays_sanitized() -> None:
    global _CANDIDATE_CAPTURED
    _CANDIDATE_CAPTURED = False
    contract, key, ledger, binding = _prepare_bound_judge(_RichAnswerer())

    _dispatch_with_binding(contract, key, ledger, binding, _capture_candidate)
    assert _CANDIDATE_CAPTURED is True
    report = verified_gold_blind_execution_report(verify_gold_blind_execution(ledger))
    serialized = json.dumps(report, sort_keys=True)
    assert _CANDIDATE_SENTINEL not in serialized
    assert "citations" not in serialized


def test_same_gold_and_evaluator_score_distinct_bound_candidates_differently() -> None:
    correct_contract, correct_key, correct_ledger, correct_binding = _prepare_bound_judge(
        _RichAnswerer()
    )
    wrong_contract, wrong_key, wrong_ledger, wrong_binding = _prepare_bound_judge(_WrongAnswerer())
    evaluator = create_trusted_gold_blind_evaluator(_semantic_candidate_judge)

    correct = dispatch_judge(
        evaluator,
        correct_contract.judge_channel,
        backend_id=_JUDGE,
        dispatch_ledger=correct_ledger,
        answer_binding=correct_binding,  # type: ignore[arg-type]
        key=correct_key,
        run_id=_RUN,
        case_id=_CASE,
    )
    wrong = dispatch_judge(
        evaluator,
        wrong_contract.judge_channel,
        backend_id=_JUDGE,
        dispatch_ledger=wrong_ledger,
        answer_binding=wrong_binding,  # type: ignore[arg-type]
        key=wrong_key,
        run_id=_RUN,
        case_id=_CASE,
    )
    correct_report = verified_gold_blind_execution_report(
        verify_gold_blind_execution(correct_ledger)
    )
    wrong_report = verified_gold_blind_execution_report(verify_gold_blind_execution(wrong_ledger))

    assert correct["verdict"] == "correct"
    assert correct["score"] == 1.0
    assert wrong["verdict"] == "incorrect"
    assert wrong["score"] == 0.0
    assert correct_report["answer_identity"] != wrong_report["answer_identity"]


def test_judge_binding_is_single_issue_and_single_dispatch() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger, binding = _prepare_bound_judge()
    with pytest.raises(GoldBlindContractError, match="binding verification"):
        issue_gold_blind_judge_dispatch_binding(
            ledger,
            run_id=_RUN,
            case_id=_CASE,
            backend_id=_JUDGE,
        )
    _dispatch_with_binding(contract, key, ledger, binding)
    with pytest.raises(GoldBlindContractError, match="ledger verification"):
        _dispatch_with_binding(contract, key, ledger, binding)
    assert _CALLS == 1


def test_private_gold_channel_is_consumed_once_across_fresh_ledgers() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger, binding = _prepare_bound_judge()
    _dispatch_with_binding(contract, key, ledger, binding)

    second_ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(_expected(),),
    )
    second_contract = build_gold_blind_contract(
        _case(),
        run_id=_RUN,
        judge_key=key,
        dispatch_ledger=second_ledger,
    )
    evidence = _retrieve(second_contract, second_ledger)
    _dispatch_answer(
        _answer_request(second_contract, second_ledger, evidence),
        second_ledger,
    )
    second_binding = issue_gold_blind_judge_dispatch_binding(
        second_ledger,
        run_id=_RUN,
        case_id=_CASE,
        backend_id=_JUDGE,
    )
    with pytest.raises(GoldBlindContractError, match="evaluator failed"):
        dispatch_judge(
            create_trusted_gold_blind_evaluator(_correct),
            contract.judge_channel,
            backend_id=_JUDGE,
            dispatch_ledger=second_ledger,
            answer_binding=second_binding,
            key=key,
            run_id=_RUN,
            case_id=_CASE,
        )
    assert _CALLS == 1


def test_judge_binding_mismatch_and_integrity_tamper_fail_before_callback() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger, binding = _prepare_bound_judge()
    other_contract, other_key, other_ledger, _ = _prepare_bound_judge()
    with pytest.raises(GoldBlindContractError, match="ledger verification"):
        _dispatch_with_binding(other_contract, other_key, other_ledger, binding)
    assert _CALLS == 0

    object.__setattr__(
        binding,
        "_GoldBlindJudgeDispatchBinding__commitment",
        "0" * 64,
    )
    with pytest.raises(GoldBlindContractError, match="ledger verification"):
        _dispatch_with_binding(contract, key, ledger, binding)
    assert _CALLS == 0


def test_judge_binding_concurrent_dispatch_invokes_private_judge_once() -> None:
    global _CALLS
    _CALLS = 0
    contract, key, ledger, binding = _prepare_bound_judge()
    evaluator = create_trusted_gold_blind_evaluator(_correct)
    barrier = threading.Barrier(2)

    def dispatch() -> str:
        barrier.wait()
        try:
            dispatch_judge(
                evaluator,
                contract.judge_channel,
                backend_id=_JUDGE,
                dispatch_ledger=ledger,
                answer_binding=binding,  # type: ignore[arg-type]
                key=key,
                run_id=_RUN,
                case_id=_CASE,
            )
        except GoldBlindContractError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(dispatch), pool.submit(dispatch))
        outcomes = sorted(future.result() for future in futures)
    assert outcomes == ["accepted", "rejected"]
    assert _CALLS == 1
