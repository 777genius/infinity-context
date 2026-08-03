from __future__ import annotations

from copy import deepcopy

import pytest
from infinity_context_server.memory_comparison_mem0_contract import (
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION,
    MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
    evaluate_mem0_openapi_contract,
    evaluate_mem0_runtime_capabilities,
    public_mem0_runtime_manifest,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
    REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
)


def test_mem0_openapi_contract_accepts_canonical_adapter_schema() -> None:
    payload = _valid_openapi()

    result = evaluate_mem0_openapi_contract(payload, require_timestamp=True)

    assert result["violations"] == ()
    assert len(result["fingerprint_sha256"]) == 64
    reordered = {
        "components": payload["components"],
        "paths": dict(reversed(tuple(payload["paths"].items()))),
    }
    assert (
        evaluate_mem0_openapi_contract(
            reordered,
            require_timestamp=True,
        )["fingerprint_sha256"]
        == result["fingerprint_sha256"]
    )


def test_mem0_exact_openapi_contract_reports_semantic_drift() -> None:
    payload = _valid_openapi()
    del payload["paths"]["/health"]["get"]
    del payload["components"]["schemas"]["AddRequest"]["properties"]["timestamp"]
    payload["components"]["schemas"]["SearchRequest"]["additionalProperties"] = True
    payload["paths"]["/memories"]["delete"]["parameters"] = []

    result = evaluate_mem0_openapi_contract(payload, require_timestamp=True)

    assert result["violations"] == (
        "missing_operation:get:/health",
        "missing_request_field:post:/memories:timestamp",
        "request_allows_unknown_fields:post:/search",
        "request_field_type_mismatch:post:/memories:timestamp:integer",
        "missing_query_parameter:delete:/memories:run_id",
        "missing_query_parameter:delete:/memories:user_id",
    )


