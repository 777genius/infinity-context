"""Process-scoped lifecycle for the Retrieval runtime fence owner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeVar

from infinity_context_core.features.context_building.public import RuntimeFenceOwner

_T = TypeVar("_T")


async def complete_despite_cancellation(
    awaitable: Awaitable[_T],
) -> tuple[_T, asyncio.CancelledError | None]:
    """Resolve an idempotent durable phase before propagating cancellation."""

    task = asyncio.ensure_future(awaitable)
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
    return task.result(), cancellation


@dataclass(slots=True)
class RetrievalRuntimeLifecycle:
    """Register once after readiness and retire once after process draining."""

    registry: object
    owner: RuntimeFenceOwner
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _registered: bool = field(default=False, init=False, repr=False)
    _retired: bool = field(default=False, init=False, repr=False)

    async def start(self, *, now: datetime) -> None:
        async with self._lock:
            if self._retired:
                raise RuntimeError("retrieval_profile_runtime_lifecycle_retired")
            if self._registered:
                return
            await self.registry.register_runtime_incarnation(self.owner, now=now)
            self._registered = True

    async def close(self, *, now: datetime) -> None:
        async with self._lock:
            if self._retired or not self._registered:
                return
            await self.registry.retire_runtime_incarnation(self.owner, now=now)
            self._registered = False
            self._retired = True


@dataclass(frozen=True, slots=True)
class ProviderFreeRetrievalRuntimeLifecycle:
    """No-op lifecycle for local runtimes with no derived retrieval provider."""

    async def start(self, *, now: datetime) -> None:
        del now

    async def close(self, *, now: datetime) -> None:
        del now


__all__ = (
    "ProviderFreeRetrievalRuntimeLifecycle",
    "RetrievalRuntimeLifecycle",
    "complete_despite_cancellation",
)
