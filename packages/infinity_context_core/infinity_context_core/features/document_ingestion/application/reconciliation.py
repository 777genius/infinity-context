"""Application boundary for exact-document reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.reconciliation import (
    ExactDocumentIdentity,
    ExactDocumentReconciliation,
    reconcile_exact_document,
)
from ..ports.reconciliation import ExactDocumentObservationPort


@dataclass(frozen=True, slots=True)
class ReconcileExactDocumentQuery:
    identity: ExactDocumentIdentity
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileExactDocumentHandler:
    observations: ExactDocumentObservationPort

    async def execute(self, query: ReconcileExactDocumentQuery) -> ExactDocumentReconciliation:
        observed = await self.observations.observe_exact_document(
            query.identity,
            idempotency_key=query.idempotency_key,
        )
        return reconcile_exact_document(query.identity, observed)


__all__ = ("ReconcileExactDocumentHandler", "ReconcileExactDocumentQuery")
