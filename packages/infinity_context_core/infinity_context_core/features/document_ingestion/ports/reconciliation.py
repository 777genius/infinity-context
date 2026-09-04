"""Read-only port for bounded exact-document reconciliation."""

from __future__ import annotations

from typing import Protocol

from ..domain.reconciliation import ExactDocumentIdentity, ExactDocumentObservation


class ExactDocumentObservationPort(Protocol):
    async def observe_exact_document(
        self,
        identity: ExactDocumentIdentity,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[ExactDocumentObservation, ...]:
        """Return at most two observations so duplicate identity fails closed."""


__all__ = ("ExactDocumentObservationPort",)
