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
from memo_stack_core.ports.clock import ClockPort
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
        clock: ClockPort | None = None,
        rag_recall: RagRecallPort | None = None,
        packer: ContextPacker | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._vector_index = vector_index
        self._graph_index = graph_index
        self._embedder = embedder
        self._packer = packer or ContextPacker()
        self._hydrator = ContextHydrator(uow_factory=uow_factory, clock=clock)
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
        pending_conflicts = await self._pending_conflict_items(
            query=query,
            visible_fact_ids=tuple(
                item.item_id for item in deduped if item.item_type == "fact"
            ),
        )
        result = self._packer.pack(
            bundle_id=self._ids.new_id("ctx"),
            items=dedupe_rank_items((*deduped, *pending_conflicts)),
            token_budget=query.token_budget,
            max_rendered_chars=query.max_rendered_chars,
        )
        diagnostics.update(result.bundle.diagnostics)
        diagnostics["pending_conflict_suggestions_considered"] = len(pending_conflicts)
        return ContextBundle(
            bundle_id=result.bundle.bundle_id,
            rendered_text=result.bundle.rendered_text,
            items=result.bundle.items,
            token_estimate=result.bundle.token_estimate,
            diagnostics=diagnostics,
        )

    async def _pending_conflict_items(
        self,
        *,
        query: BuildContextQuery,
        visible_fact_ids: tuple[str, ...],
    ) -> tuple[ContextItem, ...]:
        max_items = max(0, query.max_conflicting_suggestions)
        visible_fact_id_set = set(visible_fact_ids)
        if max_items <= 0 or not visible_fact_id_set:
            return ()

        items: list[ContextItem] = []
        async with self._uow_factory() as uow:
            for profile_id in query.profile_ids:
                if len(items) >= max_items:
                    break
                suggestions = await uow.suggestions.list_for_scope(
                    space_id=str(query.space_id),
                    profile_id=str(profile_id),
                    status="pending",
                    operation=None,
                    category=None,
                    tag=None,
                    limit=max(20, max_items * 4),
                )
                for suggestion in suggestions:
                    conflict_fact_id = _suggestion_conflict_fact_id(suggestion)
                    if conflict_fact_id not in visible_fact_id_set:
                        continue
                    items.append(
                        ContextItem(
                            item_id=str(suggestion.id),
                            item_type="suggestion",
                            text=_conflict_suggestion_text(
                                candidate_text=suggestion.candidate_text,
                                operation=suggestion.operation.value,
                                conflict_fact_id=conflict_fact_id,
                            ),
                            score=0.94,
                            source_refs=suggestion.source_refs,
                            diagnostics={
                                "profile_id": str(suggestion.profile_id),
                                "retrieval_source": "pending_conflict_suggestion",
                                "status": suggestion.status.value,
                                "operation": suggestion.operation.value,
                                "canonical": False,
                                "conflicting_fact_id": conflict_fact_id,
                            },
                        )
                    )
                    if len(items) >= max_items:
                        return tuple(items)
        return tuple(items)


def _suggestion_conflict_fact_id(suggestion) -> str | None:
    payload = suggestion.review_payload or {}
    for key in ("conflicting_fact_id", "conflict_fact_id", "possible_conflict_fact_id"):
        value = payload.get(key)
        if value:
            return str(value)
    if suggestion.target_fact_id:
        return str(suggestion.target_fact_id)
    return None


def _conflict_suggestion_text(
    *,
    candidate_text: str,
    operation: str,
    conflict_fact_id: str,
) -> str:
    return (
        f"Pending review {operation} suggestion for active fact {conflict_fact_id}: "
        f"{candidate_text}"
    )
