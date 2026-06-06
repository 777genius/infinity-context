"""Build prompt-safe memory context from canonical and derived candidates."""

from __future__ import annotations

from memo_stack_core.application.context_collectors import (
    CanonicalContextCollector,
    GraphContextCollector,
    RagContextCollector,
    VectorContextCollector,
)
from memo_stack_core.application.context_hydration import ContextHydrator
from memo_stack_core.application.context_packer import ContextPacker
from memo_stack_core.application.context_ranking import dedupe_rank_items
from memo_stack_core.application.document_text import document_chunk_retrieval_text
from memo_stack_core.application.dto import (
    BuildContextQuery,
    ConsistencyMode,
    ContextBundle,
    ContextItem,
)
from memo_stack_core.domain.entities import SourceRef
from memo_stack_core.ports.adapters import EmbeddingPort, GraphMemoryPort, VectorMemoryPort
from memo_stack_core.ports.capabilities import RagRecallPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class BuildContextUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        ids: IdGeneratorPort,
        vector_index: VectorMemoryPort,
        graph_index: GraphMemoryPort,
        embedder: EmbeddingPort,
        rag_recall: RagRecallPort | None = None,
        packer: ContextPacker | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._vector_index = vector_index
        self._graph_index = graph_index
        self._embedder = embedder
        self._packer = packer or ContextPacker()
        self._hydrator = ContextHydrator(uow_factory=uow_factory)
        self._canonical_collector = CanonicalContextCollector(uow_factory=uow_factory)
        self._vector_collector = VectorContextCollector(
            vector_index=vector_index,
            embedder=embedder,
            hydrator=self._hydrator,
        )
        self._graph_collector = GraphContextCollector(
            graph_index=graph_index,
            hydrator=self._hydrator,
        )
        self._rag_collector = RagContextCollector(
            rag_recall=rag_recall,
            hydrator=self._hydrator,
        )

    async def execute(self, query: BuildContextQuery) -> ContextBundle:
        profile_ids = tuple(str(profile_id) for profile_id in query.profile_ids)
        canonical = await self._canonical_collector.collect(query=query, profile_ids=profile_ids)

        diagnostics: dict[str, object] = {
            "consistency_mode": query.consistency_mode.value,
            "facts_considered": len(canonical.facts),
            "keyword_chunks_considered": len(canonical.keyword_chunks),
            "vector_status": "disabled",
            "graph_status": "disabled",
            "rag_status": "disabled",
            "vector_candidate_count": 0,
            "vector_hydrated_count": 0,
            "graph_candidate_count": 0,
            "graph_hydrated_count": 0,
            "stale_vector_drop_count": 0,
            "stale_graph_drop_count": 0,
            "stale_rag_drop_count": 0,
        }
        if query.consistency_mode == ConsistencyMode.CANONICAL_ONLY:
            diagnostics["vector_status"] = "skipped"
            diagnostics["vector_skip_reason"] = "canonical_only"
            diagnostics["graph_status"] = "skipped"
            diagnostics["graph_skip_reason"] = "canonical_only"
            diagnostics["rag_status"] = "skipped"
            diagnostics["rag_skip_reason"] = "canonical_only"
            vector_chunks = ()
            graph_items = ()
            rag_items = ()
        else:
            vector_chunks = await self._vector_collector.collect(
                query=query,
                profile_ids=profile_ids,
                diagnostics=diagnostics,
            )
            graph_items = await self._graph_collector.collect(
                query=query,
                profile_ids=profile_ids,
                diagnostics=diagnostics,
            )
            rag_items = await self._rag_collector.collect(
                query=query,
                profile_ids=profile_ids,
                diagnostics=diagnostics,
            )

        items: list[ContextItem] = []
        for fact in canonical.facts:
            items.append(
                ContextItem(
                    item_id=str(fact.id),
                    item_type="fact",
                    text=fact.text,
                    score=0.95,
                    source_refs=fact.source_refs,
                    diagnostics={
                        "profile_id": str(fact.profile_id),
                        "retrieval_source": "postgres_facts",
                    },
                )
            )
        keyword_chunk_ids = {str(chunk.id) for chunk in canonical.keyword_chunks}
        for chunk in (*canonical.keyword_chunks, *vector_chunks):
            chunk_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            items.append(
                ContextItem(
                    item_id=str(chunk.id),
                    item_type="chunk",
                    text=chunk_text,
                    score=0.75 if str(chunk.id) in keyword_chunk_ids else 0.82,
                    source_refs=(
                        SourceRef(
                            source_type=chunk.source_type,
                            source_id=chunk.source_external_id,
                            chunk_id=str(chunk.id),
                            char_start=chunk.char_start,
                            char_end=chunk.char_end,
                            quote_preview=chunk_text[:200],
                        ),
                    ),
                    diagnostics={
                        "profile_id": str(chunk.profile_id),
                        "retrieval_source": "chunks",
                    },
                )
            )
        items.extend(graph_items)
        items.extend(rag_items)

        deduped = await self._hydrator.revalidate_visible_items(
            dedupe_rank_items(tuple(items)),
            query=query,
            profile_ids=profile_ids,
        )
        result = self._packer.pack(
            bundle_id=self._ids.new_id("ctx"),
            items=deduped,
            token_budget=query.token_budget,
            max_rendered_chars=query.max_rendered_chars,
        )
        diagnostics.update(result.bundle.diagnostics)
        return ContextBundle(
            bundle_id=result.bundle.bundle_id,
            rendered_text=result.bundle.rendered_text,
            items=result.bundle.items,
            token_estimate=result.bundle.token_estimate,
            diagnostics=diagnostics,
        )
