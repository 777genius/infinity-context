"""Postgres canonical registry, rebuild source and attestation for Retrieval profiles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    CanonicalProjectionPage,
    ProfileActivationEvidence,
    ProfileAttestationLease,
    ProfileCoverageAttestation,
    ProfileLaneHealth,
    ProfileQueueHealth,
    ProfileTombstoneDeleteAuthorization,
    ProfileTombstoneHealth,
    RetrievalProfileIdentity,
    RuntimeFenceOwner,
    accumulate_attestation_digest,
    finalize_attestation_digest,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.postgres.locator_profile_attestation_checkpoints import (
    PostgresRetrievalProfileAttestationCheckpointMixin,
)
from infinity_context_adapters.postgres.locator_profile_cleanup import (
    PostgresRetrievalProfileCleanupMixin,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    ROUTABLE_PROFILE_STATES as _ROUTABLE_STATES,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    eligible_conditions as _eligible_conditions,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    eligible_value as _eligible_value,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    profile_coverage as _coverage,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    profile_identity as _identity,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    projection_item as _projection_item,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    require_building as _require_building,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    require_promotable as _require_promotable,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    require_routable as _require_routable,
)
from infinity_context_adapters.postgres.locator_profile_operator_receipts import (
    PostgresRetrievalProfileOperatorReceiptMixin,
)
from infinity_context_adapters.postgres.locator_profile_reconciliation import (
    PostgresRetrievalProfileReconciliationMixin,
)
from infinity_context_adapters.postgres.locator_profile_recovery import (
    PostgresRetrievalProfileRecoveryMixin,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryLocatorProfileLaneRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileQueryRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProfileTombstoneRow,
    MemoryLocatorProfileTransitionAuditRow,
    MemoryOutboxRow,
)
from infinity_context_adapters.postgres.supervisor_trust import SupervisorTrustRegistry

_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class PostgresCanonicalProjectionSource:
    sessions: async_sessionmaker[AsyncSession]

    async def page_eligible(self, *, after: str | None, limit: int) -> CanonicalProjectionPage:
        if not 1 <= limit <= 1000:
            raise ValueError("retrieval profile page limit must be within 1..1000")
        async with self.sessions() as session:
            watermark = int(
                await session.scalar(select(func.max(MemoryChunkRow.retrieval_commit_watermark)))
                or 0
            )
            conditions = list(_eligible_conditions())
            if after is not None:
                conditions.append(MemoryChunkRow.id > after)
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryChunkRow)
                        .where(*conditions)
                        .order_by(MemoryChunkRow.id)
                        .limit(limit + 1)
                    )
                ).scalars()
            )
        selected = rows[:limit]
        next_cursor = str(selected[-1].id) if len(rows) > limit else None
        return CanonicalProjectionPage(
            items=tuple(_projection_item(row) for row in selected),
            next_cursor=next_cursor,
            canonical_watermark=watermark,
        )

    async def items_by_ids(
        self, canonical_ids: tuple[str, ...]
    ) -> tuple[CanonicalProjectionItem, ...]:
        if not canonical_ids:
            return ()
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(MemoryChunkRow)
                    .where(MemoryChunkRow.id.in_(canonical_ids), *_eligible_conditions())
                    .order_by(MemoryChunkRow.id)
                )
            ).scalars()
            return tuple(_projection_item(row) for row in rows)


@dataclass(frozen=True, slots=True)
class PostgresRetrievalProfileRegistry(
    PostgresRetrievalProfileOperatorReceiptMixin,
    PostgresRetrievalProfileRecoveryMixin,
    PostgresRetrievalProfileReconciliationMixin,
    PostgresRetrievalProfileAttestationCheckpointMixin,
    PostgresRetrievalProfileCleanupMixin,
):
    sessions: async_sessionmaker[AsyncSession]
    supervisor_trust: SupervisorTrustRegistry | None = None

    async def create_building(self, identity: RetrievalProfileIdentity, *, now: datetime) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            existing = await session.get(
                MemoryLocatorProfileRow, identity.profile_id, with_for_update=True
            )
            if existing is not None:
                if _identity(existing) == identity:
                    return
                raise RuntimeError("retrieval_profile_idempotency_conflict")
            building = await session.scalar(
                select(MemoryLocatorProfileRow.profile_id)
                .where(MemoryLocatorProfileRow.state == "building")
                .with_for_update()
            )
            if building is not None:
                raise RuntimeError("retrieval_profile_building_exists")
            session.add(
                MemoryLocatorProfileRow(
                    profile_id=identity.profile_id,
                    generation=identity.generation,
                    profile_digest=identity.profile_digest,
                    collection_name=identity.collection_name,
                    state="building",
                    backfill_cursor=None,
                    backfill_complete=False,
                    canonical_watermark=0,
                    projected_watermark=0,
                    expected_count=0,
                    projected_count=0,
                    expected_digest=_EMPTY_DIGEST,
                    projected_digest=_EMPTY_DIGEST,
                    created_at=now,
                    backfill_updated_at=None,
                    activated_at=None,
                    retained_at=None,
                    retired_at=None,
                )
            )

    async def building(self) -> RetrievalProfileIdentity | None:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(MemoryLocatorProfileRow).where(
                        MemoryLocatorProfileRow.state == "building"
                    )
                )
            ).scalar_one_or_none()
        return _identity(row) if row is not None else None

    async def routable(self) -> tuple[RetrievalProfileIdentity, ...]:
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(MemoryLocatorProfileRow)
                    .where(MemoryLocatorProfileRow.state.in_(_ROUTABLE_STATES))
                    .order_by(MemoryLocatorProfileRow.profile_id)
                )
            ).scalars()
            return tuple(_identity(row) for row in rows)

    async def active(self) -> RetrievalProfileIdentity | None:
        async with self.sessions() as session:
            row = (
                await session.execute(
                    select(MemoryLocatorProfileRow).where(MemoryLocatorProfileRow.state == "active")
                )
            ).scalar_one_or_none()
        return _identity(row) if row is not None else None

    async def promotable(self, profile_id: str) -> RetrievalProfileIdentity | None:
        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileRow, profile_id)
            if row is None or row.state not in ("building", "retained"):
                return None
            return _identity(row)

    async def backfill_cursor(self, profile_id: str) -> str | None:
        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileRow, profile_id)
            _require_building(row)
            return row.backfill_cursor

    async def backfill_complete(self, profile_id: str) -> bool:
        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileRow, profile_id)
            _require_building(row)
            return bool(row.backfill_complete)

    async def record_projection(
        self,
        profile_id: str,
        items: tuple[CanonicalProjectionItem, ...],
        *,
        projected_at: datetime,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            _require_routable(profile)
            for item in items:
                canonical = await session.get(
                    MemoryChunkRow, item.canonical_identity, with_for_update=True
                )
                if canonical is None or not all(_eligible_value(canonical)):
                    raise RuntimeError("retrieval_profile_stale_projection_write")
                current = _projection_item(canonical)
                if (
                    current.canonical_version != item.canonical_version
                    or current.canonical_watermark != item.canonical_watermark
                    or current.payload_digest != item.payload_digest
                ):
                    raise RuntimeError("retrieval_profile_stale_projection_write")
                row = await session.get(
                    MemoryLocatorProfileProjectionReceiptRow,
                    (profile_id, item.canonical_identity),
                )
                if row is None:
                    session.add(
                        MemoryLocatorProfileProjectionReceiptRow(
                            profile_id=profile_id,
                            chunk_id=item.canonical_identity,
                            canonical_version=item.canonical_version,
                            canonical_watermark=item.canonical_watermark,
                            payload_digest=item.payload_digest,
                            projected_at=projected_at,
                        )
                    )
                elif row.canonical_version > item.canonical_version:
                    # The provider write already happened. Failing makes the caller
                    # retry from canonical state instead of falsely attesting a stale
                    # point as the newer receipt.
                    raise RuntimeError("retrieval_profile_stale_projection_write")
                elif (
                    row.canonical_version == item.canonical_version
                    and row.payload_digest != item.payload_digest
                ):
                    raise RuntimeError("retrieval_profile_projection_digest_drift")
                else:
                    row.canonical_version = item.canonical_version
                    row.canonical_watermark = item.canonical_watermark
                    row.payload_digest = item.payload_digest
                    row.projected_at = projected_at

    async def checkpoint_backfill(
        self,
        profile_id: str,
        *,
        previous_cursor: str | None,
        cursor: str | None,
        watermark: int,
        complete: bool,
        now: datetime,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            _require_building(row)
            if row.backfill_cursor != previous_cursor:
                raise RuntimeError("retrieval_profile_backfill_cursor_raced")
            row.backfill_cursor = cursor
            row.canonical_watermark = max(row.canonical_watermark, watermark)
            row.backfill_complete = complete
            row.backfill_updated_at = now
            if complete:
                await self._refresh_attestation(session, row)

    async def coverage(
        self,
        profile_id: str,
        *,
        reconciliation_operation=None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileCoverageAttestation:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            await _fence_reconciliation_write(
                session,
                profile_id=profile_id,
                reconciliation_operation=reconciliation_operation,
                runtime_owner=runtime_owner,
            )
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if row is None:
                raise RuntimeError("retrieval_profile_missing")
            await self._refresh_attestation(session, row)
            return _coverage(row)

    async def activation_evidence(
        self,
        profile_id: str,
        *,
        now: datetime,
        reconciliation_operation=None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> ProfileActivationEvidence:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            await _fence_reconciliation_write(
                session,
                profile_id=profile_id,
                reconciliation_operation=reconciliation_operation,
                runtime_owner=runtime_owner,
            )
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            _require_routable(row)
            await self._refresh_attestation(session, row)
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
                        .where(MemoryLocatorProfileLaneRow.profile_id == profile_id)
                        .order_by(MemoryLocatorProfileLaneRow.lane_id)
                    )
                ).scalars()
            )
            routable_ids = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileRow.profile_id).where(
                            MemoryLocatorProfileRow.state.in_(_ROUTABLE_STATES)
                        )
                    )
                ).scalars()
            )
            queue = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(MemoryOutboxRow.attempt_count), 0),
                        func.count().filter(MemoryOutboxRow.status == "dead"),
                        func.min(MemoryOutboxRow.created_at).filter(
                            MemoryOutboxRow.status != "dead"
                        ),
                    ).where(
                        MemoryOutboxRow.fairness_key.in_(
                            tuple(f"profile:{value}" for value in routable_ids)
                        ),
                        MemoryOutboxRow.status.in_(("pending", "retry_pending", "running", "dead")),
                    )
                )
            ).one()
            required_tombstones = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileTombstoneRow)
                    .join(
                        MemoryLocatorProfileRow,
                        MemoryLocatorProfileRow.profile_id
                        == MemoryLocatorProfileTombstoneRow.profile_id,
                    )
                    .where(MemoryLocatorProfileRow.state.in_(("active", "retained")))
                )
                or 0
            )
            completed_tombstones = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileTombstoneRow)
                    .join(
                        MemoryLocatorProfileRow,
                        MemoryLocatorProfileRow.profile_id
                        == MemoryLocatorProfileTombstoneRow.profile_id,
                    )
                    .where(
                        MemoryLocatorProfileRow.state.in_(("active", "retained")),
                        MemoryLocatorProfileTombstoneRow.completed_at.is_not(None),
                    )
                )
                or 0
            )
            return ProfileActivationEvidence(
                coverage=_coverage(row),
                queue=ProfileQueueHealth(int(queue[0]), int(queue[1]), queue[2], now),
                lanes=lanes,
                tombstones=ProfileTombstoneHealth(required_tombstones, completed_tombstones),
            )

    async def activate(
        self,
        lease: ProfileAttestationLease,
        evidence: ProfileActivationEvidence,
        *,
        now: datetime,
        maximum_queue_lag: timedelta,
        maximum_retained: int,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> tuple[str, ...]:
        """Recheck every gate under the same transaction as the state transition."""

        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            evidence_version = await _lock_profile_evidence(session)
            if self.supervisor_trust is not None and runtime_owner is None:
                raise RuntimeError("retrieval_profile_lifecycle_receipt_identity_required")
            if runtime_owner is not None:
                from infinity_context_adapters.postgres.locator_profile_reconciliation import (
                    _register_runtime,
                )

                await _register_runtime(
                    session,
                    runtime_owner,
                    now=now,
                    supervisor_trust=self.supervisor_trust,
                )
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileRow)
                        .where(
                            MemoryLocatorProfileRow.state.in_(("building", "active", "retained"))
                        )
                        .order_by(MemoryLocatorProfileRow.profile_id)
                        .with_for_update()
                    )
                ).scalars()
            )
            profile_id = lease.profile_id
            target = next((row for row in rows if row.profile_id == profile_id), None)
            _require_promotable(target)
            if target.activation_lease_id != lease.lease_id:
                raise RuntimeError("retrieval_profile_activation_lease_invalid")
            database_now = await session.scalar(select(func.clock_timestamp()))
            if (
                not isinstance(database_now, datetime)
                or target.activation_lease_expires_at is None
                or database_now >= target.activation_lease_expires_at
            ):
                raise RuntimeError("retrieval_profile_activation_lease_expired")
            if (
                target.generation != lease.generation
                or target.activation_evidence_digest != lease.evidence_digest
                or evidence.digest() != lease.evidence_digest
                or lease.evidence_version <= 0
                or target.activation_evidence_version != lease.evidence_version
                or evidence_version != lease.evidence_version
                or target.activation_mutation_epoch != lease.mutation_epoch
                or target.provider_mutation_epoch != lease.mutation_epoch
            ):
                raise RuntimeError("retrieval_profile_activation_lease_invalid")
            active_mutations = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if active_mutations:
                raise RuntimeError("retrieval_profile_activation_raced")
            active_queries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileQueryRow)
                    .where(
                        MemoryLocatorProfileQueryRow.profile_id.in_(
                            tuple(row.profile_id for row in rows)
                        )
                    )
                )
                or 0
            )
            if active_queries:
                raise RuntimeError("retrieval_profile_activation_raced")
            await self._refresh_attestation(session, target)
            lane_rows = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileLaneRow).where(
                            MemoryLocatorProfileLaneRow.profile_id == profile_id
                        )
                    )
                ).scalars()
            )
            routable_ids = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileRow.profile_id).where(
                            MemoryLocatorProfileRow.state.in_(_ROUTABLE_STATES)
                        )
                    )
                ).scalars()
            )
            queue = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(MemoryOutboxRow.attempt_count), 0),
                        func.count().filter(MemoryOutboxRow.status == "dead"),
                        func.min(MemoryOutboxRow.created_at).filter(
                            MemoryOutboxRow.status != "dead"
                        ),
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
                        func.count().filter(
                            MemoryLocatorProfileTombstoneRow.completed_at.is_not(None)
                        ),
                    )
                    .select_from(MemoryLocatorProfileTombstoneRow)
                    .join(
                        MemoryLocatorProfileRow,
                        MemoryLocatorProfileRow.profile_id
                        == MemoryLocatorProfileTombstoneRow.profile_id,
                    )
                    .where(
                        MemoryLocatorProfileRow.state.in_(("active", "retained")),
                    )
                )
            ).one()
            current_evidence = ProfileActivationEvidence(
                coverage=_coverage(target),
                queue=ProfileQueueHealth(int(queue[0]), int(queue[1]), queue[2], database_now),
                lanes=tuple(
                    ProfileLaneHealth(
                        item.lane_id,
                        item.required,
                        item.healthy,
                        item.profile_qualified,
                        int(item.observed_count),
                        item.observed_digest,
                    )
                    for item in lane_rows
                ),
                tombstones=ProfileTombstoneHealth(int(tombstones[0]), int(tombstones[1])),
            )
            required_lanes = tuple(item for item in lane_rows if item.required)
            gates_hold = (
                _coverage(target).exact
                and current_evidence.digest() == lease.evidence_digest
                and bool(required_lanes)
                and all(item.healthy and item.profile_qualified for item in required_lanes)
                and int(queue[1]) == 0
                and (queue[2] is None or database_now - queue[2] <= maximum_queue_lag)
                and int(tombstones[0]) == int(tombstones[1])
            )
            if not gates_hold:
                raise RuntimeError("retrieval_profile_activation_raced")
            previous_active = next((row for row in rows if row.state == "active"), None)
            for row in rows:
                if row.state == "active":
                    row.state = "retained"
                    row.retained_at = now
            await session.flush()
            target.state = "active"
            target.activated_at = now
            target.reconciled_at = now
            target.reconciliation_drifted = False
            session.add(
                MemoryLocatorProfileTransitionAuditRow(
                    profile_id=target.profile_id,
                    previous_active_profile_id=(
                        previous_active.profile_id if previous_active is not None else None
                    ),
                    lease_id=lease.lease_id,
                    evidence_digest=lease.evidence_digest,
                    runtime_instance_id=(
                        runtime_owner.instance_id if runtime_owner is not None else None
                    ),
                    runtime_generation=(
                        runtime_owner.generation if runtime_owner is not None else None
                    ),
                    lifecycle_identity_sha256=(
                        runtime_owner.lifecycle_identity_sha256()
                        if runtime_owner is not None
                        else None
                    ),
                    operation="activation",
                    lease_issued_at=lease.issued_at,
                    lease_expires_at=lease.expires_at,
                    requested_expires_at=lease.expires_at,
                    mutation_epoch=lease.mutation_epoch,
                    reconciliation_drifted=False,
                    occurred_at=now,
                )
            )
            retired = await self._enforce_retained_bound(
                session, now=now, maximum_retained=maximum_retained
            )
            return retired

    async def issue_activation_lease(
        self,
        profile_id: str,
        evidence: ProfileActivationEvidence,
        *,
        lease_id: str,
        now: datetime,
        expires_at: datetime,
        mutation_epoch: int = 0,
    ) -> ProfileAttestationLease:
        if expires_at <= now or mutation_epoch < 0:
            raise ValueError("retrieval profile activation lease bounds are invalid")
        ttl = expires_at - now
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            evidence_version = await _lock_profile_evidence(session)
            row = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            _require_promotable(row)
            await self._refresh_attestation(session, row)
            if _coverage(row) != evidence.coverage:
                raise RuntimeError("retrieval_profile_activation_raced")
            active_mutations = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if active_mutations or row.provider_mutation_epoch != mutation_epoch:
                raise RuntimeError("retrieval_profile_activation_raced")
            database_now = await session.scalar(select(func.clock_timestamp()))
            if not isinstance(database_now, datetime):
                raise RuntimeError("retrieval_profile_activation_clock_unavailable")
            lease = ProfileAttestationLease(
                lease_id,
                profile_id,
                row.generation,
                evidence.digest(),
                database_now,
                database_now + ttl,
                evidence_version,
                mutation_epoch,
            )
            row.activation_lease_id = lease.lease_id
            row.activation_evidence_digest = lease.evidence_digest
            row.activation_lease_issued_at = lease.issued_at
            row.activation_lease_expires_at = lease.expires_at
            row.activation_evidence_version = lease.evidence_version
            row.activation_mutation_epoch = lease.mutation_epoch
        return lease

    async def _generation(self, profile_id: str) -> str:
        async with self.sessions() as session:
            row = await session.get(MemoryLocatorProfileRow, profile_id)
            _require_promotable(row)
            return row.generation

    async def rollback(
        self, profile_id: str, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]:
        del profile_id, now, maximum_retained
        raise RuntimeError("retrieval_profile_rollback_requires_attested_promotion")

    async def retire(
        self, profile_id: str, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileRow)
                        .where(
                            MemoryLocatorProfileRow.state.in_(
                                ("building", "active", "retained", "retired")
                            )
                        )
                        .order_by(MemoryLocatorProfileRow.profile_id)
                        .with_for_update()
                    )
                ).scalars()
            )
            target = next((row for row in rows if row.profile_id == profile_id), None)
            if target is None:
                raise RuntimeError("retrieval_profile_missing")
            if target.state == "active":
                raise RuntimeError("retrieval_profile_last_active_protected")
            active_queries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileQueryRow)
                    .where(MemoryLocatorProfileQueryRow.profile_id == profile_id)
                )
                or 0
            )
            if active_queries:
                raise RuntimeError("retrieval_profile_retirement_query_active")
            retired: list[str] = []
            if target.state != "retired":
                target.state = "retired"
                target.provider_mutation_epoch += 1
                target.retired_at = now
                await self._request_cleanup_row(session, target.profile_id, now=now)
                retired.append(target.profile_id)
            bounded = await self._enforce_retained_bound(
                session, now=now, maximum_retained=maximum_retained
            )
            return tuple(dict.fromkeys((*retired, *bounded)))

    async def update_lane(
        self,
        profile_id: str,
        lane_id: str,
        *,
        required: bool,
        healthy: bool,
        profile_qualified: bool,
        failure_code: str | None,
        checked_at: datetime,
        observed_count: int = 0,
        observed_digest: str = _EMPTY_DIGEST,
        reconciliation_operation=None,
        runtime_owner: RuntimeFenceOwner | None = None,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            await _fence_reconciliation_write(
                session,
                profile_id=profile_id,
                reconciliation_operation=reconciliation_operation,
                runtime_owner=runtime_owner,
            )
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if profile is None:
                raise RuntimeError("retrieval_profile_missing")
            row = await session.get(MemoryLocatorProfileLaneRow, (profile_id, lane_id))
            if row is None:
                session.add(
                    MemoryLocatorProfileLaneRow(
                        profile_id=profile_id,
                        lane_id=lane_id,
                        required=required,
                        healthy=healthy,
                        profile_qualified=profile_qualified,
                        failure_code=failure_code,
                        checked_at=checked_at,
                        observed_count=observed_count,
                        observed_digest=observed_digest,
                    )
                )
            else:
                row.required = required
                row.healthy = healthy
                row.profile_qualified = profile_qualified
                row.failure_code = failure_code
                row.checked_at = checked_at
                row.observed_count = observed_count
                row.observed_digest = observed_digest

    async def complete_tombstone(
        self,
        profile_id: str,
        chunk_id: str,
        *,
        canonical_version: int,
        deleted_canonical_version: int | None,
        provider_observed_at: datetime,
        completed_at: datetime,
    ) -> bool:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if profile is None:
                raise RuntimeError("retrieval_profile_missing")
            row = await session.get(
                MemoryLocatorProfileTombstoneRow, (profile_id, chunk_id), with_for_update=True
            )
            if (
                row is None
                or row.canonical_version != canonical_version
                or row.completed_at is not None
            ):
                return False
            if deleted_canonical_version is not None and not (
                1 <= deleted_canonical_version <= canonical_version
            ):
                return False
            chunk = await session.get(MemoryChunkRow, chunk_id)
            if chunk is not None and (
                chunk.retrieval_version != canonical_version or all(_eligible_value(chunk))
            ):
                return False
            row.delete_canonical_version = deleted_canonical_version
            row.provider_observed_at = provider_observed_at
            row.completed_at = completed_at
            row.updated_at = completed_at
            await session.execute(
                delete(MemoryLocatorProfileProjectionReceiptRow).where(
                    MemoryLocatorProfileProjectionReceiptRow.profile_id == profile_id,
                    MemoryLocatorProfileProjectionReceiptRow.chunk_id == chunk_id,
                    MemoryLocatorProfileProjectionReceiptRow.canonical_version <= canonical_version,
                )
            )
            return True

    async def authorize_tombstone(
        self, profile_id: str, chunk_id: str, *, canonical_version: int
    ) -> ProfileTombstoneDeleteAuthorization | None:
        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            tombstone = await session.get(MemoryLocatorProfileTombstoneRow, (profile_id, chunk_id))
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if (
                tombstone is None
                or profile is None
                or profile.state not in _ROUTABLE_STATES
                or tombstone.canonical_version != canonical_version
                or tombstone.completed_at is not None
            ):
                return None
            chunk = await session.get(MemoryChunkRow, chunk_id)
            if chunk is not None and (
                chunk.retrieval_version != canonical_version or all(_eligible_value(chunk))
            ):
                return None
            return ProfileTombstoneDeleteAuthorization(
                _identity(profile),
                tombstone.canonical_version,
            )

    async def _refresh_attestation(
        self, session: AsyncSession, profile: MemoryLocatorProfileRow
    ) -> None:
        expected_accumulator = "0" * 64
        expected_count = 0
        expected_rows = await session.stream_scalars(
            select(MemoryChunkRow)
            .where(*_eligible_conditions())
            .order_by(MemoryChunkRow.id)
            .execution_options(yield_per=256)
        )
        async for row in expected_rows:
            item = _projection_item(row)
            expected_accumulator = accumulate_attestation_digest(
                expected_accumulator,
                item.canonical_identity,
                item.canonical_version,
                item.payload_digest,
            )
            expected_count += 1
        projected_accumulator = "0" * 64
        projected_count = 0
        receipt_rows = await session.stream_scalars(
            select(MemoryLocatorProfileProjectionReceiptRow)
            .where(MemoryLocatorProfileProjectionReceiptRow.profile_id == profile.profile_id)
            .order_by(MemoryLocatorProfileProjectionReceiptRow.chunk_id)
            .execution_options(yield_per=256)
        )
        async for item in receipt_rows:
            projected_accumulator = accumulate_attestation_digest(
                projected_accumulator,
                item.chunk_id,
                item.canonical_version,
                item.payload_digest,
            )
            projected_count += 1
        profile.expected_count = expected_count
        profile.projected_count = projected_count
        profile.canonical_watermark = int(
            await session.scalar(
                select(func.max(MemoryChunkRow.retrieval_commit_watermark)).where(
                    *_eligible_conditions()
                )
            )
            or 0
        )
        profile.projected_watermark = int(
            await session.scalar(
                select(
                    func.max(MemoryLocatorProfileProjectionReceiptRow.canonical_watermark)
                ).where(MemoryLocatorProfileProjectionReceiptRow.profile_id == profile.profile_id)
            )
            or 0
        )
        profile.expected_digest = finalize_attestation_digest(expected_count, expected_accumulator)
        profile.projected_digest = finalize_attestation_digest(
            projected_count, projected_accumulator
        )


async def _lock_profile_evidence(session: AsyncSession) -> int:
    value = await session.scalar(
        text(
            "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
            "WHERE singleton = TRUE FOR UPDATE"
        )
    )
    if value is None:
        raise RuntimeError("retrieval_profile_evidence_version_missing")
    return int(value)


async def _fence_reconciliation_write(
    session,
    *,
    profile_id: str,
    reconciliation_operation,
    runtime_owner: RuntimeFenceOwner | None,
) -> None:
    if reconciliation_operation is None and runtime_owner is None:
        return
    if reconciliation_operation is None or not isinstance(runtime_owner, RuntimeFenceOwner):
        raise RuntimeError("retrieval_profile_reconciliation_runtime_identity_missing")
    from infinity_context_adapters.postgres.locator_profile_reconciliation import (
        _verify_reconciliation_operation,
    )
    from infinity_context_adapters.postgres.locator_runtime_identity import (
        verify_registered_runtime,
    )

    await verify_registered_runtime(session, runtime_owner)
    await _verify_reconciliation_operation(
        session,
        profile_id=profile_id,
        operation=reconciliation_operation,
        owner=runtime_owner,
    )


async def _lock_maintenance(session: AsyncSession) -> None:
    row = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True)
    if row is None:
        raise RuntimeError("retrieval_profile_maintenance_fence_missing")
    if row.active:
        raise RuntimeError("retrieval_profile_maintenance_active")


__all__ = ("PostgresCanonicalProjectionSource", "PostgresRetrievalProfileRegistry")
