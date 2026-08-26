"""Canonical Postgres observation adapter for exact-document reconciliation."""

from __future__ import annotations

from infinity_context_core.features.document_ingestion.public import (
    ExactDocumentIdentity,
    ExactDocumentObservation,
    ExactDocumentObservationPort,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .locator_models import (
    MemoryDocumentProjectionReceiptRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileRow,
)
from .models import MemoryChunkRow, MemoryDocumentRow
from .outbox_models import MemoryOutboxRow


class PostgresExactDocumentObservationAdapter(ExactDocumentObservationPort):
    """Perform one exact, indexed canonical lookup; never list or mutate providers."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def observe_exact_document(
        self,
        identity: ExactDocumentIdentity,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[ExactDocumentObservation, ...]:
        async with self._sessions() as session:
            documents = list(
                (
                    await session.execute(
                        select(MemoryDocumentRow)
                        .where(*_identity_conditions(identity))
                        .order_by(MemoryDocumentRow.id)
                        .limit(2)
                    )
                ).scalars()
            )
            observations = [
                await self._observation(session, identity, document, idempotency_key)
                for document in documents
            ]
        return tuple(observations)

    async def _observation(self, session, identity, document, idempotency_key):
        chunks = list(
            (
                await session.execute(
                    select(MemoryChunkRow)
                    .where(MemoryChunkRow.document_id == document.id)
                    .order_by(MemoryChunkRow.id)
                )
            ).scalars()
        )
        active_chunks = [chunk for chunk in chunks if chunk.status == "active"]
        generations = {chunk.retrieval_projection_generation for chunk in active_chunks}
        binding_conflict = len(generations) > 1
        projection_generation = generations.pop() if len(generations) == 1 else None
        profile = await _profile(session, identity.profile_generation)
        profile_generation = profile.generation if profile is not None else None
        visibility = await _visibility(session, document, active_chunks, profile)
        idempotency_matches = await _idempotency_match(
            session, document.id, identity.scope.space_id, idempotency_key
        )
        return ExactDocumentObservation(
            document_id=document.id,
            canonical_status=document.status,
            projection_generation=projection_generation,
            profile_generation=profile_generation,
            visibility=visibility,
            idempotency_key_matches=idempotency_matches,
            binding_conflict=binding_conflict,
        )


def _identity_conditions(identity: ExactDocumentIdentity) -> list[object]:
    scope = identity.scope
    conditions: list[object] = [
        MemoryDocumentRow.space_id == scope.space_id,
        MemoryDocumentRow.memory_scope_id == scope.memory_scope_id,
        MemoryDocumentRow.source_type == identity.origin.source_type,
        MemoryDocumentRow.source_external_id == identity.origin.source_external_id,
    ]
    conditions.append(
        MemoryDocumentRow.thread_id.is_(None)
        if scope.thread_id is None
        else MemoryDocumentRow.thread_id == scope.thread_id
    )
    return conditions


async def _profile(session, requested_generation):
    statement = select(MemoryLocatorProfileRow)
    if requested_generation is None:
        statement = statement.where(MemoryLocatorProfileRow.state == "active")
    else:
        statement = statement.where(MemoryLocatorProfileRow.generation == requested_generation)
    rows = list(
        (
            await session.execute(statement.order_by(MemoryLocatorProfileRow.profile_id).limit(2))
        ).scalars()
    )
    return rows[0] if len(rows) == 1 else None


async def _visibility(session, document, active_chunks, profile):
    if document.status in {"deleted", "superseded"}:
        return "not_queryable"
    if document.status != "active":
        return "unavailable"
    if profile is not None and profile.state == "active" and active_chunks:
        eligible = all(
            chunk.retrieval_locator is not None and chunk.classification in {"public", "internal"}
            for chunk in active_chunks
        )
        if eligible:
            receipts = list(
                (
                    await session.execute(
                        select(MemoryLocatorProfileProjectionReceiptRow).where(
                            MemoryLocatorProfileProjectionReceiptRow.profile_id
                            == profile.profile_id,
                            MemoryLocatorProfileProjectionReceiptRow.chunk_id.in_(
                                [chunk.id for chunk in active_chunks]
                            ),
                        )
                    )
                ).scalars()
            )
            versions = {receipt.chunk_id: receipt.canonical_version for receipt in receipts}
            if all(versions.get(chunk.id) == chunk.retrieval_version for chunk in active_chunks):
                return "indexed"
    if not active_chunks:
        return "processing"
    processing = (
        await session.execute(
            select(MemoryOutboxRow.id)
            .where(
                MemoryOutboxRow.aggregate_id.in_([chunk.id for chunk in active_chunks]),
                MemoryOutboxRow.event_type.in_(
                    ("vector.upsert_chunk", "vector.upsert_locator_profile")
                ),
                or_(MemoryOutboxRow.status == "pending", MemoryOutboxRow.status == "running"),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return "processing" if processing is not None else "accepted"


async def _idempotency_match(session, document_id, space_id, idempotency_key):
    if idempotency_key is None:
        return None
    receipt = await session.get(MemoryDocumentProjectionReceiptRow, (space_id, idempotency_key))
    if receipt is None:
        return None
    return receipt.document_id == document_id


__all__ = ("PostgresExactDocumentObservationAdapter",)
