"""Feature-local checks for document_ingestion application handlers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

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


def test_projected_ingest_is_single_chunk_and_exact_retry_is_idempotent() -> None:
    source_documents = _SourceDocumentRepo()
    chunks = _ChunkRepo()
    ownership = _ProjectionOwnership()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=chunks,
        identity_factory=public.StableDocumentIngestionIdentityFactory(),
        projection_ownership=ownership,
    )
    command = _ingest_command(
        text="One independently projected block.",
        retrieval_projection=_projection("locator-1", 1),
        idempotency_key="projection-1",
    )

    first = asyncio.run(handler.execute(command))
    ownership.document_ids["locator-1"] = first.document.identity.document_id
    retry = asyncio.run(handler.execute(command))

    assert first.document.retrieval_v2_eligible is True
    assert len(first.chunks) == 1
    assert retry.document == first.document
    assert retry.chunks == first.chunks
    assert len(source_documents.documents) == 1


def test_same_projected_content_with_distinct_locator_creates_distinct_documents() -> None:
    source_documents = _SourceDocumentRepo()
    chunks = _ChunkRepo()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=chunks,
        identity_factory=public.StableDocumentIngestionIdentityFactory(),
        projection_ownership=_ProjectionOwnership(),
    )

    first = asyncio.run(
        handler.execute(
            _ingest_command(text="Same content.", retrieval_projection=_projection("locator-1", 1))
        )
    )
    second = asyncio.run(
        handler.execute(
            _ingest_command(text="Same content.", retrieval_projection=_projection("locator-2", 2))
        )
    )

    assert first.document.content_hash == second.document.content_hash
    assert first.document.identity.document_id != second.document.identity.document_id
    assert len(source_documents.documents) == 2


def test_projected_ingest_rejects_multi_chunk_content() -> None:
    command = _ingest_command(
        text="First projected block. Second projected block.",
        retrieval_projection=_projection("locator-1", 1),
        chunking_policy=public.ChunkingPolicy(
            target_chars=24, overlap_chars=0, min_chars=8, boundary_scan_chars=0
        ),
    )

    with pytest.raises(public.DocumentProjectionInvalidError, match="exactly one"):
        asyncio.run(public.PrepareDocumentIngestionHandler().execute(command))


def test_projection_ownership_conflicts_are_stable_and_typed() -> None:
    ownership = _ProjectionOwnership()
    scope = public.DocumentIngestionScope("space-1", "scope-1")

    async def claim(locator: str, ordinal: int, key: str):
        return await ownership.claim_document_projection(
            public.DocumentProjectionOwnershipClaimV1(
                scope=scope,
                projection=_projection(locator, ordinal),
                content_hash=public.content_hash_for_text(locator),
                idempotency_key=key,
            )
        )

    asyncio.run(claim("locator-1", 1, "key-1"))
    with pytest.raises(public.DocumentProjectionLocatorConflictError) as locator_error:
        asyncio.run(claim("locator-1", 2, "key-2"))
    with pytest.raises(public.DocumentProjectionOrdinalConflictError) as ordinal_error:
        asyncio.run(claim("locator-2", 1, "key-2"))
    with pytest.raises(public.DocumentProjectionIdempotencyConflictError) as idem_error:
        asyncio.run(claim("locator-2", 2, "key-1"))

    assert locator_error.value.code == "memory.document_projection_locator_conflict"
    assert ordinal_error.value.code == "memory.document_projection_ordinal_conflict"
    assert idem_error.value.code == "memory.document_projection_idempotency_conflict"


def test_projection_ownership_adapter_cannot_mutate_caller_or_saved_projection() -> None:
    projection = _projection("locator-original", 1)
    command = _ingest_command(text="Immutable projected block.", retrieval_projection=projection)
    source_documents = _SourceDocumentRepo()
    handler = public.IngestDocumentHandler(
        source_documents=source_documents,
        chunks=_ChunkRepo(),
        projection_ownership=_MutatingOwnership(),
    )

    result = asyncio.run(handler.execute(command))

    assert projection.locator == "locator-original"
    assert command.retrieval_projection is not projection
    assert command.retrieval_projection.locator == "locator-original"
    assert result.document.retrieval_projection.locator == "locator-original"


@pytest.mark.parametrize("drift", ["scope", "content_hash"])
def test_idempotent_projection_revalidates_exact_scope_and_content(drift: str) -> None:
    command = _ingest_command(
        text="Exact retry content.", retrieval_projection=_projection("locator-1", 1)
    )
    prepared = asyncio.run(public.PrepareDocumentIngestionHandler().execute(command))
    existing = public.SourceDocument.from_draft(document_id="doc-existing", draft=prepared.document)
    if drift == "scope":
        existing = public.SourceDocument(
            identity=public.SourceDocumentIdentity(
                "doc-existing", public.DocumentIngestionScope("space-b", "scope-b")
            ),
            title=existing.title,
            origin=existing.origin,
            content_hash=existing.content_hash,
            retrieval_projection=existing.retrieval_projection,
        )
    else:
        existing = public.SourceDocument(
            identity=existing.identity,
            title=existing.title,
            origin=existing.origin,
            content_hash=public.content_hash_for_text("different content"),
            retrieval_projection=existing.retrieval_projection,
        )
    handler = public.IngestDocumentHandler(
        source_documents=_SourceDocumentRepo(existing_document=existing),
        chunks=_ChunkRepo(),
        projection_ownership=_FixedIdempotentOwnership("doc-existing"),
    )

    with pytest.raises(public.DocumentIngestionInvariantError, match="resolve canonically"):
        asyncio.run(handler.execute(command))


def _ingest_command(
    *,
    text: str,
    chunking_policy: public.ChunkingPolicy | None = None,
    retrieval_projection: public.DocumentRetrievalProjectionV1 | None = None,
    idempotency_key: str | None = None,
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
        retrieval_projection=retrieval_projection,
        idempotency_key=idempotency_key,
    )


def _projection(locator: str, ordinal: int) -> public.DocumentRetrievalProjectionV1:
    return public.DocumentRetrievalProjectionV1(
        locator=locator,
        source_key="source-family",
        projection_generation="generation-1",
        sequence_ordinal=ordinal,
        actor_keys=("actor",),
        time_interval=public.DocumentRetrievalProjectionTimeIntervalV1(
            datetime(2026, 1, 1, 0, ordinal, tzinfo=UTC),
            datetime(2026, 1, 1, 0, ordinal + 1, tzinfo=UTC),
        ),
        kind="record_block",
        category="decision",
        tags=("accepted",),
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
            for chunk in (*self._existing_chunks, *self.upserted)
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


class _ProjectionOwnership:
    def __init__(self) -> None:
        self.claims: dict[str, public.DocumentProjectionOwnershipClaimV1] = {}
        self.document_ids: dict[str, str] = {}
        self.ordinals: dict[tuple[object, ...], str] = {}
        self.idempotency: dict[str, public.DocumentProjectionOwnershipClaimV1] = {}

    async def claim_document_projection(
        self, claim: public.DocumentProjectionOwnershipClaimV1
    ) -> public.DocumentProjectionOwnershipDecisionV1:
        locator = claim.projection.locator
        prior = self.claims.get(locator)
        if claim.idempotency_key is not None:
            prior_idempotency = self.idempotency.get(claim.idempotency_key)
            if prior_idempotency is not None and prior_idempotency != claim:
                raise public.DocumentProjectionIdempotencyConflictError(claim.idempotency_key)
        if prior is None:
            ordinal = (
                claim.scope.space_id,
                claim.scope.memory_scope_id,
                claim.scope.thread_id,
                claim.projection.source_key,
                claim.projection.projection_generation,
                claim.projection.sequence_ordinal,
            )
            ordinal_owner = self.ordinals.get(ordinal)
            if ordinal_owner is not None and ordinal_owner != locator:
                raise public.DocumentProjectionOrdinalConflictError(locator)
            self.claims[locator] = claim
            self.ordinals[ordinal] = locator
            if claim.idempotency_key is not None:
                self.idempotency[claim.idempotency_key] = claim
            return public.DocumentProjectionOwnershipDecisionV1("acquired")
        if prior != claim:
            raise public.DocumentProjectionLocatorConflictError(locator)
        return public.DocumentProjectionOwnershipDecisionV1(
            "idempotent", self.document_ids[locator]
        )


class _MutatingOwnership:
    async def claim_document_projection(
        self, claim: public.DocumentProjectionOwnershipClaimV1
    ) -> public.DocumentProjectionOwnershipDecisionV1:
        object.__setattr__(claim.projection, "locator", "mutated-by-adapter")
        return public.DocumentProjectionOwnershipDecisionV1("acquired")


class _FixedIdempotentOwnership:
    def __init__(self, document_id: str) -> None:
        self.document_id = document_id

    async def claim_document_projection(
        self, _claim: public.DocumentProjectionOwnershipClaimV1
    ) -> public.DocumentProjectionOwnershipDecisionV1:
        return public.DocumentProjectionOwnershipDecisionV1("idempotent", self.document_id)
