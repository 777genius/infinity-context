from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_server.memory_comparison_gold_blind import (
    GoldBlindCaseContract,
    build_gold_blind_contract,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    GoldBlindContractError,
    GoldBlindEvidence,
    GoldBlindExpectedDispatchCase,
    GoldBlindRetrievalRequest,
    JudgeRunKey,
    create_gold_blind_run_dispatch_ledger,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    verify_gold_blind_execution,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_RUN = "hardening-run"
_COMPARISON_BINDING = "9" * 64
_CASE = "hardening-case"
_RETRIEVAL = "retrieval-v1"
_ANSWER = "answer-v1"
_JUDGE = "judge-v1"
_SECRET = "SECRET-DO-NOT-LEAK-779"


def _setup() -> tuple[GoldBlindCaseContract, object]:
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
    key = JudgeRunKey.issue(run_id=_RUN, case_id=_CASE)
    case = PublicBenchmarkCase(
        benchmark="locomo",
        case_id=_CASE,
        question="What happened?",
        expected_terms=(_SECRET,),
        metadata={
            "_evaluator_ground_truth": {"answer": _SECRET},
            "reference_date": "2 January 2023",
            "question_type": "single-hop",
        },
    )
    return (
        build_gold_blind_contract(
            case,
            run_id=_RUN,
            judge_key=key,
            dispatch_ledger=ledger,
        ),
        ledger,
    )


def _evidence() -> tuple[GoldBlindEvidence, ...]:
    return (
        GoldBlindEvidence(
            item_id="item-1",
            text="public evidence",
            rank=1,
            created_at="2023-01-02T10:00:00Z",
        ),
    )


class _Retriever:
    def __init__(self, result: object = None) -> None:
        self.result = _evidence() if result is None else result
        self.calls = 0

    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> object:
        del request, run_id, top_k
        self.calls += 1
        return self.result


class _Answerer:
    def __init__(self, result: object = None) -> None:
        self.result = {"answer": "ok"} if result is None else result
        self.calls = 0

    def answer(self, request: Mapping[str, object]) -> object:
        del request
        self.calls += 1
        return self.result


def _retrieve(contract: GoldBlindCaseContract, ledger: object, port: object) -> object:
    return dispatch_retrieval(
        port,  # type: ignore[arg-type]
        contract.retrieval_request,
        backend_id=_RETRIEVAL,
        dispatch_ledger=ledger,  # type: ignore[arg-type]
        run_id=_RUN,
        top_k=5,
    )


def _answer(contract: GoldBlindCaseContract, ledger: object, port: object) -> object:
    evidence = _retrieve(contract, ledger, _Retriever())
    request = contract.answer_request(evidence)  # type: ignore[arg-type]
    return dispatch_answer(
        port,  # type: ignore[arg-type]
        request,
        backend_id=_ANSWER,
        case_id=_CASE,
        dispatch_ledger=ledger,  # type: ignore[arg-type]
        run_id=_RUN,
    )


def test_raw_retrieval_constructor_and_public_answer_factories_are_closed() -> None:
    with pytest.raises(GoldBlindContractError, match="must be issued"):
        GoldBlindRetrievalRequest(
            benchmark="locomo",
            case_id=_CASE,
            question=_SECRET,
            public_metadata={},
        )
    with pytest.raises(TypeError):
        GoldBlindCaseContract()  # type: ignore[call-arg]

    answer_module = importlib.import_module(
        "infinity_context_server.memory_comparison_gold_blind_answer_contract"
    )
    proof_module = importlib.import_module(
        "infinity_context_server.memory_comparison_gold_blind_run_proof"
    )
    assert not hasattr(answer_module, "issue_gold_blind_answer_request")
    assert not hasattr(proof_module, "issue_gold_blind_answer_dispatch_binding")
    assert not hasattr(proof_module, "_issue_dispatch_mutation_capability")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("question", _SECRET),
        ("case_id", "rebound-case"),
    ),
)
def test_retrieval_request_mutation_rejects_before_provider(
    field: str,
    value: str,
) -> None:
    contract, ledger = _setup()
    request = contract.retrieval_request
    object.__setattr__(request, field, value)
    retriever = _Retriever()

    with pytest.raises(GoldBlindContractError, match="integrity"):
        dispatch_retrieval(
            retriever,
            request,
            backend_id=_RETRIEVAL,
            dispatch_ledger=ledger,  # type: ignore[arg-type]
            run_id=_RUN,
            top_k=5,
        )
    assert retriever.calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("_GoldBlindCaseContract__question", _SECRET),
        ("_GoldBlindCaseContract__reference_date", "31 December 2099"),
    ),
)
def test_case_contract_mutation_invalidates_even_held_retrieval_request(
    field: str,
    value: str,
) -> None:
    contract, ledger = _setup()
    request = contract.retrieval_request
    object.__setattr__(contract, field, value)
    retriever = _Retriever()

    with pytest.raises(GoldBlindContractError, match="integrity"):
        dispatch_retrieval(
            retriever,
            request,
            backend_id=_RETRIEVAL,
            dispatch_ledger=ledger,  # type: ignore[arg-type]
            run_id=_RUN,
            top_k=5,
        )
    assert retriever.calls == 0


