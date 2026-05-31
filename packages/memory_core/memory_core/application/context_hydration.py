"""Hydrate derived candidates through canonical repositories."""

from __future__ import annotations

from memory_core.application.context_policy import (
    is_context_fact_visible,
    is_graph_fact_visible,
)
from memory_core.application.dto import BuildContextQuery, ContextItem
from memory_core.domain.entities import MemoryChunk, SourceRef
from memory_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ContextHydrator:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        query: BuildContextQuery,
        profile_ids: tuple[str, ...],
    ) -> tuple[MemoryChunk, ...]:
        async with self._uow_factory() as uow:
            chunks = await uow.chunks.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                space_id=str(query.space_id),
                profile_ids=profile_ids,
                thread_id=str(query.thread_id) if query.thread_id else None,
            )
        return tuple(chunks)

    async def hydrate_graph_facts(
        self,
        *,
        fact_ids: tuple[str, ...],
        query: BuildContextQuery,
        profile_ids: tuple[str, ...],
    ) -> tuple[tuple[ContextItem, ...], int]:
        async with self._uow_factory() as uow:
            hydrated: list[ContextItem] = []
            stale_count = 0
            for fact_id in fact_ids:
                fact = await uow.facts.get_by_id(fact_id)
                if fact is not None and is_graph_fact_visible(
                    fact,
                    query=query,
                    profile_ids=profile_ids,
                ):
                    hydrated.append(
                        ContextItem(
                            item_id=str(fact.id),
                            item_type="fact",
                            text=fact.text,
                            score=0.78,
                            source_refs=fact.source_refs,
                            diagnostics={
                                "profile_id": str(fact.profile_id),
                                "retrieval_source": "graph_hydrated",
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
        profile_ids: tuple[str, ...],
    ) -> tuple[ContextItem, ...]:
        if not items:
            return ()

        chunk_ids = tuple(item.item_id for item in items if item.item_type == "chunk")
        visible_chunks = {
            str(chunk.id): chunk
            for chunk in await self.hydrate_visible_chunks(
                chunk_ids=chunk_ids,
                query=query,
                profile_ids=profile_ids,
            )
        }
        async with self._uow_factory() as uow:
            visible_facts = {}
            for item in items:
                if item.item_type != "fact":
                    continue
                fact = await uow.facts.get_by_id(item.item_id)
                if fact is not None and is_context_fact_visible(
                    fact,
                    query=query,
                    profile_ids=profile_ids,
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
                visible_items.append(
                    ContextItem(
                        item_id=str(chunk.id),
                        item_type=item.item_type,
                        text=chunk.text,
                        score=item.score,
                        source_refs=(
                            SourceRef(
                                source_type=chunk.source_type,
                                source_id=chunk.source_external_id,
                                chunk_id=str(chunk.id),
                                char_start=chunk.char_start,
                                char_end=chunk.char_end,
                                quote_preview=chunk.text[:200],
                            ),
                        ),
                        is_instruction=item.is_instruction,
                        diagnostics=item.diagnostics,
                    )
                )
        return tuple(visible_items)
