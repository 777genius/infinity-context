"""Read model for browsing a memory scope."""

from __future__ import annotations

from memo_stack_core.application.dto import MemoryBrowserQuery, MemoryBrowserResult
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class BuildMemoryBrowserUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, query: MemoryBrowserQuery) -> MemoryBrowserResult:
        limit = max(1, min(query.limit, 200))
        space_id = str(query.space_id)
        memory_scope_id = str(query.memory_scope_id)
        async with self._uow_factory() as uow:
            memory_scope = await uow.scope.get_memory_scope(memory_scope_id)
            if memory_scope is None or str(memory_scope.space_id) != space_id:
                raise MemoryNotFoundError("MemoryScope not found")

            facts = await uow.facts.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.fact_status,
                limit=limit,
            )
            episodes = await uow.episodes.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.episode_status,
                limit=limit,
            )
            documents = await uow.documents.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.document_status,
                limit=limit,
            )
            chunks = await uow.chunks.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.chunk_status,
                limit=limit,
            )
            extraction_jobs = await uow.asset_extractions.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.extraction_status,
                limit=limit,
            )
            threads = await uow.scope.list_threads(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                status=query.thread_status,
                limit=limit,
            )
            captures = await uow.captures.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                status=query.capture_status,
                consolidation_status=None,
                limit=limit,
            )
            assets = await uow.assets.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                thread_id=None,
                status=query.asset_status,
                limit=limit,
            )
            anchors = await uow.anchors.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                kind=None,
                status=query.anchor_status,
                limit=limit,
            )
            context_links = await uow.context_links.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                status=query.link_status,
                limit=limit,
            )
            suggestions = await uow.context_link_suggestions.list_for_scope(
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                status=query.suggestion_status,
                limit=limit,
            )

        stats = {
            "facts": len(facts),
            "episodes": len(episodes),
            "documents": len(documents),
            "chunks": len(chunks),
            "extraction_jobs": len(extraction_jobs),
            "threads": len(threads),
            "captures": len(captures),
            "assets": len(assets),
            "anchors": len(anchors),
            "context_links": len(context_links),
            "context_link_suggestions": len(suggestions),
            "pending_context_link_suggestions": sum(
                1 for suggestion in suggestions if suggestion.status.value == "pending"
            ),
            "active_context_links": sum(
                1 for link in context_links if link.status.value == "active"
            ),
        }
        return MemoryBrowserResult(
            generated_at=self._clock.now(),
            memory_scope=memory_scope,
            facts=tuple(facts),
            episodes=tuple(episodes),
            documents=tuple(documents),
            chunks=tuple(chunks),
            extraction_jobs=tuple(extraction_jobs),
            threads=tuple(threads),
            captures=tuple(captures),
            assets=tuple(assets),
            anchors=tuple(anchors),
            context_links=tuple(context_links),
            context_link_suggestions=tuple(suggestions),
            stats=stats,
            diagnostics={
                "browser_version": "memory-browser-v1",
                "limit": limit,
                "statuses": {
                    "fact": query.fact_status,
                    "episode": query.episode_status,
                    "document": query.document_status,
                    "chunk": query.chunk_status,
                    "extraction": query.extraction_status,
                    "thread": query.thread_status,
                    "capture": query.capture_status,
                    "asset": query.asset_status,
                    "anchor": query.anchor_status,
                    "link": query.link_status,
                    "suggestion": query.suggestion_status,
                },
            },
        )
