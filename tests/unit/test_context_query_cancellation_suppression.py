"""Cancelled fanout must not admit queued calls even if an adapter swallows cancellation."""

from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.application.context_query_execution import collect_query_results


@pytest.mark.parametrize("timeout_seconds", [None, 10.0])
@pytest.mark.parametrize("convert_to_error", [False, True])
def test_cancelled_fanout_stops_admission_when_provider_suppresses_cancellation(
    timeout_seconds, convert_to_error
):
    async def exercise():
        entered = []
        cleaned = []
        ready = asyncio.Event()

        async def search(index):
            entered.append(index)
            if index >= 4:
                return index
            if len(entered) == 4:
                ready.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if convert_to_error:
                    raise RuntimeError("provider converted cancellation") from None
                return index
            finally:
                cleaned.append(index)

        operation = asyncio.create_task(
            collect_query_results(tuple(range(8)), search, timeout_seconds=timeout_seconds)
        )
        async with asyncio.timeout(5):
            await ready.wait()
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
        assert entered == [0, 1, 2, 3]
        assert sorted(cleaned) == [0, 1, 2, 3]
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())
