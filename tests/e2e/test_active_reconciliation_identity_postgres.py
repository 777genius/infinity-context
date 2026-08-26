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
    ProfileReconciliationWriteOutcome,
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
        await registry.register_runtime_incarnation(owner, now=now)
        competing = (
            replace(
                owner,
                instance_id="simultaneous-runtime",
                generation="generation-a",
                launch_token="unrecoverable-simultaneous-a",
            ),
            replace(
                owner,
                instance_id="simultaneous-runtime",
                generation="generation-b",
                launch_token="unrecoverable-simultaneous-b",
            ),
        )

        async def register(candidate):
            try:
                await PostgresRetrievalProfileRegistry(
                    build_session_factory(engine)
                ).register_runtime_incarnation(candidate, now=now)
                return candidate
            except RuntimeError as exc:
                return str(exc)

        competing_results = await asyncio.gather(*(register(item) for item in competing))
        winners = tuple(item for item in competing_results if isinstance(item, RuntimeFenceOwner))
        failures = tuple(item for item in competing_results if isinstance(item, str))
        assert len(winners) == 1
        assert failures == ("retrieval_profile_runtime_generation_competing",)
        await registry.retire_runtime_incarnation(winners[0], now=now)
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
        operation = await registry.reconciliation_operation(
            identity.profile_id, runtime_owner=owner
        )
        write_outcome = await registry.record_reconciliation(
            identity.profile_id,
            evidence,
            operation=operation,
            runtime_owner=owner,
            now=now + timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            drifted=False,
        )
        assert write_outcome is ProfileReconciliationWriteOutcome.APPLIED
        replay_outcome = await registry.record_reconciliation(
            identity.profile_id,
            evidence,
            operation=operation,
            runtime_owner=owner,
            now=now + timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            drifted=False,
        )
        assert replay_outcome is ProfileReconciliationWriteOutcome.IDEMPOTENT_REPLAY

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
        async with engine.connect() as connection:
            assert (
                int(
                    await connection.scalar(
                        text(
                            "SELECT count(*) FROM memory_locator_profile_transition_audit "
                            "WHERE lease_id=:lease_id"
                        ),
                        {"lease_id": operation.operation_id},
                    )
                    or 0
                )
                == 1
            )
        renewed = await registry.active_lease(now=now + timedelta(seconds=2))
        assert renewed is not None
        rejected_expiry = renewed.expires_at

        await registry.verify_registered_runtime_owner(owner)
        unchanged = await _lifecycle_state(engine)

        missing = replace(
            owner,
            instance_id="reconciliation-identity-missing",
            generation="generation-missing",
            launch_token="unrecoverable-launch-missing",
        )
        stale_generation = replace(
            owner,
            generation="generation-stale",
            launch_token="unrecoverable-launch-stale-generation",
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
        stale_lifecycle = replace(owner, supervisor_key_id="test-unrecoverable-stale")
        reused_launch = replace(
            owner,
            instance_id="reconciliation-identity-reused",
            generation="generation-reused",
        )
        rejected = (
            (missing, "runtime_incarnation_missing"),
            (stale_generation, "runtime_generation_mismatch"),
            (stale_release, "runtime_release_identity_mismatch"),
            (stale_lifecycle, "runtime_lifecycle_identity_mismatch"),
            (reused_launch, "runtime_launch_token_reused"),
        )
        for candidate, reason in rejected:
            with pytest.raises(RuntimeError, match=reason):
                await registry.verify_registered_runtime_owner(candidate)
            assert await _lifecycle_state(engine) == unchanged

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
        drift_operation = await registry.reconciliation_operation(
            identity.profile_id, runtime_owner=owner
        )
        before_stale_drift = await _lifecycle_state(engine)
        with pytest.raises(RuntimeError, match="runtime_generation_mismatch"):
            await registry.mark_reconciliation_drift(
                identity.profile_id,
                operation=drift_operation,
                runtime_owner=stale_generation,
                now=now + timedelta(seconds=2),
            )
        assert await _lifecycle_state(engine) == before_stale_drift

        with pytest.raises(RuntimeError, match="runtime_generation_mismatch"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=stale_generation,
                now=now + timedelta(seconds=2),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
        with pytest.raises(RuntimeError, match="runtime_release_identity_mismatch"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=stale_release,
                now=now + timedelta(seconds=2),
                expires_at=now + timedelta(minutes=10),
                drifted=False,
            )
        for replay_now, replay_expiry in (
            (now + timedelta(seconds=2), now + timedelta(minutes=5)),
            (now + timedelta(seconds=1), now + timedelta(minutes=10)),
        ):
            replay = await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=operation,
                runtime_owner=owner,
                now=replay_now,
                expires_at=replay_expiry,
                drifted=False,
            )
            assert replay is ProfileReconciliationWriteOutcome.IDEMPOTENT_REPLAY
        conflict = await registry.record_reconciliation(
            identity.profile_id,
            evidence,
            operation=operation,
            runtime_owner=owner,
            now=now + timedelta(seconds=1),
            expires_at=now + timedelta(minutes=5),
            drifted=False,
            mutation_epoch=1,
        )
        assert conflict is ProfileReconciliationWriteOutcome.CONFLICT
        after_rejections = await registry.active_lease(now=now + timedelta(seconds=2))
        assert after_rejections is not None
        assert after_rejections.expires_at == rejected_expiry

        restarted_owner = replace(
            owner,
            generation="generation-restarted",
            launch_token="unrecoverable-launch-restarted",
        )
        before_competing_registration = await _lifecycle_state(engine)
        with pytest.raises(RuntimeError, match="runtime_generation_competing"):
            await registry.register_runtime_incarnation(
                restarted_owner, now=now + timedelta(seconds=3)
            )
        assert await _lifecycle_state(engine) == before_competing_registration
        await registry.retire_runtime_incarnation(owner, now=now + timedelta(seconds=3))
        await registry.register_runtime_incarnation(restarted_owner, now=now + timedelta(seconds=3))
        await registry.verify_registered_runtime_owner(restarted_owner)
        before_retired_owner_writes = await _lifecycle_state(engine)
        with pytest.raises(RuntimeError, match="runtime_incarnation_retired"):
            await registry.coverage(
                identity.profile_id,
                reconciliation_operation=drift_operation,
                runtime_owner=owner,
            )
        with pytest.raises(RuntimeError, match="runtime_incarnation_retired"):
            await registry.update_lane(
                identity.profile_id,
                "qdrant_dense",
                required=True,
                healthy=False,
                profile_qualified=False,
                failure_code="retired-owner-must-not-write",
                checked_at=now + timedelta(seconds=3),
                reconciliation_operation=drift_operation,
                runtime_owner=owner,
            )
        with pytest.raises(RuntimeError, match="runtime_incarnation_retired"):
            await registry.checkpoint_attestation(
                identity.profile_id,
                "retired-owner-checkpoint",
                previous_cursor=None,
                cursor=None,
                item_count=0,
                digest_accumulator="0" * 64,
                started_at=now,
                deadline_at=now + timedelta(seconds=30),
                now=now + timedelta(seconds=3),
                complete=False,
                owner_operation_id=drift_operation.operation_id,
                reconciliation_operation=drift_operation,
                runtime_owner=owner,
            )
        with pytest.raises(RuntimeError, match="operation_owner_mismatch"):
            await registry.record_reconciliation(
                identity.profile_id,
                evidence,
                operation=drift_operation,
                runtime_owner=restarted_owner,
                now=now + timedelta(seconds=3),
                expires_at=now + timedelta(minutes=6),
                drifted=False,
            )
        assert await _lifecycle_state(engine) == before_retired_owner_writes
        restart_operation = await registry.reconciliation_operation(
            identity.profile_id, runtime_owner=restarted_owner
        )
        restart_evidence = await registry.activation_evidence(identity.profile_id, now=now)
        await registry.record_reconciliation(
            identity.profile_id,
            restart_evidence,
            operation=restart_operation,
            runtime_owner=restarted_owner,
            now=now + timedelta(seconds=3),
            expires_at=now + timedelta(minutes=6),
            drifted=False,
        )
        restarted_lease = await registry.active_lease(now=now + timedelta(seconds=4))
        assert restarted_lease is not None
        assert restarted_lease.lease_id == restart_operation.operation_id
    finally:
        await engine.dispose()
        await database.drop()


async def _lifecycle_state(engine) -> tuple[tuple[object, ...], ...]:
    statements = (
        "SELECT profile_id, generation, reconciled_at, reconciliation_drifted, "
        "activation_lease_id, activation_lease_issued_at, activation_lease_expires_at, "
        "activation_evidence_version, activation_mutation_epoch "
        "FROM memory_locator_profiles ORDER BY profile_id",
        "SELECT profile_id, lane_id, healthy, profile_qualified, failure_code, checked_at, "
        "observed_count, observed_digest FROM memory_locator_profile_lanes "
        "ORDER BY profile_id, lane_id",
        "SELECT profile_id, operation_id, cursor, item_count, digest_accumulator, complete "
        "FROM memory_locator_profile_attestation_checkpoints ORDER BY profile_id, operation_id",
        "SELECT profile_id, operation_id, page_number, page_digest "
        "FROM memory_locator_profile_attestation_pages "
        "ORDER BY profile_id, operation_id, page_number",
        "SELECT profile_id, operation_id, predecessor_lease_id, predecessor_generation, "
        "runtime_instance_id, runtime_generation, lifecycle_identity_sha256, created_at "
        "FROM memory_locator_profile_reconciliation_operations "
        "ORDER BY profile_id, operation_id",
        "SELECT profile_id, lease_id, runtime_instance_id, runtime_generation, "
        "lifecycle_identity_sha256, occurred_at "
        "FROM memory_locator_profile_transition_audit ORDER BY lease_id",
        "SELECT instance_id, generation, last_seen_at, launch_token, "
        "release_identity_sha256, launch_identity_sha256, sealed_dead_generation, retired_at "
        "FROM memory_locator_runtime_incarnations ORDER BY instance_id, generation",
    )
    async with engine.connect() as connection:
        state = []
        for statement in statements:
            rows = (await connection.execute(text(statement))).all()
            state.append(tuple(tuple(row) for row in rows))
        return tuple(state)
