"""Secret-safe public value types for managed runtime credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_preflight import (
    ManagedBackendEndpoint,
    ManagedCredentialBinding,
)
from infinity_context_server.memory_comparison_provider_provenance import (
    ProviderRouteAttestation,
)

_SAFE_CODES = frozenset(
    {
        "managed_credentials_configuration_invalid",
        "managed_credentials_context_mismatch",
        "managed_credentials_expired",
        "managed_credentials_integrity_failed",
        "managed_credentials_preflight_invalid",
        "managed_credentials_readiness_failed",
        "managed_credentials_terminal",
    }
)


class ManagedRuntimeCredentialError(RuntimeError):
    """Secret-safe fail-closed authority error."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        safe = code if code in _SAFE_CODES else "managed_credentials_terminal"
        self.code = safe
        super().__init__(safe)


@final
@dataclass(frozen=True, slots=True)
class ManagedCredentialPreflightMaterial:
    """Non-consuming public facts used verbatim in one preflight request."""

    provider_credential: ManagedCredentialBinding
    backend_endpoints: tuple[ManagedBackendEndpoint, ...]
    provider_route: ProviderRouteAttestation
    mem0_probe_credential: ManagedCredentialBinding

    def __post_init__(self) -> None:
        if (
            type(self.provider_credential) is not ManagedCredentialBinding
            or type(self.backend_endpoints) is not tuple
            or any(type(item) is not ManagedBackendEndpoint for item in self.backend_endpoints)
            or type(self.provider_route) is not ProviderRouteAttestation
            or type(self.mem0_probe_credential) is not ManagedCredentialBinding
        ):
            raise ManagedRuntimeCredentialError(
                "managed_credentials_configuration_invalid"
            )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedCredentialPreflightMaterial is final")


__all__ = (
    "ManagedCredentialPreflightMaterial",
    "ManagedRuntimeCredentialError",
)
