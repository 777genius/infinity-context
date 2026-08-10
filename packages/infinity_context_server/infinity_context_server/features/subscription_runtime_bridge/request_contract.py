"""Canonical request admission and durable intent derivation."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from .contracts import (
    BridgeAuthority,
    BridgeCallBinding,
    BridgeIntent,
    BridgeIntentError,
    BridgePoolAuthority,
)
from .json_boundary import canonical_json_bytes, exact_object, strict_canonical_json_object
from .response_format_contract import response_format_identity

_REQUEST_REQUIRED = frozenset({"messages", "model"})
_REQUEST_OPTIONAL = frozenset(
    {
        "max_completion_tokens",
        "max_tokens",
        "n",
        "response_format",
        "stream",
        "temperature",
        "tool_choice",
        "tools",
    }
)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def canonical_openai_request_body(value: object) -> bytes:
    """Render the exact bytes accepted by this boundary."""

    return canonical_json_bytes(value)


def derive_bridge_intent(
    *,
    pool: BridgePoolAuthority,
    binding: BridgeCallBinding,
    request_body: bytes,
    maximum_request_bytes: int,
) -> tuple[BridgeAuthority, BridgeIntent]:
    request = strict_canonical_json_object(
        request_body,
        maximum_bytes=maximum_request_bytes,
    )
    exact_object(
        request,
        required=_REQUEST_REQUIRED,
        optional=_REQUEST_OPTIONAL,
        label="bridge_request",
    )
    bridge = pool.select(binding)
    _validate_request(request, bridge)
    response_format_type, response_format_sha256, response_schema_sha256 = response_format_identity(
        request.get("response_format")
    )
    messages = request["messages"]
    intent = BridgeIntent(
        binding=binding,
        pool_id=pool.pool_id,
        pool_authority_sha256=pool.commitment_sha256,
        bridge_id=bridge.bridge_id,
        bridge_authority_sha256=bridge.commitment_sha256,
        request_body_sha256=hashlib.sha256(request_body).hexdigest(),
        prompt_input_sha256=hashlib.sha256(canonical_json_bytes(messages)).hexdigest(),
        response_format_type=response_format_type,
        response_format_sha256=response_format_sha256,
        response_schema_sha256=response_schema_sha256,
        output_token_limit=_output_token_limit(request),
    )
    return bridge, intent


def _validate_request(request: dict[str, Any], bridge: BridgeAuthority) -> None:
    if request["model"] != bridge.public_model:
        raise BridgeIntentError("bridge_request_public_model_invalid")
    _validate_messages(request["messages"])
    if "stream" in request and request["stream"] is not False:
        raise BridgeIntentError("bridge_request_streaming_invalid")
    if "n" in request and (type(request["n"]) is not int or request["n"] != 1):
        raise BridgeIntentError("bridge_request_choice_count_invalid")
    if "tools" in request and request["tools"] != []:
        raise BridgeIntentError("bridge_request_tools_invalid")
    if "tool_choice" in request and request["tool_choice"] != "none":
        raise BridgeIntentError("bridge_request_tool_choice_invalid")
    if "temperature" in request:
        temperature = request["temperature"]
        if type(temperature) not in {int, float}:
            raise BridgeIntentError("bridge_request_temperature_invalid")
        try:
            finite = math.isfinite(temperature)
        except OverflowError as exc:
            raise BridgeIntentError("bridge_request_temperature_invalid") from exc
        if not finite:
            raise BridgeIntentError("bridge_request_temperature_invalid")
    if "response_format" in request and request["response_format"] is None:
        raise BridgeIntentError("bridge_response_format_invalid")
    _output_token_limit(request)


def _validate_messages(value: object) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise BridgeIntentError("bridge_request_messages_invalid")
    for message_value in value:
        message = exact_object(
            message_value,
            required=frozenset({"role"}),
            optional=frozenset({"content", "name"}),
            label="bridge_message",
        )
        if message["role"] not in {"system", "user", "assistant", "tool"}:
            raise BridgeIntentError("bridge_message_role_invalid")
        name = message.get("name")
        if name is not None and (not isinstance(name, str) or not name):
            raise BridgeIntentError("bridge_message_name_invalid")
        content = message.get("content")
        if content is None or isinstance(content, str):
            continue
        if not isinstance(content, list) or not content:
            raise BridgeIntentError("bridge_message_content_invalid")
        for part_value in content:
            part = exact_object(
                part_value,
                required=frozenset({"text", "type"}),
                label="bridge_message_part",
            )
            if part["type"] != "text" or not isinstance(part["text"], str):
                raise BridgeIntentError("bridge_message_part_invalid")


def _output_token_limit(request: dict[str, Any]) -> int:
    maximum = request.get("max_tokens")
    completion_maximum = request.get("max_completion_tokens")
    if "max_tokens" not in request and "max_completion_tokens" not in request:
        raise BridgeIntentError("bridge_request_output_token_limit_required")
    for key, value in (
        ("max_tokens", maximum),
        ("max_completion_tokens", completion_maximum),
    ):
        if key in request and (type(value) is not int or not 1 <= value <= _MAX_SAFE_INTEGER):
            raise BridgeIntentError("bridge_request_output_token_limit_invalid")
    if maximum is not None and completion_maximum is not None and maximum != completion_maximum:
        raise BridgeIntentError("bridge_request_output_token_limits_diverge")
    return completion_maximum if completion_maximum is not None else maximum


__all__ = ("canonical_openai_request_body", "derive_bridge_intent")
