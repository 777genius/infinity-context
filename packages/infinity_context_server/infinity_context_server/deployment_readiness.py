"""Deployment readiness helpers for server-facing diagnostics."""

from __future__ import annotations

from typing import Any

from infinity_context_server.config import Settings


def build_storage_deployment_readiness(
    *,
    settings: Settings,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    backend = settings.asset_storage_backend
    configured = diagnostics.get("configured") is True
    ready = diagnostics.get("ready") is True
    maintenance = diagnostics.get("maintenance")
    maintenance_payload = maintenance if isinstance(maintenance, dict) else {}
    governance = diagnostics.get("governance")
    governance_payload = governance if isinstance(governance, dict) else {}
    maintenance_enabled = maintenance_payload.get("enabled") is True
    cleanup_apply_enabled = maintenance_payload.get("cleanup_apply_enabled") is True
    backup_policy_configured = governance_payload.get("backup_policy_configured") is True
    object_lifecycle_policy_configured = (
        governance_payload.get("object_lifecycle_policy_configured") is True
    )
    degraded_reasons: list[str] = []
    warnings: list[str] = []
    if not configured:
        degraded_reasons.append("asset_storage_not_configured")
    if not ready:
        degraded_reasons.append("asset_storage_not_ready")
    if backend == "local":
        warnings.append("hosted_team_deployments_should_use_s3_compatible_storage")
    if not backup_policy_configured:
        warnings.append("asset_storage_backup_policy_not_confirmed")
    if backend == "s3" and not object_lifecycle_policy_configured:
        warnings.append("s3_object_lifecycle_policy_not_confirmed")
    if not maintenance_enabled:
        warnings.append("asset_storage_maintenance_not_enabled")
    if maintenance_enabled and not cleanup_apply_enabled:
        warnings.append("asset_storage_cleanup_apply_disabled")
    if backend == "s3" and not settings.asset_storage_s3_region:
        warnings.append("s3_region_not_configured")
    auto_create_schema_enabled = bool(settings.auto_create_schema)
    schema_management_mode = (
        "auto_create"
        if auto_create_schema_enabled
        else "external_migration_runner"
    )
    migration_runner_required = not auto_create_schema_enabled
    if migration_runner_required:
        warnings.append("database_migration_runner_required")
    return {
        "schema_version": "asset-storage-deployment-readiness-v2",
        "status": "ok" if ready and configured else "misconfigured",
        "self_host_ready": ready and configured,
        "hosted_team_ready": backend == "s3" and ready and configured,
        "self_host_production_ready": (
            ready
            and configured
            and backup_policy_configured
            and maintenance_enabled
            and migration_runner_required
        ),
        "hosted_team_production_ready": (
            backend == "s3"
            and ready
            and configured
            and backup_policy_configured
            and object_lifecycle_policy_configured
            and maintenance_enabled
            and migration_runner_required
        ),
        "schema_management_mode": schema_management_mode,
        "auto_create_schema_enabled": auto_create_schema_enabled,
        "auto_create_schema_allowed_in_server_profile": False,
        "migration_runner_required": migration_runner_required,
        "migration_runner_service": "infinity_context_migrate",
        "migration_strategy": "external_forward_migrations",
        "recommended_hosted_backend": "s3",
        "blob_identity": "sha256",
        "duplicate_detection": "exact_sha256",
        "scope_storage_quota_enforced": (
            settings.plan_asset_storage_bytes_per_memory_scope > 0
        ),
        "scope_storage_quota_bytes": settings.plan_asset_storage_bytes_per_memory_scope,
        "scope_storage_quota_unlimited_when_zero": True,
        "storage_cleanup_supported": True,
        "maintenance_enabled": maintenance_enabled,
        "cleanup_apply_enabled": cleanup_apply_enabled,
        "backup_policy_configured": backup_policy_configured,
        "object_lifecycle_policy_configured": object_lifecycle_policy_configured,
        "safe_diagnostics": True,
        "degraded_reasons": degraded_reasons,
        "warnings": warnings,
    }
