"""Issued answer DTOs bound to exact retrieval evidence and temporal context."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass, field
from typing import final

from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    GoldBlindAnswerDispatchBinding,
    GoldBlindRunDispatchLedger,
    GoldBlindRunDispatchProofError,
    _gold_blind_answer_dispatch_binding_fields,
    _gold_blind_case_dispatch_fields,
    _issue_gold_blind_answer_dispatch_binding,
    validate_gold_blind_answer_dispatch_binding,
)
from infinity_context_server.memory_comparison_gold_blind_validation import (
    GoldBlindContractError,
    validate_exact_string_length,
    validate_nonempty_exact_string,
    validate_provider_text,
)

ANSWER_REQUEST_SCHEMA_VERSION = "memory-comparison-gold-blind-answer.v1"
_MAX_PROVIDER_TEXT_CHARS = 16_384
_MAX_EVIDENCE_ITEMS = 1_024
_MAX_EVIDENCE_TEXT_CHARS = 131_072
_MAX_ANSWER_EVIDENCE_CHARS = 1_048_576
_TOKEN = object()


@final
@dataclass(frozen=True, slots=True)
class GoldBlindEvidence:
    """The only retrieval fields an answer provider may observe."""

    item_id: str
    text: str = field(repr=False)
    rank: int
    created_at: str | None = None

    def __post_init__(self) -> None:
        _validate_evidence_state(self)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindEvidence is final")

    def __repr__(self) -> str:
        return f"GoldBlindEvidence(item_id=<redacted>, rank={self.rank}, text=<redacted>)"


@dataclass(frozen=True, slots=True)
class _AnswerIssuerSnapshot:
    ledger: GoldBlindRunDispatchLedger
    run_id: str
    case_id: str
    backend_id: str
    question: str
    reference_date: str | None
    question_date: str | None
    secret: bytes
    commitment: str


@dataclass(frozen=True, slots=True)
class _AnswerRequestSnapshot:
    binding: GoldBlindAnswerDispatchBinding
    run_id: str
    case_id: str
    backend_id: str
    question: str
    evidence: tuple[tuple[str, str, int, str | None], ...]
    evidence_identity: str
    reference_date: str | None
    question_date: str | None
    secret: bytes
    commitment: str


@final
class _GoldBlindAnswerRequestIssuer:
    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Answer request issuers must be contract-issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("_GoldBlindAnswerRequestIssuer is final")

    def __repr__(self) -> str:
        return "_GoldBlindAnswerRequestIssuer(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("Answer request issuers are nonserializable")


@final
class GoldBlindAnswerRequest:
    """Issued question/evidence view; public construction is forbidden."""

    __slots__ = (
        "__binding",
        "__integrity_commitment",
        "__weakref__",
        "evidence",
        "question",
        "question_date",
        "reference_date",
    )

    def __init__(
        self,
        *,
        question: str,
        evidence: tuple[GoldBlindEvidence, ...],
        reference_date: str | None,
        question_date: str | None,
        binding: GoldBlindAnswerDispatchBinding,
        integrity_commitment: str,
        _token: object,
    ) -> None:
        if _token is not _TOKEN:
            raise GoldBlindContractError("Answer requests must be issued from retrieval")
        self.question = question
        self.evidence = evidence
        self.reference_date = reference_date
        self.question_date = question_date
        self.__binding = binding
        self.__integrity_commitment = integrity_commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindAnswerRequest is final")

    def __repr__(self) -> str:
        try:
            count = len(self.evidence)
        except Exception:
            count = 0
        return f"GoldBlindAnswerRequest(question=<redacted>, evidence_count={count})"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindAnswerRequest is nonserializable")


_ANSWER_ISSUERS: weakref.WeakKeyDictionary[_GoldBlindAnswerRequestIssuer, _AnswerIssuerSnapshot] = (
    weakref.WeakKeyDictionary()
)
_ANSWER_REQUESTS: weakref.WeakKeyDictionary[GoldBlindAnswerRequest, _AnswerRequestSnapshot] = (
    weakref.WeakKeyDictionary()
)
_LOCK = threading.RLock()


def _create_gold_blind_answer_request_issuer(
    *,
    ledger: GoldBlindRunDispatchLedger,
    run_id: str,
    case_id: str,
    backend_id: str,
    question: str,
    reference_date: str | None,
    question_date: str | None,
) -> _GoldBlindAnswerRequestIssuer:
    """Create one contract-owned issuer from exact registered case fields."""

    validate_provider_text(question, field_name="Answer question")
    _validate_temporal_context(reference_date, question_date)
    try:
        _, expected_backend, _ = _gold_blind_case_dispatch_fields(
            ledger, run_id=run_id, case_id=case_id
        )
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Answer issuer ledger binding failed") from None
    if not hmac.compare_digest(expected_backend, backend_id):
        raise GoldBlindContractError("Answer issuer backend binding failed")
    secret = secrets.token_bytes(32)
    fields = _issuer_integrity_fields(
        run_id=run_id,
        case_id=case_id,
        backend_id=backend_id,
        question=question,
        reference_date=reference_date,
        question_date=question_date,
    )
    commitment = hmac.new(secret, _canonical(fields), hashlib.sha256).hexdigest()
    issuer = _GoldBlindAnswerRequestIssuer(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _ANSWER_ISSUERS[issuer] = _AnswerIssuerSnapshot(
            ledger=ledger,
            run_id=run_id,
            case_id=case_id,
            backend_id=backend_id,
            question=question,
            reference_date=reference_date,
            question_date=question_date,
            secret=secret,
            commitment=commitment,
        )
    return issuer


def _issue_gold_blind_answer_request(
    issuer: _GoldBlindAnswerRequestIssuer,
    evidence: tuple[GoldBlindEvidence, ...],
) -> GoldBlindAnswerRequest:
    """Issue only from a registered contract-owned issuer and retrieval receipt."""

    issuer_snapshot = _answer_issuer_snapshot(issuer)
    evidence_snapshot = validate_gold_blind_evidence(evidence)
    evidence_identity = gold_blind_evidence_identity(evidence)
    try:
        binding = _issue_gold_blind_answer_dispatch_binding(
            issuer_snapshot.ledger,
            run_id=issuer_snapshot.run_id,
            case_id=issuer_snapshot.case_id,
            backend_id=issuer_snapshot.backend_id,
            evidence_identity=evidence_identity,
        )
        run_id, case_id, backend_id, expected_evidence_identity = (
            _gold_blind_answer_dispatch_binding_fields(binding)
        )
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Answer retrieval binding failed") from None
    if not hmac.compare_digest(evidence_identity, expected_evidence_identity):
        raise GoldBlindContractError("Answer evidence does not match retrieval")
    secret = secrets.token_bytes(32)
    fields = _integrity_fields(
        run_id=run_id,
        case_id=case_id,
        backend_id=backend_id,
        question=issuer_snapshot.question,
        evidence=evidence_snapshot,
        evidence_identity=evidence_identity,
        reference_date=issuer_snapshot.reference_date,
        question_date=issuer_snapshot.question_date,
    )
    commitment = hmac.new(secret, _canonical(fields), hashlib.sha256).hexdigest()
    request = GoldBlindAnswerRequest(
        question=issuer_snapshot.question,
        evidence=evidence,
        reference_date=issuer_snapshot.reference_date,
        question_date=issuer_snapshot.question_date,
        binding=binding,
        integrity_commitment=commitment,
        _token=_TOKEN,
    )
    with _LOCK:
        _ANSWER_REQUESTS[request] = _AnswerRequestSnapshot(
            binding,
            run_id,
            case_id,
            backend_id,
            issuer_snapshot.question,
            evidence_snapshot,
            evidence_identity,
            issuer_snapshot.reference_date,
            issuer_snapshot.question_date,
            secret,
            commitment,
        )
    return request


def validate_gold_blind_answer_request(
    request: GoldBlindAnswerRequest,
    ledger: GoldBlindRunDispatchLedger,
    *,
    run_id: str,
    case_id: str,
    backend_id: str,
) -> None:
    """Revalidate all public and hidden DTO state before provider dispatch."""

    if type(request) is not GoldBlindAnswerRequest:
        raise GoldBlindContractError("Answer request must use the exact DTO type")
    with _LOCK:
        snapshot = _ANSWER_REQUESTS.get(request)
    if snapshot is None:
        raise GoldBlindContractError("Answer request integrity registration is missing")
    try:
        current_evidence = validate_gold_blind_evidence(request.evidence)
        current_binding = request._GoldBlindAnswerRequest__binding
        current_commitment = request._GoldBlindAnswerRequest__integrity_commitment
        current_fields = _integrity_fields(
            run_id=snapshot.run_id,
            case_id=snapshot.case_id,
            backend_id=snapshot.backend_id,
            question=request.question,
            evidence=current_evidence,
            evidence_identity=gold_blind_evidence_identity(request.evidence),
            reference_date=request.reference_date,
            question_date=request.question_date,
        )
        expected_commitment = hmac.new(
            snapshot.secret, _canonical(current_fields), hashlib.sha256
        ).hexdigest()
        if (
            current_binding is not snapshot.binding
            or snapshot.run_id != run_id
            or snapshot.case_id != case_id
            or snapshot.backend_id != backend_id
            or current_evidence != snapshot.evidence
            or type(current_commitment) is not str
            or not hmac.compare_digest(current_commitment, snapshot.commitment)
            or not hmac.compare_digest(expected_commitment, snapshot.commitment)
        ):
            raise GoldBlindContractError("Answer request integrity verification failed")
        validate_gold_blind_answer_dispatch_binding(
            current_binding,
            ledger,
            run_id=run_id,
            case_id=case_id,
            backend_id=backend_id,
            evidence_identity=snapshot.evidence_identity,
        )
    except GoldBlindContractError:
        raise
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Answer retrieval binding failed") from None
    except Exception:
        raise GoldBlindContractError("Answer request integrity verification failed") from None


def gold_blind_evidence_identity(evidence: tuple[GoldBlindEvidence, ...]) -> str:
    snapshot = validate_gold_blind_evidence(evidence)
    return hashlib.sha256(_canonical([list(item) for item in snapshot])).hexdigest()


def validate_gold_blind_evidence(
    evidence: object,
) -> tuple[tuple[str, str, int, str | None], ...]:
    if type(evidence) is not tuple:
        raise GoldBlindContractError("Answer evidence must be an exact tuple")
    if len(evidence) > _MAX_EVIDENCE_ITEMS:
        raise GoldBlindContractError("Answer evidence exceeds the item limit")
    total_chars = 0
    snapshot: list[tuple[str, str, int, str | None]] = []
    for item in evidence:
        if type(item) is not GoldBlindEvidence:
            raise GoldBlindContractError("Answer evidence must use exact GoldBlindEvidence")
        _validate_evidence_state(item)
        total_chars += len(item.text)
        if total_chars > _MAX_ANSWER_EVIDENCE_CHARS:
            raise GoldBlindContractError("Answer evidence exceeds the text budget")
        snapshot.append((item.item_id, item.text, item.rank, item.created_at))
    return tuple(snapshot)


def _validate_evidence_state(item: GoldBlindEvidence) -> None:
    validate_provider_text(item.item_id, field_name="Evidence item_id")
    validate_exact_string_length(
        item.text,
        field_name="Evidence text",
        maximum=_MAX_EVIDENCE_TEXT_CHARS,
        allow_empty=True,
    )
    if type(item.rank) is not int or item.rank < 1:
        raise GoldBlindContractError("Evidence rank must be a positive exact integer")
    _validate_temporal_text(item.created_at, field_name="Evidence created_at")


def _validate_temporal_context(reference_date: object, question_date: object) -> None:
    if (reference_date is None) == (question_date is None):
        raise GoldBlindContractError("Answer request requires one exact temporal reference")
    _validate_temporal_text(reference_date, field_name="Answer reference_date")
    _validate_temporal_text(question_date, field_name="Answer question_date", allow_empty=True)


def _validate_temporal_text(value: object, *, field_name: str, allow_empty: bool = False) -> None:
    if value is None:
        return
    validate_exact_string_length(
        value,
        field_name=field_name,
        maximum=_MAX_PROVIDER_TEXT_CHARS,
        allow_empty=allow_empty,
    )
    if value:
        validate_provider_text(value, field_name=field_name)


def _answer_issuer_snapshot(
    issuer: _GoldBlindAnswerRequestIssuer,
) -> _AnswerIssuerSnapshot:
    if type(issuer) is not _GoldBlindAnswerRequestIssuer:
        raise GoldBlindContractError("Answer issuer type must be exact")
    with _LOCK:
        snapshot = _ANSWER_ISSUERS.get(issuer)
    if snapshot is None:
        raise GoldBlindContractError("Answer issuer integrity registration is missing")
    try:
        current = issuer._GoldBlindAnswerRequestIssuer__commitment
        fields = _issuer_integrity_fields(
            run_id=snapshot.run_id,
            case_id=snapshot.case_id,
            backend_id=snapshot.backend_id,
            question=snapshot.question,
            reference_date=snapshot.reference_date,
            question_date=snapshot.question_date,
        )
        expected = hmac.new(snapshot.secret, _canonical(fields), hashlib.sha256).hexdigest()
        if (
            type(current) is not str
            or not hmac.compare_digest(current, snapshot.commitment)
            or not hmac.compare_digest(expected, snapshot.commitment)
        ):
            raise GoldBlindContractError("Answer issuer integrity verification failed")
        _, expected_backend, _ = _gold_blind_case_dispatch_fields(
            snapshot.ledger,
            run_id=snapshot.run_id,
            case_id=snapshot.case_id,
        )
        if not hmac.compare_digest(expected_backend, snapshot.backend_id):
            raise GoldBlindContractError("Answer issuer backend binding failed")
    except GoldBlindContractError:
        raise
    except BaseException:
        raise GoldBlindContractError("Answer issuer integrity verification failed") from None
    return snapshot


def _issuer_integrity_fields(
    *,
    run_id: str,
    case_id: str,
    backend_id: str,
    question: str,
    reference_date: str | None,
    question_date: str | None,
) -> dict[str, object]:
    validate_nonempty_exact_string(run_id, field_name="Answer run_id")
    validate_nonempty_exact_string(case_id, field_name="Answer case_id")
    validate_nonempty_exact_string(backend_id, field_name="Answer backend_id")
    validate_provider_text(question, field_name="Answer question")
    _validate_temporal_context(reference_date, question_date)
    return {
        "schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "run_id": run_id,
        "case_id": case_id,
        "backend_id": backend_id,
        "question": question,
        "reference_date": reference_date,
        "question_date": question_date,
    }


def _integrity_fields(
    *,
    run_id: str,
    case_id: str,
    backend_id: str,
    question: str,
    evidence: tuple[tuple[str, str, int, str | None], ...],
    evidence_identity: str,
    reference_date: str | None,
    question_date: str | None,
) -> dict[str, object]:
    validate_nonempty_exact_string(run_id, field_name="Answer run_id")
    validate_nonempty_exact_string(case_id, field_name="Answer case_id")
    validate_nonempty_exact_string(backend_id, field_name="Answer backend_id")
    return {
        "schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "run_id": run_id,
        "case_id": case_id,
        "backend_id": backend_id,
        "question": question,
        "evidence": [list(item) for item in evidence],
        "evidence_identity": evidence_identity,
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
    ).encode()
