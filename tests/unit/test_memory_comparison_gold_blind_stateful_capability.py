from __future__ import annotations

import copy
import json
import pickle
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar

import pytest
from infinity_context_server.memory_comparison_gold_blind import (
    GoldBlindCaseContract,
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindJudgeResult,
    GoldBlindRunDispatchLedger,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    issue_gold_blind_judge_dispatch_binding,
)
from infinity_context_server.memory_comparison_gold_blind_judge_capability import (
    TrustedGoldBlindJudgeCapability,
    _issue_trusted_gold_blind_judge_capability,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN = "stateful-capability-run"
_CASE = "stateful-capability-case"
_RETRIEVAL = "retrieval-v1"
_ANSWER = "answer-v1"
_JUDGE = "judge-v1"
_SECRET = "STATEFUL-PRIVATE-GOLD-741"
_COMPARISON_BINDING = "8" * 64
_GLOBAL_CAPTURE: list[object] = []


class _JudgeState:
    def __init__(self, *, failure: BaseException | None = None, blocking: bool = False) -> None:
        self.calls = 0
        self.failure = failure
        self.blocking = blocking
        self.started = threading.Event()
        self.release = threading.Event()
        self.secret = _SECRET
        self.gold_matched = False
        self.candidate_matched = False
        self.result = GoldBlindJudgeResult(verdict="correct", score=1.0)


def _stateful_invoker(
    state: _JudgeState,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    state.calls += 1
    state.started.set()
    state.gold_matched = (
        ground_truth["answer"] == state.secret  # type: ignore[index]
        and expected_terms[0] == state.secret
        and forbidden_terms == ()
    )
    state.candidate_matched = candidate_answer["answer"] == "candidate"  # type: ignore[index]
    if state.blocking:
        state.release.wait()
    if state.failure is not None:
        raise state.failure
    return state.result


def _alternate_invoker(
    state: _JudgeState,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del candidate_answer, ground_truth, expected_terms, forbidden_terms
    state.calls += 100
    return state.result


def _global_invoker(
    state: _JudgeState,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> GoldBlindJudgeResult:
    del candidate_answer, expected_terms, forbidden_terms
    _GLOBAL_CAPTURE.append(ground_truth)
    return state.result


def _closure_invoker() -> object:
    retained: list[object] = []

    def invoker(
        state: _JudgeState,
        candidate_answer: object,
        ground_truth: object,
        expected_terms: tuple[str, ...],
        forbidden_terms: tuple[str, ...],
    ) -> GoldBlindJudgeResult:
        del candidate_answer, expected_terms, forbidden_terms
        retained.append(ground_truth)
        return state.result

    return invoker


def _other_dispatcher() -> object:
    marker = object()

    def dispatch_judge() -> object:
        return marker

    return dispatch_judge


class _Retriever:
    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]:
        del request, run_id, top_k
        return (
            GoldBlindEvidence(
                item_id="item-1",
                text="retrieved",
                rank=1,
                created_at="2023-01-02T10:00:00Z",
            ),
        )


class _Answerer:
    def answer(self, request: Mapping[str, object]) -> object:
        del request
        return {"answer": "candidate"}


def _setup_ready() -> tuple[
    GoldBlindCaseContract,
    JudgeRunKey,
    GoldBlindRunDispatchLedger,
    object,
]:
    key = JudgeRunKey.issue(run_id=_RUN, case_id=_CASE)
    ledger = create_gold_blind_run_dispatch_ledger(
        run_id=_RUN,
        comparison_binding_commitment_sha256=_COMPARISON_BINDING,
        expected_cases=(
            GoldBlindExpectedDispatchCase(
                case_id=_CASE,
                retrieval_backend_id=_RETRIEVAL,
                answer_backend_id=_ANSWER,
                judge_backend_id=_JUDGE,
            ),
        ),
    )
    contract = build_gold_blind_contract(
        PublicBenchmarkCase(
            benchmark="locomo",
            case_id=_CASE,
            question="What happened?",
            expected_terms=(_SECRET,),
            metadata={
                "_evaluator_ground_truth": {"answer": _SECRET},
                "reference_date": "2 January 2023",
            },
        ),
        run_id=_RUN,
        judge_key=key,
        dispatch_ledger=ledger,
    )
    evidence = dispatch_retrieval(
        _Retriever(),
        contract.retrieval_request,
        backend_id=_RETRIEVAL,
        dispatch_ledger=ledger,
        run_id=_RUN,
        top_k=5,
    )
    request = contract.answer_request(evidence)
    dispatch_answer(
        _Answerer(),
        request,
        backend_id=_ANSWER,
        dispatch_ledger=ledger,
        run_id=_RUN,
        case_id=_CASE,
    )
    binding = issue_gold_blind_judge_dispatch_binding(
        ledger,
        run_id=_RUN,
        case_id=_CASE,
        backend_id=_JUDGE,
    )
    return contract, key, ledger, binding


def _capability(
    state: object,
    *,
    dispatcher: object = dispatch_judge,
    invoker: object = _stateful_invoker,
    run_id: str = _RUN,
    case_id: str = _CASE,
    backend_id: str = _JUDGE,
) -> TrustedGoldBlindJudgeCapability:
    return _issue_trusted_gold_blind_judge_capability(
        dispatcher=dispatcher,
        invoker=invoker,
        state=state,
        run_id=run_id,
        case_id=case_id,
        backend_id=backend_id,
    )


def _dispatch(
    capability: object,
    contract: GoldBlindCaseContract,
    key: JudgeRunKey,
    ledger: GoldBlindRunDispatchLedger,
    binding: object,
) -> dict[str, object]:
    return dispatch_judge(
        capability,
        contract.judge_channel,
        backend_id=_JUDGE,
        dispatch_ledger=ledger,
        answer_binding=binding,  # type: ignore[arg-type]
        key=key,
        run_id=_RUN,
        case_id=_CASE,
    )


def test_stateful_capability_dispatches_once_without_exposing_gold() -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    capability = _capability(state)

    output = _dispatch(capability, contract, key, ledger, binding)

    assert output == {
        "schema_version": "memory-comparison-gold-blind-judge-result.v1",
        "verdict": "correct",
        "score": 1.0,
    }
    assert _SECRET not in json.dumps(output)
    assert state.calls == 1
    assert state.gold_matched is True
    assert state.candidate_matched is True
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)


def test_capability_is_final_opaque_noncopyable_and_nonserializable() -> None:
    state = _JudgeState()
    capability = _capability(state)

    assert repr(capability) == "TrustedGoldBlindJudgeCapability(<opaque-one-shot>)"
    assert _SECRET not in repr(capability)
    with pytest.raises(TypeError):
        copy.copy(capability)
    with pytest.raises(TypeError):
        copy.deepcopy(capability)
    with pytest.raises(TypeError):
        pickle.dumps(capability)
    with pytest.raises(TypeError):
        json.dumps(capability)

    with pytest.raises(TypeError):

        class ForgedCapability(TrustedGoldBlindJudgeCapability):
            pass

    with pytest.raises(GoldBlindContractError, match="privately issued"):
        TrustedGoldBlindJudgeCapability(
            fingerprint="0" * 64,
            nonce="0" * 64,
            _token=object(),
        )


@pytest.mark.parametrize(
    ("invoker", "state", "message"),
    (
        (_closure_invoker(), _JudgeState(), "closure-free"),
        (_global_invoker, _JudgeState(), "global state"),
        (_stateful_invoker, ContextVar("judge-state"), "context-local"),
    ),
)
def test_private_issuer_rejects_closure_global_and_contextvar_hacks(
    invoker: object,
    state: object,
    message: str,
) -> None:
    with pytest.raises(GoldBlindContractError, match=message):
        _capability(state, invoker=invoker)


@pytest.mark.parametrize(
    ("binding_overrides",),
    (
        ({"dispatcher": _other_dispatcher()},),
        ({"run_id": "wrong-run"},),
        ({"case_id": "wrong-case"},),
        ({"backend_id": "wrong-lane"},),
    ),
)
def test_wrong_dispatcher_run_case_or_lane_burns_the_dispatch(
    binding_overrides: dict[str, object],
) -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    capability = _capability(state, **binding_overrides)  # type: ignore[arg-type]

    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)
    assert state.calls == 0
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(_capability(_JudgeState()), contract, key, ledger, binding)


def test_forged_and_mutated_capabilities_are_rejected_before_invocation() -> None:
    contract, key, ledger, binding = _setup_ready()
    forged = object.__new__(TrustedGoldBlindJudgeCapability)
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(forged, contract, key, ledger, binding)

    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    capability = _capability(state)
    object.__setattr__(
        capability,
        "_TrustedGoldBlindJudgeCapability__fingerprint",
        "0" * 64,
    )
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)
    assert state.calls == 0


