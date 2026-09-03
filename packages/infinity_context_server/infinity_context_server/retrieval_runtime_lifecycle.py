"""Process-scoped lifecycle for the Retrieval runtime fence owner."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from infinity_context_core.features.context_building.public import RuntimeFenceOwner

_T = TypeVar("_T")
_CANCEL_DRAIN_SECONDS = 0.01


async def complete_despite_cancellation(
    awaitable: Awaitable[_T],
    *,
    deadline_monotonic: float,
) -> tuple[_T, asyncio.CancelledError | None]:
    """Resolve a durable phase without outliving its request deadline."""

    task = asyncio.ensure_future(awaitable)
    loop = asyncio.get_running_loop()
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        remaining = deadline_monotonic - loop.time()
        if remaining <= 0:
            await _cancel_and_drain(task, deadline_monotonic=deadline_monotonic)
            raise TimeoutError
        cancel_at = deadline_monotonic - min(_CANCEL_DRAIN_SECONDS, remaining / 10)
        try:
            async with asyncio.timeout_at(cancel_at):
                await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc
            current = asyncio.current_task()
            if current is not None:
                current.uncancel()
        except TimeoutError:
            await _cancel_and_drain(task, deadline_monotonic=deadline_monotonic)
            raise
    return task.result(), cancellation


async def _cancel_and_drain(task: asyncio.Future[Any], *, deadline_monotonic: float) -> None:
    """Cancel and drain only while the absolute request deadline permits."""

    if not task.done():
        task.cancel()
    try:
        async with asyncio.timeout_at(deadline_monotonic):
            await asyncio.shield(task)
    except (asyncio.CancelledError, Exception):
        pass
    if not task.done():
        task.add_done_callback(_consume_terminal_exception)


def _consume_terminal_exception(task: asyncio.Future[Any]) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.exception()


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
