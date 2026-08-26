from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import (
    PostgresRetrievalProfileRegistry,
    build_async_engine,
    build_session_factory,
    upgrade_schema,
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


def test_active_reconciliation_converges_after_its_lane_writes(monkeypatch) -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")

    async def attest(_registry, _projection, _identity, **_kwargs):
        return 0, _EMPTY_DIGEST, 0

    monkeypatch.setattr(
        "infinity_context_server.retrieval_profile_composition._bounded_qdrant_attestation",
        attest,
    )
    asyncio.run(_assert_reconciliation_converges(database_url))


async def _assert_reconciliation_converges(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="active_reconciliation",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    now = datetime.now(UTC)
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="reconciliation-orchestration-runtime",
        generation="generation-current",
        key_id="test-unrecoverable",
    )
    registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
    identity = RetrievalProfileIdentity(
        "profile-active", "profile-generation", "a" * 64, "collection-active"
    )
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
            lease_id="activation-short",
            now=now,
            expires_at=now + timedelta(seconds=5),
        )
        await registry.activate(
            lease,
            evidence,
            now=now,
            maximum_queue_lag=timedelta(minutes=5),
            maximum_retained=1,
        )
        service = ProfileAwareLocatorRetrievalService(
            fallback=object(),
            registry=registry,
            projection=_Projection(),
            sessions=object(),
            query_embeddings=object(),
            runtime_owner=owner,
        )

        first = await service.reconcile_active(now=now)
        second = await service.reconcile_active(now=now + timedelta(seconds=20))

        assert first.complete is True
        assert first.renewed is True
        assert first.outcome == "applied"
        assert second.complete is True
        assert second.renewed is True
        assert second.outcome == "applied"
        async with engine.connect() as connection:
            reconciliations = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM memory_locator_profile_transition_audit "
                        "WHERE profile_id=:profile_id AND operation='reconciliation'"
                    ),
                    {"profile_id": identity.profile_id},
                )
                or 0
            )
        assert reconciliations == 2
    finally:
        await engine.dispose()
        await database.drop()


class _Projection:
    def adapter_for(self, _identity):
        return self

    async def capabilities(self):
        return SimpleNamespace(
            enabled=True,
            healthy=True,
            supports_search=True,
            supports_filters=True,
        )


_EMPTY_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
