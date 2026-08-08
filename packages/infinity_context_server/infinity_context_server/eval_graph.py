"""Graph-specific helpers for deterministic eval suites."""

from __future__ import annotations

from infinity_context_core.application import BuildContextUseCase
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.ports.adapters import (
    AdapterCapabilities,
    GraphCandidate,
    GraphSearchResult,
)


class EvalGraphMemoryAdapter:
    def __init__(self) -> None:
        self._aliases: dict[str, tuple[str | None, ...]] = {}
        self.search_calls: list[dict[str, object]] = []

    def set_aliases(self, aliases: dict[str, tuple[str | None, ...]]) -> None:
        self._aliases = {key.lower(): value for key, value in aliases.items()}

    async def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="eval-graph",
            enabled=True,
            healthy=True,
            supports_upsert=True,
            supports_delete=True,
            supports_search=True,
            supports_filters=True,
            supports_temporal_queries=True,
        )

    async def search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None = None,
        query: str,
        limit: int,
    ) -> GraphSearchResult:
        self.search_calls.append(
            {
                "space_id": space_id,
                "memory_scope_ids": memory_scope_ids,
                "thread_id": thread_id,
                "query": query,
                "limit": limit,
            }
        )
        candidate_ids = self._aliases.get(query.lower(), ())
        candidates: list[GraphCandidate] = []
        for index, fact_id in enumerate(candidate_ids[:limit]):
            if fact_id is None:
                candidates.append(
                    GraphCandidate(
                        source_fact_ids=(),
                        source_chunk_ids=(),
                        relation_label="eval_orphan_relation",
                        score=max(0.1, 0.99 - index * 0.01),
                        diagnostics={"provider": "eval-graph"},
                    )
                )
                continue
            candidates.append(
                GraphCandidate(
                    source_fact_ids=(fact_id,),
                    source_chunk_ids=(),
                    relation_label="eval_temporal_relation",
                    score=max(0.1, 0.99 - index * 0.01),
                    diagnostics={"provider": "eval-graph"},
                )
            )
        return GraphSearchResult.ok(candidates)


def _install_eval_graph_adapter(app, graph: EvalGraphMemoryAdapter) -> None:
    container = app.state.container
    graph_context = BuildContextUseCase(
        uow_factory=container.uow_factory,
        ids=container.ids,
        vector_index=container.vector_index,
        graph_index=graph,
        embedder=container.embedder,
        clock=container.clock,
        rag_recall=container.cognee_memory,
        packer=ContextPacker(),
        blob_storage=container.blob_storage,
        fact_selection=container.canonical_fact_selection,
    )
    object.__setattr__(container, "graph_index", graph)
    object.__setattr__(container, "build_context", graph_context)
