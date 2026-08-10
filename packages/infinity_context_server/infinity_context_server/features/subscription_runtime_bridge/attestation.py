"""Schema-v2 runtime receipt verification copied from the public attestation contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

from .contracts import (
    AuthenticatedBridgeResult,
    BridgeAuthority,
    BridgeIntent,
    BridgeReceiptError,
    TokenUsage,
)
from .json_boundary import BridgeJsonError, canonical_json_bytes, exact_object, strict_json_loads

_HEX = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeResponse:
    output_text: str
    response_body_sha256: str
    output_text_sha256: str
    attestation_sha256: str
    receipt_hmac_sha256: str
    thread_id: str
    turn_id: str
    usage: TokenUsage

    def with_encrypted_output(self, encrypted_output: bytes) -> AuthenticatedBridgeResult:
        return AuthenticatedBridgeResult(
            response_body_sha256=self.response_body_sha256,
            output_text_sha256=self.output_text_sha256,
            attestation_sha256=self.attestation_sha256,
            receipt_hmac_sha256=self.receipt_hmac_sha256,
            thread_id=self.thread_id,
            turn_id=self.turn_id,
            usage=self.usage,
            encrypted_output=encrypted_output,
        )


def verify_runtime_response(
    *,
    response_body: bytes,
    maximum_response_bytes: int,
    authority: BridgeAuthority,
    intent: BridgeIntent,
    attestation_secret: bytes,
) -> VerifiedRuntimeResponse:
    """Verify the complete response and public runtime attestation before persistence."""

    _require_attestation_secret(attestation_secret)
    try:
        parsed = strict_json_loads(response_body, maximum_bytes=maximum_response_bytes)
        response = exact_object(
            parsed,
            required=frozenset(
                {
                    "choices",
                    "created",
                    "id",
                    "model",
                    "object",
                    "subscription_runtime",
                    "system_fingerprint",
                    "usage",
                }
            ),
            label="bridge_response",
        )
        output_text = _validate_response_identity(response, authority)
        usage, usage_payload = _validate_usage(response["usage"], intent.output_token_limit)
        receipt, selection, request_identity, output_identity, output_limit = _receipt_parts(
            response["subscription_runtime"]
        )
    except BridgeJsonError as exc:
        raise BridgeReceiptError(str(exc)) from exc

    _validate_runtime_selection(selection, authority)
    _validate_request_identity(request_identity, authority, intent)
    output_text_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    if output_identity != {
        "output_text_sha256": output_text_sha256,
        "terminal_status": "completed",
    }:
        raise BridgeReceiptError("bridge_output_identity_invalid")
    if output_limit != {"requested_tokens": intent.output_token_limit, "enforced": False}:
        raise BridgeReceiptError("bridge_output_token_limit_identity_invalid")

    canonical = _runtime_attestation_canonical_bytes(
        selection=selection,
        request_identity=request_identity,
        output_identity=output_identity,
        usage=usage_payload,
        requested_tokens=intent.output_token_limit,
    )
    receipt_hmac = receipt["receipt_hmac_sha256"]
    if not isinstance(receipt_hmac, str) or _HEX.fullmatch(receipt_hmac) is None:
        raise BridgeReceiptError("bridge_receipt_hmac_invalid")
    expected_hmac = hmac.new(attestation_secret, canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hmac, receipt_hmac):
        raise BridgeReceiptError("bridge_receipt_hmac_mismatch")

    thread_id = selection["thread_id"]
    turn_id = selection["turn_id"]
    if (
        not isinstance(thread_id, str)
        or _RUNTIME_ID.fullmatch(thread_id) is None
        or not isinstance(turn_id, str)
        or _RUNTIME_ID.fullmatch(turn_id) is None
    ):
        raise BridgeReceiptError("bridge_runtime_execution_identity_invalid")
    return VerifiedRuntimeResponse(
        output_text=output_text,
        response_body_sha256=hashlib.sha256(response_body).hexdigest(),
        output_text_sha256=output_text_sha256,
        attestation_sha256=hashlib.sha256(canonical).hexdigest(),
        receipt_hmac_sha256=receipt_hmac,
        thread_id=thread_id,
        turn_id=turn_id,
        usage=usage,
    )


def verify_reconstructed_runtime_receipt(
    *,
    authority: BridgeAuthority,
    intent: BridgeIntent,
    result: AuthenticatedBridgeResult,
    attestation_secret: bytes,
) -> None:
    """Reauthenticate a durable result from the exact persisted receipt fields."""

    _require_attestation_secret(attestation_secret)
    if result.usage.completion_tokens > intent.output_token_limit:
        raise BridgeReceiptError("bridge_persisted_output_token_limit_exceeded")
    selection = {
        "account_binding_hmac_sha256": authority.account_binding_hmac_sha256,
        "thread_id": result.thread_id,
        "turn_id": result.turn_id,
        "model": authority.CODEX_MODEL,
        "model_provider": authority.MODEL_PROVIDER,
        "reasoning_effort": authority.REASONING_EFFORT,
        "service_tier": authority.SERVICE_TIER,
        "execution_profile": authority.EXECUTION_PROFILE,
        "base_instructions_sha256": authority.base_instructions_sha256,
    }
    request_identity = {
        "public_model": authority.public_model,
        "client_requested_model": authority.public_model,
        "configured_codex_model": authority.CODEX_MODEL,
        "requested_codex_model": authority.CODEX_MODEL,
        "request_body_sha256": intent.request_body_sha256,
        "response_format_type": intent.response_format_type,
        "response_format_sha256": intent.response_format_sha256,
        "response_schema_sha256": intent.response_schema_sha256,
    }
    output_identity = {
        "output_text_sha256": result.output_text_sha256,
        "terminal_status": "completed",
    }
    canonical = _runtime_attestation_canonical_bytes(
        selection=selection,
        request_identity=request_identity,
        output_identity=output_identity,
        usage=_usage_payload(result.usage),
        requested_tokens=intent.output_token_limit,
    )
    expected_attestation = hashlib.sha256(canonical).hexdigest()
    if not hmac.compare_digest(expected_attestation, result.attestation_sha256):
        raise BridgeReceiptError("bridge_persisted_attestation_mismatch")
    expected_receipt = hmac.new(attestation_secret, canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_receipt, result.receipt_hmac_sha256):
        raise BridgeReceiptError("bridge_persisted_receipt_hmac_mismatch")


def output_associated_data(
    intent: BridgeIntent,
    result: AuthenticatedBridgeResult | VerifiedRuntimeResponse,
) -> bytes:
    """Bind private output to pool, bridge, intent, request, and response identities."""

    return canonical_json_bytes(
        {
            "bridge": {
                "authority_sha256": intent.bridge_authority_sha256,
                "bridge_id": intent.bridge_id,
            },
            "intent": intent.binding.public_payload(),
            "pool": {
                "authority_sha256": intent.pool_authority_sha256,
                "pool_id": intent.pool_id,
            },
            "request_identity": {
                "prompt_input_sha256": intent.prompt_input_sha256,
                "request_body_sha256": intent.request_body_sha256,
                "response_format_sha256": intent.response_format_sha256,
                "response_schema_sha256": intent.response_schema_sha256,
            },
            "response_identity": {
                "attestation_sha256": result.attestation_sha256,
                "output_text_sha256": result.output_text_sha256,
                "receipt_hmac_sha256": result.receipt_hmac_sha256,
                "response_body_sha256": result.response_body_sha256,
                "thread_id": result.thread_id,
                "turn_id": result.turn_id,
            },
        }
    )


def _validate_response_identity(response: dict[str, Any], authority: BridgeAuthority) -> str:
    if (
        not isinstance(response["id"], str)
        or not response["id"].startswith("chatcmpl-")
        or len(response["id"]) > 200
        or response["object"] != "chat.completion"
        or type(response["created"]) is not int
        or not 0 <= response["created"] <= _MAX_SAFE_INTEGER
        or response["model"] != authority.CODEX_MODEL
    ):
        raise BridgeReceiptError("bridge_response_identity_invalid")
    expected_fingerprint = (
        "subscription-runtime-codex-bridge-v4:"
        + hashlib.sha256(
            json.dumps(
                [
                    "codex-app-server",
                    authority.public_model,
                    authority.CODEX_MODEL,
                    authority.EXECUTION_PROFILE,
                    authority.base_instructions_sha256,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    if response["system_fingerprint"] != expected_fingerprint:
        raise BridgeReceiptError("bridge_system_fingerprint_invalid")
    choices = response["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise BridgeReceiptError("bridge_response_choices_invalid")
    try:
        choice = exact_object(
            choices[0],
            required=frozenset({"finish_reason", "index", "message"}),
            label="bridge_choice",
        )
        message = exact_object(
            choice["message"],
            required=frozenset({"content", "role"}),
            label="bridge_choice_message",
        )
    except BridgeJsonError as exc:
        raise BridgeReceiptError(str(exc)) from exc
    if (
        type(choice["index"]) is not int
        or choice["index"] != 0
        or choice["finish_reason"] != "stop"
        or message["role"] != "assistant"
        or not isinstance(message["content"], str)
    ):
        raise BridgeReceiptError("bridge_response_choice_identity_invalid")
    return message["content"]


def _validate_usage(value: object, output_limit: int) -> tuple[TokenUsage, dict[str, Any]]:
    usage = exact_object(
        value,
        required=frozenset(
            {
                "completion_tokens",
                "completion_tokens_details",
                "prompt_tokens",
                "prompt_tokens_details",
                "total_tokens",
            }
        ),
        label="bridge_usage",
    )
    prompt_details = exact_object(
        usage["prompt_tokens_details"],
        required=frozenset({"cached_tokens"}),
        optional=frozenset({"cache_write_tokens"}),
        label="bridge_prompt_token_details",
    )
    completion_details = exact_object(
        usage["completion_tokens_details"],
        required=frozenset({"reasoning_tokens"}),
        label="bridge_completion_token_details",
    )
    observed = TokenUsage(
        prompt_tokens=_token(usage["prompt_tokens"], "prompt_tokens"),
        cached_tokens=_token(prompt_details["cached_tokens"], "cached_tokens"),
        cache_write_tokens=(
            None
            if "cache_write_tokens" not in prompt_details
            else _token(prompt_details["cache_write_tokens"], "cache_write_tokens")
        ),
        completion_tokens=_token(usage["completion_tokens"], "completion_tokens"),
        reasoning_tokens=_token(completion_details["reasoning_tokens"], "reasoning_tokens"),
        total_tokens=_token(usage["total_tokens"], "total_tokens"),
    )
    if observed.completion_tokens > output_limit:
        raise BridgeReceiptError("bridge_observed_output_token_limit_exceeded")
    return observed, _usage_payload(observed)


def _usage_payload(observed: TokenUsage) -> dict[str, Any]:
    return {
        "prompt_tokens": observed.prompt_tokens,
        "prompt_tokens_details": {
            "cached_tokens": observed.cached_tokens,
            **(
                {}
                if observed.cache_write_tokens is None
                else {"cache_write_tokens": observed.cache_write_tokens}
            ),
        },
        "completion_tokens": observed.completion_tokens,
        "completion_tokens_details": {"reasoning_tokens": observed.reasoning_tokens},
        "total_tokens": observed.total_tokens,
    }


def _receipt_parts(
    value: object,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    receipt = exact_object(
        value,
        required=frozenset(
            {
                "attestation_level",
                "output_identity",
                "output_token_limit",
                "receipt_hmac_sha256",
                "request_identity",
                "runtime_selection",
                "schema_version",
                "usage_source",
            }
        ),
        label="bridge_subscription_runtime",
    )
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 2
        or receipt["attestation_level"] != "provider_receipt"
        or receipt["usage_source"] != "codex_thread_token_usage_updated"
    ):
        raise BridgeReceiptError("bridge_receipt_contract_invalid")
    selection = exact_object(
        receipt["runtime_selection"],
        required=frozenset(
            {
                "account_binding_hmac_sha256",
                "base_instructions_sha256",
                "execution_profile",
                "model",
                "model_provider",
                "reasoning_effort",
                "service_tier",
                "thread_id",
                "turn_id",
            }
        ),
        label="bridge_runtime_selection",
    )
    request_identity = exact_object(
        receipt["request_identity"],
        required=frozenset(
            {
                "client_requested_model",
                "configured_codex_model",
                "public_model",
                "request_body_sha256",
                "requested_codex_model",
                "response_format_sha256",
                "response_format_type",
                "response_schema_sha256",
            }
        ),
        label="bridge_request_identity",
    )
    output_identity = exact_object(
        receipt["output_identity"],
        required=frozenset({"output_text_sha256", "terminal_status"}),
        label="bridge_output_identity",
    )
    output_limit = exact_object(
        receipt["output_token_limit"],
        required=frozenset({"enforced", "requested_tokens"}),
        label="bridge_output_token_limit",
    )
    return receipt, selection, request_identity, output_identity, output_limit


def _validate_runtime_selection(selection: dict[str, Any], authority: BridgeAuthority) -> None:
    expected = {
        "account_binding_hmac_sha256": authority.account_binding_hmac_sha256,
        "base_instructions_sha256": authority.base_instructions_sha256,
        "execution_profile": authority.EXECUTION_PROFILE,
        "model": authority.CODEX_MODEL,
        "model_provider": authority.MODEL_PROVIDER,
        "reasoning_effort": authority.REASONING_EFFORT,
        "service_tier": authority.SERVICE_TIER,
    }
    for key, value in expected.items():
        if selection[key] != value:
            raise BridgeReceiptError(f"bridge_runtime_{key}_invalid")


def _validate_request_identity(
    identity: dict[str, Any],
    authority: BridgeAuthority,
    intent: BridgeIntent,
) -> None:
    expected = {
        "client_requested_model": authority.public_model,
        "configured_codex_model": authority.CODEX_MODEL,
        "public_model": authority.public_model,
        "request_body_sha256": intent.request_body_sha256,
        "requested_codex_model": authority.CODEX_MODEL,
        "response_format_sha256": intent.response_format_sha256,
        "response_format_type": intent.response_format_type,
        "response_schema_sha256": intent.response_schema_sha256,
    }
    if identity != expected:
        raise BridgeReceiptError("bridge_request_identity_invalid")


def _runtime_attestation_canonical_bytes(
    *,
    selection: dict[str, Any],
    request_identity: dict[str, Any],
    output_identity: dict[str, Any],
    usage: dict[str, Any],
    requested_tokens: int,
) -> bytes:
    """Match openAiBridgeRuntimeAttestationCanonicalBytes field order exactly."""

    prompt_details = usage["prompt_tokens_details"]
    payload = {
        "schema_version": 2,
        "attestation_level": "provider_receipt",
        "usage_source": "codex_thread_token_usage_updated",
        "runtime_selection": {
            "account_binding_hmac_sha256": selection["account_binding_hmac_sha256"],
            "thread_id": selection["thread_id"],
            "turn_id": selection["turn_id"],
            "model": selection["model"],
            "model_provider": selection["model_provider"],
            "reasoning_effort": selection["reasoning_effort"],
            "service_tier": selection["service_tier"],
            "execution_profile": selection["execution_profile"],
            "base_instructions_sha256": selection["base_instructions_sha256"],
        },
        "request_identity": {
            "public_model": request_identity["public_model"],
            "client_requested_model": request_identity["client_requested_model"],
            "configured_codex_model": request_identity["configured_codex_model"],
            "requested_codex_model": request_identity["requested_codex_model"],
            "request_body_sha256": request_identity["request_body_sha256"],
            "response_format_type": request_identity["response_format_type"],
            "response_format_sha256": request_identity["response_format_sha256"],
            "response_schema_sha256": request_identity["response_schema_sha256"],
        },
        "output_identity": {
            "output_text_sha256": output_identity["output_text_sha256"],
            "terminal_status": output_identity["terminal_status"],
        },
        "usage": {
            "prompt_tokens": usage["prompt_tokens"],
            "prompt_tokens_details": {
                "cached_tokens": prompt_details["cached_tokens"],
                **(
                    {}
                    if "cache_write_tokens" not in prompt_details
                    else {"cache_write_tokens": prompt_details["cache_write_tokens"]}
                ),
            },
            "completion_tokens": usage["completion_tokens"],
            "completion_tokens_details": {
                "reasoning_tokens": usage["completion_tokens_details"]["reasoning_tokens"]
            },
            "total_tokens": usage["total_tokens"],
        },
        "output_token_limit": {"requested_tokens": requested_tokens, "enforced": False},
    }
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BridgeReceiptError("bridge_attestation_canonicalization_invalid") from exc


def _token(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise BridgeReceiptError(f"bridge_usage_{label}_invalid")
    return value


def _require_attestation_secret(value: object) -> None:
    if type(value) is not bytes or len(value) < 32:
        raise BridgeReceiptError("bridge_attestation_secret_invalid")


__all__ = (
    "VerifiedRuntimeResponse",
    "output_associated_data",
    "verify_reconstructed_runtime_receipt",
    "verify_runtime_response",
)
