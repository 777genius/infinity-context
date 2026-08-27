"""Admin projection repair and reindex commands."""

from __future__ import annotations

from datetime import datetime

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.admin_invariants import ScopeFilters, _resolve_scope, _scope_filters
from infinity_context_server.composition import build_container
from infinity_context_server.config import Settings
from infinity_context_server.processes.vector_rebuild import EVENT_TYPE, MAX_BATCH_SIZE


async def repair_projections(
    *,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
) -> dict[str, object]:
    if not space or not memory_scope:
        return {
            "status": "refused",
            "reason": "repair requires --space and --memory_scope",
            "dry_run": dry_run,
        }
    if not dry_run:
        return {
            "status": "refused",
            "reason": "repair requires --dry-run in Core Lite",
            "dry_run": dry_run,
        }
    container = build_container(Settings())
    try:
        async with AsyncSession(container.engine) as session:
            scope = await _resolve_scope(session, space=space, memory_scope=memory_scope)
            if scope is None:
                return {
                    "status": "not_found",
                    "space": space,
                    "memory_scope": memory_scope,
                    "dry_run": dry_run,
                }
            scope_filters = _scope_filters(scope)
            active_chunks = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(MemoryChunkRow)
                        .where(
                            MemoryChunkRow.status == "active",
                            *scope_filters.for_model(MemoryChunkRow),
                        )
                    )
                )
                or 0
            )
            active_facts = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(MemoryFactRow)
                        .where(
                            MemoryFactRow.status == "active",
                            *scope_filters.for_model(MemoryFactRow),
                        )
                    )
                )
                or 0
            )
        return {
            "status": "ok",
            "space": space,
            "memory_scope": memory_scope,
            "dry_run": dry_run,
            "qdrant": {
                "missing_chunks": active_chunks,
                "stale_chunks": 0,
                "would_upsert": active_chunks,
                "would_delete": 0,
                "enqueued": 0,
                "skipped_existing_jobs": 0,
            },
            "graphiti": {
                "missing_facts": active_facts,
                "stale_facts": 0,
                "would_upsert": active_facts,
                "would_delete": 0,
                "enqueued": 0,
                "skipped_existing_jobs": 0,
            },
        }
    finally:
        await container.engine.dispose()


async def reindex_qdrant(
    *,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    confirmed: bool = False,
    operation_id: str | None = None,
    batch_size: int = 100,
) -> dict[str, object]:
    return await _start_qdrant_rebuild(
        space=space,
        memory_scope=memory_scope,
        dry_run=dry_run,
        confirmed=confirmed,
        operation_id=operation_id,
        batch_size=batch_size,
    )


