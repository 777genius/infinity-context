"""Conservative exact subset of the runtime's structured-output policy."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .contracts import BridgeIntentError
from .json_boundary import canonical_json_bytes, exact_object

_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALLOWED_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "description",
        "enum",
        "items",
        "properties",
        "required",
        "type",
    }
)
_MAX_SCHEMA_DEPTH = 8
_MAX_SCHEMA_PROPERTIES = 100
_MAX_CANONICAL_SCHEMA_BYTES = 64 * 1024
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def response_format_identity(value: object) -> tuple[str, str, str | None]:
    """Validate an identity-stable subset and reproduce runtime semantic hashes."""

    if value is None:
        text = {"type": "text"}
        return "text", hashlib.sha256(canonical_json_bytes(text)).hexdigest(), None
    response_format = exact_object(
        value,
        required=frozenset({"type"}),
        optional=frozenset({"json_schema"}),
        label="bridge_response_format",
    )
    if response_format["type"] == "text" and "json_schema" not in response_format:
        text = {"type": "text"}
        return "text", hashlib.sha256(canonical_json_bytes(text)).hexdigest(), None
    if response_format["type"] != "json_schema" or "json_schema" not in response_format:
        raise BridgeIntentError("bridge_response_format_invalid")
    json_schema = exact_object(
        response_format["json_schema"],
        required=frozenset({"name", "schema", "strict"}),
        label="bridge_json_schema",
    )
    name = json_schema["name"]
    schema = json_schema["schema"]
    if (
        not isinstance(name, str)
        or _NAME.fullmatch(name) is None
        or json_schema["strict"] is not True
        or not isinstance(schema, dict)
    ):
        raise BridgeIntentError("bridge_json_schema_invalid")
    _reject_float_values(response_format)
    _validate_schema_node(schema, depth=0, root=True)
    schema_bytes = _runtime_canonical_json_bytes(schema)
    if len(schema_bytes) > _MAX_CANONICAL_SCHEMA_BYTES:
        raise BridgeIntentError("bridge_json_schema_too_large")
    return (
        "json_schema",
        hashlib.sha256(_runtime_canonical_json_bytes(response_format)).hexdigest(),
        hashlib.sha256(schema_bytes).hexdigest(),
    )


def _validate_schema_node(value: object, *, depth: int, root: bool) -> None:
    if not isinstance(value, dict) or depth > _MAX_SCHEMA_DEPTH:
        raise BridgeIntentError("bridge_json_schema_malformed")
    if any(key not in _ALLOWED_SCHEMA_KEYS for key in value):
        raise BridgeIntentError("bridge_json_schema_keyword_unsupported")
    schema_type = value.get("type")
    if not isinstance(schema_type, str) or schema_type not in _ALLOWED_SCHEMA_TYPES:
        raise BridgeIntentError("bridge_json_schema_type_unsupported")
    if root and schema_type != "object":
        raise BridgeIntentError("bridge_json_schema_root_invalid")
    if "description" in value and not isinstance(value["description"], str):
        raise BridgeIntentError("bridge_json_schema_description_invalid")
    if schema_type == "object":
        _validate_object_schema(value, depth=depth)
    elif schema_type == "array":
        _reject_present(value, {"additionalProperties", "enum", "properties", "required"})
        if "items" not in value:
            raise BridgeIntentError("bridge_json_schema_array_items_required")
        _validate_schema_node(value["items"], depth=depth + 1, root=False)
    else:
        _reject_present(value, {"additionalProperties", "items", "properties", "required"})
        if "enum" in value:
            _validate_primitive_enum(value["enum"], schema_type=schema_type)


def _validate_object_schema(value: dict[str, Any], *, depth: int) -> None:
    properties = value.get("properties")
    required = value.get("required")
    if (
        not isinstance(properties, dict)
        or value.get("additionalProperties") is not False
        or not isinstance(required, list)
    ):
        raise BridgeIntentError("bridge_json_schema_object_shape_invalid")
    _reject_present(value, {"enum", "items"})
    property_names = list(properties)
    if len(property_names) > _MAX_SCHEMA_PROPERTIES:
        raise BridgeIntentError("bridge_json_schema_properties_too_large")
    if (
        any(not isinstance(item, str) for item in required)
        or len(set(required)) != len(required)
        or len(required) != len(property_names)
        or any(name not in required for name in property_names)
    ):
        raise BridgeIntentError("bridge_json_schema_required_invalid")
    for property_schema in properties.values():
        _validate_schema_node(property_schema, depth=depth + 1, root=False)


def _validate_primitive_enum(value: object, *, schema_type: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise BridgeIntentError("bridge_json_schema_enum_invalid")
    for item in value:
        if schema_type == "string" and isinstance(item, str):
            continue
        if schema_type == "boolean" and type(item) is bool:
            continue
        if schema_type == "null" and item is None:
            continue
        if (
            schema_type in {"integer", "number"}
            and type(item) is int
            and -_MAX_SAFE_INTEGER <= item <= _MAX_SAFE_INTEGER
        ):
            continue
        raise BridgeIntentError("bridge_json_schema_enum_invalid")


def _reject_present(value: dict[str, Any], keys: set[str]) -> None:
    if any(key in value for key in keys):
        raise BridgeIntentError("bridge_json_schema_keyword_combination_unsupported")


def _reject_float_values(value: object) -> None:
    """Use a subset whose Python and JavaScript number identities are exact."""

    if isinstance(value, float):
        raise BridgeIntentError("bridge_response_format_float_identity_unsupported")
    if isinstance(value, list):
        for item in value:
            _reject_float_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_float_values(item)


def _runtime_canonical_json_bytes(value: object) -> bytes:
    """Match canonicalValue plus JSON.stringify, including UTF-16 key ordering."""

    ordered = _runtime_canonical_value(value)
    try:
        return json.dumps(
            ordered,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BridgeIntentError("bridge_response_format_identity_invalid") from exc


def _runtime_canonical_value(value: object) -> object:
    if isinstance(value, list):
        return [_runtime_canonical_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {key: _runtime_canonical_value(value[key]) for key in sorted(value, key=_utf16_sort_key)}


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


__all__ = ("response_format_identity",)
