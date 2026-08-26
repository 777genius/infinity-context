"""Exact application dispatch for independently issued v4 and managed-v5 runtime proofs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    RUNTIME_FAMILY as MANAGED_MEM0_V5_RUNTIME_FAMILY,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_runtime_attestation import (
    VerifiedManagedMem0V5RuntimeAttestationValidation,
    _verified_managed_mem0_v5_runtime_validation_is_issued,
    managed_mem0_v5_runtime_validation_is_publishable,
    public_managed_mem0_v5_runtime_validation,
)
from infinity_context_server.memory_comparison_mem0_runtime_attestation import (
    VerifiedMem0RuntimeAttestationValidation,
    _verified_mem0_runtime_attestation_validation_is_issued,
    mem0_runtime_attestation_validation_is_publishable,
    public_mem0_runtime_attestation_validation,
)

LEGACY_MEM0_RUNTIME_FAMILY = "mem0_v4"


@final
@dataclass(frozen=True, slots=True)
class ManagedRuntimeValidationView:
    """Uniform immutable view, issued only after exact nominal type dispatch."""

    family: str
    public_payload: MappingProxyType
    payload_fingerprint_sha256: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedRuntimeValidationView is final")


def managed_runtime_validation_view(value: object) -> ManagedRuntimeValidationView | None:
    """Project only exact process-issued runtime capabilities; never structural objects."""

    if type(value) is VerifiedMem0RuntimeAttestationValidation:
        if not _verified_mem0_runtime_attestation_validation_is_issued(value):
            return None
        public = public_mem0_runtime_attestation_validation(value)
        family = LEGACY_MEM0_RUNTIME_FAMILY
    elif type(value) is VerifiedManagedMem0V5RuntimeAttestationValidation:
        if not _verified_managed_mem0_v5_runtime_validation_is_issued(value):
            return None
        public = public_managed_mem0_v5_runtime_validation(value)
        family = MANAGED_MEM0_V5_RUNTIME_FAMILY
    else:
        return None
    fingerprint = getattr(value, "_payload_fingerprint_sha256", None)
    if type(fingerprint) is not str:
        return None
    return ManagedRuntimeValidationView(
        family=family,
        public_payload=_freeze_mapping(public),
        payload_fingerprint_sha256=fingerprint,
    )


def managed_runtime_validation_is_issued(value: object) -> bool:
    return managed_runtime_validation_view(value) is not None


def managed_runtime_validation_payload_fingerprint_sha256(value: object) -> str | None:
    view = managed_runtime_validation_view(value)
    return view.payload_fingerprint_sha256 if view is not None else None


def managed_runtime_validation_public_payload(value: object) -> dict[str, object]:
    view = managed_runtime_validation_view(value)
    if view is None:
        return {}
    return {str(key): _thaw(item) for key, item in view.public_payload.items()}


def managed_runtime_validation_is_publishable(
    value: object,
    *,
    required_runtime_mode: str,
    required_family: str | None = None,
) -> bool:
    """Dispatch a family-specific policy after exact nominal issuance checks."""

    view = managed_runtime_validation_view(value)
    if view is None or (required_family is not None and view.family != required_family):
        return False
    if type(value) is VerifiedMem0RuntimeAttestationValidation:
        return mem0_runtime_attestation_validation_is_publishable(
            value,
            required_runtime_mode=required_runtime_mode,
        )
    if type(value) is VerifiedManagedMem0V5RuntimeAttestationValidation:
        return managed_mem0_v5_runtime_validation_is_publishable(
            value,
            required_runtime_mode=required_runtime_mode,
        )
    return False


def _freeze_mapping(value: Mapping[str, object]) -> MappingProxyType:
    return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_thaw(item) for item in value]
    return value


__all__ = (
    "LEGACY_MEM0_RUNTIME_FAMILY",
    "MANAGED_MEM0_V5_RUNTIME_FAMILY",
    "ManagedRuntimeValidationView",
    "managed_runtime_validation_is_issued",
    "managed_runtime_validation_is_publishable",
    "managed_runtime_validation_payload_fingerprint_sha256",
    "managed_runtime_validation_public_payload",
    "managed_runtime_validation_view",
)
