"""Authenticated clean-state evidence for benchmark publication gates."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

_SCHEMA_VERSION = "memory-comparison-clean-state-v2"
_REQUIRED_BACKENDS = ("infinity-context", "mem0")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MIN_KEY_BYTES = 32
_PROOF_KEYS = frozenset(
    {
        "backend",
        "strategy",
        "run_id_sha256",
        "corpus_identity_sha256",
        "scope_identity_sha256",
        "expected_scope_count",
        "http_status_code",
        "verified",
        "reason_code",
        "deleted",
        "verified_absent",
        "attestation_hmac_sha256",
    }
)
_BACKEND_CONTRACT_KEYS = frozenset(
    {"expected_scope_count", "observed_scope_count", "proofs", "verified"}
)
_TOP_LEVEL_CONTRACT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "eligible",
        "expected_run_id_sha256",
        "backends",
        "issues",
    }
)


class CleanStateProofError(RuntimeError):
    """Raised when a backend cannot produce bounded clean-state evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BackendCleanStateProof:
    """Serializable evidence authenticated by a run-scoped HMAC key."""

    backend: str
    strategy: str
    run_id_sha256: str
    corpus_identity_sha256: str
    scope_identity_sha256: str
    expected_scope_count: int
    http_status_code: int | None
    verified: bool
    reason_code: str | None
    deleted: bool | None
    verified_absent: bool | None
    attestation_hmac_sha256: str


class ResetProofPort(Protocol):
    """Narrow reset capability, separate from the retrieval backend port."""

    clean_state_backend_role: str

    def reset_for_clean_state(
        self, *, run_id: str, attestation_key: bytes
    ) -> BackendCleanStateProof:
        """Reset one backend and return authenticated evidence."""


class CleanStateBackendPort(Protocol):
    """Narrow completed-ingestion proof capability."""

    clean_state_backend_role: str

    def clean_state_proofs(self) -> tuple[BackendCleanStateProof, ...]:
        """Return proofs used by completed ingestion operations."""


@dataclass(frozen=True, slots=True)
class VerifiedCleanStateValidation:
    """Result whose evidence must still be reverified before publication."""

    payload: Mapping[str, object]

    @property
    def eligible(self) -> bool:
        return self.payload.get("eligible") is True


