"""Durable active-profile lease reconciliation and evidence retention."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from infinity_context_core.features.context_building.public import (
    ProfileActivationEvidence,
    ProfileAttestationLease,
    ProfileLaneHealth,
    ProfileQueryAdmission,
    ProfileQueryAdmissionStatus,
    ProfileQueueHealth,
    ProfileReconciliationOperation,
    ProfileTombstoneHealth,
    RuntimeFenceOwner,
)
from sqlalchemy import func, select, text

from infinity_context_adapters.postgres.locator_profile_attestation_retention import (
    compact_reconciliation_evidence,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    ROUTABLE_PROFILE_STATES,
    profile_coverage,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    profile_identity as _identity,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileLaneRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileQueryRow,
    MemoryLocatorProfileReconciliationOperationRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProfileTombstoneRow,
    MemoryLocatorProfileTransitionAuditRow,
    MemoryLocatorRuntimeIncarnationRow,
    MemoryOutboxRow,
)


class PostgresRetrievalProfileReconciliationMixin:
    async def register_runtime_incarnation(
        self, owner: RuntimeFenceOwner, *, now: datetime
    ) -> None:
        """Persist one verified launcher identity without opening a provider fence."""

        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            await _register_runtime(
                session, owner, now=now, supervisor_trust=self.supervisor_trust
            )

    async def begin_profile_query(
        self,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        now: datetime,
        expires_at: datetime,
    ) -> ProfileQueryAdmission:
        """Atomically distinguish no registry, exact admission, and unavailable."""

        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            await _register_runtime(
                session, owner, now=now, supervisor_trust=self.supervisor_trust
            )
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileRow)
                        .where(MemoryLocatorProfileRow.state.in_(ROUTABLE_PROFILE_STATES))
                        .order_by(MemoryLocatorProfileRow.profile_id)
                        .with_for_update()
                    )
                ).scalars()
            )
            if not rows:
                return ProfileQueryAdmission(ProfileQueryAdmissionStatus.NO_PROFILE)
            row = next((item for item in rows if item.state == "active"), None)
            database_now = await session.scalar(select(func.clock_timestamp()))
            if row is None or not isinstance(database_now, datetime):
                return ProfileQueryAdmission(ProfileQueryAdmissionStatus.UNAVAILABLE)
            if (
                row.reconciliation_drifted
                or row.activation_lease_id is None
                or row.activation_lease_expires_at is None
                or row.activation_evidence_version <= 0
                or database_now >= row.activation_lease_expires_at
                or expires_at <= now
            ):
                return ProfileQueryAdmission(ProfileQueryAdmissionStatus.UNAVAILABLE)
            active_mutations = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == row.profile_id)
                )
                or 0
            )
            if active_mutations or row.activation_mutation_epoch != row.provider_mutation_epoch:
                return ProfileQueryAdmission(ProfileQueryAdmissionStatus.UNAVAILABLE)
            existing = await session.get(
                MemoryLocatorProfileQueryRow, (row.profile_id, operation_id)
            )
            if existing is not None:
                if (
                    existing.activation_lease_id != row.activation_lease_id
                    or existing.owner_instance_id != owner.instance_id
                    or existing.owner_generation != owner.generation
                ):
                    raise RuntimeError("retrieval_profile_query_lease_invalid")
                return ProfileQueryAdmission(
                    ProfileQueryAdmissionStatus.ADMITTED,
                    _identity(row),
                    existing.activation_lease_id,
                )
            session.add(
                MemoryLocatorProfileQueryRow(
                    profile_id=row.profile_id,
                    operation_id=operation_id,
                    owner_instance_id=owner.instance_id,
                    owner_generation=owner.generation,
                    activation_lease_id=row.activation_lease_id,
                    started_at=now,
                    expires_at=expires_at,
                )
            )
            return ProfileQueryAdmission(
                ProfileQueryAdmissionStatus.ADMITTED,
                _identity(row),
                row.activation_lease_id,
            )

    async def finish_profile_query(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        activation_lease_id: str,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            row = await session.get(
                MemoryLocatorProfileQueryRow,
                (profile_id, operation_id),
                with_for_update=True,
            )
            if (
                row is None
                or row.activation_lease_id != activation_lease_id
                or row.owner_instance_id != owner.instance_id
                or row.owner_generation != owner.generation
            ):
                raise RuntimeError("retrieval_profile_query_fenced")
            await session.delete(row)

    async def active_lease(self, *, now: datetime) -> ProfileAttestationLease | None:
        del now
        async with self.sessions() as session:
            maintenance = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True)
            if maintenance is None or maintenance.active:
                return None
            row = (
                await session.execute(
                    select(MemoryLocatorProfileRow).where(MemoryLocatorProfileRow.state == "active")
                )
            ).scalar_one_or_none()
            database_now = await session.scalar(select(func.clock_timestamp()))
            if (
                row is None
                or not isinstance(database_now, datetime)
                or row.reconciliation_drifted
                or row.activation_lease_id is None
                or row.activation_lease_expires_at is None
                or database_now >= row.activation_lease_expires_at
            ):
                return None
            return ProfileAttestationLease(
                row.activation_lease_id,
                row.profile_id,
                row.generation,
                row.activation_evidence_digest,
                row.activation_lease_issued_at,
                row.activation_lease_expires_at,
                int(row.activation_evidence_version),
                int(row.activation_mutation_epoch),
            )

    async def consumed_transition_profile(self, lease_id: str) -> str | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(MemoryLocatorProfileTransitionAuditRow.profile_id).where(
                    MemoryLocatorProfileTransitionAuditRow.lease_id == lease_id
                )
            )

    async def record_reconciliation(
        self,
        profile_id: str,
        evidence: ProfileActivationEvidence,
        *,
        operation: ProfileReconciliationOperation,
        runtime_owner: RuntimeFenceOwner | None,
        now: datetime,
        expires_at: datetime,
        drifted: bool,
        mutation_epoch: int = 0,
    ) -> None:
        if not isinstance(runtime_owner, RuntimeFenceOwner):
            raise RuntimeError("retrieval_profile_reconciliation_runtime_identity_missing")
        lifecycle_digest = runtime_owner.lifecycle_identity_sha256()
        raced = False
        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            evidence_version = await _lock_profile_evidence(session)
            await _register_runtime(
                session,
                runtime_owner,
                now=now,
                supervisor_trust=self.supervisor_trust,
            )
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None or row.state != "active":
                raise RuntimeError("retrieval_profile_active_missing")
            persisted = await session.get(
                MemoryLocatorProfileReconciliationOperationRow,
                (profile_id, operation.operation_id),
            )
            if persisted is None or _operation(persisted) != operation:
                raise RuntimeError("retrieval_profile_reconciliation_operation_invalid")
            if row.activation_lease_id == operation.operation_id:
                audit = await _reconciliation_audit(session, operation.operation_id)
                if (
                    row.generation != operation.predecessor_generation
                    or row.activation_evidence_digest != evidence.digest()
                    or row.reconciliation_drifted != drifted
                    or not _audit_matches_owner(
                        audit,
                        runtime_owner,
                        evidence_digest=evidence.digest(),
                        lifecycle_digest=lifecycle_digest,
                    )
                ):
                    raise RuntimeError("retrieval_profile_reconciliation_replay_drift")
                return
            if not _matches_predecessor(row, operation):
                raise RuntimeError("retrieval_profile_reconciliation_superseded")
            if not drifted:
                active_mutations = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(MemoryLocatorProfileProviderMutationRow)
                        .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                    )
                    or 0
                )
                if active_mutations or row.provider_mutation_epoch != mutation_epoch:
                    raise RuntimeError("retrieval_profile_reconciliation_raced")
                current = await _reconciliation_evidence(self, session, row, now=now)
                raced = current.digest() != evidence.digest()
            row.reconciled_at = now
            row.reconciliation_drifted = drifted or raced
            row.activation_lease_id = operation.operation_id
            if drifted or raced:
                # Preserve a durable, constraint-valid expired lease.  Keeping the
                # failed operation id rotates the next reconciliation identity,
                # while expiry at ``now`` makes routing fail closed immediately.
                row.activation_lease_issued_at = now - timedelta(microseconds=1)
                row.activation_lease_expires_at = now
            else:
                row.activation_evidence_digest = evidence.digest()
                row.activation_lease_issued_at = now
                row.activation_lease_expires_at = expires_at
                row.activation_evidence_version = evidence_version
                row.activation_mutation_epoch = mutation_epoch
            session.add(
                MemoryLocatorProfileTransitionAuditRow(
                    profile_id=profile_id,
                    previous_active_profile_id=None,
                    lease_id=operation.operation_id,
                    evidence_digest=evidence.digest(),
                    runtime_instance_id=runtime_owner.instance_id,
                    runtime_generation=runtime_owner.generation,
                    lifecycle_identity_sha256=lifecycle_digest,
                    occurred_at=now,
                )
            )
            await compact_reconciliation_evidence(
                session, profile_id=profile_id, operation_id=operation.operation_id
            )
        if raced:
            raise RuntimeError("retrieval_profile_reconciliation_raced")

    async def reconciliation_operation(self, profile_id: str) -> ProfileReconciliationOperation:
        """Persist the exact predecessor compared by reconciliation completion."""

        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None or row.state != "active":
                raise RuntimeError("retrieval_profile_active_missing")
            seed = row.activation_lease_id or "initial"
            digest = hashlib.sha256(
                (
                    f"reconcile.v3\0{row.profile_id}\0{row.generation}\0{seed}\0"
                    f"{row.activation_evidence_digest or ''}\0"
                    f"{row.activation_lease_issued_at!s}\0{row.activation_lease_expires_at!s}\0"
                    f"{int(row.reconciliation_drifted)}"
                ).encode()
            ).hexdigest()
            operation = ProfileReconciliationOperation(
                f"reconcile-{digest}",
                row.profile_id,
                row.activation_lease_id,
                row.generation,
                row.activation_evidence_digest,
                row.activation_lease_issued_at,
                row.activation_lease_expires_at,
                row.reconciliation_drifted,
            )
            existing = await session.get(
                MemoryLocatorProfileReconciliationOperationRow,
                (profile_id, operation.operation_id),
            )
            if existing is None:
                session.add(
                    MemoryLocatorProfileReconciliationOperationRow(
                        profile_id=profile_id,
                        operation_id=operation.operation_id,
                        predecessor_lease_id=operation.predecessor_lease_id,
                        predecessor_generation=operation.predecessor_generation,
                        predecessor_evidence_digest=operation.predecessor_evidence_digest,
                        predecessor_lease_issued_at=operation.predecessor_lease_issued_at,
                        predecessor_lease_expires_at=operation.predecessor_lease_expires_at,
                        predecessor_drifted=operation.predecessor_drifted,
                        created_at=row.reconciled_at or row.created_at,
                    )
                )
            elif _operation(existing) != operation:
                raise RuntimeError("retrieval_profile_reconciliation_operation_drift")
            return operation

    async def mark_reconciliation_drift(
        self, profile_id: str, *, operation: ProfileReconciliationOperation, now: datetime
    ) -> None:
        """Fail closed and rotate evidence identity after a physical read failure."""

        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None or row.state != "active":
                raise RuntimeError("retrieval_profile_active_missing")
            persisted = await session.get(
                MemoryLocatorProfileReconciliationOperationRow,
                (profile_id, operation.operation_id),
            )
            if persisted is None or _operation(persisted) != operation:
                raise RuntimeError("retrieval_profile_reconciliation_operation_invalid")
            if row.activation_lease_id == operation.operation_id:
                return
            if not _matches_predecessor(row, operation):
                raise RuntimeError("retrieval_profile_reconciliation_superseded")
            row.reconciled_at = now
            row.reconciliation_drifted = True
            row.activation_lease_id = operation.operation_id
            row.activation_lease_issued_at = now - timedelta(microseconds=1)
            row.activation_lease_expires_at = now
            await compact_reconciliation_evidence(
                session, profile_id=profile_id, operation_id=operation.operation_id
            )

    async def provider_attestation_epoch(self, profile_id: str, *, now: datetime) -> int:
        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None:
                raise RuntimeError("retrieval_profile_missing")
            active = await session.scalar(
                select(func.count())
                .select_from(MemoryLocatorProfileProviderMutationRow)
                .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
            )
            if active:
                raise RuntimeError("retrieval_profile_provider_mutation_active")
            return int(row.provider_mutation_epoch)

    async def begin_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        now: datetime,
        expires_at: datetime,
    ) -> int:
        async with self.sessions() as session, session.begin():
            await _lock_admission(session)
            await _lock_profile_evidence(session)
            await _register_runtime(
                session, owner, now=now, supervisor_trust=self.supervisor_trust
            )
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None:
                raise RuntimeError("retrieval_profile_missing")
            if row.state not in ("building", "active", "retained"):
                raise RuntimeError("retrieval_profile_provider_mutation_rejected")
            active_queries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileQueryRow)
                    .where(MemoryLocatorProfileQueryRow.profile_id == profile_id)
                )
                or 0
            )
            if active_queries:
                raise RuntimeError("retrieval_profile_provider_mutation_reader_active")
            existing = await session.get(
                MemoryLocatorProfileProviderMutationRow, (profile_id, operation_id)
            )
            if existing is not None:
                if (
                    existing.owner_instance_id != owner.instance_id
                    or existing.owner_generation != owner.generation
                ):
                    raise RuntimeError("retrieval_profile_provider_mutation_fenced")
                if existing.expires_at <= now:
                    raise RuntimeError("retrieval_profile_provider_mutation_stale")
                return int(existing.started_epoch)
            row.provider_mutation_epoch += 1
            if row.state == "active":
                row.reconciliation_drifted = True
                if row.activation_lease_issued_at is not None:
                    row.activation_lease_expires_at = max(
                        now, row.activation_lease_issued_at + timedelta(microseconds=1)
                    )
            session.add(
                MemoryLocatorProfileProviderMutationRow(
                    profile_id=profile_id,
                    operation_id=operation_id,
                    owner_instance_id=owner.instance_id,
                    owner_generation=owner.generation,
                    started_epoch=row.provider_mutation_epoch,
                    started_at=now,
                    expires_at=expires_at,
                )
            )
            return int(row.provider_mutation_epoch)

    async def heartbeat_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        started_epoch: int,
        now: datetime,
        expires_at: datetime,
    ) -> None:
        """Renew one exact live writer without ever permitting lease stealing.

        An elapsed heartbeat is diagnostic evidence, not authority to erase the
        durable fence.  Only the exact writer may close its row after a successful
        bounded provider call.
        """

        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            mutation = await session.get(
                MemoryLocatorProfileProviderMutationRow,
                (profile_id, operation_id),
                with_for_update=True,
            )
            if (
                row is None
                or mutation is None
                or mutation.started_epoch != started_epoch
                or mutation.owner_instance_id != owner.instance_id
                or mutation.owner_generation != owner.generation
            ):
                raise RuntimeError("retrieval_profile_provider_mutation_fenced")
            if expires_at <= now:
                raise RuntimeError("retrieval_profile_provider_mutation_heartbeat_invalid")
            mutation.expires_at = expires_at

    async def finish_provider_mutation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        owner: RuntimeFenceOwner,
        started_epoch: int | None = None,
        now: datetime,
    ) -> int:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None:
                raise RuntimeError("retrieval_profile_missing")
            mutation = await session.get(
                MemoryLocatorProfileProviderMutationRow,
                (profile_id, operation_id),
                with_for_update=True,
            )
            if mutation is None:
                raise RuntimeError("retrieval_profile_provider_mutation_fenced")
            if (
                started_epoch is None
                or mutation.started_epoch != started_epoch
                or mutation.owner_instance_id != owner.instance_id
                or mutation.owner_generation != owner.generation
            ):
                raise RuntimeError("retrieval_profile_provider_mutation_fenced")
            await session.delete(mutation)
            row.provider_mutation_epoch += 1
            return int(row.provider_mutation_epoch)


def _operation(row) -> ProfileReconciliationOperation:
    return ProfileReconciliationOperation(
        row.operation_id,
        row.profile_id,
        row.predecessor_lease_id,
        row.predecessor_generation,
        row.predecessor_evidence_digest,
        row.predecessor_lease_issued_at,
        row.predecessor_lease_expires_at,
        row.predecessor_drifted,
    )


def _matches_predecessor(row, operation: ProfileReconciliationOperation) -> bool:
    return (
        row.profile_id == operation.profile_id
        and row.activation_lease_id == operation.predecessor_lease_id
        and row.generation == operation.predecessor_generation
        and row.activation_evidence_digest == operation.predecessor_evidence_digest
        and row.activation_lease_issued_at == operation.predecessor_lease_issued_at
        and row.activation_lease_expires_at == operation.predecessor_lease_expires_at
        and row.reconciliation_drifted == operation.predecessor_drifted
    )


async def _reconciliation_evidence(owner, session, row, *, now: datetime):
    await owner._refresh_attestation(session, row)
    lanes = tuple(
        ProfileLaneHealth(
            item.lane_id,
            item.required,
            item.healthy,
            item.profile_qualified,
            int(item.observed_count),
            item.observed_digest,
        )
        for item in (
            await session.execute(
                select(MemoryLocatorProfileLaneRow)
                .where(MemoryLocatorProfileLaneRow.profile_id == row.profile_id)
                .order_by(MemoryLocatorProfileLaneRow.lane_id)
            )
        ).scalars()
    )
    routable_ids = tuple(
        (
            await session.execute(
                select(MemoryLocatorProfileRow.profile_id).where(
                    MemoryLocatorProfileRow.state.in_(ROUTABLE_PROFILE_STATES)
                )
            )
        ).scalars()
    )
    queue = (
        await session.execute(
            select(
                func.coalesce(func.sum(MemoryOutboxRow.attempt_count), 0),
                func.count().filter(MemoryOutboxRow.status == "dead"),
                func.min(MemoryOutboxRow.created_at).filter(MemoryOutboxRow.status != "dead"),
            ).where(
                MemoryOutboxRow.fairness_key.in_(
                    tuple(f"profile:{value}" for value in routable_ids)
                ),
                MemoryOutboxRow.status.in_(("pending", "retry_pending", "running", "dead")),
            )
        )
    ).one()
    tombstones = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(MemoryLocatorProfileTombstoneRow.completed_at.is_not(None)),
            )
            .select_from(MemoryLocatorProfileTombstoneRow)
            .join(
                MemoryLocatorProfileRow,
                MemoryLocatorProfileRow.profile_id == MemoryLocatorProfileTombstoneRow.profile_id,
            )
            .where(MemoryLocatorProfileRow.state.in_(("active", "retained")))
        )
    ).one()
    return ProfileActivationEvidence(
        coverage=profile_coverage(row),
        queue=ProfileQueueHealth(int(queue[0]), int(queue[1]), queue[2], now),
        lanes=lanes,
        tombstones=ProfileTombstoneHealth(int(tombstones[0]), int(tombstones[1])),
    )


async def _lock_profile_evidence(session) -> int:
    value = await session.scalar(
        text(
            "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
            "WHERE singleton = TRUE FOR UPDATE"
        )
    )
    if value is None:
        raise RuntimeError("retrieval_profile_evidence_version_missing")
    return int(value)


async def _lock_maintenance(session) -> None:
    row = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True)
    if row is None:
        raise RuntimeError("retrieval_profile_maintenance_fence_missing")


async def _reconciliation_audit(session, lease_id: str):
    return (
        await session.execute(
            select(MemoryLocatorProfileTransitionAuditRow).where(
                MemoryLocatorProfileTransitionAuditRow.lease_id == lease_id
            )
        )
    ).scalar_one_or_none()


def _audit_matches_owner(
    audit,
    owner: RuntimeFenceOwner,
    *,
    evidence_digest: str,
    lifecycle_digest: str,
) -> bool:
    return bool(
        audit is not None
        and audit.runtime_instance_id == owner.instance_id
        and audit.runtime_generation == owner.generation
        and audit.evidence_digest == evidence_digest
        and audit.lifecycle_identity_sha256 == lifecycle_digest
    )


async def _lock_admission(session) -> None:
    await _lock_maintenance(session)
    row = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True)
    if row.active:
        raise RuntimeError("retrieval_profile_maintenance_active")


async def _register_runtime(
    session, owner: RuntimeFenceOwner, *, now: datetime, supervisor_trust
) -> None:
    import hashlib

    owner.assert_current_process()
    unrecoverable = owner.supervisor_public_key == "0" * 64
    if unrecoverable:
        if (
            owner.launch_signature
            or "unrecoverable" not in owner.supervisor_key_id
            or owner.trust_root_sha256 != "0" * 64
            or owner.trust_registry_generation != 0
        ):
            raise RuntimeError("retrieval_profile_runtime_launch_invalid")
    else:
        if supervisor_trust is None:
            raise RuntimeError("retrieval_profile_supervisor_trust_required")
        supervisor_trust.verify_launch(owner, now=now)
    launch_digest = hashlib.sha256(owner.launch_payload()).hexdigest()
    row = await session.get(
        MemoryLocatorRuntimeIncarnationRow,
        (owner.instance_id, owner.generation),
        with_for_update=True,
    )
    if row is None:
        launch_owner = (
            await session.execute(
                select(MemoryLocatorRuntimeIncarnationRow).where(
                    MemoryLocatorRuntimeIncarnationRow.launch_token == owner.launch_token
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if launch_owner is not None:
            raise RuntimeError("retrieval_profile_runtime_supervisor_conflict")
        session.add(
            MemoryLocatorRuntimeIncarnationRow(
                instance_id=owner.instance_id,
                generation=owner.generation,
                registered_at=now,
                last_seen_at=now,
                acknowledged_generation=0,
                supervisor_key_id=owner.supervisor_key_id,
                supervisor_public_key=owner.supervisor_public_key,
                trust_root_sha256=owner.trust_root_sha256,
                trust_registry_generation=owner.trust_registry_generation,
                launch_token=owner.launch_token,
                process_pid=owner.process_pid,
                process_birth_identity=owner.process_birth_identity,
                executable_identity=owner.executable_identity,
                executable_sha256=owner.executable_sha256,
                release_revision=owner.installed_release.service_revision,
                release_source_tree_sha256=(
                    owner.installed_release.source_tree_digest_sha256
                ),
                release_installed_distribution_sha256=(
                    owner.installed_release.installed_distribution_digest_sha256
                ),
                release_runtime_modules_sha256=(
                    owner.installed_release.runtime_modules_digest_sha256
                ),
                release_identity_sha256=owner.installed_release.digest(),
                launch_identity_sha256=launch_digest,
            )
        )
        return
    if (
        row.supervisor_key_id != owner.supervisor_key_id
        or row.supervisor_public_key != owner.supervisor_public_key
        or row.trust_root_sha256 != owner.trust_root_sha256
        or row.trust_registry_generation != owner.trust_registry_generation
        or row.launch_token != owner.launch_token
        or row.process_pid != owner.process_pid
        or row.process_birth_identity != owner.process_birth_identity
        or row.executable_identity != owner.executable_identity
        or row.executable_sha256 != owner.executable_sha256
        or row.release_revision != owner.installed_release.service_revision
        or row.release_source_tree_sha256 != owner.installed_release.source_tree_digest_sha256
        or row.release_installed_distribution_sha256
        != owner.installed_release.installed_distribution_digest_sha256
        or row.release_runtime_modules_sha256
        != owner.installed_release.runtime_modules_digest_sha256
        or row.release_identity_sha256 != owner.installed_release.digest()
        or row.launch_identity_sha256 != launch_digest
    ):
        raise RuntimeError("retrieval_profile_runtime_supervisor_conflict")
    if row.sealed_dead_generation is not None:
        raise RuntimeError("retrieval_profile_runtime_incarnation_sealed_dead")
    row.last_seen_at = now


__all__ = ("PostgresRetrievalProfileReconciliationMixin",)
