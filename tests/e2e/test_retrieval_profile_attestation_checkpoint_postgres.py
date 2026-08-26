"""PostgreSQL persistence proof for incremental Qdrant attestation manifests."""

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
from infinity_context_core.features.context_building.public import (
    ProfileAttestationPageReceipt,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text


def test_incremental_attestation_manifest_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("disposable PostgreSQL is not configured")
    asyncio.run(_assert_manifest(database_url))


async def _assert_manifest(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="profile_attestation_manifest", asyncpg=asyncpg
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    now = datetime(2026, 8, 25, tzinfo=UTC)
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="attestation-checkpoint-runtime",
        generation="generation-a",
        key_id="test-unrecoverable",
    )
    try:
        await upgrade_schema(engine)
        registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        await registry.create_building(
            RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection-a"),
            now=now,
        )
        receipt = ProfileAttestationPageReceipt(
            0, None, "cursor-256", 256, 32_768, "b" * 64
        )
        await registry.checkpoint_attestation(
            "profile-a",
            "operation-a",
            previous_cursor=None,
            cursor="cursor-256",
            item_count=256,
            digest_accumulator="c" * 64,
            started_at=now,
            deadline_at=now + timedelta(seconds=10),
            now=now,
            complete=False,
            scan_complete=True,
            page_receipt=receipt,
        )

        restarted = PostgresRetrievalProfileRegistry(build_session_factory(engine))
        checkpoint = await restarted.attestation_checkpoint("profile-a", "operation-a")
        assert checkpoint is not None
        assert checkpoint.scan_complete is True
        assert checkpoint.scan_page_count == 1
        assert await restarted.attestation_page_receipt(
            "profile-a", "operation-a", 0
        ) == receipt

        await restarted.checkpoint_attestation(
            "profile-a",
            "operation-a",
            previous_cursor="cursor-256",
            cursor="cursor-256",
            item_count=256,
            digest_accumulator="c" * 64,
            started_at=now,
            deadline_at=now + timedelta(seconds=10),
            now=now,
            complete=True,
            scan_complete=True,
            validation_cursor="cursor-256",
            validation_page_number=1,
            validation_item_count=256,
            validation_accumulator="c" * 64,
        )
        terminal = await restarted.attestation_checkpoint("profile-a", "operation-a")
        assert terminal is not None and terminal.complete is True

        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE memory_locator_profiles SET state = 'active' "
                    "WHERE profile_id = 'profile-a'"
                )
            )
        for renewal in range(8):
            operation = await restarted.reconciliation_operation("profile-a")
            cursor = None
            for page_number in range(65):
                next_cursor = None if page_number == 64 else f"cursor-{page_number + 1}"
                item_count = 16_385 if page_number == 64 else (page_number + 1) * 256
                await restarted.checkpoint_attestation(
                    "profile-a",
                    f"manifest-{renewal}",
                    previous_cursor=cursor,
                    cursor=next_cursor,
                    item_count=item_count,
                    digest_accumulator="d" * 64,
                    started_at=now,
                    deadline_at=now + timedelta(minutes=1),
                    now=now + timedelta(seconds=renewal),
                    complete=False,
                    scan_complete=page_number == 64,
                    page_receipt=ProfileAttestationPageReceipt(
                        page_number,
                        cursor,
                        next_cursor,
                        1 if page_number == 64 else 256,
                        128,
                        f"{page_number:064x}",
                    ),
                    owner_operation_id=operation.operation_id,
                )
                cursor = next_cursor
            await restarted.checkpoint_attestation(
                "profile-a",
                f"manifest-{renewal}",
                previous_cursor=None,
                cursor=None,
                item_count=16_385,
                digest_accumulator="d" * 64,
                started_at=now,
                deadline_at=now + timedelta(minutes=1),
                now=now + timedelta(seconds=renewal),
                complete=True,
                scan_complete=True,
                validation_page_number=65,
                validation_item_count=16_385,
                validation_accumulator="d" * 64,
                owner_operation_id=operation.operation_id,
            )
            async with engine.connect() as connection:
                active_rows = int(
                    await connection.scalar(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM memory_locator_profile_attestation_checkpoints "
                            " WHERE profile_id = 'profile-a') + "
                            "(SELECT count(*) FROM memory_locator_profile_attestation_pages "
                            " WHERE profile_id = 'profile-a')"
                        )
                    )
                )
            assert active_rows <= 67
            evidence = await restarted.activation_evidence("profile-a", now=now)
            await restarted.record_reconciliation(
                "profile-a",
                evidence,
                operation=operation,
                runtime_owner=owner,
                now=now + timedelta(seconds=renewal),
                expires_at=now + timedelta(minutes=2, seconds=renewal),
                drifted=False,
            )
            async with engine.connect() as connection:
                counts = (
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM "
                                "memory_locator_profile_attestation_checkpoints "
                                "WHERE profile_id = 'profile-a'"
                            )
                        )
                    ),
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM memory_locator_profile_attestation_pages "
                                "WHERE profile_id = 'profile-a'"
                            )
                        )
                    ),
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM "
                                "memory_locator_profile_reconciliation_operations "
                                "WHERE profile_id = 'profile-a'"
                            )
                        )
                    ),
                )
            assert counts[0:2] == (1, 0)
            assert counts[2] <= 2
    finally:
        await engine.dispose()
        await database.drop()