async def _start_qdrant_rebuild(
    *,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    confirmed: bool,
    operation_id: str | None,
    batch_size: int,
) -> dict[str, object]:
    refusal = _qdrant_rebuild_refusal(
        space=space,
        memory_scope=memory_scope,
        dry_run=dry_run,
        confirmed=confirmed,
        operation_id=operation_id,
        batch_size=batch_size,
    )
    if refusal is not None:
        return refusal
    container = build_container(Settings())
    try:
        async with AsyncSession(container.engine) as session:
            scope = await _resolve_scope(session, space=space, memory_scope=memory_scope)
            if scope is None:
                return {
                    "status": "not_found",
                    "operation": "reindex-qdrant",
                    "space": space,
                    "memory_scope": memory_scope,
                    "dry_run": dry_run,
                }
            space_id, memory_scope_id = scope
            assert space_id is not None and memory_scope_id is not None
            await session.execute(
                select(MemoryScopeRow)
                .where(MemoryScopeRow.id == memory_scope_id)
                .with_for_update()
            )
            counts = await _qdrant_rebuild_counts(
                session, space_id=space_id, memory_scope_id=memory_scope_id
            )
            if dry_run:
                return _qdrant_rebuild_result(
                    status="ok",
                    operation_id=operation_id,
                    space=space,
                    memory_scope=memory_scope,
                    dry_run=True,
                    batch_size=batch_size,
                    counts=counts,
                    cursor=None,
                )
            assert operation_id is not None
            existing = await _existing_rebuild(session, operation_id)
            if existing is not None:
                expected = _rebuild_payload(
                    operation_id=operation_id,
                    space_id=space_id,
                    memory_scope_id=memory_scope_id,
                    upper_bound_id=str(existing.payload_json.get("upper_bound_id") or ""),
                    cursor=existing.payload_json.get("cursor"),
                    batch_size=batch_size,
                )
                comparable = dict(existing.payload_json)
                comparable["cursor"] = expected["cursor"]
                if comparable != expected:
                    return {
                        "status": "refused",
                        "operation": "reindex-qdrant",
                        "reason": "operation id is already bound to a different rebuild",
                        "dry_run": False,
                    }
                if existing.status == "dead":
                    existing.status = "pending"
                    existing.attempt_count = 0
                    existing.next_attempt_at = container.clock.now()
                    existing.last_safe_error = None
                    existing.last_safe_diagnostic_code = None
                    existing.updated_at = container.clock.now()
                resumed_status = "complete" if existing.status == "done" else "resumed"
                resumed_cursor = existing.payload_json.get("cursor")
                await session.commit()
                return _qdrant_rebuild_result(
                    status=resumed_status,
                    operation_id=operation_id,
                    space=space,
                    memory_scope=memory_scope,
                    dry_run=False,
                    batch_size=batch_size,
                    counts=counts,
                    cursor=resumed_cursor,
                )
            upper_bound_id = str(
                (
                    await session.scalar(
                        select(func.max(MemoryChunkRow.id)).where(
                            MemoryChunkRow.space_id == space_id,
                            MemoryChunkRow.memory_scope_id == memory_scope_id,
                        )
                    )
                )
                or "\U0010ffff"
            )
            now = container.clock.now()
            session.add(
                _projection_outbox(
                    event_type=EVENT_TYPE,
                    aggregate_type="vector_rebuild",
                    aggregate_id=operation_id,
                    now=now,
                    fairness_key=f"vector-rebuild:{operation_id}",
                    payload=_rebuild_payload(
                        operation_id=operation_id,
                        space_id=space_id,
                        memory_scope_id=memory_scope_id,
                        upper_bound_id=upper_bound_id,
                        cursor=None,
                        batch_size=batch_size,
                    ),
                )
            )
            await session.commit()
        return _qdrant_rebuild_result(
            status="started",
            operation_id=operation_id,
            space=space,
            memory_scope=memory_scope,
            dry_run=False,
            batch_size=batch_size,
            counts=counts,
            cursor=None,
        )
    finally:
        await container.engine.dispose()


async def reindex_graphiti(
    *,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    confirmed: bool = False,
) -> dict[str, object]:
    return await _reindex_projection(
        operation="reindex-graphiti",
        adapter_key="graphiti",
        aggregate_type="fact",
        event_type="graph.upsert_fact",
        space=space,
        memory_scope=memory_scope,
        dry_run=dry_run,
        confirmed=confirmed,
    )


async def _reindex_projection(
    *,
    operation: str,
    adapter_key: str,
    aggregate_type: str,
    event_type: str,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    confirmed: bool,
) -> dict[str, object]:
    if not space or not memory_scope:
        return {
            "status": "refused",
            "operation": operation,
            "reason": "reindex requires --space and --memory_scope",
            "dry_run": dry_run,
        }
    if not dry_run and not confirmed:
        return {
            "status": "refused",
            "operation": operation,
            "reason": "reindex requires --i-understand-this-enqueues-projection-jobs",
            "dry_run": dry_run,
        }

    container = build_container(Settings())
    try:
        async with AsyncSession(container.engine) as session:
            scope = await _resolve_scope(session, space=space, memory_scope=memory_scope)
            if scope is None:
                return {
                    "status": "not_found",
                    "operation": operation,
                    "space": space,
                    "memory_scope": memory_scope,
                    "dry_run": dry_run,
                }
            scope_filters = _scope_filters(scope)
            rows = await _active_projection_rows(
                session,
                aggregate_type=aggregate_type,
                scope_filters=scope_filters,
            )
            skipped_existing = 0
            enqueued = 0
            if not dry_run:
                now = container.clock.now()
                for row in rows:
                    aggregate_id = str(row.id)
                    aggregate_version = _projection_aggregate_version(row, aggregate_type)
                    exists_active_job = await _active_projection_job_exists(
                        session,
                        event_type=event_type,
                        aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id,
                        aggregate_version=aggregate_version,
                    )
                    if exists_active_job:
                        skipped_existing += 1
                        continue
                    session.add(
                        _projection_outbox(
                            event_type=event_type,
                            aggregate_type=aggregate_type,
                            aggregate_id=aggregate_id,
                            aggregate_version=aggregate_version,
                            now=now,
                            payload=_projection_payload(
                                aggregate_type=aggregate_type,
                                aggregate_id=aggregate_id,
                                aggregate_version=aggregate_version,
                                space_id=str(row.space_id),
                                memory_scope_id=str(row.memory_scope_id),
                            ),
                        )
                    )
                    enqueued += 1
                await session.commit()
        would_upsert = len(rows)
        return {
            "status": "ok",
            "operation": operation,
            "space": space,
            "memory_scope": memory_scope,
            "dry_run": dry_run,
            adapter_key: _reindex_adapter_payload(
                aggregate_type=aggregate_type,
                would_upsert=would_upsert,
                enqueued=enqueued,
                skipped_existing_jobs=skipped_existing,
            ),
        }
    finally:
        await container.engine.dispose()


