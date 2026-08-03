"""Opaque one-shot capability for trusted stateful production gold-blind judges."""

from __future__ import annotations

import dis
import hashlib
import hmac
import inspect
import secrets
import threading
import weakref
from collections.abc import Callable
from contextvars import Context, ContextVar
from dataclasses import dataclass
from types import FunctionType
from typing import final

from infinity_context_server.memory_comparison_gold_blind_contract import (
    _CHANNEL_INTEGRITY,
    _CONSUMED_CHANNELS,
    _INTEGRITY_LOCK,
    ExactGoldJudgeChannel,
    GoldBlindContractError,
    GoldBlindJudgeResult,
    JudgeRunKey,
    _ChannelIntegritySnapshot,
    _validate_channel_binding,
    canonical_gold_json,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    validate_nonempty_exact_string as _validate_nonempty_exact_string,
)

__all__ = ("TrustedGoldBlindJudgeCapability",)

_CAPABILITY_SCHEMA_VERSION = "memory-comparison-trusted-judge-capability.v1"
_TOKEN = object()
_LOCK = threading.RLock()
_FORBIDDEN_GLOBAL_OPS = frozenset(
    {"DELETE_GLOBAL", "DELETE_NAME", "LOAD_GLOBAL", "LOAD_NAME", "STORE_GLOBAL", "STORE_NAME"}
)


