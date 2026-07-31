"""Backend-bound reservations, receipts, and sealed gold-blind admission."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_gold_blind_validation import GoldBlindContractError

RUN_DISPATCH_PROOF_SCHEMA_VERSION = "memory-comparison-gold-blind-dispatch-proof.v4"
_MAX_ID_CHARS = 16_384
_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_STAGES = ("retrieval", "answer", "judge")
_TOKEN = object()


class GoldBlindRunDispatchProofError(GoldBlindContractError):
    """Raised when dispatch state cannot prove the expected execution."""


@final
@dataclass(frozen=True, slots=True)
class GoldBlindExpectedDispatchCase:
    """Exact backend-role selection for one expected case in a run."""

    case_id: str
    retrieval_backend_id: str
    answer_backend_id: str
    judge_backend_id: str

    def __post_init__(self) -> None:
        _validate_id(self.case_id, field_name="Expected case_id")
        for value in (
            self.retrieval_backend_id,
            self.answer_backend_id,
            self.judge_backend_id,
        ):
            _validate_id(value, field_name="Expected backend_id")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindExpectedDispatchCase is final")


@dataclass(frozen=True, slots=True)
class _ExpectedSnapshot:
    case_id: str
    retrieval_backend_id: str
    answer_backend_id: str
    judge_backend_id: str


@dataclass(frozen=True, slots=True)
class _ReceiptSnapshot:
    receipt_identity: str
    result_identity: str | None


@dataclass(slots=True)
class _LedgerState:
    run_id: str
    comparison_binding_commitment_sha256: str
    secret: bytes
    expected: dict[str, _ExpectedSnapshot]
    receipts: dict[tuple[str, str], _ReceiptSnapshot]
    pending: set[tuple[str, str]]
    generation: int
    sealed: bool


@dataclass(frozen=True, slots=True)
class _AnswerBindingSnapshot:
    ledger: GoldBlindRunDispatchLedger
    run_id: str
    case_id: str
    answer_backend_id: str
    retrieval_identity: str
    evidence_identity: str


@dataclass(frozen=True, slots=True)
class _ValidationSnapshot:
    ledger: GoldBlindRunDispatchLedger
    run_id: str
    generation: int
    commitment: str
    report: MappingProxyType[str, object]


@final
class GoldBlindRunDispatchLedger:
    """Opaque mutable-until-verified run lifecycle."""

    __slots__ = ("__run_id", "__weakref__")

    def __init__(self, *, run_id: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindRunDispatchProofError("Dispatch ledgers must be issued")
        _validate_id(run_id, field_name="Dispatch run_id")
        self.__run_id = run_id

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindRunDispatchLedger is final")

    def __repr__(self) -> str:
        return "GoldBlindRunDispatchLedger(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindRunDispatchLedger is nonserializable")


@final
class GoldBlindAnswerDispatchBinding:
    """Issued proof that exact retrieval evidence may enter one answer dispatch."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindRunDispatchProofError("Answer bindings must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindAnswerDispatchBinding is final")

    def __repr__(self) -> str:
        return "GoldBlindAnswerDispatchBinding(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindAnswerDispatchBinding is nonserializable")


