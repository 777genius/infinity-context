"""Use case boundaries for the document_ingestion feature."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from infinity_context_core.features.document_ingestion.application.commands import (
    IngestDocumentCommand,
    IngestDocumentResult,
    PreparedDocumentIngestion,
)
from infinity_context_core.features.document_ingestion.domain import (
    ChunkingPolicy,
    DocumentChunk,
    DocumentChunkDraft,
    SourceDocumentDraft,
    SourceDocument,
    content_hash_for_text,
)
from infinity_context_core.features.document_ingestion.ports import (
    DocumentChunkIndexItem,
    DocumentChunkIndexPort,
    DocumentChunkRepositoryPort,
    DocumentIndexingResult,
    SourceDocumentRepositoryPort,
)


class PrepareDocumentIngestionUseCase(Protocol):
    async def execute(self, command: IngestDocumentCommand) -> PreparedDocumentIngestion:
        """Validate source text and build chunk drafts without adapter dependencies."""


class IngestDocumentUseCase(Protocol):
    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        """Ingest a source document through the feature-owned application boundary."""


class DocumentIngestionIdentityFactory(Protocol):
    def new_document_id(self, prepared: PreparedDocumentIngestion) -> str:
        """Return the canonical id for a prepared source document."""

    def new_chunk_id(
        self,
        *,
        document: SourceDocument,
        draft: DocumentChunkDraft,
    ) -> str:
        """Return the canonical id for one prepared chunk."""


@dataclass(frozen=True, slots=True)
class DocumentIngestionUseCases:
    """Feature-owned document ingestion use case bundle."""

    prepare_document_ingestion: PrepareDocumentIngestionUseCase
    ingest_document: IngestDocumentUseCase


class PrepareDocumentIngestionHandler:
    """Pure application handler for validation and deterministic chunk planning."""

    def __init__(self, chunking_policy: ChunkingPolicy | None = None) -> None:
        self._chunking_policy = chunking_policy or ChunkingPolicy()

    async def execute(self, command: IngestDocumentCommand) -> PreparedDocumentIngestion:
        policy = command.chunking_policy or self._chunking_policy
        document = SourceDocumentDraft.create(
            scope=command.scope,
            title=command.title,
            origin=command.origin,
            text=command.text,
            classification=command.classification,
        )
        chunks = policy.plan_chunks(document.content.text)
        warnings: tuple[str, ...] = ()
        if not chunks:
            warnings = ("no_chunks_created",)
        return PreparedDocumentIngestion(
            document=document,
            chunks=chunks,
            chunking_policy_version=policy.version,
            idempotency_key=command.idempotency_key,
            warnings=warnings,
        )


@dataclass(frozen=True, slots=True)
class StableDocumentIngestionIdentityFactory:
    """Deterministic id policy for feature-owned ingestion handlers."""

    document_prefix: str = "doc"
    chunk_prefix: str = "chunk"
    hash_chars: int = 32

    def __post_init__(self) -> None:
        if not self.document_prefix.strip():
            raise ValueError("document_prefix is required")
        if not self.chunk_prefix.strip():
            raise ValueError("chunk_prefix is required")
        if self.hash_chars <= 0:
            raise ValueError("hash_chars must be positive")

    def new_document_id(self, prepared: PreparedDocumentIngestion) -> str:
        document = prepared.document
        scope = document.scope
        seed = ":".join(
            (
                scope.space_id,
                scope.memory_scope_id,
                scope.thread_id or "",
                document.content.content_hash,
            )
        )
        return _stable_id(self.document_prefix, seed, hash_chars=self.hash_chars)

    def new_chunk_id(
        self,
        *,
        document: SourceDocument,
        draft: DocumentChunkDraft,
    ) -> str:
        seed = ":".join(
            (
                document.identity.document_id,
                str(draft.sequence),
                draft.content_hash,
            )
        )
        return _stable_id(self.chunk_prefix, seed, hash_chars=self.hash_chars)


@dataclass(frozen=True, slots=True)
class IngestDocumentHandler:
    """Create canonical documents/chunks and best-effort derived chunk indexes."""

    source_documents: SourceDocumentRepositoryPort
    chunks: DocumentChunkRepositoryPort
    chunk_index: DocumentChunkIndexPort | None = None
    prepare_document_ingestion: PrepareDocumentIngestionUseCase = field(
        default_factory=PrepareDocumentIngestionHandler
    )
    identity_factory: DocumentIngestionIdentityFactory = field(
        default_factory=StableDocumentIngestionIdentityFactory
    )

    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        prepared = await self.prepare_document_ingestion.execute(command)
        existing_document = await self.source_documents.find_active_by_content_hash(
            scope=prepared.document.scope,
            content_hash=prepared.document.content.content_hash,
        )
        if existing_document is not None:
            existing_chunks = await self.chunks.list_for_document(
                existing_document.identity.document_id
            )
            return IngestDocumentResult(
                document=existing_document,
                chunks=existing_chunks,
                duplicate_chunk_count=len(existing_chunks),
                indexing_status="already_indexed_or_pending",
                warnings=prepared.warnings,
            )

        document = SourceDocument.from_draft(
            document_id=self.identity_factory.new_document_id(prepared),
            draft=prepared.document,
        )
        saved_document = await self.source_documents.create(document)
        upserted_chunks: list[DocumentChunk] = []
        indexable_chunks: list[DocumentChunk] = []
        duplicate_chunk_count = 0
        for draft in prepared.chunks:
            chunk = DocumentChunk.from_draft(
                chunk_id=self.identity_factory.new_chunk_id(
                    document=saved_document,
                    draft=draft,
                ),
                document_id=saved_document.identity.document_id,
                scope=saved_document.identity.scope,
                draft=draft,
            )
            upsert = await self.chunks.upsert(chunk)
            upserted_chunks.append(upsert.chunk)
            if upsert.duplicate:
                duplicate_chunk_count += 1
            else:
                indexable_chunks.append(upsert.chunk)

        indexing_status, indexing_warnings = await self._index_chunks(
            saved_document,
            tuple(indexable_chunks),
        )
        return IngestDocumentResult(
            document=saved_document,
            chunks=tuple(upserted_chunks),
            duplicate_chunk_count=duplicate_chunk_count,
            indexing_status=indexing_status,
            warnings=prepared.warnings + indexing_warnings,
        )

    async def _index_chunks(
        self,
        document: SourceDocument,
        chunks: tuple[DocumentChunk, ...],
    ) -> tuple[str, tuple[str, ...]]:
        if not chunks:
            return "pending", ()
        if self.chunk_index is None:
            return "pending", ()

        items = tuple(_index_item(document=document, chunk=chunk) for chunk in chunks)
        try:
            result = await self.chunk_index.upsert_chunks(items)
        except Exception:
            return "indexing_failed", ("chunk_index_failed",)
        return _indexing_status(result, tuple(item.chunk_id for item in items))


def _index_item(
    *,
    document: SourceDocument,
    chunk: DocumentChunk,
) -> DocumentChunkIndexItem:
    return DocumentChunkIndexItem(
        chunk_id=chunk.identity.chunk_id,
        document_id=document.identity.document_id,
        scope=document.identity.scope,
        origin=document.origin,
        text=chunk.text,
        content_hash=chunk.content_hash,
        sequence=chunk.sequence,
    )


def _indexing_status(
    result: DocumentIndexingResult,
    chunk_ids: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    accepted = set(result.accepted_chunk_ids)
    failed = set(result.failed_chunk_ids)
    expected = set(chunk_ids)
    warnings: list[str] = []
    if failed:
        warnings.append("chunk_index_failed")
    if result.retryable:
        warnings.append("chunk_index_retryable")
    if failed and accepted:
        return "partially_indexed", tuple(warnings)
    if failed:
        return "indexing_failed", tuple(warnings)
    if expected <= accepted:
        return "indexed", tuple(warnings)
    if result.retryable:
        return "indexing_retryable", tuple(warnings)
    return "pending", tuple(warnings)


def _stable_id(prefix: str, seed: str, *, hash_chars: int) -> str:
    digest = content_hash_for_text(seed)
    return f"{prefix.strip()}_{digest[:hash_chars]}"


__all__ = (
    "DocumentIngestionIdentityFactory",
    "DocumentIngestionUseCases",
    "IngestDocumentHandler",
    "IngestDocumentUseCase",
    "PrepareDocumentIngestionHandler",
    "PrepareDocumentIngestionUseCase",
    "StableDocumentIngestionIdentityFactory",
)
