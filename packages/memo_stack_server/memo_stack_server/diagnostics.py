"""Production-safe diagnostics for API routes and admin commands."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from memo_stack_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemorySuggestionRow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_server.composition import Container
from memo_stack_server.pagination import cursor_int, decode_cursor, encode_cursor


async def adapter_diagnostics(container: Container) -> dict[str, Any]:
    capabilities = await container.get_capabilities.execute()
    return {
        "adapters": {adapter.name: asdict(adapter) for adapter in capabilities.adapters},
        "capabilities": [
            _capability_payload(capability) for capability in capabilities.capabilities
        ],
        "circuits": _circuit_snapshots(container),
        "enabled_adapters": [
            adapter.name for adapter in capabilities.adapters if adapter.enabled and adapter.healthy
        ],
        "policy_mode": capabilities.policy_mode,
        "deploy_profile": capabilities.deploy_profile,
    }


def _capability_payload(capability: Any) -> dict[str, Any]:
    payload = asdict(capability)
    status = str(payload["status"])
    payload["capability"] = str(payload["capability"])
    payload["mode"] = str(payload["mode"])
    payload["status"] = status
    payload["projection_freshness"] = str(payload["projection_freshness"])
    payload["healthy"] = status == "ok"
    return payload


async def outbox_diagnostics(
    container: Container,
    *,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    decoded_cursor = decode_cursor(cursor, kind="diagnostics_outbox")
    last_id = cursor_int(decoded_cursor, "id")
    now = container.clock.now()
    async with AsyncSession(container.engine) as session:
        counts = {
            str(status): int(count)
            for status, count in (
                await session.execute(
                    select(MemoryOutboxRow.status, func.count(MemoryOutboxRow.id)).group_by(
                        MemoryOutboxRow.status
                    )
                )
            ).all()
        }
        oldest_pending = await session.scalar(
            select(func.min(MemoryOutboxRow.created_at)).where(
                MemoryOutboxRow.status.in_(("pending", "retry_pending", "running"))
            )
        )
        query = select(MemoryOutboxRow).order_by(MemoryOutboxRow.id).limit(limit + 1)
        if last_id is not None:
            query = query.where(MemoryOutboxRow.id > last_id)
        rows = list((await session.execute(query)).scalars())

    visible_rows = rows[:limit]
    next_cursor = (
        encode_cursor("diagnostics_outbox", id=visible_rows[-1].id)
        if len(rows) > limit and visible_rows
        else None
    )
    return {
        "counts": counts,
        "oldest_active_lag_seconds": _lag_seconds(now, oldest_pending),
        "items": [_outbox_row_to_diagnostic(row) for row in visible_rows],
        "next_cursor": next_cursor,
    }


async def profile_diagnostics(container: Container, *, profile_id: str) -> dict[str, Any]:
    async with AsyncSession(container.engine) as session:
        active_facts = await _count_by_profile(session, MemoryFactRow, profile_id, "active")
        deleted_facts = await _count_by_profile(session, MemoryFactRow, profile_id, "deleted")
        active_documents = await _count_by_profile(
            session, MemoryDocumentRow, profile_id, "active"
        )
        deleted_documents = await _count_by_profile(
            session, MemoryDocumentRow, profile_id, "deleted"
        )
        active_chunks = await _count_by_profile(session, MemoryChunkRow, profile_id, "active")
        deleted_chunks = await _count_by_profile(session, MemoryChunkRow, profile_id, "deleted")
        pending_suggestions = await _count_by_profile(
            session, MemorySuggestionRow, profile_id, "pending"
        )
    return {
        "profile_id": profile_id,
        "facts": {"active": active_facts, "deleted": deleted_facts},
        "documents": {"active": active_documents, "deleted": deleted_documents},
        "chunks": {"active": active_chunks, "deleted": deleted_chunks},
        "suggestions": {"pending": pending_suggestions},
    }


async def operational_metrics(container: Container) -> dict[str, Any]:
    now = container.clock.now()
    async with AsyncSession(container.engine) as session:
        outbox_counts = await _status_counts(session, MemoryOutboxRow)
        oldest_pending = await session.scalar(
            select(func.min(MemoryOutboxRow.created_at)).where(
                MemoryOutboxRow.status.in_(("pending", "retry_pending", "running"))
            )
        )
        facts = await _status_counts(session, MemoryFactRow)
        documents = await _status_counts(session, MemoryDocumentRow)
        chunks = await _status_counts(session, MemoryChunkRow)
        suggestions = await _status_counts(session, MemorySuggestionRow)
    capabilities = await container.get_capabilities.execute()
    adapter_statuses = {
        adapter.name: {
            "status": _adapter_status(adapter.enabled, adapter.healthy, adapter.degraded_reason),
            "enabled": adapter.enabled,
            "healthy": adapter.healthy,
            "degraded_reason": adapter.degraded_reason,
        }
        for adapter in capabilities.adapters
    }
    pending_active = sum(
        outbox_counts.get(status, 0) for status in ("pending", "retry_pending", "running")
    )
    dead_count = outbox_counts.get("dead", 0)
    oldest_active_lag_seconds = _lag_seconds(now, oldest_pending)
    context_metrics = container.runtime_metrics.snapshot()
    circuit_snapshots = _circuit_snapshots(container)
    return {
        "outbox": {
            "counts": outbox_counts,
            "pending_active": pending_active,
            "dead": dead_count,
            "oldest_active_lag_seconds": oldest_active_lag_seconds,
        },
        "canonical": {
            "facts": facts,
            "documents": documents,
            "chunks": chunks,
            "suggestions": suggestions,
        },
        "adapters": adapter_statuses,
        "circuits": circuit_snapshots,
        "context": context_metrics,
        "alerts": _operational_alerts(
            dead_count=dead_count,
            pending_active=pending_active,
            oldest_active_lag_seconds=oldest_active_lag_seconds,
            adapters=adapter_statuses,
            circuits=circuit_snapshots,
            context_degraded_rate=float(context_metrics["degraded_rate"]),
        ),
    }


async def _count_by_profile(
    session: AsyncSession,
    model: type[MemoryFactRow]
    | type[MemoryDocumentRow]
    | type[MemoryChunkRow]
    | type[MemorySuggestionRow],
    profile_id: str,
    status: str,
) -> int:
    return int(
        (
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.profile_id == profile_id, model.status == status)
            )
        )
        or 0
    )


async def _status_counts(
    session: AsyncSession,
    model: type[MemoryOutboxRow]
    | type[MemoryFactRow]
    | type[MemoryDocumentRow]
    | type[MemoryChunkRow]
    | type[MemorySuggestionRow],
) -> dict[str, int]:
    return {
        str(status): int(count)
        for status, count in (
            await session.execute(select(model.status, func.count(model.id)).group_by(model.status))
        ).all()
    }


def _outbox_row_to_diagnostic(row: MemoryOutboxRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "aggregate_version": row.aggregate_version,
        "workload_class": row.workload_class,
        "fairness_key": row.fairness_key,
        "status": row.status,
        "attempt_count": row.attempt_count,
        "last_safe_error": row.last_safe_error,
        "last_safe_diagnostic_code": row.last_safe_diagnostic_code,
        "next_attempt_at": row.next_attempt_at.isoformat(),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _lag_seconds(now, oldest_pending) -> int | None:
    if oldest_pending is None:
        return None
    if oldest_pending.tzinfo is None and now.tzinfo is not None:
        oldest_pending = oldest_pending.replace(tzinfo=now.tzinfo)
    return max(0, int((now - oldest_pending).total_seconds()))


def _adapter_status(enabled: bool, healthy: bool, degraded_reason: str | None) -> str:
    if not enabled and degraded_reason == "disabled":
        return "disabled"
    if enabled and healthy:
        return "ok"
    return "degraded"


def _circuit_snapshots(container: Container) -> dict[str, dict[str, object]]:
    return {circuit.adapter_name: circuit.snapshot() for circuit in container.provider_circuits}


def _operational_alerts(
    *,
    dead_count: int,
    pending_active: int,
    oldest_active_lag_seconds: int | None,
    adapters: dict[str, dict[str, object]],
    circuits: dict[str, dict[str, object]],
    context_degraded_rate: float,
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    if dead_count > 0:
        alerts.append(
            _alert(
                name="outbox_dead_count",
                severity="warning",
                value=dead_count,
                threshold=0,
                playbook_command="python -m memo_stack_server.admin replay-outbox --status dead",
            )
        )
    if pending_active > 0 and (oldest_active_lag_seconds or 0) > 600:
        alerts.append(
            _alert(
                name="outbox_pending_lag_seconds",
                severity="warning",
                value=oldest_active_lag_seconds or 0,
                threshold=600,
                playbook_command="python -m memo_stack_server.worker --once",
            )
        )
    for adapter_name, adapter in adapters.items():
        if adapter["status"] == "degraded":
            alerts.append(
                _alert(
                    name=f"adapter_{adapter_name}_degraded",
                    severity="warning",
                    value=1,
                    threshold=0,
                    playbook_command="python -m memo_stack_server.doctor",
                )
            )
    for adapter_name, circuit in circuits.items():
        if circuit["state"] == "open":
            alerts.append(
                _alert(
                    name=f"provider_circuit_{adapter_name}_open",
                    severity="warning",
                    value=int(circuit["failure_count"]),
                    threshold=int(circuit["failure_threshold"]),
                    playbook_command="python -m memo_stack_server.doctor",
                )
            )
    if context_degraded_rate > 0.2:
        alerts.append(
            _alert(
                name="context_degraded_rate",
                severity="warning",
                value=int(context_degraded_rate * 10000),
                threshold=2000,
                playbook_command="python -m memo_stack_server.doctor",
            )
        )
    return alerts


def _alert(
    *,
    name: str,
    severity: str,
    value: int,
    threshold: int,
    playbook_command: str,
) -> dict[str, object]:
    return {
        "name": name,
        "severity": severity,
        "status": "firing",
        "value": value,
        "threshold": threshold,
        "playbook_command": playbook_command,
    }
