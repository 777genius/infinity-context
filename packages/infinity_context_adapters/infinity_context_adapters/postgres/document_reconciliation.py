"""Canonical Postgres observation adapter for exact-document reconciliation."""

from __future__ import annotations

from infinity_context_core.features.document_ingestion.public import (
    ExactDocumentIdentity,
    ExactDocumentObservation,
    ExactDocumentObservationPort,
)
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .locator_models import (
    MemoryDocumentProjectionReceiptRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileRow,
)
from .locator_profile_queryability import is_profile_canonically_queryable
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
        async with self._sessions() as session, session.begin():
            await _establish_snapshot(session)
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
                    .where(*_child_binding_conditions(identity, document.id))
                    .order_by(MemoryChunkRow.id)
                )
            ).scalars()
        )
        active_chunks = [chunk for chunk in chunks if chunk.status == "active"]
        generations = {chunk.retrieval_projection_generation for chunk in active_chunks}
        binding_conflict = len(generations) > 1
        projection_generation = _observed_projection_generation(
            identity, chunks, active_chunks, generations
        )
        profile = await _profile(session, identity.profile_generation)
        profile_generation = profile.generation if profile is not None else None
        visibility = await _visibility(
            session,
            identity,
            document,
            chunks,
            active_chunks,
            profile,
        )
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


async def _establish_snapshot(session: AsyncSession) -> None:
    """Pin every PostgreSQL observation read to one non-leaking MVCC snapshot."""

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        # SET TRANSACTION is deliberately the first statement in the transaction.
        # Unlike SET SESSION, both properties end automatically with this transaction.
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))


def _child_binding_conditions(identity: ExactDocumentIdentity, document_id: str) -> list[object]:
    scope = identity.scope
    return [
        MemoryChunkRow.document_id == document_id,
        MemoryChunkRow.space_id == scope.space_id,
        MemoryChunkRow.memory_scope_id == scope.memory_scope_id,
        (
            MemoryChunkRow.thread_id.is_(None)
            if scope.thread_id is None
            else MemoryChunkRow.thread_id == scope.thread_id
        ),
    ]


def _observed_projection_generation(identity, chunks, active_chunks, active_generations):
    if len(active_generations) == 1:
        return next(iter(active_generations))
    if active_chunks:
        return None
    requested = identity.projection_generation
    if requested is None:
        return None
    chunk_generations = {chunk.retrieval_projection_generation for chunk in chunks}
    if not chunk_generations or requested in chunk_generations:
        return requested
    if len(chunk_generations) == 1:
        return next(iter(chunk_generations))
    return None


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


async def _visibility(session, identity, document, chunks, active_chunks, profile):
    if document.status in {"deleted", "superseded"}:
        return "not_queryable"
    if document.status != "active":
        return "unavailable"
    if (
        profile is not None
        and active_chunks
        and await is_profile_canonically_queryable(session, profile.profile_id)
    ):
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
    if await _has_live_projection_work(session, identity, document, chunks, profile):
        return "processing"
    return "accepted"


async def _has_live_projection_work(session, identity, document, chunks, profile):
    bound_chunks = [
        chunk
        for chunk in chunks
        if identity.projection_generation is None
        or chunk.retrieval_projection_generation == identity.projection_generation
    ]
    active_statuses = ("pending", "retry_pending", "running")
    document_delete = and_(
        MemoryOutboxRow.event_type == "vector.delete_chunks",
        MemoryOutboxRow.aggregate_type == "document",
        MemoryOutboxRow.aggregate_id == document.id,
        MemoryOutboxRow.aggregate_version.is_(None),
        MemoryOutboxRow.payload_json["document_id"].as_string() == document.id,
    )
    bindings = [document_delete]
    for chunk in bound_chunks:
        chunk_id = chunk.id
        current_version = chunk.retrieval_version
        bindings.extend(
            (
                # Runtime/application producers are intentionally unversioned.
                and_(
                    MemoryOutboxRow.event_type == "vector.upsert_chunk",
                    MemoryOutboxRow.aggregate_type == "chunk",
                    MemoryOutboxRow.aggregate_id == chunk_id,
                    MemoryOutboxRow.aggregate_version.is_(None),
                    MemoryOutboxRow.payload_json["chunk_id"].as_string() == chunk_id,
                ),
                # The locator migration trigger binds work to the exact current version.
                and_(
                    MemoryOutboxRow.event_type == "vector.upsert_chunk",
                    MemoryOutboxRow.aggregate_type == "locator_chunk",
                    MemoryOutboxRow.aggregate_id == chunk_id,
                    MemoryOutboxRow.aggregate_version == current_version,
                    MemoryOutboxRow.payload_json["chunk_id"].as_string() == chunk_id,
                ),
                and_(
                    MemoryOutboxRow.event_type == "vector.delete_chunks",
                    MemoryOutboxRow.aggregate_type == "locator_chunk",
                    MemoryOutboxRow.aggregate_id == chunk_id,
                    MemoryOutboxRow.aggregate_version == current_version,
                    MemoryOutboxRow.payload_json["chunk_ids"][0].as_string() == chunk_id,
                ),
            )
        )
        if profile is not None:
            profile_id = profile.profile_id
            bindings.extend(
                (
                    and_(
                        MemoryOutboxRow.event_type == "vector.upsert_locator_profile",
                        MemoryOutboxRow.aggregate_type == "locator_profile_chunk",
                        MemoryOutboxRow.aggregate_id == chunk_id,
                        MemoryOutboxRow.aggregate_version == current_version,
                        MemoryOutboxRow.payload_json["chunk_id"].as_string() == chunk_id,
                        MemoryOutboxRow.payload_json["profile_id"].as_string() == profile_id,
                    ),
                    and_(
                        MemoryOutboxRow.event_type == "vector.delete_locator_profile",
                        MemoryOutboxRow.aggregate_type == "locator_profile_chunk",
                        MemoryOutboxRow.aggregate_id == chunk_id,
                        MemoryOutboxRow.aggregate_version == current_version,
                        MemoryOutboxRow.payload_json["chunk_ids"][0].as_string() == chunk_id,
                        MemoryOutboxRow.payload_json["profile_id"].as_string() == profile_id,
                    ),
                )
            )
    processing = (
        await session.execute(
            select(MemoryOutboxRow.id)
            .where(
                MemoryOutboxRow.status.in_(active_statuses),
                or_(*bindings),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return processing is not None


async def _idempotency_match(session, document_id, space_id, idempotency_key):
    if idempotency_key is None:
        return None
    receipt = await session.get(MemoryDocumentProjectionReceiptRow, (space_id, idempotency_key))
    if receipt is None:
        return None
    return receipt.document_id == document_id


__all__ = ("PostgresExactDocumentObservationAdapter",)
