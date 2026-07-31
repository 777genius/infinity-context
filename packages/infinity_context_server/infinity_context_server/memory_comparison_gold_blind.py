"""Project benchmark cases into strict provider-neutral gold-blind capabilities."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import unicodedata
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import final

from infinity_context_server.memory_comparison_gold_blind_answer_contract import (
    ANSWER_REQUEST_SCHEMA_VERSION,
    GoldBlindAnswerRequest,
    GoldBlindEvidence,
    _create_gold_blind_answer_request_issuer,
    _issue_gold_blind_answer_request,
)
from infinity_context_server.memory_comparison_gold_blind_contract import (
    AUDIT_EVIDENCE_SCHEMA_VERSION,
    JUDGE_CHANNEL_KIND,
    ExactGoldJudgeChannel,
    GoldBlindContractError,
    JudgeRunKey,
    canonical_gold_json,
    contains_evaluator_secret,
    create_exact_gold_judge_channel,
    gold_blind_audit_commitment,
    validate_provider_text,
    validate_string_terms,
)
from infinity_context_server.memory_comparison_gold_blind_retrieval_contract import (
    PUBLIC_RETRIEVAL_METADATA_KEYS,
    RETRIEVAL_REQUEST_SCHEMA_VERSION,
    GoldBlindRetrievalRequest,
    _bind_gold_blind_retrieval_request_to_contract,
    _gold_blind_retrieval_snapshot_fields,
    _issue_gold_blind_retrieval_request,
)
from infinity_context_server.memory_comparison_gold_blind_run_proof import (
    GoldBlindRunDispatchLedger,
    GoldBlindRunDispatchProofError,
    _gold_blind_case_dispatch_fields,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkMemoryInput,
    PublicBenchmarkCase,
)

EVALUATOR_GROUND_TRUTH_KEY = "_evaluator_ground_truth"
_KNOWN_PRIVATE_METADATA_KEYS = frozenset(
    {
        EVALUATOR_GROUND_TRUTH_KEY,
        "answer_preview",
        "reference_date",
        "reference_date_human",
    }
)
_SENSITIVE_KEY_FRAGMENTS = (
    "answer",
    "expected",
    "gold",
    "groundtruth",
    "label",
    "oracle",
    "reference",
)


@dataclass(frozen=True, slots=True)
class _CaseContractSnapshot:
    retrieval_request: GoldBlindRetrievalRequest
    answer_issuer: object
    judge_channel: ExactGoldJudgeChannel
    judge_key: JudgeRunKey
    dispatch_ledger: GoldBlindRunDispatchLedger
    run_id: str
    case_id: str
    retrieval_backend_id: str
    answer_backend_id: str
    judge_backend_id: str
    question: str
    reference_date: str | None
    question_date: str | None
    audit_evidence: tuple[tuple[str, object], ...]
    secret: bytes
    commitment: str


_CONTRACT_TOKEN = object()
_CONTRACTS: weakref.WeakKeyDictionary[GoldBlindCaseContract, _CaseContractSnapshot]
_CONTRACT_LOCK = threading.RLock()


@final
class GoldBlindCaseContract:
    """Integrity-snapshotted provider views plus one evaluator-only channel."""

    __slots__ = (
        "__answer_issuer",
        "__audit_evidence",
        "__case_id",
        "__dispatch_ledger",
        "__judge_backend_id",
        "__judge_channel",
        "__judge_key",
        "__question",
        "__question_date",
        "__reference_date",
        "__retrieval_backend_id",
        "__retrieval_request",
        "__run_id",
        "__answer_backend_id",
        "__integrity_commitment",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        retrieval_request: GoldBlindRetrievalRequest,
        answer_issuer: object,
        judge_channel: ExactGoldJudgeChannel,
        judge_key: JudgeRunKey,
        dispatch_ledger: GoldBlindRunDispatchLedger,
        run_id: str,
        case_id: str,
        retrieval_backend_id: str,
        answer_backend_id: str,
        judge_backend_id: str,
        question: str,
        reference_date: str | None,
        question_date: str | None,
        audit_evidence: dict[str, object],
        integrity_commitment: str,
        _token: object,
    ) -> None:
        if _token is not _CONTRACT_TOKEN:
            raise GoldBlindContractError("Case contracts must be issued by the benchmark projector")
        self.__retrieval_request = retrieval_request
        self.__answer_issuer = answer_issuer
        self.__judge_channel = judge_channel
        self.__judge_key = judge_key
        self.__dispatch_ledger = dispatch_ledger
        self.__run_id = run_id
        self.__case_id = case_id
        self.__retrieval_backend_id = retrieval_backend_id
        self.__answer_backend_id = answer_backend_id
        self.__judge_backend_id = judge_backend_id
        self.__question = question
        self.__reference_date = reference_date
        self.__question_date = question_date
        self.__audit_evidence = dict(audit_evidence)
        self.__integrity_commitment = integrity_commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del kwargs
        raise TypeError("GoldBlindCaseContract is final")

    @property
    def retrieval_request(self) -> GoldBlindRetrievalRequest:
        return _case_contract_snapshot(self).retrieval_request

    @property
    def judge_channel(self) -> ExactGoldJudgeChannel:
        return _case_contract_snapshot(self).judge_channel

    def answer_request(
        self,
        evidence: tuple[GoldBlindEvidence, ...],
    ) -> GoldBlindAnswerRequest:
        """Issue from this exact case and its committed retrieval receipt only."""

        snapshot = _case_contract_snapshot(self)
        return _issue_gold_blind_answer_request(snapshot.answer_issuer, evidence)

    def audit_evidence(self) -> dict[str, object]:
        """Return deterministic structural proof without raw gold or labels."""

        snapshot = _case_contract_snapshot(self)
        verified_commitment = gold_blind_audit_commitment(
            key=snapshot.judge_key,
            channel=snapshot.judge_channel,
            run_id=snapshot.run_id,
            case_id=snapshot.case_id,
        )
        evidence = dict(snapshot.audit_evidence)
        recorded_commitment = evidence.get("gold_commitment")
        if type(recorded_commitment) is not str or not hmac.compare_digest(
            recorded_commitment,
            verified_commitment,
        ):
            raise GoldBlindContractError("Contract audit commitment integrity failed")
        return evidence

    def __repr__(self) -> str:
        return "GoldBlindCaseContract(<redacted>, judge_channel=<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("GoldBlindCaseContract contains a nonserializable capability")


_CONTRACTS = weakref.WeakKeyDictionary()


def build_gold_blind_contract(
    case: PublicBenchmarkCase,
    *,
    run_id: str,
    judge_key: JudgeRunKey,
    dispatch_ledger: GoldBlindRunDispatchLedger,
) -> GoldBlindCaseContract:
    """Issue exact provider views bound to the run ledger's backend selection."""

    if type(case) is not PublicBenchmarkCase:
        raise GoldBlindContractError("Gold-blind source case type must be exact")
    validate_provider_text(run_id, field_name="Gold-blind run_id")
    if type(judge_key) is not JudgeRunKey:
        raise GoldBlindContractError("judge_key type must be exact")
    metadata = case.metadata
    if type(metadata) is not dict:
        raise GoldBlindContractError("Case metadata must be an exact dict")
    if EVALUATOR_GROUND_TRUTH_KEY not in metadata:
        raise GoldBlindContractError("Case lacks exact evaluator-only ground truth")

    ground_truth = metadata[EVALUATOR_GROUND_TRUTH_KEY]
    ground_truth_json = canonical_gold_json(ground_truth)
    expected_terms = validate_string_terms(case.expected_terms, field_name="expected_terms")
    forbidden_terms = validate_string_terms(case.forbidden_terms, field_name="forbidden_terms")
    reference_date, question_date = _official_temporal_context(case, metadata)
    public_metadata, excluded_metadata_count = _project_public_metadata(metadata)
    secret_fragments = _secret_fragments(
        ground_truth=ground_truth,
        expected_terms=expected_terms,
        forbidden_terms=forbidden_terms,
    )
    _validate_public_view(
        run_id=run_id,
        benchmark=case.benchmark,
        case_id=case.case_id,
        question=case.question,
        memory_scope_external_ref=case.memory_scope_external_ref,
        thread_external_ref=case.thread_external_ref,
        reference_date=reference_date,
        question_date=question_date,
        public_metadata=public_metadata,
        secret_fragments=secret_fragments,
    )
    try:
        retrieval_backend_id, answer_backend_id, judge_backend_id = (
            _gold_blind_case_dispatch_fields(
                dispatch_ledger,
                run_id=run_id,
                case_id=case.case_id,
            )
        )
    except GoldBlindRunDispatchProofError:
        raise GoldBlindContractError("Case contract ledger binding failed") from None

    request = _issue_gold_blind_retrieval_request(
        ledger=dispatch_ledger,
        run_id=run_id,
        backend_id=retrieval_backend_id,
        benchmark=case.benchmark,
        case_id=case.case_id,
        question=case.question,
        memory_scope_external_ref=case.memory_scope_external_ref,
        thread_external_ref=case.thread_external_ref,
        public_metadata=public_metadata,
        reference_date=reference_date,
        question_date=question_date,
    )
    answer_issuer = _create_gold_blind_answer_request_issuer(
        ledger=dispatch_ledger,
        run_id=run_id,
        case_id=case.case_id,
        backend_id=answer_backend_id,
        question=case.question,
        reference_date=reference_date,
        question_date=question_date,
    )
    channel = create_exact_gold_judge_channel(
        key=judge_key,
        run_id=run_id,
        case_id=case.case_id,
        ground_truth_json=ground_truth_json,
        expected_terms=expected_terms,
        forbidden_terms=forbidden_terms,
    )
    audit_evidence = {
        "schema_version": AUDIT_EVIDENCE_SCHEMA_VERSION,
        "run_id": run_id,
        "case_id": case.case_id,
        "retrieval_schema_version": RETRIEVAL_REQUEST_SCHEMA_VERSION,
        "answer_schema_version": ANSWER_REQUEST_SCHEMA_VERSION,
        "judge_channel": JUDGE_CHANNEL_KIND,
        "gold_commitment": gold_blind_audit_commitment(
            key=judge_key,
            channel=channel,
            run_id=run_id,
            case_id=case.case_id,
        ),
        "excluded_field_count": 5 + excluded_metadata_count,
    }
    secret = secrets.token_bytes(32)
    integrity_fields = _case_integrity_fields(
        run_id=run_id,
        case_id=case.case_id,
        retrieval_backend_id=retrieval_backend_id,
        answer_backend_id=answer_backend_id,
        judge_backend_id=judge_backend_id,
        question=case.question,
        reference_date=reference_date,
        question_date=question_date,
        audit_evidence=audit_evidence,
    )
    commitment = hmac.new(
        secret,
        canonical_gold_json(integrity_fields),
        hashlib.sha256,
    ).hexdigest()
    contract = GoldBlindCaseContract(
        retrieval_request=request,
        answer_issuer=answer_issuer,
        judge_channel=channel,
        judge_key=judge_key,
        dispatch_ledger=dispatch_ledger,
        run_id=run_id,
        case_id=case.case_id,
        retrieval_backend_id=retrieval_backend_id,
        answer_backend_id=answer_backend_id,
        judge_backend_id=judge_backend_id,
        question=case.question,
        reference_date=reference_date,
        question_date=question_date,
        audit_evidence=audit_evidence,
        integrity_commitment=commitment,
        _token=_CONTRACT_TOKEN,
    )
    snapshot = _CaseContractSnapshot(
        retrieval_request=request,
        answer_issuer=answer_issuer,
        judge_channel=channel,
        judge_key=judge_key,
        dispatch_ledger=dispatch_ledger,
        run_id=run_id,
        case_id=case.case_id,
        retrieval_backend_id=retrieval_backend_id,
        answer_backend_id=answer_backend_id,
        judge_backend_id=judge_backend_id,
        question=case.question,
        reference_date=reference_date,
        question_date=question_date,
        audit_evidence=tuple(sorted(audit_evidence.items())),
        secret=secret,
        commitment=commitment,
    )
    with _CONTRACT_LOCK:
        _CONTRACTS[contract] = snapshot
    _bind_gold_blind_retrieval_request_to_contract(
        request,
        contract,
        _validate_gold_blind_case_contract,
    )
    return contract


