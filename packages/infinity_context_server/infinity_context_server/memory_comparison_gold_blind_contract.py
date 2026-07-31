"""Provider-neutral capabilities for a fail-closed gold-blind benchmark lane."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import secrets
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import AsyncGeneratorType, CoroutineType, FunctionType, GeneratorType
from typing import Protocol, final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    ANSWER_REQUEST_SCHEMA_VERSION,
    GoldBlindAnswerRequest,
    GoldBlindEvidence,
    validate_gold_blind_evidence,
)
from infinity_context_server.memory_comparison_gold_blind_retrieval_contract import (
    RETRIEVAL_REQUEST_SCHEMA_VERSION,
    GoldBlindRetrievalRequest,
)
from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    RUN_DISPATCH_PROOF_SCHEMA_VERSION,
    GoldBlindExpectedDispatchCase,
    GoldBlindRunDispatchLedger,
    VerifiedGoldBlindExecutionValidation,
    create_gold_blind_run_dispatch_ledger,
    dispatch_answer,
    dispatch_judge,
    dispatch_retrieval,
    verified_gold_blind_execution_report,
    verify_gold_blind_execution,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
    canonical_gold_json,
    contains_evaluator_secret,
    validate_provider_text,
    validate_string_terms,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    parse_canonical_gold_json as _parse_canonical_gold_json,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    validate_exact_string_length as _validate_exact_string_length,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    validate_nonempty_exact_string as _validate_nonempty_exact_string,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    validate_provider_text as _validate_provider_text,
)

__all__ = (
    "RUN_DISPATCH_PROOF_SCHEMA_VERSION",
    "GoldBlindContractError",
    "GoldBlindExpectedDispatchCase",
    "GoldBlindRetrievalRequest",
    "GoldBlindRunDispatchLedger",
    "VerifiedGoldBlindExecutionValidation",
    "canonical_gold_json",
    "contains_evaluator_secret",
    "create_gold_blind_run_dispatch_ledger",
    "dispatch_answer",
    "dispatch_judge",
    "dispatch_retrieval",
    "validate_provider_text",
    "validate_string_terms",
    "verified_gold_blind_execution_report",
    "verify_gold_blind_execution",
)

JUDGE_RESULT_SCHEMA_VERSION = "memory-comparison-gold-blind-judge-result.v1"
AUDIT_EVIDENCE_SCHEMA_VERSION = "memory-comparison-gold-blind-audit.v1"
PRIVATE_INTEGRITY_SCHEMA_VERSION = "memory-comparison-gold-blind-private-integrity.v1"
JUDGE_CHANNEL_KIND = "opaque_nonserializable_run_and_case_scoped"

_MAX_PROVIDER_TEXT_CHARS = 16_384
_MAX_EVIDENCE_ITEMS = 1_024
_MAX_EVIDENCE_TEXT_CHARS = 131_072
_MAX_ANSWER_EVIDENCE_CHARS = 1_048_576
_JUDGE_VERDICTS = frozenset({"correct", "incorrect", "partial", "abstain", "error"})
_CAPABILITY_TOKEN = object()


@final
@dataclass(frozen=True, slots=True)
class GoldBlindJudgeResult:
    """Only judge fields allowed to leave the trusted evaluator boundary."""

    verdict: str
    score: float

    def __post_init__(self) -> None:
        _validate_judge_result_state(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindJudgeResult is final")

    def __repr__(self) -> str:
        return f"GoldBlindJudgeResult(verdict={self.verdict!r}, score={self.score!r})"


@dataclass(frozen=True, slots=True)
class _KeyIntegritySnapshot:
    run_id: str
    case_id: str
    secret: bytes


@dataclass(frozen=True, slots=True)
class _ChannelIntegritySnapshot:
    key: JudgeRunKey
    run_id: str
    case_id: str
    ground_truth_json: bytes
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    commitment: str


@dataclass(frozen=True, slots=True)
class _EvaluatorIntegritySnapshot:
    callback: Callable[..., GoldBlindJudgeResult]
    code: object
    globals_mapping: dict[str, object]
    module: str | None
    name: str
    qualname: str


@final
class JudgeRunKey:
    """Opaque identity capability bound to one exact run and case."""

    __slots__ = ("__case_id", "__run_id", "__secret", "__weakref__")

    def __init__(
        self,
        *,
        run_id: str,
        case_id: str,
        secret: bytes,
        _token: object,
    ) -> None:
        if _token is not _CAPABILITY_TOKEN:
            raise GoldBlindContractError("Judge run keys must be issued by the contract")
        _validate_nonempty_exact_string(run_id, field_name="Judge run_id")
        _validate_nonempty_exact_string(case_id, field_name="Judge case_id")
        if type(secret) is not bytes or len(secret) < 32:
            raise GoldBlindContractError("Judge run key secret is invalid")
        self.__run_id = run_id
        self.__case_id = case_id
        self.__secret = secret

    @classmethod
    def issue(cls, *, run_id: str, case_id: str) -> JudgeRunKey:
        """Issue a fresh exact capability for one run and one case."""

        if cls is not JudgeRunKey:
            raise TypeError("JudgeRunKey is final")
        key = JudgeRunKey(
            run_id=run_id,
            case_id=case_id,
            secret=secrets.token_bytes(32),
            _token=_CAPABILITY_TOKEN,
        )
        _register_key_integrity(key)
        return key

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("JudgeRunKey is final")

    def __repr__(self) -> str:
        return "JudgeRunKey(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("JudgeRunKey is a nonserializable capability")


@final
class ExactGoldJudgeChannel:
    """Opaque exact-gold storage with no public materialization method."""

    __slots__ = (
        "__case_id",
        "__expected_terms",
        "__forbidden_terms",
        "__ground_truth_json",
        "__integrity_commitment",
        "__key",
        "__run_id",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        key: JudgeRunKey,
        run_id: str,
        case_id: str,
        ground_truth_json: bytes,
        expected_terms: tuple[str, ...],
        forbidden_terms: tuple[str, ...],
        integrity_commitment: str,
        _token: object,
    ) -> None:
        if _token is not _CAPABILITY_TOKEN:
            raise GoldBlindContractError("Judge channels must be created by the contract")
        if type(key) is not JudgeRunKey:
            raise GoldBlindContractError("Judge channel key must be exact")
        if type(integrity_commitment) is not str or len(integrity_commitment) != 64:
            raise GoldBlindContractError("Judge channel commitment is invalid")
        self.__key = key
        self.__run_id = run_id
        self.__case_id = case_id
        self.__ground_truth_json = ground_truth_json
        self.__expected_terms = expected_terms
        self.__forbidden_terms = forbidden_terms
        self.__integrity_commitment = integrity_commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("ExactGoldJudgeChannel is final")

    def __repr__(self) -> str:
        return "ExactGoldJudgeChannel(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("ExactGoldJudgeChannel is nonserializable")


@final
class TrustedGoldBlindEvaluator:
    """Explicit trust boundary for reviewed stateless evaluator code.

    Python cannot sandbox arbitrary callbacks. Issuance therefore accepts only an exact
    closure-free function with no default state. That function is trusted to use the
    immutable gold view only during the call and never write it to module globals.
    Public callers receive only a reconstructed GoldBlindJudgeResult schema.
    """

    __slots__ = ("__callback", "__weakref__")

    def __init__(
        self,
        *,
        callback: Callable[..., GoldBlindJudgeResult],
        _token: object,
    ) -> None:
        if _token is not _CAPABILITY_TOKEN:
            raise GoldBlindContractError("Trusted evaluators must be explicitly issued")
        _validate_trusted_callback(callback)
        self.__callback = callback

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("TrustedGoldBlindEvaluator is final")

    def __repr__(self) -> str:
        return "TrustedGoldBlindEvaluator(<reviewed stateless function>)"

    def __reduce__(self) -> object:
        raise TypeError("TrustedGoldBlindEvaluator is nonserializable")


class GoldBlindRetrievalPort(Protocol):
    def search(
        self,
        request: Mapping[str, object],
        *,
        run_id: str,
        top_k: int,
    ) -> tuple[GoldBlindEvidence, ...]: ...


class GoldBlindAnswerPort(Protocol):
    def answer(self, request: Mapping[str, object]) -> object: ...


_KEY_INTEGRITY: weakref.WeakKeyDictionary[JudgeRunKey, _KeyIntegritySnapshot] = (
    weakref.WeakKeyDictionary()
)
_CHANNEL_INTEGRITY: weakref.WeakKeyDictionary[ExactGoldJudgeChannel, _ChannelIntegritySnapshot] = (
    weakref.WeakKeyDictionary()
)
_EVALUATOR_INTEGRITY: weakref.WeakKeyDictionary[
    TrustedGoldBlindEvaluator, _EvaluatorIntegritySnapshot
] = weakref.WeakKeyDictionary()
_INTEGRITY_LOCK = threading.RLock()


def create_trusted_gold_blind_evaluator(
    callback: Callable[..., GoldBlindJudgeResult],
) -> TrustedGoldBlindEvaluator:

    _validate_trusted_callback(callback)
    evaluator = TrustedGoldBlindEvaluator(callback=callback, _token=_CAPABILITY_TOKEN)
    with _INTEGRITY_LOCK:
        _EVALUATOR_INTEGRITY[evaluator] = _EvaluatorIntegritySnapshot(
            callback=callback,
            code=callback.__code__,
            globals_mapping=callback.__globals__,
            module=callback.__module__,
            name=callback.__name__,
            qualname=callback.__qualname__,
        )
    return evaluator


def create_exact_gold_judge_channel(
    *,
    key: JudgeRunKey,
    run_id: str,
    case_id: str,
    ground_truth_json: bytes,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> ExactGoldJudgeChannel:
    """Create a channel only from exact canonical replay-safe private inputs."""

    _validate_judge_key_binding(key=key, run_id=run_id, case_id=case_id)
    ground_truth = _parse_canonical_gold_json(ground_truth_json)
    validated_expected = validate_string_terms(expected_terms, field_name="expected_terms")
    validated_forbidden = validate_string_terms(forbidden_terms, field_name="forbidden_terms")
    integrity_payload = _private_integrity_payload(
        run_id=run_id,
        case_id=case_id,
        ground_truth=ground_truth,
        expected_terms=validated_expected,
        forbidden_terms=validated_forbidden,
    )
    commitment = _hmac_for_key(key, integrity_payload)
    channel = ExactGoldJudgeChannel(
        key=key,
        run_id=run_id,
        case_id=case_id,
        ground_truth_json=ground_truth_json,
        expected_terms=validated_expected,
        forbidden_terms=validated_forbidden,
        integrity_commitment=commitment,
        _token=_CAPABILITY_TOKEN,
    )
    snapshot = _ChannelIntegritySnapshot(
        key=key,
        run_id=run_id,
        case_id=case_id,
        ground_truth_json=ground_truth_json,
        expected_terms=validated_expected,
        forbidden_terms=validated_forbidden,
        commitment=commitment,
    )
    with _INTEGRITY_LOCK:
        _CHANNEL_INTEGRITY[channel] = snapshot
    return channel


def gold_blind_audit_commitment(
    *,
    key: JudgeRunKey,
    channel: ExactGoldJudgeChannel,
    run_id: str,
    case_id: str,
) -> str:
    """Verify immutable capability state and return its original commitment."""

    snapshot = _validate_channel_binding(
        key=key,
        channel=channel,
        run_id=run_id,
        case_id=case_id,
    )
    return snapshot.commitment


def _reject_exact_deferred_result(value: object) -> None:
    """Use exact type checks; never inspect hostile async/iterator protocols."""

    value_type = type(value)
    if value_type is CoroutineType or value_type is GeneratorType:
        value.close()  # type: ignore[union-attr]
    if value_type in (CoroutineType, GeneratorType, AsyncGeneratorType):
        raise GoldBlindContractError("Deferred dispatch results are unsupported")


def _validate_retrieval_provider_result(value: object) -> None:
    _reject_exact_deferred_result(value)
    if type(value) is not tuple:
        raise GoldBlindContractError("Retrieval provider result must be exact evidence")
    validate_gold_blind_evidence(value)


def _validate_answer_provider_result(value: object) -> None:
    _reject_exact_deferred_result(value)
    _validate_immediate_json(value, depth=0)


def _validate_immediate_json(value: object, *, depth: int) -> None:
    if depth > 12:
        raise GoldBlindContractError("Answer provider result nesting is invalid")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise GoldBlindContractError("Answer provider result number is invalid")
        return
    if type(value) is list:
        for item in value:
            _validate_immediate_json(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise GoldBlindContractError("Answer provider result key is invalid")
            _validate_immediate_json(item, depth=depth + 1)
        return
    raise GoldBlindContractError("Answer provider result must be exact immediate JSON")


def _raise_sanitized_provider_failure(exc: BaseException, *, stage: str) -> None:
    _raise_sanitized_dispatch_failure(exc, message=f"{stage} provider failed")


def _raise_sanitized_judge_failure(exc: BaseException) -> None:
    _raise_sanitized_dispatch_failure(exc, message="Trusted judge evaluator failed")


def _raise_sanitized_dispatch_failure(exc: BaseException, *, message: str) -> None:
    if type(exc) is asyncio.CancelledError:
        raise asyncio.CancelledError() from None
    if type(exc) is KeyboardInterrupt:
        raise KeyboardInterrupt() from None
    if type(exc) is SystemExit:
        raise SystemExit() from None
    raise GoldBlindContractError(message) from None


def _answer_payload(request: GoldBlindAnswerRequest) -> dict[str, object]:
    _validate_provider_text(request.question, field_name="Answer question")
    _validate_answer_evidence(request.evidence)
    _validate_answer_temporal_context(request)
    return {
        "schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "question": request.question,
        "reference_date": request.reference_date,
        "question_date": request.question_date,
        "evidence": [
            {
                "item_id": item.item_id,
                "text": item.text,
                "rank": item.rank,
                "created_at": item.created_at,
            }
            for item in request.evidence
        ],
    }


def _judge_result_payload(
    result: object,
    *,
    secrets_to_hide: tuple[str, ...],
) -> dict[str, object]:
    if type(result) is not GoldBlindJudgeResult:
        raise GoldBlindContractError("Trusted judge result type must be exact")
    _validate_judge_result_state(result)
    if contains_evaluator_secret(result.verdict, secrets_to_hide):
        raise GoldBlindContractError("Trusted judge result contains evaluator gold")
    return {
        "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
        "verdict": result.verdict,
        "score": result.score,
    }


def _validate_answer_evidence(evidence: object) -> None:
    if type(evidence) is not tuple:
        raise GoldBlindContractError("Answer evidence must be an exact tuple")
    if len(evidence) > _MAX_EVIDENCE_ITEMS:
        raise GoldBlindContractError("Answer evidence exceeds the item limit")
    total_chars = 0
    for item in evidence:
        if type(item) is not GoldBlindEvidence:
            raise GoldBlindContractError("Answer evidence must use exact GoldBlindEvidence")
        _validate_evidence_state(item)
        total_chars += len(item.text)
        if total_chars > _MAX_ANSWER_EVIDENCE_CHARS:
            raise GoldBlindContractError("Answer evidence exceeds the text budget")


def _validate_evidence_state(item: GoldBlindEvidence) -> None:
    _validate_provider_text(item.item_id, field_name="Evidence item_id")
    _validate_exact_string_length(
        item.text,
        field_name="Evidence text",
        maximum=_MAX_EVIDENCE_TEXT_CHARS,
        allow_empty=True,
    )
    if type(item.rank) is not int or item.rank < 1:
        raise GoldBlindContractError("Evidence rank must be a positive exact integer")
    _validate_temporal_text(item.created_at, field_name="Evidence created_at")


def _validate_judge_result_state(result: GoldBlindJudgeResult) -> None:
    if type(result.verdict) is not str or result.verdict not in _JUDGE_VERDICTS:
        raise GoldBlindContractError("Judge verdict is not an allowed exact value")
    if (
        type(result.score) is not float
        or not math.isfinite(result.score)
        or not 0.0 <= result.score <= 1.0
    ):
        raise GoldBlindContractError("Judge score must be an exact finite float from 0 to 1")


def _validate_answer_temporal_context(request: GoldBlindAnswerRequest) -> None:
    if (request.reference_date is None) == (request.question_date is None):
        raise GoldBlindContractError("Answer request requires one exact temporal reference")
    _validate_temporal_text(request.reference_date, field_name="Answer reference_date")
    _validate_temporal_text(
        request.question_date,
        field_name="Answer question_date",
        allow_empty=True,
    )


def _validate_temporal_text(
    value: object,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> None:
    if value is None:
        return
    _validate_exact_string_length(
        value,
        field_name=field_name,
        maximum=_MAX_PROVIDER_TEXT_CHARS,
        allow_empty=allow_empty,
    )
    if value:
        _validate_provider_text(value, field_name=field_name)


def _register_key_integrity(key: JudgeRunKey) -> None:
    snapshot = _KeyIntegritySnapshot(
        run_id=key._JudgeRunKey__run_id,
        case_id=key._JudgeRunKey__case_id,
        secret=key._JudgeRunKey__secret,
    )
    with _INTEGRITY_LOCK:
        _KEY_INTEGRITY[key] = snapshot


def _key_snapshot(key: JudgeRunKey) -> _KeyIntegritySnapshot:
    if type(key) is not JudgeRunKey:
        raise GoldBlindContractError("Judge run key type must be exact")
    with _INTEGRITY_LOCK:
        snapshot = _KEY_INTEGRITY.get(key)
    if snapshot is None:
        raise GoldBlindContractError("Judge key integrity registration is missing")
    try:
        if (
            type(key._JudgeRunKey__run_id) is not str
            or type(key._JudgeRunKey__case_id) is not str
            or type(key._JudgeRunKey__secret) is not bytes
            or key._JudgeRunKey__run_id != snapshot.run_id
            or key._JudgeRunKey__case_id != snapshot.case_id
            or not hmac.compare_digest(key._JudgeRunKey__secret, snapshot.secret)
        ):
            raise GoldBlindContractError("Judge key integrity verification failed")
    except GoldBlindContractError:
        raise
    except Exception:
        raise GoldBlindContractError("Judge key integrity verification failed") from None
    return snapshot


def _validate_channel_binding(
    *,
    key: JudgeRunKey,
    channel: ExactGoldJudgeChannel,
    run_id: str,
    case_id: str,
) -> _ChannelIntegritySnapshot:
    if type(key) is not JudgeRunKey or type(channel) is not ExactGoldJudgeChannel:
        raise GoldBlindContractError("Judge capability types must be exact")
    _validate_nonempty_exact_string(run_id, field_name="Judge run_id")
    _validate_nonempty_exact_string(case_id, field_name="Judge case_id")
    key_snapshot = _key_snapshot(key)
    with _INTEGRITY_LOCK:
        snapshot = _CHANNEL_INTEGRITY.get(channel)
    if snapshot is None:
        raise GoldBlindContractError("Judge channel integrity registration is missing")
    try:
        current_ground_truth = channel._ExactGoldJudgeChannel__ground_truth_json
        current_commitment = channel._ExactGoldJudgeChannel__integrity_commitment
        current_expected = channel._ExactGoldJudgeChannel__expected_terms
        current_forbidden = channel._ExactGoldJudgeChannel__forbidden_terms
        if (
            snapshot.key is not key
            or channel._ExactGoldJudgeChannel__key is not key
            or key_snapshot.run_id != run_id
            or key_snapshot.case_id != case_id
            or type(channel._ExactGoldJudgeChannel__run_id) is not str
            or type(channel._ExactGoldJudgeChannel__case_id) is not str
            or channel._ExactGoldJudgeChannel__run_id != snapshot.run_id
            or channel._ExactGoldJudgeChannel__case_id != snapshot.case_id
            or snapshot.run_id != run_id
            or snapshot.case_id != case_id
            or type(current_ground_truth) is not bytes
            or not hmac.compare_digest(current_ground_truth, snapshot.ground_truth_json)
            or type(current_expected) is not tuple
            or type(current_forbidden) is not tuple
            or any(type(term) is not str for term in current_expected)
            or any(type(term) is not str for term in current_forbidden)
            or current_expected != snapshot.expected_terms
            or current_forbidden != snapshot.forbidden_terms
            or type(current_commitment) is not str
            or not hmac.compare_digest(current_commitment, snapshot.commitment)
        ):
            raise GoldBlindContractError("Judge capability integrity verification failed")
        expected_commitment = _hmac_for_snapshot(key_snapshot, snapshot)
        if not hmac.compare_digest(expected_commitment, snapshot.commitment):
            raise GoldBlindContractError("Judge capability integrity verification failed")
    except GoldBlindContractError:
        raise
    except Exception:
        raise GoldBlindContractError("Judge capability integrity verification failed") from None
    return snapshot


def _validate_judge_key_binding(
    *,
    key: JudgeRunKey,
    run_id: str,
    case_id: str,
) -> None:
    _validate_nonempty_exact_string(run_id, field_name="Judge run_id")
    _validate_nonempty_exact_string(case_id, field_name="Judge case_id")
    snapshot = _key_snapshot(key)
    if snapshot.run_id != run_id or snapshot.case_id != case_id:
        raise GoldBlindContractError("Judge run/case capability binding mismatch")


def _hmac_for_key(key: JudgeRunKey, payload: bytes) -> str:
    snapshot = _key_snapshot(key)
    return hmac.new(snapshot.secret, payload, hashlib.sha256).hexdigest()


def _hmac_for_snapshot(
    key_snapshot: _KeyIntegritySnapshot,
    channel_snapshot: _ChannelIntegritySnapshot,
) -> str:
    ground_truth = _parse_canonical_gold_json(channel_snapshot.ground_truth_json)
    payload = _private_integrity_payload(
        run_id=channel_snapshot.run_id,
        case_id=channel_snapshot.case_id,
        ground_truth=ground_truth,
        expected_terms=channel_snapshot.expected_terms,
        forbidden_terms=channel_snapshot.forbidden_terms,
    )
    return hmac.new(key_snapshot.secret, payload, hashlib.sha256).hexdigest()


def _private_integrity_payload(
    *,
    run_id: str,
    case_id: str,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> bytes:
    return canonical_gold_json(
        {
            "answer_schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
            "case_id": case_id,
            "channel_kind": JUDGE_CHANNEL_KIND,
            "forbidden_terms": list(forbidden_terms),
            "ground_truth": ground_truth,
            "integrity_schema_version": PRIVATE_INTEGRITY_SCHEMA_VERSION,
            "judge_result_schema_version": JUDGE_RESULT_SCHEMA_VERSION,
            "retrieval_schema_version": RETRIEVAL_REQUEST_SCHEMA_VERSION,
            "run_id": run_id,
            "expected_terms": list(expected_terms),
        }
    )


def _trusted_evaluator_callback(
    evaluator: TrustedGoldBlindEvaluator,
) -> Callable[..., GoldBlindJudgeResult]:
    if type(evaluator) is not TrustedGoldBlindEvaluator:
        raise GoldBlindContractError("Judge evaluator must use the exact trusted boundary")
    with _INTEGRITY_LOCK:
        snapshot = _EVALUATOR_INTEGRITY.get(evaluator)
    if snapshot is None:
        raise GoldBlindContractError("Judge evaluator integrity registration is missing")
    try:
        callback = evaluator._TrustedGoldBlindEvaluator__callback
        if (
            callback is not snapshot.callback
            or callback.__code__ is not snapshot.code
            or callback.__globals__ is not snapshot.globals_mapping
            or callback.__module__ != snapshot.module
            or callback.__name__ != snapshot.name
            or callback.__qualname__ != snapshot.qualname
        ):
            raise GoldBlindContractError("Judge evaluator integrity verification failed")
        _validate_trusted_callback(callback)
    except GoldBlindContractError:
        raise
    except Exception:
        raise GoldBlindContractError("Judge evaluator integrity verification failed") from None
    return callback


def _validate_trusted_callback(callback: object) -> None:
    if type(callback) is not FunctionType:
        raise GoldBlindContractError("Trusted evaluator must be an exact function")
    if (
        callback.__closure__ is not None
        or callback.__defaults__ is not None
        or callback.__kwdefaults__ is not None
        or callback.__dict__
    ):
        raise GoldBlindContractError("Trusted evaluator function must be stateless")