@final
class VerifiedGoldBlindExecutionValidation:
    """Issued admission capability; serialized reports are never admission input."""

    __slots__ = ("__commitment", "__run_id", "__weakref__")

    def __init__(self, *, run_id: str, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindRunDispatchProofError("Execution validations must be issued")
        self.__run_id = run_id
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("VerifiedGoldBlindExecutionValidation is final")

    def __repr__(self) -> str:
        return "VerifiedGoldBlindExecutionValidation(<sealed>)"

    def __reduce__(self) -> object:
        raise TypeError("VerifiedGoldBlindExecutionValidation is nonserializable")


_LOCK = threading.RLock()


def _build_public_dispatch_api() -> tuple[Callable[..., object], ...]:
    states: weakref.WeakKeyDictionary[GoldBlindRunDispatchLedger, _LedgerState] = (
        weakref.WeakKeyDictionary()
    )
    owned_ledgers: weakref.WeakSet[GoldBlindRunDispatchLedger] = weakref.WeakSet()
    answer_bindings: weakref.WeakKeyDictionary[
        GoldBlindAnswerDispatchBinding, _AnswerBindingSnapshot
    ] = weakref.WeakKeyDictionary()
    validations: weakref.WeakKeyDictionary[
        VerifiedGoldBlindExecutionValidation, _ValidationSnapshot
    ] = weakref.WeakKeyDictionary()

    def create_ledger(
        *,
        run_id: str,
        comparison_binding_commitment_sha256: str,
        expected_cases: tuple[GoldBlindExpectedDispatchCase, ...],
    ) -> GoldBlindRunDispatchLedger:
        _validate_id(run_id, field_name="Dispatch run_id")
        _validate_digest(
            comparison_binding_commitment_sha256,
            field_name="Comparison binding commitment",
        )
        if type(expected_cases) is not tuple or not expected_cases:
            raise GoldBlindRunDispatchProofError("Expected dispatch cases must be a nonempty tuple")
        expected: dict[str, _ExpectedSnapshot] = {}
        for item in expected_cases:
            if type(item) is not GoldBlindExpectedDispatchCase:
                raise GoldBlindRunDispatchProofError("Expected dispatch case type must be exact")
            item.__post_init__()
            if item.case_id in expected:
                raise GoldBlindRunDispatchProofError("Expected dispatch case_id is duplicated")
            expected[item.case_id] = _ExpectedSnapshot(
                item.case_id,
                item.retrieval_backend_id,
                item.answer_backend_id,
                item.judge_backend_id,
            )
        ledger = GoldBlindRunDispatchLedger(run_id=run_id, _token=_TOKEN)
        with _LOCK:
            states[ledger] = _LedgerState(
                run_id,
                comparison_binding_commitment_sha256,
                secrets.token_bytes(32),
                expected,
                {},
                set(),
                0,
                False,
            )
            owned_ledgers.add(ledger)
        return ledger

    def dispatch_retrieval(
        port: object,
        request: object,
        *,
        backend_id: str,
        dispatch_ledger: GoldBlindRunDispatchLedger,
        run_id: str,
        top_k: int,
    ) -> object:
        from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
            gold_blind_evidence_identity,
        )
        from infinity_context_server.memory_comparison_gold_blind_contract import (
            _raise_sanitized_provider_failure,
            _validate_retrieval_provider_result,
        )
        from infinity_context_server.memory_comparison_gold_blind_retrieval_contract import (
            gold_blind_retrieval_payload,
            validate_gold_blind_retrieval_request,
        )

        _validate_id(run_id, field_name="run_id")
        if type(top_k) is not int or top_k < 1:
            raise GoldBlindContractError("top_k must be a positive exact integer")
        validate_gold_blind_retrieval_request(
            request,  # type: ignore[arg-type]
            dispatch_ledger,
            run_id=run_id,
            backend_id=backend_id,
        )
        payload = gold_blind_retrieval_payload(request)  # type: ignore[arg-type]
        receipt_key = (request.case_id, "retrieval")  # type: ignore[attr-defined]
        try:
            if dispatch_ledger not in owned_ledgers:
                raise GoldBlindRunDispatchProofError("Dispatch ledger is not coordinator-owned")
            with _LOCK:
                state = states.get(dispatch_ledger)
            _validate_registered_ledger_state(dispatch_ledger, state)
            with _LOCK:
                _validate_open_binding(
                    state,  # type: ignore[arg-type]
                    run_id,
                    request.case_id,  # type: ignore[attr-defined]
                    backend_id,
                    "retrieval",
                )
                if receipt_key in state.pending or receipt_key in state.receipts:  # type: ignore[union-attr]
                    raise GoldBlindRunDispatchProofError("Duplicate dispatch receipt")
                state.pending.add(receipt_key)  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except GoldBlindRunDispatchProofError:
            raise GoldBlindContractError("Run dispatch ledger verification failed") from None
        try:
            try:
                result = port.search(payload, run_id=run_id, top_k=top_k)  # type: ignore[attr-defined]
                _validate_retrieval_provider_result(result)
                evidence_identity = gold_blind_evidence_identity(result)  # type: ignore[arg-type]
            except BaseException as exc:
                _raise_sanitized_provider_failure(exc, stage="Retrieval")
            event = _canonical_json(
                {
                    "backend_id": backend_id,
                    "case_id": request.case_id,  # type: ignore[attr-defined]
                    "identity": {"request": payload, "top_k": top_k},
                    "result_identity": evidence_identity,
                    "run_id": run_id,
                    "schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION,
                    "stage": "retrieval",
                }
            )
            receipt = _ReceiptSnapshot(
                hashlib.sha256(event).hexdigest(),
                evidence_identity,
            )
            with _LOCK:
                if (
                    state.sealed  # type: ignore[union-attr]
                    or receipt_key not in state.pending  # type: ignore[union-attr]
                    or receipt_key in state.receipts  # type: ignore[union-attr]
                ):
                    raise GoldBlindRunDispatchProofError("Retrieval dispatch is not live")
                state.pending.remove(receipt_key)  # type: ignore[union-attr]
                state.receipts[receipt_key] = receipt  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except BaseException as exc:
            with _LOCK:
                if (
                    receipt_key in state.pending  # type: ignore[union-attr]
                    and receipt_key not in state.receipts  # type: ignore[union-attr]
                ):
                    state.pending.remove(receipt_key)  # type: ignore[union-attr]
                    state.generation += 1  # type: ignore[union-attr]
            if type(exc) is GoldBlindRunDispatchProofError:
                raise GoldBlindContractError("Run dispatch completion failed") from None
            raise
        return result

    def dispatch_answer(
        port: object,
        request: object,
        *,
        backend_id: str,
        dispatch_ledger: GoldBlindRunDispatchLedger,
        run_id: str,
        case_id: str,
    ) -> object:
        from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
            validate_gold_blind_answer_request,
        )
        from infinity_context_server.memory_comparison_gold_blind_contract import (
            _answer_payload,
            _raise_sanitized_provider_failure,
            _validate_answer_provider_result,
        )

        _validate_id(run_id, field_name="run_id")
        _validate_id(case_id, field_name="case_id")
        validate_gold_blind_answer_request(
            request,  # type: ignore[arg-type]
            dispatch_ledger,
            run_id=run_id,
            case_id=case_id,
            backend_id=backend_id,
        )
        payload = _answer_payload(request)  # type: ignore[arg-type]
        receipt_key = (case_id, "answer")
        try:
            if dispatch_ledger not in owned_ledgers:
                raise GoldBlindRunDispatchProofError("Dispatch ledger is not coordinator-owned")
            with _LOCK:
                state = states.get(dispatch_ledger)
            _validate_registered_ledger_state(dispatch_ledger, state)
            with _LOCK:
                _validate_open_binding(
                    state,  # type: ignore[arg-type]
                    run_id,
                    case_id,
                    backend_id,
                    "answer",
                )
                if receipt_key in state.pending or receipt_key in state.receipts:  # type: ignore[union-attr]
                    raise GoldBlindRunDispatchProofError("Duplicate dispatch receipt")
                state.pending.add(receipt_key)  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except GoldBlindRunDispatchProofError:
            raise GoldBlindContractError("Run dispatch ledger verification failed") from None
        try:
            try:
                result = port.answer(payload)  # type: ignore[attr-defined]
                _validate_answer_provider_result(result)
            except BaseException as exc:
                _raise_sanitized_provider_failure(exc, stage="Answer")
            event = _canonical_json(
                {
                    "backend_id": backend_id,
                    "case_id": case_id,
                    "identity": payload,
                    "result_identity": None,
                    "run_id": run_id,
                    "schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION,
                    "stage": "answer",
                }
            )
            receipt = _ReceiptSnapshot(hashlib.sha256(event).hexdigest(), None)
            with _LOCK:
                if (
                    state.sealed  # type: ignore[union-attr]
                    or receipt_key not in state.pending  # type: ignore[union-attr]
                    or receipt_key in state.receipts  # type: ignore[union-attr]
                ):
                    raise GoldBlindRunDispatchProofError("Answer dispatch is not live")
                state.pending.remove(receipt_key)  # type: ignore[union-attr]
                state.receipts[receipt_key] = receipt  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except BaseException as exc:
            with _LOCK:
                if (
                    receipt_key in state.pending  # type: ignore[union-attr]
                    and receipt_key not in state.receipts  # type: ignore[union-attr]
                ):
                    state.pending.remove(receipt_key)  # type: ignore[union-attr]
                    state.generation += 1  # type: ignore[union-attr]
            if type(exc) is GoldBlindRunDispatchProofError:
                raise GoldBlindContractError("Run dispatch completion failed") from None
            raise
        return result

    def dispatch_judge(
        evaluator: object,
        channel: object,
        *,
        backend_id: str,
        dispatch_ledger: GoldBlindRunDispatchLedger,
        key: object,
        run_id: str,
        case_id: str,
    ) -> object:
        from infinity_context_server.memory_comparison_gold_blind_contract import (
            _judge_result_payload,
            _raise_sanitized_judge_failure,
            _reject_exact_deferred_result,
            _trusted_evaluator_callback,
            _validate_channel_binding,
        )
        from infinity_context_server.memory_comparison_gold_blind_validation import (
            freeze_json_value,
            parse_canonical_gold_json,
            secret_fragments,
        )

        callback = _trusted_evaluator_callback(evaluator)
        snapshot = _validate_channel_binding(
            key=key,
            channel=channel,
            run_id=run_id,
            case_id=case_id,
        )
        receipt_key = (case_id, "judge")
        try:
            if dispatch_ledger not in owned_ledgers:
                raise GoldBlindRunDispatchProofError("Dispatch ledger is not coordinator-owned")
            with _LOCK:
                state = states.get(dispatch_ledger)
            _validate_registered_ledger_state(dispatch_ledger, state)
            with _LOCK:
                _validate_open_binding(
                    state,  # type: ignore[arg-type]
                    run_id,
                    case_id,
                    backend_id,
                    "judge",
                )
                if receipt_key in state.pending or receipt_key in state.receipts:  # type: ignore[union-attr]
                    raise GoldBlindRunDispatchProofError("Duplicate dispatch receipt")
                state.pending.add(receipt_key)  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except GoldBlindRunDispatchProofError:
            raise GoldBlindContractError("Run dispatch ledger verification failed") from None
        try:
            try:
                mutable_ground_truth = parse_canonical_gold_json(snapshot.ground_truth_json)
                immutable_ground_truth = freeze_json_value(mutable_ground_truth)
                result = callback(
                    ground_truth=immutable_ground_truth,
                    expected_terms=tuple(snapshot.expected_terms),
                    forbidden_terms=tuple(snapshot.forbidden_terms),
                )
                _reject_exact_deferred_result(result)
                _trusted_evaluator_callback(evaluator)
                output = _judge_result_payload(
                    result,
                    secrets_to_hide=secret_fragments(
                        mutable_ground_truth,
                        snapshot.expected_terms,
                        snapshot.forbidden_terms,
                    ),
                )
            except BaseException as exc:
                _raise_sanitized_judge_failure(exc)
            event = _canonical_json(
                {
                    "backend_id": backend_id,
                    "case_id": case_id,
                    "identity": {
                        "gold_commitment": snapshot.commitment,
                        "result": output,
                    },
                    "result_identity": None,
                    "run_id": run_id,
                    "schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION,
                    "stage": "judge",
                }
            )
            receipt = _ReceiptSnapshot(hashlib.sha256(event).hexdigest(), None)
            with _LOCK:
                if (
                    state.sealed  # type: ignore[union-attr]
                    or receipt_key not in state.pending  # type: ignore[union-attr]
                    or receipt_key in state.receipts  # type: ignore[union-attr]
                ):
                    raise GoldBlindRunDispatchProofError("Judge dispatch is not live")
                state.pending.remove(receipt_key)  # type: ignore[union-attr]
                state.receipts[receipt_key] = receipt  # type: ignore[union-attr]
                state.generation += 1  # type: ignore[union-attr]
        except BaseException as exc:
            with _LOCK:
                if (
                    receipt_key in state.pending  # type: ignore[union-attr]
                    and receipt_key not in state.receipts  # type: ignore[union-attr]
                ):
                    state.pending.remove(receipt_key)  # type: ignore[union-attr]
                    state.generation += 1  # type: ignore[union-attr]
            if type(exc) is GoldBlindRunDispatchProofError:
                raise GoldBlindContractError("Run dispatch completion failed") from None
            raise
        return output

    def lookup_state(ledger: GoldBlindRunDispatchLedger) -> _LedgerState:
        if type(ledger) is not GoldBlindRunDispatchLedger:
            raise GoldBlindRunDispatchProofError("Dispatch ledger type must be exact")
        with _LOCK:
            state = states.get(ledger)
        if state is None:
            raise GoldBlindRunDispatchProofError("Dispatch ledger registration is missing")
        try:
            current_run_id = ledger._GoldBlindRunDispatchLedger__run_id
        except Exception:
            raise GoldBlindRunDispatchProofError("Dispatch ledger integrity failed") from None
        if type(current_run_id) is not str or current_run_id != state.run_id:
            raise GoldBlindRunDispatchProofError("Dispatch ledger integrity failed")
        return state

    def answer_binding_snapshot(
        binding: GoldBlindAnswerDispatchBinding,
    ) -> _AnswerBindingSnapshot:
        if type(binding) is not GoldBlindAnswerDispatchBinding:
            raise GoldBlindRunDispatchProofError("Answer binding type must be exact")
        with _LOCK:
            snapshot = answer_bindings.get(binding)
        if snapshot is None:
            raise GoldBlindRunDispatchProofError("Answer binding registration is missing")
        state = lookup_state(snapshot.ledger)
        expected = _commitment(
            state.secret,
            {
                "run_id": snapshot.run_id,
                "case_id": snapshot.case_id,
                "answer_backend_id": snapshot.answer_backend_id,
                "retrieval_identity": snapshot.retrieval_identity,
                "evidence_identity": snapshot.evidence_identity,
            },
        )
        try:
            current = binding._GoldBlindAnswerDispatchBinding__commitment
        except Exception:
            raise GoldBlindRunDispatchProofError("Answer binding integrity failed") from None
        if type(current) is not str or not hmac.compare_digest(current, expected):
            raise GoldBlindRunDispatchProofError("Answer binding integrity failed")
        return snapshot

    def validate_answer_binding_current(snapshot: _AnswerBindingSnapshot) -> None:
        state = lookup_state(snapshot.ledger)
        with _LOCK:
            if state.sealed:
                raise GoldBlindRunDispatchProofError("Dispatch ledger is sealed")
            retrieval = state.receipts.get((snapshot.case_id, "retrieval"))
            if (
                retrieval is None
                or not hmac.compare_digest(
                    retrieval.receipt_identity,
                    snapshot.retrieval_identity,
                )
                or retrieval.result_identity is None
                or not hmac.compare_digest(
                    retrieval.result_identity,
                    snapshot.evidence_identity,
                )
            ):
                raise GoldBlindRunDispatchProofError("Answer retrieval binding is stale")

    def case_dispatch_fields(
        ledger: GoldBlindRunDispatchLedger,
        *,
        run_id: str,
        case_id: str,
    ) -> tuple[str, str, str]:
        state = lookup_state(ledger)
        _validate_id(run_id, field_name="Dispatch run_id")
        _validate_id(case_id, field_name="Dispatch case_id")
        with _LOCK:
            if state.sealed or state.run_id != run_id:
                raise GoldBlindRunDispatchProofError("Dispatch case binding mismatch")
            expected = state.expected.get(case_id)
            if expected is None:
                raise GoldBlindRunDispatchProofError("Unexpected dispatch case")
            return (
                expected.retrieval_backend_id,
                expected.answer_backend_id,
                expected.judge_backend_id,
            )

    def issue_answer_binding(
        ledger: GoldBlindRunDispatchLedger,
        *,
        run_id: str,
        case_id: str,
        backend_id: str,
        evidence_identity: str,
    ) -> GoldBlindAnswerDispatchBinding:
        _validate_digest(evidence_identity, field_name="Evidence identity")
        state = lookup_state(ledger)
        with _LOCK:
            _validate_open_binding(state, run_id, case_id, backend_id, "answer")
            retrieval = state.receipts.get((case_id, "retrieval"))
            if retrieval is None or retrieval.result_identity is None:
                raise GoldBlindRunDispatchProofError("Retrieval evidence receipt is missing")
            if not hmac.compare_digest(retrieval.result_identity, evidence_identity):
                raise GoldBlindRunDispatchProofError("Retrieval evidence identity mismatch")
            fields = {
                "run_id": run_id,
                "case_id": case_id,
                "answer_backend_id": backend_id,
                "retrieval_identity": retrieval.receipt_identity,
                "evidence_identity": evidence_identity,
            }
            commitment = _commitment(state.secret, fields)
            binding = GoldBlindAnswerDispatchBinding(
                commitment=commitment,
                _token=_TOKEN,
            )
            answer_bindings[binding] = _AnswerBindingSnapshot(
                ledger,
                run_id,
                case_id,
                backend_id,
                retrieval.receipt_identity,
                evidence_identity,
            )
        return binding

    def answer_binding_fields(
        binding: GoldBlindAnswerDispatchBinding,
    ) -> tuple[str, str, str, str]:
        snapshot = answer_binding_snapshot(binding)
        validate_answer_binding_current(snapshot)
        return (
            snapshot.run_id,
            snapshot.case_id,
            snapshot.answer_backend_id,
            snapshot.evidence_identity,
        )

    def validate_answer_binding(
        binding: GoldBlindAnswerDispatchBinding,
        ledger: GoldBlindRunDispatchLedger,
        *,
        run_id: str,
        case_id: str,
        backend_id: str,
        evidence_identity: str,
    ) -> None:
        snapshot = answer_binding_snapshot(binding)
        if (
            snapshot.ledger is not ledger
            or snapshot.run_id != run_id
            or snapshot.case_id != case_id
            or snapshot.answer_backend_id != backend_id
            or not hmac.compare_digest(
                snapshot.evidence_identity,
                evidence_identity,
            )
        ):
            raise GoldBlindRunDispatchProofError("Answer dispatch binding mismatch")
        validate_answer_binding_current(snapshot)

    def verify_execution(
        ledger: GoldBlindRunDispatchLedger,
    ) -> VerifiedGoldBlindExecutionValidation:
        state = lookup_state(ledger)
        with _LOCK:
            if state.sealed:
                raise GoldBlindRunDispatchProofError("Dispatch ledger is already sealed")
            missing = [
                (case_id, stage)
                for case_id in state.expected
                for stage in _STAGES
                if (case_id, stage) not in state.receipts
            ]
            if state.pending or missing or len(state.receipts) != len(state.expected) * 3:
                raise GoldBlindRunDispatchProofError("Gold-blind execution receipts are incomplete")
            state.sealed = True
            state.generation += 1
            report_fields = _report_fields(state)
            commitment = _commitment(state.secret, report_fields)
            validation = VerifiedGoldBlindExecutionValidation(
                run_id=state.run_id,
                commitment=commitment,
                _token=_TOKEN,
            )
            validations[validation] = _ValidationSnapshot(
                ledger,
                state.run_id,
                state.generation,
                commitment,
                MappingProxyType(
                    {
                        "schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION,
                        **report_fields,
                        "commitment": commitment,
                    }
                ),
            )
        return validation

    def execution_report(
        validation: VerifiedGoldBlindExecutionValidation,
    ) -> dict[str, object]:
        if type(validation) is not VerifiedGoldBlindExecutionValidation:
            raise GoldBlindRunDispatchProofError("Execution validation type must be exact")
        with _LOCK:
            snapshot = validations.get(validation)
        if snapshot is None:
            raise GoldBlindRunDispatchProofError("Execution validation registration is missing")
        try:
            run_id = validation._VerifiedGoldBlindExecutionValidation__run_id
            commitment = validation._VerifiedGoldBlindExecutionValidation__commitment
        except Exception:
            raise GoldBlindRunDispatchProofError("Execution validation integrity failed") from None
        state = lookup_state(snapshot.ledger)
        with _LOCK:
            current_fields = _report_fields(state)
            current_commitment = _commitment(state.secret, current_fields)
            valid = (
                state.sealed
                and state.generation == snapshot.generation
                and type(run_id) is str
                and run_id == snapshot.run_id == state.run_id
                and type(commitment) is str
                and hmac.compare_digest(commitment, snapshot.commitment)
                and hmac.compare_digest(current_commitment, snapshot.commitment)
                and dict(snapshot.report)
                == {
                    "schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION,
                    **current_fields,
                    "commitment": current_commitment,
                }
            )
        if not valid:
            raise GoldBlindRunDispatchProofError("Execution validation integrity failed")
        return dict(snapshot.report)

    return (
        create_ledger,
        dispatch_retrieval,
        dispatch_answer,
        dispatch_judge,
        case_dispatch_fields,
        issue_answer_binding,
        answer_binding_fields,
        validate_answer_binding,
        verify_execution,
        execution_report,
    )