def test_mem0_openapi_contract_rejects_delete_response_drift() -> None:
    payload = _valid_openapi()
    delete_schema = payload["paths"]["/memories"]["delete"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    delete_schema["required"] = ["deleted"]
    delete_schema["properties"]["deleted"] = {"type": "string"}
    delete_schema["properties"]["trace"] = {"type": "string"}
    delete_schema["additionalProperties"] = True

    violations = evaluate_mem0_openapi_contract(
        payload,
        require_timestamp=True,
    )["violations"]

    assert violations == (
        "response_field_type_mismatch:delete:/memories:deleted:boolean",
        "response_field_not_required:delete:/memories:verified_absent",
        "unexpected_response_fields:delete:/memories",
        "response_allows_unknown_fields:delete:/memories",
    )


def test_mem0_openapi_contract_rejects_required_type_and_envelope_drift() -> None:
    payload = _valid_openapi()
    add = payload["components"]["schemas"]["AddRequest"]
    search = payload["components"]["schemas"]["SearchRequest"]
    add["required"] = []
    add["properties"]["messages"] = {"type": "object"}
    add["properties"]["timestamp"] = {"type": "string"}
    search["required"] = ["query"]
    search["properties"]["query"] = {"type": "array"}
    search["properties"]["filters"] = {"type": "array"}
    search["properties"]["limit"] = {"type": "string"}
    payload["components"]["schemas"]["AddResponse"]["required"] = []
    payload["components"]["schemas"]["SearchResponse"]["properties"]["results"] = {"type": "object"}
    delete_parameters = payload["paths"]["/memories"]["delete"]["parameters"]
    delete_parameters[0]["required"] = False
    delete_parameters[1]["schema"] = {"type": "integer"}

    violations = evaluate_mem0_openapi_contract(
        payload,
        require_timestamp=True,
    )["violations"]

    assert "request_field_not_required:post:/memories:messages" in violations
    assert "request_field_type_mismatch:post:/memories:messages:array" in violations
    assert "request_field_not_required:post:/memories:timestamp" in violations
    assert "request_field_type_mismatch:post:/memories:timestamp:integer" in violations
    assert "request_field_not_required:post:/search:filters" in violations
    assert "request_field_type_mismatch:post:/search:query:string" in violations
    assert "request_field_type_mismatch:post:/search:filters:object" in violations
    assert "request_field_not_required:post:/search:limit" in violations
    assert "request_field_type_mismatch:post:/search:limit:integer" in violations
    assert "response_field_not_required:post:/memories:results" in violations
    assert "response_field_type_mismatch:post:/search:results:array" in violations
    assert "query_parameter_not_required:delete:/memories:user_id" in violations
    assert "query_parameter_type_mismatch:delete:/memories:run_id:string" in violations


def test_mem0_runtime_capabilities_require_pinned_native_timestamp_runtime() -> None:
    payload = _valid_capabilities()

    assert (
        evaluate_mem0_runtime_capabilities(
            payload,
            require_timestamp=True,
        )
        == ()
    )

    payload["mem0_source_revision"] = "feat/v3-pipeline"
    payload["timestamp"]["sdk_forwarding_supported"] = False
    payload["timestamp"]["readback_supported"] = False

    assert evaluate_mem0_runtime_capabilities(
        payload,
        require_timestamp=True,
    ) == (
        "mem0_source_revision_unpinned",
        "timestamp_sdk_forwarding_not_supported",
        "timestamp_readback_not_supported",
    )


@pytest.mark.parametrize("version", ("invalid", "2", "2.0", "2.0.0 secret", "v2.0.0"))
def test_runtime_capability_evaluator_rejects_invalid_package_versions(version: str) -> None:
    payload = _valid_capabilities()
    payload["mem0_package_version"] = version

    issues = evaluate_mem0_runtime_capabilities(payload, require_timestamp=True)

    assert "mem0_package_version_invalid" in issues


def test_public_mem0_runtime_manifest_drops_unknown_or_sensitive_fields() -> None:
    payload = {
        **_valid_capabilities(),
        "api_key": "secret",
        "environment": {"OPENAI_API_KEY": "secret"},
    }

    public = public_mem0_runtime_manifest(payload)

    assert "api_key" not in public
    assert "environment" not in public
    assert public["schema_version"] == MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION


def test_managed_platform_runtime_requires_observed_exact_sdk_artifact() -> None:
    payload = _valid_managed_capabilities()

    assert evaluate_mem0_runtime_capabilities(payload, require_timestamp=True) == ()

    mutations = (
        (("sdk", "version"), "2.0.13", "sdk_version_mismatch"),
        (("sdk", "source_revision"), "d" * 40, "sdk_source_revision_mismatch"),
        (("sdk", "artifact_sha256"), "e" * 64, "sdk_artifact_sha256_mismatch"),
        (
            ("sdk", "verification", "observed_sha256"),
            "f" * 64,
            "sdk_verification_observed_mismatch",
        ),
        (("sdk", "verification", "passed"), False, "sdk_verification_not_passed"),
        (
            ("sdk", "verification", "method"),
            "declared_constant",
            "sdk_verification_method_invalid",
        ),
    )
    for path, value, expected_issue in mutations:
        candidate = deepcopy(payload)
        target = candidate
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert expected_issue in evaluate_mem0_runtime_capabilities(
            candidate,
            require_timestamp=True,
        )


def test_public_managed_manifest_keeps_only_safe_verification_evidence() -> None:
    payload = _valid_managed_capabilities()
    payload["sdk"]["verification"].update(
        {
            "url": "file:///private/wheel.whl",
            "path": "/private/wheel.whl",
            "api_key": "secret",
        }
    )

    public = public_mem0_runtime_manifest(payload)

    assert public["sdk"]["verification"] == {
        "method": "direct_url_archive_info_sha256",
        "observed_sha256": ("9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"),
        "passed": True,
    }
    assert "private" not in str(public)
    assert "secret" not in str(public)


def test_public_manifest_never_reflects_arbitrary_values_from_allowed_fields() -> None:
    payload = _valid_managed_capabilities()
    secret = "operator-token-value"
    payload["runtime_mode"] = secret
    payload["sdk"]["distribution"] = secret
    payload["platform"]["api_origin"] = secret
    payload["timestamp"]["attestation"]["failure_code"] = secret

    public = public_mem0_runtime_manifest(payload)

    assert secret not in str(public)
    assert public["runtime_mode"] == "invalid"
    assert public["sdk"]["distribution"] == "invalid"
    assert public["platform"]["api_origin"] == "invalid"
    assert public["timestamp"]["attestation"]["failure_code"] == "invalid"


def _valid_capabilities() -> dict[str, object]:
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION,
        "runtime_mode": "oss",
        "wrapper_source_sha256": "a" * 64,
        "mem0_source_revision": "b" * 40,
        "mem0_package_version": "2.0.12",
        "config_fingerprint_sha256": "c" * 64,
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "readback_supported": True,
        },
    }


