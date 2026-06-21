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
    production_readiness = _storage_production_readiness(
        backend=backend,
        configured=configured,
        ready=ready,
        migration_runner_required=migration_runner_required,
        backup_policy_configured=backup_policy_configured,
        object_lifecycle_policy_configured=object_lifecycle_policy_configured,
        maintenance_enabled=maintenance_enabled,
        cleanup_apply_enabled=cleanup_apply_enabled,
        s3_region_configured=bool(settings.asset_storage_s3_region),
    )
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
            and cleanup_apply_enabled
            and migration_runner_required
        ),
        "hosted_team_production_ready": (
            backend == "s3"
            and ready
            and configured
            and backup_policy_configured
            and object_lifecycle_policy_configured
            and maintenance_enabled
            and cleanup_apply_enabled
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
        "production_readiness": production_readiness,
    }


def _storage_production_readiness(
    *,
    backend: str,
    configured: bool,
    ready: bool,
    migration_runner_required: bool,
    backup_policy_configured: bool,
    object_lifecycle_policy_configured: bool,
    maintenance_enabled: bool,
    cleanup_apply_enabled: bool,
    s3_region_configured: bool,
) -> dict[str, Any]:
    requirement_status = {
        "asset_storage_configured": configured,
        "asset_storage_ready": ready,
        "s3_compatible_backend": backend == "s3",
        "external_migration_runner": migration_runner_required,
        "backup_policy": backup_policy_configured,
        "object_lifecycle_policy": object_lifecycle_policy_configured,
        "maintenance_worker": maintenance_enabled,
        "cleanup_apply": cleanup_apply_enabled,
        "s3_region": s3_region_configured,
    }
    self_host_requirements = (
        "asset_storage_configured",
        "asset_storage_ready",
        "external_migration_runner",
        "backup_policy",
        "maintenance_worker",
        "cleanup_apply",
    )
    hosted_team_requirements = (
        "asset_storage_configured",
        "asset_storage_ready",
        "s3_compatible_backend",
        "external_migration_runner",
        "backup_policy",
        "object_lifecycle_policy",
        "maintenance_worker",
        "cleanup_apply",
        "s3_region",
    )
    return {
        "schema_version": "asset-storage-production-readiness-v1",
        "requirement_status": requirement_status,
        "self_host": _target_readiness(
            requirement_status=requirement_status,
            requirement_names=self_host_requirements,
        ),
        "hosted_team": _target_readiness(
            requirement_status=requirement_status,
            requirement_names=hosted_team_requirements,
        ),
    }


def _target_readiness(
    *,
    requirement_status: dict[str, bool],
    requirement_names: tuple[str, ...],
) -> dict[str, Any]:
    blocking = [
        requirement
        for requirement in requirement_names
        if requirement_status.get(requirement) is not True
    ]
    return {
        "production_ready": not blocking,
        "blocking_requirements": blocking,
        "operator_actions": _operator_actions(blocking),
    }


def _operator_actions(blocking_requirements: list[str]) -> list[str]:
    actions_by_requirement = {
        "asset_storage_configured": "configure_asset_storage_backend",
        "asset_storage_ready": "fix_asset_storage_health",
        "s3_compatible_backend": "use_s3_compatible_asset_storage",
        "external_migration_runner": "disable_auto_schema_and_run_migrations",
        "backup_policy": "configure_asset_storage_backup_policy",
        "object_lifecycle_policy": "configure_s3_object_lifecycle_policy",
        "maintenance_worker": "enable_asset_storage_maintenance_worker",
        "cleanup_apply": "enable_asset_storage_cleanup_apply",
        "s3_region": "configure_s3_region",
    }
    actions: list[str] = []
    for requirement in blocking_requirements:
        action = actions_by_requirement.get(requirement)
        if action and action not in actions:
            actions.append(action)
    return actions