(
    create_gold_blind_run_dispatch_ledger,
    dispatch_retrieval,
    dispatch_answer,
    dispatch_judge,
    _gold_blind_case_dispatch_fields,
    _issue_gold_blind_answer_dispatch_binding,
    _gold_blind_answer_dispatch_binding_fields,
    validate_gold_blind_answer_dispatch_binding,
    verify_gold_blind_execution,
    verified_gold_blind_execution_report,
) = _build_public_dispatch_api()
del _build_public_dispatch_api


def _validate_registered_ledger_state(
    ledger: GoldBlindRunDispatchLedger,
    state: _LedgerState | None,
) -> None:
    if type(ledger) is not GoldBlindRunDispatchLedger or state is None:
        raise GoldBlindRunDispatchProofError("Dispatch ledger registration is missing")
    try:
        current_run_id = ledger._GoldBlindRunDispatchLedger__run_id
    except Exception:
        raise GoldBlindRunDispatchProofError("Dispatch ledger integrity failed") from None
    if type(current_run_id) is not str or current_run_id != state.run_id:
        raise GoldBlindRunDispatchProofError("Dispatch ledger integrity failed")


def _validate_open_binding(
    state: _LedgerState,
    run_id: str,
    case_id: str,
    backend_id: str,
    stage: str,
) -> None:
    _validate_id(run_id, field_name="Dispatch run_id")
    _validate_id(case_id, field_name="Dispatch case_id")
    _validate_id(backend_id, field_name="Dispatch backend_id")
    if stage not in _STAGES:
        raise GoldBlindRunDispatchProofError("Dispatch stage is invalid")
    if state.sealed:
        raise GoldBlindRunDispatchProofError("Dispatch ledger is sealed")
    if state.run_id != run_id:
        raise GoldBlindRunDispatchProofError("Dispatch ledger run binding mismatch")
    expected = state.expected.get(case_id)
    if expected is None:
        raise GoldBlindRunDispatchProofError("Unexpected dispatch case")
    expected_backend = getattr(expected, f"{stage}_backend_id")
    if not hmac.compare_digest(backend_id, expected_backend):
        raise GoldBlindRunDispatchProofError("Dispatch backend-role binding mismatch")


