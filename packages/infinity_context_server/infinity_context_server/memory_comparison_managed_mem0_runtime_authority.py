"""Application-owned authority for one pending managed Mem0 runtime probe.

The registry deliberately separates admission reservation from the one-shot
deadline lease. A lease is minted only for the exact reserved authority after a
successful probe, and keeps the original monotonic clock/deadline private.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, isfinite
from typing import Protocol, final

from infinity_context_server.memory_comparison_managed_mem0_auth import (
    MANAGED_MEM0_RUNTIME_MODE_PLATFORM,
    managed_mem0_runtime_mode,
)

MANAGED_MEM0_RUNTIME_DEADLINE_POLICY = "monotonic-hard-deadline.v1"
MANAGED_LIVE_RUNTIME_VALIDATION_MAX_AGE_SECONDS = 7_200
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")
_LEASE_TOKEN = object()
_LEASE_KEY = secrets.token_bytes(32)


class ManagedMem0RuntimeAuthorityError(RuntimeError):
    """Sanitized rejection from the application-owned authority boundary."""


class ManagedMem0RuntimeAttestationPort(Protocol):
    """Port returned to the managed runner after opaque admission."""

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object: ...


@final
@dataclass(frozen=True, slots=True)
class ManagedMem0RuntimeAuthorityDescriptor:
    """Secret-safe commitment to one exact pending runtime probe."""

    adapter_id: str
    implementation_sha256: str
    target_identity_sha256: str
    probe_nonce_sha256: str
    probe_token_credential_binding_id: str
    request_timeout_seconds: float
    deadline_policy: str
    deadline_budget_seconds: float
    minimum_network_timeout_seconds: float
    max_attempts: int
    expected_runtime_mode: str = MANAGED_MEM0_RUNTIME_MODE_PLATFORM

    def __post_init__(self) -> None:
        if (
            type(self.adapter_id) is not str
            or _IDENTIFIER.fullmatch(self.adapter_id) is None
            or type(self.implementation_sha256) is not str
            or _SHA256.fullmatch(self.implementation_sha256) is None
            or type(self.target_identity_sha256) is not str
            or _SHA256.fullmatch(self.target_identity_sha256) is None
            or type(self.probe_nonce_sha256) is not str
            or _SHA256.fullmatch(self.probe_nonce_sha256) is None
            or type(self.probe_token_credential_binding_id) is not str
            or _BINDING.fullmatch(self.probe_token_credential_binding_id) is None
            or type(self.deadline_policy) is not str
            or self.deadline_policy != MANAGED_MEM0_RUNTIME_DEADLINE_POLICY
            or type(self.request_timeout_seconds) is not float
            or not isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
            or type(self.deadline_budget_seconds) is not float
            or not isfinite(self.deadline_budget_seconds)
            or self.deadline_budget_seconds <= 0
            or type(self.minimum_network_timeout_seconds) is not float
            or not isfinite(self.minimum_network_timeout_seconds)
            or self.minimum_network_timeout_seconds <= 0
            or self.minimum_network_timeout_seconds > self.request_timeout_seconds
            or self.minimum_network_timeout_seconds > self.deadline_budget_seconds
            or type(self.max_attempts) is not int
            or self.max_attempts != 1
        ):
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority descriptor is invalid"
            )
        try:
            managed_mem0_runtime_mode(self.expected_runtime_mode)
        except ValueError:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority descriptor is invalid"
            ) from None

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedMem0RuntimeAuthorityDescriptor is final")


@final
class _ManagedMem0RuntimeDeadlineLease:
    """Opaque, non-copyable claim for one registered monotonic deadline."""

    __slots__ = ("__marker", "__weakref__")

    def __init__(self, *, _token: object) -> None:
        if _token is not _LEASE_TOKEN:
            raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is private")
        self.__marker = _token

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("_ManagedMem0RuntimeDeadlineLease is final")

    def __repr__(self) -> str:
        return "_ManagedMem0RuntimeDeadlineLease(<sealed>)"

    def __copy__(self) -> object:
        raise TypeError("managed Mem0 runtime deadline leases are noncopyable")

    def __deepcopy__(self, memo: object) -> object:
        del memo
        raise TypeError("managed Mem0 runtime deadline leases are noncopyable")

    def __reduce__(self) -> object:
        raise TypeError("managed Mem0 runtime deadline leases are nonserializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("managed Mem0 runtime deadline leases are nonserializable")

    def __getstate__(self) -> object:
        raise TypeError("managed Mem0 runtime deadline leases are nonserializable")


@dataclass(frozen=True, slots=True)
class _ManagedMem0RuntimeDeadlineLeaseMaterial:
    """Private result consumed by the managed-live policy issuer only."""

    authority_descriptor_sha256: str
    lease_binding_sha256: str
    run_id_sha256: str
    probe_nonce_sha256: str
    target_identity_sha256: str
    validation_payload_fingerprint_sha256: str
    remaining_seconds: float
    max_age_seconds: int


@dataclass(slots=True)
class _PendingAuthority:
    reference: weakref.ReferenceType[object]
    descriptor: ManagedMem0RuntimeAuthorityDescriptor
    fingerprint: tuple[object, ...]
    monotonic_clock: Callable[[], float] | None
    deadline_monotonic: float | None
    reserved: bool = False
    deadline_lease_issued: bool = False


@dataclass(slots=True)
class _DeadlineLeaseState:
    reference: weakref.ReferenceType[_ManagedMem0RuntimeDeadlineLease]
    authority: object
    authority_identity: int
    descriptor_fingerprint: tuple[object, ...]
    descriptor_sha256: str
    monotonic_clock: Callable[[], float]
    deadline_monotonic: float
    run_id_sha256: str
    probe_nonce_sha256: str
    target_identity_sha256: str
    validation_payload_fingerprint_sha256: str
    binding_sha256: str
    consumed: bool = False


_LOCK = threading.RLock()
_PENDING: dict[int, _PendingAuthority] = {}
_LEASES: dict[int, _DeadlineLeaseState] = {}


def _register_pending_managed_mem0_runtime_authority(
    port: object,
    descriptor: ManagedMem0RuntimeAuthorityDescriptor,
    *,
    monotonic_clock: Callable[[], float] | None = None,
    deadline_monotonic: float | None = None,
) -> None:
    """Trusted private composition seam for one exact adapter authority."""

    if (
        type(descriptor) is not ManagedMem0RuntimeAuthorityDescriptor
        or port is None
        or not callable(getattr(port, "attest", None))
        or not callable(getattr(port, "authority_descriptor", None))
        or (monotonic_clock is None) != (deadline_monotonic is None)
        or (
            monotonic_clock is not None
            and (
                not callable(monotonic_clock)
                or type(deadline_monotonic) is not float
                or not isfinite(deadline_monotonic)
            )
        )
    ):
        raise ManagedMem0RuntimeAuthorityError(
            "managed Mem0 runtime authority registration is invalid"
        )
    try:
        identity = id(port)
        reference = weakref.ref(
            port,
            lambda observed: _release_pending_authority(identity, observed),
        )
    except Exception:
        raise ManagedMem0RuntimeAuthorityError(
            "managed Mem0 runtime authority registration is invalid"
        ) from None
    with _LOCK:
        prior = _PENDING.get(identity)
        if prior is not None and prior.reference() is port:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority was already registered"
            )
        _PENDING[identity] = _PendingAuthority(
            reference=reference,
            descriptor=descriptor,
            fingerprint=_descriptor_fingerprint(descriptor),
            monotonic_clock=monotonic_clock,
            deadline_monotonic=deadline_monotonic,
        )


def inspect_pending_managed_mem0_runtime_authority(
    port: object,
) -> ManagedMem0RuntimeAuthorityDescriptor:
    """Inspect the exact registered authority while proving it remains pending."""

    with _LOCK:
        registration = _registered_authority(port)
        try:
            observed = port.authority_descriptor()
        except Exception:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority is unavailable"
            ) from None
        _require_registration_descriptor_intact(registration)
        if observed is not registration.descriptor:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority descriptor changed"
            )
        return registration.descriptor


def reserve_pending_managed_mem0_runtime_authority(
    port: object,
    descriptor: ManagedMem0RuntimeAuthorityDescriptor,
) -> None:
    """Atomically reserve a registered pending authority exactly once."""

    with _LOCK:
        observed = inspect_pending_managed_mem0_runtime_authority(port)
        registration = _PENDING.get(id(port))
        if registration is None or observed is not descriptor:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority changed before reservation"
            )
        if registration.reserved:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority was already reserved"
            )
        registration.reserved = True


def _reserved_managed_mem0_runtime_deadline_lease_is_available(port: object) -> bool:
    """Return whether a private post-probe lease may be issued for this port."""

    with _LOCK:
        registration = _PENDING.get(id(port))
        return bool(
            registration is not None
            and registration.reference() is port
            and registration.reserved
            and not registration.deadline_lease_issued
        )


def _issue_reserved_managed_mem0_runtime_deadline_lease(
    port: object,
    *,
    run_id: object,
    probe_nonce_sha256: object,
    target_identity_sha256: object,
    validation_payload_fingerprint_sha256: object,
) -> _ManagedMem0RuntimeDeadlineLease:
    """Issue one lease for the exact reserved authority and successful probe."""

    if (
        type(run_id) is not str
        or _IDENTIFIER.fullmatch(run_id) is None
        or type(probe_nonce_sha256) is not str
        or _SHA256.fullmatch(probe_nonce_sha256) is None
        or type(target_identity_sha256) is not str
        or _SHA256.fullmatch(target_identity_sha256) is None
        or type(validation_payload_fingerprint_sha256) is not str
        or _SHA256.fullmatch(validation_payload_fingerprint_sha256) is None
    ):
        raise ManagedMem0RuntimeAuthorityError(
            "managed Mem0 runtime deadline lease binding is invalid"
        )
    with _LOCK:
        registration = _registered_authority(port)
        _require_registration_descriptor_intact(registration)
        if not registration.reserved:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority was not reserved"
            )
        if registration.deadline_lease_issued:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime deadline lease was already issued"
            )
        if (
            registration.monotonic_clock is None
            or registration.deadline_monotonic is None
            or probe_nonce_sha256 != registration.descriptor.probe_nonce_sha256
            or target_identity_sha256 != registration.descriptor.target_identity_sha256
        ):
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime deadline lease binding is invalid"
            )
        run_sha256 = hashlib.sha256(run_id.encode()).hexdigest()
        descriptor_sha256 = _descriptor_sha256(registration.descriptor)
        binding_sha256 = _lease_binding_signature(
            authority_identity=id(port),
            descriptor_sha256=descriptor_sha256,
            run_id_sha256=run_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=target_identity_sha256,
            validation_payload_fingerprint_sha256=(validation_payload_fingerprint_sha256),
            deadline_monotonic=registration.deadline_monotonic,
        )
        lease = _ManagedMem0RuntimeDeadlineLease(_token=_LEASE_TOKEN)
        lease_identity = id(lease)
        _LEASES[lease_identity] = _DeadlineLeaseState(
            reference=weakref.ref(
                lease,
                lambda observed: _release_deadline_lease(lease_identity, observed),
            ),
            authority=port,
            authority_identity=id(port),
            descriptor_fingerprint=registration.fingerprint,
            descriptor_sha256=descriptor_sha256,
            monotonic_clock=registration.monotonic_clock,
            deadline_monotonic=registration.deadline_monotonic,
            run_id_sha256=run_sha256,
            probe_nonce_sha256=probe_nonce_sha256,
            target_identity_sha256=target_identity_sha256,
            validation_payload_fingerprint_sha256=(validation_payload_fingerprint_sha256),
            binding_sha256=binding_sha256,
        )
        registration.deadline_lease_issued = True
        return lease


def _consume_reserved_managed_mem0_runtime_deadline_lease(
    lease: object,
) -> _ManagedMem0RuntimeDeadlineLeaseMaterial:
    """Consume a lease once and derive the remaining private terminal allowance."""

    with _LOCK:
        state = _lease_state(lease)
        if state.consumed:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime deadline lease was already consumed"
            )
        _require_lease_state_intact(state, lease)
        try:
            current = _monotonic_now(state.monotonic_clock)
        except Exception:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime deadline lease clock is invalid"
            ) from None
        remaining = state.deadline_monotonic - current
        max_age_seconds = ceil(remaining)
        if not (
            remaining > 0
            and 1 <= max_age_seconds <= MANAGED_LIVE_RUNTIME_VALIDATION_MAX_AGE_SECONDS
        ):
            raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is expired")
        state.consumed = True
        return _ManagedMem0RuntimeDeadlineLeaseMaterial(
            authority_descriptor_sha256=state.descriptor_sha256,
            lease_binding_sha256=state.binding_sha256,
            run_id_sha256=state.run_id_sha256,
            probe_nonce_sha256=state.probe_nonce_sha256,
            target_identity_sha256=state.target_identity_sha256,
            validation_payload_fingerprint_sha256=(state.validation_payload_fingerprint_sha256),
            remaining_seconds=remaining,
            max_age_seconds=max_age_seconds,
        )


def _retire_managed_mem0_runtime_deadline_lease(lease: object) -> None:
    """Irreversibly retire a failed post-issuance lease and its authority."""

    with _LOCK:
        state = _lease_state(lease)
        registration = _PENDING.get(state.authority_identity)
        if (
            registration is None
            or registration.reference() is not state.authority
            or not registration.deadline_lease_issued
        ):
            raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is invalid")
        del _LEASES[id(lease)]
        del _PENDING[state.authority_identity]


def _managed_mem0_runtime_deadline_lease_is_intact(
    lease: object,
    *,
    lease_binding_sha256: object,
    authority_descriptor_sha256: object,
    run_id_sha256: object,
    probe_nonce_sha256: object,
    target_identity_sha256: object,
    validation_payload_fingerprint_sha256: object,
) -> bool:
    """Check immutable lease/policy binding without applying deadline decay."""

    with _LOCK:
        try:
            state = _lease_state(lease)
            _require_lease_state_intact(state, lease)
        except ManagedMem0RuntimeAuthorityError:
            return False
        return bool(
            state.consumed
            and all(
                type(value) is str and _SHA256.fullmatch(value) is not None
                for value in (
                    lease_binding_sha256,
                    authority_descriptor_sha256,
                    run_id_sha256,
                    probe_nonce_sha256,
                    target_identity_sha256,
                    validation_payload_fingerprint_sha256,
                )
            )
            and hmac.compare_digest(state.binding_sha256, lease_binding_sha256)
            and hmac.compare_digest(state.descriptor_sha256, authority_descriptor_sha256)
            and hmac.compare_digest(state.run_id_sha256, run_id_sha256)
            and hmac.compare_digest(state.probe_nonce_sha256, probe_nonce_sha256)
            and hmac.compare_digest(state.target_identity_sha256, target_identity_sha256)
            and hmac.compare_digest(
                state.validation_payload_fingerprint_sha256,
                validation_payload_fingerprint_sha256,
            )
        )


def _managed_mem0_runtime_deadline_lease_is_current(
    lease: object,
    *,
    lease_binding_sha256: object,
    authority_descriptor_sha256: object,
    run_id_sha256: object,
    probe_nonce_sha256: object,
    target_identity_sha256: object,
    validation_payload_fingerprint_sha256: object,
) -> bool:
    """Apply the original monotonic hard deadline without trusting wall time."""

    if not _managed_mem0_runtime_deadline_lease_is_intact(
        lease,
        lease_binding_sha256=lease_binding_sha256,
        authority_descriptor_sha256=authority_descriptor_sha256,
        run_id_sha256=run_id_sha256,
        probe_nonce_sha256=probe_nonce_sha256,
        target_identity_sha256=target_identity_sha256,
        validation_payload_fingerprint_sha256=(validation_payload_fingerprint_sha256),
    ):
        return False
    with _LOCK:
        try:
            state = _lease_state(lease)
            return _monotonic_now(state.monotonic_clock) < state.deadline_monotonic
        except Exception:
            return False


def _registered_authority(port: object) -> _PendingAuthority:
    registration = _PENDING.get(id(port))
    if registration is None or registration.reference() is not port:
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime authority is not registered")
    return registration


def _lease_state(lease: object) -> _DeadlineLeaseState:
    if type(lease) is not _ManagedMem0RuntimeDeadlineLease:
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is invalid")
    state = _LEASES.get(id(lease))
    if state is None or state.reference() is not lease:
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is invalid")
    return state


def _require_registration_descriptor_intact(registration: _PendingAuthority) -> None:
    try:
        registration.descriptor.__post_init__()
        fingerprint = _descriptor_fingerprint(registration.descriptor)
    except Exception:
        raise ManagedMem0RuntimeAuthorityError(
            "managed Mem0 runtime authority descriptor changed"
        ) from None
    if fingerprint != registration.fingerprint:
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime authority descriptor changed")


def _require_lease_state_intact(
    state: _DeadlineLeaseState,
    lease: object,
) -> None:
    registration = _PENDING.get(state.authority_identity)
    if (
        registration is None
        or registration.reference() is not state.authority
        or id(state.authority) != state.authority_identity
        or registration.fingerprint != state.descriptor_fingerprint
        or registration.monotonic_clock is not state.monotonic_clock
        or registration.deadline_monotonic != state.deadline_monotonic
    ):
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is invalid")
    _require_registration_descriptor_intact(registration)
    if state.reference() is not lease:
        raise ManagedMem0RuntimeAuthorityError("managed Mem0 runtime deadline lease is invalid")


def _monotonic_now(clock: Callable[[], float]) -> float:
    value = clock()
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("monotonic clock is invalid")
    current = float(value)
    if not isfinite(current):
        raise ValueError("monotonic clock is invalid")
    return current


def _descriptor_fingerprint(
    descriptor: ManagedMem0RuntimeAuthorityDescriptor,
) -> tuple[object, ...]:
    return (
        descriptor.adapter_id,
        descriptor.implementation_sha256,
        descriptor.target_identity_sha256,
        descriptor.probe_nonce_sha256,
        descriptor.probe_token_credential_binding_id,
        descriptor.request_timeout_seconds,
        descriptor.deadline_policy,
        descriptor.deadline_budget_seconds,
        descriptor.minimum_network_timeout_seconds,
        descriptor.max_attempts,
        descriptor.expected_runtime_mode,
    )


def _descriptor_sha256(descriptor: ManagedMem0RuntimeAuthorityDescriptor) -> str:
    return hashlib.sha256(
        json.dumps(
            _descriptor_fingerprint(descriptor),
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _lease_binding_signature(
    *,
    authority_identity: int,
    descriptor_sha256: str,
    run_id_sha256: str,
    probe_nonce_sha256: str,
    target_identity_sha256: str,
    validation_payload_fingerprint_sha256: str,
    deadline_monotonic: float,
) -> str:
    message = "\n".join(
        (
            "managed-mem0-runtime-deadline-lease.v2",
            str(authority_identity),
            descriptor_sha256,
            run_id_sha256,
            probe_nonce_sha256,
            target_identity_sha256,
            validation_payload_fingerprint_sha256,
            deadline_monotonic.hex(),
        )
    ).encode()
    return hmac.new(_LEASE_KEY, message, hashlib.sha256).hexdigest()


def _release_pending_authority(
    identity: int,
    reference: weakref.ReferenceType[object],
) -> None:
    with _LOCK:
        registration = _PENDING.get(identity)
        if registration is not None and registration.reference is reference:
            del _PENDING[identity]


def _release_deadline_lease(
    identity: int,
    reference: weakref.ReferenceType[_ManagedMem0RuntimeDeadlineLease],
) -> None:
    with _LOCK:
        state = _LEASES.get(identity)
        if state is not None and state.reference is reference:
            del _LEASES[identity]


__all__ = (
    "MANAGED_MEM0_RUNTIME_DEADLINE_POLICY",
    "ManagedMem0RuntimeAttestationPort",
    "ManagedMem0RuntimeAuthorityDescriptor",
    "ManagedMem0RuntimeAuthorityError",
    "inspect_pending_managed_mem0_runtime_authority",
    "reserve_pending_managed_mem0_runtime_authority",
)
