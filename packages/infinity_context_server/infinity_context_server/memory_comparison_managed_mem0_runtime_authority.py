"""Application-owned contract for one pending managed Mem0 attestation.

Concrete transports register an exact pending authority here. Managed admission
depends only on this contract and on the opaque registry entry, never on an HTTP
adapter type. The registry is deliberately process-local and identity based.
Its private registrar is a trusted composition seam, not a cryptographic issuer.
"""

from __future__ import annotations

import re
import threading
import weakref
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, final

MANAGED_MEM0_RUNTIME_DEADLINE_POLICY = "monotonic-hard-deadline.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BINDING = re.compile(r"^sha256:[0-9a-f]{64}$")


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

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedMem0RuntimeAuthorityDescriptor is final")


@dataclass(slots=True)
class _PendingAuthority:
    reference: weakref.ReferenceType[object]
    descriptor: ManagedMem0RuntimeAuthorityDescriptor
    fingerprint: tuple[object, ...]
    reserved: bool = False


_LOCK = threading.RLock()
_PENDING: dict[int, _PendingAuthority] = {}


def _register_pending_managed_mem0_runtime_authority(
    port: object,
    descriptor: ManagedMem0RuntimeAuthorityDescriptor,
) -> None:
    """Trusted private composition seam for an exact adapter authority."""

    if (
        type(descriptor) is not ManagedMem0RuntimeAuthorityDescriptor
        or port is None
        or not callable(getattr(port, "attest", None))
        or not callable(getattr(port, "authority_descriptor", None))
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
        )


def inspect_pending_managed_mem0_runtime_authority(
    port: object,
) -> ManagedMem0RuntimeAuthorityDescriptor:
    """Inspect the exact registered authority while proving it remains pending."""

    with _LOCK:
        registration = _PENDING.get(id(port))
        if registration is None or registration.reference() is not port:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority is not registered"
            )
        try:
            observed = port.authority_descriptor()
        except Exception:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority is unavailable"
            ) from None
        try:
            registration.descriptor.__post_init__()
            fingerprint = _descriptor_fingerprint(registration.descriptor)
        except Exception:
            raise ManagedMem0RuntimeAuthorityError(
                "managed Mem0 runtime authority descriptor changed"
            ) from None
        if observed is not registration.descriptor or fingerprint != registration.fingerprint:
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
    )


def _release_pending_authority(
    identity: int,
    reference: weakref.ReferenceType[object],
) -> None:
    with _LOCK:
        registration = _PENDING.get(identity)
        if registration is not None and registration.reference is reference:
            del _PENDING[identity]


__all__ = (
    "MANAGED_MEM0_RUNTIME_DEADLINE_POLICY",
    "ManagedMem0RuntimeAttestationPort",
    "ManagedMem0RuntimeAuthorityDescriptor",
    "ManagedMem0RuntimeAuthorityError",
    "inspect_pending_managed_mem0_runtime_authority",
    "reserve_pending_managed_mem0_runtime_authority",
)
