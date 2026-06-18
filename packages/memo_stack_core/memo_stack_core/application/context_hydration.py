"""Hydrate derived candidates through canonical repositories."""

from __future__ import annotations

from memo_stack_core.application.context_policy import (
    is_context_fact_visible,
    is_graph_fact_visible,
)
from memo_stack_core.application.document_text import document_chunk_retrieval_text
from memo_stack_core.application.dto import BuildContextQuery, ContextItem
from memo_stack_core.application.source_refs import chunk_source_refs
from memo_stack_core.domain.entities import MemoryChunk
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ContextHydrator:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[MemoryChunk, ...]:
        async with self._uow_factory() as uow:
            chunks = await uow.chunks.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                space_id=str(query.space_id),
                memory_scope_ids=memory_scope_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
            )
        return tuple(chunks)

    async def hydrate_graph_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        async with self._uow_factory() as uow:
            hydrated: list[ContextItem] = []
            stale_count = 0
            now = self._clock.now() if self._clock is not None else None
            for fact_id in fact_ids:
                fact = await uow.facts.get_by_id(fact_id)
                if fact is not None and is_graph_fact_visible(
                    fact,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    now=now,
                ):
                    hydrated.append(
                        ContextItem(
                            item_id=str(fact.id),
                            item_type="fact",
                            text=fact.text,
                            score=0.78,
                            source_refs=fact.source_refs,
                            diagnostics={
                                "memory_scope_id": str(fact.memory_scope_id),
                                "retrieval_source": "graph_hydrated",
                                "retrieval_sources": ["graph_hydrated"],
                                "ranking_reason": "graph candidate resolved to visible active fact",
                                "score_signals": {
                                    "base_score": 0.78,
                                    "retrieval_channel": "graph_hydrated",
                                    "fact_status": fact.status.value,
                                },
                                "provenance": {
                                    "retrieval_sources": ["graph_hydrated"],
                                    "source_ref_count": len(fact.source_refs),
                                    "fact_status": fact.status.value,
                                    "fact_version": fact.version,
                                },
                            },
                        )
                    )
                else:
                    stale_count += 1
        return tuple(hydrated), stale_count

    async def revalidate_visible_items(
        self,
        items: tuple[ContextItem, ...],
        *,
        query: BuildContextQuery,
        memory_scope_ids: tuple[str, ...],
    ) -> tuple[ContextItem, ...]:
        if not items:
            return ()

        chunk_ids = tuple(item.item_id for item in items if item.item_type == "chunk")
        visible_chunks = {
            str(chunk.id): chunk
            for chunk in await self.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                query=query,
                memory_scope_ids=memory_scope_ids,
            )
        }
        async with self._uow_factory() as uow:
            visible_facts = {}
            now = self._clock.now() if self._clock is not None else None
            for item in items:
                if item.item_type != "fact":
                    continue
                fact = await uow.facts.get_by_id(item.item_id)
                if fact is not None and is_context_fact_visible(
                    fact,
                    query=query,
                    memory_scope_ids=memory_scope_ids,
                    now=now,
                ):
                    visible_facts[str(fact.id)] = fact

        visible_items: list[ContextItem] = []
        for item in items:
            if item.item_type == "fact":
                fact = visible_facts.get(item.item_id)
                if fact is None:
                    continue
                visible_items.append(
                    ContextItem(
                        item_id=str(fact.id),
                        item_type=item.item_type,
                        text=fact.text,
                        score=item.score,
                        source_refs=fact.source_refs,
                        is_instruction=item.is_instruction,
                        diagnostics=item.diagnostics,
                    )
                )
            elif item.item_type == "chunk":
                chunk = visible_chunks.get(item.item_id)
                if chunk is None:
                    continue
                chunk_text = document_chunk_retrieval_text(
                    text=chunk.text,
                    metadata=chunk.metadata,
                )
                visible_items.append(
                    ContextItem(
                        item_id=str(chunk.id),
                        item_type=item.item_type,
                        text=chunk_text,
                        score=item.score,
                        source_refs=chunk_source_refs(chunk, text_preview=chunk_text),
                        is_instruction=item.is_instruction,
                        diagnostics=item.diagnostics,
                    )
                )
        return tuple(visible_items)
