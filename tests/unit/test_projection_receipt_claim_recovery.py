from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from infinity_context_adapters.postgres.benchmark_run_models import (
    MemoryComparisonBenchmarkRunRow,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.orm import Base
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow
from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryCleanupInventoryKeyRow,
    MemoryCleanupInventoryMaterializationRow,
    MemoryCleanupV3ContextAuthorityRow,
    MemoryProjectionReceiptClaimRow,
    MemoryProjectionReceiptIdentityLinkRow,
    MemoryProjectionResultReceiptRow,
    MemoryProjectionTargetIdentityRow,
)
from infinity_context_adapters.postgres.projection_receipt_repository import (
    PostgresProjectionReceiptRepository,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionMaterialization,
    ProjectionReceiptError,
)
from infinity_context_server.projection_receipt_worker import ProjectionReceiptWorker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_projection_result_receipts import (
    AUTHENTICATOR,
    V3_AUTHORITY,
    V3_CONTEXT,
    WHEN,
    _binding,
    _delete_binding,
    _identity,
    _seed_canonical_job,
    _seed_grouped_delete_job,
)

from tests.e2e.postgres_test_database import PostgresTestDatabase


class _StatefulProvider:
    def __init__(self) -> None:
        self.value: ProjectionMaterialization | None = None
        self.reads = 0
        self.upserts = 0

    async def read_exact(self, _binding):
        self.reads += 1
        return () if self.value is None else (self.value,)

    async def upsert_exact(self, binding, identities):
        self.upserts += 1
        self.value = ProjectionMaterialization(
            projection_key_sha256=binding.projection_key_sha256,
            identities=identities,
            completed_at=WHEN,
        )

    async def delete_exact(self, _binding, _identities):
        raise AssertionError("delete is not expected")


def test_worker_durable_replay_skips_all_provider_io() -> None:
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        tables = (
            MemorySpaceRow.__table__,
            MemoryComparisonBenchmarkRunRow.__table__,
            MemoryOutboxRow.__table__,
            MemoryChunkRow.__table__,
            MemoryCleanupV3ContextAuthorityRow.__table__,
            MemoryCleanupInventoryMaterializationRow.__table__,
            MemoryCleanupInventoryKeyRow.__table__,
            MemoryProjectionReceiptClaimRow.__table__,
            MemoryProjectionTargetIdentityRow.__table__,
            MemoryProjectionResultReceiptRow.__table__,
            MemoryProjectionReceiptIdentityLinkRow.__table__,
        )
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        await _seed_canonical_job(sessions)
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(
                session, AUTHENTICATOR
            ).register_context_authority(
                context=V3_CONTEXT, authority=V3_AUTHORITY, registered_at=WHEN
            )
        provider = _StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        first = await worker.ensure_projection_and_readback(
            binding=_binding(), expected_identities=(_identity(),)
        )
        calls = (provider.reads, provider.upserts)
        second = await worker.ensure_projection_and_readback(
            binding=_binding(), expected_identities=(_identity(),)
        )
        assert second == first
        assert (provider.reads, provider.upserts) == calls
        await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_workers_perform_one_provider_mutation(tmp_path) -> None:
    class BarrierProvider(_StatefulProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def upsert_exact(self, binding, identities):
            self.upserts += 1
            self.value = ProjectionMaterialization(
                projection_key_sha256=binding.projection_key_sha256,
                identities=identities,
                completed_at=WHEN,
            )
            self.started.set()
            await self.release.wait()

    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "claims.db")
        provider = BarrierProvider()
        first_worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        second_worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        first_task = asyncio.create_task(
            first_worker.ensure_projection_and_readback(
                binding=_binding(), expected_identities=(_identity(),)
            )
        )
        await provider.started.wait()
        second_task = asyncio.create_task(
            second_worker.ensure_projection_and_readback(
                binding=_binding(), expected_identities=(_identity(),)
            )
        )
        for _ in range(100):
            async with sessions() as session:
                stored = await session.get(MemoryProjectionResultReceiptRow, 7)
            if stored is not None:
                break
            await asyncio.sleep(0.01)
        assert stored is not None
        provider.release.set()
        first, second = await asyncio.gather(first_task, second_task)
        assert first == second
        assert provider.upserts == 1
        await cleanup()

    asyncio.run(scenario())