class _AsyncIterable:
    touched = False

    def __aiter__(self) -> object:
        self.touched = True
        return self


class _Iterable:
    touched = False

    def __iter__(self) -> object:
        self.touched = True
        return iter(())


async def _coroutine_result() -> object:
    return {"answer": "later"}


async def _async_generator_result() -> object:
    yield {"answer": "later"}


def _generator_result() -> object:
    yield {"answer": "later"}


@pytest.mark.parametrize(
    "factory",
    (
        _coroutine_result,
        _async_generator_result,
        _generator_result,
        _AsyncIterable,
        _Iterable,
        lambda: iter(()),
    ),
)
def test_answer_rejects_every_deferred_or_iterable_result_and_rolls_back(
    factory: object,
) -> None:
    contract, ledger = _setup()
    result = factory()  # type: ignore[operator]
    answerer = _Answerer(result)

    with pytest.raises(GoldBlindContractError, match="Answer provider failed"):
        _answer(contract, ledger, answerer)
    assert answerer.calls == 1
    if isinstance(result, (_AsyncIterable, _Iterable)):
        assert result.touched is False

    retry = _Answerer()
    request = contract.answer_request(_evidence())
    assert dispatch_answer(
        retry,
        request,
        backend_id=_ANSWER,
        case_id=_CASE,
        dispatch_ledger=ledger,  # type: ignore[arg-type]
        run_id=_RUN,
    ) == {"answer": "ok"}


@pytest.mark.parametrize(
    "factory",
    (
        _coroutine_result,
        _async_generator_result,
        _generator_result,
        _AsyncIterable,
        _Iterable,
        lambda: iter(()),
    ),
)
def test_retrieval_rejects_every_deferred_or_iterable_result_and_rolls_back(
    factory: object,
) -> None:
    contract, ledger = _setup()
    result = factory()  # type: ignore[operator]
    retriever = _Retriever(result)

    with pytest.raises(GoldBlindContractError, match="Retrieval provider failed"):
        _retrieve(contract, ledger, retriever)
    assert retriever.calls == 1
    if isinstance(result, (_AsyncIterable, _Iterable)):
        assert result.touched is False
    assert _retrieve(contract, ledger, _Retriever()) == _evidence()


class _HostileResultMeta(type):
    def __getattribute__(cls, name: str) -> object:
        if name == "__mro__":
            raise RuntimeError(_SECRET)
        return super().__getattribute__(name)


class _HostileResult(metaclass=_HostileResultMeta):
    pass


def test_hostile_result_metaclass_is_not_introspected_or_leaked_and_rolls_back() -> None:
    contract, ledger = _setup()
    with pytest.raises(GoldBlindContractError) as caught:
        _answer(contract, ledger, _Answerer(_HostileResult()))
    assert str(caught.value) == "Answer provider failed"
    assert _SECRET not in str(caught.value)

    request = contract.answer_request(_evidence())
    assert dispatch_answer(
        _Answerer(),
        request,
        backend_id=_ANSWER,
        case_id=_CASE,
        dispatch_ledger=ledger,  # type: ignore[arg-type]
        run_id=_RUN,
    ) == {"answer": "ok"}


class _RaiseRetriever:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def search(self, request: object, *, run_id: str, top_k: int) -> object:
        del request, run_id, top_k
        raise self.error


class _RaiseAnswerer:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def answer(self, request: object) -> object:
        del request
        raise self.error


@pytest.mark.parametrize(
    ("factory", "expected"),
    (
        (lambda: SystemExit(_SECRET), SystemExit),
        (lambda: KeyboardInterrupt(_SECRET), KeyboardInterrupt),
        (lambda: asyncio.CancelledError(_SECRET), asyncio.CancelledError),
        (lambda: RuntimeError(_SECRET), GoldBlindContractError),
    ),
)
@pytest.mark.parametrize("stage", ("retrieval", "answer"))
def test_provider_base_exceptions_are_fresh_secret_free_and_rollback(
    factory: object,
    expected: type[BaseException],
    stage: str,
) -> None:
    contract, ledger = _setup()
    original = factory()  # type: ignore[operator]
    with pytest.raises(expected) as caught:
        if stage == "retrieval":
            _retrieve(contract, ledger, _RaiseRetriever(original))
        else:
            _answer(contract, ledger, _RaiseAnswerer(original))
    assert caught.value is not original
    assert _SECRET not in str(caught.value)

    if stage == "retrieval":
        assert _retrieve(contract, ledger, _Retriever()) == _evidence()
    else:
        request = contract.answer_request(_evidence())
        assert dispatch_answer(
            _Answerer(),
            request,
            backend_id=_ANSWER,
            case_id=_CASE,
            dispatch_ledger=ledger,  # type: ignore[arg-type]
            run_id=_RUN,
        ) == {"answer": "ok"}


