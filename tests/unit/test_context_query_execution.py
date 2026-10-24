"""Scheduling tests use barriers, not timing thresholds."""

from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.application.context_query_execution import collect_query_results


def test_query_fanout_is_bounded_and_reduces_in_query_order():
    async def exercise():
        entered = []
        active = peak = 0
        ready = asyncio.Event()
        release = [asyncio.Event() for _ in range(8)]

        async def search(index):
            nonlocal active, peak
            entered.append(index)
            active += 1
            peak = max(peak, active)
            if len(entered) == 4:
                ready.set()
            try:
                await release[index].wait()
                return f"result-{index}"
            finally:
                active -= 1

        operation = asyncio.create_task(
            collect_query_results(tuple(range(8)), search, timeout_seconds=None)
        )
        async with asyncio.timeout(5):
            await ready.wait()
            assert entered == [0, 1, 2, 3]
            for index in reversed(range(8)):
                release[index].set()
            assert await operation == tuple(f"result-{index}" for index in range(8))
        assert peak == 4
        assert active == 0

    asyncio.run(exercise())


def test_query_failures_are_isolated_and_slots_reused():
    async def exercise():
        seen = []

        async def search(index):
            seen.append(index)
            if index in (1, 5):
                raise ValueError(f"failure-{index}")
            return index

        results = await collect_query_results(tuple(range(8)), search, timeout_seconds=1)
        assert sorted(seen) == list(range(8))
        assert [str(result) for result in results] == [
            "0",
            "failure-1",
            "2",
            "3",
            "4",
            "failure-5",
            "6",
            "7",
        ]
        assert isinstance(results[1], ValueError)

    asyncio.run(exercise())


def test_query_timeout_cleans_up_before_reusing_slot():
    async def exercise():
        cleanup = []

        async def search(index):
            if index == 0:
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup.append(index)
            assert cleanup == [0]
            return index

        results = await collect_query_results((0, 1), search, timeout_seconds=0.01, concurrency=1)
        assert isinstance(results[0], TimeoutError)
        assert results[1] == 1

    asyncio.run(exercise())


def test_repeated_caller_cancellation_drains_active_queries_and_never_starts_queued_queries():
    async def exercise():
        entered = []
        cleaned = []
        ready = asyncio.Event()
        cleaning = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def search(index):
            entered.append(index)
            if len(entered) == 4:
                ready.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release_cleanup.wait()
                cleaned.append(index)

        operation = asyncio.create_task(
            collect_query_results(tuple(range(8)), search, timeout_seconds=10)
        )
        async with asyncio.timeout(5):
            await ready.wait()
            operation.cancel()
            await cleaning.wait()
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done()
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
        assert sorted(entered) == [0, 1, 2, 3]
        assert sorted(cleaned) == [0, 1, 2, 3]
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())


def test_child_cancellation_is_not_converted_to_provider_degradation():
    async def exercise():
        async def search(index):
            if index == 0:
                raise asyncio.CancelledError
            await asyncio.Event().wait()

        with pytest.raises(asyncio.CancelledError):
            await collect_query_results((0, 1), search, timeout_seconds=None)
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("concurrency", [0, -1, 5, True, 1.5])
def test_invalid_query_concurrency_is_rejected(concurrency):
    async def search(query):
        return query

    with pytest.raises(ValueError, match="query concurrency"):
        asyncio.run(collect_query_results((1,), search, timeout_seconds=1, concurrency=concurrency))


def test_empty_queries_do_not_invoke_provider():
    async def search(query):
        pytest.fail("empty query set invoked provider")

    assert asyncio.run(collect_query_results((), search, timeout_seconds=1)) == ()
