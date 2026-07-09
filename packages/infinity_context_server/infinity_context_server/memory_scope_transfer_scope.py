"""Scope helpers for MemoryScope snapshot transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_adapters.postgres.models import (
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.memory_scope_transfer_remap import episode_source_thread_id
from infinity_context_server.memory_scope_transfer_support import (
    bounded_external_ref,
    import_thread_external_ref,
    stable_id,
)


async def load_scope(
    session: AsyncSession,
    *,
    space_slug: str,
    memory_scope_external_ref: str,
) -> tuple[MemorySpaceRow, MemoryScopeRow] | None:
    space = (
        await session.execute(
            select(MemorySpaceRow).where(
                MemorySpaceRow.slug == space_slug,
                MemorySpaceRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if space is None:
        return None
    memory_scope = (
        await session.execute(
            select(MemoryScopeRow).where(
                MemoryScopeRow.space_id == space.id,
                MemoryScopeRow.external_ref == memory_scope_external_ref,
                MemoryScopeRow.status == "active",
            )
        )
    ).scalar_one_or_none()
    if memory_scope is None:
        return None
    return space, memory_scope


async def create_import_memory_scope(
    session: AsyncSession,
    *,
    space_id: str,
    base_memory_scope_id: str,
    now: datetime,
) -> MemoryScopeRow:
    base_memory_scope = await session.get(MemoryScopeRow, base_memory_scope_id)
    if base_memory_scope is None:
        msg = "Base memory_scope not found"
        raise ValueError(msg)
    external_ref = await _next_import_memory_scope_ref(
        session,
        space_id=space_id,
        base_external_ref=base_memory_scope.external_ref,
        now=now,
    )
    row = MemoryScopeRow(
        id=stable_id("memory_scope", space_id, external_ref),
        space_id=space_id,
        external_ref=external_ref,
        name=f"{base_memory_scope.name} import",
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def load_threads(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
) -> list[MemoryThreadRow]:
    return list(
        (
            await session.execute(
                select(MemoryThreadRow)
                .where(
                    MemoryThreadRow.space_id == space_id,
                    MemoryThreadRow.memory_scope_id == memory_scope_id,
                )
                .order_by(MemoryThreadRow.created_at, MemoryThreadRow.id)
            )
        ).scalars()
    )


def thread_to_json(row: MemoryThreadRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_ref": row.external_ref,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def ensure_import_threads(
    session: AsyncSession,
    *,
    threads: list[dict[str, Any]] | None = None,
    skipped_thread_ids: set[str] | None = None,
    episodes: list[dict[str, Any]],
    skipped_episode_ids: set[str],
    thread_id_map: dict[str, str],
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> None:
    threads = threads or []
    skipped_thread_ids = skipped_thread_ids or set()
    imported_thread_ids = await _import_snapshot_threads(
        session,
        threads=threads,
        skipped_thread_ids=skipped_thread_ids,
        thread_id_map=thread_id_map,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        now=now,
    )
    thread_payload_ids = {str(thread["id"]) for thread in threads if thread.get("id") is not None}
    needed = {
        episode_source_thread_id(episode): thread_id_map.get(
            episode_source_thread_id(episode),
            episode_source_thread_id(episode),
        )
        for episode in episodes
        if str(episode.get("id")) not in skipped_episode_ids
        and episode_source_thread_id(episode) not in thread_payload_ids
    }
    needed = {
        source_thread_id: target_thread_id
        for source_thread_id, target_thread_id in needed.items()
        if target_thread_id not in imported_thread_ids
    }
    if not needed:
        return
    existing = set(
        (
            await session.execute(
                select(MemoryThreadRow.id).where(MemoryThreadRow.id.in_(set(needed.values())))
            )
        ).scalars()
    )
    for source_thread_id, target_thread_id in needed.items():
        if target_thread_id in existing:
            continue
        session.add(
            MemoryThreadRow(
                id=target_thread_id,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                external_ref=import_thread_external_ref(source_thread_id, target_thread_id),
                status="active",
                created_at=now,
                updated_at=now,
            )
        )


async def _import_snapshot_threads(
    session: AsyncSession,
    *,
    threads: list[dict[str, Any]],
    skipped_thread_ids: set[str],
    thread_id_map: dict[str, str],
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> set[str]:
    target_thread_ids = {
        thread_id_map.get(str(thread["id"]), str(thread["id"]))
        for thread in threads
        if thread.get("id") is not None and str(thread["id"]) not in skipped_thread_ids
    }
    if not target_thread_ids:
        return set()
    existing = set(
        (
            await session.execute(
                select(MemoryThreadRow.id).where(MemoryThreadRow.id.in_(target_thread_ids))
            )
        ).scalars()
    )
    imported: set[str] = set()
    for thread in threads:
        thread_id = str(thread["id"])
        if thread_id in skipped_thread_ids:
            continue
        target_thread_id = thread_id_map.get(thread_id, thread_id)
        imported.add(target_thread_id)
        if target_thread_id in existing:
            continue
        session.add(
            MemoryThreadRow(
                id=target_thread_id,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                external_ref=str(thread.get("external_ref") or thread_id)[:240],
                status=str(thread.get("status", "active"))[:40],
                created_at=_parse_dt(thread.get("created_at"), now),
                updated_at=_parse_dt(thread.get("updated_at"), now),
            )
        )
    return imported


async def _next_import_memory_scope_ref(
    session: AsyncSession,
    *,
    space_id: str,
    base_external_ref: str,
    now: datetime,
) -> str:
    base = bounded_external_ref(
        f"{base_external_ref}-import-{now.strftime('%Y%m%d%H%M%S')}",
        suffix="",
    )
    candidate = base
    suffix = 2
    while await _memory_scope_ref_exists(session, space_id=space_id, external_ref=candidate):
        candidate = bounded_external_ref(base, suffix=f"-{suffix}")
        suffix += 1
    return candidate


async def _memory_scope_ref_exists(
    session: AsyncSession,
    *,
    space_id: str,
    external_ref: str,
) -> bool:
    return (
        await session.scalar(
            select(MemoryScopeRow.id).where(
                MemoryScopeRow.space_id == space_id,
                MemoryScopeRow.external_ref == external_ref,
            )
        )
        is not None
    )


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str):
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback
