"""Expired provider responses never enter ranking, even after cancellation suppression."""

from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.application.context_collectors import (
    ContextRetrievalDeadlines,
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
)
from infinity_context_core.application.context_query_execution import collect_query_results
from infinity_context_core.application.context_query_expansion import (
    QueryExpansion,
    QueryExpansionPlan,
)
from infinity_context_core.application.dto import BuildContextQuery
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId

from tests.unit.test_context_candidate_fusion_equivalence import (
    _chunk,
    _Embedder,
    _GraphIndex,
    _RagRecall,
    _RecordingHydrator,
    _VectorIndex,
)


def test_expired_result_is_rejected_and_cleanup_finishes_before_slot_reuse():
    async def exercise():
        cleaning, release = asyncio.Event(), asyncio.Event()
        entered, cleaned = [], []

        async def search(index):
            entered.append(index)
            if index == 0:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cleaning.set()
                    await release.wait()
                    cleaned.append(index)
                    return "late response"
            assert cleaned == [0]
            return "on time"

        operation = asyncio.create_task(
            collect_query_results((0, 1), search, timeout_seconds=0.01, concurrency=1)
        )
        async with asyncio.timeout(5):
            await cleaning.wait()
            assert entered == [0]
            assert not operation.done()
            release.set()
            results = await operation
        assert isinstance(results[0], TimeoutError)
        assert results[1] == "on time"
        assert entered == [0, 1]
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())


def test_caller_cancellation_during_timeout_cleanup_does_not_release_queued_work():
    async def exercise():
        cleaning, release = asyncio.Event(), asyncio.Event()
        entered, cleaned = [], []

        async def search(index):
            entered.append(index)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleaning.set()
                while not release.is_set():
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        continue
                cleaned.append(index)
                return "late response"

        operation = asyncio.create_task(
            collect_query_results((0, 1), search, timeout_seconds=0.01, concurrency=1)
        )
        async with asyncio.timeout(5):
            await cleaning.wait()
            operation.cancel()
            await asyncio.sleep(0)
            operation.cancel()
            await asyncio.sleep(0)
            assert not operation.done()
            assert entered == [0]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
        assert entered == cleaned == [0]
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["vector", "graph", "rag"])
def test_collectors_drop_late_results_before_hydration_and_ranking(lane, monkeypatch):
    async def exercise():
        results_by_query = {"late query": ("late",), "healthy query": ("healthy",)}
        hydrated = []
        cleanup_finished = False

        class Hydrator(_RecordingHydrator):
            async def hydrate_visible_chunks(self, **kwargs):
                assert cleanup_finished
                hydrated.extend(kwargs["chunk_ids"])
                return await super().hydrate_visible_chunks(**kwargs)

            async def hydrate_graph_facts(self, **kwargs):
                assert cleanup_finished
                hydrated.extend(kwargs["fact_ids"])
                return await super().hydrate_graph_facts(**kwargs)

        hydrator = Hydrator({key: _chunk(key) for key in ("late", "healthy")})
        deadlines = ContextRetrievalDeadlines(
            vector_search_seconds=0.01, graph_search_seconds=0.01, rag_recall_seconds=0.01
        )
        if lane == "vector":
            provider = _VectorIndex(results_by_query)
            method = "search_chunks"
            collector = VectorContextCollector(
                vector_index=provider, embedder=_Embedder(), hydrator=hydrator, deadlines=deadlines
            )
        elif lane == "graph":
            provider = _GraphIndex(results_by_query)
            method = "search"
            collector = GraphContextCollector(
                graph_index=provider, hydrator=hydrator, deadlines=deadlines
            )
        else:
            provider = _RagRecall(results_by_query)
            method = "recall"
            collector = RagContextCollector(
                rag_recall=provider, hydrator=hydrator, deadlines=deadlines
            )
        original = getattr(provider, method)

        async def suppressing_provider(*args, **kwargs):
            nonlocal cleanup_finished
            text = args[0].query if args else kwargs.get("query_text", kwargs.get("query"))
            if text == "late query":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await asyncio.sleep(0)
                    cleanup_finished = True
            return await original(*args, **kwargs)

        monkeypatch.setattr(provider, method, suppressing_provider)
        diagnostics = {}
        async with asyncio.timeout(5):
            result = await collector.collect(
                query=BuildContextQuery(
                    space_id=SpaceId("space_test"),
                    memory_scope_ids=(MemoryScopeId("scope_test"),),
                    query="late query",
                    max_chunks=4,
                    max_facts=4,
                ),
                memory_scope_ids=("scope_test",),
                query_plan=QueryExpansionPlan(
                    original_query="late query",
                    expansions=(QueryExpansion(query="healthy query", reason="test"),),
                ),
                diagnostics=diagnostics,
            )
        assert hydrated == ["healthy"]
        assert len(result) == 1
        assert diagnostics[f"{lane}_query_degraded_count"] == 1
        assert diagnostics[f"{lane}_degraded_reason"] == f"{lane}.timeout"
        assert diagnostics[f"{lane}_candidate_count"] == 1
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_nonpositive_deadline_does_not_start_provider(timeout_seconds):
    async def search(query):
        pytest.fail("an expired query budget must not invoke the provider")

    results = asyncio.run(collect_query_results((0,), search, timeout_seconds=timeout_seconds))
    assert len(results) == 1
    assert isinstance(results[0], TimeoutError)
