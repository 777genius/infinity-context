"""Own concurrent derived collectors while preserving their static merge order."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import TypeVar

from infinity_context_core.application.context_stage_diagnostics import (
    record_context_stage_interval,
)

_Vector = TypeVar("_Vector")
_Graph = TypeVar("_Graph")
_Rag = TypeVar("_Rag")
_Result = TypeVar("_Result")


async def collect_derived_context(
    *,
    vector: Callable[[dict[str, object]], Awaitable[_Vector]],
    graph: Callable[[dict[str, object]], Awaitable[_Graph]],
    rag: Callable[[dict[str, object]], Awaitable[_Rag]],
    diagnostics: dict[str, object],
) -> tuple[_Vector, _Graph, _Rag]:
    """Join every owned task before publishing results or propagating failure."""
    tasks = (
        asyncio.create_task(_collect_lane(vector)),
        asyncio.create_task(_collect_lane(graph)),
        asyncio.create_task(_collect_lane(rag)),
    )
    completion = asyncio.gather(*tasks)
    try:
        vector_result, graph_result, rag_result = await asyncio.shield(completion)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        cleanup = asyncio.gather(*tasks, return_exceptions=True)
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                # Repeated caller cancellation must not abandon child cleanup.
                continue
        if not completion.cancelled():
            completion.exception()
        raise
    for stage, (_, lane_diagnostics, started, finished) in zip(
        ("vector_collect", "graph_collect", "rag_collect"),
        (vector_result, graph_result, rag_result),
        strict=True,
    ):
        diagnostics.update(
            (key, value) for key, value in lane_diagnostics.items() if key != "stage_timings_ms"
        )
        record_context_stage_interval(
            diagnostics, stage=stage, started_at=started, finished_at=finished
        )
    return vector_result[0], graph_result[0], rag_result[0]


async def _collect_lane(
    collect: Callable[[dict[str, object]], Awaitable[_Result]],
) -> tuple[_Result, dict[str, object], float, float]:
    diagnostics: dict[str, object] = {}
    started = perf_counter()
    result = await collect(diagnostics)
    return result, diagnostics, started, perf_counter()
