"""Capabilities API."""

import importlib.util
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import should_capture
from memo_stack_server.composition import Container

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
        "extraction": {
            "enabled": container.settings.extraction_enabled,
            "default_profile": container.settings.extraction_default_profile,
            "profiles": [
                "standard_local",
                "standard_docling",
                "standard_vision",
                "media_api",
                "media_local_asr",
                "standard_asr",
                "standard_full",
            ],
            "optional_extras": {
                "docling": {
                    "installed": _module_available("docling"),
                    "profiles": ["standard_docling", "standard_full"],
                },
                "vision": {
                    "installed": _module_available("openai"),
                    "configured": (
                        container.settings.extraction_external_ai_enabled
                        and bool(container.settings.openai_api_key)
                    ),
                    "profiles": ["standard_vision", "standard_full"],
                    "model": container.settings.extraction_vision_model,
                    "detail": container.settings.extraction_vision_detail,
                },
                "transcription_api": {
                    "installed": _module_available("openai"),
                    "configured": (
                        container.settings.transcription_provider == "openai"
                        and container.settings.extraction_external_ai_enabled
                        and bool(container.settings.openai_api_key)
                    ),
                    "provider": container.settings.transcription_provider,
                    "profiles": ["media_api", "standard_asr", "standard_full"],
                    "model": container.settings.transcription_openai_model,
                    "max_provider_upload_bytes": (
                        container.settings.transcription_openai_max_upload_bytes
                    ),
                },
                "transcription_local": {
                    "installed": _module_available("faster_whisper"),
                    "profiles": ["media_local_asr", "asr:<model>", "faster_whisper:<model>"],
                    "model": container.settings.extraction_asr_model,
                    "device": container.settings.extraction_asr_device,
                    "compute_type": container.settings.extraction_asr_compute_type,
                    "default": False,
                },
                "asr": {
                    "deprecated": True,
                    "replacement_profiles": ["media_api", "media_local_asr"],
                },
            },
            "external_provider_egress": container.settings.extraction_external_ai_enabled,
            "limits": {
                "max_bytes": container.settings.extraction_max_bytes,
                "max_pages": container.settings.extraction_max_pages,
                "max_media_seconds": container.settings.extraction_max_media_seconds,
                "max_output_chars": container.settings.extraction_max_output_chars,
                "max_tables": container.settings.extraction_max_tables,
                "ocr_enabled": container.settings.extraction_ocr_enabled,
            },
        },
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


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
