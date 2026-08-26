"""Retired Retrieval profile cleanup lifecycle."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from infinity_context_core.features.context_building.public import (
    ProfileCleanup,
    ProfileCollectionDeleteAuthorization,
    RetainedProfile,
    retained_profiles_to_retire,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.postgres.locator_profile_mapping import (
    profile_cleanup as _cleanup,
)
from infinity_context_adapters.postgres.locator_profile_mapping import (
    profile_identity as _identity,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileAttestationCheckpointRow,
    MemoryLocatorProfileCleanupRow,
    MemoryLocatorProfileLaneRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileOperatorOperationRow,
    MemoryLocatorProfileOperatorRebuildRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileQueryRow,
    MemoryLocatorProfileReconciliationOperationRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProfileTombstoneRow,
    MemoryOutboxRow,
)


class PostgresRetrievalProfileCleanupMixin:
    """Cleanup policy kept separate from profile build and attestation orchestration."""

    sessions: async_sessionmaker[AsyncSession]

    async def request_cleanup(self, profile_id: str, *, now: datetime) -> ProfileCleanup:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if profile is None:
                raise RuntimeError("retrieval_profile_missing")
            if profile.state != "retired":
                raise RuntimeError("retrieval_profile_cleanup_requires_retired")
            row = await self._request_cleanup_row(session, profile_id, now=now)
            return _cleanup(profile, row)

    async def cleanup(self, profile_id: str) -> ProfileCleanup:
        async with self.sessions() as session:
            profile = await session.get(MemoryLocatorProfileRow, profile_id)
            row = await session.get(MemoryLocatorProfileCleanupRow, profile_id)
            if profile is None or row is None:
                raise RuntimeError("retrieval_profile_cleanup_missing")
            return _cleanup(profile, row)

    async def cleanup_candidates(self, *, limit: int) -> tuple[str, ...]:
        async with self.sessions() as session:
            return tuple(
                (
                    await session.execute(
                        select(MemoryLocatorProfileCleanupRow.profile_id)
                        .where(MemoryLocatorProfileCleanupRow.phase != "complete")
                        .order_by(
                            MemoryLocatorProfileCleanupRow.updated_at,
                            MemoryLocatorProfileCleanupRow.profile_id,
                        )
                        .limit(limit)
                    )
                ).scalars()
            )

    async def reconcile_retained_profiles(
        self, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            return await self._enforce_retained_bound(
                session, now=now, maximum_retained=maximum_retained
            )

    async def authorize_collection_delete(
        self, profile_id: str, *, now: datetime
    ) -> ProfileCollectionDeleteAuthorization | None:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            row = await session.get(
                MemoryLocatorProfileCleanupRow, profile_id, with_for_update=True
            )
            if profile is None or row is None or profile.state != "retired":
                raise RuntimeError("retrieval_profile_cleanup_not_authorized")
            if row.phase not in ("requested", "waiting_for_jobs"):
                return None
            running = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryOutboxRow)
                    .where(
                        MemoryOutboxRow.fairness_key == f"profile:{profile_id}",
                        MemoryOutboxRow.status == "running",
                    )
                )
                or 0
            )
            provider_writers = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            active_queries = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileQueryRow)
                    .where(MemoryLocatorProfileQueryRow.profile_id == profile_id)
                )
                or 0
            )
            row.attempt_count += 1
            row.updated_at = now
            row.last_error_code = None
            if running or provider_writers or active_queries:
                row.phase = "waiting_for_jobs"
                return None
            row.phase = "requested"
            if row.delete_token is None:
                profile.provider_mutation_epoch += 1
                row.delete_token = f"profile-delete-{uuid4().hex}"
                row.delete_epoch = profile.provider_mutation_epoch
                row.delete_authorized_at = now
            if row.delete_epoch != profile.provider_mutation_epoch:
                raise RuntimeError("retrieval_profile_cleanup_fence_drift")
            return ProfileCollectionDeleteAuthorization(
                _identity(profile), row.delete_token, int(row.delete_epoch)
            )

    async def mark_collection_deleted(
        self,
        authorization: ProfileCollectionDeleteAuthorization,
        *,
        now: datetime,
    ) -> None:
        profile_id = authorization.identity.profile_id
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            row = await session.get(
                MemoryLocatorProfileCleanupRow, profile_id, with_for_update=True
            )
            if profile is None or row is None or profile.state != "retired":
                raise RuntimeError("retrieval_profile_cleanup_not_authorized")
            if row.phase == "collection_deleted":
                return
            if (
                row.phase != "requested"
                or row.delete_token != authorization.delete_token
                or row.delete_epoch != authorization.provider_epoch
                or profile.provider_mutation_epoch != authorization.provider_epoch
            ):
                raise RuntimeError("retrieval_profile_cleanup_fence_drift")
            writers = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if writers:
                raise RuntimeError("retrieval_profile_cleanup_writer_raced")
            row.phase = "collection_deleted"
            row.updated_at = now
            row.last_error_code = None

    async def cleanup_postgres(self, profile_id: str, *, now: datetime) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            row = await session.get(
                MemoryLocatorProfileCleanupRow, profile_id, with_for_update=True
            )
            if profile is None or row is None or profile.state != "retired":
                raise RuntimeError("retrieval_profile_cleanup_not_authorized")
            if row.phase == "postgres_cleaned":
                return
            if row.phase != "collection_deleted":
                raise RuntimeError("retrieval_profile_cleanup_phase_mismatch")
            for model in (
                # Checkpoints and their ON DELETE CASCADE page manifests are
                # recovery evidence until the retired collection is physically
                # deleted; only this fenced lifecycle phase may remove them.
                MemoryLocatorProfileAttestationCheckpointRow,
                MemoryLocatorProfileOperatorRebuildRow,
                MemoryLocatorProfileOperatorOperationRow,
                MemoryLocatorProfileProviderMutationRow,
                MemoryLocatorProfileQueryRow,
                MemoryLocatorProfileReconciliationOperationRow,
                MemoryLocatorProfileProjectionReceiptRow,
                MemoryLocatorProfileTombstoneRow,
                MemoryLocatorProfileLaneRow,
            ):
                await session.execute(delete(model).where(model.profile_id == profile_id))
            await session.execute(
                delete(MemoryOutboxRow).where(
                    MemoryOutboxRow.fairness_key == f"profile:{profile_id}"
                )
            )
            row.phase = "postgres_cleaned"
            row.updated_at = now
            row.last_error_code = None

    async def complete_cleanup(self, profile_id: str, *, now: datetime) -> None:
        await self._advance_cleanup(
            profile_id, expected=("postgres_cleaned", "complete"), target="complete", now=now
        )

    async def record_cleanup_failure(
        self, profile_id: str, *, error_code: str, now: datetime
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            row = await session.get(
                MemoryLocatorProfileCleanupRow, profile_id, with_for_update=True
            )
            if row is None or row.phase == "complete":
                return
            row.last_error_code = error_code
            row.updated_at = now

    async def _advance_cleanup(
        self,
        profile_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
        now: datetime,
    ) -> None:
        async with self.sessions() as session, session.begin():
            await _lock_cleanup_gates(session)
            row = await session.get(
                MemoryLocatorProfileCleanupRow, profile_id, with_for_update=True
            )
            if row is None:
                raise RuntimeError("retrieval_profile_cleanup_missing")
            if row.phase == target:
                return
            if row.phase not in expected:
                raise RuntimeError("retrieval_profile_cleanup_phase_mismatch")
            row.phase = target
            row.updated_at = now
            row.last_error_code = None

    async def _request_cleanup_row(
        self, session: AsyncSession, profile_id: str, *, now: datetime
    ) -> MemoryLocatorProfileCleanupRow:
        row = await session.get(MemoryLocatorProfileCleanupRow, profile_id)
        if row is None:
            row = MemoryLocatorProfileCleanupRow(
                profile_id=profile_id,
                phase="requested",
                attempt_count=0,
                last_error_code=None,
                requested_at=now,
                updated_at=now,
            )
            session.add(row)
        return row

    async def _enforce_retained_bound(
        self, session: AsyncSession, *, now: datetime, maximum_retained: int
    ) -> tuple[str, ...]:
        retained = tuple(
            (
                await session.execute(
                    select(MemoryLocatorProfileRow)
                    .where(MemoryLocatorProfileRow.state == "retained")
                    .order_by(MemoryLocatorProfileRow.profile_id)
                    .with_for_update()
                )
            ).scalars()
        )
        retire_ids = retained_profiles_to_retire(
            tuple(
                RetainedProfile(item.profile_id, item.retained_at or item.created_at)
                for item in retained
            ),
            maximum_retained=maximum_retained,
        )
        for profile in retained:
            if profile.profile_id in retire_ids:
                active_queries = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(MemoryLocatorProfileQueryRow)
                        .where(MemoryLocatorProfileQueryRow.profile_id == profile.profile_id)
                    )
                    or 0
                )
                if active_queries:
                    raise RuntimeError("retrieval_profile_retirement_query_active")
                profile.state = "retired"
                profile.provider_mutation_epoch += 1
                profile.retired_at = now
                await self._request_cleanup_row(session, profile.profile_id, now=now)
        return retire_ids


async def _lock_cleanup_gates(session: AsyncSession) -> None:
    maintenance = await session.get(
        MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True
    )
    if maintenance is None:
        raise RuntimeError("retrieval_profile_maintenance_fence_missing")
    if maintenance.active:
        raise RuntimeError("retrieval_profile_maintenance_active")
    value = await session.scalar(
        text(
            "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
            "WHERE singleton = TRUE FOR UPDATE"
        )
    )
    if value is None:
        raise RuntimeError("retrieval_profile_evidence_version_missing")