def test_reentrant_retrieval_is_rejected_before_nested_provider() -> None:
    contract, ledger = _setup()
    nested = _Retriever()

    class Reentrant:
        calls = 0

        def search(self, request: object, *, run_id: str, top_k: int) -> object:
            del request, run_id, top_k
            self.calls += 1
            with pytest.raises(GoldBlindContractError):
                _retrieve(contract, ledger, nested)
            return _evidence()

    outer = Reentrant()
    assert _retrieve(contract, ledger, outer) == _evidence()
    assert outer.calls == 1
    assert nested.calls == 0


def test_concurrent_retrieval_allows_exactly_one_provider_call() -> None:
    contract, ledger = _setup()
    entered = threading.Event()
    release = threading.Event()

    class Blocking:
        calls = 0

        def search(self, request: object, *, run_id: str, top_k: int) -> object:
            del request, run_id, top_k
            self.calls += 1
            entered.set()
            assert release.wait(timeout=5)
            return _evidence()

    port = Blocking()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_retrieve, contract, ledger, port)
        assert entered.wait(timeout=5)
        second = pool.submit(_retrieve, contract, ledger, port)
        with pytest.raises(GoldBlindContractError):
            second.result(timeout=5)
        release.set()
        assert first.result(timeout=5) == _evidence()
    assert port.calls == 1


def test_stage_dispatch_closures_expose_no_callable_mutation_primitive() -> None:
    for dispatch in (dispatch_retrieval, dispatch_answer, dispatch_judge):
        cells = dispatch.__closure__ or ()
        assert cells
        assert all(not callable(cell.cell_contents) for cell in cells)


def test_receipt_forgery_primitives_are_absent_before_contract_import_and_reload() -> None:
    code = """
import importlib
p = importlib.import_module(
    "infinity_context_server.memory_comparison_gold_blind_run_proof"
)
again = importlib.import_module(
    "infinity_context_server.memory_comparison_gold_blind_run_proof"
)
blocked = (
    "_claim_dispatch_api",
    "_dispatch_capability_for_registered_ledger",
    "_execute_dispatch",
    "_reserve_dispatch",
    "_complete_dispatch",
    "_rollback_dispatch",
    "_state",
    "_STATES",
    "_require_dispatch_authority",
)
assert p is again
assert p.dispatch_retrieval is again.dispatch_retrieval
assert all(name not in vars(p) for name in blocked)
expected = p.GoldBlindExpectedDispatchCase(
    case_id="reload-case",
    retrieval_backend_id="retrieval",
    answer_backend_id="answer",
    judge_backend_id="judge",
)
old_ledger = p.create_gold_blind_run_dispatch_ledger(
    run_id="reload-run",
    comparison_binding_commitment_sha256="9" * 64,
    expected_cases=(expected,),
)
p = importlib.reload(p)
assert all(name not in vars(p) for name in blocked)
try:
    p.verify_gold_blind_execution(old_ledger)
except p.GoldBlindRunDispatchProofError:
    pass
else:
    raise AssertionError("reloaded proof module accepted an old ledger")
assert callable(p.create_gold_blind_run_dispatch_ledger)
assert callable(p.dispatch_retrieval)
"""
    python_paths: list[str] = []
    for entry in sys.path:
        if type(entry) is not str or not entry or "\x00" in entry:
            continue
        absolute = os.path.abspath(entry)
        if os.path.isdir(absolute) and absolute not in python_paths:
            python_paths.append(absolute)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr


def test_forgery_replay_and_cross_ledger_paths_invoke_no_callback() -> None:
    proof = importlib.import_module(
        "infinity_context_server.memory_comparison_gold_blind_run_proof"
    )
    blocked = (
        "_claim_dispatch_api",
        "_dispatch_capability_for_registered_ledger",
        "_execute_dispatch",
        "_reserve_dispatch",
        "_complete_dispatch",
        "_rollback_dispatch",
        "_state",
        "_STATES",
        "_require_dispatch_authority",
    )
    assert all(name not in vars(proof) for name in blocked)

    contract, ledger = _setup()
    _, other_ledger = _setup()
    cross_ledger = _Retriever()
    with pytest.raises(GoldBlindContractError):
        dispatch_retrieval(
            cross_ledger,
            contract.retrieval_request,
            backend_id=_RETRIEVAL,
            dispatch_ledger=other_ledger,  # type: ignore[arg-type]
            run_id=_RUN,
            top_k=5,
        )
    assert cross_ledger.calls == 0

    first = _Retriever()
    assert _retrieve(contract, ledger, first) == _evidence()
    replay = _Retriever()
    with pytest.raises(GoldBlindContractError):
        _retrieve(contract, ledger, replay)
    assert first.calls == 1
    assert replay.calls == 0

    with pytest.raises(GoldBlindContractError):
        verify_gold_blind_execution(ledger)  # type: ignore[arg-type]
    with pytest.raises(GoldBlindContractError):
        verify_gold_blind_execution(other_ledger)  # type: ignore[arg-type]