def _validate_gold_blind_case_contract(contract: object) -> None:
    _case_contract_snapshot(contract)


def _case_contract_snapshot(contract: object) -> _CaseContractSnapshot:
    if type(contract) is not GoldBlindCaseContract:
        raise GoldBlindContractError("Case contract must use the exact issued type")
    with _CONTRACT_LOCK:
        snapshot = _CONTRACTS.get(contract)
    if snapshot is None:
        raise GoldBlindContractError("Case contract integrity registration is missing")
    try:
        evidence = tuple(sorted(dict(contract._GoldBlindCaseContract__audit_evidence).items()))
        retrieval_fields = _gold_blind_retrieval_snapshot_fields(
            contract._GoldBlindCaseContract__retrieval_request
        )
        expected_retrieval, expected_answer, expected_judge = _gold_blind_case_dispatch_fields(
            contract._GoldBlindCaseContract__dispatch_ledger,
            run_id=snapshot.run_id,
            case_id=snapshot.case_id,
        )
        fields = _case_integrity_fields(
            run_id=contract._GoldBlindCaseContract__run_id,
            case_id=contract._GoldBlindCaseContract__case_id,
            retrieval_backend_id=contract._GoldBlindCaseContract__retrieval_backend_id,
            answer_backend_id=contract._GoldBlindCaseContract__answer_backend_id,
            judge_backend_id=contract._GoldBlindCaseContract__judge_backend_id,
            question=contract._GoldBlindCaseContract__question,
            reference_date=contract._GoldBlindCaseContract__reference_date,
            question_date=contract._GoldBlindCaseContract__question_date,
            audit_evidence=dict(evidence),
        )
        expected_commitment = hmac.new(
            snapshot.secret,
            canonical_gold_json(fields),
            hashlib.sha256,
        ).hexdigest()
        current_commitment = contract._GoldBlindCaseContract__integrity_commitment
        if (
            contract._GoldBlindCaseContract__retrieval_request is not snapshot.retrieval_request
            or contract._GoldBlindCaseContract__answer_issuer is not snapshot.answer_issuer
            or contract._GoldBlindCaseContract__judge_channel is not snapshot.judge_channel
            or contract._GoldBlindCaseContract__judge_key is not snapshot.judge_key
            or contract._GoldBlindCaseContract__dispatch_ledger is not snapshot.dispatch_ledger
            or evidence != snapshot.audit_evidence
            or retrieval_fields
            != (
                snapshot.dispatch_ledger,
                snapshot.run_id,
                snapshot.case_id,
                snapshot.retrieval_backend_id,
                snapshot.reference_date,
                snapshot.question_date,
            )
            or expected_retrieval != snapshot.retrieval_backend_id
            or expected_answer != snapshot.answer_backend_id
            or expected_judge != snapshot.judge_backend_id
            or type(current_commitment) is not str
            or not hmac.compare_digest(current_commitment, snapshot.commitment)
            or not hmac.compare_digest(expected_commitment, snapshot.commitment)
        ):
            raise GoldBlindContractError("Case contract integrity verification failed")
    except GoldBlindContractError:
        raise
    except BaseException:
        raise GoldBlindContractError("Case contract integrity verification failed") from None
    return snapshot


