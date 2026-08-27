"""Hostile PostgreSQL proofs for the tombstone/provider-writer epoch fence."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_profile_lifecycle import (
    PostgresRetrievalProfileRegistry,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileTombstoneRow,
)
from infinity_context_core.features.context_building.public import (
    ExactVersionDeletionProof,
    ProjectedGenerationObservation,
    RuntimeFenceOwner,
)
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.retrieval_profile_outbox import RetrievalProfileOutboxCoordinator
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import func, select, text
from test_locator_retrieval_transit_versions_postgres import (
    _maximum_deleted_chunk,
    _seed_authority,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


@pytest.mark.parametrize("crash_point", ["before_effect", "after_effect"])
def test_tombstone_delete_crash_restart_and_expiry_replay_when_configured(
    crash_point: str,
) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_crash_replay_scenario(database_url, crash_point))


def test_older_active_writer_cannot_invalidate_completed_absence_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_older_writer_scenario(database_url))


def test_active_v4_removes_old_authorization_without_being_deleted_when_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_active_v4_scenario(database_url))


async def _older_writer_scenario(database_url: str) -> None:
    database, engine, sessions, registry, owner = await _database(
        database_url, "tombstone_older_writer"
    )
    try:
        await _seed_deleted_chunk(sessions, "chunk-writer")
        writer_epoch = await registry.begin_provider_mutation(
            "profile-max",
            "stale-upsert-v2",
            owner=owner,
            now=NOW,
            expires_at=NOW + timedelta(seconds=5),
        )
        await _make_tombstone(sessions, "chunk-writer")
        projection = _FencedProjection(registry, owner, current_version=1)
        coordinator = RetrievalProfileOutboxCoordinator(registry, _Source(), projection)

        with pytest.raises(RuntimeError, match="retrieval_profile_provider_mutation_active"):
            await coordinator.delete(_job("chunk-writer"), now=NOW + timedelta(seconds=1))
        assert projection.current_version == 1
        assert projection.observations == 0

        projection.current_version = 2
        finished_epoch = await registry.finish_provider_mutation(
            "profile-max",
            "stale-upsert-v2",
            owner=owner,
            started_epoch=writer_epoch,
            now=NOW + timedelta(seconds=2),
        )
        assert finished_epoch == writer_epoch + 1

        restarted = PostgresRetrievalProfileRegistry(sessions)
        replay_projection = _FencedProjection(restarted, owner, current_version=2)
        await RetrievalProfileOutboxCoordinator(restarted, _Source(), replay_projection).delete(
            _job("chunk-writer"), now=NOW + timedelta(seconds=3)
        )
        async with sessions() as session:
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow, ("profile-max", "chunk-writer")
            )
            scheduled = int(
                await session.scalar(
                    select(func.count())
                    .select_from(text("memory_outbox"))
                    .where(text("message_key LIKE 'locator-profile-delete-fence:%'"))
                )
                or 0
            )
        assert tombstone is not None
        assert tombstone.completed_at == NOW + timedelta(seconds=3)
        assert tombstone.delete_canonical_version == 2
        assert tombstone.delete_authorized_mutation_epoch == finished_epoch
        assert tombstone.delete_completed_mutation_epoch == finished_epoch + 2
        assert replay_projection.current_version is None
        assert scheduled >= 2
    finally:
        await engine.dispose()
        await database.drop()


async def _crash_replay_scenario(database_url: str, crash_point: str) -> None:
    database, engine, sessions, registry, owner = await _database(
        database_url, f"tombstone_{crash_point}"
    )
    try:
        chunk_id = f"chunk-{crash_point}"
        await _seed_deleted_chunk(sessions, chunk_id)
        await _make_tombstone(sessions, chunk_id)
        projection = _FencedProjection(
            registry,
            owner,
            current_version=1,
            crash_point=crash_point,
        )
        coordinator = RetrievalProfileOutboxCoordinator(registry, _Source(), projection)

        with pytest.raises(RuntimeError, match=f"injected_{crash_point}"):
            await coordinator.delete(_job(chunk_id), now=NOW)
        restarted = PostgresRetrievalProfileRegistry(sessions)

        async with sessions() as session:
            mutation = (
                await session.execute(select(MemoryLocatorProfileProviderMutationRow))
            ).scalar_one()
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow, ("profile-max", chunk_id)
            )
        with pytest.raises(RuntimeError, match="retrieval_profile_provider_mutation_stale"):
            await restarted.begin_provider_mutation(
                "profile-max",
                mutation.operation_id,
                owner=owner,
                now=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=2),
            )
        with pytest.raises(RuntimeError, match="retrieval_profile_provider_mutation_active"):
            await restarted.authorize_tombstone("profile-max", chunk_id, canonical_version=3)
        assert mutation.expires_at < NOW + timedelta(minutes=1)
        assert tombstone is not None and tombstone.completed_at is None

        completed_epoch = await restarted.finish_provider_mutation(
            "profile-max",
            mutation.operation_id,
            owner=owner,
            started_epoch=mutation.started_epoch,
            now=NOW + timedelta(minutes=1),
        )
        replay = _FencedProjection(
            restarted,
            owner,
            current_version=projection.current_version,
        )
        await RetrievalProfileOutboxCoordinator(restarted, _Source(), replay).delete(
            _job(chunk_id), now=NOW + timedelta(minutes=1, seconds=1)
        )
        async with sessions() as session:
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow, ("profile-max", chunk_id)
            )
        assert tombstone is not None and tombstone.completed_at is not None
        assert tombstone.delete_authorized_mutation_epoch == completed_epoch
        assert replay.current_version is None
    finally:
        await engine.dispose()
        await database.drop()


async def _active_v4_scenario(database_url: str) -> None:
    database, engine, sessions, registry, owner = await _database(database_url, "tombstone_v4")
    try:
        await _seed_deleted_chunk(sessions, "chunk-v4")
        await _make_tombstone(sessions, "chunk-v4")
        authorization = await registry.authorize_tombstone(
            "profile-max", "chunk-v4", canonical_version=3
        )
        assert authorization is not None
        with pytest.raises(RuntimeError, match="retrieval_profile_tombstone_delete_active"):
            await registry.begin_provider_mutation(
                "profile-max",
                "active-v4-before-canonical",
                owner=owner,
                now=NOW,
                expires_at=NOW + timedelta(seconds=5),
            )

        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE memory_chunks SET status='active', classification='internal', "
                    "retrieval_version=4 WHERE id='chunk-v4'"
                )
            )
        writer_epoch = await registry.begin_provider_mutation(
            "profile-max",
            "active-v4-after-canonical",
            owner=owner,
            now=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=6),
        )
        await registry.finish_provider_mutation(
            "profile-max",
            "active-v4-after-canonical",
            owner=owner,
            started_epoch=writer_epoch,
            now=NOW + timedelta(seconds=2),
        )
        projection = _FencedProjection(registry, owner, current_version=4)
        await RetrievalProfileOutboxCoordinator(registry, _Source(), projection).delete(
            _job("chunk-v4"), now=NOW + timedelta(seconds=3)
        )
        assert projection.current_version == 4
        assert projection.observations == 0
        async with sessions() as session:
            assert (
                await session.get(MemoryLocatorProfileTombstoneRow, ("profile-max", "chunk-v4"))
                is None
            )
    finally:
        await engine.dispose()
        await database.drop()


async def _database(database_url: str, prefix: str):
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(database_url, prefix=prefix, asyncpg=asyncpg)
    await database.recreate()
    engine = build_async_engine(database.app_url)
    await upgrade_schema(engine)
    sessions = build_session_factory(engine)
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id=f"{prefix}-runtime",
        generation="generation-a",
        key_id="test-unrecoverable",
    )
    registry = PostgresRetrievalProfileRegistry(sessions)
    await registry.register_runtime_incarnation(owner, now=NOW)
    return database, engine, sessions, registry, owner


async def _seed_deleted_chunk(sessions, chunk_id: str) -> None:
    async with sessions() as session, session.begin():
        await _seed_authority(session)
        chunk = _maximum_deleted_chunk()
        chunk.id = chunk_id
        chunk.source_hash = ("c" if "before" in chunk_id else "d") * 64
        chunk.retrieval_locator = f"locator-{chunk_id}"
        chunk.retrieval_version = 1
        session.add(chunk)
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "UPDATE memory_chunks SET text='generation two', "
                "normalized_text='generation two', retrieval_version=2 WHERE id=:chunk_id"
            ),
            {"chunk_id": chunk_id},
        )


async def _make_tombstone(sessions, chunk_id: str) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "UPDATE memory_chunks SET classification='restricted', retrieval_version=3 "
                "WHERE id=:chunk_id"
            ),
            {"chunk_id": chunk_id},
        )


class _Source:
    async def items_by_ids(self, _canonical_ids):
        return ()


class _FencedProjection:
    def __init__(self, registry, owner, *, current_version, crash_point=None) -> None:
        self.registry = registry
        self.owner = owner
        self.current_version = current_version
        self.crash_point = crash_point
        self.observations = 0

    async def observe_profile_generation(self, _identity, canonical_id):
        self.observations += 1
        return ProjectedGenerationObservation(canonical_id, self.current_version)

    async def delete_profile_if_version(
        self,
        identity,
        canonical_ids,
        *,
        canonical_version,
        tombstone_authorization,
    ):
        operation_id = f"delete-{canonical_ids[0]}-{self.crash_point or 'complete'}"
        started_epoch = await self.registry.begin_provider_mutation(
            identity.profile_id,
            operation_id,
            owner=self.owner,
            now=NOW,
            expires_at=NOW + timedelta(seconds=5),
            tombstone_authorization=tombstone_authorization,
        )
        if self.crash_point == "before_effect":
            raise RuntimeError("injected_before_effect")
        if self.current_version == canonical_version:
            self.current_version = None
        if self.crash_point == "after_effect":
            raise RuntimeError("injected_after_effect")
        finished_epoch = await self.registry.finish_provider_mutation(
            identity.profile_id,
            operation_id,
            owner=self.owner,
            started_epoch=started_epoch,
            now=NOW + timedelta(seconds=1),
        )
        return ExactVersionDeletionProof(
            canonical_ids,
            canonical_version,
            tuple(self.current_version for _ in canonical_ids),
            finished_epoch,
        )


def _job(chunk_id: str) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        1,
        "vector.delete_locator_profile",
        chunk_id,
        3,
        0,
        "projection",
        "profile:profile-max",
        {"profile_id": "profile-max", "chunk_ids": [chunk_id]},
        "locator_profile_chunk",
    )
