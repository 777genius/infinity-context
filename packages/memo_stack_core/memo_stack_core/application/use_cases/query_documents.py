"""Read-side document use cases."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    DocumentChunksQueryResult,
    DocumentQueryResult,
    GetDocumentQuery,
    ListDocumentChunksQuery,
)
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class GetDocumentUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetDocumentQuery) -> DocumentQueryResult:
        async with self._uow_factory() as uow:
            document = await uow.documents.get_by_id(query.document_id)
        if document is None:
            raise MemoryNotFoundError("Document not found")
        return DocumentQueryResult(document=document)


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
