"""Narrow managed-run composition ports.

The high-level attestation policy depends only on these operation-specific
abstractions. Concrete provider SDKs and service clients stay in adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol


class ManagedPortIdentity(Protocol):
    """Safe provenance exposed by a composition-owned live adapter."""

    @property
    def adapter_id(self) -> str:
        """Return the stable adapter identifier."""

    @property
    def implementation_sha256(self) -> str:
        """Return the pinned implementation digest."""


class ManagedResetPort(ManagedPortIdentity, Protocol):
    """Reset both bound backends for one exact managed run."""

    def reset(
        self,
        *,
        run_id: str,
        binding_commitment_sha256: str,
        backend_targets: tuple[tuple[str, str], ...],
    ) -> None:
        """Complete the run-scoped reset before ingestion."""


class ManagedAttestationPort(ManagedPortIdentity, Protocol):
    """Produce the live managed-runtime capability for one run."""

    def attest(
        self,
        *,
        run_id: str,
        probe_nonce_sha256: str,
        target_identity_sha256: str,
    ) -> object:
        """Return an adapter-produced nominal runtime capability."""


class ManagedIngestPort(ManagedPortIdentity, Protocol):
    """Ingest one bounded record into one bound backend."""

    def ingest(
        self,
        *,
        run_id: str,
        backend_role: str,
        target_identity_sha256: str,
        record: Mapping[str, object],
    ) -> None:
        """Persist one record without exposing provider client types."""


class ManagedClockPort(ManagedPortIdentity, Protocol):
    """Provide the composition root's timezone-aware current clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware instant."""


__all__ = (
    "ManagedAttestationPort",
    "ManagedClockPort",
    "ManagedIngestPort",
    "ManagedPortIdentity",
    "ManagedResetPort",
)
