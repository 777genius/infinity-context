"""Feature-local checks for document_ingestion application handlers."""

from __future__ import annotations

import asyncio

from infinity_context_core.features.document_ingestion import public


def test_ingest_document_handler_creates_chunks_and_indexes_new_document() -> None:
    source_documents = _SourceDocumentRepo()
    chunks = _ChunkRepo()
    chunk_index = _ChunkIndex()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=chunks,
        chunk_index=chunk_index,
        identity_factory=_SequenceIdentityFactory(),
    )
    command = _ingest_command(
        text=(
            "First section has enough detail for the chunker.\n\n"
            "Second section keeps the document useful for retrieval."
        ),
        chunking_policy=public.ChunkingPolicy(
            target_chars=60,
            overlap_chars=10,
            min_chars=20,
        ),
    )

    result = asyncio.run(handler.execute(command))

    assert result.document.identity.document_id == "doc-1"
    assert tuple(source_documents.documents) == (result.document,)
    assert result.chunks == tuple(chunks.upserted)
    assert tuple(item.chunk_id for item in chunk_index.items) == tuple(
        chunk.identity.chunk_id for chunk in result.chunks
    )
    assert all(item.document_id == "doc-1" for item in chunk_index.items)
    assert result.duplicate_chunk_count == 0
    assert result.indexing_status == "indexed"
    assert result.warnings == ()


def test_ingest_document_handler_returns_existing_document_for_duplicate_content() -> None:
    command = _ingest_command(text="Already stored document text.")
    prepared = asyncio.run(public.PrepareDocumentIngestionHandler().execute(command))
    existing_document = public.SourceDocument.from_draft(
        document_id="doc-existing",
        draft=prepared.document,
    )
    existing_chunk = public.DocumentChunk.from_draft(
        chunk_id="chunk-existing",
        document_id=existing_document.identity.document_id,
        scope=existing_document.identity.scope,
        draft=prepared.chunks[0],
    )
    source_documents = _SourceDocumentRepo(existing_document=existing_document)
    chunks = _ChunkRepo(existing_chunks=(existing_chunk,))
    chunk_index = _ChunkIndex()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=chunks,
        chunk_index=chunk_index,
        identity_factory=_SequenceIdentityFactory(),
    )

    result = asyncio.run(handler.execute(command))

    assert result.document is existing_document
    assert result.chunks == (existing_chunk,)
    assert result.duplicate_chunk_count == 1
    assert result.indexing_status == "already_indexed_or_pending"
    assert source_documents.documents == []
    assert chunks.upserted == []
    assert chunk_index.items == []


def test_ingest_document_handler_keeps_canonical_write_when_indexing_fails() -> None:
    source_documents = _SourceDocumentRepo()
    chunks = _ChunkRepo()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=chunks,
        chunk_index=_ChunkIndex(raise_on_upsert=True),
        identity_factory=_SequenceIdentityFactory(),
    )

    result = asyncio.run(handler.execute(_ingest_command(text="Index failure still stores text.")))

    assert source_documents.documents == [result.document]
    assert result.chunks == tuple(chunks.upserted)
    assert result.indexing_status == "indexing_failed"
    assert result.warnings == ("chunk_index_failed",)


def _ingest_command(
    *,
    text: str,
    chunking_policy: public.ChunkingPolicy | None = None,
) -> public.IngestDocumentCommand:
    return public.IngestDocumentCommand(
        scope=public.DocumentIngestionScope(
            space_id="space-1",
            memory_scope_id="scope-1",
        ),
        title="Requirements",
        origin=public.SourceDocumentOrigin(
            source_type="markdown",
            source_external_id="requirements.md",
        ),
        text=text,
        classification="internal",
        chunking_policy=chunking_policy,
    )


class _SequenceIdentityFactory:
    def new_document_id(self, _prepared: public.PreparedDocumentIngestion) -> str:
        return "doc-1"

    def new_chunk_id(
        self,
        *,
        document: public.SourceDocument,
        draft: public.DocumentChunkDraft,
    ) -> str:
        return f"{document.identity.document_id}-chunk-{draft.sequence}"


class _SourceDocumentRepo:
    def __init__(
        self,
        *,
        existing_document: public.SourceDocument | None = None,
    ) -> None:
        self._existing_document = existing_document
        self.documents: list[public.SourceDocument] = []

    async def create(
        self,
        document: public.SourceDocument,
    ) -> public.SourceDocument:
        self.documents.append(document)
        return document

    async def get(self, identity: str) -> public.SourceDocument | None:
        for document in self.documents:
            if document.identity.document_id == identity:
                return document
        if (
            self._existing_document is not None
            and self._existing_document.identity.document_id == identity
        ):
            return self._existing_document
        return None

    async def find_active_by_content_hash(
        self,
        *,
        scope: public.DocumentIngestionScope,
        content_hash: str,
    ) -> public.SourceDocument | None:
        if (
            self._existing_document is not None
            and self._existing_document.identity.scope == scope
            and self._existing_document.content_hash == content_hash
        ):
            return self._existing_document
        return None


class _ChunkRepo:
    def __init__(
        self,
        *,
        existing_chunks: tuple[public.DocumentChunk, ...] = (),
    ) -> None:
        self._existing_chunks = existing_chunks
        self.upserted: list[public.DocumentChunk] = []

    async def upsert(
        self,
        chunk: public.DocumentChunk,
    ) -> public.DocumentChunkUpsertResult:
        self.upserted.append(chunk)
        return public.DocumentChunkUpsertResult(chunk=chunk)

    async def list_for_document(
        self,
        document_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[public.DocumentChunk, ...]:
        chunks = tuple(
            chunk
            for chunk in self._existing_chunks
            if chunk.identity.document_id == document_id
        )
        if limit is None:
            return chunks
        return chunks[:limit]


class _ChunkIndex:
    def __init__(self, *, raise_on_upsert: bool = False) -> None:
        self._raise_on_upsert = raise_on_upsert
        self.items: list[public.DocumentChunkIndexItem] = []

    async def upsert_chunks(
        self,
        items: tuple[public.DocumentChunkIndexItem, ...],
    ) -> public.DocumentIndexingResult:
        if self._raise_on_upsert:
            raise RuntimeError("index unavailable")
        self.items.extend(items)
        return public.DocumentIndexingResult(
            accepted_chunk_ids=tuple(item.chunk_id for item in items)
        )

    async def delete_chunks(
        self,
        chunk_ids: tuple[str, ...],
    ) -> public.DocumentIndexingResult:
        return public.DocumentIndexingResult(accepted_chunk_ids=chunk_ids)
