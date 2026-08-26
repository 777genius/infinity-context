from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_adapters.postgres import (
    PostgresRetrievalProfileRegistry,
    build_async_engine,
    build_session_factory,
    upgrade_schema,
)
from infinity_context_core.features.context_building.public import (
    InstalledReleaseIdentity,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_active_reconciliation_identity_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_active_reconciliation_identity(database_url))


async def _assert_active_reconciliation_identity(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="active_reconciliation_identity", asyncpg=asyncpg
    )
    now = datetime.now(UTC)
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="reconciliation-identity-runtime",
        generation="generation-current",
        key_id="test-unrecoverable",
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    try:
        await upgrade_schema(engine)
        registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        identity = RetrievalProfileIdentity(
            "profile-active", "profile-generation", "a" * 64, "collection-active"
        )
        await registry.create_building(identity, now=now)
        await registry.checkpoint_backfill(
            identity.profile_id,
            previous_cursor=None,
            cursor=None,
            watermark=0,
            complete=True,
            now=now,
        )
        await registry.update_lane(
            identity.profile_id,
            "qdrant_dense",
            required=True,
            healthy=True,
            profile_qualified=True,
            failure_code=None,
            checked_at=now,
        )
        evidence = await registry.activation_evidence(identity.profile_id, now=now)
        lease = await registry.issue_activation_lease(
            identity.profile_id,
            evidence,
            lease_id="activation-a",
            now=now,
            expires_at=now + timedelta(minutes=5),
        )
        await registry.activate(
            lease,
            evidence,
            now=now,
            maximum_queue_lag=timedelta(minutes=5),
            maximum_retained=1,
        )
        operation = await registry.reconciliation_operation(identity.profile_id)
        await registry.record_reconciliation(
            identity.profile_id,
            evidence,
            operation=operation,
            runtime_owner=owner,
            now=now + timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            drifted=False,
        )

        async with engine.connect() as connection:
            audit = (
                await connection.execute(
                    text(
                        "SELECT audit.runtime_instance_id, audit.runtime_generation, "
                        "runtime.release_identity_sha256, audit.lifecycle_identity_sha256 "
                        "FROM memory_locator_profile_transition_audit AS audit JOIN "
                        "memory_locator_runtime_incarnations AS runtime ON "
                        "runtime.instance_id = audit.runtime_instance_id AND "
                        "runtime.generation = audit.runtime_generation "
                        "WHERE audit.lease_id = :lease_id"
                    ),
                    {"lease_id": operation.operation_id},
                )
            ).one()
        assert tuple(audit) == (
            owner.instance_id,
            owner.generation,
            owner.installed_release.digest(),
            owner.lifecycle_identity_sha256(),
        )
        renewed = await registry.active_lease(now=now + timedelta(seconds=2))
        assert renewed is not None
        rejected_expiry = renewed.expires_at

        with pytest.raises(RuntimeError, match="reconciliation_runtime_identity_missing"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=None,
                now=now + timedelta(seconds=2),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
        stale_generation = replace(
            owner,
            generation="generation-stale",
            launch_token="unrecoverable-launch-stale-generation",
        )
        with pytest.raises(RuntimeError, match="reconciliation_replay_drift"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=stale_generation,
                now=now + timedelta(seconds=2),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
        stale_release = replace(
            owner,
            installed_release=InstalledReleaseIdentity(
                "1" * 40,
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
                "sha256:" + "3" * 64,
            ),
        )
        with pytest.raises(RuntimeError, match="runtime_supervisor_conflict"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=stale_release,
                now=now + timedelta(seconds=2),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
        after_rejections = await registry.active_lease(now=now + timedelta(seconds=2))
        assert after_rejections is not None
        assert after_rejections.expires_at == rejected_expiry
    finally:
        await engine.dispose()
        await database.drop()
