"""Sealed transport-generated timestamp evidence for official LoCoMo ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import weakref
from collections import Counter
from collections.abc import Mapping, Sequence
from threading import RLock
from typing import NamedTuple

from infinity_context_server.memory_comparison_benchmark_identity import (
    mem0_benchmark_user_id,
    valid_benchmark_run_id,
)
from infinity_context_server.memory_comparison_locomo_expected_turn import (
    ExpectedOfficialLocomoTurn,
    trusted_expected_official_locomo_turn,
    validate_official_locomo_turn_projection,
)
from infinity_context_server.public_benchmark_models import BenchmarkValidationError

LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION = "locomo-add-request-producer-projection.v1"
LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA_VERSION = "locomo-timestamp-transport-evidence.v5"
LOCOMO_TIMESTAMP_CONTRACT_SCHEMA_VERSION = "locomo-timestamp-transport-contract.v2"
LOCOMO_OFFICIAL_INGEST_MODE = "official-turns"
_MAX_ID_LENGTH = 512
_EVIDENCE_CONSTRUCTION_SEAL = object()
_KEY_CONSTRUCTION_SEAL = object()
_REQUEST_CONSTRUCTION_SEAL = object()
_KEY_STATE_LOCK = RLock()
_REQUEST_STATE_LOCK = RLock()
_KEY_INTEGRITY_STATE: weakref.WeakKeyDictionary[object, object] = weakref.WeakKeyDictionary()
_REQUEST_INTEGRITY_STATE: weakref.WeakKeyDictionary[object, object] = weakref.WeakKeyDictionary()
_LOCOMO_REQUIRED_METADATA_KEYS = {
    "benchmark",
    "case_id",
    "corpus_key",
    "source_external_id",
    "source_id",
    "session_key",
    "session_date",
    "dia_id",
    "role",
    "speaker",
    "locomo_evidence_ref",
}
_LOCOMO_OPTIONAL_METADATA_KEYS = {"source_timestamp"}
_EVIDENCE_PAYLOAD_KEYS = {
    "schema_version",
    "run_id_sha256",
    "corpus_key_sha256",
    "source_id_sha256",
    "turn_identity_sha256",
    "expected_turn_digest_sha256",
    "trigger_case_id_sha256",
    "ingest_mode",
    "ingestion_payload_count",
    "timestamp_payload_count",
    "request_projection_schema_version",
    "request_digest_sha256",
    "commitment_sha256",
}


class _KeyIntegritySnapshot(NamedTuple):
    run_id: str
    secret: bytes
    commitment: bytes


class _RequestIntegritySnapshot(NamedTuple):
    canonical_bytes: bytes
    commitment: bytes


class LocomoOfficialTurnsTransportRequest:
    """Sealed producer-observed canonical AddRequest projection for one official turn."""

    __slots__ = ("_canonical_bytes", "_seal", "__weakref__")

    def __init__(
        self,
        *,
        canonical_bytes: bytes,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _REQUEST_CONSTRUCTION_SEAL:
            raise TypeError("use LocomoOfficialTurnsTransportRequest.create")
        parsed = _parse_canonical_request_bytes(canonical_bytes)
        del parsed
        self._canonical_bytes = canonical_bytes
        self._seal = _REQUEST_CONSTRUCTION_SEAL
        commitment = hashlib.sha256(
            b"locomo-official-turns-request-integrity\0" + canonical_bytes
        ).digest()
        with _REQUEST_STATE_LOCK:
            _REQUEST_INTEGRITY_STATE[self] = _RequestIntegritySnapshot(
                canonical_bytes=canonical_bytes,
                commitment=commitment,
            )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("LocomoOfficialTurnsTransportRequest is sealed")

    @classmethod
    def create(
        cls,
        *,
        messages: Sequence[Mapping[str, object]],
        user_id: str,
        run_id: str,
        metadata: Mapping[str, object],
        timestamp: int,
        idempotency_key: str,
    ) -> LocomoOfficialTurnsTransportRequest:
        del cls
        if type(messages) not in {list, tuple}:
            raise ValueError("messages must be an exact list or tuple")
        if any(type(message) is not dict for message in messages):
            raise ValueError("messages must contain exact dict records")
        if type(metadata) is not dict:
            raise ValueError("metadata must be an exact dict")
        payload = {
            "messages": list(messages),
            "user_id": user_id,
            "run_id": run_id,
            "metadata": metadata,
            "timestamp": timestamp,
            "idempotency_key": idempotency_key,
        }
        canonical_bytes = _canonical_json_bytes(payload)
        _parse_canonical_request_bytes(canonical_bytes)
        return LocomoOfficialTurnsTransportRequest(
            canonical_bytes=canonical_bytes,
            _construction_seal=_REQUEST_CONSTRUCTION_SEAL,
        )

    def __repr__(self) -> str:
        return "LocomoOfficialTurnsTransportRequest(<sealed>)"

    def __getstate__(self) -> object:
        raise TypeError("official-turn transport requests must never be pickled")


class LocomoTimestampTransportEvidence:
    """Opaque in-memory HMAC evidence issued only at the request transport boundary."""

    __slots__ = (
        "_run_id",
        "_corpus_key",
        "_source_id",
        "_turn_identity_sha256",
        "_expected_turn_digest_sha256",
        "_trigger_case_id_sha256",
        "_ingest_mode",
        "_ingestion_payload_count",
        "_timestamp_payload_count",
        "_request_digest_sha256",
        "_commitment_sha256",
        "_proof",
        "_seal",
    )

    def __init__(
        self,
        *,
        run_id: str,
        corpus_key: str,
        source_id: str,
        turn_identity_sha256: str,
        expected_turn_digest_sha256: str,
        trigger_case_id_sha256: str,
        ingest_mode: str,
        ingestion_payload_count: int,
        timestamp_payload_count: int,
        request_digest_sha256: str,
        commitment_sha256: str,
        proof: bytes,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _EVIDENCE_CONSTRUCTION_SEAL:
            raise TypeError("use RunScopedLocomoTransportEvidenceKey.issue")
        self._run_id = run_id
        self._corpus_key = corpus_key
        self._source_id = source_id
        self._turn_identity_sha256 = turn_identity_sha256
        self._expected_turn_digest_sha256 = expected_turn_digest_sha256
        self._trigger_case_id_sha256 = trigger_case_id_sha256
        self._ingest_mode = ingest_mode
        self._ingestion_payload_count = ingestion_payload_count
        self._timestamp_payload_count = timestamp_payload_count
        self._request_digest_sha256 = request_digest_sha256
        self._commitment_sha256 = commitment_sha256
        self._proof = proof
        self._seal = _EVIDENCE_CONSTRUCTION_SEAL

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("LocomoTimestampTransportEvidence is sealed")

    def __repr__(self) -> str:
        return "LocomoTimestampTransportEvidence(<sealed>)"

    def __getstate__(self) -> object:
        raise TypeError("transport HMAC evidence must never be serialized")


class RunScopedLocomoTransportEvidenceKey:
    """Opaque run-scoped issuer/verifier owned by the HTTP transport adapter."""

    __slots__ = ("_run_id", "_secret", "_seal", "__weakref__")

    def __init__(
        self,
        *,
        run_id: str,
        secret: bytes,
        _construction_seal: object,
    ) -> None:
        if _construction_seal is not _KEY_CONSTRUCTION_SEAL:
            raise TypeError("use RunScopedLocomoTransportEvidenceKey.generate")
        if not valid_benchmark_run_id(run_id):
            raise ValueError("run_id must match the adapter SafeIdentifier contract")
        if type(secret) is not bytes or len(secret) != 32:
            raise ValueError("transport evidence secret must contain exactly 32 bytes")
        self._run_id = run_id
        self._secret = secret
        self._seal = _KEY_CONSTRUCTION_SEAL
        commitment = _key_integrity_commitment(run_id=run_id, secret=secret)
        with _KEY_STATE_LOCK:
            _KEY_INTEGRITY_STATE[self] = _KeyIntegritySnapshot(
                run_id=run_id,
                secret=secret,
                commitment=commitment,
            )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("RunScopedLocomoTransportEvidenceKey is sealed")

    @classmethod
    def generate(cls, *, run_id: str) -> RunScopedLocomoTransportEvidenceKey:
        del cls
        return RunScopedLocomoTransportEvidenceKey(
            run_id=run_id,
            secret=secrets.token_bytes(32),
            _construction_seal=_KEY_CONSTRUCTION_SEAL,
        )

    def issue(
        self,
        request: LocomoOfficialTurnsTransportRequest,
        *,
        expected_turn: ExpectedOfficialLocomoTurn,
        public_trigger_case_id: str | None = None,
    ) -> LocomoTimestampTransportEvidence:
        """Sign evidence only after an exact expected loader projection match."""

        key_state = self._trusted_state()
        if key_state is None:
            raise ValueError("transport evidence key is invalid")
        request_state = _trusted_request_state(request)
        if request_state is None:
            raise ValueError("official-turn transport request is invalid or mutated")
        expected_state = trusted_expected_official_locomo_turn(expected_turn)
        if expected_state is None:
            raise ValueError("expected official LoCoMo turn is invalid or mutated")
        expected_projection, expected_digest = expected_state
        parsed = _parse_canonical_request_bytes(request_state.canonical_bytes)
        if not hmac.compare_digest(parsed["run_id"].encode(), key_state.run_id.encode()):
            raise ValueError("official-turn request run_id differs from immutable key scope")
        metadata = parsed["metadata"]
        message = parsed["messages"][0]
        observed_projection = {
            "run_id": parsed["run_id"],
            "corpus_key": metadata["corpus_key"],
            "source_external_id": metadata["source_external_id"],
            "source_id": metadata["source_id"],
            "session_key": metadata["session_key"],
            "dia_id": metadata["dia_id"],
            "speaker": metadata["speaker"],
            "session_date": metadata["session_date"],
            "trigger_case_id": metadata["case_id"],
            "role": message["role"],
            "content": message["content"],
            "timestamp": parsed["timestamp"],
        }
        if not hmac.compare_digest(
            _canonical_json_bytes(observed_projection),
            _canonical_json_bytes(expected_projection),
        ):
            raise ValueError("observed AddRequest differs from expected official LoCoMo turn")
        corpus_key = metadata["corpus_key"]
        source_id = metadata["source_id"]
        turn_identity_sha256 = _logical_turn_identity_sha256(metadata)
        if public_trigger_case_id is not None and not _bounded_id(public_trigger_case_id):
            raise ValueError("public trigger case_id must be a bounded canonical string")
        public_trigger = public_trigger_case_id or metadata["case_id"]
        trigger_case_id_sha256 = hashlib.sha256(public_trigger.encode()).hexdigest()
        request_digest = hashlib.sha256(request_state.canonical_bytes).hexdigest()
        material = _evidence_material(
            run_id=key_state.run_id,
            corpus_key=corpus_key,
            source_id=source_id,
            turn_identity_sha256=turn_identity_sha256,
            expected_turn_digest_sha256=expected_digest,
            trigger_case_id_sha256=trigger_case_id_sha256,
            ingest_mode=LOCOMO_OFFICIAL_INGEST_MODE,
            ingestion_payload_count=1,
            timestamp_payload_count=1,
            request_digest_sha256=request_digest,
        )
        commitment = hashlib.sha256(material).hexdigest()
        proof = hmac.new(key_state.secret, material, hashlib.sha256).digest()
        return LocomoTimestampTransportEvidence(
            run_id=key_state.run_id,
            corpus_key=corpus_key,
            source_id=source_id,
            turn_identity_sha256=turn_identity_sha256,
            expected_turn_digest_sha256=expected_digest,
            trigger_case_id_sha256=trigger_case_id_sha256,
            ingest_mode=LOCOMO_OFFICIAL_INGEST_MODE,
            ingestion_payload_count=1,
            timestamp_payload_count=1,
            request_digest_sha256=request_digest,
            commitment_sha256=commitment,
            proof=proof,
            _construction_seal=_EVIDENCE_CONSTRUCTION_SEAL,
        )

    def verify(
        self,
        evidence: LocomoTimestampTransportEvidence,
        *,
        expected_run_id: str,
        expected_corpus_key: str,
    ) -> bool:
        key_state = self._trusted_state()
        if (
            key_state is None
            or type(evidence) is not LocomoTimestampTransportEvidence
            or evidence._seal is not _EVIDENCE_CONSTRUCTION_SEAL
            or not valid_benchmark_run_id(expected_run_id)
            or not hmac.compare_digest(expected_run_id.encode(), key_state.run_id.encode())
            or not _bounded_id(expected_corpus_key)
            or evidence._run_id != expected_run_id
            or evidence._corpus_key != expected_corpus_key
            or not _bounded_id(evidence._source_id)
            or not _sha256(evidence._turn_identity_sha256)
            or not _sha256(evidence._expected_turn_digest_sha256)
            or not _sha256(evidence._trigger_case_id_sha256)
            or evidence._ingest_mode != LOCOMO_OFFICIAL_INGEST_MODE
            or type(evidence._ingest_mode) is not str
            or type(evidence._ingestion_payload_count) is not int
            or evidence._ingestion_payload_count != 1
            or type(evidence._timestamp_payload_count) is not int
            or evidence._timestamp_payload_count != 1
            or not _sha256(evidence._request_digest_sha256)
            or not _sha256(evidence._commitment_sha256)
            or type(evidence._proof) is not bytes
            or len(evidence._proof) != 32
        ):
            return False
        material = _evidence_material(
            run_id=evidence._run_id,
            corpus_key=evidence._corpus_key,
            source_id=evidence._source_id,
            turn_identity_sha256=evidence._turn_identity_sha256,
            expected_turn_digest_sha256=evidence._expected_turn_digest_sha256,
            trigger_case_id_sha256=evidence._trigger_case_id_sha256,
            ingest_mode=evidence._ingest_mode,
            ingestion_payload_count=evidence._ingestion_payload_count,
            timestamp_payload_count=evidence._timestamp_payload_count,
            request_digest_sha256=evidence._request_digest_sha256,
        )
        return bool(
            hmac.compare_digest(hashlib.sha256(material).hexdigest(), evidence._commitment_sha256)
            and hmac.compare_digest(
                hmac.new(key_state.secret, material, hashlib.sha256).digest(),
                evidence._proof,
            )
        )

    def _is_sealed(self) -> bool:
        return self._trusted_state() is not None

    def _trusted_state(self) -> _KeyIntegritySnapshot | None:
        if type(self) is not RunScopedLocomoTransportEvidenceKey:
            return None
        with _KEY_STATE_LOCK:
            state = _KEY_INTEGRITY_STATE.get(self)
        if type(state) is not _KeyIntegritySnapshot:
            return None
        try:
            run_id = self._run_id
            secret = self._secret
            seal = self._seal
        except AttributeError:
            return None
        if (
            seal is not _KEY_CONSTRUCTION_SEAL
            or not valid_benchmark_run_id(run_id)
            or type(secret) is not bytes
            or len(secret) != 32
        ):
            return None
        current_commitment = _key_integrity_commitment(run_id=run_id, secret=secret)
        return (
            state
            if hmac.compare_digest(run_id.encode(), state.run_id.encode())
            and hmac.compare_digest(secret, state.secret)
            and hmac.compare_digest(current_commitment, state.commitment)
            else None
        )

    def __repr__(self) -> str:
        return "RunScopedLocomoTransportEvidenceKey(<redacted>)"

    def __getstate__(self) -> object:
        raise TypeError("run-scoped transport evidence keys must never be serialized")


def public_locomo_timestamp_transport_evidence(
    evidence: LocomoTimestampTransportEvidence,
    *,
    verifier: RunScopedLocomoTransportEvidenceKey,
    expected_run_id: str,
    expected_corpus_key: str,
) -> dict[str, object]:
    """Return an exact safe projection only after live HMAC revalidation."""

    if type(verifier) is not RunScopedLocomoTransportEvidenceKey or not verifier.verify(
        evidence,
        expected_run_id=expected_run_id,
        expected_corpus_key=expected_corpus_key,
    ):
        raise BenchmarkValidationError("LoCoMo timestamp transport evidence is invalid")
    return {
        "schema_version": LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA_VERSION,
        "run_id_sha256": hashlib.sha256(expected_run_id.encode()).hexdigest(),
        "corpus_key_sha256": hashlib.sha256(expected_corpus_key.encode()).hexdigest(),
        "source_id_sha256": hashlib.sha256(evidence._source_id.encode()).hexdigest(),
        "turn_identity_sha256": evidence._turn_identity_sha256,
        "expected_turn_digest_sha256": evidence._expected_turn_digest_sha256,
        "trigger_case_id_sha256": evidence._trigger_case_id_sha256,
        "ingest_mode": evidence._ingest_mode,
        "ingestion_payload_count": evidence._ingestion_payload_count,
        "timestamp_payload_count": evidence._timestamp_payload_count,
        "request_projection_schema_version": LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION,
        "request_digest_sha256": evidence._request_digest_sha256,
        "commitment_sha256": evidence._commitment_sha256,
    }


def locomo_timestamp_evidence_payload_is_exact(payload: object) -> bool:
    if type(payload) is not dict or set(payload) != _EVIDENCE_PAYLOAD_KEYS:
        return False
    return bool(
        payload["schema_version"] == LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA_VERSION
        and type(payload["schema_version"]) is str
        and _sha256(payload["run_id_sha256"])
        and _sha256(payload["corpus_key_sha256"])
        and _sha256(payload["source_id_sha256"])
        and _sha256(payload["turn_identity_sha256"])
        and _sha256(payload["expected_turn_digest_sha256"])
        and _sha256(payload["trigger_case_id_sha256"])
        and payload["ingest_mode"] == LOCOMO_OFFICIAL_INGEST_MODE
        and type(payload["ingest_mode"]) is str
        and type(payload["ingestion_payload_count"]) is int
        and payload["ingestion_payload_count"] == 1
        and type(payload["timestamp_payload_count"]) is int
        and payload["timestamp_payload_count"] == 1
        and payload["request_projection_schema_version"]
        == LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION
        and type(payload["request_projection_schema_version"]) is str
        and _sha256(payload["request_digest_sha256"])
        and _sha256(payload["commitment_sha256"])
    )


def locomo_timestamp_transport_contract(
    *,
    benchmark: str,
    evaluations: Sequence[Mapping[str, object]],
    declared_sent: bool | None,
    run_id: str | None = None,
    verifier: RunScopedLocomoTransportEvidenceKey | None = None,
    timestamp_evidence: Sequence[LocomoTimestampTransportEvidence] = (),
) -> dict[str, object]:
    """Cross-check exact corpus observations against sealed transport evidence."""

    if type(benchmark) is not str or benchmark not in {"locomo", "longmemeval"}:
        raise BenchmarkValidationError("benchmark must be exactly locomo or longmemeval")
    if declared_sent is not None and type(declared_sent) is not bool:
        raise BenchmarkValidationError("declared_sent must be an exact boolean or None")
    evaluation_values = _exact_evaluation_sequence(evaluations)
    evidence_values = _exact_evidence_sequence(timestamp_evidence)
    if benchmark == "longmemeval":
        exact_not_required = bool(
            declared_sent is None
            and run_id is None
            and verifier is None
            and not evidence_values
            and all(item.get("benchmark") == "longmemeval" for item in evaluation_values)
        )
        return {
            "schema_version": LOCOMO_TIMESTAMP_CONTRACT_SCHEMA_VERSION,
            "required": False,
            "declared_sent": declared_sent,
            "observed_evaluation_count": 0,
            "observed_corpus_count": 0,
            "evidence_count": 0,
            "ingestion_payload_count": 0,
            "timestamp_payload_count": 0,
            "timestamp_attested_evaluation_count": 0,
            "issues": [] if exact_not_required else ["longmemeval_transport_state_not_exact"],
            "evidence": [],
            "matches": exact_not_required,
        }

    issues: Counter[str] = Counter()
    if declared_sent is not True:
        issues["declared_sent_not_exact_true"] += 1
    if not valid_benchmark_run_id(run_id):
        issues["run_id_invalid"] += 1
    trusted_verifier = (
        verifier
        if type(verifier) is RunScopedLocomoTransportEvidenceKey and verifier._is_sealed()
        else None
    )
    if trusted_verifier is None:
        issues["live_verifier_invalid"] += 1

    corpus_keys: list[str] = []
    mem0_evaluation_count = 0
    for item in evaluation_values:
        if item.get("benchmark") != "locomo":
            issues["evaluation_benchmark_mismatch"] += 1
            continue
        if item.get("backend") != "mem0":
            continue
        mem0_evaluation_count += 1
        corpus_key = _exact_corpus_key(item)
        if corpus_key is None:
            issues["corpus_key_invalid"] += 1
        else:
            corpus_keys.append(corpus_key)
    expected_corpora = set(corpus_keys)
    if not expected_corpora:
        issues["missing_expected_corpus"] += 1

    observed_source_identities: set[tuple[str, str, str]] = set()
    observed_turn_identities: set[tuple[str, str, str]] = set()
    observed_evidence_corpora: set[str] = set()
    public_evidence: list[dict[str, object]] = []
    for evidence in evidence_values:
        evidence_run_id = evidence._run_id if type(evidence._run_id) is str else ""
        corpus_key = evidence._corpus_key if type(evidence._corpus_key) is str else ""
        source_id = evidence._source_id if type(evidence._source_id) is str else ""
        turn_identity = (
            evidence._turn_identity_sha256 if type(evidence._turn_identity_sha256) is str else ""
        )
        source_identity = (evidence_run_id, corpus_key, source_id)
        turn_identity_key = (evidence_run_id, corpus_key, turn_identity)
        if (
            source_identity in observed_source_identities
            or turn_identity_key in observed_turn_identities
        ):
            issues["duplicate_logical_turn_evidence"] += 1
            continue
        observed_source_identities.add(source_identity)
        observed_turn_identities.add(turn_identity_key)
        observed_evidence_corpora.add(corpus_key)
        if corpus_key not in expected_corpora:
            issues["unexpected_corpus_evidence"] += 1
            continue
        if (
            trusted_verifier is None
            or run_id is None
            or not trusted_verifier.verify(
                evidence,
                expected_run_id=run_id,
                expected_corpus_key=corpus_key,
            )
        ):
            issues["invalid_corpus_evidence"] += 1
            continue
        projection = public_locomo_timestamp_transport_evidence(
            evidence,
            verifier=trusted_verifier,
            expected_run_id=run_id,
            expected_corpus_key=corpus_key,
        )
        if not locomo_timestamp_evidence_payload_is_exact(projection):
            issues["invalid_evidence_projection"] += 1
            continue
        if evidence._timestamp_payload_count != evidence._ingestion_payload_count:
            issues["timestamp_count_mismatch"] += 1
        public_evidence.append(projection)

    missing = expected_corpora - observed_evidence_corpora
    if missing:
        issues["missing_corpus_evidence"] += len(missing)
    valid_corpus_hashes = {item["corpus_key_sha256"] for item in public_evidence}
    attested_evaluation_count = sum(
        1
        for corpus_key in corpus_keys
        if hashlib.sha256(corpus_key.encode()).hexdigest() in valid_corpus_hashes
    )
    ingestion_count = sum(int(item["ingestion_payload_count"]) for item in public_evidence)
    timestamp_count = sum(int(item["timestamp_payload_count"]) for item in public_evidence)
    return {
        "schema_version": LOCOMO_TIMESTAMP_CONTRACT_SCHEMA_VERSION,
        "required": True,
        "declared_sent": declared_sent,
        "observed_evaluation_count": mem0_evaluation_count,
        "observed_corpus_count": len(expected_corpora),
        "evidence_count": len(public_evidence),
        "ingestion_payload_count": ingestion_count,
        "timestamp_payload_count": timestamp_count,
        "timestamp_attested_evaluation_count": attested_evaluation_count,
        "issues": [
            {"code": code, "count": count} for code, count in sorted(issues.items()) if count
        ],
        "evidence": sorted(public_evidence, key=lambda item: str(item["corpus_key_sha256"])),
        "matches": not issues,
    }


def _exact_evaluation_sequence(value: object) -> tuple[dict[str, object], ...]:
    if type(value) not in {tuple, list}:
        raise BenchmarkValidationError("evaluations must be an exact list or tuple")
    if any(type(item) is not dict for item in value):
        raise BenchmarkValidationError("evaluations must contain exact dict values")
    return tuple(value)


def _exact_evidence_sequence(
    value: object,
) -> tuple[LocomoTimestampTransportEvidence, ...]:
    if type(value) not in {tuple, list}:
        raise BenchmarkValidationError("timestamp_evidence must be an exact list or tuple")
    if any(type(item) is not LocomoTimestampTransportEvidence for item in value):
        raise BenchmarkValidationError("timestamp_evidence contains an invalid sealed type")
    return tuple(value)


def _exact_corpus_key(item: dict[str, object]) -> str | None:
    if "ingestion" not in item or type(item["ingestion"]) is not dict:
        return None
    ingestion = item["ingestion"]
    if "metadata" not in ingestion or type(ingestion["metadata"]) is not dict:
        return None
    metadata = ingestion["metadata"]
    if "corpus_key" not in metadata:
        return None
    corpus_key = metadata["corpus_key"]
    return corpus_key if _bounded_id(corpus_key) else None


def _trusted_request_state(
    request: object,
) -> _RequestIntegritySnapshot | None:
    if type(request) is not LocomoOfficialTurnsTransportRequest:
        return None
    with _REQUEST_STATE_LOCK:
        state = _REQUEST_INTEGRITY_STATE.get(request)
    if type(state) is not _RequestIntegritySnapshot:
        return None
    try:
        canonical_bytes = request._canonical_bytes
        seal = request._seal
    except AttributeError:
        return None
    if (
        seal is not _REQUEST_CONSTRUCTION_SEAL
        or type(canonical_bytes) is not bytes
        or not canonical_bytes
    ):
        return None
    commitment = hashlib.sha256(
        b"locomo-official-turns-request-integrity\0" + canonical_bytes
    ).digest()
    return (
        state
        if hmac.compare_digest(canonical_bytes, state.canonical_bytes)
        and hmac.compare_digest(commitment, state.commitment)
        else None
    )


def _parse_canonical_request_bytes(payload: object) -> dict[str, object]:
    if type(payload) is not bytes or not payload:
        raise ValueError("canonical AddRequest projection must be non-empty exact bytes")
    try:
        parsed = json.loads(payload, object_pairs_hook=_exact_json_object_pairs)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise ValueError("canonical AddRequest projection is malformed") from error
    if type(parsed) is not dict or set(parsed) != {
        "messages",
        "user_id",
        "run_id",
        "metadata",
        "timestamp",
        "idempotency_key",
    }:
        raise ValueError("canonical AddRequest projection fields are not exact")
    if _canonical_json_bytes(parsed) != payload:
        raise ValueError("AddRequest projection bytes are not canonical")
    run_id = parsed["run_id"]
    if not valid_benchmark_run_id(run_id):
        raise ValueError("AddRequest run_id must match the adapter SafeIdentifier contract")
    expected_user_id = mem0_benchmark_user_id(run_id)
    if type(parsed["user_id"]) is not str or not hmac.compare_digest(
        parsed["user_id"].encode(), expected_user_id.encode()
    ):
        raise ValueError("AddRequest user_id does not match the canonical benchmark run user")
    metadata = parsed["metadata"]
    if type(metadata) is not dict:
        raise ValueError("AddRequest metadata must be an exact object")
    metadata_keys = set(metadata)
    if not metadata_keys.issuperset(_LOCOMO_REQUIRED_METADATA_KEYS) or not metadata_keys.issubset(
        _LOCOMO_REQUIRED_METADATA_KEYS | _LOCOMO_OPTIONAL_METADATA_KEYS
    ):
        raise ValueError("AddRequest metadata fields are not the exact LoCoMo turn schema")
    if metadata["benchmark"] != "locomo" or type(metadata["benchmark"]) is not str:
        raise ValueError("AddRequest metadata.benchmark must be exactly locomo")
    for key in _LOCOMO_REQUIRED_METADATA_KEYS - {"benchmark"}:
        if not _bounded_id(metadata[key]):
            raise ValueError(f"AddRequest metadata.{key} must be a bounded canonical string")
    if metadata["locomo_evidence_ref"] != metadata["dia_id"]:
        raise ValueError("LoCoMo evidence ref must equal dia_id")
    idempotency_key = parsed["idempotency_key"]
    if idempotency_key != metadata["source_id"]:
        raise ValueError("Idempotency-Key must equal LoCoMo metadata.source_id")
    timestamp = parsed["timestamp"]
    if "source_timestamp" in metadata and (
        type(metadata["source_timestamp"]) is not int or metadata["source_timestamp"] != timestamp
    ):
        raise ValueError("metadata.source_timestamp must equal the AddRequest timestamp")
    messages = parsed["messages"]
    if type(messages) is not list or len(messages) != 1:
        raise ValueError("official LoCoMo AddRequest must contain exactly one turn message")
    message = messages[0]
    if type(message) is not dict or set(message) != {"role", "content"}:
        raise ValueError("AddRequest message fields must be exactly role and content")
    if metadata["role"] != message["role"]:
        raise ValueError("LoCoMo metadata role must equal the single message role")
    validate_official_locomo_turn_projection(
        {
            "run_id": run_id,
            "corpus_key": metadata["corpus_key"],
            "source_external_id": metadata["source_external_id"],
            "source_id": metadata["source_id"],
            "session_key": metadata["session_key"],
            "dia_id": metadata["dia_id"],
            "speaker": metadata["speaker"],
            "session_date": metadata["session_date"],
            "trigger_case_id": metadata["case_id"],
            "role": message["role"],
            "content": message["content"],
            "timestamp": timestamp,
        }
    )
    return parsed


def _exact_json_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("AddRequest projection must contain exact JSON values") from error


def _key_integrity_commitment(*, run_id: str, secret: bytes) -> bytes:
    material = _canonical_json_bytes(
        {
            "schema_version": "locomo-run-scoped-evidence-key.v1",
            "run_id": run_id,
        }
    )
    return hmac.new(secret, material, hashlib.sha256).digest()


def _evidence_material(
    *,
    run_id: str,
    corpus_key: str,
    source_id: str,
    turn_identity_sha256: str,
    expected_turn_digest_sha256: str,
    ingest_mode: str,
    trigger_case_id_sha256: str,
    ingestion_payload_count: int,
    timestamp_payload_count: int,
    request_digest_sha256: str,
) -> bytes:
    return json.dumps(
        {
            "schema_version": LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA_VERSION,
            "run_id": run_id,
            "corpus_key": corpus_key,
            "source_id": source_id,
            "turn_identity_sha256": turn_identity_sha256,
            "expected_turn_digest_sha256": expected_turn_digest_sha256,
            "trigger_case_id_sha256": trigger_case_id_sha256,
            "ingest_mode": ingest_mode,
            "ingestion_payload_count": ingestion_payload_count,
            "timestamp_payload_count": timestamp_payload_count,
            "request_digest_sha256": request_digest_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _logical_turn_identity_sha256(metadata: dict[str, object]) -> str:
    material = _canonical_json_bytes(
        {
            "corpus_key": metadata["corpus_key"],
            "session_key": metadata["session_key"],
            "dia_id": metadata["dia_id"],
        }
    )
    return hashlib.sha256(material).hexdigest()


def _bounded_id(value: object) -> bool:
    return bool(type(value) is str and 0 < len(value) <= _MAX_ID_LENGTH and value == value.strip())


def _sha256(value: object) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = (
    "LOCOMO_ADD_REQUEST_PROJECTION_SCHEMA_VERSION",
    "LOCOMO_OFFICIAL_INGEST_MODE",
    "LOCOMO_TIMESTAMP_CONTRACT_SCHEMA_VERSION",
    "LOCOMO_TIMESTAMP_EVIDENCE_SCHEMA_VERSION",
    "LocomoOfficialTurnsTransportRequest",
    "LocomoTimestampTransportEvidence",
    "RunScopedLocomoTransportEvidenceKey",
    "locomo_timestamp_evidence_payload_is_exact",
    "locomo_timestamp_transport_contract",
    "public_locomo_timestamp_transport_evidence",
)
