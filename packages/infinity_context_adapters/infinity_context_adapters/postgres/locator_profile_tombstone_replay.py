"""Bounded durable scheduling for provider-fenced tombstone replay."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.locator_models import (
    MemoryLocatorProfileTombstoneReplayRow,
    MemoryLocatorProfileTombstoneRow,
)
from infinity_context_adapters.postgres.outbox_models import MemoryOutboxRow

TOMBSTONE_REPLAY_PAGE_LIMIT = 32
TOMBSTONE_REPLAY_EVENT = "vector.replay_locator_profile_tombstones"


async def request_tombstone_replay(
    session: AsyncSession,
    *,
    profile_id: str,
    provider_mutation_epoch: int,
    now: datetime,
) -> None:
    """Coalesce one provider epoch into constant-size durable continuation state."""

    state = await session.get(
        MemoryLocatorProfileTombstoneReplayRow, profile_id, with_for_update=True
    )
    if state is None:
        requested_epoch = provider_mutation_epoch
        state = MemoryLocatorProfileTombstoneReplayRow(
            profile_id=profile_id,
            requested_epoch=requested_epoch,
            processed_epoch=0,
            scan_epoch=None,
            cursor_chunk_id=None,
            updated_at=now,
        )
        session.add(state)
    else:
        requested_epoch = max(state.requested_epoch + 1, provider_mutation_epoch)
        state.requested_epoch = requested_epoch
        state.updated_at = now
    await _enqueue_continuation(
        session,
        profile_id=profile_id,
        requested_epoch=requested_epoch,
        cursor=None,
        now=now,
    )


async def continue_tombstone_replay(
    session: AsyncSession,
    *,
    profile_id: str,
    now: datetime,
    limit: int = TOMBSTONE_REPLAY_PAGE_LIMIT,
) -> int:
    """Expand at most one deterministic page and persist the next cursor."""

    if not 1 <= limit <= TOMBSTONE_REPLAY_PAGE_LIMIT:
        raise ValueError("Tombstone replay page limit is invalid")
    state = await session.get(
        MemoryLocatorProfileTombstoneReplayRow, profile_id, with_for_update=True
    )
    if state is None or (
        state.scan_epoch is None and state.processed_epoch >= state.requested_epoch
    ):
        return 0
    if state.scan_epoch is None:
        state.scan_epoch = state.requested_epoch
        state.cursor_chunk_id = None
    scan_epoch = int(state.scan_epoch)
    query = select(MemoryLocatorProfileTombstoneRow).where(
        MemoryLocatorProfileTombstoneRow.profile_id == profile_id,
        MemoryLocatorProfileTombstoneRow.completed_at.is_(None),
    )
    if state.cursor_chunk_id is not None:
        query = query.where(MemoryLocatorProfileTombstoneRow.chunk_id > state.cursor_chunk_id)
    rows = tuple(
        (
            await session.execute(
                query.order_by(MemoryLocatorProfileTombstoneRow.chunk_id).limit(limit + 1)
            )
        ).scalars()
    )
    page = rows[:limit]
    keys = tuple(_delete_key(profile_id, row, scan_epoch) for row in page)
    existing = set()
    if keys:
        existing = set(
            (
                await session.execute(
                    select(MemoryOutboxRow.message_key).where(MemoryOutboxRow.message_key.in_(keys))
                )
            ).scalars()
        )
    for row, message_key in zip(page, keys, strict=True):
        if message_key not in existing:
            session.add(_delete_event(row, message_key=message_key, now=now))
    if len(rows) > limit:
        state.cursor_chunk_id = page[-1].chunk_id
        await _enqueue_continuation(
            session,
            profile_id=profile_id,
            requested_epoch=scan_epoch,
            cursor=state.cursor_chunk_id,
            now=now,
        )
    else:
        state.processed_epoch = max(state.processed_epoch, scan_epoch)
        state.scan_epoch = None
        state.cursor_chunk_id = None
        if state.requested_epoch > state.processed_epoch:
            await _enqueue_continuation(
                session,
                profile_id=profile_id,
                requested_epoch=state.requested_epoch,
                cursor=None,
                now=now,
            )
    state.updated_at = now
    return len(page)


def _delete_event(row, *, message_key: str, now: datetime) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        message_key=message_key,
        event_type="vector.delete_locator_profile",
        aggregate_type="locator_profile_chunk",
        aggregate_id=row.chunk_id,
        aggregate_version=row.canonical_version,
        workload_class="projection",
        fairness_key=f"profile:{row.profile_id}",
        payload_json={"chunk_ids": [row.chunk_id], "profile_id": row.profile_id},
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )


async def _enqueue_continuation(
    session: AsyncSession,
    *,
    profile_id: str,
    requested_epoch: int,
    cursor: str | None,
    now: datetime,
) -> None:
    identity = f"{profile_id}:{requested_epoch}:{cursor or ''}"
    message_key = (
        "locator-profile-tombstone-page:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
    )
    if (
        await session.scalar(
            select(MemoryOutboxRow.id).where(MemoryOutboxRow.message_key == message_key)
        )
        is not None
    ):
        return
    session.add(
        MemoryOutboxRow(
            message_key=message_key,
            event_type=TOMBSTONE_REPLAY_EVENT,
            aggregate_type="locator_profile",
            aggregate_id=profile_id,
            aggregate_version=requested_epoch,
            workload_class="projection",
            fairness_key=f"profile:{profile_id}",
            payload_json={"profile_id": profile_id},
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _delete_key(profile_id: str, row, scan_epoch: int) -> str:
    identity = f"{profile_id}:{row.chunk_id}:{row.canonical_version}:{scan_epoch}"
    return "locator-profile-delete-fence:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


__all__ = (
    "TOMBSTONE_REPLAY_EVENT",
    "TOMBSTONE_REPLAY_PAGE_LIMIT",
    "continue_tombstone_replay",
    "request_tombstone_replay",
)
