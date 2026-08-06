from __future__ import annotations

import json
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes


class StrictSchemaError(ValueError):
    pass


LOCOMO_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "label": {"type": "string", "enum": ["CORRECT", "WRONG"]},
    },
    "required": ["reasoning", "label"],
    "additionalProperties": False,
}
LOCOMO_JUDGE_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "locomo_judge",
        "strict": True,
        "schema": LOCOMO_JUDGE_SCHEMA,
    },
}
LOCOMO_RESPONSE_FORMAT_SHA256 = "812938567c7a81bac6ed3266608adf470dedc57706102e039422f695495322bf"
LOCOMO_RESPONSE_SCHEMA_SHA256 = "2461f7a465be82aa67751dc04e0717cde75c69b86e7db54bb306a2e3d1d4d8f0"
LOCOMO_RESPONSE_FORMAT_POLICY_SHA256 = (
    "9d7bcc89f3e8cc3683a18d83d90d6ffde05cdb02358d1cd055bf273f92a772f1"
)


def parse_locomo_judge(text: str) -> dict[str, str]:
    decoder = json.JSONDecoder()
    candidate = text.lstrip(" \t\r\n")
    try:
        value, end = decoder.raw_decode(candidate)
    except json.JSONDecodeError as exc:
        raise StrictSchemaError("judge output is not one JSON object") from exc
    if candidate[end:].strip(" \t\r\n"):
        raise StrictSchemaError("judge output contains trailing content")
    if not isinstance(value, dict) or set(value) != {"reasoning", "label"}:
        raise StrictSchemaError("judge output has missing or additional properties")
    if not isinstance(value["reasoning"], str):
        raise StrictSchemaError("reasoning must be a string")
    if value["label"] not in ("CORRECT", "WRONG"):
        raise StrictSchemaError("label must be CORRECT or WRONG")
    return value


def validate_locomo_request(
    request: dict[str, Any],
    *,
    policy_sha256: str,
    model: str,
    requested_output_tokens: int,
) -> None:
    if type(request) is not dict:
        raise StrictSchemaError("LoCoMo request must be an exact object")
    response_format = request.get("response_format")
    if not _same_exact_json(response_format, LOCOMO_JUDGE_RESPONSE_FORMAT):
        raise StrictSchemaError("LoCoMo request requires the exact strict response format")
    if sha256_bytes(canonical_json_bytes(response_format)) != LOCOMO_RESPONSE_FORMAT_SHA256:
        raise StrictSchemaError("LoCoMo response format identity drifted")
    schema = response_format["json_schema"]["schema"]
    if sha256_bytes(canonical_json_bytes(schema)) != LOCOMO_RESPONSE_SCHEMA_SHA256:
        raise StrictSchemaError("LoCoMo response schema identity drifted")
    if type(policy_sha256) is not str or policy_sha256 != LOCOMO_RESPONSE_FORMAT_POLICY_SHA256:
        raise StrictSchemaError("LoCoMo response-format policy identity drifted")
    if type(request.get("model")) is not str or request.get("model") != model:
        raise StrictSchemaError("LoCoMo request model drifted")
    if (
        type(request.get("max_tokens")) is not int
        or request.get("max_tokens") != requested_output_tokens
    ):
        raise StrictSchemaError("LoCoMo requested output limit drifted")
    if request.get("temperature") != 0 or type(request.get("temperature")) is not int:
        raise StrictSchemaError("LoCoMo temperature must be exact integer zero")


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
