"""Private terminal-freshness policy for an admitted managed Mem0 runtime.

Public runtime validation remains a normal 120-second generic proof. This
module keeps an extended allowance in a process-local association that is bound
once to the exact validation object and to the authority's original monotonic
deadline lease.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_runtime_authority import (
    MANAGED_LIVE_RUNTIME_VALIDATION_MAX_AGE_SECONDS,
    _consume_reserved_managed_mem0_runtime_deadline_lease,
    _issue_reserved_managed_mem0_runtime_deadline_lease,
    _managed_mem0_runtime_deadline_lease_is_current,
    _managed_mem0_runtime_deadline_lease_is_intact,
    _ManagedMem0RuntimeDeadlineLease,
    _retire_managed_mem0_runtime_deadline_lease,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    _verified_mem0_runtime_attestation_validation_is_issued,
)

_PUBLIC_RUNTIME_VALIDATION_MAX_AGE_SECONDS = 120
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_POLICY_MARKER = object()
_POLICY_KEY = secrets.token_bytes(32)
_LOCK = threading.RLock()
_PENDING_POLICY_ISSUANCE_NONCES: set[object] = set()
_ISSUED_POLICIES: weakref.WeakValueDictionary[int, object] = weakref.WeakValueDictionary()


@final
@dataclass(frozen=True, slots=True, weakref_slot=True)
class _ManagedLiveRuntimeFreshnessPolicy:
    """Opaque allowance backed by one consumed monotonic deadline lease."""

    max_age_seconds: int
    deadline_at: datetime
    run_id_sha256: str
    probe_nonce_sha256: str
    target_identity_sha256: str
    authority_descriptor_sha256: str
    validation_payload_fingerprint_sha256: str
    _deadline_lease: _ManagedMem0RuntimeDeadlineLease
    _lease_binding_sha256: str
    _signature_sha256: str
    _marker: object
    _issuance_nonce: object

    def __post_init__(self) -> None:
        with _LOCK:
            issued_here = self._issuance_nonce in _PENDING_POLICY_ISSUANCE_NONCES
            _PENDING_POLICY_ISSUANCE_NONCES.discard(self._issuance_nonce)
        deadline = _policy_deadline(self.deadline_at)
        if not issued_here:
            raise TypeError("managed live freshness policies are noncopyable")
        if (
            self._marker is not _POLICY_MARKER
            or deadline is None
            or _bounded_max_age(self.max_age_seconds) != self.max_age_seconds
            or type(self._deadline_lease) is not _ManagedMem0RuntimeDeadlineLease
            or not _hashes_are_valid(
                self.run_id_sha256,
                self.probe_nonce_sha256,
                self.target_identity_sha256,
                self.authority_descriptor_sha256,
                self.validation_payload_fingerprint_sha256,
                self._lease_binding_sha256,
                self._signature_sha256,
            )
            or not hmac.compare_digest(
                self._signature_sha256,
                _policy_signature(
                    max_age_seconds=self.max_age_seconds,
                    deadline_at=deadline,
                    run_id_sha256=self.run_id_sha256,
                    probe_nonce_sha256=self.probe_nonce_sha256,
                    target_identity_sha256=self.target_identity_sha256,
                    authority_descriptor_sha256=self.authority_descriptor_sha256,
                    validation_payload_fingerprint_sha256=(
                        self.validation_payload_fingerprint_sha256
                    ),
                    lease_binding_sha256=self._lease_binding_sha256,
                ),
            )
        ):
            raise ValueError("managed live freshness policy is invalid")
        with _LOCK:
            _ISSUED_POLICIES[id(self)] = self

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("_ManagedLiveRuntimeFreshnessPolicy is final")

    def __copy__(self) -> object:
        raise TypeError("managed live freshness policies are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed live freshness policies are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed live freshness policies are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed live freshness policies are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed live freshness policies are nonserializable")


@dataclass(frozen=True, slots=True)
class _ManagedLiveRuntimeTerminalAllowance:
    """Private terminal-only view of a policy without exposing it publicly."""

    deadline_at: datetime
    max_age_seconds: int
    monotonic_current: bool
    binding_commitment_sha256: str


@dataclass(slots=True)
class _BoundRuntimeValidation:
    reference: weakref.ReferenceType[object]
    policy: _ManagedLiveRuntimeFreshnessPolicy
    validation_payload_fingerprint_sha256: str
    binding_sha256: str
    deadline_at: datetime
    max_age_seconds: int


_VALIDATIONS: dict[int, _BoundRuntimeValidation] = {}
_POLICY_VALIDATIONS: dict[int, int] = {}


def _issue_managed_live_runtime_freshness_policy(
    *,
    deadline_lease: object,
    validation: object,
) -> _ManagedLiveRuntimeFreshnessPolicy:
    """Consume one exact authority lease for its exact verified payload."""

    data = _validation_data(validation)
    if data is None:
        raise ValueError("managed live freshness policy is invalid")
    material = _consume_reserved_managed_mem0_runtime_deadline_lease(deadline_lease)
    if not hmac.compare_digest(
        material.validation_payload_fingerprint_sha256,
        data.payload_fingerprint_sha256,
    ) or not _validation_material_matches_policy(data, material):
        raise ValueError("managed live freshness policy is invalid")
    observed_at = _validation_instant(data.payload.get("validated_at"))
    if observed_at is None:
        raise ValueError("managed live freshness policy is invalid")
    deadline = _policy_deadline(observed_at + timedelta(seconds=material.remaining_seconds))
    if deadline is None or _bounded_max_age(material.max_age_seconds) is None:
        raise ValueError("managed live freshness policy is invalid")
    signature = _policy_signature(
        max_age_seconds=material.max_age_seconds,
        deadline_at=deadline,
        run_id_sha256=material.run_id_sha256,
        probe_nonce_sha256=material.probe_nonce_sha256,
        target_identity_sha256=material.target_identity_sha256,
        authority_descriptor_sha256=material.authority_descriptor_sha256,
        validation_payload_fingerprint_sha256=(material.validation_payload_fingerprint_sha256),
        lease_binding_sha256=material.lease_binding_sha256,
    )
    nonce = object()
    with _LOCK:
        _PENDING_POLICY_ISSUANCE_NONCES.add(nonce)
    try:
        return _ManagedLiveRuntimeFreshnessPolicy(
            max_age_seconds=material.max_age_seconds,
            deadline_at=deadline,
            run_id_sha256=material.run_id_sha256,
            probe_nonce_sha256=material.probe_nonce_sha256,
            target_identity_sha256=material.target_identity_sha256,
            authority_descriptor_sha256=material.authority_descriptor_sha256,
            validation_payload_fingerprint_sha256=(material.validation_payload_fingerprint_sha256),
            _deadline_lease=deadline_lease,
            _lease_binding_sha256=material.lease_binding_sha256,
            _signature_sha256=signature,
            _marker=_POLICY_MARKER,
            _issuance_nonce=nonce,
        )
    finally:
        with _LOCK:
            _PENDING_POLICY_ISSUANCE_NONCES.discard(nonce)


def _bind_managed_live_runtime_policy_from_reserved_authority(
    validation: object,
    *,
    authority: object,
    run_id: object,
    probe_nonce_sha256: object,
    target_identity_sha256: object,
) -> None:
    """Atomically derive and bind terminal authority after a verified probe."""

    data = _validation_data(validation)
    if data is None or not _validation_matches_claim(
        data,
        run_id=run_id,
        probe_nonce_sha256=probe_nonce_sha256,
        target_identity_sha256=target_identity_sha256,
    ):
        raise ValueError("managed live freshness policy binding is invalid")
    lease = _issue_reserved_managed_mem0_runtime_deadline_lease(
        authority,
        run_id=run_id,
        probe_nonce_sha256=probe_nonce_sha256,
        target_identity_sha256=target_identity_sha256,
        validation_payload_fingerprint_sha256=data.payload_fingerprint_sha256,
    )
    try:
        policy = _issue_managed_live_runtime_freshness_policy(
            deadline_lease=lease,
            validation=validation,
        )
        _bind_managed_live_runtime_freshness_policy(validation, policy=policy)
    except Exception:
        _retire_managed_mem0_runtime_deadline_lease(lease)
        raise


def _bind_managed_live_runtime_freshness_policy(
    validation: object,
    *,
    policy: object,
) -> None:
    """Bind a sealed policy once to its exact already-verified validation."""

    trusted_policy = _valid_managed_live_runtime_freshness_policy(policy)
    data = _validation_data(validation)
    if (
        trusted_policy is None
        or data is None
        or not _validation_matches_policy(data, trusted_policy)
    ):
        raise ValueError("managed live freshness policy binding is invalid")
    identity = id(validation)
    try:
        reference = weakref.ref(
            validation,
            lambda observed: _release_validation(identity, observed),
        )
    except Exception:
        raise ValueError("managed live freshness policy binding is invalid") from None
    binding_sha256 = _validation_binding_signature(
        trusted_policy,
        data.payload_fingerprint_sha256,
    )
    with _LOCK:
        if identity in _VALIDATIONS or id(trusted_policy) in _POLICY_VALIDATIONS:
            raise ValueError("managed live freshness policy was already bound")
        _VALIDATIONS[identity] = _BoundRuntimeValidation(
            reference=reference,
            policy=trusted_policy,
            validation_payload_fingerprint_sha256=data.payload_fingerprint_sha256,
            binding_sha256=binding_sha256,
            deadline_at=trusted_policy.deadline_at,
            max_age_seconds=trusted_policy.max_age_seconds,
        )
        _POLICY_VALIDATIONS[id(trusted_policy)] = identity


def _managed_live_runtime_validation_terminal_allowance(
    value: object,
) -> _ManagedLiveRuntimeTerminalAllowance | None:
    """Return a policy only for terminal inspection, with monotonic freshness."""

    state = _bound_validation(value)
    if state is None or not _bound_validation_is_intact(value, state):
        return None
    policy = state.policy
    return _ManagedLiveRuntimeTerminalAllowance(
        deadline_at=state.deadline_at,
        max_age_seconds=state.max_age_seconds,
        monotonic_current=_managed_mem0_runtime_deadline_lease_is_current(
            policy._deadline_lease,
            lease_binding_sha256=policy._lease_binding_sha256,
            authority_descriptor_sha256=policy.authority_descriptor_sha256,
            run_id_sha256=policy.run_id_sha256,
            probe_nonce_sha256=policy.probe_nonce_sha256,
            target_identity_sha256=policy.target_identity_sha256,
            validation_payload_fingerprint_sha256=(policy.validation_payload_fingerprint_sha256),
        ),
        binding_commitment_sha256=state.binding_sha256,
    )


def _managed_live_runtime_validation_deadline(value: object) -> datetime | None:
    """Compatibility helper returning only an intact private policy deadline."""

    allowance = _managed_live_runtime_validation_terminal_allowance(value)
    return allowance.deadline_at if allowance is not None else None


@dataclass(frozen=True, slots=True)
class _ValidationData:
    payload: MappingProxyType
    payload_fingerprint_sha256: str


def _validation_data(value: object) -> _ValidationData | None:
    if not _verified_mem0_runtime_attestation_validation_is_issued(value):
        return None
    try:
        payload = value.payload
        fingerprint = value._payload_fingerprint_sha256
    except (AttributeError, TypeError):
        return None
    if (
        not isinstance(payload, MappingProxyType)
        or type(fingerprint) is not str
        or _SHA256_RE.fullmatch(fingerprint) is None
        or _validation_payload_fingerprint(payload) != fingerprint
    ):
        return None
    return _ValidationData(payload=payload, payload_fingerprint_sha256=fingerprint)


def _validation_matches_policy(
    data: _ValidationData,
    policy: _ManagedLiveRuntimeFreshnessPolicy,
) -> bool:
    attestation = data.payload.get("attestation")
    return bool(
        data.payload.get("status") == "valid"
        and data.payload.get("eligible") is True
        and data.payload.get("max_age_seconds") == _PUBLIC_RUNTIME_VALIDATION_MAX_AGE_SECONDS
        and isinstance(attestation, Mapping)
        and attestation.get("run_id_sha256") == policy.run_id_sha256
        and attestation.get("probe_nonce_sha256") == policy.probe_nonce_sha256
        and attestation.get("target_identity_sha256") == policy.target_identity_sha256
    )


def _validation_matches_claim(
    data: _ValidationData,
    *,
    run_id: object,
    probe_nonce_sha256: object,
    target_identity_sha256: object,
) -> bool:
    if (
        type(run_id) is not str
        or type(probe_nonce_sha256) is not str
        or type(target_identity_sha256) is not str
    ):
        return False
    attestation = data.payload.get("attestation")
    return bool(
        data.payload.get("status") == "valid"
        and data.payload.get("eligible") is True
        and data.payload.get("max_age_seconds") == _PUBLIC_RUNTIME_VALIDATION_MAX_AGE_SECONDS
        and isinstance(attestation, Mapping)
        and attestation.get("run_id_sha256") == hashlib.sha256(run_id.encode()).hexdigest()
        and attestation.get("probe_nonce_sha256") == probe_nonce_sha256
        and attestation.get("target_identity_sha256") == target_identity_sha256
    )


def _validation_material_matches_policy(data: _ValidationData, material: object) -> bool:
    try:
        run_id_sha256 = material.run_id_sha256
        probe_nonce_sha256 = material.probe_nonce_sha256
        target_identity_sha256 = material.target_identity_sha256
    except AttributeError:
        return False
    attestation = data.payload.get("attestation")
    return bool(
        data.payload.get("status") == "valid"
        and data.payload.get("eligible") is True
        and data.payload.get("max_age_seconds") == _PUBLIC_RUNTIME_VALIDATION_MAX_AGE_SECONDS
        and isinstance(attestation, Mapping)
        and attestation.get("run_id_sha256") == run_id_sha256
        and attestation.get("probe_nonce_sha256") == probe_nonce_sha256
        and attestation.get("target_identity_sha256") == target_identity_sha256
    )


def _bound_validation(value: object) -> _BoundRuntimeValidation | None:
    with _LOCK:
        state = _VALIDATIONS.get(id(value))
        return state if state is not None and state.reference() is value else None


def _bound_validation_is_intact(
    value: object,
    state: _BoundRuntimeValidation,
) -> bool:
    data = _validation_data(value)
    policy = state.policy
    return bool(
        data is not None
        and state.reference() is value
        and data.payload_fingerprint_sha256 == state.validation_payload_fingerprint_sha256
        and data.payload_fingerprint_sha256 == policy.validation_payload_fingerprint_sha256
        and _validation_matches_policy(data, policy)
        and _valid_managed_live_runtime_freshness_policy(policy) is policy
        and hmac.compare_digest(
            state.binding_sha256,
            _validation_binding_signature(policy, data.payload_fingerprint_sha256),
        )
    )


def _valid_managed_live_runtime_freshness_policy(
    value: object,
) -> _ManagedLiveRuntimeFreshnessPolicy | None:
    if type(value) is not _ManagedLiveRuntimeFreshnessPolicy:
        return None
    deadline = _policy_deadline(value.deadline_at)
    if (
        _ISSUED_POLICIES.get(id(value)) is not value
        or value._marker is not _POLICY_MARKER
        or deadline is None
        or _bounded_max_age(value.max_age_seconds) != value.max_age_seconds
        or type(value._deadline_lease) is not _ManagedMem0RuntimeDeadlineLease
        or not _hashes_are_valid(
            value.run_id_sha256,
            value.probe_nonce_sha256,
            value.target_identity_sha256,
            value.authority_descriptor_sha256,
            value.validation_payload_fingerprint_sha256,
            value._lease_binding_sha256,
            value._signature_sha256,
        )
        or not hmac.compare_digest(
            value._signature_sha256,
            _policy_signature(
                max_age_seconds=value.max_age_seconds,
                deadline_at=deadline,
                run_id_sha256=value.run_id_sha256,
                probe_nonce_sha256=value.probe_nonce_sha256,
                target_identity_sha256=value.target_identity_sha256,
                authority_descriptor_sha256=value.authority_descriptor_sha256,
                validation_payload_fingerprint_sha256=(value.validation_payload_fingerprint_sha256),
                lease_binding_sha256=value._lease_binding_sha256,
            ),
        )
        or not _managed_mem0_runtime_deadline_lease_is_intact(
            value._deadline_lease,
            lease_binding_sha256=value._lease_binding_sha256,
            authority_descriptor_sha256=value.authority_descriptor_sha256,
            run_id_sha256=value.run_id_sha256,
            probe_nonce_sha256=value.probe_nonce_sha256,
            target_identity_sha256=value.target_identity_sha256,
            validation_payload_fingerprint_sha256=(value.validation_payload_fingerprint_sha256),
        )
    ):
        return None
    return value


def _validation_payload_fingerprint(payload: Mapping[str, object]) -> str | None:
    try:
        encoded = json.dumps(
            _deep_thaw(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_deep_thaw(item) for item in value]
    return copy.deepcopy(value)


def _policy_deadline(value: object) -> datetime | None:
    if type(value) is not datetime or value.tzinfo is None:
        return None
    normalized = value.astimezone(UTC)
    return normalized if 1970 <= normalized.year <= 2100 else None


def _validation_instant(value: object) -> datetime | None:
    if type(value) is not str or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return None
    return _policy_deadline(parsed)


def _bounded_max_age(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MANAGED_LIVE_RUNTIME_VALIDATION_MAX_AGE_SECONDS
    ):
        return None
    return value


def _hashes_are_valid(*values: object) -> bool:
    return all(type(value) is str and _SHA256_RE.fullmatch(value) is not None for value in values)


def _policy_signature(
    *,
    max_age_seconds: int,
    deadline_at: datetime,
    run_id_sha256: str,
    probe_nonce_sha256: str,
    target_identity_sha256: str,
    authority_descriptor_sha256: str,
    validation_payload_fingerprint_sha256: str,
    lease_binding_sha256: str,
) -> str:
    message = "\n".join(
        (
            "mem0-managed-live-runtime-freshness.v2",
            str(max_age_seconds),
            deadline_at.astimezone(UTC).isoformat(timespec="microseconds"),
            run_id_sha256,
            probe_nonce_sha256,
            target_identity_sha256,
            authority_descriptor_sha256,
            validation_payload_fingerprint_sha256,
            lease_binding_sha256,
        )
    ).encode()
    return hmac.new(_POLICY_KEY, message, hashlib.sha256).hexdigest()


def _validation_binding_signature(
    policy: _ManagedLiveRuntimeFreshnessPolicy,
    payload_fingerprint_sha256: str,
) -> str:
    message = "\n".join(
        (
            "mem0-managed-live-runtime-validation-binding.v2",
            policy._signature_sha256,
            payload_fingerprint_sha256,
        )
    ).encode()
    return hmac.new(_POLICY_KEY, message, hashlib.sha256).hexdigest()


def _release_validation(identity: int, reference: weakref.ReferenceType[object]) -> None:
    with _LOCK:
        state = _VALIDATIONS.get(identity)
        if state is not None and state.reference is reference:
            _POLICY_VALIDATIONS.pop(id(state.policy), None)
            del _VALIDATIONS[identity]


__all__ = ("MANAGED_LIVE_RUNTIME_VALIDATION_MAX_AGE_SECONDS",)