def test_expired_prepared_claim_is_reclaimed_and_stale_owner_is_fenced(tmp_path) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "expiry.db")
        async with sessions() as session, session.begin():
            repository = PostgresProjectionReceiptRepository(session, AUTHENTICATOR)
            first_token, first_generation = await repository.claim_job_preflight(
                binding=_binding(), operation="upsert", expected_identities=(_identity(),)
            )
        async with sessions() as session, session.begin():
            claim = await session.get(MemoryProjectionReceiptClaimRow, 7)
            assert claim is not None
            claim.lease_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        async with sessions() as session, session.begin():
            second_token, second_generation = await PostgresProjectionReceiptRepository(
                session, AUTHENTICATOR
            ).claim_job_preflight(
                binding=_binding(), operation="upsert", expected_identities=(_identity(),)
            )
        assert second_generation == first_generation + 1
        assert second_token != first_token
        async with sessions() as session, session.begin():
            with pytest.raises(ProjectionReceiptError, match="claim_fenced"):
                await PostgresProjectionReceiptRepository(
                    session, AUTHENTICATOR
                ).mark_dispatch_started(
                    binding=_binding(),
                    operation="upsert",
                    expected_identities=(_identity(),),
                    claim_token=first_token,
                    generation=first_generation,
                )
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(session, AUTHENTICATOR).mark_dispatch_started(
                binding=_binding(),
                operation="upsert",
                expected_identities=(_identity(),),
                claim_token=second_token,
                generation=second_generation,
            )
        async with sessions() as session:
            claim = await session.get(MemoryProjectionReceiptClaimRow, 7)
            assert claim is not None
            assert claim.state == "dispatch_started"
            assert claim.generation == 2
        await engine.dispose()

    asyncio.run(scenario())


_TABLES = (
    MemorySpaceRow.__table__,
    MemoryComparisonBenchmarkRunRow.__table__,
    MemoryOutboxRow.__table__,
    MemoryChunkRow.__table__,
    MemoryCleanupV3ContextAuthorityRow.__table__,
    MemoryProjectionReceiptClaimRow.__table__,
    MemoryProjectionTargetIdentityRow.__table__,
    MemoryProjectionResultReceiptRow.__table__,
    MemoryProjectionReceiptIdentityLinkRow.__table__,
)


async def _setup(tmp_path, name: str):
    database = None
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if database_url:
        asyncpg = pytest.importorskip("asyncpg")
        database = PostgresTestDatabase.from_url(
            database_url, prefix="projection_claim", asyncpg=asyncpg
        )
        await database.recreate()
        engine = create_async_engine(database.app_url)
    else:
        engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / name))
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_TABLES))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _seed_canonical_job(sessions)
    async with sessions() as session, session.begin():
        await PostgresProjectionReceiptRepository(
            session, AUTHENTICATOR
        ).register_context_authority(context=V3_CONTEXT, authority=V3_AUTHORITY, registered_at=WHEN)

    async def cleanup() -> None:
        await engine.dispose()
        if database is not None:
            await database.drop()

    return engine, sessions, cleanup


async def _mark_upsert_dispatch_started(sessions) -> None:
    async with sessions() as session, session.begin():
        repository = PostgresProjectionReceiptRepository(session, AUTHENTICATOR)
        token, generation = await repository.claim_job_preflight(
            binding=_binding(), operation="upsert", expected_identities=(_identity(),)
        )
    async with sessions() as session, session.begin():
        await PostgresProjectionReceiptRepository(session, AUTHENTICATOR).mark_dispatch_started(
            binding=_binding(),
            operation="upsert",
            expected_identities=(_identity(),),
            claim_token=token,
            generation=generation,
        )


def test_dispatch_started_upsert_present_reconciles_without_mutation(tmp_path) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "present.db")
        await _mark_upsert_dispatch_started(sessions)
        provider = _StatefulProvider()
        provider.value = ProjectionMaterialization(
            projection_key_sha256=_binding().projection_key_sha256,
            identities=(_identity(),),
            completed_at=WHEN,
        )
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        receipt = await worker.ensure_projection_and_readback(
            binding=_binding(), expected_identities=(_identity(),)
        )
        assert receipt.result_state == "present"
        assert provider.upserts == 0
        async with sessions() as session:
            assert await session.get(MemoryProjectionReceiptClaimRow, 7) is None
        await cleanup()

    asyncio.run(scenario())


def test_dispatch_started_upsert_absent_is_outcome_unknown_without_redispatch(
    tmp_path,
) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "absent.db")
        await _mark_upsert_dispatch_started(sessions)
        provider = _StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        with pytest.raises(ProjectionReceiptError, match="outcome_unknown"):
            await worker.ensure_projection_and_readback(
                binding=_binding(), expected_identities=(_identity(),)
            )
        assert provider.upserts == 0
        async with sessions() as session:
            claim = await session.get(MemoryProjectionReceiptClaimRow, 7)
            assert claim is not None and claim.state == "dispatch_started"
        await cleanup()

    asyncio.run(scenario())


def test_forged_future_worker_clock_cannot_steal_live_prepared_claim(tmp_path) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "forged-clock.db")
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(session, AUTHENTICATOR).claim_job_preflight(
                binding=_binding(),
                operation="upsert",
                expected_identities=(_identity(),),
            )
        provider = _StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN + timedelta(days=36500),
        )
        with pytest.raises(ProjectionReceiptError, match="claim_busy"):
            await worker._claim_job_preflight(
                _binding(), operation="upsert", expected_identities=(_identity(),)
            )
        assert provider.upserts == 0
        await cleanup()

    asyncio.run(scenario())


