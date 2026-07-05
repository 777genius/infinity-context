"""Use case boundaries for the document_ingestion feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.document_ingestion.application.commands import (
    IngestDocumentCommand,
    IngestDocumentResult,
    PreparedDocumentIngestion,
)
from infinity_context_core.features.document_ingestion.domain import (
    ChunkingPolicy,
    SourceDocumentDraft,
)


class PrepareDocumentIngestionUseCase(Protocol):
    async def execute(self, command: IngestDocumentCommand) -> PreparedDocumentIngestion:
        """Validate source text and build chunk drafts without adapter dependencies."""


class IngestDocumentUseCase(Protocol):
    async def execute(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        """Ingest a source document through the feature-owned application boundary."""


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


__all__ = (
    "DocumentIngestionUseCases",
    "IngestDocumentUseCase",
    "PrepareDocumentIngestionHandler",
    "PrepareDocumentIngestionUseCase",
)