def _valid_managed_capabilities() -> dict[str, object]:
    artifact_sha256 = "9c567df69af794278bc051400829d1a2d4f8aa659cae6cd019d88ec66dbf4f3f"
    return {
        "schema_version": MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
        "runtime_mode": "managed_platform",
        "wrapper_source_sha256": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_SHA256,
        "wrapper_source_revision": REVIEWED_MEM0_MANAGED_WRAPPER_SOURCE_REVISION,
        "config_fingerprint_sha256": "c" * 64,
        "sdk": {
            "distribution": "mem0ai",
            "version": "2.0.14",
            "source_revision": "b357a5a1b03c299ec8229c268e63cfac0f7c6566",
            "artifact_sha256": artifact_sha256,
            "verification": {
                "method": "direct_url_archive_info_sha256",
                "observed_sha256": artifact_sha256,
                "passed": True,
            },
        },
        "platform": {
            "api_origin": "https://api.mem0.ai",
            "api_generation": "v3",
            "add_path": "/v3/memories/add/",
            "search_path": "/v3/memories/search/",
            "event_path_template": "/v1/event/{event_id}/",
            "server_source_revision": None,
            "server_revision_attestable": False,
        },
        "persisted_source_identity": {
            "request_metadata_required": True,
            "source_filtered_readback_supported": True,
            "source_id_roundtrip_attested": True,
            "source_sha256_roundtrip_attested": True,
            "sanitized_identity_response": True,
        },
        "timestamp": {
            "request_supported": True,
            "sdk_forwarding_supported": True,
            "event_completion_supported": True,
            "readback_supported": True,
            "attestation": {
                "status": "passed",
                "checked_at": "2026-07-29T10:00:00Z",
                "probe_mode": "live_sentinel",
                "input_epoch_seconds": 1672531200,
                "expected_created_at": "2023-01-01T00:00:00Z",
                "event_terminal_status": "SUCCEEDED",
                "readback_result_count": 1,
                "persisted_created_at": "2023-01-01T00:00:00Z",
                "delta_seconds": 0.0,
                "cleanup_succeeded": True,
                "failure_code": None,
            },
        },
    }


def _valid_openapi() -> dict[str, object]:
    return {
        "paths": {
            "/health": {"get": {"responses": {"200": {}}}},
            "/memories": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/AddRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AddResponse"}
                                }
                            }
                        }
                    },
                },
                "delete": {
                    "parameters": [
                        {
                            "name": "user_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "run_id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "deleted": {"type": "boolean"},
                                            "verified_absent": {"type": "boolean"},
                                        },
                                        "required": ["deleted", "verified_absent"],
                                    }
                                }
                            }
                        }
                    },
                },
            },
            "/search": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/SearchRequest"}
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/SearchResponse"}
                                }
                            }
                        }
                    },
                }
            },
            "/benchmark/capabilities": {"get": {"responses": {"200": {}}}},
        },
        "components": {
            "schemas": {
                "AddRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "messages": {"type": "array"},
                        "user_id": {"type": ["string", "null"]},
                        "run_id": {"type": ["string", "null"]},
                        "metadata": {"type": ["object", "null"]},
                        "timestamp": {"type": "integer"},
                    },
                    "required": ["messages", "timestamp"],
                },
                "SearchRequest": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string"},
                        "filters": {"type": "object"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query", "filters", "limit"],
                },
                "AddResponse": {
                    "type": "object",
                    "properties": {"results": {"type": "array", "items": {}}},
                    "required": ["results"],
                },
                "SearchResponse": {
                    "type": "object",
                    "properties": {"results": {"type": "array", "items": {}}},
                    "required": ["results"],
                },
            }
        },
    }