def _report_fields(state: _LedgerState) -> dict[str, object]:
    stage_identities = {
        stage: hashlib.sha256(
            "".join(
                state.receipts[(case_id, stage)].receipt_identity
                for case_id in sorted(state.expected)
            ).encode()
        ).hexdigest()
        for stage in _STAGES
    }
    count = len(state.expected)
    return {
        "run_id": state.run_id,
        "comparison_binding_commitment_sha256": (state.comparison_binding_commitment_sha256),
        "expected_case_count": count,
        "retrieval_dispatch_count": count,
        "answer_dispatch_count": count,
        "judge_dispatch_count": count,
        "retrieval_identity": stage_identities["retrieval"],
        "answer_identity": stage_identities["answer"],
        "judge_identity": stage_identities["judge"],
    }


def _commitment(secret: bytes, fields: dict[str, object]) -> str:
    return hmac.new(
        secret,
        _canonical_json({"schema_version": RUN_DISPATCH_PROOF_SCHEMA_VERSION, **fields}),
        hashlib.sha256,
    ).hexdigest()


def _validate_id(value: object, *, field_name: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > _MAX_ID_CHARS:
        raise GoldBlindRunDispatchProofError(f"{field_name} is invalid")


def _validate_digest(value: object, *, field_name: str) -> None:
    if type(value) is not str or not _HEX_256.fullmatch(value):
        raise GoldBlindRunDispatchProofError(f"{field_name} is invalid")


def _canonical_json(value: object) -> bytes:
    _validate_json(value, depth=0)
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError):
        raise GoldBlindRunDispatchProofError("Dispatch identity is not JSON") from None


def _validate_json(value: object, *, depth: int) -> None:
    if depth > 12:
        raise GoldBlindRunDispatchProofError("Dispatch identity nesting is invalid")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise GoldBlindRunDispatchProofError("Dispatch identity number is invalid")
        return
    if type(value) is list:
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise GoldBlindRunDispatchProofError("Dispatch identity key is invalid")
            _validate_json(item, depth=depth + 1)
        return
    raise GoldBlindRunDispatchProofError("Dispatch identity is not exact JSON")
