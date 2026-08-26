"""Atomic Postgres ingestion for Contract-C projected documents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from infinity_context_core.application.document_fragments import fragment_document_text
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import IngestDocumentResult
from infinity_context_core.application.normalize import (
    content_hash,
    estimate_tokens,
    normalize_text,
    scoped_source_hash,
)
from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryDocument,
    MemoryDocumentId,
)
from infinity_context_core.features.document_ingestion.public import (
    DocumentProjectionIdempotencyConflictError,
    DocumentProjectionLocatorConflictError,
    DocumentProjectionOrdinalConflictError,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from infinity_context_adapters.postgres.locator_catalog_attestation import (
    lock_and_attest_locator_retrieval_catalog,
)
from infinity_context_adapters.postgres.mappers import (
    chunk_row_to_domain,
    chunk_to_row,
    document_row_to_domain,
    document_to_row,
)
from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryDocumentRow
from infinity_context_adapters.postgres.retrieval_projection_mapping import (
    typed_retrieval_projection,
)


@dataclass(frozen=True, slots=True)
class PostgresProjectedDocumentIngestor:
    engine: AsyncEngine
    clock: object
    ids: object

    async def execute(self, command) -> IngestDocumentResult:
        projection = typed_retrieval_projection(command.chunk_metadata)
        if projection is None:
            raise ValueError("projected ingestor requires retrieval_projection")
        pieces = fragment_document_text(command.text)
        if len(pieces) != 1:
            raise ValueError("projected ingestion requires exactly one canonical chunk")
        fingerprint = _request_fingerprint(command)
        async with AsyncSession(self.engine) as session:
            try:
                async with session.begin():
                    await lock_and_attest_locator_retrieval_catalog(session)
                    replay = await self._idempotent_replay(
                        session, command, projection, fingerprint
                    )
                    if replay is not None:
                        return replay
                    locator_replay = await self._locator_replay(session, command, projection)
                    if locator_replay is not None:
                        return locator_replay
                    await self._assert_ordinal_available(session, command, projection)
                    result = await self._insert(session, command, projection, pieces[0])
                    if command.idempotency_key is not None:
                        await session.execute(
                            text(
                                "INSERT INTO memory_document_projection_receipts "
                                "(space_id,idempotency_key,request_fingerprint_sha256,"
                                "document_id,locator,created_at) "
                                "VALUES (:space,:key,:fingerprint,:document,:locator,:now)"
                            ),
                            {
                                "space": str(command.space_id),
                                "key": command.idempotency_key,
                                "fingerprint": fingerprint,
                                "document": str(result.document.id),
                                "locator": projection["locator"],
                                "now": self.clock.now(),
                            },
                        )
                    return result
            except IntegrityError as exc:
                conflict = _named_conflict(exc)
        if isinstance(conflict, DocumentProjectionIdempotencyConflictError):
            async with AsyncSession(self.engine) as retry_session, retry_session.begin():
                replay = await self._idempotent_replay(
                    retry_session, command, projection, fingerprint
                )
                if replay is not None:
                    return replay
        if isinstance(conflict, DocumentProjectionLocatorConflictError):
            async with AsyncSession(self.engine) as retry_session, retry_session.begin():
                replay = await self._locator_replay(retry_session, command, projection)
                if replay is not None:
                    return replay
        raise conflict

    async def _idempotent_replay(self, session, command, projection, fingerprint):
        if command.idempotency_key is None:
            return None
        receipt = (
            (
                await session.execute(
                    text(
                        "SELECT request_fingerprint_sha256, document_id, locator "
                        "FROM memory_document_projection_receipts "
                        "WHERE space_id=:space AND idempotency_key=:key FOR UPDATE"
                    ),
                    {"space": str(command.space_id), "key": command.idempotency_key},
                )
            )
            .mappings()
            .one_or_none()
        )
        if receipt is None:
            return None
        if (
            receipt["request_fingerprint_sha256"] != fingerprint
            or receipt["locator"] != projection["locator"]
        ):
            raise DocumentProjectionIdempotencyConflictError
        return await _load_result(session, receipt["document_id"])

    async def _locator_replay(self, session, command, projection):
        row = (
            await session.execute(
                select(MemoryChunkRow)
                .where(
                    MemoryChunkRow.space_id == str(command.space_id),
                    MemoryChunkRow.memory_scope_id == str(command.memory_scope_id),
                    MemoryChunkRow.retrieval_locator == projection["locator"],
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        document = await session.get(MemoryDocumentRow, row.document_id)
        if document is None or not _matches_existing(document, row, command, projection):
            raise DocumentProjectionLocatorConflictError
        return await _load_result(session, row.document_id)

    async def _assert_ordinal_available(self, session, command, projection) -> None:
        conditions = [
            MemoryChunkRow.space_id == str(command.space_id),
            MemoryChunkRow.memory_scope_id == str(command.memory_scope_id),
            MemoryChunkRow.retrieval_source_key == projection["source_key"],
            MemoryChunkRow.retrieval_projection_generation == projection["projection_generation"],
            MemoryChunkRow.retrieval_sequence_ordinal == projection["sequence_ordinal"],
            MemoryChunkRow.status == "active",
            MemoryChunkRow.classification.in_(("public", "internal")),
        ]
        conditions.append(
            MemoryChunkRow.thread_id.is_(None)
            if command.thread_id is None
            else MemoryChunkRow.thread_id == str(command.thread_id)
        )
        existing = (
            await session.execute(select(MemoryChunkRow.id).where(*conditions).with_for_update())
        ).scalar_one_or_none()
        if existing is not None:
            raise DocumentProjectionOrdinalConflictError

    async def _insert(self, session, command, projection, piece):
        now = self.clock.now()
        body_hash = content_hash(command.text)
        document = MemoryDocument.create(
            document_id=MemoryDocumentId(self.ids.new_id("doc")),
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            thread_id=command.thread_id,
            title=command.title,
            source_type=command.source_type,
            source_external_id=command.source_external_id,
            content_hash=body_hash,
            now=now,
            classification=command.classification,
        )
        document_row = document_to_row(document)
        document_row.retrieval_projected = True
        session.add(document_row)
        await session.flush()
        retrieval_text = document_chunk_retrieval_text(
            text=piece.text, metadata=command.chunk_metadata or {}, title=document.title
        )
        chunk = MemoryChunk.create(
            chunk_id=MemoryChunkId(self.ids.new_id("chunk")),
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            thread_id=command.thread_id,
            document_id=document.id,
            episode_id=None,
            source_type=command.source_type,
            source_external_id=command.source_external_id,
            source_hash=scoped_source_hash(
                command.space_id,
                command.memory_scope_id,
                str(document.id),
                piece.sequence,
                normalize_text(piece.text),
            ),
            kind=piece.kind,
            text=piece.text,
            normalized_text=normalize_text(retrieval_text),
            sequence=piece.sequence,
            char_start=piece.char_start,
            char_end=piece.char_end,
            token_estimate=estimate_tokens(retrieval_text),
            now=now,
            metadata=dict(command.chunk_metadata or {}),
            classification=document.classification,
        )
        session.add(chunk_to_row(chunk))
        await session.flush()
        return IngestDocumentResult(document, (chunk,), 0, "pending")


async def _load_result(session, document_id: str) -> IngestDocumentResult:
    document = await session.get(MemoryDocumentRow, document_id)
    if document is None:
        raise RuntimeError("projection receipt points to a missing document")
    chunks = tuple(
        (
            await session.execute(
                select(MemoryChunkRow)
                .where(MemoryChunkRow.document_id == document_id)
                .order_by(MemoryChunkRow.sequence, MemoryChunkRow.id)
            )
        ).scalars()
    )
    if len(chunks) != 1:
        raise RuntimeError("projected document does not own exactly one chunk")
    return IngestDocumentResult(
        document_row_to_domain(document),
        tuple(chunk_row_to_domain(row) for row in chunks),
        len(chunks),
        "already_indexed_or_pending",
    )


def _matches_existing(document, row, command, projection) -> bool:
    return (
        document.space_id == str(command.space_id)
        and document.memory_scope_id == str(command.memory_scope_id)
        and document.thread_id == (str(command.thread_id) if command.thread_id else None)
        and document.title == command.title
        and document.source_type == command.source_type
        and document.source_external_id == command.source_external_id
        and document.content_hash == content_hash(command.text)
        and document.classification == command.classification
        and row.metadata_json == dict(command.chunk_metadata or {})
        and row.retrieval_locator == projection["locator"]
        and row.retrieval_source_key == projection["source_key"]
        and row.retrieval_projection_generation == projection["projection_generation"]
        and row.retrieval_sequence_ordinal == projection["sequence_ordinal"]
        and row.retrieval_kind == projection["kind"]
        and row.retrieval_actor_keys_json == projection["actor_keys"]
        and row.retrieval_start_at == projection["start_at"]
        and row.retrieval_end_at == projection["end_at"]
        and row.retrieval_relative_start_ms == projection["relative_start_ms"]
        and row.retrieval_relative_end_ms == projection["relative_end_ms"]
        and row.retrieval_category == projection["category"]
        and row.retrieval_tags_json == projection["tags"]
    )


def _request_fingerprint(command) -> str:
    value = {
        "space_id": str(command.space_id),
        "memory_scope_id": str(command.memory_scope_id),
        "thread_id": str(command.thread_id) if command.thread_id else None,
        "title": command.title,
        "source_type": command.source_type,
        "source_external_id": command.source_external_id,
        "classification": command.classification,
        "content_hash": content_hash(command.text),
        "chunk_metadata": {
            key: value
            for key, value in (command.chunk_metadata or {}).items()
            if key != "_retrieval_projection_contract"
        },
        "retrieval_projection": (command.chunk_metadata or {})["_retrieval_projection_contract"],
    }
    encoded = json.dumps(
        _utf8_order(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utf8_order(value):
    if isinstance(value, dict):
        return {
            key: _utf8_order(value[key])
            for key in sorted(value, key=lambda item: item.encode("utf-8"))
        }
    if isinstance(value, list):
        return [_utf8_order(item) for item in value]
    return value


def _named_conflict(exc: IntegrityError) -> RuntimeError:
    name = getattr(getattr(exc, "orig", None), "diag", None)
    name = getattr(name, "constraint_name", "")
    if name == "uq_memory_chunks_retrieval_locator_owner":
        return DocumentProjectionLocatorConflictError()
    if name == "uq_memory_chunks_retrieval_active_ordinal_owner":
        return DocumentProjectionOrdinalConflictError()
    if name in {
        "memory_document_projection_receipts_pkey",
        "pk_memory_document_projection_receipts",
    }:
        return DocumentProjectionIdempotencyConflictError()
    return RuntimeError("canonical projected document write conflicted")


__all__ = ("PostgresProjectedDocumentIngestor",)