async def _active_projection_rows(
    session: AsyncSession,
    *,
    aggregate_type: str,
    scope_filters: ScopeFilters,
) -> list[MemoryChunkRow] | list[MemoryFactRow]:
    if aggregate_type == "chunk":
        return list(
            (
                await session.execute(
                    select(MemoryChunkRow)
                    .where(
                        MemoryChunkRow.status == "active",
                        *scope_filters.for_model(MemoryChunkRow),
                    )
                    .order_by(MemoryChunkRow.id)
                )
            ).scalars()
        )
    if aggregate_type == "fact":
        return list(
            (
                await session.execute(
                    select(MemoryFactRow)
                    .where(
                        MemoryFactRow.status == "active",
                        *scope_filters.for_model(MemoryFactRow),
                    )
                    .order_by(MemoryFactRow.id)
                )
            ).scalars()
        )
    raise ValueError(f"Unsupported projection aggregate type: {aggregate_type}")


async def _active_projection_job_exists(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int | None,
) -> bool:
    version_filter = (
        MemoryOutboxRow.aggregate_version.is_(None)
        if aggregate_version is None
        else MemoryOutboxRow.aggregate_version == aggregate_version
    )
    count = await session.scalar(
        select(func.count())
        .select_from(MemoryOutboxRow)
        .where(
            MemoryOutboxRow.event_type == event_type,
            MemoryOutboxRow.aggregate_type == aggregate_type,
            MemoryOutboxRow.aggregate_id == aggregate_id,
            version_filter,
            MemoryOutboxRow.status.in_(("pending", "retry_pending", "running")),
        )
    )
    return int(count or 0) > 0


def _projection_aggregate_version(
    row: MemoryChunkRow | MemoryFactRow,
    aggregate_type: str,
) -> int | None:
    if aggregate_type == "fact":
        return int(row.version)
    return None


def _projection_payload(
    *,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int | None,
    space_id: str,
    memory_scope_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "space_id": space_id,
        "memory_scope_id": memory_scope_id,
    }
    if aggregate_type == "chunk":
        payload["chunk_id"] = aggregate_id
    elif aggregate_type == "fact":
        payload["fact_id"] = aggregate_id
        payload["fact_version"] = aggregate_version
    return payload


def _reindex_adapter_payload(
    *,
    aggregate_type: str,
    would_upsert: int,
    enqueued: int,
    skipped_existing_jobs: int,
) -> dict[str, object]:
    if aggregate_type == "chunk":
        return {
            "missing_chunks": would_upsert,
            "stale_chunks": 0,
            "would_upsert": would_upsert,
            "would_delete": 0,
            "enqueued": enqueued,
            "skipped_existing_jobs": skipped_existing_jobs,
        }
    return {
        "missing_facts": would_upsert,
        "stale_facts": 0,
        "would_upsert": would_upsert,
        "would_delete": 0,
        "enqueued": enqueued,
        "skipped_existing_jobs": skipped_existing_jobs,
    }


