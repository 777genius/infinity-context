"""Issued retrieval DTOs bound to one exact case and backend selection."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    GoldBlindRunDispatchLedger,
    GoldBlindRunDispatchProofError,
    _gold_blind_case_dispatch_fields,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
    is_public_scalar,
    validate_exact_string_length,
    validate_provider_text,
)

RETRIEVAL_REQUEST_SCHEMA_VERSION = "memory-comparison-gold-blind-retrieval.v1"
PUBLIC_RETRIEVAL_METADATA_KEYS = frozenset(
    {
        "category",
        "dataset_split",
        "language",
        "locale",
        "question_date",
        "question_type",
    }
)
_MAX_TEXT_CHARS = 16_384
_TOKEN = object()


@dataclass(frozen=True, slots=True)
class _RetrievalSnapshot:
    ledger: GoldBlindRunDispatchLedger
    run_id: str
    case_id: str
    backend_id: str
    benchmark: str
    question: str
    memory_scope_external_ref: str | None
    thread_external_ref: str | None
    public_metadata: tuple[tuple[str, object], ...]
    reference_date: str | None
    question_date: str | None
    secret: bytes
    commitment: str


@final
class GoldBlindRetrievalRequest:
    """Issued query-only provider view; direct construction is forbidden."""

    __slots__ = (
        "__integrity_commitment",
        "__weakref__",
        "benchmark",
        "case_id",
        "memory_scope_external_ref",
        "public_metadata",
        "question",
        "thread_external_ref",
    )

    def __init__(
        self,
        *,
        benchmark: str,
        case_id: str,
        question: str,
        public_metadata: dict[str, object],
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        integrity_commitment: str = "",
        _token: object = None,
    ) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Retrieval requests must be issued by a case contract")
        self.benchmark = benchmark
        self.case_id = case_id
        self.question = question
        self.memory_scope_external_ref = memory_scope_external_ref
        self.thread_external_ref = thread_external_ref
        self.public_metadata = MappingProxyType(dict(public_metadata))
        self.__integrity_commitment = integrity_commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindRetrievalRequest is final")

    def __repr__(self) -> str:
        return "GoldBlindRetrievalRequest(<redacted>)"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindRetrievalRequest is nonserializable")


_REQUESTS: weakref.WeakKeyDictionary[GoldBlindRetrievalRequest, _RetrievalSnapshot] = (
    weakref.WeakKeyDictionary()
)
_CONTRACT_GUARDS: weakref.WeakKeyDictionary[
    GoldBlindRetrievalRequest, tuple[object, Callable[[object], None]]
] = weakref.WeakKeyDictionary()
_LOCK = threading.RLock()


def _issue_gold_blind_retrieval_request(
    *,
    ledger: GoldBlindRunDispatchLedger,
    run_id: str,
    backend_id: str,
    benchmark: str,
    case_id: str,
    question: str,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    public_metadata: dict[str, object],
    reference_date: str | None,
    question_date: str | None,
) -> GoldBlindRetrievalRequest:
    """Internal builder boundary for an already sanitized benchmark case."""

    _validate_fields(
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        public_metadata=public_metadata,
        reference_date=reference_date,
        question_date=question_date,
    )
    try:
        expected_retrieval, _, _ = _gold_blind_case_dispatch_fields(
            ledger, run_id=run_id, case_id=case_id
        )
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Retrieval request ledger binding failed") from None
    if not hmac.compare_digest(expected_retrieval, backend_id):
        raise GoldBlindContractError("Retrieval request backend binding failed")
    metadata_snapshot = tuple(sorted(public_metadata.items()))
    secret = secrets.token_bytes(32)
    fields = _integrity_fields(
        run_id=run_id,
        backend_id=backend_id,
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        public_metadata=metadata_snapshot,
        reference_date=reference_date,
        question_date=question_date,
    )
    commitment = hmac.new(secret, _canonical(fields), hashlib.sha256).hexdigest()
    request = GoldBlindRetrievalRequest(
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        public_metadata=public_metadata,
        integrity_commitment=commitment,
        _token=_TOKEN,
    )
    with _LOCK:
        _REQUESTS[request] = _RetrievalSnapshot(
            ledger=ledger,
            run_id=run_id,
            case_id=case_id,
            backend_id=backend_id,
            benchmark=benchmark,
            question=question,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            public_metadata=metadata_snapshot,
            reference_date=reference_date,
            question_date=question_date,
            secret=secret,
            commitment=commitment,
        )
    return request


def validate_gold_blind_retrieval_request(
    request: GoldBlindRetrievalRequest,
    ledger: GoldBlindRunDispatchLedger,
    *,
    run_id: str,
    backend_id: str,
) -> None:
    snapshot = _snapshot(request)
    if (
        snapshot.ledger is not ledger
        or snapshot.run_id != run_id
        or not hmac.compare_digest(snapshot.backend_id, backend_id)
    ):
        raise GoldBlindContractError("Retrieval request dispatch binding mismatch")
    try:
        expected_backend, _, _ = _gold_blind_case_dispatch_fields(
            ledger, run_id=run_id, case_id=snapshot.case_id
        )
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Retrieval request ledger binding failed") from None
    if not hmac.compare_digest(expected_backend, backend_id):
        raise GoldBlindContractError("Retrieval request backend binding failed")


def gold_blind_retrieval_payload(
    request: GoldBlindRetrievalRequest,
) -> dict[str, object]:
    snapshot = _snapshot(request)
    return {
        "schema_version": RETRIEVAL_REQUEST_SCHEMA_VERSION,
        "benchmark": snapshot.benchmark,
        "case_id": snapshot.case_id,
        "question": snapshot.question,
        "session": {
            "memory_scope_external_ref": snapshot.memory_scope_external_ref,
            "thread_external_ref": snapshot.thread_external_ref,
        },
        "public_metadata": dict(snapshot.public_metadata),
    }


def _gold_blind_retrieval_snapshot_fields(
    request: GoldBlindRetrievalRequest,
) -> tuple[GoldBlindRunDispatchLedger, str, str, str, str | None, str | None]:
    snapshot = _snapshot(request, validate_contract=False)
    return (
        snapshot.ledger,
        snapshot.run_id,
        snapshot.case_id,
        snapshot.backend_id,
        snapshot.reference_date,
        snapshot.question_date,
    )


def _bind_gold_blind_retrieval_request_to_contract(
    request: GoldBlindRetrievalRequest,
    contract: object,
    validator: Callable[[object], None],
) -> None:
    """Bind an issued request to its externally snapshotted case contract."""

    _snapshot(request, validate_contract=False)
    if type(validator) is not type(_bind_gold_blind_retrieval_request_to_contract):
        raise GoldBlindContractError("Retrieval contract validator must be exact")
    with _LOCK:
        if request in _CONTRACT_GUARDS:
            raise GoldBlindContractError("Retrieval request contract is already bound")
        _CONTRACT_GUARDS[request] = (contract, validator)


def _snapshot(
    request: GoldBlindRetrievalRequest,
    *,
    validate_contract: bool = True,
) -> _RetrievalSnapshot:
    if type(request) is not GoldBlindRetrievalRequest:
        raise GoldBlindContractError("Retrieval request must use the exact issued DTO")
    with _LOCK:
        snapshot = _REQUESTS.get(request)
    if snapshot is None:
        raise GoldBlindContractError("Retrieval request integrity registration is missing")
    try:
        metadata = request.public_metadata
        metadata_snapshot = tuple(sorted(dict(metadata).items()))
        fields = _integrity_fields(
            run_id=snapshot.run_id,
            backend_id=snapshot.backend_id,
            benchmark=request.benchmark,
            case_id=request.case_id,
            question=request.question,
            memory_scope_external_ref=request.memory_scope_external_ref,
            thread_external_ref=request.thread_external_ref,
            public_metadata=metadata_snapshot,
            reference_date=snapshot.reference_date,
            question_date=snapshot.question_date,
        )
        expected = hmac.new(snapshot.secret, _canonical(fields), hashlib.sha256).hexdigest()
        current = request._GoldBlindRetrievalRequest__integrity_commitment
        if (
            type(metadata) is not type(MappingProxyType({}))
            or metadata_snapshot != snapshot.public_metadata
            or type(current) is not str
            or not hmac.compare_digest(current, snapshot.commitment)
            or not hmac.compare_digest(expected, snapshot.commitment)
        ):
            raise GoldBlindContractError("Retrieval request integrity verification failed")
    except GoldBlindContractError:
        raise
    except BaseException:
        raise GoldBlindContractError("Retrieval request integrity verification failed") from None
    if validate_contract:
        with _LOCK:
            guard = _CONTRACT_GUARDS.get(request)
        if guard is None:
            raise GoldBlindContractError("Retrieval request case contract binding is missing")
        contract, validator = guard
        try:
            validator(contract)
        except GoldBlindContractError:
            raise
        except BaseException:
            raise GoldBlindContractError("Retrieval case contract integrity failed") from None
    return snapshot


def _validate_fields(
    *,
    benchmark: object,
    case_id: object,
    question: object,
    memory_scope_external_ref: object,
    thread_external_ref: object,
    public_metadata: object,
    reference_date: object,
    question_date: object,
) -> None:
    validate_provider_text(benchmark, field_name="Retrieval benchmark")
    validate_provider_text(case_id, field_name="Retrieval case_id")
    validate_provider_text(question, field_name="Retrieval question")
    for name, value in (
        ("memory_scope_external_ref", memory_scope_external_ref),
        ("thread_external_ref", thread_external_ref),
    ):
        if value is not None:
            validate_provider_text(value, field_name=f"Retrieval {name}")
    if type(public_metadata) is not dict:
        raise GoldBlindContractError("Retrieval public_metadata must be an exact dict")
    for key, value in public_metadata.items():
        if type(key) is not str or key not in PUBLIC_RETRIEVAL_METADATA_KEYS:
            raise GoldBlindContractError("Retrieval public_metadata contains a non-public key")
        if not is_public_scalar(value):
            raise GoldBlindContractError("Retrieval public_metadata value must be a JSON scalar")
        validate_exact_string_length(
            key,
            field_name="Retrieval public_metadata key",
            maximum=128,
            allow_empty=False,
        )
        if type(value) is str:
            validate_exact_string_length(
                value,
                field_name="Retrieval public_metadata value",
                maximum=_MAX_TEXT_CHARS,
                allow_empty=True,
            )
    _validate_temporal(reference_date, question_date)


def _validate_temporal(reference_date: object, question_date: object) -> None:
    if (reference_date is None) == (question_date is None):
        raise GoldBlindContractError("Retrieval request needs exactly one temporal reference")
    for name, value in (("reference_date", reference_date), ("question_date", question_date)):
        if value is None:
            continue
        validate_exact_string_length(
            value,
            field_name=f"Retrieval {name}",
            maximum=_MAX_TEXT_CHARS,
            allow_empty=name == "question_date",
        )


def _integrity_fields(
    *,
    run_id: str,
    backend_id: str,
    benchmark: str,
    case_id: str,
    question: str,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    public_metadata: tuple[tuple[str, object], ...],
    reference_date: str | None,
    question_date: str | None,
) -> dict[str, object]:
    return {
        "schema_version": RETRIEVAL_REQUEST_SCHEMA_VERSION,
        "run_id": run_id,
        "backend_id": backend_id,
        "benchmark": benchmark,
        "case_id": case_id,
        "question": question,
        "memory_scope_external_ref": memory_scope_external_ref,
        "thread_external_ref": thread_external_ref,
        "public_metadata": dict(public_metadata),
        "reference_date": reference_date,
        "question_date": question_date,
    }


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
