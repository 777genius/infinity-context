from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.application import context_derived_collection as module
from infinity_context_core.application.context_retrieval_performance import (
    cached_safe_metadata_text,
    remember_safe_metadata_text,
    with_request_retrieval_performance_cache,
)
from infinity_context_core.application.context_stage_diagnostics import (
    normalize_context_stage_timings,
)


def test_lanes_overlap_and_merge_results_diagnostics_and_spans_in_static_order(monkeypatch):
    async def exercise():
        entered = [asyncio.Event() for _ in range(3)]
        release = [asyncio.Event() for _ in range(3)]
        finished = [asyncio.Event() for _ in range(3)]
        private_maps = []
        clock = iter(range(6))
        monkeypatch.setattr(module, "perf_counter", lambda: next(clock))
        diagnostics = {"stage_timings_ms": {"canonical_collect": 7, "planning_expansion": 5}}

        def lane(index):
            async def collect(private):
                assert private == {}
                private_maps.append(private)
                entered[index].set()
                await release[index].wait()
                private[f"lane_{index}"] = "ok"
                private["same_key"] = index
                # Parent timing ownership is retained even for an accidental lane timing key.
                private["stage_timings_ms"] = {"scope_resolution": 999}
                finished[index].set()
                return index

            return collect

        operation = asyncio.create_task(
            module.collect_derived_context(
                vector=lane(0), graph=lane(1), rag=lane(2), diagnostics=diagnostics
            )
        )
        async with asyncio.timeout(2):
            await asyncio.gather(*(event.wait() for event in entered))
            for index in (2, 1, 0):
                release[index].set()
                await finished[index].wait()
            assert await operation == (0, 1, 2)
        assert len({id(private) for private in private_maps}) == 3
        assert diagnostics["same_key"] == 2
        assert [key for key in diagnostics if key.startswith("lane_")] == [
            "lane_0",
            "lane_1",
            "lane_2",
        ]
        timings = normalize_context_stage_timings(diagnostics["stage_timings_ms"])
        assert list(timings) == [
            "planning_expansion",
            "canonical_collect",
            "vector_collect",
            "graph_collect",
            "rag_collect",
        ]
        assert timings == {
            "planning_expansion": 5,
            "canonical_collect": 7,
            "vector_collect": 5000,
            "graph_collect": 3000,
            "rag_collect": 1000,
        }

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["cancel", "error"])
def test_parent_failure_cancels_and_joins_every_owned_lane(failure):
    async def exercise():
        entered = [asyncio.Event() for _ in range(3)]
        trigger = asyncio.Event()
        closed = []

        def lane(index):
            async def collect(private):
                entered[index].set()
                try:
                    if failure == "error" and index == 0:
                        await trigger.wait()
                        raise RuntimeError("unexpected collector failure")
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(0)
                    closed.append(index)

            return collect

        before = asyncio.all_tasks()
        operation = asyncio.create_task(
            module.collect_derived_context(
                vector=lane(0), graph=lane(1), rag=lane(2), diagnostics={}
            )
        )
        async with asyncio.timeout(2):
            await asyncio.gather(*(event.wait() for event in entered))
            if failure == "cancel":
                operation.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await operation
            else:
                trigger.set()
                with pytest.raises(RuntimeError, match="unexpected collector failure"):
                    await operation
        assert sorted(closed) == [0, 1, 2]
        assert asyncio.all_tasks() == before

    asyncio.run(exercise())


def test_repeated_parent_cancellation_waits_for_child_cleanup():
    async def exercise():
        entered = asyncio.Event()
        cleaning = asyncio.Event()
        release_cleanup = asyncio.Event()
        closed = []

        async def lane(private):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release_cleanup.wait()
                closed.append(True)

        operation = asyncio.create_task(
            module.collect_derived_context(vector=lane, graph=lane, rag=lane, diagnostics={})
        )
        async with asyncio.timeout(2):
            await entered.wait()
            operation.cancel()
            await cleaning.wait()
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done()
            release_cleanup.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
        assert len(closed) == 3

    asyncio.run(exercise())


def test_lane_tasks_inherit_context_without_retaining_it_in_next_request():
    @with_request_retrieval_performance_cache
    async def request(expected):
        assert cached_safe_metadata_text("derived-test-key") is None
        remember_safe_metadata_text("derived-test-key", expected)

        async def lane(private):
            return cached_safe_metadata_text("derived-test-key")

        assert await module.collect_derived_context(
            vector=lane, graph=lane, rag=lane, diagnostics={}
        ) == (expected, expected, expected)

    async def exercise():
        await request("first")
        assert cached_safe_metadata_text("derived-test-key") is None
        await request("next")
        assert cached_safe_metadata_text("derived-test-key") is None

    asyncio.run(exercise())