def test_dispatch_started_delete_absent_reconciles_without_mutation(tmp_path) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "delete-absent.db")
        await _seed_grouped_delete_job(sessions)
        binding = _delete_binding()
        async with sessions() as session, session.begin():
            repository = PostgresProjectionReceiptRepository(session, AUTHENTICATOR)
            token, generation = await repository.claim_job_preflight(
                binding=binding,
                operation="delete",
                expected_identities=(_identity(),),
            )
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(session, AUTHENTICATOR).mark_dispatch_started(
                binding=binding,
                operation="delete",
                expected_identities=(_identity(),),
                claim_token=token,
                generation=generation,
            )
        provider = _StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        receipt = await worker.ensure_deletion_and_readback(
            binding=binding, expected_identities=(_identity(),)
        )
        assert receipt.operation == "delete"
        assert receipt.result_state == "absent"
        assert provider.upserts == 0
        async with sessions() as session:
            assert await session.get(MemoryProjectionReceiptClaimRow, 8) is None
            outbox = await session.get(MemoryOutboxRow, 8)
            assert outbox is not None and outbox.status == "done"
        await cleanup()

    asyncio.run(scenario())


def test_projection_receipt_orm_constraint_names_match_migration_0035() -> None:
    expected = {
        MemoryCleanupV3ContextAuthorityRow.__table__: {
            "uq_cleanup_v3_context_authority_run_context",
            "uq_cleanup_v3_context_authority_run_context_terminal",
            "ck_projection_context_authority_digests",
        },
        MemoryProjectionReceiptClaimRow.__table__: {
            "fk_projection_receipt_claim_context",
            "ck_projection_receipt_claim_digests",
            "ck_projection_receipt_claim_state",
        },
        MemoryProjectionResultReceiptRow.__table__: {
            "fk_projection_receipt_context_authority",
            "ck_projection_receipt_identity_count",
            "ck_projection_receipt_lane",
            "ck_projection_receipt_operation",
            "ck_projection_receipt_result_state",
            "ck_projection_receipt_operation_result",
            "ck_projection_receipt_digests",
            "uq_projection_receipt_outbox_run",
            "uq_projection_receipt_canonical_job",
            "ix_projection_receipts_cleanup_page",
            "ix_projection_receipts_inventory_page",
            "ix_projection_receipts_operation_page",
            "ix_projection_receipts_delete_page",
        },
        MemoryProjectionTargetIdentityRow.__table__: {
            "ck_projection_identity_physical_value",
            "ck_projection_identity_digests",
            "ck_projection_identity_kind",
            "uq_projection_identity_authenticated",
        },
        MemoryProjectionReceiptIdentityLinkRow.__table__: {
            "fk_projection_receipt_link_identity",
            "fk_projection_receipt_link_receipt",
            "ck_projection_receipt_link_ordinal",
            "ck_projection_receipt_link_digests",
            "uq_projection_receipt_link_ordinal",
            "ix_projection_links_identity_outbox",
            "ix_projection_links_outbox_page",
        },
        MemoryCleanupInventoryMaterializationRow.__table__: {
            "fk_cleanup_inventory_context_authority",
            "ck_cleanup_inventory_expected_count",
            "ck_cleanup_inventory_materialization_kind",
            "ck_cleanup_inventory_materialization_digests",
        },
        MemoryCleanupInventoryKeyRow.__table__: {
            "fk_cleanup_inventory_key_materialization",
            "uq_cleanup_inventory_locator",
            "ck_cleanup_inventory_key_kind",
            "ck_cleanup_inventory_key_digests",
        },
    }
    for table, required in expected.items():
        observed = {constraint.name for constraint in table.constraints}
        observed.update(index.name for index in table.indexes)
        assert required <= observed
    assert {index.name for index in MemoryProjectionResultReceiptRow.__table__.indexes} == {
        "ix_projection_receipts_run_receipt",
        "ix_projection_receipts_cleanup_page",
        "ix_projection_receipts_inventory_page",
        "ix_projection_receipts_operation_page",
        "ix_projection_receipts_delete_page",
    }
    assert "ix_memory_scopes_space_id_id" in {
        index.name for index in MemoryScopeRow.__table__.indexes
    }
    assert "ix_memory_threads_space_scope_id" in {
        index.name for index in MemoryThreadRow.__table__.indexes
    }


def test_prepared_claim_busy_path_performs_zero_provider_reads(tmp_path) -> None:
    async def scenario() -> None:
        engine, sessions, cleanup = await _setup(tmp_path, "prepared-busy.db")
        async with sessions() as session, session.begin():
            await PostgresProjectionReceiptRepository(session, AUTHENTICATOR).claim_job_preflight(
                binding=_binding(),
                operation="upsert",
                expected_identities=(_identity(),),
            )
        provider = _StatefulProvider()
        worker = ProjectionReceiptWorker(
            session_factory=sessions,
            provider=provider,
            authenticator=AUTHENTICATOR,
            now=lambda: WHEN,
        )
        with pytest.raises(ProjectionReceiptError, match="claim_busy"):
            await worker.ensure_projection_and_readback(
                binding=_binding(), expected_identities=(_identity(),)
            )
        assert provider.reads == 0
        assert provider.upserts == 0
        async with sessions() as session:
            claim = await session.get(MemoryProjectionReceiptClaimRow, 7)
            assert claim is not None and claim.state == "prepared"
        await cleanup()

    asyncio.run(scenario())
