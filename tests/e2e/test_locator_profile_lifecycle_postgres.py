"""Real PostgreSQL proof for immutable profile identity and atomic activation."""

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
from infinity_context_core.features.context_building.public import (
    ProfileAttestationPageReceipt,
    ProfileCollectionDeleteAuthorization,
    ProfileReconciliationOperation,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_profile_lifecycle_when_postgres_is_configured() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_profile_lifecycle(database_url))


async def _assert_profile_lifecycle(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url, prefix="locator_profile_lifecycle", asyncpg=asyncpg
    )
    now = datetime.now(UTC)
    owner = RuntimeFenceOwner.unrecoverable_current(
        instance_id="postgres-e2e-runtime",
        generation="generation-a",
        key_id="test-unrecoverable",
    )
    try:
        await database.recreate()
        engine = build_async_engine(database.app_url)
        try:
            await upgrade_schema(engine)
            registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            first = RetrievalProfileIdentity("profile-a", "gen-a", "a" * 64, "collection-a")
            await registry.create_building(first, now=now)
            await registry.create_building(first, now=now)
            conflicting_replay = RetrievalProfileIdentity(
                "profile-a", "gen-other", "f" * 64, "collection-other"
            )
            with pytest.raises(RuntimeError, match="idempotency_conflict"):
                await registry.create_building(conflicting_replay, now=now)
            await registry.checkpoint_backfill(
                first.profile_id,
                previous_cursor=None,
                cursor=None,
                watermark=0,
                complete=True,
                now=now,
            )
            await registry.update_lane(
                first.profile_id,
                "qdrant_dense",
                required=True,
                healthy=True,
                profile_qualified=True,
                failure_code=None,
                checked_at=now,
            )
            initial_evidence = await registry.activation_evidence(first.profile_id, now=now)
            stale_lease = await registry.issue_activation_lease(
                first.profile_id,
                initial_evidence,
                lease_id="lease-a-stale",
                now=now,
                expires_at=now + timedelta(seconds=30),
            )
            exact_lease = await registry.issue_activation_lease(
                first.profile_id,
                initial_evidence,
                lease_id="lease-a",
                now=now,
                expires_at=now + timedelta(seconds=30),
            )
            with pytest.raises(RuntimeError, match="activation_lease_invalid"):
                await registry.activate(
                    stale_lease,
                    initial_evidence,
                    now=now,
                    maximum_queue_lag=timedelta(minutes=5),
                    maximum_retained=10,
                )
            await registry.activate(
                exact_lease,
                initial_evidence,
                now=now,
                maximum_queue_lag=timedelta(minutes=5),
                maximum_retained=10,
            )
            restarted_registry = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            operation_ids = await asyncio.gather(
                registry.reconciliation_operation(first.profile_id),
                restarted_registry.reconciliation_operation(first.profile_id),
            )
            assert operation_ids[0] == operation_ids[1]
            for checkpoint_id in (
                "superseded-reconciliation",
                operation_ids[0].operation_id,
            ):
                await registry.checkpoint_attestation(
                    first.profile_id,
                    checkpoint_id,
                    previous_cursor=None,
                    cursor=None,
                    item_count=0,
                    digest_accumulator="0" * 64,
                    started_at=now,
                    deadline_at=now + timedelta(seconds=30),
                    now=now,
                    complete=True,
                    scan_complete=True,
                    owner_operation_id=(
                        operation_ids[0].operation_id
                        if checkpoint_id == operation_ids[0].operation_id
                        else "superseded-operation"
                    ),
                )
            reconciliation_evidence = await registry.activation_evidence(first.profile_id, now=now)
            wrong_predecessor = ProfileReconciliationOperation(
                "reconcile-wrong-predecessor-lease",
                first.profile_id,
                "different-lease-with-identical-metadata",
                operation_ids[0].predecessor_generation,
                operation_ids[0].predecessor_evidence_digest,
                operation_ids[0].predecessor_lease_issued_at,
                operation_ids[0].predecessor_lease_expires_at,
                operation_ids[0].predecessor_drifted,
            )
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO memory_locator_profile_reconciliation_operations "
                        "(profile_id, operation_id, predecessor_lease_id, "
                        "predecessor_generation, predecessor_evidence_digest, "
                        "predecessor_lease_issued_at, predecessor_lease_expires_at, "
                        "predecessor_drifted, created_at) VALUES "
                        "(:profile_id, :operation_id, :lease_id, :generation, :digest, "
                        ":issued_at, :expires_at, :drifted, :created_at)"
                    ),
                    {
                        "profile_id": first.profile_id,
                        "operation_id": wrong_predecessor.operation_id,
                        "lease_id": wrong_predecessor.predecessor_lease_id,
                        "generation": wrong_predecessor.predecessor_generation,
                        "digest": wrong_predecessor.predecessor_evidence_digest,
                        "issued_at": wrong_predecessor.predecessor_lease_issued_at,
                        "expires_at": wrong_predecessor.predecessor_lease_expires_at,
                        "drifted": wrong_predecessor.predecessor_drifted,
                        "created_at": now,
                    },
                )
            with pytest.raises(RuntimeError, match="reconciliation_(superseded|operation_invalid)"):
                await registry.record_reconciliation(
                    first.profile_id,
                    reconciliation_evidence,
                    operation=wrong_predecessor,
                    runtime_owner=owner,
                    now=now,
                    expires_at=now + timedelta(minutes=5),
                    drifted=False,
                )
            with pytest.raises(RuntimeError, match="reconciliation_superseded"):
                await registry.mark_reconciliation_drift(
                    first.profile_id, operation=wrong_predecessor, now=now
                )
            await asyncio.gather(
                registry.record_reconciliation(
                    first.profile_id,
                    reconciliation_evidence,
                    operation=operation_ids[0],
                    runtime_owner=owner,
                    now=now,
                    expires_at=now + timedelta(seconds=30),
                    drifted=False,
                ),
                restarted_registry.record_reconciliation(
                    first.profile_id,
                    reconciliation_evidence,
                    operation=operation_ids[0],
                    runtime_owner=owner,
                    now=now,
                    expires_at=now + timedelta(seconds=30),
                    drifted=False,
                ),
            )
            assert (
                await registry.attestation_checkpoint(first.profile_id, "superseded-reconciliation")
                is None
            )
            assert (
                await registry.attestation_checkpoint(
                    first.profile_id, operation_ids[0].operation_id
                )
                is not None
            )
            assert (
                await restarted_registry.active_lease(now=now + timedelta(seconds=29)) is not None
            )
            await registry.record_reconciliation(
                first.profile_id,
                reconciliation_evidence,
                operation=operation_ids[0],
                runtime_owner=owner,
                now=now + timedelta(seconds=1),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
            exact_replay = await registry.active_lease(now=now + timedelta(seconds=29))
            assert exact_replay is not None
            assert exact_replay.expires_at == now + timedelta(seconds=30)
            assert (
                await restarted_registry.reconciliation_operation(first.profile_id)
                != operation_ids[0]
            )
            successor = await restarted_registry.reconciliation_operation(first.profile_id)
            successor_evidence = await restarted_registry.activation_evidence(
                first.profile_id, now=now
            )
            await restarted_registry.record_reconciliation(
                first.profile_id,
                successor_evidence,
                operation=successor,
                runtime_owner=owner,
                now=now + timedelta(seconds=1),
                expires_at=now + timedelta(seconds=40),
                drifted=False,
            )
            with pytest.raises(RuntimeError, match="reconciliation_(superseded|operation_invalid)"):
                await registry.record_reconciliation(
                    first.profile_id,
                    reconciliation_evidence,
                    operation=operation_ids[0],
                    runtime_owner=owner,
                    now=now + timedelta(seconds=2),
                    expires_at=now + timedelta(minutes=10),
                    drifted=False,
                )
            winner = await registry.active_lease(now=now + timedelta(seconds=39))
            assert winner is not None
            assert winner.lease_id == successor.operation_id
            assert winner.expires_at == now + timedelta(seconds=40)
            started_epoch = await registry.begin_provider_mutation(
                first.profile_id,
                "concurrent-qdrant-write",
                owner=owner,
                now=now + timedelta(seconds=3),
                expires_at=now + timedelta(seconds=20),
            )
            assert await registry.active_lease(now=now + timedelta(seconds=3)) is None
            with pytest.raises(RuntimeError, match="provider_mutation_active"):
                await restarted_registry.provider_attestation_epoch(
                    first.profile_id, now=now + timedelta(seconds=3)
                )
            with pytest.raises(RuntimeError, match="provider_mutation_active"):
                await restarted_registry.provider_attestation_epoch(
                    first.profile_id, now=now + timedelta(seconds=30)
                )
            with pytest.raises(RuntimeError, match="provider_mutation_fenced"):
                await registry.finish_provider_mutation(
                    first.profile_id,
                    "concurrent-qdrant-write",
                    owner=owner,
                    started_epoch=started_epoch + 1,
                    now=now + timedelta(seconds=4),
                )
            finished_epoch = await registry.finish_provider_mutation(
                first.profile_id,
                "concurrent-qdrant-write",
                owner=owner,
                started_epoch=started_epoch,
                now=now + timedelta(seconds=4),
            )
            assert finished_epoch == started_epoch + 1
            assert (
                await restarted_registry.provider_attestation_epoch(
                    first.profile_id, now=now + timedelta(seconds=4)
                )
                == finished_epoch
            )
            gate_operation = await registry.reconciliation_operation(first.profile_id)
            gate_evidence = await registry.activation_evidence(first.profile_id, now=now)
            adverse = await engine.connect()
            adverse_transaction = await adverse.begin()
            await adverse.execute(
                text(
                    "UPDATE memory_locator_profile_lanes SET healthy = FALSE, "
                    "profile_qualified = FALSE WHERE profile_id = 'profile-a' "
                    "AND lane_id = 'qdrant_dense'"
                )
            )
            gated_completion = asyncio.create_task(
                registry.record_reconciliation(
                    first.profile_id,
                    gate_evidence,
                    operation=gate_operation,
                    runtime_owner=owner,
                    now=now + timedelta(seconds=5),
                    expires_at=now + timedelta(seconds=35),
                    drifted=False,
                    mutation_epoch=finished_epoch,
                )
            )
            await asyncio.sleep(0)
            assert not gated_completion.done()
            await adverse_transaction.commit()
            await adverse.close()
            with pytest.raises(RuntimeError, match="reconciliation_(raced|superseded)"):
                await asyncio.wait_for(gated_completion, timeout=5)
            assert await registry.active_lease(now=now + timedelta(seconds=5)) is None
            await registry.update_lane(
                first.profile_id,
                "qdrant_dense",
                required=True,
                healthy=True,
                profile_qualified=True,
                failure_code=None,
                checked_at=now + timedelta(seconds=6),
            )

            second = RetrievalProfileIdentity("profile-b", "gen-b", "b" * 64, "collection-b")
            await registry.create_building(second, now=now)
            await registry.checkpoint_backfill(
                second.profile_id,
                previous_cursor=None,
                cursor=None,
                watermark=0,
                complete=True,
                now=now,
            )
            await registry.update_lane(
                second.profile_id,
                "qdrant_dense",
                required=True,
                healthy=True,
                profile_qualified=True,
                failure_code=None,
                checked_at=now,
            )
            query_predecessor = await registry.reconciliation_operation(first.profile_id)
            query_evidence = await registry.activation_evidence(first.profile_id, now=now)
            await registry.record_reconciliation(
                first.profile_id,
                query_evidence,
                operation=query_predecessor,
                runtime_owner=owner,
                now=now,
                expires_at=now + timedelta(seconds=30),
                drifted=False,
                mutation_epoch=finished_epoch,
            )
            active_lease = await registry.active_lease(now=now)
            assert active_lease is not None
            query_admission = await registry.begin_profile_query(
                "query-crossing-activation",
                owner=owner,
                now=now,
                expires_at=now + timedelta(seconds=5),
            )
            assert query_admission.status == "admitted"
            query_identity = query_admission.identity
            query_lease_id = query_admission.activation_lease_id
            assert query_identity is not None and query_lease_id is not None
            assert query_identity.profile_id == first.profile_id
            assert query_lease_id == active_lease.lease_id
            with pytest.raises(RuntimeError, match="activation_raced"):
                await _activate(registry, second.profile_id, now, "lease-b-query-raced", 10)
            with pytest.raises(RuntimeError, match="query_fenced"):
                await registry.finish_profile_query(
                    first.profile_id,
                    "query-crossing-activation",
                    owner=owner,
                    activation_lease_id="different-lease",
                )
            await registry.finish_profile_query(
                first.profile_id,
                "query-crossing-activation",
                owner=owner,
                activation_lease_id=query_lease_id,
            )
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO memory_locator_profile_tombstones "
                        "(profile_id, chunk_id, canonical_version, created_at, updated_at) "
                        "VALUES ('profile-a', 'deleted-chunk', 1, :now, :now)"
                    ),
                    {"now": now},
                )
            with pytest.raises(RuntimeError, match="retrieval_profile_activation_raced"):
                await _activate(registry, second.profile_id, now, "lease-b-rejected", 10)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE memory_locator_profile_tombstones SET completed_at = :now "
                        "WHERE profile_id = 'profile-a' AND chunk_id = 'deleted-chunk'"
                    ),
                    {"now": now},
                )
            activation_evidence = await registry.activation_evidence(second.profile_id, now=now)
            activation_epoch = await registry.provider_attestation_epoch(
                second.profile_id, now=now
            )
            activation_lease = await registry.issue_activation_lease(
                second.profile_id,
                activation_evidence,
                lease_id="lease-b",
                now=now,
                expires_at=now + timedelta(seconds=30),
                mutation_epoch=activation_epoch,
            )
            blocker = await engine.connect()
            blocker_transaction = await blocker.begin()
            await blocker.execute(
                text(
                    "SELECT fence_generation FROM memory_locator_profile_maintenance_fence "
                    "WHERE singleton = TRUE FOR UPDATE"
                )
            )
            activation_task = asyncio.create_task(
                registry.activate(
                    activation_lease,
                    activation_evidence,
                    now=now,
                    maximum_queue_lag=timedelta(minutes=5),
                    maximum_retained=10,
                )
            )
            await asyncio.sleep(0.05)
            activation_first_query = asyncio.create_task(
                restarted_registry.begin_profile_query(
                    "query-queued-after-activation",
                    owner=owner,
                    now=now,
                    expires_at=now + timedelta(seconds=5),
                )
            )
            await asyncio.sleep(0.05)
            assert not activation_task.done() and not activation_first_query.done()
            await blocker_transaction.commit()
            await blocker.close()
            await asyncio.wait_for(activation_task, timeout=5)
            admitted_after_activation = await asyncio.wait_for(
                activation_first_query, timeout=5
            )
            assert admitted_after_activation.status == "admitted"
            assert admitted_after_activation.identity == second
            await registry.finish_profile_query(
                second.profile_id,
                "query-queued-after-activation",
                owner=owner,
                activation_lease_id=admitted_after_activation.activation_lease_id or "",
            )
            await _activate(registry, first.profile_id, now, "lease-a-restore", 10)
            async with engine.begin() as connection:
                audits = int(
                    await connection.scalar(
                        text("SELECT count(*) FROM memory_locator_profile_transition_audit")
                    )
                    or 0
                )
                assert audits == 3
            async with engine.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(Exception, match="append-only"):
                    await connection.execute(
                        text("DELETE FROM memory_locator_profile_transition_audit")
                    )
                await transaction.rollback()
            with pytest.raises(RuntimeError, match="retrieval_profile_last_active_protected"):
                await registry.retire(first.profile_id, now=now, maximum_retained=1)
            with pytest.raises(RuntimeError, match="requires_attested_promotion"):
                await registry.rollback(second.profile_id, now=now, maximum_retained=10)
            await _activate(registry, second.profile_id, now, "lease-b-rollback", 10)

            third = RetrievalProfileIdentity("profile-c", "gen-c", "c" * 64, "collection-c")
            await registry.create_building(third, now=now)
            await registry.checkpoint_backfill(
                third.profile_id,
                previous_cursor=None,
                cursor=None,
                watermark=0,
                complete=True,
                now=now,
            )
            await registry.update_lane(
                third.profile_id,
                "qdrant_dense",
                required=True,
                healthy=True,
                profile_qualified=True,
                failure_code=None,
                checked_at=now,
            )
            retiring_writer_epoch = await registry.begin_provider_mutation(
                first.profile_id,
                "writer-crossing-retirement",
                owner=owner,
                now=now,
                expires_at=now + timedelta(seconds=1),
            )
            retired = await _activate(registry, third.profile_id, now, "lease-c", 1)
            assert retired == ("profile-a",)

            cleanup = await registry.cleanup("profile-a")
            assert cleanup.phase == "requested"
            assert (
                await registry.authorize_collection_delete(
                    "profile-a", now=now + timedelta(minutes=1)
                )
                is None
            )
            with pytest.raises(RuntimeError, match="provider_mutation_rejected"):
                await registry.begin_provider_mutation(
                    first.profile_id,
                    "stale-writer-after-retirement",
                    owner=owner,
                    now=now + timedelta(minutes=1),
                    expires_at=now + timedelta(minutes=2),
                )
            await registry.finish_provider_mutation(
                first.profile_id,
                "writer-crossing-retirement",
                owner=owner,
                started_epoch=retiring_writer_epoch,
                now=now + timedelta(minutes=1),
            )
            await registry.checkpoint_attestation(
                "profile-a",
                "retired-recovery-evidence",
                previous_cursor=None,
                cursor=None,
                item_count=1,
                digest_accumulator="d" * 64,
                started_at=now,
                deadline_at=now + timedelta(seconds=30),
                now=now,
                complete=False,
                scan_complete=True,
                page_receipt=ProfileAttestationPageReceipt(0, None, None, 1, 64, "e" * 64),
            )
            assert (
                await registry.attestation_checkpoint("profile-a", "retired-recovery-evidence")
                is not None
            )
            authorization = await registry.authorize_collection_delete("profile-a", now=now)
            assert authorization is not None
            # A crash before the provider acknowledgement leaves the durable phase
            # retryable. Recomposition reads the same state and can safely resume.
            restarted = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            assert (await restarted.cleanup("profile-a")).phase == "requested"
            replay_authorization = await restarted.authorize_collection_delete("profile-a", now=now)
            assert replay_authorization == authorization
            with pytest.raises(RuntimeError, match="cleanup_fence_drift"):
                await restarted.mark_collection_deleted(
                    ProfileCollectionDeleteAuthorization(
                        authorization.identity,
                        "different-delete-token",
                        authorization.provider_epoch,
                    ),
                    now=now,
                )
            await restarted.mark_collection_deleted(authorization, now=now)
            await restarted.cleanup_postgres("profile-a", now=now)
            assert (
                await restarted.attestation_checkpoint("profile-a", "retired-recovery-evidence")
                is None
            )
            async with engine.connect() as connection:
                assert (
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM "
                                "memory_locator_profile_reconciliation_operations "
                                "WHERE profile_id = 'profile-a'"
                            )
                        )
                    )
                    == 0
                )
                assert (
                    int(
                        await connection.scalar(
                            text(
                                "SELECT count(*) FROM memory_locator_profile_provider_mutations "
                                "WHERE profile_id = 'profile-a'"
                            )
                        )
                    )
                    == 0
                )
            await restarted.cleanup_postgres("profile-a", now=now)
            await restarted.complete_cleanup("profile-a", now=now)
            await restarted.complete_cleanup("profile-a", now=now)
            drift_operation = await restarted.reconciliation_operation("profile-c")
            await restarted.checkpoint_attestation(
                "profile-c",
                drift_operation.operation_id,
                previous_cursor=None,
                cursor=None,
                item_count=0,
                digest_accumulator="0" * 64,
                started_at=now,
                deadline_at=now + timedelta(seconds=30),
                now=now,
                complete=True,
                scan_complete=True,
            )
            await restarted.mark_reconciliation_drift(
                "profile-c", operation=drift_operation, now=now
            )
            after_drift = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            assert await after_drift.active_lease(now=now) is None
            assert await after_drift.reconciliation_operation("profile-c") != drift_operation
            assert (
                await after_drift.attestation_checkpoint("profile-c", drift_operation.operation_id)
                is not None
            )
            rejected_operation = await after_drift.reconciliation_operation("profile-c")
            rejected_evidence = await after_drift.activation_evidence("profile-c", now=now)
            await after_drift.record_reconciliation(
                "profile-c",
                rejected_evidence,
                operation=rejected_operation,
                runtime_owner=owner,
                now=now,
                expires_at=now + timedelta(seconds=30),
                drifted=True,
            )
            after_rejection = PostgresRetrievalProfileRegistry(build_session_factory(engine))
            assert await after_rejection.active_lease(now=now) is None
            assert await after_rejection.reconciliation_operation("profile-c") != rejected_operation
            async with engine.begin() as connection:
                states = tuple(
                    (
                        await connection.execute(
                            text(
                                "SELECT profile_id, state FROM memory_locator_profiles "
                                "ORDER BY profile_id"
                            )
                        )
                    ).all()
                )
                assert states == (
                    ("profile-a", "retired"),
                    ("profile-b", "retained"),
                    ("profile-c", "active"),
                )
                assert (
                    await connection.scalar(
                        text(
                            "SELECT phase FROM memory_locator_profile_cleanups "
                            "WHERE profile_id = 'profile-a'"
                        )
                    )
                    == "complete"
                )
                with pytest.raises(DBAPIError):
                    await connection.execute(
                        text(
                            "UPDATE memory_locator_profiles SET generation = 'drift' "
                            "WHERE profile_id = 'profile-b'"
                        )
                    )
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _activate(
    registry, profile_id: str, now: datetime, lease_id: str, maximum_retained: int
) -> tuple[str, ...]:
    evidence = await registry.activation_evidence(profile_id, now=now)
    mutation_epoch = await registry.provider_attestation_epoch(profile_id, now=now)
    lease = await registry.issue_activation_lease(
        profile_id,
        evidence,
        lease_id=lease_id,
        now=now,
        expires_at=now + timedelta(seconds=30),
        mutation_epoch=mutation_epoch,
    )
    exact = await registry.activation_evidence(profile_id, now=now)
    return await registry.activate(
        lease,
        exact,
        now=now,
        maximum_queue_lag=timedelta(minutes=5),
        maximum_retained=maximum_retained,
    )
