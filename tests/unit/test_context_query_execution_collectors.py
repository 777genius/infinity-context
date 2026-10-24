"""Each collector fans out provider work but hydrates only after all calls finish."""

from __future__ import annotations

import asyncio

import pytest
from infinity_context_core.application.context_collectors import (
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
    _fused_ranked_keys,
)
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


@pytest.mark.parametrize("lane", ["vector", "graph", "rag"])
def test_collectors_bound_provider_fanout_preserve_order_and_isolate_failure(lane, monkeypatch):
    async def exercise():
        queries = tuple(f"query {i}" for i in range(8))
        results = {text: (f"chunk_{i}", "shared") for i, text in enumerate(queries)}
        chunks = {key: _chunk(key) for values in results.values() for key in values}
        active = peak = hydration_calls = 0
        entered, finished = [], []
        ready = asyncio.Event()
        release = [asyncio.Event() for _ in queries]

        class Hydrator(_RecordingHydrator):
            async def hydrate_visible_chunks(self, **kwargs):
                nonlocal hydration_calls
                assert active == 0
                assert len(finished) == 8
                hydration_calls += 1
                return await super().hydrate_visible_chunks(**kwargs)

            async def hydrate_graph_facts(self, **kwargs):
                nonlocal hydration_calls
                assert active == 0
                assert len(finished) == 8
                hydration_calls += 1
                return await super().hydrate_graph_facts(**kwargs)

        hydrator = Hydrator(chunks)
        if lane == "vector":
            provider = _VectorIndex(results)
            method = "search_chunks"
            collector = VectorContextCollector(
                vector_index=provider, embedder=_Embedder(), hydrator=hydrator
            )
        elif lane == "graph":
            provider = _GraphIndex(results)
            method = "search"
            collector = GraphContextCollector(graph_index=provider, hydrator=hydrator)
        else:
            provider = _RagRecall(results)
            method = "recall"
            collector = RagContextCollector(rag_recall=provider, hydrator=hydrator)
        original = getattr(provider, method)

        async def instrumented(*args, **kwargs):
            nonlocal active, peak
            text = args[0].query if args else kwargs.get("query_text", kwargs.get("query"))
            index = queries.index(text)
            active += 1
            peak = max(peak, active)
            entered.append(index)
            if len(entered) == 4:
                ready.set()
            try:
                await release[index].wait()
                if index == 2:
                    raise ValueError("private provider payload must not escape")
                return await original(*args, **kwargs)
            finally:
                active -= 1
                finished.append(index)

        monkeypatch.setattr(provider, method, instrumented)
        diagnostics = {}
        operation = asyncio.create_task(
            collector.collect(
                query=BuildContextQuery(
                    space_id=SpaceId("space_test"),
                    memory_scope_ids=(MemoryScopeId("scope_test"),),
                    query=queries[0],
                    max_chunks=20,
                    max_facts=20,
                ),
                memory_scope_ids=("scope_test",),
                diagnostics=diagnostics,
                query_plan=QueryExpansionPlan(
                    original_query=queries[0],
                    expansions=tuple(
                        QueryExpansion(query=text, reason=f"test_{i}")
                        for i, text in enumerate(queries[1:], 1)
                    ),
                ),
            )
        )
        async with asyncio.timeout(5):
            await ready.wait()
            assert entered == [0, 1, 2, 3]
            for index in reversed(range(8)):
                release[index].set()
            actual = await operation
        expected = _fused_ranked_keys(
            {
                f"{i}:{'original_query' if i == 0 else f'test_{i}'}": results[text]
                for i, text in enumerate(queries)
                if i != 2
            },
            limit=80,
        )
        ids = tuple(str(item.id) if lane == "vector" else item.item_id for item in actual)
        assert ids == expected
        assert peak == 4
        assert hydration_calls == 1
        assert diagnostics[f"{lane}_query_degraded_count"] == 1
        assert diagnostics[f"{lane}_candidate_count"] == 14
        assert "private provider payload" not in str(diagnostics)
        assert len(asyncio.all_tasks()) == 1

    asyncio.run(exercise())