def clean_state_identity_sha256(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("clean_state_identity_must_be_non_empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validated_key(attestation_key: bytes) -> bytes:
    if not isinstance(attestation_key, bytes) or len(attestation_key) < _MIN_KEY_BYTES:
        raise CleanStateProofError("clean_state_attestation_key_invalid")
    return attestation_key


def _proof_message(proof: BackendCleanStateProof) -> bytes:
    body = {
        "backend": proof.backend,
        "corpus_identity_sha256": proof.corpus_identity_sha256,
        "deleted": proof.deleted,
        "expected_scope_count": proof.expected_scope_count,
        "http_status_code": proof.http_status_code,
        "reason_code": proof.reason_code,
        "run_id_sha256": proof.run_id_sha256,
        "schema_version": _SCHEMA_VERSION,
        "scope_identity_sha256": proof.scope_identity_sha256,
        "strategy": proof.strategy,
        "verified": proof.verified,
        "verified_absent": proof.verified_absent,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def _signed_proof(
    *,
    backend: str,
    strategy: str,
    run_id: str,
    corpus_identity_sha256: str,
    scope_identity_sha256: str,
    expected_scope_count: int,
    http_status_code: int | None,
    verified: bool,
    reason_code: str | None,
    deleted: bool | None,
    verified_absent: bool | None,
    attestation_key: bytes,
) -> BackendCleanStateProof:
    key = _validated_key(attestation_key)
    if http_status_code is not None and (
        isinstance(http_status_code, bool) or not isinstance(http_status_code, int)
    ):
        raise CleanStateProofError("clean_state_http_status_invalid")
    if not _SHA256_RE.fullmatch(corpus_identity_sha256):
        raise CleanStateProofError("clean_state_corpus_identity_invalid")
    if not _SHA256_RE.fullmatch(scope_identity_sha256):
        raise CleanStateProofError("clean_state_scope_identity_invalid")
    if (
        isinstance(expected_scope_count, bool)
        or not isinstance(expected_scope_count, int)
        or expected_scope_count < 1
    ):
        raise CleanStateProofError("clean_state_expected_scope_count_invalid")
    unsigned = BackendCleanStateProof(
        backend=backend,
        strategy=strategy,
        run_id_sha256=clean_state_identity_sha256(run_id),
        corpus_identity_sha256=corpus_identity_sha256,
        scope_identity_sha256=scope_identity_sha256,
        expected_scope_count=expected_scope_count,
        http_status_code=http_status_code,
        verified=verified,
        reason_code=reason_code,
        deleted=deleted,
        verified_absent=verified_absent,
        attestation_hmac_sha256="",
    )
    signature = hmac.new(key, _proof_message(unsigned), hashlib.sha256).hexdigest()
    return BackendCleanStateProof(**{**asdict(unsigned), "attestation_hmac_sha256": signature})


def fresh_namespace_clean_state_proof(
    *,
    backend: str,
    run_id: str,
    expected_slug: str,
    corpus_identity_sha256: str,
    expected_scope_count: int,
    status_code: int,
    payload: object,
    attestation_key: bytes,
) -> BackendCleanStateProof:
    if status_code != 201 or not isinstance(payload, Mapping) or set(payload) != {"data"}:
        raise CleanStateProofError("clean_state_namespace_ack_invalid")
    data = payload["data"]
    if not isinstance(data, Mapping) or data.get("slug") != expected_slug:
        raise CleanStateProofError("clean_state_namespace_ack_invalid")
    return _signed_proof(
        backend=backend,
        strategy="fresh_namespace",
        run_id=run_id,
        corpus_identity_sha256=corpus_identity_sha256,
        scope_identity_sha256=clean_state_identity_sha256(expected_slug),
        expected_scope_count=expected_scope_count,
        http_status_code=status_code,
        verified=True,
        reason_code=None,
        deleted=None,
        verified_absent=None,
        attestation_key=attestation_key,
    )


def mem0_delete_clean_state_proof(
    *,
    run_id: str,
    scope_identity: str,
    corpus_identity_sha256: str,
    expected_scope_count: int,
    status_code: int,
    payload: object,
    attestation_key: bytes,
) -> BackendCleanStateProof:
    if (
        status_code != 200
        or not isinstance(payload, Mapping)
        or set(payload) != {"deleted", "verified_absent"}
    ):
        raise CleanStateProofError("mem0_delete_ack_invalid")
    if payload["deleted"] is not True or payload["verified_absent"] is not True:
        raise CleanStateProofError("mem0_delete_ack_invalid")
    return _signed_proof(
        backend="mem0",
        strategy="delete_readback",
        run_id=run_id,
        corpus_identity_sha256=corpus_identity_sha256,
        scope_identity_sha256=clean_state_identity_sha256(scope_identity),
        expected_scope_count=expected_scope_count,
        http_status_code=status_code,
        verified=True,
        reason_code=None,
        deleted=True,
        verified_absent=True,
        attestation_key=attestation_key,
    )


def skipped_mem0_clean_state_proof(
    *,
    run_id: str,
    scope_identity: str,
    corpus_identity_sha256: str,
    expected_scope_count: int,
    attestation_key: bytes,
) -> BackendCleanStateProof:
    return _signed_proof(
        backend="mem0",
        strategy="reset_skipped",
        run_id=run_id,
        corpus_identity_sha256=corpus_identity_sha256,
        scope_identity_sha256=clean_state_identity_sha256(scope_identity),
        expected_scope_count=expected_scope_count,
        http_status_code=None,
        verified=False,
        reason_code="mem0_reset_disabled",
        deleted=None,
        verified_absent=None,
        attestation_key=attestation_key,
    )


def _signature_is_valid(proof: BackendCleanStateProof, key: bytes) -> bool:
    try:
        key = _validated_key(key)
    except CleanStateProofError:
        return False
    if not _SHA256_RE.fullmatch(proof.attestation_hmac_sha256):
        return False
    expected = hmac.new(key, _proof_message(proof), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, proof.attestation_hmac_sha256)


def reset_proof_is_valid(
    proof: object,
    *,
    expected_backend: str,
    expected_run_id_sha256: str,
    attestation_key: bytes,
    require_verified: bool,
) -> bool:
    if type(proof) is not BackendCleanStateProof:
        return False
    assert isinstance(proof, BackendCleanStateProof)
    if expected_backend not in _REQUIRED_BACKENDS:
        return False
    if proof.backend != expected_backend or proof.run_id_sha256 != expected_run_id_sha256:
        return False
    if not _SHA256_RE.fullmatch(proof.corpus_identity_sha256):
        return False
    if not _SHA256_RE.fullmatch(proof.scope_identity_sha256):
        return False
    if proof.http_status_code is not None and (
        isinstance(proof.http_status_code, bool) or not isinstance(proof.http_status_code, int)
    ):
        return False
    if (
        isinstance(proof.expected_scope_count, bool)
        or not isinstance(proof.expected_scope_count, int)
        or proof.expected_scope_count < 1
        or not _signature_is_valid(proof, attestation_key)
    ):
        return False
    if require_verified and proof.verified is not True:
        return False
    if proof.verified is True:
        if proof.reason_code is not None:
            return False
        if proof.backend == "infinity-context" and not (
            proof.strategy == "fresh_namespace"
            and proof.http_status_code == 201
            and proof.deleted is None
            and proof.verified_absent is None
        ):
            return False
        if proof.backend == "mem0" and not (
            proof.strategy == "delete_readback"
            and proof.http_status_code == 200
            and proof.deleted is True
            and proof.verified_absent is True
        ):
            return False
    elif not (
        proof.backend == "mem0"
        and proof.strategy == "reset_skipped"
        and proof.http_status_code is None
        and proof.reason_code == "mem0_reset_disabled"
        and proof.deleted is None
        and proof.verified_absent is None
    ):
        return False
    return True


def _normalize_expectations(
    value: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    issues: list[str] = []
    if set(value) != set(_REQUIRED_BACKENDS):
        issues.append("clean_state_expected_backend_set_invalid")
    result: dict[str, dict[str, str]] = {}
    for backend in _REQUIRED_BACKENDS:
        raw = value.get(backend)
        if not isinstance(raw, Mapping) or not raw:
            issues.append(f"{backend}:clean_state_expected_scopes_invalid")
            result[backend] = {}
            continue
        scopes: dict[str, str] = {}
        for corpus_hash, scope_hash in raw.items():
            if not isinstance(corpus_hash, str) or not _SHA256_RE.fullmatch(corpus_hash):
                issues.append(f"{backend}:clean_state_expected_corpus_invalid")
                continue
            if not isinstance(scope_hash, str) or not _SHA256_RE.fullmatch(scope_hash):
                issues.append(f"{backend}:clean_state_expected_scope_invalid")
                continue
            scopes[corpus_hash] = scope_hash
        if len(set(scopes.values())) != len(scopes):
            issues.append(f"{backend}:clean_state_expected_scope_duplicate")
        result[backend] = scopes
    return result, issues


def public_clean_state_proof(proof: BackendCleanStateProof) -> dict[str, object]:
    return asdict(proof) if type(proof) is BackendCleanStateProof else {}


def validate_typed_clean_state_proofs(
    proofs_by_backend: Mapping[str, Sequence[BackendCleanStateProof]],
    *,
    expected_run_id_sha256: str,
    expected_scopes_by_backend: Mapping[str, Mapping[str, str]],
    attestation_key: bytes,
) -> VerifiedCleanStateValidation:
    expected, issues = _normalize_expectations(expected_scopes_by_backend)
    if not _SHA256_RE.fullmatch(expected_run_id_sha256):
        issues.append("clean_state_expected_run_invalid")
    if set(proofs_by_backend) != set(_REQUIRED_BACKENDS):
        issues.append("clean_state_backend_set_invalid")
    backend_payloads: dict[str, object] = {}
    for backend in _REQUIRED_BACKENDS:
        expected_scopes = expected[backend]
        observed: dict[str, str] = {}
        public_proofs: list[dict[str, object]] = []
        for proof in proofs_by_backend.get(backend, ()):
            if type(proof) is not BackendCleanStateProof:
                issues.append(f"{backend}:clean_state_proof_not_typed")
                continue
            public_proofs.append(public_clean_state_proof(proof))
            if not reset_proof_is_valid(
                proof,
                expected_backend=backend,
                expected_run_id_sha256=expected_run_id_sha256,
                attestation_key=attestation_key,
                require_verified=True,
            ):
                issues.append(f"{backend}:clean_state_proof_invalid")
                continue
            if proof.expected_scope_count != len(expected_scopes):
                issues.append(f"{backend}:clean_state_expected_count_mismatch")
            if proof.corpus_identity_sha256 in observed:
                issues.append(f"{backend}:clean_state_corpus_duplicate")
            observed[proof.corpus_identity_sha256] = proof.scope_identity_sha256
        if observed != expected_scopes:
            issues.append(f"{backend}:clean_state_scope_set_mismatch")
        backend_payloads[backend] = {
            "expected_scope_count": len(expected_scopes),
            "observed_scope_count": len(observed),
            "proofs": tuple(public_proofs),
            "verified": observed == expected_scopes
            and not any(issue.startswith(f"{backend}:") for issue in issues),
        }
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "status": "verified" if not issues else "invalid",
        "eligible": not issues,
        "expected_run_id_sha256": expected_run_id_sha256,
        "backends": backend_payloads,
        "issues": tuple(sorted(set(issues))),
    }
    return VerifiedCleanStateValidation(payload)


def public_clean_state_validation(validation: object) -> dict[str, object]:
    if type(validation) is not VerifiedCleanStateValidation:
        return {}
    assert isinstance(validation, VerifiedCleanStateValidation)
    return dict(validation.payload)


def _proof_from_mapping(value: object) -> BackendCleanStateProof | None:
    if not isinstance(value, Mapping) or set(value) != _PROOF_KEYS:
        return None
    try:
        count = value["expected_scope_count"]
        status_code = value["http_status_code"]
        verified = value["verified"]
        deleted = value["deleted"]
        absent = value["verified_absent"]
        reason = value["reason_code"]
        if isinstance(count, bool) or not isinstance(count, int):
            return None
        if status_code is not None and (
            isinstance(status_code, bool) or not isinstance(status_code, int)
        ):
            return None
        if not isinstance(verified, bool):
            return None
        if deleted is not None and not isinstance(deleted, bool):
            return None
        if absent is not None and not isinstance(absent, bool):
            return None
        if reason is not None and not isinstance(reason, str):
            return None
        names = (
            "backend",
            "strategy",
            "run_id_sha256",
            "corpus_identity_sha256",
            "scope_identity_sha256",
            "attestation_hmac_sha256",
        )
        strings = {name: value[name] for name in names}
        if not all(isinstance(item, str) for item in strings.values()):
            return None
        return BackendCleanStateProof(
            **strings,
            expected_scope_count=count,
            http_status_code=status_code,
            verified=verified,
            reason_code=reason,
            deleted=deleted,
            verified_absent=absent,
        )
    except (KeyError, TypeError):
        return None


def _proofs_from_contract(
    payload: object,
    *,
    expected_run_id_sha256: str,
    expected_scopes_by_backend: Mapping[str, Mapping[str, str]],
) -> Mapping[str, Sequence[BackendCleanStateProof]] | None:
    if type(payload) is VerifiedCleanStateValidation:
        assert isinstance(payload, VerifiedCleanStateValidation)
        payload = payload.payload
    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL_CONTRACT_KEYS:
        return None
    issues = payload["issues"]
    if (
        payload["schema_version"] != _SCHEMA_VERSION
        or payload["status"] != "verified"
        or payload["eligible"] is not True
        or payload["expected_run_id_sha256"] != expected_run_id_sha256
        or not isinstance(issues, Sequence)
        or isinstance(issues, (str, bytes))
        or len(issues) != 0
    ):
        return None
    backends = payload["backends"]
    if not isinstance(backends, Mapping) or set(backends) != set(_REQUIRED_BACKENDS):
        return None
    result: dict[str, tuple[BackendCleanStateProof, ...]] = {}
    for backend in _REQUIRED_BACKENDS:
        backend_payload = backends[backend]
        expected_scopes = expected_scopes_by_backend.get(backend)
        if (
            not isinstance(backend_payload, Mapping)
            or set(backend_payload) != _BACKEND_CONTRACT_KEYS
            or not isinstance(expected_scopes, Mapping)
        ):
            return None
        raw = backend_payload["proofs"]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return None
        expected_count = backend_payload["expected_scope_count"]
        observed_count = backend_payload["observed_scope_count"]
        if (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count != len(expected_scopes)
            or isinstance(observed_count, bool)
            or not isinstance(observed_count, int)
            or observed_count != len(raw)
            or backend_payload["verified"] is not True
        ):
            return None
        proofs = tuple(_proof_from_mapping(item) for item in raw)
        if any(proof is None for proof in proofs):
            return None
        result[backend] = tuple(proof for proof in proofs if proof is not None)
    return result


def verify_clean_state_contract_for_publication(
    payload: object,
    *,
    expected_run_id_sha256: str,
    expected_scopes_by_backend: Mapping[str, Mapping[str, str]],
    attestation_key: bytes,
) -> dict[str, object] | None:
    """Return only a reconstructed, sanitized contract after full verification."""

    proofs = _proofs_from_contract(
        payload,
        expected_run_id_sha256=expected_run_id_sha256,
        expected_scopes_by_backend=expected_scopes_by_backend,
    )
    if proofs is None:
        return None
    validation = validate_typed_clean_state_proofs(
        proofs,
        expected_run_id_sha256=expected_run_id_sha256,
        expected_scopes_by_backend=expected_scopes_by_backend,
        attestation_key=attestation_key,
    )
    if not validation.eligible:
        return None
    return public_clean_state_validation(validation)


def clean_state_contract_is_publishable(
    payload: object,
    *,
    expected_run_id_sha256: str,
    expected_scopes_by_backend: Mapping[str, Mapping[str, str]],
    attestation_key: bytes,
) -> bool:
    return (
        verify_clean_state_contract_for_publication(
            payload,
            expected_run_id_sha256=expected_run_id_sha256,
            expected_scopes_by_backend=expected_scopes_by_backend,
            attestation_key=attestation_key,
        )
        is not None
    )


__all__ = [
    "BackendCleanStateProof",
    "CleanStateBackendPort",
    "CleanStateProofError",
    "ResetProofPort",
    "VerifiedCleanStateValidation",
    "clean_state_contract_is_publishable",
    "clean_state_identity_sha256",
    "fresh_namespace_clean_state_proof",
    "mem0_delete_clean_state_proof",
    "public_clean_state_proof",
    "public_clean_state_validation",
    "reset_proof_is_valid",
    "skipped_mem0_clean_state_proof",
    "validate_typed_clean_state_proofs",
    "verify_clean_state_contract_for_publication",
]
