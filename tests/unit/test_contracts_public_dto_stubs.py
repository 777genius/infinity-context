from __future__ import annotations

import json

import infinity_context_contracts as contracts
from infinity_context_contracts import (
    CapabilitiesResponseDto,
    ErrorDto,
    ErrorResponseDto,
    HealthResponseDto,
    ResponseEnvelopeDto,
)


CURRENT_CAPABILITIES_TOP_LEVEL_KEYS = {
    "api_version",
    "server_version",
    "service_name",
    "deploy_profile",
    "policy_mode",
    "adapters",
    "capabilities",
    "enabled_adapters",
    "supports_qdrant",
    "supports_graphiti",
    "supports_cognee",
    "supports_legacy_client_routes",
    "captures",
    "suggestions",
    "context",
    "storage",
    "extraction",
    "plans",
    "supported_policy_modes",
    "supported_embedding_models",
    "limits",
}


def test_contracts_package_exports_public_dtos() -> None:
    assert contracts.ErrorDto is ErrorDto
    assert contracts.ErrorResponseDto is ErrorResponseDto
    assert contracts.ResponseEnvelopeDto is ResponseEnvelopeDto
    assert contracts.HealthResponseDto is HealthResponseDto
    assert contracts.CapabilitiesResponseDto is CapabilitiesResponseDto


def test_common_error_and_envelope_dtos_serialize_to_plain_json_dicts() -> None:
    error = ErrorDto(
        code="memory.validation",
        message="Request validation failed",
        retryable=False,
        details={"fields": ("memory_scope_id", "text")},
    )

    assert error.to_dict() == {
        "code": "memory.validation",
        "message": "Request validation failed",
        "retryable": False,
        "details": {"fields": ["memory_scope_id", "text"]},
    }
    assert ErrorResponseDto(error=error).to_dict() == {"error": error.to_dict()}

    envelope = ResponseEnvelopeDto(
        data={"id": "fact_1", "tags": ("profile", "manual")},
        meta={"request_id": "req_1"},
    )
    payload = envelope.to_dict()

    assert payload == {
        "data": {"id": "fact_1", "tags": ["profile", "manual"]},
        "error": None,
        "meta": {"request_id": "req_1"},
    }
    json.dumps(payload, sort_keys=True)


def test_health_response_dto_matches_public_health_fields() -> None:
    payload = HealthResponseDto(
        status="ok",
        service="infinity-context",
        deploy_profile="test",
    ).to_dict()

    assert payload == {
        "status": "ok",
        "service": "infinity-context",
        "deploy_profile": "test",
    }
    json.dumps(payload, sort_keys=True)


def test_capabilities_response_dto_covers_current_top_level_shape() -> None:
    dto = CapabilitiesResponseDto(
        service_name="infinity-context",
        deploy_profile="test",
        policy_mode="active_context",
        adapters={
            "qdrant": {
                "enabled": False,
                "healthy": False,
                "supports_search": True,
            }
        },
        capabilities=(
            {
                "adapter_name": "qdrant",
                "capability": "vector_recall",
                "status": "disabled",
                "healthy": False,
            },
        ),
        captures={"enabled": True, "modes": ("off", "retrieve_only", "capture_only")},
        suggestions={"review_tool_supported": True},
        context={
            "api_version": 1,
            "source_text_policy": "untrusted_evidence",
        },
        storage={
            "asset_backend": "local",
            "deployment_readiness": {
                "status": "ok",
                "warnings": ("database_migration_runner_required",),
            },
        },
        extraction={
            "enabled": True,
            "experimental_nested": {"kept_as_extension_map": True},
        },
        plans={"current": "free"},
        supported_policy_modes=("manual_only", "active_context", "disabled"),
        supported_embedding_models=("text-embedding-3-small",),
        limits={"max_context_tokens": 1800},
        extensions={"future_public_section": {"enabled": True}},
    )

    payload = dto.to_dict()

    assert set(payload) == CURRENT_CAPABILITIES_TOP_LEVEL_KEYS | {"future_public_section"}
    assert payload["api_version"] == "v1"
    assert payload["server_version"] == "0.1.0"
    assert payload["adapters"]["qdrant"]["enabled"] is False
    assert payload["capabilities"][0]["capability"] == "vector_recall"
    assert payload["captures"]["modes"] == ["off", "retrieve_only", "capture_only"]
    assert payload["storage"]["deployment_readiness"]["warnings"] == [
        "database_migration_runner_required"
    ]
    assert payload["extraction"]["experimental_nested"] == {
        "kept_as_extension_map": True
    }
    assert payload["future_public_section"] == {"enabled": True}
    json.dumps(payload, sort_keys=True)
