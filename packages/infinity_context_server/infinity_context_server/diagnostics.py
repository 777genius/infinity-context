"""Production-safe diagnostics for API routes and admin commands."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
    MemoryDocumentRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemorySuggestionRow,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.composition import Container
from infinity_context_server.extraction_capabilities import build_extraction_capability_payload
from infinity_context_server.pagination import cursor_int, decode_cursor, encode_cursor


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
        "extraction": build_extraction_capability_payload(container.settings),
        "storage": storage_diagnostics(container),
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


async def memory_scope_diagnostics(container: Container, *, memory_scope_id: str) -> dict[str, Any]:
    async with AsyncSession(container.engine) as session:
        active_facts = await _count_by_memory_scope(
            session, MemoryFactRow, memory_scope_id, "active"
        )
        deleted_facts = await _count_by_memory_scope(
            session, MemoryFactRow, memory_scope_id, "deleted"
        )
        active_documents = await _count_by_memory_scope(
            session, MemoryDocumentRow, memory_scope_id, "active"
        )
        deleted_documents = await _count_by_memory_scope(
            session, MemoryDocumentRow, memory_scope_id, "deleted"
        )
        active_chunks = await _count_by_memory_scope(
            session, MemoryChunkRow, memory_scope_id, "active"
        )
        deleted_chunks = await _count_by_memory_scope(
            session, MemoryChunkRow, memory_scope_id, "deleted"
        )
        pending_suggestions = await _count_by_memory_scope(
            session, MemorySuggestionRow, memory_scope_id, "pending"
        )
        context_links = await _status_counts_by_memory_scope(
            session,
            MemoryContextLinkRow,
            memory_scope_id,
        )
        context_link_suggestions = await _status_counts_by_memory_scope(
            session,
            MemoryContextLinkSuggestionRow,
            memory_scope_id,
        )
    return {
        "memory_scope_id": memory_scope_id,
        "facts": {"active": active_facts, "deleted": deleted_facts},
        "documents": {"active": active_documents, "deleted": deleted_documents},
        "chunks": {"active": active_chunks, "deleted": deleted_chunks},
        "suggestions": {"pending": pending_suggestions},
        "context_links": _with_status_defaults(context_links, ("active", "deleted")),
        "context_link_suggestions": _with_status_defaults(
            context_link_suggestions,
            ("pending", "approved", "rejected", "expired"),
        ),
    }


def storage_diagnostics(container: Container) -> dict[str, Any]:
    settings = container.settings
    backend = settings.asset_storage_backend
    if backend == "local":
        readiness = _local_storage_readiness(settings.asset_storage_dir)
        return {
            "asset_backend": "local",
            "asset_external": False,
            "configured": True,
            "ready": readiness["ready"],
            "readiness": readiness,
            "maintenance": _storage_maintenance_config(settings),
            "governance": _storage_governance_config(settings),
        }
    if backend == "s3":
        configured = bool(settings.asset_storage_s3_bucket)
        return {
            "asset_backend": "s3",
            "asset_external": True,
            "configured": configured,
            "ready": configured,
            "readiness": {
                "bucket_configured": configured,
                "prefix_configured": bool(settings.asset_storage_s3_prefix.strip()),
                "endpoint_configured": bool(settings.asset_storage_s3_endpoint_url),
                "region_configured": bool(settings.asset_storage_s3_region),
                "explicit_credentials_configured": bool(
                    settings.asset_storage_s3_access_key_id
                    and settings.asset_storage_s3_secret_access_key
                ),
                "session_token_configured": bool(settings.asset_storage_s3_session_token),
                "force_path_style": settings.asset_storage_s3_force_path_style,
                "network_probe": "not_performed",
            },
            "maintenance": _storage_maintenance_config(settings),
            "governance": _storage_governance_config(settings),
        }
    return {
        "asset_backend": backend,
        "asset_external": False,
        "configured": False,
        "ready": False,
        "readiness": {"unsupported_backend": True},
        "maintenance": _storage_maintenance_config(settings),
        "governance": _storage_governance_config(settings),
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
        context_links = await _status_counts(session, MemoryContextLinkRow)
        context_link_suggestions = await _status_counts(session, MemoryContextLinkSuggestionRow)
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
    storage = storage_diagnostics(container)
    storage["maintenance"] = {
        **dict(storage.get("maintenance") or {}),
        **container.runtime_metrics.storage_maintenance_snapshot(),
    }
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
            "context_links": _with_status_defaults(context_links, ("active", "deleted")),
            "context_link_suggestions": _with_status_defaults(
                context_link_suggestions,
                ("pending", "approved", "rejected", "expired"),
            ),
        },
        "adapters": adapter_statuses,
        "circuits": circuit_snapshots,
        "context": context_metrics,
        "storage": storage,
        "alerts": _operational_alerts(
            dead_count=dead_count,
            pending_active=pending_active,
            oldest_active_lag_seconds=oldest_active_lag_seconds,
            adapters=adapter_statuses,
            circuits=circuit_snapshots,
            context_degraded_rate=float(context_metrics["degraded_rate"]),
            storage=storage,
        ),
    }


async def _count_by_memory_scope(
    session: AsyncSession,
    model: type[Any],
    memory_scope_id: str,
    status: str,
) -> int:
    return int(
        (
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.memory_scope_id == memory_scope_id, model.status == status)
            )
        )
        or 0
    )


async def _status_counts_by_memory_scope(
    session: AsyncSession,
    model: type[Any],
    memory_scope_id: str,
) -> dict[str, int]:
    return {
        str(status): int(count)
        for status, count in (
            await session.execute(
                select(model.status, func.count(model.id))
                .where(model.memory_scope_id == memory_scope_id)
                .group_by(model.status)
            )
        ).all()
    }


async def _status_counts(
    session: AsyncSession,
    model: type[Any],
) -> dict[str, int]:
    return {
        str(status): int(count)
        for status, count in (
            await session.execute(select(model.status, func.count(model.id)).group_by(model.status))
        ).all()
    }


def _with_status_defaults(counts: dict[str, int], statuses: tuple[str, ...]) -> dict[str, int]:
    return {status: counts.get(status, 0) for status in statuses} | {
        status: count for status, count in counts.items() if status not in statuses
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


def _local_storage_readiness(root_dir: str) -> dict[str, object]:
    root = Path(root_dir).expanduser()
    root_exists = root.exists()
    root_is_dir = root.is_dir()
    nearest_parent = _nearest_existing_parent(root)
    root_writable = root_is_dir and _path_writable(root)
    parent_writable = nearest_parent is not None and _path_writable(nearest_parent)
    return {
        "root_configured": bool(str(root_dir).strip()),
        "root_exists": root_exists,
        "root_is_dir": root_is_dir,
        "root_writable": root_writable,
        "parent_exists": nearest_parent is not None,
        "parent_writable": parent_writable,
        "ready": root_writable or (not root_exists and parent_writable),
    }


def _nearest_existing_parent(path: Path) -> Path | None:
    current = path if path.exists() else path.parent
    while current != current.parent:
        if current.exists():
            return current
        current = current.parent
    return current if current.exists() else None


def _path_writable(path: Path) -> bool:
    try:
        return path.is_dir() and path.stat().st_mode is not None and os.access(path, os.W_OK)
    except OSError:
        return False


def _operational_alerts(
    *,
    dead_count: int,
    pending_active: int,
    oldest_active_lag_seconds: int | None,
    adapters: dict[str, dict[str, object]],
    circuits: dict[str, dict[str, object]],
    context_degraded_rate: float,
    storage: dict[str, Any],
) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    if dead_count > 0:
        alerts.append(
            _alert(
                name="outbox_dead_count",
                severity="warning",
                value=dead_count,
                threshold=0,
                playbook_command=(
                    "python -m infinity_context_server.admin replay-outbox --status dead"
                ),
            )
        )
    if pending_active > 0 and (oldest_active_lag_seconds or 0) > 600:
        alerts.append(
            _alert(
                name="outbox_pending_lag_seconds",
                severity="warning",
                value=oldest_active_lag_seconds or 0,
                threshold=600,
                playbook_command="python -m infinity_context_server.worker --once",
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
                    playbook_command="python -m infinity_context_server.doctor",
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
                    playbook_command="python -m infinity_context_server.doctor",
                )
            )
    if context_degraded_rate > 0.2:
        alerts.append(
            _alert(
                name="context_degraded_rate",
                severity="warning",
                value=int(context_degraded_rate * 10000),
                threshold=2000,
                playbook_command="python -m infinity_context_server.doctor",
            )
        )
    if storage.get("ready") is not True:
        alerts.append(
            _alert(
                name="asset_storage_not_ready",
                severity="critical",
                value=1,
                threshold=0,
                playbook_command="python -m infinity_context_server.doctor",
            )
        )
    maintenance = storage.get("maintenance")
    if isinstance(maintenance, dict):
        last_trace = maintenance.get("last_trace")
        if isinstance(last_trace, dict) and last_trace.get("status") == "degraded":
            alerts.append(
                _alert(
                    name="asset_storage_maintenance_degraded",
                    severity="warning",
                    value=1,
                    threshold=0,
                    playbook_command=(
                        "python -m infinity_context_server.admin audit-asset-storage"
                    ),
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


def _storage_maintenance_config(settings) -> dict[str, object]:
    return {
        "enabled": bool(getattr(settings, "asset_storage_maintenance_enabled", False)),
        "interval_seconds": int(
            getattr(settings, "asset_storage_maintenance_interval_seconds", 3600)
        ),
        "limit": int(getattr(settings, "asset_storage_maintenance_limit", 100)),
        "prefix_configured": bool(
            str(getattr(settings, "asset_storage_maintenance_prefix", "")).strip()
        ),
        "cleanup_apply_enabled": bool(
            getattr(settings, "asset_storage_cleanup_apply_enabled", False)
        ),
        "cleanup_max_deletions": int(
            getattr(settings, "asset_storage_cleanup_max_deletions", 100)
        ),
        "cleanup_grace_period_seconds": int(
            getattr(settings, "asset_storage_cleanup_grace_period_seconds", 86_400)
        ),
        "integrity_max_blob_read_bytes": int(
            getattr(settings, "asset_storage_integrity_max_blob_read_bytes", 8 * 1024 * 1024)
        ),
    }


def _storage_governance_config(settings) -> dict[str, object]:
    return {
        "backup_policy_configured": bool(
            getattr(settings, "asset_storage_backup_policy_configured", False)
        ),
        "object_lifecycle_policy_configured": bool(
            getattr(settings, "asset_storage_object_lifecycle_policy_configured", False)
        ),
    }
