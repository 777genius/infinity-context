"""Synthetic PostgreSQL proof of lane no-ops and statement-trigger invalidation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_adapters.postgres import (
    PostgresRetrievalProfileRegistry,
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_adapters.postgres.locator_profile_queryability import (
    is_profile_canonically_queryable,
)
from infinity_context_core.features.context_building.public import (
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from infinity_context_server.retrieval_profile_composition import (
    ProfileAwareLocatorRetrievalService,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from test_active_reconciliation_orchestration_postgres import _EMPTY_DIGEST, _Projection


@pytest.mark.parametrize(
    "change",
    [
        {"healthy": False},
        {"profile_qualified": False},
        {"required": False},
        {"failure_code": "synthetic_failure"},
        {"observed_count": 1},
        {"observed_digest": "f" * 64},
        {"lane_id": "new_lane"},
        {"raw_sql": True},
    ],
)
def test_lane_observation_preserves_lease_until_evidence_changes(monkeypatch, change) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_continuity(database_url, monkeypatch, change))


async def _assert_continuity(database_url, monkeypatch, change):
    database = PostgresTestDatabase.from_url(
        database_url, prefix="lane_lease_continuity", asyncpg=pytest.importorskip("asyncpg")
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    sessions = build_session_factory(engine)
    registry = PostgresRetrievalProfileRegistry(sessions)
    now = datetime.now(UTC)
    observation_now = now
    lease_ttl = timedelta(seconds=30)
    renew_before = timedelta(seconds=15)
    identity = RetrievalProfileIdentity("synthetic-profile", "gen-a", "a" * 64, "synthetic-only")
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="synthetic-runtime", generation="runtime-a", key_id="test-unrecoverable"
    )
    observation = dict(
        required=True,
        healthy=True,
        profile_qualified=True,
        failure_code=None,
        observed_count=0,
        observed_digest=_EMPTY_DIGEST,
    )

    async def snapshot():
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    text(
                        "SELECT aggregate_version, activation_lease_id, "
                        "activation_lease_expires_at, "
                        "reconciliation_drifted, activation_evidence_version "
                        "FROM memory_locator_profile_evidence_versions, memory_locator_profiles "
                        "WHERE profile_id='synthetic-profile'"
                    )
                )
            ).one()

    async def assert_ready():
        current = await registry.active_lease(now=observation_now)
        assert current is not None
        # active_lease and canonical admission use database time, so also check
        # continuity at the simulated observation time explicitly.
        assert current.issued_at <= observation_now < current.expires_at
        async with sessions() as session:
            assert await is_profile_canonically_queryable(session, identity.profile_id)
        return current

    try:
        await upgrade_schema(engine)
        await registry.register_runtime_incarnation(owner, now=now)
        await registry.create_building(identity, now=now)
        await registry.checkpoint_backfill(
            identity.profile_id,
            previous_cursor=None,
            cursor=None,
            watermark=0,
            complete=True,
            now=now,
        )
        for lane_id in ("postgres_keyword", "qdrant_dense"):
            await registry.update_lane(identity.profile_id, lane_id, checked_at=now, **observation)
        evidence = await registry.activation_evidence(identity.profile_id, now=now)
        lease = await registry.issue_activation_lease(
            identity.profile_id,
            evidence,
            lease_id="synthetic-activation",
            now=now,
            expires_at=now + lease_ttl,
        )
        await registry.activate(
            lease, evidence, now=now, maximum_queue_lag=timedelta(minutes=5), maximum_retained=1
        )
        activated = await registry.active_lease(now=now)
        assert activated is not None
        # Issuance rebases the requested TTL onto PostgreSQL clock_timestamp(),
        # which can be later than the application timestamp captured before setup.
        observation_now = activated.issued_at
        assert activated.expires_at - activated.issued_at == lease_ttl
        update_lane = PostgresRetrievalProfileRegistry.update_lane
        writes = []

        async def checked_update(self, *args, **kwargs):
            before = await snapshot()
            await update_lane(self, *args, **kwargs)
            assert await snapshot() == before
            await assert_ready()
            writes.append(args[1])

        async def attest(*_args, **_kwargs):
            # Observe the window after the PostgreSQL lane and before the Qdrant lane.
            await assert_ready()
            return 0, _EMPTY_DIGEST, 0

        monkeypatch.setattr(PostgresRetrievalProfileRegistry, "update_lane", checked_update)
        monkeypatch.setattr(
            "infinity_context_server.retrieval_profile_composition._bounded_qdrant_attestation",
            attest,
        )
        service = ProfileAwareLocatorRetrievalService(
            registry=registry,
            projection=_Projection(),
            sessions=sessions,
            query_embeddings=object(),
            service_revision="1" * 40,
            runtime_owner=owner,
        )
        for _ in range(3):
            current = await assert_ready()
            observation_now = current.expires_at - renew_before / 2
            assert timedelta(0) < current.expires_at - observation_now < renew_before
            await assert_ready()
            result = await service.reconcile_active(
                now=observation_now, lease_ttl=lease_ttl, renew_before=renew_before
            )
            assert result.complete and result.renewed and result.outcome == "applied"
            renewed = await assert_ready()
            assert renewed.lease_id != current.lease_id
            assert renewed.issued_at == observation_now
            assert renewed.expires_at == observation_now + lease_ttl
            assert renewed.expires_at > current.expires_at
        assert writes == ["postgres_keyword", "qdrant_dense"] * 3
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM memory_locator_profile_transition_audit "
                        "WHERE operation='reconciliation'"
                    )
                )
                == 3
            )
            assert (
                await connection.execute(
                    text("SELECT DISTINCT checked_at FROM memory_locator_profile_lanes")
                )
            ).scalars().all() == [now]

        before = await snapshot()
        changed_at = observation_now + timedelta(seconds=1)
        observation_now = changed_at
        await assert_ready()
        if change.get("raw_sql"):
            # The database trigger still invalidates even a raw SQL semantic no-op.
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memory_locator_profile_lanes SET checked_at=checked_at "
                        "WHERE lane_id='qdrant_dense'"
                    )
                )
        else:
            values = observation | change
            lane_id = values.pop("lane_id", "qdrant_dense")
            await update_lane(
                registry, identity.profile_id, lane_id, checked_at=changed_at, **values
            )
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT checked_at FROM memory_locator_profile_lanes "
                            "WHERE lane_id=:lane"
                        ),
                        {"lane": lane_id},
                    )
                    == changed_at
                )
        after = await snapshot()
        assert after.aggregate_version > before.aggregate_version
        assert after.activation_lease_expires_at < before.activation_lease_expires_at
        assert after.reconciliation_drifted is True
        assert await registry.active_lease(now=observation_now) is None
        async with sessions() as session:
            assert not await is_profile_canonically_queryable(session, identity.profile_id)
    finally:
        await engine.dispose()
        await database.drop()
