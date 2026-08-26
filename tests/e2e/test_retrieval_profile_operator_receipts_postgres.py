"""Durable lost-response replay proof for every strict-admin profile phase."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime

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
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_operator_receipts_survive_lost_responses_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL is not configured")
    asyncio.run(_assert_durable_receipts(database_url))


async def _assert_durable_receipts(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="profile_operator_receipts", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    now = datetime(2026, 8, 25, tzinfo=UTC)
    provenance = _provenance()
    try:
        upgraded = await upgrade_schema(engine)
        assert upgraded.current == "0052_document_scope_listing_indexes"
        registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        for operation in ("create", "rebuild", "attest", "activate"):
            key = f"lost-response-{operation}"
            fingerprint = hashlib.sha256(operation.encode()).hexdigest()
            result = {
                "operation": operation,
                "profile_id": "profile-a",
                "idempotency_key": key,
                "phase": "complete",
                "runtime_trust_provenance": provenance,
            }
            await registry.record_operator_receipt(
                idempotency_key=key,
                request_fingerprint=fingerprint,
                operation=operation,
                profile_id="profile-a",
                result=result,
                now=now,
            )
            # The response is now considered lost. A freshly composed repository
            # must replay the exact durable JSON without executing another phase.
            restarted = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            assert await restarted.operator_receipt(
                idempotency_key=key, request_fingerprint=fingerprint
            ) == result

        with pytest.raises(RuntimeError, match="idempotency_conflict"):
            await registry.operator_receipt(
                idempotency_key="lost-response-create",
                request_fingerprint="f" * 64,
            )
        async with engine.connect() as connection:
            bound = await connection.scalar(
                text(
                    "SELECT count(*) FROM memory_locator_profile_operator_receipts "
                    "WHERE runtime_instance_id IS NOT NULL "
                    "AND launch_identity_sha256 IS NOT NULL "
                    "AND release_identity_sha256 IS NOT NULL "
                    "AND lifecycle_identity_sha256 IS NOT NULL"
                )
            )
        assert int(bound or 0) == 4
        await _assert_rebuild_crash_atomicity(registry, now, provenance)
    finally:
        await engine.dispose()
        await database.drop()


async def _assert_rebuild_crash_atomicity(registry, now, provenance) -> None:
    identity = RetrievalProfileIdentity(
        "profile-crash", "generation-crash", "c" * 64, "collection-crash"
    )
    await registry.create_building(identity, now=now)
    key = "rebuild-crash-boundary"
    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    result = {
        "operation": "rebuild",
        "profile_id": identity.profile_id,
        "idempotency_key": key,
        "phase": "pending",
        "projected_count": 0,
        "next_cursor": "cursor-after-page",
        "runtime_trust_provenance": provenance,
    }
    plan = {
        "previous_cursor": None,
        "next_cursor": "cursor-after-page",
        "watermark": 7,
        "complete": False,
        "items": [],
        "result": result,
    }
    await registry.prepare_operator_rebuild(
        idempotency_key=key,
        request_fingerprint=fingerprint,
        profile_id=identity.profile_id,
        plan=plan,
        now=now,
    )

    def crash() -> None:
        raise RuntimeError("injected_after_checkpoint_before_receipt")

    with pytest.raises(RuntimeError, match="injected_after_checkpoint"):
        await registry.commit_operator_rebuild(
            identity.profile_id,
            (),
            idempotency_key=key,
            request_fingerprint=fingerprint,
            previous_cursor=None,
            cursor="cursor-after-page",
            watermark=7,
            complete=False,
            result=result,
            now=now,
            crash_after_checkpoint=crash,
        )
    assert await registry.backfill_cursor(identity.profile_id) is None
    assert await registry.operator_receipt(
        idempotency_key=key, request_fingerprint=fingerprint
    ) is None
    assert await registry.operator_rebuild_plan(
        idempotency_key=key, request_fingerprint=fingerprint
    ) == plan

    committed = await registry.commit_operator_rebuild(
        identity.profile_id,
        (),
        idempotency_key=key,
        request_fingerprint=fingerprint,
        previous_cursor=None,
        cursor="cursor-after-page",
        watermark=7,
        complete=False,
        result=result,
        now=now,
    )
    assert committed == result
    assert await registry.backfill_cursor(identity.profile_id) == "cursor-after-page"
    assert await registry.operator_receipt(
        idempotency_key=key, request_fingerprint=fingerprint
    ) == result


def _provenance() -> dict[str, object]:
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="operator-receipt-test",
        generation="operator-receipt-generation",
    )
    payload = owner.lifecycle_identity_payload()
    payload["receipt_identity_sha256"] = owner.lifecycle_identity_sha256()
    return payload