@final
class TrustedGoldBlindJudgeCapability:
    """One exact process-local authority with no public materialization surface."""

    __slots__ = ("__fingerprint", "__nonce", "__weakref__")

    def __init__(self, *, fingerprint: str, nonce: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Trusted judge capabilities must be privately issued")
        self.__fingerprint = fingerprint
        self.__nonce = nonce

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("TrustedGoldBlindJudgeCapability is final")

    def __repr__(self) -> str:
        return "TrustedGoldBlindJudgeCapability(<opaque-one-shot>)"

    def __copy__(self) -> object:
        raise TypeError("TrustedGoldBlindJudgeCapability is noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("TrustedGoldBlindJudgeCapability is noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("TrustedGoldBlindJudgeCapability is nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("TrustedGoldBlindJudgeCapability is nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("TrustedGoldBlindJudgeCapability is nonserializable")


@dataclass(frozen=True, slots=True, repr=False)
class _CapabilitySnapshot:
    dispatcher: Callable[..., object]
    invoker: Callable[..., GoldBlindJudgeResult]
    state: object
    run_id: str
    case_id: str
    backend_id: str
    dispatcher_code: object
    dispatcher_globals: dict[str, object]
    dispatcher_module: str | None
    dispatcher_name: str
    dispatcher_qualname: str
    dispatcher_closure: tuple[tuple[int, int], ...]
    invoker_code: object
    invoker_globals: dict[str, object]
    invoker_module: str | None
    invoker_name: str
    invoker_qualname: str
    secret: bytes
    nonce: str
    fingerprint: str


_CAPABILITIES: weakref.WeakKeyDictionary[TrustedGoldBlindJudgeCapability, _CapabilitySnapshot] = (
    weakref.WeakKeyDictionary()
)
_CONSUMED: weakref.WeakSet[TrustedGoldBlindJudgeCapability] = weakref.WeakSet()


def _issue_trusted_gold_blind_judge_capability(
    *,
    dispatcher: object,
    invoker: object,
    state: object,
    run_id: str,
    case_id: str,
    backend_id: str,
) -> TrustedGoldBlindJudgeCapability:
    """Private trusted composition seam; no public factory is exported."""

    _validate_trusted_dispatcher(dispatcher)
    _validate_stateful_invoker(invoker)
    if type(state) in (Context, ContextVar):
        raise GoldBlindContractError("Trusted judge state must not be context-local")
    _validate_nonempty_exact_string(run_id, field_name="Trusted judge run_id")
    _validate_nonempty_exact_string(case_id, field_name="Trusted judge case_id")
    _validate_nonempty_exact_string(backend_id, field_name="Trusted judge backend_id")

    dispatcher_closure = _dispatcher_closure_identity(dispatcher)
    secret = secrets.token_bytes(32)
    nonce = secrets.token_hex(32)
    fingerprint = _capability_fingerprint(
        secret=secret,
        nonce=nonce,
        dispatcher=dispatcher,
        dispatcher_closure=dispatcher_closure,
        invoker=invoker,
        state=state,
        run_id=run_id,
        case_id=case_id,
        backend_id=backend_id,
    )
    capability = TrustedGoldBlindJudgeCapability(
        fingerprint=fingerprint,
        nonce=nonce,
        _token=_TOKEN,
    )
    snapshot = _CapabilitySnapshot(
        dispatcher=dispatcher,
        invoker=invoker,
        state=state,
        run_id=run_id,
        case_id=case_id,
        backend_id=backend_id,
        dispatcher_code=dispatcher.__code__,
        dispatcher_globals=dispatcher.__globals__,
        dispatcher_module=dispatcher.__module__,
        dispatcher_name=dispatcher.__name__,
        dispatcher_qualname=dispatcher.__qualname__,
        dispatcher_closure=dispatcher_closure,
        invoker_code=invoker.__code__,
        invoker_globals=invoker.__globals__,
        invoker_module=invoker.__module__,
        invoker_name=invoker.__name__,
        invoker_qualname=invoker.__qualname__,
        secret=secret,
        nonce=nonce,
        fingerprint=fingerprint,
    )
    with _LOCK:
        _CAPABILITIES[capability] = snapshot
    return capability


def _consume_trusted_gold_blind_judge_capability(
    capability: object,
    *,
    key: JudgeRunKey,
    channel: ExactGoldJudgeChannel,
    run_id: str,
    case_id: str,
    backend_id: str,
) -> tuple[_CapabilitySnapshot, _ChannelIntegritySnapshot]:
    """Burn the exact capability and channel together before parsing any private data."""

    from infinity_context_server import memory_comparison_gold_blind_run_proof

    dispatcher = memory_comparison_gold_blind_run_proof.dispatch_judge
    if type(capability) is not TrustedGoldBlindJudgeCapability:
        raise GoldBlindContractError("Trusted judge capability type must be exact")
    if type(channel) is not ExactGoldJudgeChannel:
        raise GoldBlindContractError("Trusted judge channel type must be exact")
    with _INTEGRITY_LOCK, _LOCK:
        capability_snapshot = _CAPABILITIES.get(capability)
        channel_snapshot = _CHANNEL_INTEGRITY.get(channel)
        if (
            capability_snapshot is None
            or channel_snapshot is None
            or capability in _CONSUMED
            or channel in _CONSUMED_CHANNELS
        ):
            raise GoldBlindContractError("Trusted judge capability is unavailable or consumed")

        # Every registered consume attempt is terminal, including failed revalidation.
        _CONSUMED.add(capability)
        _CONSUMED_CHANNELS.add(channel)
        _validate_capability_snapshot(
            capability,
            capability_snapshot,
            dispatcher=dispatcher,
            run_id=run_id,
            case_id=case_id,
            backend_id=backend_id,
        )
        verified_channel = _validate_channel_binding(
            key=key,
            channel=channel,
            run_id=run_id,
            case_id=case_id,
        )
        if verified_channel is not channel_snapshot:
            raise GoldBlindContractError("Trusted judge channel identity changed")
        return capability_snapshot, channel_snapshot


def _invoke_trusted_gold_blind_judge_capability(
    snapshot: _CapabilitySnapshot,
    *,
    candidate_answer: object,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> object:
    _validate_invoker_snapshot(snapshot)
    result = snapshot.invoker(
        snapshot.state,
        candidate_answer,
        ground_truth,
        expected_terms,
        forbidden_terms,
    )
    _validate_invoker_snapshot(snapshot)
    return result


def _validate_capability_snapshot(
    capability: TrustedGoldBlindJudgeCapability,
    snapshot: _CapabilitySnapshot,
    *,
    dispatcher: object,
    run_id: str,
    case_id: str,
    backend_id: str,
) -> None:
    _validate_dispatcher_snapshot(snapshot)
    _validate_invoker_snapshot(snapshot)
    expected = _capability_fingerprint(
        secret=snapshot.secret,
        nonce=snapshot.nonce,
        dispatcher=snapshot.dispatcher,
        dispatcher_closure=snapshot.dispatcher_closure,
        invoker=snapshot.invoker,
        state=snapshot.state,
        run_id=snapshot.run_id,
        case_id=snapshot.case_id,
        backend_id=snapshot.backend_id,
    )
    try:
        current_fingerprint = capability._TrustedGoldBlindJudgeCapability__fingerprint
        current_nonce = capability._TrustedGoldBlindJudgeCapability__nonce
    except Exception:
        raise GoldBlindContractError("Trusted judge capability integrity failed") from None
    if (
        dispatcher is not snapshot.dispatcher
        or run_id != snapshot.run_id
        or case_id != snapshot.case_id
        or backend_id != snapshot.backend_id
        or type(current_fingerprint) is not str
        or type(current_nonce) is not str
        or not hmac.compare_digest(current_nonce, snapshot.nonce)
        or not hmac.compare_digest(current_fingerprint, snapshot.fingerprint)
        or not hmac.compare_digest(expected, snapshot.fingerprint)
    ):
        raise GoldBlindContractError("Trusted judge capability binding or integrity failed")


def _validate_dispatcher_snapshot(snapshot: _CapabilitySnapshot) -> None:
    dispatcher = snapshot.dispatcher
    _validate_trusted_dispatcher(dispatcher)
    if (
        dispatcher.__code__ is not snapshot.dispatcher_code
        or dispatcher.__globals__ is not snapshot.dispatcher_globals
        or dispatcher.__module__ != snapshot.dispatcher_module
        or dispatcher.__name__ != snapshot.dispatcher_name
        or dispatcher.__qualname__ != snapshot.dispatcher_qualname
        or _dispatcher_closure_identity(dispatcher) != snapshot.dispatcher_closure
    ):
        raise GoldBlindContractError("Trusted judge dispatcher integrity failed")


def _validate_invoker_snapshot(snapshot: _CapabilitySnapshot) -> None:
    invoker = snapshot.invoker
    _validate_stateful_invoker(invoker)
    if (
        invoker.__code__ is not snapshot.invoker_code
        or invoker.__globals__ is not snapshot.invoker_globals
        or invoker.__module__ != snapshot.invoker_module
        or invoker.__name__ != snapshot.invoker_name
        or invoker.__qualname__ != snapshot.invoker_qualname
    ):
        raise GoldBlindContractError("Trusted judge invoker integrity failed")


def _validate_trusted_dispatcher(dispatcher: object) -> None:
    if (
        type(dispatcher) is not FunctionType
        or dispatcher.__name__ != "dispatch_judge"
        or dispatcher.__closure__ is None
    ):
        raise GoldBlindContractError("Trusted judge dispatcher identity is invalid")


def _validate_stateful_invoker(invoker: object) -> None:
    if type(invoker) is not FunctionType:
        raise GoldBlindContractError("Trusted judge invoker must be an exact function")
    code = invoker.__code__
    if (
        invoker.__closure__ is not None
        or invoker.__defaults__ is not None
        or invoker.__kwdefaults__ is not None
        or invoker.__dict__
        or type(invoker.__module__) is not str
        or invoker.__qualname__ != invoker.__name__
        or code.co_argcount != 5
        or code.co_kwonlyargcount != 0
        or code.co_flags & (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS)
    ):
        raise GoldBlindContractError("Trusted judge invoker must be closure-free module code")
    try:
        if any(
            instruction.opname in _FORBIDDEN_GLOBAL_OPS
            for instruction in dis.get_instructions(invoker)
        ):
            raise GoldBlindContractError("Trusted judge invoker must not use global state")
    except GoldBlindContractError:
        raise
    except Exception:
        raise GoldBlindContractError("Trusted judge invoker validation failed") from None


def _dispatcher_closure_identity(dispatcher: Callable[..., object]) -> tuple[tuple[int, int], ...]:
    closure = dispatcher.__closure__
    if closure is None:
        raise GoldBlindContractError("Trusted judge dispatcher closure is missing")
    try:
        return tuple((id(cell), id(cell.cell_contents)) for cell in closure)
    except Exception:
        raise GoldBlindContractError("Trusted judge dispatcher closure is invalid") from None


def _capability_fingerprint(
    *,
    secret: bytes,
    nonce: str,
    dispatcher: object,
    dispatcher_closure: tuple[tuple[int, int], ...],
    invoker: object,
    state: object,
    run_id: str,
    case_id: str,
    backend_id: str,
) -> str:
    payload = canonical_gold_json(
        {
            "schema_version": _CAPABILITY_SCHEMA_VERSION,
            "nonce": nonce,
            "dispatcher_identity": str(id(dispatcher)),
            "dispatcher_closure": [list(item) for item in dispatcher_closure],
            "invoker_identity": str(id(invoker)),
            "state_identity": str(id(state)),
            "run_id": run_id,
            "case_id": case_id,
            "backend_id": backend_id,
        }
    )
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()
