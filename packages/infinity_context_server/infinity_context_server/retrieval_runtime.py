"""Narrow process-lifecycle capability for the active Retrieval runtime."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_server.retrieval_profile_composition import ActiveReconciliationResult
from infinity_context_server.retrieval_runtime_lifecycle import (
    RetrievalRuntimeLifecycle as ProcessRetrievalRuntimeLifecycle,
)


class RetrievalRuntimeLifecycle(Protocol):
    async def start_runtime(self, *, now: datetime) -> None: ...

    async def close_runtime(self, *, now: datetime) -> None: ...

    async def reconcile_active(self, *, now: datetime) -> ActiveReconciliationResult: ...


@dataclass(frozen=True, slots=True)
class ActiveRetrievalRuntimeLifecycle:
    """Bind process fencing and active reconciliation behind one capability."""

    process: ProcessRetrievalRuntimeLifecycle
    reconciler: RetrievalRuntimeLifecycle

    async def start_runtime(self, *, now: datetime) -> None:
        await self.process.start(now=now)

    async def close_runtime(self, *, now: datetime) -> None:
        await self.process.close(now=now)

    async def reconcile_active(self, *, now: datetime) -> ActiveReconciliationResult:
        return await self.reconciler.reconcile_active(now=now)


@dataclass(frozen=True, slots=True)
class DisabledRetrievalRuntimeLifecycle:
    """Explicit no-op capability when no verified serving release is installed."""

    async def start_runtime(self, *, now: datetime) -> None:
        del now

    async def close_runtime(self, *, now: datetime) -> None:
        del now

    async def reconcile_active(self, *, now: datetime) -> ActiveReconciliationResult:
        del now
        return ActiveReconciliationResult(complete=True, renewed=False, outcome="disabled")


__all__ = (
    "ActiveRetrievalRuntimeLifecycle",
    "DisabledRetrievalRuntimeLifecycle",
    "RetrievalRuntimeLifecycle",
)
