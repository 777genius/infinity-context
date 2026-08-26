"""Read-only canonical Retrieval profile queryability policy."""

from __future__ import annotations

from sqlalchemy import exists, func, select

from .locator_models import (
    MemoryLocatorProfileLaneRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileProviderMutationRow,
    MemoryLocatorProfileRow,
)


async def is_profile_canonically_queryable(session, profile_id: str) -> bool:
    """Return the exact canonical predicate used by every query admission path.

    The database evaluates lease expiry so application clock skew cannot admit an
    expired profile. Provider calls are deliberately excluded: current canonical
    lane state and mutation fences are the read authority.
    """

    database_now = (
        func.clock_timestamp()
        if session.bind is not None and session.bind.dialect.name == "postgresql"
        else func.current_timestamp()
    )
    active_mutation = exists(
        select(MemoryLocatorProfileProviderMutationRow.profile_id).where(
            MemoryLocatorProfileProviderMutationRow.profile_id == profile_id
        )
    )
    required_lane = exists(
        select(MemoryLocatorProfileLaneRow.profile_id).where(
            MemoryLocatorProfileLaneRow.profile_id == profile_id,
            MemoryLocatorProfileLaneRow.required.is_(True),
        )
    )
    unhealthy_required_lane = exists(
        select(MemoryLocatorProfileLaneRow.profile_id).where(
            MemoryLocatorProfileLaneRow.profile_id == profile_id,
            MemoryLocatorProfileLaneRow.required.is_(True),
            (
                MemoryLocatorProfileLaneRow.healthy.is_(False)
                | MemoryLocatorProfileLaneRow.profile_qualified.is_(False)
            ),
        )
    )
    queryable = await session.scalar(
        select(MemoryLocatorProfileRow.profile_id)
        .join(
            MemoryLocatorProfileMaintenanceFenceRow,
            MemoryLocatorProfileMaintenanceFenceRow.singleton.is_(True),
        )
        .where(
            MemoryLocatorProfileRow.profile_id == profile_id,
            MemoryLocatorProfileRow.state == "active",
            MemoryLocatorProfileMaintenanceFenceRow.active.is_(False),
            MemoryLocatorProfileRow.reconciliation_drifted.is_(False),
            MemoryLocatorProfileRow.activation_lease_id.is_not(None),
            MemoryLocatorProfileRow.activation_lease_expires_at.is_not(None),
            MemoryLocatorProfileRow.activation_lease_expires_at > database_now,
            MemoryLocatorProfileRow.activation_evidence_version > 0,
            MemoryLocatorProfileRow.activation_mutation_epoch
            == MemoryLocatorProfileRow.provider_mutation_epoch,
            ~active_mutation,
            required_lane,
            ~unhealthy_required_lane,
        )
        .limit(1)
    )
    return queryable is not None


__all__ = ("is_profile_canonically_queryable",)