def _case_integrity_fields(
    *,
    run_id: str,
    case_id: str,
    retrieval_backend_id: str,
    answer_backend_id: str,
    judge_backend_id: str,
    question: str,
    reference_date: str | None,
    question_date: str | None,
    audit_evidence: dict[str, object],
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "case_id": case_id,
        "retrieval_backend_id": retrieval_backend_id,
        "answer_backend_id": answer_backend_id,
        "judge_backend_id": judge_backend_id,
        "question": question,
        "reference_date": reference_date,
        "question_date": question_date,
        "audit_evidence": audit_evidence,
    }


def _project_public_metadata(metadata: dict[str, object]) -> tuple[dict[str, object], int]:
    public: dict[str, object] = {}
    for key, value in metadata.items():
        if type(key) is not str:
            raise GoldBlindContractError("Metadata keys must be exact strings")
        if key in _KNOWN_PRIVATE_METADATA_KEYS:
            continue
        _reject_nested_sensitive_keys(value, depth=0)
        if _is_sensitive_key(key):
            raise GoldBlindContractError("Ambiguous evaluator metadata alias")
        if key not in PUBLIC_RETRIEVAL_METADATA_KEYS:
            continue
        if not _is_public_scalar(value):
            raise GoldBlindContractError("Public metadata value must be a JSON scalar")
        public[key] = value
    return public, len(metadata) - len(public)


