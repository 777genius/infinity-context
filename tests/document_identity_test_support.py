"""Persisted legacy document fixtures without changing canonical IDs or references."""

from infinity_context_adapters.postgres.models import (
    MemoryDocumentRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
)
from infinity_context_core.application.normalize import scoped_idempotency_key
from infinity_context_core.features.document_ingestion.public import legacy_document_content_digest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def downgrade_document_identity(engine, document_id: str, text: str, *, explicit: bool):
    async with AsyncSession(engine) as session:
        document = await session.get(MemoryDocumentRow, document_id)
        digest = legacy_document_content_digest(text)
        document.content_hash = digest
        records = (
            await session.execute(
                select(MemoryIdempotencyRecordRow).where(
                    MemoryIdempotencyRecordRow.result_id == document_id
                )
            )
        ).scalars()
        for record in records:
            record.fingerprint = digest
            if not explicit:
                raw = (
                    f"document:{document.space_id}:{document.memory_scope_id}:"
                    f"{document.source_type}:{document.source_external_id}:{digest}"
                )
                record.key = scoped_idempotency_key(
                    "ingest_document", document.memory_scope_id, document.thread_id, raw
                )
        await session.commit()


async def document_write_counts(engine):
    async with AsyncSession(engine) as session:
        return (
            await session.scalar(select(func.count()).select_from(MemoryDocumentRow)),
            await session.scalar(select(func.count()).select_from(MemoryOutboxRow)),
        )
