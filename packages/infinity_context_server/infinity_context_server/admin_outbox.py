"""Admin outbox replay and compaction commands."""

from __future__ import annotations

from datetime import datetime, timedelta

from infinity_context_adapters.postgres.models import MemoryOutboxRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.composition import build_container
from infinity_context_server.config import Settings

SAFE_COMPACTED_OUTBOX_PAYLOAD_KEYS = frozenset(
    {
        "space_id",
        "memory_scope_id",
        "thread_id",
        "fact_id",
        "document_id",
        "chunk_id",
        "episode_id",
        "suggestion_id",
        "version",
    }
)


async def replay_outbox(*, status: str, limit: int) -> dict[str, object]:
    if status != "dead":
        raise ValueError("status must be exactly 'dead'")
    container = build_container(Settings())
    try:
        async with AsyncSession(container.engine) as session:
            rows = list(
                (
                    await session.execute(
                        select(MemoryOutboxRow)
                        .where(MemoryOutboxRow.status == status)
                        .order_by(MemoryOutboxRow.created_at)
                        .limit(limit)
                    )
                ).scalars()
            )
            now = container.clock.now()
            for row in rows:
                row.status = "pending"
                row.next_attempt_at = now
                row.updated_at = now
            await session.commit()
        return {"replayed": len(rows), "from_status": status}
    finally:
        await container.engine.dispose()


async def compact_done_outbox(
    *,
    older_than_seconds: int,
    limit: int,
    dry_run: bool,
) -> dict[str, object]:
    if older_than_seconds < 0:
        raise ValueError("older_than_seconds must be >= 0")
    if limit < 1:
        raise ValueError("limit must be >= 1")

    container = build_container(Settings())
    try:
        now = container.clock.now()
        cutoff = now - timedelta(seconds=older_than_seconds)
        async with AsyncSession(container.engine) as session:
            rows = list(
                (
                    await session.execute(
                        select(MemoryOutboxRow)
                        .where(
                            MemoryOutboxRow.status == "done",
                            MemoryOutboxRow.updated_at <= cutoff,
                            MemoryOutboxRow.aggregate_type != "benchmark_run",
                        )
                        .order_by(MemoryOutboxRow.updated_at, MemoryOutboxRow.id)
                        .limit(limit)
                    )
                ).scalars()
            )
            already_compacted = sum(
                1
                for row in rows
                if isinstance(row.payload_json, dict) and row.payload_json.get("compacted") is True
            )
            rows_to_compact = [
                row
                for row in rows
                if not (
                    isinstance(row.payload_json, dict) and row.payload_json.get("compacted") is True
                )
            ]
            if not dry_run:
                for row in rows_to_compact:
                    row.payload_json = _compacted_outbox_payload(row, now=now)
                    row.updated_at = now
                await session.commit()
        return {
            "status": "ok",
            "dry_run": dry_run,
            "matched": len(rows),
            "compacted": 0 if dry_run else len(rows_to_compact),
            "would_compact": len(rows_to_compact),
            "already_compacted": already_compacted,
            "older_than_seconds": older_than_seconds,
            "limit": limit,
            "cutoff": cutoff.isoformat(),
        }
    finally:
        await container.engine.dispose()


def _compacted_outbox_payload(row: MemoryOutboxRow, *, now: datetime) -> dict[str, object]:
    original_payload = row.payload_json if isinstance(row.payload_json, dict) else {}
    safe_payload = {
        key: value
        for key, value in original_payload.items()
        if key in SAFE_COMPACTED_OUTBOX_PAYLOAD_KEYS and isinstance(value, str | int | type(None))
    }
    return {
        "compacted": True,
        "compacted_at": now.isoformat(),
        "payload_key_count": len(original_payload),
        "preserved": safe_payload,
    }