def test_invoker_code_mutation_is_tamper_evident_and_terminal() -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    capability = _capability(state)
    original_code = _stateful_invoker.__code__
    _stateful_invoker.__code__ = _alternate_invoker.__code__
    try:
        with pytest.raises(
            GoldBlindContractError, match="verification failed|binding verification"
        ):
            _dispatch(capability, contract, key, ledger, binding)
    finally:
        _stateful_invoker.__code__ = original_code
    assert state.calls == 0
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(_capability(_JudgeState()), contract, key, ledger, binding)


def test_provider_failure_leaves_capability_channel_and_binding_terminal() -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState(failure=RuntimeError(_SECRET))
    capability = _capability(state)

    with pytest.raises(GoldBlindContractError, match="evaluator failed") as failure:
        _dispatch(capability, contract, key, ledger, binding)
    assert failure.value.__cause__ is None
    assert _SECRET not in str(failure.value)
    assert state.calls == 1
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)


def test_nonexact_provider_result_is_rejected_and_terminal() -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    state.result = {"verdict": "correct", "score": 1.0}  # type: ignore[assignment]
    capability = _capability(state)

    with pytest.raises(GoldBlindContractError, match="evaluator failed"):
        _dispatch(capability, contract, key, ledger, binding)
    assert state.calls == 1
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)


def test_parsing_failure_after_burn_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState()
    capability = _capability(state)

    def fail_parse(value: object) -> object:
        del value
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(
        "infinity_context_server.memory_comparison_gold_blind_validation.parse_canonical_gold_json",
        fail_parse,
    )
    with pytest.raises(GoldBlindContractError, match="evaluator failed") as failure:
        _dispatch(capability, contract, key, ledger, binding)
    assert _SECRET not in str(failure.value)
    assert state.calls == 0
    with pytest.raises(GoldBlindContractError, match="verification failed|binding verification"):
        _dispatch(capability, contract, key, ledger, binding)


def test_concurrent_use_invokes_stateful_judge_exactly_once() -> None:
    contract, key, ledger, binding = _setup_ready()
    state = _JudgeState(blocking=True)
    capability = _capability(state)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_dispatch, capability, contract, key, ledger, binding)
        assert state.started.wait(timeout=2)
        second = executor.submit(_dispatch, capability, contract, key, ledger, binding)
        try:
            with pytest.raises(
                GoldBlindContractError, match="verification failed|binding verification"
            ):
                second.result(timeout=2)
        finally:
            state.release.set()
        assert first.result(timeout=2)["verdict"] == "correct"

    assert state.calls == 1
