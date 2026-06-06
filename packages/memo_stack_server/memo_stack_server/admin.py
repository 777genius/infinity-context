"""Production-safe admin and repair commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from memo_stack_adapters.postgres.models import (
    Base,
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
    MemoryProfileRow,
    MemorySourceRefRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)
from memo_stack_core.application import EnsureScopeCommand
from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_server.auth_tokens import (
    create_service_token,
    list_service_tokens,
    revoke_service_token,
)
from memo_stack_server.composition import build_container
from memo_stack_server.config import DeployProfile, Settings
from memo_stack_server.profile_transfer import export_profile, import_profile

ACTIVE_CONTEXT_MANUAL_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "client_fallback_canary",
        "run the client fallback canary in shadow mode and confirm fallback works",
    ),
    (
        "shadow_retrieve_diagnostics",
        "review shadow retrieve diagnostics for leaks, latency, and degradation rate",
    ),
    ("golden_eval", "run golden eval and confirm all gates pass"),
    ("service_token_rotation", "create, use, revoke, and replace a service token"),
    ("kill_switches", "manually verify memory kill switches and fallback mode"),
)
ACTIVE_CONTEXT_MANUAL_CHECK_NAMES = tuple(name for name, _ in ACTIVE_CONTEXT_MANUAL_CHECKS)
SAFE_COMPACTED_OUTBOX_PAYLOAD_KEYS = frozenset(
    {
        "space_id",
        "profile_id",
        "thread_id",
        "fact_id",
        "document_id",
        "chunk_id",
        "episode_id",
        "suggestion_id",
        "version",
    }
)


async def seed_defaults() -> dict[str, object]:
    container = build_container(Settings())
    try:
        scope = await container.ensure_scope.execute(
            EnsureScopeCommand(
                space_slug=container.settings.default_space_slug,
                profile_external_ref=container.settings.default_profile_external_ref,
            )
        )
        return {
            "status": "ok",
            "space_id": str(scope.space_id),
            "profile_id": str(scope.profile_id),
            "thread_id": str(scope.thread_id) if scope.thread_id else None,
        }
    finally:
        await container.engine.dispose()


async def doctor() -> dict[str, object]:
    container = build_container(Settings())
    try:
        capabilities = await container.get_capabilities.execute()
        async with AsyncSession(container.engine) as session:
            await session.execute(text("SELECT 1"))
            pending = await _count_outbox(session, "pending")
            dead = await _count_outbox(session, "dead")
        adapter_checks = [
            _adapter_check(adapter.name, adapter.enabled, adapter.healthy, adapter.degraded_reason)
            for adapter in capabilities.adapters
        ]
        checks = [
            {"name": "postgres", "status": "ok"},
            {"name": "migrations", "status": "ok"},
            {
                "name": "outbox",
                "status": "ok" if dead == 0 else "degraded",
                "pending": pending,
                "dead": dead,
            },
            *adapter_checks,
        ]
        return {
            "status": _doctor_status(checks),
            "checks": checks,
            "adapters": {
                adapter.name: {
                    "enabled": adapter.enabled,
                    "healthy": adapter.healthy,
                    "degraded_reason": adapter.degraded_reason,
                }
                for adapter in capabilities.adapters
            },
            "outbox": {"pending": pending, "dead": dead},
        }
    finally:
        await container.engine.dispose()


async def active_context_readiness_gate(
    *,
    acknowledged_checks: set[str] | None = None,
) -> dict[str, object]:
    acknowledged = acknowledged_checks or set()
    unknown = sorted(acknowledged.difference(ACTIVE_CONTEXT_MANUAL_CHECK_NAMES))
    if unknown:
        return {
            "status": "failed",
            "gate": "active_context",
            "checks": [
                {
                    "name": "manual_acknowledgements",
                    "status": "failed",
                    "unknown": unknown,
                    "remediation": (
                        "use one of the documented active context gate acknowledgement names"
                    ),
                }
            ],
        }

    doctor_result = await doctor()
    invariant_result = await invariant_check(include_projections=True)
    default_scope = await _default_scope_status()

    outbox = doctor_result.get("outbox")
    if not isinstance(outbox, dict):
        outbox = {}
    dead_outbox = int(outbox.get("dead") or 0)
    pending_outbox = int(outbox.get("pending") or 0)

    checks = [
        _gate_check(
            "doctor",
            "ok" if doctor_result.get("status") == "ok" else "failed",
            remediation="python -m memo_stack_server.doctor",
            doctor_status=str(doctor_result.get("status")),
        ),
        _gate_check(
            "default_scope",
            str(default_scope["status"]),
            remediation="python -m memo_stack_server.admin seed-defaults",
        ),
        _gate_check(
            "outbox_dead_count",
            "ok" if dead_outbox == 0 else "failed",
            remediation="python -m memo_stack_server.admin replay-outbox --status dead --limit 50",
            dead=dead_outbox,
            pending=pending_outbox,
        ),
        _gate_check(
            "invariant_check",
            "ok" if invariant_result.get("status") == "ok" else "failed",
            remediation="python -m memo_stack_server.admin check-invariants --include-projections",
            invariant_status=str(invariant_result.get("status")),
            dead_outbox_jobs=int(invariant_result.get("dead_outbox_jobs") or 0),
        ),
    ]
    checks.extend(_manual_gate_checks(acknowledged))

    return {
        "status": _gate_status(checks),
        "gate": "active_context",
        "checks": checks,
        "manual_acknowledgements": sorted(acknowledged),
        "doctor_status": str(doctor_result.get("status")),
        "invariant_status": str(invariant_result.get("status")),
        "outbox": {"pending": pending_outbox, "dead": dead_outbox},
    }


async def _default_scope_status() -> dict[str, object]:
    settings = Settings()
    container = build_container(settings)
    try:
        async with AsyncSession(container.engine) as session:
            space_id = await session.scalar(
                select(MemorySpaceRow.id).where(
                    MemorySpaceRow.slug == settings.default_space_slug,
                    MemorySpaceRow.status == "active",
                )
            )
            if not space_id:
                return {"status": "failed"}
            profile_id = await session.scalar(
                select(MemoryProfileRow.id).where(
                    MemoryProfileRow.space_id == space_id,
                    MemoryProfileRow.external_ref == settings.default_profile_external_ref,
                    MemoryProfileRow.status == "active",
                )
            )
            return {"status": "ok" if profile_id else "failed"}
    finally:
        await container.engine.dispose()


def _manual_gate_checks(acknowledged: set[str]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for name, remediation in ACTIVE_CONTEXT_MANUAL_CHECKS:
        status = "ok" if name in acknowledged else "manual_required"
        checks.append(
            _gate_check(
                name,
                status,
                remediation=remediation,
                acknowledgement_required=name not in acknowledged,
            )
        )
    return checks


def _gate_check(
    name: str,
    status: str,
    *,
    remediation: str,
    **extra: object,
) -> dict[str, object]:
    return {"name": name, "status": status, "remediation": remediation, **extra}


def _gate_status(checks: list[dict[str, object]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "failed" in statuses:
        return "failed"
    if "manual_required" in statuses:
        return "blocked"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


def _adapter_check(
    name: str,
    enabled: bool,
    healthy: bool,
    degraded_reason: str | None,
) -> dict[str, object]:
    if not enabled and degraded_reason == "disabled":
        status = "disabled"
    elif enabled and healthy:
        status = "ok"
    else:
        status = "degraded"
    return {
        "name": name,
        "status": status,
        "enabled": enabled,
        "healthy": healthy,
        "degraded_reason": degraded_reason,
        "provider_version": "unknown",
        "required_action": _adapter_required_action(name, degraded_reason),
    }


def _adapter_required_action(name: str, degraded_reason: str | None) -> str | None:
    if degraded_reason is None or degraded_reason == "disabled":
        return None
    actions = {
        "qdrant.dimension_mismatch": (
            "create a new projection collection or reindex Qdrant with the configured "
            "embedding dimension"
        ),
        "qdrant_sdk_missing": "install the qdrant optional dependency in the memory runtime",
        "qdrant_unavailable": "verify Qdrant URL, credentials and container health",
        "graphiti.capability_mismatch": (
            "verify graphiti-core version and required client methods before enabling "
            "graph retrieval"
        ),
        "graphiti_unavailable": (
            "verify Graphiti dependencies, Neo4j credentials and container health"
        ),
        "embeddings.disabled": "enable and configure an embedding provider before vector retrieval",
        "embeddings.missing_api_key": "configure the embedding provider API key",
    }
    return actions.get(degraded_reason, f"inspect {name} adapter configuration and provider logs")


def _doctor_status(checks: list[dict[str, object]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "failed" in statuses:
        return "failed"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


async def invariant_check(
    *,
    space: str | None = None,
    profile: str | None = None,
    include_projections: bool = False,
) -> dict[str, object]:
    container = build_container(Settings())
    try:
        async with AsyncSession(container.engine) as session:
            scope = await _resolve_scope(session, space=space, profile=profile)
            if (space or profile) and scope is None:
                return {
                    "status": "not_found",
                    "checks": [],
                    "space": space,
                    "profile": profile,
                }
            scope_filters = _scope_filters(scope)
            active_facts = await session.scalar(
                select(func.count())
                .select_from(MemoryFactRow)
                .where(MemoryFactRow.status == "active", *scope_filters.for_model(MemoryFactRow))
            )
            active_chunks = await session.scalar(
                select(func.count())
                .select_from(MemoryChunkRow)
                .where(MemoryChunkRow.status == "active", *scope_filters.for_model(MemoryChunkRow))
            )
            dead = await _count_outbox(session, "dead")
            checks = [
                await _check_active_fact_source_refs(session, scope_filters),
                await _check_active_chunk_parent_exists(session, scope_filters),
                await _check_profile_rows_match_scope(session, scope_filters),
                await _check_deleted_document_has_no_active_chunks(session, scope_filters),
                await _check_idempotency_results_exist(session, scope_filters),
                _check_dead_outbox(dead),
            ]
            if include_projections:
                checks.append(
                    await _check_projection_outbox_aggregates_exist(session, scope_filters)
                )
        failed = [check for check in checks if check["status"] != "ok"]
        active_facts_without_source_refs = next(
            check["count"] for check in checks if check["name"] == "active_fact_source_refs"
        )
        return {
            "status": "ok" if not failed else "failed",
            "space": space,
            "profile": profile,
            "checks": checks,
            "active_facts": int(active_facts or 0),
            "active_facts_without_source_refs": int(active_facts_without_source_refs),
            "active_chunks": int(active_chunks or 0),
            "dead_outbox_jobs": dead,
            "include_projections": include_projections,
        }
    finally:
        await container.engine.dispose()


async def _check_active_fact_source_refs(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(MemoryFactRow.id)
                .outerjoin(
                    MemorySourceRefRow,
                    (MemorySourceRefRow.fact_id == MemoryFactRow.id)
                    & (MemorySourceRefRow.fact_version == MemoryFactRow.version),
                )
                .where(
                    MemoryFactRow.status == "active",
                    MemorySourceRefRow.id.is_(None),
                    *scope_filters.for_model(MemoryFactRow),
                )
                .order_by(MemoryFactRow.id)
                .limit(50)
            )
        ).scalars()
    )
    return _check("active_fact_source_refs", rows)


async def _check_active_chunk_parent_exists(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    document_exists = exists(
        select(MemoryDocumentRow.id).where(MemoryDocumentRow.id == MemoryChunkRow.document_id)
    )
    episode_exists = exists(
        select(MemoryEpisodeRow.id).where(MemoryEpisodeRow.id == MemoryChunkRow.episode_id)
    )
    rows = list(
        (
            await session.execute(
                select(MemoryChunkRow.id)
                .where(
                    MemoryChunkRow.status == "active",
                    or_(
                        and_(
                            MemoryChunkRow.document_id.is_(None),
                            MemoryChunkRow.episode_id.is_(None),
                        ),
                        and_(
                            MemoryChunkRow.document_id.is_not(None),
                            ~document_exists,
                        ),
                        and_(
                            MemoryChunkRow.episode_id.is_not(None),
                            ~episode_exists,
                        ),
                    ),
                    *scope_filters.for_model(MemoryChunkRow),
                )
                .order_by(MemoryChunkRow.id)
                .limit(50)
            )
        ).scalars()
    )
    return _check("active_chunk_parent_exists", rows)


async def _check_profile_rows_match_scope(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    ids: list[str] = []
    for model, prefix in (
        (MemoryFactRow, "fact"),
        (MemoryDocumentRow, "doc"),
        (MemoryChunkRow, "chunk"),
        (MemorySuggestionRow, "suggestion"),
    ):
        ids.extend(
            f"{prefix}:{row_id}"
            for row_id in (
                await session.execute(
                    select(model.id)
                    .outerjoin(
                        MemoryProfileRow,
                        (MemoryProfileRow.id == model.profile_id)
                        & (MemoryProfileRow.space_id == model.space_id),
                    )
                    .where(
                        MemoryProfileRow.id.is_(None),
                        *scope_filters.for_model(model),
                    )
                    .order_by(model.id)
                    .limit(50)
                )
            ).scalars()
        )
    return _check("profile_scoped_rows_match_profile", ids[:50])


async def _check_deleted_document_has_no_active_chunks(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(MemoryChunkRow.id)
                .join(MemoryDocumentRow, MemoryDocumentRow.id == MemoryChunkRow.document_id)
                .where(
                    MemoryChunkRow.status == "active",
                    MemoryDocumentRow.status == "deleted",
                    *scope_filters.for_model(MemoryChunkRow),
                )
                .order_by(MemoryChunkRow.id)
                .limit(50)
            )
        ).scalars()
    )
    return _check("deleted_document_active_chunks", rows)


async def _check_idempotency_results_exist(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(MemoryIdempotencyRecordRow).where(*scope_filters.for_idempotency())
            )
        ).scalars()
    )
    broken: list[str] = []
    for row in rows:
        model = {
            "fact": MemoryFactRow,
            "document": MemoryDocumentRow,
            "episode": MemoryEpisodeRow,
        }.get(row.result_type)
        if model is None:
            broken.append(str(row.id))
            continue
        exists_result = await session.scalar(
            select(func.count()).select_from(model).where(model.id == row.result_id)
        )
        if int(exists_result or 0) == 0:
            broken.append(str(row.id))
    return _check("idempotency_results_exist", broken[:50])


def _check_dead_outbox(dead: int) -> dict[str, object]:
    return {
        "name": "dead_outbox_jobs",
        "status": "ok" if dead == 0 else "failed",
        "count": dead,
        "ids": [],
    }


async def _check_projection_outbox_aggregates_exist(
    session: AsyncSession,
    scope_filters: ScopeFilters,
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(MemoryOutboxRow)
                .where(MemoryOutboxRow.workload_class == "projection")
                .order_by(MemoryOutboxRow.id)
                .limit(500)
            )
        ).scalars()
    )
    broken: list[str] = []
    for row in rows:
        model = _projection_aggregate_model(row.aggregate_type)
        if model is None:
            continue
        exists_any = await session.scalar(
            select(func.count()).select_from(model).where(model.id == row.aggregate_id)
        )
        if int(exists_any or 0) == 0:
            if scope_filters.is_scoped and not scope_filters.matches_payload(row.payload_json):
                continue
            broken.append(f"{row.aggregate_type}:{row.aggregate_id}")
            continue
        if scope_filters.is_scoped:
            exists_scoped = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.id == row.aggregate_id, *scope_filters.for_model(model))
            )
            if int(exists_scoped or 0) == 0:
                continue
    return _check("projection_outbox_aggregate_exists", broken[:50])


def _projection_aggregate_model(
    aggregate_type: str,
) -> (
    type[MemoryFactRow]
    | type[MemoryDocumentRow]
    | type[MemoryChunkRow]
    | type[MemoryEpisodeRow]
    | type[MemoryThreadRow]
    | None
):
    return {
        "fact": MemoryFactRow,
        "document": MemoryDocumentRow,
        "chunk": MemoryChunkRow,
        "episode": MemoryEpisodeRow,
        "thread": MemoryThreadRow,
    }.get(aggregate_type)


def _check(name: str, ids: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "status": "ok" if not ids else "failed",
        "count": len(ids),
        "ids": ids[:20],
    }


class ScopeFilters:
    def __init__(self, *, space_id: str | None, profile_id: str | None) -> None:
        self.space_id = space_id
        self.profile_id = profile_id

    def for_model(self, model) -> list[object]:
        filters = []
        if self.space_id is not None:
            filters.append(model.space_id == self.space_id)
        if self.profile_id is not None:
            filters.append(model.profile_id == self.profile_id)
        return filters

    def for_idempotency(self) -> list[object]:
        if self.space_id is None:
            return []
        return [MemoryIdempotencyRecordRow.space_id == self.space_id]

    @property
    def is_scoped(self) -> bool:
        return self.space_id is not None or self.profile_id is not None

    def matches_payload(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if self.space_id is not None and str(payload.get("space_id")) != self.space_id:
            return False
        if self.profile_id is not None and str(payload.get("profile_id")) != self.profile_id:
            return False
        return self.is_scoped


async def _resolve_scope(
    session: AsyncSession,
    *,
    space: str | None,
    profile: str | None,
) -> tuple[str | None, str | None] | None:
    if space is None and profile is None:
        return (None, None)
    if space is None or profile is None:
        return None
    space_row = (
        await session.execute(select(MemorySpaceRow).where(MemorySpaceRow.slug == space))
    ).scalar_one_or_none()
    if space_row is None:
        return None
    profile_row = (
        await session.execute(
            select(MemoryProfileRow).where(
                MemoryProfileRow.space_id == space_row.id,
                MemoryProfileRow.external_ref == profile,
            )
        )
    ).scalar_one_or_none()
    if profile_row is None:
        return None
    return (space_row.id, profile_row.id)


def _scope_filters(scope: tuple[str | None, str | None] | None) -> ScopeFilters:
    space_id, profile_id = scope or (None, None)
    return ScopeFilters(space_id=space_id, profile_id=profile_id)


async def repair_projections(
    *,
    space: str | None,
    profile: str | None,
    dry_run: bool,
) -> dict[str, object]:
    if not space or not profile:
        return {
            "status": "refused",
            "reason": "repair requires --space and --profile",
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
            scope = await _resolve_scope(session, space=space, profile=profile)
            if scope is None:
                return {
                    "status": "not_found",
                    "space": space,
                    "profile": profile,
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
            "profile": profile,
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
    profile: str | None,
    dry_run: bool,
    confirmed: bool = False,
) -> dict[str, object]:
    return await _reindex_projection(
        operation="reindex-qdrant",
        adapter_key="qdrant",
        aggregate_type="chunk",
        event_type="vector.upsert_chunk",
        space=space,
        profile=profile,
        dry_run=dry_run,
        confirmed=confirmed,
    )


async def reindex_graphiti(
    *,
    space: str | None,
    profile: str | None,
    dry_run: bool,
    confirmed: bool = False,
) -> dict[str, object]:
    return await _reindex_projection(
        operation="reindex-graphiti",
        adapter_key="graphiti",
        aggregate_type="fact",
        event_type="graph.upsert_fact",
        space=space,
        profile=profile,
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
    profile: str | None,
    dry_run: bool,
    confirmed: bool,
) -> dict[str, object]:
    if not space or not profile:
        return {
            "status": "refused",
            "operation": operation,
            "reason": "reindex requires --space and --profile",
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
            scope = await _resolve_scope(session, space=space, profile=profile)
            if scope is None:
                return {
                    "status": "not_found",
                    "operation": operation,
                    "space": space,
                    "profile": profile,
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
                                profile_id=str(row.profile_id),
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
            "profile": profile,
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
    profile_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "space_id": space_id,
        "profile_id": profile_id,
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
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        workload_class="projection",
        fairness_key=f"{aggregate_type}:{aggregate_id}",
        payload_json=payload,
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=now,
        updated_at=now,
    )


async def replay_outbox(*, status: str, limit: int) -> dict[str, object]:
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
                    isinstance(row.payload_json, dict)
                    and row.payload_json.get("compacted") is True
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


async def token_create(
    *,
    space_id: str | None,
    profile_ids: tuple[str, ...] | None = None,
    description: str,
    expires_at: str | None = None,
    permissions: tuple[str, ...] | None = None,
) -> dict[str, object]:
    container = build_container(Settings())
    try:
        parsed_expires_at = _parse_optional_datetime(expires_at)
        token = await create_service_token(
            engine=container.engine,
            now=container.clock.now(),
            token_id=container.ids.new_id("tok"),
            description=description,
            space_id=space_id,
            profile_ids=profile_ids,
            expires_at=parsed_expires_at,
            permissions=permissions,
        )
        return {
            "status": "created",
            "token_id": token.token_id,
            "token": token.token,
            "space_id": token.space_id,
            "profile_ids": list(token.profile_ids) if token.profile_ids is not None else None,
            "description": token.description,
            "permissions": list(token.permissions),
            "expires_at": parsed_expires_at.isoformat() if parsed_expires_at else None,
        }
    finally:
        await container.engine.dispose()


async def token_list(*, space_id: str | None) -> dict[str, object]:
    container = build_container(Settings())
    try:
        return {
            "status": "ok",
            "tokens": await list_service_tokens(engine=container.engine, space_id=space_id),
        }
    finally:
        await container.engine.dispose()


async def token_revoke(*, token_id: str) -> dict[str, object]:
    container = build_container(Settings())
    try:
        return await revoke_service_token(
            engine=container.engine,
            now=container.clock.now(),
            token_id=token_id,
        )
    finally:
        await container.engine.dispose()


async def reset_local(*, confirmed: bool) -> dict[str, object]:
    settings = Settings()
    if settings.deploy_profile == DeployProfile.SERVER:
        return {"status": "refused", "reason": "reset-local is forbidden in server profile"}
    if not confirmed:
        return {
            "status": "refused",
            "reason": "pass --i-understand-this-deletes-local-memory to reset local memory",
        }
    container = build_container(settings)
    try:
        async with container.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        return {"status": "ok", "operation": "reset-local"}
    finally:
        await container.engine.dispose()


async def export_profile_command(
    *,
    space: str,
    profile: str,
    out: str,
    redacted: bool,
) -> dict[str, object]:
    container = build_container(Settings())
    try:
        return await export_profile(
            engine=container.engine,
            space_slug=space,
            profile_external_ref=profile,
            out_path=Path(out),
            redacted=redacted,
        )
    finally:
        await container.engine.dispose()


async def import_profile_command(
    *,
    space: str,
    profile: str,
    file: str,
    dry_run: bool,
    merge_strategy: str,
    confirmed: bool = False,
) -> dict[str, object]:
    if not dry_run and not confirmed:
        return {
            "status": "refused",
            "reason": "import-profile requires --i-understand-this-writes-canonical-memory",
        }
    container = build_container(Settings())
    try:
        if dry_run:
            space_id = ""
            profile_id = ""
        else:
            scope = await container.ensure_scope.execute(
                EnsureScopeCommand(space_slug=space, profile_external_ref=profile)
            )
            space_id = str(scope.space_id)
            profile_id = str(scope.profile_id)
        return await import_profile(
            engine=container.engine,
            now=container.clock.now(),
            space_id=space_id,
            profile_id=profile_id,
            in_path=Path(file),
            dry_run=dry_run,
            merge_strategy=merge_strategy,
        )
    finally:
        await container.engine.dispose()


async def _count_outbox(session: AsyncSession, status: str) -> int:
    return int(
        (
            await session.scalar(
                select(func.count())
                .select_from(MemoryOutboxRow)
                .where(MemoryOutboxRow.status == status)
            )
        )
        or 0
    )


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "seed-defaults":
        return await seed_defaults()
    if args.command == "doctor":
        return await doctor()
    if args.command in {"invariant-check", "check-invariants"}:
        return await invariant_check(
            space=args.space,
            profile=args.profile,
            include_projections=args.include_projections,
        )
    if args.command == "repair-projections":
        return await repair_projections(
            space=args.space,
            profile=args.profile,
            dry_run=args.dry_run,
        )
    if args.command == "reindex-qdrant":
        return await reindex_qdrant(
            space=args.space,
            profile=args.profile,
            dry_run=args.dry_run,
            confirmed=args.i_understand_this_enqueues_projection_jobs,
        )
    if args.command == "reindex-graphiti":
        return await reindex_graphiti(
            space=args.space,
            profile=args.profile,
            dry_run=args.dry_run,
            confirmed=args.i_understand_this_enqueues_projection_jobs,
        )
    if args.command == "replay-outbox":
        return await replay_outbox(status=args.status, limit=args.limit)
    if args.command == "compact-outbox":
        return await compact_done_outbox(
            older_than_seconds=args.older_than_seconds,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    if args.command == "token":
        if args.token_command == "create":
            return await token_create(
                space_id=args.space,
                profile_ids=tuple(args.profile) if args.profile else None,
                description=args.description,
                expires_at=args.expires_at,
                permissions=tuple(args.permission) if args.permission else None,
            )
        if args.token_command == "list":
            return await token_list(space_id=args.space)
        if args.token_command == "revoke":
            return await token_revoke(token_id=args.token_id)
    if args.command == "reset-local":
        return await reset_local(confirmed=args.i_understand_this_deletes_local_memory)
    if args.command == "export-profile":
        return await export_profile_command(
            space=args.space,
            profile=args.profile,
            out=args.out,
            redacted=args.redacted,
        )
    if args.command == "import-profile":
        return await import_profile_command(
            space=args.space,
            profile=args.profile,
            file=args.file,
            dry_run=args.dry_run,
            merge_strategy=args.merge_strategy,
            confirmed=args.i_understand_this_writes_canonical_memory,
        )
    raise ValueError(f"Unknown command: {args.command}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Memo Stack admin commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-defaults")
    sub.add_parser("doctor")
    invariant = sub.add_parser("invariant-check")
    invariant.add_argument("--space", default=None)
    invariant.add_argument("--profile", default=None)
    invariant.add_argument("--include-projections", action="store_true")
    check_invariants = sub.add_parser("check-invariants")
    check_invariants.add_argument("--space", default=None)
    check_invariants.add_argument("--profile", default=None)
    check_invariants.add_argument("--include-projections", action="store_true")
    repair = sub.add_parser("repair-projections")
    repair.add_argument("--space", default=None)
    repair.add_argument("--profile", default=None)
    repair.add_argument("--dry-run", action="store_true")
    for command in ("reindex-qdrant", "reindex-graphiti"):
        reindex = sub.add_parser(command)
        reindex.add_argument("--space", default=None)
        reindex.add_argument("--profile", default=None)
        reindex.add_argument("--dry-run", action="store_true")
        reindex.add_argument("--i-understand-this-enqueues-projection-jobs", action="store_true")
    replay = sub.add_parser("replay-outbox")
    replay.add_argument("--status", default="dead")
    replay.add_argument("--limit", type=int, default=50)
    compact = sub.add_parser("compact-outbox")
    compact.add_argument("--older-than-seconds", type=int, default=86_400)
    compact.add_argument("--limit", type=int, default=500)
    compact.add_argument("--dry-run", action="store_true")
    token = sub.add_parser("token")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_create_parser = token_sub.add_parser("create")
    token_create_parser.add_argument("--space", default=None)
    token_create_parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Repeatable profile id or external ref for profile-scoped tokens",
    )
    token_create_parser.add_argument("--description", required=True)
    token_create_parser.add_argument("--expires-at", default=None)
    token_create_parser.add_argument(
        "--permission",
        action="append",
        default=[],
        help="Repeatable permission, for example memory:read or memory:write",
    )
    token_list_parser = token_sub.add_parser("list")
    token_list_parser.add_argument("--space", default=None)
    token_revoke_parser = token_sub.add_parser("revoke")
    token_revoke_parser.add_argument("--token-id", required=True)
    reset = sub.add_parser("reset-local")
    reset.add_argument("--i-understand-this-deletes-local-memory", action="store_true")
    export = sub.add_parser("export-profile")
    export.add_argument("--space", required=True)
    export.add_argument("--profile", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--redacted", action="store_true")
    import_parser = sub.add_parser("import-profile")
    import_parser.add_argument("--space", required=True)
    import_parser.add_argument("--profile", required=True)
    import_parser.add_argument("--file", required=True)
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument("--i-understand-this-writes-canonical-memory", action="store_true")
    import_parser.add_argument(
        "--merge-strategy",
        default="fail_on_conflict",
        choices=(
            "fail_on_conflict",
            "skip_existing",
            "create_new_profile",
            "supersede_matching_facts",
        ),
    )
    result = asyncio.run(_run(parser.parse_args()))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result.get("status") in {"failed", "refused", "conflict"}:
        sys.exit(1)


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    main()