def _reject_nested_sensitive_keys(value: object, *, depth: int) -> None:
    if depth > 12:
        raise GoldBlindContractError("Metadata exceeds the maximum nesting depth")
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise GoldBlindContractError("Nested metadata key must be an exact string")
            if _is_sensitive_key(key):
                raise GoldBlindContractError("Nested evaluator metadata alias")
            _reject_nested_sensitive_keys(nested, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        raise GoldBlindContractError("Nested metadata mappings must be exact dicts")
    if type(value) in (list, tuple):
        for nested in value:
            _reject_nested_sensitive_keys(nested, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        raise GoldBlindContractError("Nested metadata sequences must be exact")


def _official_temporal_context(
    case: PublicBenchmarkCase,
    metadata: dict[str, object],
) -> tuple[str | None, str | None]:
    validate_provider_text(case.benchmark, field_name="Benchmark")
    benchmark = case.benchmark.strip().casefold()
    if benchmark == "locomo":
        return _locomo_reference_date(case, metadata), None
    if benchmark == "longmemeval":
        return None, _longmemeval_question_date(metadata)
    raise GoldBlindContractError("Gold-blind official benchmark is unsupported")


def _locomo_reference_date(
    case: PublicBenchmarkCase,
    metadata: dict[str, object],
) -> str:
    for key in ("reference_date_human", "reference_date"):
        value = _metadata_temporal_text(metadata, key)
        if value:
            return value
    if type(case.memories) is not tuple:
        raise GoldBlindContractError("Benchmark memories must be an exact tuple")
    dated_sessions: list[tuple[datetime, str]] = []
    for memory in case.memories:
        if type(memory) is not BenchmarkMemoryInput or type(memory.metadata) is not dict:
            raise GoldBlindContractError("Benchmark memory temporal source must be exact")
        raw = _metadata_temporal_text(memory.metadata, "session_date")
        for date_format in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
            try:
                parsed = datetime.strptime(raw, date_format)
            except ValueError:
                continue
            dated_sessions.append((parsed, raw))
            break
    return max(dated_sessions, key=lambda item: item[0])[1] if dated_sessions else "2023"


def _longmemeval_question_date(metadata: dict[str, object]) -> str:
    raw = _metadata_temporal_text(metadata, "question_date")
    if not raw:
        return ""
    try:
        cleaned = re.sub(r"\s*\([A-Za-z]+\)\s*", " ", raw).strip()
        parsed = datetime.strptime(cleaned, "%Y/%m/%d %H:%M")
    except ValueError:
        return raw
    return parsed.strftime("%A, %B %d, %Y")


def _metadata_temporal_text(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    if type(value) is not str:
        raise GoldBlindContractError("Benchmark temporal metadata must be an exact string")
    stripped = value.strip()
    if stripped:
        validate_provider_text(stripped, field_name="Benchmark temporal metadata")
    return stripped


def _validate_public_view(
    *,
    run_id: str,
    benchmark: str,
    case_id: str,
    question: str,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
    reference_date: str | None,
    question_date: str | None,
    public_metadata: dict[str, object],
    secret_fragments: tuple[str, ...],
) -> None:
    public_strings: list[object] = [run_id, benchmark, case_id, question]
    public_strings.extend(
        value for value in (memory_scope_external_ref, thread_external_ref) if value is not None
    )
    public_strings.extend(value for value in (reference_date, question_date) if value)
    public_strings.extend(value for value in public_metadata.values() if type(value) is str)
    for value in public_strings:
        if contains_evaluator_secret(value, secret_fragments):
            raise GoldBlindContractError("Public provider view contains evaluator gold")
        validate_provider_text(value, field_name="Public provider field")


def _secret_fragments(
    *,
    ground_truth: object,
    expected_terms: tuple[str, ...],
    forbidden_terms: tuple[str, ...],
) -> tuple[str, ...]:
    fragments = {
        normalized
        for value in (*_json_scalar_strings(ground_truth), *expected_terms, *forbidden_terms)
        if (normalized := _normalize_text(value))
    }
    return tuple(sorted(fragments, key=lambda value: (-len(value), value)))


def _json_scalar_strings(value: object) -> tuple[str, ...]:
    if type(value) is str:
        return (value,)
    if value is None or type(value) is bool:
        return ()
    if type(value) in (int, float):
        return (json.dumps(value, allow_nan=False),)
    if type(value) is list:
        return tuple(item for nested in value for item in _json_scalar_strings(nested))
    if type(value) is dict:
        return tuple(item for nested in value.values() for item in _json_scalar_strings(nested))
    return ()


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _is_public_scalar(value: object) -> bool:
    if value is None or type(value) in (str, bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _strip_format_characters(value)).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", _strip_format_characters(value)).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _strip_format_characters(value: str) -> str:
    return "".join(
        character
        for character in value
        if unicodedata.category(character) != "Cf"
        and ord(character) != 0x034F
        and not 0xFE00 <= ord(character) <= 0xFE0F
    )
