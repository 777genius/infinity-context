"""Feature-owned scheduling for provider-fenced tombstone replay."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.locator_models import (
    MemoryLocatorProfileTombstoneRow,
)
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow


async def schedule_pending_tombstone_replay(
    session: AsyncSession,
    *,
    profile_id: str,
    provider_mutation_epoch: int,
    now: datetime,
) -> None:
    """Create one bounded cleanup event after an epoch can have changed provider state."""

    rows = tuple(
        (
            await session.execute(
                select(MemoryLocatorProfileTombstoneRow)
                .where(
                    MemoryLocatorProfileTombstoneRow.profile_id == profile_id,
                    MemoryLocatorProfileTombstoneRow.completed_at.is_(None),
                )
                .order_by(MemoryLocatorProfileTombstoneRow.chunk_id)
            )
        ).scalars()
    )
    for tombstone in rows:
        identity = (
            f"{profile_id}:{tombstone.chunk_id}:{tombstone.canonical_version}:"
            f"{provider_mutation_epoch}"
        )
        message_key = (
            "locator-profile-delete-fence:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        )
        exists = await session.scalar(
            select(MemoryOutboxRow.id).where(MemoryOutboxRow.message_key == message_key)
        )
        if exists is not None:
            continue
        session.add(
            MemoryOutboxRow(
                message_key=message_key,
                event_type="vector.delete_locator_profile",
                aggregate_type="locator_profile_chunk",
                aggregate_id=tombstone.chunk_id,
                aggregate_version=tombstone.canonical_version,
                workload_class="projection",
                fairness_key=f"profile:{profile_id}",
                payload_json={
                    "chunk_ids": [tombstone.chunk_id],
                    "profile_id": profile_id,
                },
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
        )


__all__ = ("schedule_pending_tombstone_replay",)
