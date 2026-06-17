"""Capabilities API."""

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import should_capture
from memo_stack_server.composition import Container
from memo_stack_server.extraction_capabilities import build_extraction_capability_payload

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
        "extraction": build_extraction_capability_payload(container.settings),
        "plans": {
            "current": container.settings.product_plan_tier,
            "resources": {
                "media_analysis_seconds": {
                    "limit_per_month": (
                        container.settings.plan_media_analysis_seconds_per_month
                    ),
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
