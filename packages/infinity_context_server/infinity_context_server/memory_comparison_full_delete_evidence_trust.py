"""Composition-root trust capabilities for terminal delete verification."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import weakref
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_full_delete_evidence_witnesses import (
    INFINITY_BACKEND_KIND,
    MEM0_BACKEND_KIND,
    DeleteEvidenceVerificationError,
    DeleteVerificationPort,
    validate_delete_id,
)

_TOKEN = object()


@dataclass(frozen=True, slots=True)
class AdapterProvenance:
    backend_kind: str
    backend_id: str
    adapter_id: str
    implementation_sha256: str


@dataclass(frozen=True, slots=True)
class TrustPolicySnapshot:
    issuer: _DeleteVerificationTrustPolicyIssuer
    issuer_commitment: str
    infinity_port: DeleteVerificationPort
    mem0_port: DeleteVerificationPort
    infinity_port_identity: int
    mem0_port_identity: int
    infinity: AdapterProvenance
    mem0: AdapterProvenance
    external_attestation_commitment: str
    secret: bytes
    commitment: str


@dataclass(frozen=True, slots=True)
class CoordinatorSnapshot:
    policy: DeleteVerificationTrustPolicy
    policy_commitment: str
    secret: bytes
    commitment: str


@dataclass(frozen=True, slots=True)
class _IssuerSnapshot:
    authority_id: str
    authority_implementation_sha256: str
    secret: bytes
    commitment: str


@final
class _DeleteVerificationTrustPolicyIssuer:
    """Internal composition-root authority; never part of the public API."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise DeleteEvidenceVerificationError("delete policy issuers must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("_DeleteVerificationTrustPolicyIssuer is sealed")

    def __repr__(self) -> str:
        return "_DeleteVerificationTrustPolicyIssuer(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("_DeleteVerificationTrustPolicyIssuer is nonserializable")


