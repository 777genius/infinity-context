"""Bound external query work without changing query-order reduction or ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar, cast

_Query = TypeVar("_Query")
_Result = TypeVar("_Result")
_MAX_QUERY_CONCURRENCY = 4


async def collect_query_results(
    queries: tuple[_Query, ...],
    search: Callable[[_Query], Awaitable[_Result]],
    *,
    timeout_seconds: float | None,
    concurrency: int = _MAX_QUERY_CONCURRENCY,
) -> tuple[_Result | Exception, ...]:
    """Return ordered outcomes; isolate provider errors, but propagate cancellation.

    Only workers own provider calls. A timeout starts when a worker takes a query,
    not while that query waits for a slot. Callers perform canonical hydration
    after this function returns, never through a shared database session here.
    """
    if type(concurrency) is not int or not 1 <= concurrency <= _MAX_QUERY_CONCURRENCY:
        raise ValueError("query concurrency must be an integer between 1 and 4")
    if not queries:
        return ()
    stopping = False
    pending = iter(enumerate(queries))
    results: list[_Result | Exception | None] = [None] * len(queries)

    async def worker() -> None:
        for index, query in pending:
            if stopping:
                return
            try:
                operation = search(query)
                results[index] = (
                    await operation
                    if timeout_seconds is None
                    else await asyncio.wait_for(operation, timeout=timeout_seconds)
                )
            except Exception as exc:
                results[index] = exc

    tasks = tuple(asyncio.create_task(worker()) for _ in range(min(concurrency, len(queries))))
    completion = asyncio.gather(*tasks)
    try:
        await asyncio.shield(completion)
    except BaseException:
        stopping = True
        for task in tasks:
            if not task.done():
                task.cancel()
        cleanup = asyncio.gather(*tasks, return_exceptions=True)
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Repeated cancellation cannot abandon provider cleanup.
                continue
        if not completion.cancelled():
            completion.exception()
        raise
    # Every query was consumed by a joined worker; None may itself be a valid result.
    return cast(tuple[_Result | Exception, ...], tuple(results))
