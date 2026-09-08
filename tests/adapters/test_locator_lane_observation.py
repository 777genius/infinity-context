"""Provider-free SQL emission regression; PostgreSQL trigger proof lives in E2E."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from infinity_context_adapters.postgres import locator_profile_lifecycle as lifecycle
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("required", False),
        ("healthy", False),
        ("profile_qualified", False),
        ("failure_code", "synthetic_failure"),
        ("observed_count", 1),
        ("observed_digest", "f" * 64),
    ],
)
def test_lane_observation_emits_update_only_for_changed_evidence(monkeypatch, field, value):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC)
        evidence = dict(
            required=True,
            healthy=True,
            profile_qualified=True,
            failure_code=None,
            observed_count=0,
            observed_digest="a" * 64,
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lifecycle.MemoryLocatorProfileLaneRow.__table__.create)
            async with sessions() as session, session.begin():
                session.add(
                    lifecycle.MemoryLocatorProfileLaneRow(
                        profile_id="synthetic", lane_id="qdrant_dense", checked_at=now, **evidence
                    )
                )
            # Only the PostgreSQL locks/fence and parent lookup are substituted.
            # Lane loading, dirty tracking, transaction commit and SQL emission are real.
            original_get = AsyncSession.get

            async def get(self, entity, key, **kwargs):
                if entity is lifecycle.MemoryLocatorProfileRow:
                    assert kwargs == {"with_for_update": True}
                    return object()
                return await original_get(self, entity, key, **kwargs)

            monkeypatch.setattr(AsyncSession, "get", get)
            gates = [AsyncMock() for _ in range(3)]
            for name, gate in zip(
                ("_lock_maintenance", "_lock_profile_evidence", "_fence_reconciliation_write"),
                gates,
                strict=True,
            ):
                monkeypatch.setattr(lifecycle, name, gate)
            updates = []
            event.listen(
                engine.sync_engine,
                "before_cursor_execute",
                lambda _c, _u, sql, *_a: updates.append(sql) if sql.startswith("UPDATE") else None,
            )
            registry = lifecycle.PostgresRetrievalProfileRegistry(sessions)
            observation = evidence | ({field: value} if field else {})
            await registry.update_lane(
                "synthetic", "qdrant_dense", checked_at=now + timedelta(seconds=16), **observation
            )
            assert len(updates) == int(field is not None)
            for gate in gates:
                gate.assert_awaited_once()
            # Even an identical observation must pass the runtime fence first.
            gates[-1].side_effect = RuntimeError("synthetic_stale_runtime")
            with pytest.raises(RuntimeError, match="synthetic_stale_runtime"):
                await registry.update_lane(
                    "synthetic",
                    "qdrant_dense",
                    checked_at=now + timedelta(seconds=17),
                    **observation,
                )
            assert len(updates) == int(field is not None)
        finally:
            await engine.dispose()

    asyncio.run(scenario())
