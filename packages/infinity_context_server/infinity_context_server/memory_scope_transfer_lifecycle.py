"""Canonical lifecycle fencing for snapshot imports."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from infinity_context_adapters.postgres.document_source_ref_coordination import (
    lock_exact_thread_lifecycle,
    lock_global_fact_lifecycle,
)
from infinity_context_adapters.postgres.models import MemoryThreadRow
from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def referenced_thread_ids(
    *,
    facts: Iterable[dict[str, Any]],
    documents: Iterable[dict[str, Any]],
    episodes: Iterable[dict[str, Any]],
    chunks: Iterable[dict[str, Any]],
    assets: Iterable[dict[str, Any]],
    asset_extraction_jobs: Iterable[dict[str, Any]],
    captures: Iterable[dict[str, Any]],
    skipped: dict[str, set[str]] | None = None,
) -> set[str]:
    """Collect every surviving canonical child thread before any is staged."""

    groups = (
        (facts, "facts", False),
        (documents, "documents", False),
        (episodes, "episodes", True),
        (chunks, "chunks", False),
        (assets, "assets", False),
        (asset_extraction_jobs, "asset_extraction_jobs", False),
        (captures, "captures", False),
    )
    result: set[str] = set()
    for records, record_type, episode_fallback in groups:
        for record in records:
            if skipped is not None and str(record.get("id")) in skipped[record_type]:
                continue
            thread_id = record.get("thread_id")
            if thread_id is None and episode_fallback:
                thread_id = record.get("id")
            if thread_id is not None:
                result.add(str(thread_id))
    return result


def plan_snapshot_thread_fences(
    *,
    threads: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    asset_extraction_jobs: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    skipped: dict[str, set[str]],
    thread_id_map: dict[str, str],
    create_new_memory_scope: bool,
) -> tuple[set[str], set[str], dict[str, str]]:
    """Plan exact fences, admissible creations, and implicit imported threads."""

    source_ids = referenced_thread_ids(
        facts=facts,
        documents=documents,
        episodes=episodes,
        chunks=chunks,
        assets=assets,
        asset_extraction_jobs=asset_extraction_jobs,
        captures=captures,
        skipped=skipped,
    )
    active_import_thread_ids = {
        str(thread["id"])
        for thread in threads
        if thread.get("id") is not None
        and str(thread["id"]) not in skipped["threads"]
        and str(thread.get("status", "active")) == "active"
    }
    source_ids.update(active_import_thread_ids)
    target_ids = {thread_id_map.get(thread_id, thread_id) for thread_id in source_ids}
    if create_new_memory_scope:
        return (
            target_ids,
            target_ids,
            {thread_id: thread_id_map.get(thread_id, thread_id) for thread_id in source_ids},
        )
    thread_payload_ids = {
        str(thread["id"]) for thread in threads if thread.get("id") is not None
    }
    creatable_source_ids = set(active_import_thread_ids)
    creatable_source_ids.update(
        _episode_thread_id(episode)
        for episode in episodes
        if str(episode.get("id")) not in skipped["episodes"]
        and _episode_thread_id(episode) not in thread_payload_ids
    )
    candidate_map = {
        thread_id: thread_id_map.get(thread_id, thread_id) for thread_id in source_ids
    }
    return (
        target_ids,
        {thread_id_map.get(thread_id, thread_id) for thread_id in creatable_source_ids},
        candidate_map,
    )


def _episode_thread_id(episode: dict[str, Any]) -> str:
    return str(episode.get("thread_id") or episode["id"])


async def fence_snapshot_import_threads(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_ids: Iterable[str],
    creatable_thread_ids: Iterable[str],
) -> set[str]:
    """Fence threads and return active or explicitly creatable target identities."""

    exact_ids = tuple(sorted(set(thread_ids)))
    creatable = set(creatable_thread_ids)
    await lock_global_fact_lifecycle(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
    )
    for thread_id in exact_ids:
        await lock_exact_thread_lifecycle(
            session,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
        )
    existing = {
        row.id: row
        for row in (
            (
                await session.execute(
                    select(MemoryThreadRow).where(MemoryThreadRow.id.in_(exact_ids))
                )
            ).scalars()
            if exact_ids
            else ()
        )
    }
    admitted: set[str] = set()
    for thread_id in exact_ids:
        row = existing.get(thread_id)
        if row is None and thread_id in creatable:
            admitted.add(thread_id)
            continue
        if row is None:
            # Pre-thread snapshot versions carried advisory thread ids. Preserve
            # backward compatibility by dropping an unresolved legacy reference.
            continue
        if (
            row.space_id != space_id
            or row.memory_scope_id != memory_scope_id
            or row.status != "active"
        ):
            raise MemoryConflictError(
                "Snapshot references a thread that is neither active nor created by the import"
            )
        admitted.add(thread_id)
    return admitted


__all__ = (
    "fence_snapshot_import_threads",
    "plan_snapshot_thread_fences",
    "referenced_thread_ids",
)
