"""Capabilities API."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_capture
from infinity_context_server.composition import Container
from infinity_context_server.diagnostics import storage_diagnostics
from infinity_context_server.extraction_capabilities import build_extraction_capability_payload

router = APIRouter(tags=["capabilities"], dependencies=[Depends(require_service_token)])


@router.get("/capabilities")
async def capabilities(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_capabilities.execute()
    return {
        "api_version": "v1",
        "server_version": "0.1.0",
        "service_name": result.service_name,
        "deploy_profile": result.deploy_profile,
        "policy_mode": result.policy_mode,
        "adapters": {adapter.name: asdict(adapter) for adapter in result.adapters},
        "capabilities": [_capability_payload(capability) for capability in result.capabilities],
        "enabled_adapters": [
            adapter.name for adapter in result.adapters if adapter.enabled and adapter.healthy
        ],
        "supports_qdrant": any(adapter.name == "qdrant" for adapter in result.adapters),
        "supports_graphiti": any(adapter.name == "graphiti" for adapter in result.adapters),
        "supports_cognee": any(adapter.name == "cognee" for adapter in result.adapters),
        "supports_legacy_client_routes": container.settings.legacy_client_enabled,
        "captures": {
            "enabled": container.settings.capture_mode.value not in {"off", "retrieve_only"}
            and should_capture(container),
            "api_version": 1,
            "modes": ["off", "retrieve_only", "capture_only", "suggest", "auto_apply_safe"],
            "mode": container.settings.capture_mode.value,
            "auto_apply_safe_enabled": (
                container.settings.capture_mode.value == "auto_apply_safe"
                and container.settings.auto_apply_safe_enabled
            ),
            "raw_payload_storage": False,
            "external_provider_egress": container.settings.capture_external_ai_enabled,
            "taxonomy_version": "memory-taxonomy-v1",
            "client_minimization_supported": True,
            "hook_stdout_context_supported": True,
            "max_pending_per_memory_scope": (
                container.settings.max_pending_captures_per_memory_scope
            ),
            "ingress_limit_code": "memory.capture.ingress_limited",
        },
        "suggestions": {
            "review_tool_supported": True,
            "expiry_supported": True,
            "max_pending_per_memory_scope": (
                container.settings.max_pending_suggestions_per_memory_scope
            ),
        },
        "storage": _storage_payload(container),
        "extraction": build_extraction_capability_payload(container.settings),
        "plans": {
            "current": container.settings.product_plan_tier,
            "resources": {
                "asset_storage_bytes_per_memory_scope": {
                    "limit": container.settings.plan_asset_storage_bytes_per_memory_scope,
                    "unlimited_when_zero": True,
                    "scope": "memory_scope",
                },
                "media_analysis_seconds": {
                    "limit_per_month": (container.settings.plan_media_analysis_seconds_per_month),
                    "free_default_seconds": 10 * 60 * 60,
                    "free_default_hours": 10,
                }
            },
        },
        "supported_policy_modes": list(result.supported_policy_modes),
        "supported_embedding_models": [container.settings.embeddings_model],
        "limits": result.limits,
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


def _storage_payload(container: Container) -> dict[str, Any]:
    settings = container.settings
    backend = settings.asset_storage_backend
    diagnostics = storage_diagnostics(container)
    return {
        "asset_backend": backend,
        "asset_backend_configured": backend == "local" or bool(settings.asset_storage_s3_bucket),
        "asset_external": backend == "s3",
        "s3": {
            "bucket_configured": bool(settings.asset_storage_s3_bucket),
            "prefix_configured": bool(settings.asset_storage_s3_prefix.strip()),
            "endpoint_configured": bool(settings.asset_storage_s3_endpoint_url),
            "region_configured": bool(settings.asset_storage_s3_region),
            "force_path_style": settings.asset_storage_s3_force_path_style,
        },
        "deployment_readiness": _storage_deployment_readiness(
            container,
            diagnostics=diagnostics,
        ),
    }


def _storage_deployment_readiness(
    container: Container,
    *,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    settings = container.settings
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
    return {
        "schema_version": "asset-storage-deployment-readiness-v1",
        "status": "ok" if ready and configured else "misconfigured",
        "self_host_ready": ready and configured,
        "hosted_team_ready": backend == "s3" and ready and configured,
        "self_host_production_ready": (
            ready and configured and backup_policy_configured and maintenance_enabled
        ),
        "hosted_team_production_ready": (
            backend == "s3"
            and ready
            and configured
            and backup_policy_configured
            and object_lifecycle_policy_configured
            and maintenance_enabled
        ),
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
