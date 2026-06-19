"""Production-safe admin and repair commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from infinity_context_adapters.postgres.models import (
    Base,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
)
from infinity_context_core.application import (
    BlobStorageCleanupCommand,
    BlobStorageIntegrityAuditCommand,
    EnsureScopeCommand,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.admin_invariants import invariant_check
from infinity_context_server.admin_outbox import compact_done_outbox, replay_outbox
from infinity_context_server.admin_projection_repair import (
    reindex_graphiti,
    reindex_qdrant,
    repair_projections,
)
from infinity_context_server.auth_tokens import (
    create_service_token,
    list_service_tokens,
    revoke_service_token,
)
from infinity_context_server.composition import build_container
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.memory_scope_transfer import export_memory_scope, import_memory_scope

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


async def seed_defaults() -> dict[str, object]:
    container = build_container(Settings())
    try:
        scope = await container.ensure_scope.execute(
            EnsureScopeCommand(
                space_slug=container.settings.default_space_slug,
                memory_scope_external_ref=container.settings.default_memory_scope_external_ref,
            )
        )
        return {
            "status": "ok",
            "space_id": str(scope.space_id),
            "memory_scope_id": str(scope.memory_scope_id),
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
            remediation="python -m infinity_context_server.doctor",
            doctor_status=str(doctor_result.get("status")),
        ),
        _gate_check(
            "default_scope",
            str(default_scope["status"]),
            remediation="python -m infinity_context_server.admin seed-defaults",
        ),
        _gate_check(
            "outbox_dead_count",
            "ok" if dead_outbox == 0 else "failed",
            remediation=(
                "python -m infinity_context_server.admin replay-outbox --status dead --limit 50"
            ),
            dead=dead_outbox,
            pending=pending_outbox,
        ),
        _gate_check(
            "invariant_check",
            "ok" if invariant_result.get("status") == "ok" else "failed",
            remediation=(
                "python -m infinity_context_server.admin check-invariants --include-projections"
            ),
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
            memory_scope_id = await session.scalar(
                select(MemoryScopeRow.id).where(
                    MemoryScopeRow.space_id == space_id,
                    MemoryScopeRow.external_ref == settings.default_memory_scope_external_ref,
                    MemoryScopeRow.status == "active",
                )
            )
            return {"status": "ok" if memory_scope_id else "failed"}
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
        "graph.invalid_api_key": (
            "replace the Graphiti/OpenAI provider API key and rerun the canary"
        ),
        "graph.rate_limited": "wait for Graphiti/OpenAI provider quota reset",
        "graph.invalid_request": "verify Graphiti LLM provider model and request configuration",
        "graph.provider_unavailable": "retry after Graphiti provider/network recovery",
        "embeddings.disabled": "enable and configure an embedding provider before vector retrieval",
        "embeddings.missing_api_key": "configure the embedding provider API key",
        "embeddings.invalid_api_key": "replace the embedding provider API key and rerun the canary",
        "embeddings.rate_limited": (
            "wait for provider quota reset or switch embedding provider credentials"
        ),
        "embeddings.invalid_request": "verify embedding model name and configured dimensions",
        "embeddings.provider_unavailable": "retry after provider/network recovery",
    }
    return actions.get(degraded_reason, f"inspect {name} adapter configuration and provider logs")


def _doctor_status(checks: list[dict[str, object]]) -> str:
    statuses = {str(check.get("status")) for check in checks}
    if "failed" in statuses:
        return "failed"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


async def token_create(
    *,
    space_id: str | None,
    memory_scope_ids: tuple[str, ...] | None = None,
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
            memory_scope_ids=memory_scope_ids,
            expires_at=parsed_expires_at,
            permissions=permissions,
        )
        return {
            "status": "created",
            "token_id": token.token_id,
            "token": token.token,
            "space_id": token.space_id,
            "memory_scope_ids": list(token.memory_scope_ids)
            if token.memory_scope_ids is not None
            else None,
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
        return {"status": "refused", "reason": "reset-local is forbidden in server deploy profile"}
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


async def export_memory_scope_command(
    *,
    space: str,
    memory_scope: str,
    out: str,
    redacted: bool,
) -> dict[str, object]:
    container = build_container(Settings())
    try:
        return await export_memory_scope(
            engine=container.engine,
            space_slug=space,
            memory_scope_external_ref=memory_scope,
            out_path=Path(out),
            redacted=redacted,
            blob_storage=container.blob_storage,
        )
    finally:
        await container.engine.dispose()


async def import_memory_scope_command(
    *,
    space: str,
    memory_scope: str,
    file: str,
    dry_run: bool,
    merge_strategy: str,
    confirmed: bool = False,
) -> dict[str, object]:
    if not dry_run and not confirmed:
        return {
            "status": "refused",
            "reason": "import-memory_scope requires --i-understand-this-writes-canonical-memory",
        }
    container = build_container(Settings())
    try:
        if dry_run:
            space_id = ""
            memory_scope_id = ""
        else:
            scope = await container.ensure_scope.execute(
                EnsureScopeCommand(space_slug=space, memory_scope_external_ref=memory_scope)
            )
            space_id = str(scope.space_id)
            memory_scope_id = str(scope.memory_scope_id)
        return await import_memory_scope(
            engine=container.engine,
            now=container.clock.now(),
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            in_path=Path(file),
            dry_run=dry_run,
            merge_strategy=merge_strategy,
            blob_storage=container.blob_storage,
        )
    finally:
        await container.engine.dispose()


async def cleanup_asset_storage(
    *,
    prefix: str,
    limit: int,
    max_deletions: int,
    grace_period_seconds: int,
    cursor: str | None,
    apply_changes: bool,
) -> dict[str, object]:
    container = build_container(Settings())
    try:
        result = await container.run_blob_storage_cleanup.execute(
            BlobStorageCleanupCommand(
                storage_backend=container.settings.asset_storage_backend,
                prefix=prefix,
                dry_run=not apply_changes,
                max_objects=limit,
                max_deletions=max_deletions,
                grace_period_seconds=grace_period_seconds,
                cursor=cursor,
            )
        )
        return {
            "status": result.status,
            "operation": "cleanup-asset-storage",
            "dry_run": result.dry_run,
            "storage_backend": result.storage_backend,
            "prefix": result.prefix,
            "scanned_count": result.scanned_count,
            "referenced_count": result.referenced_count,
            "recent_count": result.recent_count,
            "unknown_updated_at_count": result.unknown_updated_at_count,
            "orphan_candidate_count": result.orphan_candidate_count,
            "delete_attempt_count": result.delete_attempt_count,
            "deleted_count": result.deleted_count,
            "delete_error_count": result.delete_error_count,
            "deletion_limit_count": result.deletion_limit_count,
            "next_cursor": result.next_cursor,
            "decisions": [_cleanup_decision_payload(item) for item in result.decisions],
            "diagnostics": result.diagnostics,
        }
    finally:
        await container.engine.dispose()


async def audit_asset_storage(
    *,
    prefix: str,
    limit: int,
    max_blob_read_bytes: int,
    no_checksum: bool,
    assets_only: bool,
    artifacts_only: bool,
) -> dict[str, object]:
    if assets_only and artifacts_only:
        return {
            "status": "refused",
            "reason": "choose only one of --assets-only or --artifacts-only",
        }
    container = build_container(Settings())
    try:
        include_assets = not artifacts_only
        include_artifacts = not assets_only
        result = await container.run_blob_storage_integrity_audit.execute(
            BlobStorageIntegrityAuditCommand(
                storage_backend=container.settings.asset_storage_backend,
                prefix=prefix,
                include_assets=include_assets,
                include_artifacts=include_artifacts,
                verify_checksum=not no_checksum,
                max_references=limit,
                max_blob_read_bytes=max_blob_read_bytes,
            )
        )
        return {
            "status": result.status,
            "operation": "audit-asset-storage",
            "storage_backend": result.storage_backend,
            "prefix": result.prefix,
            "scanned_count": result.scanned_count,
            "ok_count": result.ok_count,
            "missing_count": result.missing_count,
            "byte_size_mismatch_count": result.byte_size_mismatch_count,
            "checksum_mismatch_count": result.checksum_mismatch_count,
            "checksum_skipped_count": result.checksum_skipped_count,
            "read_error_count": result.read_error_count,
            "stat_error_count": result.stat_error_count,
            "issues": [_json_safe_dataclass_payload(item) for item in result.issues],
            "diagnostics": result.diagnostics,
        }
    finally:
        await container.engine.dispose()


def _cleanup_decision_payload(decision: object) -> dict[str, object]:
    return _json_safe_dataclass_payload(decision)


def _json_safe_dataclass_payload(item: object) -> dict[str, object]:
    payload = asdict(item)
    for key, value in tuple(payload.items()):
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
    return payload


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
            memory_scope=args.memory_scope,
            include_projections=args.include_projections,
        )
    if args.command == "repair-projections":
        return await repair_projections(
            space=args.space,
            memory_scope=args.memory_scope,
            dry_run=args.dry_run,
        )
    if args.command == "reindex-qdrant":
        return await reindex_qdrant(
            space=args.space,
            memory_scope=args.memory_scope,
            dry_run=args.dry_run,
            confirmed=args.i_understand_this_enqueues_projection_jobs,
        )
    if args.command == "reindex-graphiti":
        return await reindex_graphiti(
            space=args.space,
            memory_scope=args.memory_scope,
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
    if args.command == "cleanup-asset-storage":
        return await cleanup_asset_storage(
            prefix=args.prefix,
            limit=args.limit,
            max_deletions=args.max_deletions,
            grace_period_seconds=args.grace_period_seconds,
            cursor=args.cursor,
            apply_changes=args.apply,
        )
    if args.command == "audit-asset-storage":
        return await audit_asset_storage(
            prefix=args.prefix,
            limit=args.limit,
            max_blob_read_bytes=args.max_blob_read_bytes,
            no_checksum=args.no_checksum,
            assets_only=args.assets_only,
            artifacts_only=args.artifacts_only,
        )
    if args.command == "token":
        if args.token_command == "create":
            return await token_create(
                space_id=args.space,
                memory_scope_ids=tuple(args.memory_scope) if args.memory_scope else None,
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
    if args.command == "export-memory_scope":
        return await export_memory_scope_command(
            space=args.space,
            memory_scope=args.memory_scope,
            out=args.out,
            redacted=args.redacted,
        )
    if args.command == "import-memory_scope":
        return await import_memory_scope_command(
            space=args.space,
            memory_scope=args.memory_scope,
            file=args.file,
            dry_run=args.dry_run,
            merge_strategy=args.merge_strategy,
            confirmed=args.i_understand_this_writes_canonical_memory,
        )
    raise ValueError(f"Unknown command: {args.command}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Infinity Context admin commands")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed-defaults")
    sub.add_parser("doctor")
    invariant = sub.add_parser("invariant-check")
    invariant.add_argument("--space", default=None)
    invariant.add_argument("--memory_scope", default=None)
    invariant.add_argument("--include-projections", action="store_true")
    check_invariants = sub.add_parser("check-invariants")
    check_invariants.add_argument("--space", default=None)
    check_invariants.add_argument("--memory_scope", default=None)
    check_invariants.add_argument("--include-projections", action="store_true")
    repair = sub.add_parser("repair-projections")
    repair.add_argument("--space", default=None)
    repair.add_argument("--memory_scope", default=None)
    repair.add_argument("--dry-run", action="store_true")
    for command in ("reindex-qdrant", "reindex-graphiti"):
        reindex = sub.add_parser(command)
        reindex.add_argument("--space", default=None)
        reindex.add_argument("--memory_scope", default=None)
        reindex.add_argument("--dry-run", action="store_true")
        reindex.add_argument("--i-understand-this-enqueues-projection-jobs", action="store_true")
    replay = sub.add_parser("replay-outbox")
    replay.add_argument("--status", default="dead")
    replay.add_argument("--limit", type=int, default=50)
    compact = sub.add_parser("compact-outbox")
    compact.add_argument("--older-than-seconds", type=int, default=86_400)
    compact.add_argument("--limit", type=int, default=500)
    compact.add_argument("--dry-run", action="store_true")
    cleanup_storage = sub.add_parser("cleanup-asset-storage")
    cleanup_storage.add_argument("--prefix", default="")
    cleanup_storage.add_argument("--limit", type=int, default=500)
    cleanup_storage.add_argument("--max-deletions", type=int, default=100)
    cleanup_storage.add_argument("--grace-period-seconds", type=int, default=86_400)
    cleanup_storage.add_argument("--cursor", default=None)
    cleanup_storage.add_argument("--apply", action="store_true")
    audit_storage = sub.add_parser("audit-asset-storage")
    audit_storage.add_argument("--prefix", default="")
    audit_storage.add_argument("--limit", type=int, default=100)
    audit_storage.add_argument("--max-blob-read-bytes", type=int, default=64 * 1024 * 1024)
    audit_storage.add_argument("--no-checksum", action="store_true")
    audit_storage.add_argument("--assets-only", action="store_true")
    audit_storage.add_argument("--artifacts-only", action="store_true")
    token = sub.add_parser("token")
    token_sub = token.add_subparsers(dest="token_command", required=True)
    token_create_parser = token_sub.add_parser("create")
    token_create_parser.add_argument("--space", default=None)
    token_create_parser.add_argument(
        "--memory_scope",
        action="append",
        default=[],
        help="Repeatable memory_scope id or external ref for memory_scope-scoped tokens",
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
    export = sub.add_parser("export-memory_scope")
    export.add_argument("--space", required=True)
    export.add_argument("--memory_scope", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--redacted", action="store_true")
    import_parser = sub.add_parser("import-memory_scope")
    import_parser.add_argument("--space", required=True)
    import_parser.add_argument("--memory_scope", required=True)
    import_parser.add_argument("--file", required=True)
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument("--i-understand-this-writes-canonical-memory", action="store_true")
    import_parser.add_argument(
        "--merge-strategy",
        default="fail_on_conflict",
        choices=(
            "fail_on_conflict",
            "skip_existing",
            "create_new_memory_scope",
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
