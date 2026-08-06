"""Provider-neutral structured-output policy for benchmark judge calls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence


def locomo_judge_response_format() -> dict[str, object]:
    """Return a fresh exact strict-schema request, independent of any provider."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "locomo_judge",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "reasoning": {"type": "string"},
                    "label": {"type": "string", "enum": ["CORRECT", "WRONG"]},
                },
                "required": ["reasoning", "label"],
                "additionalProperties": False,
            },
        },
    }


def normalized_supported_response_format(
    value: Mapping[str, object],
) -> dict[str, object]:
    """Validate and snapshot the two response formats supported by the bridge."""

    snapshot = _snapshot(value)
    if _same_exact_json(snapshot, {"type": "json_object"}):
        return {"type": "json_object"}
    expected = locomo_judge_response_format()
    if _same_exact_json(snapshot, expected):
        return expected
    raise ValueError("response format is unsupported")


def locomo_judge_response_format_policy() -> dict[str, object]:
    """Describe the explicit official-to-strict judge normalization contract."""

    normalized = locomo_judge_response_format()
    schema = normalized["json_schema"]["schema"]
    return {
        "policy_id": "locomo-official-json-object-to-strict-schema.v1",
        "benchmark": "locomo",
        "stage": "judge",
        "source_response_format": {"type": "json_object"},
        "normalized_response_format": normalized,
        "canonical_schema_sha256": _canonical_json_sha256(schema),
        "backend_roles": ["infinity-context", "mem0"],
        "backend_application": "identical",
    }


def locomo_judge_response_format_policy_sha256() -> str:
    """Return the stable canonical hash of the complete normalization policy."""

    return _canonical_json_sha256(locomo_judge_response_format_policy())


def _snapshot(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("response format keys must be strings")
        return {key: _snapshot(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_snapshot(item) for item in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ValueError("response format contains unsupported values")


def _same_exact_json(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(
            _same_exact_json(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _same_exact_json(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _canonical_json_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = (
    "locomo_judge_response_format",
    "locomo_judge_response_format_policy",
    "locomo_judge_response_format_policy_sha256",
    "normalized_supported_response_format",
)
