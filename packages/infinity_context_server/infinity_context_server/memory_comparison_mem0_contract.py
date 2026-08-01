"""Pure contract validation for a publishable Mem0 comparison runtime."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_mem0_platform_contract import (
    MANAGED_PLATFORM_CAPABILITY_ISSUE_CODES,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    evaluate_managed_platform_capabilities as _evaluate_managed_platform_capabilities,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    public_managed_persisted_source_identity_contract as _public_source_identity_contract,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    public_managed_platform_contract as _public_platform_contract,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    public_managed_refresh_binding as _public_refresh_binding,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    public_managed_sdk_contract as _public_sdk_contract,
)
from infinity_context_server.memory_comparison_mem0_platform_contract import (
    public_managed_timestamp_contract as _public_timestamp_contract,
)

MEM0_BENCHMARK_CAPABILITIES_PATH = "/benchmark/capabilities"
MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V1 = "mem0-benchmark-capabilities.v1"
MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2 = "mem0-benchmark-capabilities.v2"
MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION = MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_PACKAGE_VERSION_RE = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}(?:[.+-][0-9A-Za-z.-]{1,32})?$")
_OPENAPI_OPERATIONS = (
    ("/health", "get"),
    ("/memories", "delete"),
    ("/memories", "post"),
    ("/search", "post"),
)
_OPENAPI_REQUEST_FIELDS = {
    ("/memories", "post"): ("messages", "user_id", "run_id", "metadata", "timestamp"),
    ("/search", "post"): ("query", "filters", "limit"),
}
PUBLIC_MEM0_OPENAPI_VIOLATIONS = frozenset(
    {
        *{f"missing_operation:{method}:{path}" for path, method in _OPENAPI_OPERATIONS},
        *{
            f"missing_request_field:{method}:{path}:{field}"
            for (path, method), fields in _OPENAPI_REQUEST_FIELDS.items()
            for field in fields
        },
        "request_allows_unknown_fields:post:/memories",
        "request_allows_unknown_fields:post:/search",
        "request_field_not_required:post:/memories:messages",
        "request_field_not_required:post:/memories:timestamp",
        "request_field_not_required:post:/search:query",
        "request_field_not_required:post:/search:filters",
        "request_field_not_required:post:/search:limit",
        "request_field_type_mismatch:post:/memories:messages:array",
        "request_field_type_mismatch:post:/memories:timestamp:integer",
        "request_field_type_mismatch:post:/search:query:string",
        "request_field_type_mismatch:post:/search:filters:object",
        "request_field_type_mismatch:post:/search:limit:integer",
        "response_field_not_required:post:/memories:results",
        "response_field_not_required:post:/search:results",
        "response_field_not_required:delete:/memories:deleted",
        "response_field_not_required:delete:/memories:verified_absent",
        "response_field_type_mismatch:post:/memories:results:array",
        "response_field_type_mismatch:post:/search:results:array",
        "response_field_type_mismatch:delete:/memories:deleted:boolean",
        "response_field_type_mismatch:delete:/memories:verified_absent:boolean",
        "unexpected_response_fields:delete:/memories",
        "response_allows_unknown_fields:delete:/memories",
        "missing_query_parameter:delete:/memories:run_id",
        "missing_query_parameter:delete:/memories:user_id",
        "query_parameter_not_required:delete:/memories:run_id",
        "query_parameter_not_required:delete:/memories:user_id",
        "query_parameter_type_mismatch:delete:/memories:run_id:string",
        "query_parameter_type_mismatch:delete:/memories:user_id:string",
    }
)
MEM0_RUNTIME_CAPABILITY_ISSUE_CODES = frozenset(
    {
        "runtime_manifest_missing",
        "runtime_manifest_schema_version_mismatch",
        "runtime_mode_not_oss",
        "wrapper_source_sha256_invalid",
        "mem0_source_revision_unpinned",
        "mem0_package_version_missing",
        "mem0_package_version_invalid",
        "config_fingerprint_sha256_invalid",
        "timestamp_request_not_supported",
        "timestamp_sdk_forwarding_not_supported",
        "timestamp_readback_not_supported",
        *MANAGED_PLATFORM_CAPABILITY_ISSUE_CODES,
    }
)


def evaluate_mem0_openapi_contract(
    payload: object,
    *,
    require_timestamp: bool,
) -> dict[str, object]:
    """Return bounded semantic violations plus an observed projection fingerprint."""

    violations: list[str] = []
    required_operations = (
        ("/health", "get"),
        ("/memories", "delete"),
        ("/memories", "post"),
        ("/search", "post"),
    )
    for path, method in required_operations:
        if not _openapi_operation(payload, path=path, method=method):
            violations.append(f"missing_operation:{method}:{path}")

    required_fields = {
        ("/memories", "post"): {"messages", "user_id", "run_id", "metadata"},
        ("/search", "post"): {"query", "filters", "limit"},
    }
    if require_timestamp:
        required_fields[("/memories", "post")].add("timestamp")
    for (path, method), expected in required_fields.items():
        actual = _openapi_request_properties(payload, path=path, method=method)
        for field_name in sorted(expected.difference(actual)):
            violations.append(f"missing_request_field:{method}:{path}:{field_name}")

    for path, method in (("/memories", "post"), ("/search", "post")):
        schema = _openapi_request_schema(payload, path=path, method=method)
        if schema and schema.get("additionalProperties") is not False:
            violations.append(f"request_allows_unknown_fields:{method}:{path}")

    canonical_request_fields = {
        ("/memories", "post"): {"messages": "array"},
        ("/search", "post"): {
            "query": "string",
            "filters": "object",
            "limit": "integer",
        },
    }
    if require_timestamp:
        canonical_request_fields[("/memories", "post")]["timestamp"] = "integer"
    for (path, method), fields in canonical_request_fields.items():
        schema = _openapi_request_schema(payload, path=path, method=method)
        required = _openapi_required_names(schema)
        properties = _openapi_schema_properties(schema)
        for field_name, expected_type in fields.items():
            if field_name not in required:
                violations.append(f"request_field_not_required:{method}:{path}:{field_name}")
            if not _openapi_schema_has_type(properties.get(field_name), expected_type):
                violations.append(
                    f"request_field_type_mismatch:{method}:{path}:{field_name}:{expected_type}"
                )

    for path, method in (("/memories", "post"), ("/search", "post")):
        schema = _openapi_response_schema(payload, path=path, method=method)
        required = _openapi_required_names(schema)
        properties = _openapi_schema_properties(schema)
        if "results" not in required:
            violations.append(f"response_field_not_required:{method}:{path}:results")
        if not _openapi_schema_has_type(properties.get("results"), "array"):
            violations.append(f"response_field_type_mismatch:{method}:{path}:results:array")

    delete_parameters = _openapi_query_parameters(payload, path="/memories", method="delete")
    delete_schema = _openapi_response_schema(payload, path="/memories", method="delete")
    delete_required = _openapi_required_names(delete_schema)
    delete_properties = _openapi_schema_properties(delete_schema)
    for field_name in ("deleted", "verified_absent"):
        if field_name not in delete_required:
            violations.append(f"response_field_not_required:delete:/memories:{field_name}")
        if not _openapi_schema_has_type(delete_properties.get(field_name), "boolean"):
            violations.append(f"response_field_type_mismatch:delete:/memories:{field_name}:boolean")
    unexpected_delete_fields = set(delete_properties).difference({"deleted", "verified_absent"})
    if unexpected_delete_fields:
        violations.append("unexpected_response_fields:delete:/memories")
    if delete_schema and delete_schema.get("additionalProperties") is not False:
        violations.append("response_allows_unknown_fields:delete:/memories")
    for field_name in ("run_id", "user_id"):
        parameter = delete_parameters.get(field_name)
        if parameter is None:
            violations.append(f"missing_query_parameter:delete:/memories:{field_name}")
            continue
        if parameter.get("required") is not True:
            violations.append(f"query_parameter_not_required:delete:/memories:{field_name}")
        if not _openapi_schema_has_type(parameter.get("schema"), "string"):
            violations.append(f"query_parameter_type_mismatch:delete:/memories:{field_name}:string")

    canonical = _benchmark_openapi_projection(payload)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return {
        "fingerprint_sha256": hashlib.sha256(encoded).hexdigest(),
        "violations": tuple(violations),
    }


def evaluate_mem0_runtime_capabilities(
    payload: object,
    *,
    require_timestamp: bool,
) -> tuple[str, ...]:
    """Validate provenance without conflating request, forwarding and persistence."""

    if not isinstance(payload, Mapping):
        return ("runtime_manifest_missing",)
    schema_version = payload.get("schema_version")
    if schema_version == MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2:
        return _evaluate_managed_platform_capabilities(
            payload,
            require_timestamp=require_timestamp,
        )

    issues: list[str] = []
    if schema_version != MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V1:
        issues.append("runtime_manifest_schema_version_mismatch")
    if payload.get("runtime_mode") != "oss":
        issues.append("runtime_mode_not_oss")
    if not _SHA256_RE.fullmatch(str(payload.get("wrapper_source_sha256") or "")):
        issues.append("wrapper_source_sha256_invalid")
    if not _REVISION_RE.fullmatch(str(payload.get("mem0_source_revision") or "")):
        issues.append("mem0_source_revision_unpinned")
    package_version = payload.get("mem0_package_version")
    if not isinstance(package_version, str) or not package_version.strip():
        issues.append("mem0_package_version_missing")
    elif _PACKAGE_VERSION_RE.fullmatch(package_version) is None:
        issues.append("mem0_package_version_invalid")
    if not _SHA256_RE.fullmatch(str(payload.get("config_fingerprint_sha256") or "")):
        issues.append("config_fingerprint_sha256_invalid")

    timestamp = payload.get("timestamp")
    timestamp_contract = timestamp if isinstance(timestamp, Mapping) else {}
    if require_timestamp:
        if timestamp_contract.get("request_supported") is not True:
            issues.append("timestamp_request_not_supported")
        if timestamp_contract.get("sdk_forwarding_supported") is not True:
            issues.append("timestamp_sdk_forwarding_not_supported")
        if timestamp_contract.get("readback_supported") is not True:
            issues.append("timestamp_readback_not_supported")
    return tuple(issues)


def mem0_openapi_request_properties(
    payload: object,
    *,
    path: str,
    method: str,
) -> frozenset[str]:
    """Expose request fields without leaking OpenAPI traversal into HTTP adapters."""

    return _openapi_request_properties(payload, path=path, method=method)


def public_mem0_runtime_manifest(payload: object) -> dict[str, object]:
    """Keep only sanitized fields suitable for benchmark artifacts."""

    if not isinstance(payload, Mapping):
        return {}
    public = _public_runtime_scalars(payload)
    sdk = payload.get("sdk")
    if isinstance(sdk, Mapping):
        public["sdk"] = _public_sdk_contract(sdk)
    platform = payload.get("platform")
    if isinstance(platform, Mapping):
        public["platform"] = _public_platform_contract(platform)
    persisted_source_identity = payload.get("persisted_source_identity")
    if isinstance(persisted_source_identity, Mapping):
        public["persisted_source_identity"] = _public_source_identity_contract(
            persisted_source_identity
        )
    refresh_binding = payload.get("refresh_binding")
    if isinstance(refresh_binding, Mapping):
        public["refresh_binding"] = _public_refresh_binding(refresh_binding)
    timestamp = payload.get("timestamp")
    if isinstance(timestamp, Mapping):
        public["timestamp"] = _public_timestamp_contract(timestamp)
    return public


def _public_runtime_scalars(payload: Mapping[str, object]) -> dict[str, object]:
    public: dict[str, object] = {}
    schema_version = payload.get("schema_version")
    if "schema_version" in payload:
        public["schema_version"] = (
            schema_version
            if schema_version
            in {
                MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V1,
                MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2,
            }
            else "invalid"
        )
    runtime_mode = payload.get("runtime_mode")
    if "runtime_mode" in payload:
        public["runtime_mode"] = (
            runtime_mode if runtime_mode in {"oss", "managed_platform"} else "invalid"
        )
    for field_name in ("wrapper_source_sha256", "config_fingerprint_sha256"):
        if field_name in payload:
            public[field_name] = _public_pattern(payload.get(field_name), _SHA256_RE)
    for field_name in ("wrapper_source_revision", "mem0_source_revision"):
        if field_name in payload:
            public[field_name] = _public_pattern(payload.get(field_name), _REVISION_RE)
    if "mem0_package_version" in payload:
        public["mem0_package_version"] = _public_pattern(
            payload.get("mem0_package_version"),
            _PACKAGE_VERSION_RE,
        )
    return public


def _public_pattern(value: object, pattern: re.Pattern[str]) -> str:
    return value if isinstance(value, str) and pattern.fullmatch(value) else "invalid"


def _benchmark_openapi_projection(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return {}
    projected_paths = {
        path: paths[path]
        for path in (
            "/memories",
            "/search",
            "/health",
            MEM0_BENCHMARK_CAPABILITIES_PATH,
        )
        if path in paths
    }
    components = payload.get("components")
    return {
        "paths": projected_paths,
        "components": components if isinstance(components, Mapping) else {},
    }


def _openapi_operation(
    payload: object,
    *,
    path: str,
    method: str,
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return {}
    path_item = paths.get(path)
    if not isinstance(path_item, Mapping):
        return {}
    operation = path_item.get(method.casefold())
    return operation if isinstance(operation, Mapping) else {}


def _openapi_request_properties(
    payload: object,
    *,
    path: str,
    method: str,
) -> frozenset[str]:
    schema = _openapi_request_schema(payload, path=path, method=method)
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if not isinstance(properties, Mapping):
        return frozenset()
    return frozenset(str(item) for item in properties)


def _openapi_request_schema(
    payload: object,
    *,
    path: str,
    method: str,
) -> Mapping[str, object]:
    operation = _openapi_operation(payload, path=path, method=method)
    request_body = operation.get("requestBody")
    if not isinstance(request_body, Mapping):
        return {}
    content = request_body.get("content")
    if not isinstance(content, Mapping):
        return {}
    media = content.get("application/json")
    if not isinstance(media, Mapping):
        return {}
    return _resolve_openapi_schema(payload, media.get("schema"))


def _openapi_query_parameters(
    payload: object,
    *,
    path: str,
    method: str,
) -> dict[str, Mapping[str, object]]:
    operation = _openapi_operation(payload, path=path, method=method)
    parameters = operation.get("parameters")
    if not isinstance(parameters, Sequence) or isinstance(parameters, str | bytes):
        return {}
    return {
        str(parameter.get("name")): parameter
        for parameter in parameters
        if isinstance(parameter, Mapping) and parameter.get("in") == "query"
    }


def _openapi_response_schema(
    payload: object,
    *,
    path: str,
    method: str,
) -> Mapping[str, object]:
    operation = _openapi_operation(payload, path=path, method=method)
    responses = operation.get("responses")
    response = responses.get("200") if isinstance(responses, Mapping) else None
    content = response.get("content") if isinstance(response, Mapping) else None
    media = content.get("application/json") if isinstance(content, Mapping) else None
    if not isinstance(media, Mapping):
        return {}
    return _resolve_openapi_schema(payload, media.get("schema"))


def _openapi_required_names(schema: Mapping[str, object]) -> frozenset[str]:
    required = schema.get("required")
    if not isinstance(required, Sequence) or isinstance(required, str | bytes):
        return frozenset()
    return frozenset(str(item) for item in required)


def _openapi_schema_properties(schema: Mapping[str, object]) -> Mapping[str, object]:
    properties = schema.get("properties")
    return properties if isinstance(properties, Mapping) else {}


def _openapi_schema_has_type(schema: object, expected: str) -> bool:
    if not isinstance(schema, Mapping):
        return False
    return schema.get("type") == expected


def _resolve_openapi_schema(
    payload: object,
    schema: object,
) -> Mapping[str, object]:
    if not isinstance(payload, Mapping) or not isinstance(schema, Mapping):
        return {}
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
        return schema
    components = payload.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else None
    if not isinstance(schemas, Mapping):
        return {}
    resolved = schemas.get(ref.rsplit("/", 1)[-1])
    return resolved if isinstance(resolved, Mapping) else {}


__all__ = (
    "MEM0_BENCHMARK_CAPABILITIES_PATH",
    "MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION",
    "evaluate_mem0_openapi_contract",
    "evaluate_mem0_runtime_capabilities",
    "mem0_openapi_request_properties",
    "MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V1",
    "MEM0_BENCHMARK_CAPABILITIES_SCHEMA_VERSION_V2",
    "MEM0_RUNTIME_CAPABILITY_ISSUE_CODES",
    "PUBLIC_MEM0_OPENAPI_VIOLATIONS",
    "public_mem0_runtime_manifest",
)
