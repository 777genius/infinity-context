"""Canonical tombstone authorization and provider-epoch completion fence."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.features.context_building.public import (
    ProfileTombstoneDeleteAuthorization,
)
from sqlalchemy import delete, func, select, text

from infinity_context_adapters.postgres.locator_profile_mapping import (
    ROUTABLE_PROFILE_STATES,
    eligible_value,
    profile_identity,
)
from infinity_context_adapters.postgres.locator_profile_tombstone_replay import (
    request_tombstone_replay,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileProjectionReceiptRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileRow,
    MemoryLocatorProfileTombstoneRow,
)


class PostgresRetrievalProfileTombstoneMixin:
    async def reopen_stale_projection_tombstone(
        self,
        profile_id: str,
        chunk_id: str,
        *,
        stale_version: int,
        now: datetime,
    ) -> int | None:
        """Make possible stale provider state durably pending before cleanup."""

        async with self.sessions() as session, session.begin():
            await _lock_maintenance(session)
            await _lock_profile_evidence(session)
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow,
                (profile_id, chunk_id),
                with_for_update=True,
            )
            if (
                profile is None
                or profile.state not in ROUTABLE_PROFILE_STATES
                or tombstone is None
                or stale_version > tombstone.canonical_version
            ):
                return None
            active_writers = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if active_writers:
                raise RuntimeError("retrieval_profile_provider_mutation_active")
            tombstone.delete_canonical_version = None
            tombstone.delete_authorized_mutation_epoch = None
            tombstone.delete_completed_mutation_epoch = None
            tombstone.provider_observed_at = None
            tombstone.completed_at = None
            tombstone.updated_at = now
            await request_tombstone_replay(
                session,
                profile_id=profile_id,
                provider_mutation_epoch=int(profile.provider_mutation_epoch),
                now=now,
            )
            return int(tombstone.canonical_version)

    async def complete_tombstone(
        self,
        profile_id: str,
        chunk_id: str,
        *,
        canonical_version: int,
        authorized_mutation_epoch: int,
        completed_mutation_epoch: int,
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
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow, (profile_id, chunk_id), with_for_update=True
            )
            expected_epoch = authorized_mutation_epoch + (
                2 if deleted_canonical_version is not None else 0
            )
            if (
                tombstone is None
                or tombstone.canonical_version != canonical_version
                or tombstone.completed_at is not None
                or tombstone.delete_authorized_mutation_epoch != authorized_mutation_epoch
                or completed_mutation_epoch != expected_epoch
            ):
                return False
            if deleted_canonical_version is not None and not (
                1 <= deleted_canonical_version <= canonical_version
            ):
                return False
            chunk = await session.get(MemoryChunkRow, chunk_id)
            if chunk is not None and (
                chunk.retrieval_version != canonical_version or all(eligible_value(chunk))
            ):
                return False
            active_writers = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if active_writers or profile.provider_mutation_epoch != completed_mutation_epoch:
                return False
            tombstone.delete_canonical_version = deleted_canonical_version
            tombstone.delete_completed_mutation_epoch = completed_mutation_epoch
            tombstone.provider_observed_at = provider_observed_at
            tombstone.completed_at = completed_at
            tombstone.updated_at = completed_at
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
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            tombstone = await session.get(
                MemoryLocatorProfileTombstoneRow,
                (profile_id, chunk_id),
                with_for_update=True,
            )
            if (
                tombstone is None
                or profile is None
                or profile.state not in ROUTABLE_PROFILE_STATES
                or tombstone.canonical_version != canonical_version
                or tombstone.completed_at is not None
            ):
                return None
            chunk = await session.get(MemoryChunkRow, chunk_id)
            if chunk is not None and (
                chunk.retrieval_version != canonical_version or all(eligible_value(chunk))
            ):
                return None
            active_writers = int(
                await session.scalar(
                    select(func.count())
                    .select_from(MemoryLocatorProfileProviderMutationRow)
                    .where(MemoryLocatorProfileProviderMutationRow.profile_id == profile_id)
                )
                or 0
            )
            if active_writers:
                raise RuntimeError("retrieval_profile_provider_mutation_active")
            if tombstone.delete_authorized_mutation_epoch != profile.provider_mutation_epoch:
                tombstone.delete_authorized_mutation_epoch = profile.provider_mutation_epoch
                tombstone.delete_completed_mutation_epoch = None
                tombstone.delete_canonical_version = None
                tombstone.provider_observed_at = None
            return ProfileTombstoneDeleteAuthorization(
                profile_identity(profile),
                chunk_id,
                tombstone.canonical_version,
                int(profile.provider_mutation_epoch),
            )


async def _lock_profile_evidence(session) -> None:
    value = await session.scalar(
        text(
            "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
            "WHERE singleton = TRUE FOR UPDATE"
        )
    )
    if value is None:
        raise RuntimeError("retrieval_profile_evidence_version_missing")


async def _lock_maintenance(session) -> None:
    row = await session.get(MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True)
    if row is None:
        raise RuntimeError("retrieval_profile_maintenance_fence_missing")
    if row.active:
        raise RuntimeError("retrieval_profile_maintenance_active")


__all__ = ("PostgresRetrievalProfileTombstoneMixin",)