def _projection_outbox(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    now: datetime,
    payload: dict[str, object],
    aggregate_version: int | None = None,
    fairness_key: str | None = None,
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        workload_class="projection",
        fairness_key=fairness_key or f"{aggregate_type}:{aggregate_id}",
        payload_json=payload,
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=now,
        updated_at=now,
    )


def _qdrant_rebuild_refusal(
    *,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    confirmed: bool,
    operation_id: str | None,
    batch_size: int,
) -> dict[str, object] | None:
    reason: str | None = None
    if not space or not memory_scope:
        reason = "rebuild requires --space and --memory_scope"
    elif type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
        reason = f"rebuild --batch-size must be between 1 and {MAX_BATCH_SIZE}"
    elif not dry_run and not confirmed:
        reason = "rebuild requires --i-understand-this-enqueues-projection-jobs"
    elif not dry_run and not _valid_operation_id(operation_id):
        reason = "rebuild apply requires a stable --operation-id (8-80 safe characters)"
    if reason is None:
        return None
    return {
        "status": "refused",
        "operation": "reindex-qdrant",
        "reason": reason,
        "dry_run": dry_run,
    }


def _valid_operation_id(value: str | None) -> bool:
    return bool(
        isinstance(value, str)
        and 8 <= len(value) <= 80
        and all(
            character.isascii() and (character.isalnum() or character in "-_.")
            for character in value
        )
    )


async def _qdrant_rebuild_counts(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
) -> dict[str, int]:
    conditions = (
        MemoryChunkRow.space_id == space_id,
        MemoryChunkRow.memory_scope_id == memory_scope_id,
    )
    active = int(
        (
            await session.scalar(
                select(func.count()).select_from(MemoryChunkRow).where(
                    *conditions, MemoryChunkRow.status == "active"
                )
            )
        )
        or 0
    )
    total = int(
        (await session.scalar(select(func.count()).select_from(MemoryChunkRow).where(*conditions)))
        or 0
    )
    dead = int(
        (
            await session.scalar(
                select(func.count()).select_from(MemoryOutboxRow).where(
                    MemoryOutboxRow.status == "dead",
                    MemoryOutboxRow.last_safe_diagnostic_code.in_(
                        (
                            "vector.delete_canonical_versions_rebuild_required",
                            "qdrant.delete_rebuild_required",
                        )
                    ),
                    MemoryOutboxRow.payload_json["space_id"].as_string() == space_id,
                    MemoryOutboxRow.payload_json["memory_scope_id"].as_string()
                    == memory_scope_id,
                )
            )
        )
        or 0
    )
    return {"active": active, "deleted_or_ineligible": total - active, "dead_events": dead}


async def _existing_rebuild(
    session: AsyncSession, operation_id: str
) -> MemoryOutboxRow | None:
    return (
        await session.execute(
            select(MemoryOutboxRow)
            .where(
                MemoryOutboxRow.event_type == EVENT_TYPE,
                MemoryOutboxRow.aggregate_type == "vector_rebuild",
                MemoryOutboxRow.aggregate_id == operation_id,
            )
            .order_by(MemoryOutboxRow.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


def _rebuild_payload(
    *,
    operation_id: str,
    space_id: str,
    memory_scope_id: str,
    upper_bound_id: str,
    cursor: object,
    batch_size: int,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "space_id": space_id,
        "memory_scope_id": memory_scope_id,
        "upper_bound_id": upper_bound_id,
        "cursor": cursor,
        "batch_size": batch_size,
    }


def _qdrant_rebuild_result(
    *,
    status: str,
    operation_id: str | None,
    space: str | None,
    memory_scope: str | None,
    dry_run: bool,
    batch_size: int,
    counts: dict[str, int],
    cursor: object,
) -> dict[str, object]:
    return {
        "status": status,
        "operation": "reindex-qdrant",
        "operation_id": operation_id,
        "space": space,
        "memory_scope": memory_scope,
        "dry_run": dry_run,
        "batch_size": batch_size,
        "cursor": cursor,
        "qdrant": {
            "would_upsert": counts["active"],
            "would_delete_or_reconcile": counts["deleted_or_ineligible"],
            "dead_events_recoverable": counts["dead_events"],
            "enqueued": 0 if dry_run or status in {"complete", "resumed"} else 1,
        },
    }
