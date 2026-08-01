"""Narrow production facades over the shared managed HTTP lifecycle.

The lifecycle adapter owns one state machine for reset and ingest. The managed
runner deliberately requires distinct operation-specific ports, so the
composition root exposes two sealed facades instead of widening either port.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_managed_http_lifecycle import (
    MANAGED_HTTP_LIFECYCLE_ADAPTER_ID,
    ManagedComparisonHttpLifecycleAdapter,
    managed_http_lifecycle_implementation_sha256,
)

MANAGED_PRODUCTION_RESET_ADAPTER_ID = "managed-production-http-reset-v1"
MANAGED_PRODUCTION_INGEST_ADAPTER_ID = "managed-production-http-ingest-v1"


class ManagedProductionPortError(RuntimeError):
    """Fixed-code production facade failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@final
class ManagedProductionResetPort:
    """Reset-only facade bound to one exact lifecycle adapter."""

    __slots__ = ("_implementation", "_lifecycle", "_lifecycle_implementation")

    def __init__(self, lifecycle: ManagedComparisonHttpLifecycleAdapter) -> None:
        implementation = _trusted_lifecycle_implementation(lifecycle)
        self._lifecycle = lifecycle
        self._lifecycle_implementation = implementation
        self._implementation = _facade_implementation(
            MANAGED_PRODUCTION_RESET_ADAPTER_ID,
            implementation,
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProductionResetPort is final")

    @property
    def adapter_id(self) -> str:
        return MANAGED_PRODUCTION_RESET_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return self._implementation

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        lifecycle = self._trusted_lifecycle()
        lifecycle.reset(
            run_id=run_id,
            binding_commitment_sha256=binding_commitment_sha256,
            backend_targets=backend_targets,
        )

    def _trusted_lifecycle(self) -> ManagedComparisonHttpLifecycleAdapter:
        _require_lifecycle_stable(self._lifecycle, self._lifecycle_implementation)
        return self._lifecycle


@final
class ManagedProductionIngestPort:
    """Ingest-only facade bound to the same exact lifecycle adapter."""

    __slots__ = ("_implementation", "_lifecycle", "_lifecycle_implementation")

    def __init__(self, lifecycle: ManagedComparisonHttpLifecycleAdapter) -> None:
        implementation = _trusted_lifecycle_implementation(lifecycle)
        self._lifecycle = lifecycle
        self._lifecycle_implementation = implementation
        self._implementation = _facade_implementation(
            MANAGED_PRODUCTION_INGEST_ADAPTER_ID,
            implementation,
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProductionIngestPort is final")

    @property
    def adapter_id(self) -> str:
        return MANAGED_PRODUCTION_INGEST_ADAPTER_ID

    @property
    def implementation_sha256(self) -> str:
        return self._implementation

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> object:
        lifecycle = self._trusted_lifecycle()
        return lifecycle.ingest(
            run_id=run_id,
            backend_role=backend_role,
            target_identity_sha256=target_identity_sha256,
            record=record,
        )

    def _trusted_lifecycle(self) -> ManagedComparisonHttpLifecycleAdapter:
        _require_lifecycle_stable(self._lifecycle, self._lifecycle_implementation)
        return self._lifecycle


@final
@dataclass(frozen=True, slots=True)
class ManagedProductionLifecyclePorts:
    """Operation-segregated runtime ports sharing one lifecycle state machine."""

    reset: ManagedProductionResetPort
    ingest: ManagedProductionIngestPort

    def __post_init__(self) -> None:
        if (
            type(self.reset) is not ManagedProductionResetPort
            or type(self.ingest) is not ManagedProductionIngestPort
            or self.reset is self.ingest
        ):
            raise ManagedProductionPortError("managed_production_ports_invalid")

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("ManagedProductionLifecyclePorts is final")


def create_managed_production_lifecycle_ports(
    lifecycle: ManagedComparisonHttpLifecycleAdapter,
) -> ManagedProductionLifecyclePorts:
    """Create distinct reset and ingest capabilities over one exact adapter."""

    _trusted_lifecycle_implementation(lifecycle)
    return ManagedProductionLifecyclePorts(
        reset=ManagedProductionResetPort(lifecycle),
        ingest=ManagedProductionIngestPort(lifecycle),
    )


def _trusted_lifecycle_implementation(
    lifecycle: object,
) -> str:
    if type(lifecycle) is not ManagedComparisonHttpLifecycleAdapter:
        raise ManagedProductionPortError("managed_production_lifecycle_invalid")
    implementation = managed_http_lifecycle_implementation_sha256()
    if lifecycle.adapter_id != MANAGED_HTTP_LIFECYCLE_ADAPTER_ID or not hmac.compare_digest(
        lifecycle.implementation_sha256, implementation
    ):
        raise ManagedProductionPortError("managed_production_lifecycle_changed")
    return implementation


def _require_lifecycle_stable(lifecycle: object, expected: str) -> None:
    current = _trusted_lifecycle_implementation(lifecycle)
    if not hmac.compare_digest(current, expected):
        raise ManagedProductionPortError("managed_production_lifecycle_changed")


def _facade_implementation(adapter_id: str, lifecycle_implementation: str) -> str:
    return hashlib.sha256(f"{adapter_id}\0{lifecycle_implementation}".encode()).hexdigest()


__all__ = (
    "MANAGED_PRODUCTION_INGEST_ADAPTER_ID",
    "MANAGED_PRODUCTION_RESET_ADAPTER_ID",
    "ManagedProductionIngestPort",
    "ManagedProductionLifecyclePorts",
    "ManagedProductionPortError",
    "ManagedProductionResetPort",
    "create_managed_production_lifecycle_ports",
)
