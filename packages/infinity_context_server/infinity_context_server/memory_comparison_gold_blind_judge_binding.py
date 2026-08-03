"""Opaque one-shot binding from an answer receipt to a trusted judge call."""

from __future__ import annotations

import hashlib
import hmac
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_gold_blind_run_validation import (
    canonical_dispatch_json,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
)

_TOKEN = object()


@final
class GoldBlindJudgeDispatchBinding:
    """Bind one judge call to one exact answer receipt.

    Evaluator scoring semantics remain inside the separately trusted evaluator boundary.
    """

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Judge bindings must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindJudgeDispatchBinding is final")

    def __repr__(self) -> str:
        return "GoldBlindJudgeDispatchBinding(<opaque-one-shot>)"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindJudgeDispatchBinding is nonserializable")


@dataclass(frozen=True, slots=True, repr=False)
class _GoldBlindJudgeBindingPayload:
    ledger: object
    run_id: str
    case_id: str
    judge_backend_id: str
    answer_receipt_identity: str
    answer_result_identity: str
    answer_json: bytes

    def __repr__(self) -> str:
        return "_GoldBlindJudgeBindingPayload(<redacted>)"


@final
class _GoldBlindJudgeBindingRegistry:
    """Private integrity registry and atomic one-shot consumption boundary."""

    __slots__ = ("__bindings", "__consumed", "__lock")

    def __init__(self) -> None:
        self.__bindings: weakref.WeakKeyDictionary[
            GoldBlindJudgeDispatchBinding, _GoldBlindJudgeBindingPayload
        ] = weakref.WeakKeyDictionary()
        self.__consumed: weakref.WeakSet[GoldBlindJudgeDispatchBinding] = weakref.WeakSet()
        self.__lock = threading.RLock()

    def issue(
        self,
        *,
        ledger: object,
        run_id: str,
        case_id: str,
        judge_backend_id: str,
        answer_receipt_identity: str,
        answer_result_identity: str,
        answer_json: bytes,
        secret: bytes,
        schema_version: str,
    ) -> GoldBlindJudgeDispatchBinding:
        payload = _GoldBlindJudgeBindingPayload(
            ledger,
            run_id,
            case_id,
            judge_backend_id,
            answer_receipt_identity,
            answer_result_identity,
            answer_json,
        )
        commitment = _binding_commitment(payload, secret=secret, schema_version=schema_version)
        binding = GoldBlindJudgeDispatchBinding(commitment=commitment, _token=_TOKEN)
        with self.__lock:
            self.__bindings[binding] = payload
        return binding

    def consume(
        self,
        binding: object,
        *,
        ledger: object,
        run_id: str,
        case_id: str,
        judge_backend_id: str,
        answer_receipt_identity: str,
        answer_result_identity: str,
        secret: bytes,
        schema_version: str,
    ) -> _GoldBlindJudgeBindingPayload:
        if type(binding) is not GoldBlindJudgeDispatchBinding:
            raise GoldBlindContractError("Judge binding type must be exact")
        with self.__lock:
            payload = self.__bindings.get(binding)
            if payload is None:
                raise GoldBlindContractError("Judge binding registration is missing")
            expected = _binding_commitment(
                payload,
                secret=secret,
                schema_version=schema_version,
            )
            try:
                current = binding._GoldBlindJudgeDispatchBinding__commitment
            except Exception:
                raise GoldBlindContractError("Judge binding integrity failed") from None
            valid = (
                payload.ledger is ledger
                and payload.run_id == run_id
                and payload.case_id == case_id
                and payload.judge_backend_id == judge_backend_id
                and hmac.compare_digest(payload.answer_receipt_identity, answer_receipt_identity)
                and hmac.compare_digest(payload.answer_result_identity, answer_result_identity)
                and hmac.compare_digest(
                    hashlib.sha256(payload.answer_json).hexdigest(),
                    answer_result_identity,
                )
                and type(current) is str
                and hmac.compare_digest(current, expected)
            )
            if not valid or binding in self.__consumed:
                raise GoldBlindContractError("Judge answer binding mismatch")
            self.__consumed.add(binding)
        return payload


def _binding_commitment(
    payload: _GoldBlindJudgeBindingPayload,
    *,
    secret: bytes,
    schema_version: str,
) -> str:
    fields = {
        "run_id": payload.run_id,
        "case_id": payload.case_id,
        "judge_backend_id": payload.judge_backend_id,
        "answer_receipt_identity": payload.answer_receipt_identity,
        "answer_result_identity": payload.answer_result_identity,
    }
    return hmac.new(
        secret,
        canonical_dispatch_json({"schema_version": schema_version, **fields}),
        hashlib.sha256,
    ).hexdigest()