@final
class DeleteVerificationTrustPolicy:
    """Opaque external-attestation policy issued by a trusted composition root."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise DeleteEvidenceVerificationError("delete trust policies must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("DeleteVerificationTrustPolicy is sealed")

    def __repr__(self) -> str:
        return "DeleteVerificationTrustPolicy(<opaque>)"

    def __reduce__(self) -> object:
        raise TypeError("DeleteVerificationTrustPolicy is nonserializable")


@final
class TrustedDeleteVerificationCoordinator:
    """Opaque coordinator derived only from one live trust policy."""

    __slots__ = ("__commitment", "__weakref__")

    def __init__(self, *, commitment: str, _token: object) -> None:
        if _token is not _TOKEN:
            raise DeleteEvidenceVerificationError("delete coordinators must be issued")
        self.__commitment = commitment

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("TrustedDeleteVerificationCoordinator is sealed")

    def __repr__(self) -> str:
        return "TrustedDeleteVerificationCoordinator(<policy-bound>)"

    def __reduce__(self) -> object:
        raise TypeError("TrustedDeleteVerificationCoordinator is nonserializable")


_ISSUERS: weakref.WeakKeyDictionary[_DeleteVerificationTrustPolicyIssuer, _IssuerSnapshot] = (
    weakref.WeakKeyDictionary()
)
_POLICIES: weakref.WeakKeyDictionary[DeleteVerificationTrustPolicy, TrustPolicySnapshot] = (
    weakref.WeakKeyDictionary()
)
_COORDINATORS: weakref.WeakKeyDictionary[
    TrustedDeleteVerificationCoordinator, CoordinatorSnapshot
] = weakref.WeakKeyDictionary()
_LOCK = threading.RLock()


def _create_delete_verification_trust_policy_issuer_for_composition_root(
    *,
    authority_id: str,
    authority_implementation_sha256: str,
) -> _DeleteVerificationTrustPolicyIssuer:
    """Internal bootstrap used only by the owning composition root."""

    validate_delete_id(authority_id, field_name="delete policy authority_id")
    _validate_sha256(
        authority_implementation_sha256,
        field_name="delete policy authority implementation",
    )
    secret = secrets.token_bytes(32)
    payload = {
        "authority_id": authority_id,
        "authority_implementation_sha256": authority_implementation_sha256,
        "kind": "delete-verification-policy-issuer",
    }
    commitment = _commitment(secret, payload)
    issuer = _DeleteVerificationTrustPolicyIssuer(
        commitment=commitment,
        _token=_TOKEN,
    )
    with _LOCK:
        _ISSUERS[issuer] = _IssuerSnapshot(
            authority_id,
            authority_implementation_sha256,
            secret,
            commitment,
        )
    return issuer


def _issue_delete_verification_trust_policy_for_composition_root(
    issuer: _DeleteVerificationTrustPolicyIssuer,
    *,
    infinity_port: DeleteVerificationPort,
    mem0_port: DeleteVerificationPort,
    infinity_backend_id: str,
    mem0_backend_id: str,
    infinity_adapter_id: str,
    mem0_adapter_id: str,
    infinity_implementation_sha256: str,
    mem0_implementation_sha256: str,
    external_attestation_commitment: str,
) -> DeleteVerificationTrustPolicy:
    """Internal issuance binding exact ports to externally attested provenance."""

    issuer_snapshot = _issuer_snapshot(issuer)
    if infinity_port is mem0_port:
        raise DeleteEvidenceVerificationError("delete policy ports must be distinct")
    for name, value in (
        ("infinity_backend_id", infinity_backend_id),
        ("mem0_backend_id", mem0_backend_id),
        ("infinity_adapter_id", infinity_adapter_id),
        ("mem0_adapter_id", mem0_adapter_id),
    ):
        validate_delete_id(value, field_name=f"delete policy {name}")
    if infinity_backend_id == mem0_backend_id:
        raise DeleteEvidenceVerificationError("delete policy backend identities must differ")
    _validate_sha256(
        infinity_implementation_sha256,
        field_name="delete policy infinity implementation",
    )
    _validate_sha256(
        mem0_implementation_sha256,
        field_name="delete policy mem0 implementation",
    )
    _validate_sha256(
        external_attestation_commitment,
        field_name="delete policy external attestation commitment",
    )
    infinity = AdapterProvenance(
        INFINITY_BACKEND_KIND,
        infinity_backend_id,
        infinity_adapter_id,
        infinity_implementation_sha256,
    )
    mem0 = AdapterProvenance(
        MEM0_BACKEND_KIND,
        mem0_backend_id,
        mem0_adapter_id,
        mem0_implementation_sha256,
    )
    infinity_port_identity = id(infinity_port)
    mem0_port_identity = id(mem0_port)
    secret = secrets.token_bytes(32)
    payload = _policy_payload(
        issuer_snapshot.commitment,
        infinity_port_identity,
        mem0_port_identity,
        infinity,
        mem0,
        external_attestation_commitment,
    )
    commitment = _commitment(secret, payload)
    policy = DeleteVerificationTrustPolicy(commitment=commitment, _token=_TOKEN)
    with _LOCK:
        _POLICIES[policy] = TrustPolicySnapshot(
            issuer,
            issuer_snapshot.commitment,
            infinity_port,
            mem0_port,
            infinity_port_identity,
            mem0_port_identity,
            infinity,
            mem0,
            external_attestation_commitment,
            secret,
            commitment,
        )
    return policy


def create_trusted_delete_verification_coordinator(
    *,
    policy: DeleteVerificationTrustPolicy,
) -> TrustedDeleteVerificationCoordinator:
    """Create a runtime coordinator from one exact live trust policy."""

    policy_snapshot = trust_policy_snapshot(policy)
    secret = secrets.token_bytes(32)
    commitment = _commitment(
        secret,
        {
            "kind": "delete-verification-coordinator",
            "policy_commitment": policy_snapshot.commitment,
            "policy_identity": id(policy),
        },
    )
    coordinator = TrustedDeleteVerificationCoordinator(
        commitment=commitment,
        _token=_TOKEN,
    )
    with _LOCK:
        _COORDINATORS[coordinator] = CoordinatorSnapshot(
            policy,
            policy_snapshot.commitment,
            secret,
            commitment,
        )
    return coordinator


def trust_policy_snapshot(
    policy: DeleteVerificationTrustPolicy,
) -> TrustPolicySnapshot:
    if type(policy) is not DeleteVerificationTrustPolicy:
        raise DeleteEvidenceVerificationError("delete verification trust policy is invalid")
    with _LOCK:
        snapshot = _POLICIES.get(policy)
    if snapshot is None:
        raise DeleteEvidenceVerificationError("delete verification trust policy is unissued")
    issuer = _issuer_snapshot(snapshot.issuer)
    expected = _commitment(
        snapshot.secret,
        _policy_payload(
            snapshot.issuer_commitment,
            snapshot.infinity_port_identity,
            snapshot.mem0_port_identity,
            snapshot.infinity,
            snapshot.mem0,
            snapshot.external_attestation_commitment,
        ),
    )
    try:
        current = policy._DeleteVerificationTrustPolicy__commitment
    except Exception:
        raise DeleteEvidenceVerificationError("delete trust policy integrity failed") from None
    if (
        snapshot.issuer_commitment != issuer.commitment
        or id(snapshot.infinity_port) != snapshot.infinity_port_identity
        or id(snapshot.mem0_port) != snapshot.mem0_port_identity
        or type(current) is not str
        or not hmac.compare_digest(current, snapshot.commitment)
        or not hmac.compare_digest(expected, snapshot.commitment)
    ):
        raise DeleteEvidenceVerificationError("delete trust policy integrity failed")
    return snapshot


def coordinator_snapshot(
    coordinator: TrustedDeleteVerificationCoordinator,
    *,
    expected_policy: DeleteVerificationTrustPolicy,
) -> CoordinatorSnapshot:
    if type(coordinator) is not TrustedDeleteVerificationCoordinator:
        raise DeleteEvidenceVerificationError(
            "delete verification requires a policy-bound coordinator"
        )
    policy = trust_policy_snapshot(expected_policy)
    with _LOCK:
        snapshot = _COORDINATORS.get(coordinator)
    if snapshot is None:
        raise DeleteEvidenceVerificationError("delete coordinator is unissued")
    expected = _commitment(
        snapshot.secret,
        {
            "kind": "delete-verification-coordinator",
            "policy_commitment": snapshot.policy_commitment,
            "policy_identity": id(snapshot.policy),
        },
    )
    try:
        current = coordinator._TrustedDeleteVerificationCoordinator__commitment
    except Exception:
        raise DeleteEvidenceVerificationError("delete coordinator integrity failed") from None
    if (
        snapshot.policy is not expected_policy
        or snapshot.policy_commitment != policy.commitment
        or type(current) is not str
        or not hmac.compare_digest(current, snapshot.commitment)
        or not hmac.compare_digest(expected, snapshot.commitment)
    ):
        raise DeleteEvidenceVerificationError("delete coordinator integrity failed")
    return snapshot


def _issuer_snapshot(
    issuer: _DeleteVerificationTrustPolicyIssuer,
) -> _IssuerSnapshot:
    if type(issuer) is not _DeleteVerificationTrustPolicyIssuer:
        raise DeleteEvidenceVerificationError("delete policy issuer is invalid")
    with _LOCK:
        snapshot = _ISSUERS.get(issuer)
    if snapshot is None:
        raise DeleteEvidenceVerificationError("delete policy issuer is unissued")
    expected = _commitment(
        snapshot.secret,
        {
            "authority_id": snapshot.authority_id,
            "authority_implementation_sha256": snapshot.authority_implementation_sha256,
            "kind": "delete-verification-policy-issuer",
        },
    )
    try:
        current = issuer._DeleteVerificationTrustPolicyIssuer__commitment
    except Exception:
        raise DeleteEvidenceVerificationError("delete policy issuer integrity failed") from None
    if (
        type(current) is not str
        or not hmac.compare_digest(current, snapshot.commitment)
        or not hmac.compare_digest(expected, snapshot.commitment)
    ):
        raise DeleteEvidenceVerificationError("delete policy issuer integrity failed")
    return snapshot


def _policy_payload(
    issuer_commitment: str,
    infinity_port_identity: int,
    mem0_port_identity: int,
    infinity: AdapterProvenance,
    mem0: AdapterProvenance,
    external_attestation_commitment: str,
) -> dict[str, object]:
    return {
        "external_attestation_commitment": external_attestation_commitment,
        "infinity": _provenance_payload(infinity),
        "infinity_port_identity": infinity_port_identity,
        "issuer_commitment": issuer_commitment,
        "mem0": _provenance_payload(mem0),
        "mem0_port_identity": mem0_port_identity,
    }


def _provenance_payload(provenance: AdapterProvenance) -> dict[str, object]:
    return {
        "adapter_id": provenance.adapter_id,
        "backend_id": provenance.backend_id,
        "backend_kind": provenance.backend_kind,
        "implementation_sha256": provenance.implementation_sha256,
    }


def _validate_sha256(value: object, *, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise DeleteEvidenceVerificationError(f"{field_name} sha256 is invalid")


def _commitment(secret: bytes, payload: dict[str, object]) -> str:
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.new(secret, rendered, hashlib.sha256).hexdigest()


__all__ = (
    "DeleteVerificationTrustPolicy",
    "TrustedDeleteVerificationCoordinator",
    "create_trusted_delete_verification_coordinator",
)
