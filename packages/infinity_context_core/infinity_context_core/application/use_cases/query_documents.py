"""Read-side document use cases."""

from __future__ import annotations

from infinity_context_core.application.dto import (
    DocumentChunksQueryResult,
    DocumentQueryResult,
    DocumentsQueryResult,
    GetDocumentQuery,
    ListDocumentChunksQuery,
    ListDocumentsQuery,
)
from infinity_context_core.domain.errors import MemoryNotFoundError
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


class GetDocumentUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetDocumentQuery) -> DocumentQueryResult:
        async with self._uow_factory() as uow:
            document = await uow.documents.get_by_id(query.document_id)
        if document is None:
            raise MemoryNotFoundError("Document not found")
        return DocumentQueryResult(document=document)


class ListDocumentsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListDocumentsQuery) -> DocumentsQueryResult:
        async with self._uow_factory() as uow:
            documents = await uow.documents.list_exact_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=query.status,
                limit=query.limit,
                source_external_id=query.source_external_id,
                cursor_updated_at=query.cursor_updated_at,
                cursor_id=query.cursor_id,
            )
        return DocumentsQueryResult(documents=tuple(documents))


class ListDocumentChunksUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListDocumentChunksQuery) -> DocumentChunksQueryResult:
        async with self._uow_factory() as uow:
            document = await uow.documents.get_by_id(query.document_id)
            if document is None:
                raise MemoryNotFoundError("Document not found")
            chunks = await uow.documents.list_chunks(
                query.document_id,
                limit=query.limit,
                cursor_sequence=query.cursor_sequence,
                cursor_id=query.cursor_id,
            )
        return DocumentChunksQueryResult(document=document, chunks=tuple(chunks))
