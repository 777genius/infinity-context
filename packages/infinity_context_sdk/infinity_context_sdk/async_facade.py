"""Owned event-loop execution for cancellable synchronous SDK facades."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from queue import SimpleQueue
from threading import Thread
from typing import TypeVar

_ResultT = TypeVar("_ResultT")


def run_on_owned_loop(factory: Callable[[], Awaitable[_ResultT]]) -> _ResultT:
    """Run one awaitable to completion on one joined, non-daemon loop thread."""

    outcome: SimpleQueue[tuple[bool, object]] = SimpleQueue()

    def run() -> None:
        try:
            outcome.put((True, asyncio.run(factory())))
        except BaseException as exc:
            outcome.put((False, exc))

    worker = Thread(target=run, name="infinity-sdk-owned-loop", daemon=False)
    worker.start()
    worker.join()
    succeeded, value = outcome.get()
    if succeeded:
        return value  # type: ignore[return-value]
    assert isinstance(value, BaseException)
    raise value


__all__ = ("run_on_owned_loop",)
