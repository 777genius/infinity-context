"""Independent receipt-v2 canonicalization, signing, and verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .canonical import (
    E2EVerificationError,
    canonical_sha256,
    exact_object,
    require_digest,
    safe_text,
)


class ReceiptCanonicalizer(Protocol):
    def canonical_bytes(self, receipt: dict[str, object]) -> bytes: ...


class NodeReceiptCanonicalizer:
    """Calls the immutable runtime canonicalizer without exposing receipt data in argv."""

    def __init__(self, *, runtime_repo: Path, node_executable: Path) -> None:
        module = (
            runtime_repo
            / "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
        )
        if not runtime_repo.is_absolute() or not module.is_file() or not node_executable.is_file():
            raise ValueError("e2e_receipt_authority_invalid")
        self._runtime_repo = runtime_repo
        self._node = node_executable
        self._module_url = module.as_uri()

    def canonical_bytes(self, receipt: dict[str, object]) -> bytes:
        script = r"""
let body = ""; for await (const chunk of process.stdin) body += chunk;
const {receipt, module_url} = JSON.parse(body); const m = receipt.metadata;
const {openAiBridgeRuntimeAttestationCanonicalBytes} = await import(module_url);
const value = openAiBridgeRuntimeAttestationCanonicalBytes({
  selection:m.runtime_selection, requestIdentity:m.request_identity,
  outputIdentity:m.output_identity, usage:receipt.usage,
  requestedOutputTokenLimit:m.output_token_limit.requested_tokens,
});
process.stdout.write(Buffer.from(value).toString("base64"));
"""
        try:
            completed = subprocess.run(
                [str(self._node), "--input-type=module", "-e", script],
                cwd=self._runtime_repo,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
                input=json.dumps({"receipt": receipt, "module_url": self._module_url}),
                text=True,
                capture_output=True,
                timeout=10,
                check=True,
            )
            return base64.b64decode(completed.stdout, validate=True)
        except Exception:
            raise E2EVerificationError("e2e_receipt_canonicalization_failed") from None


@dataclass(frozen=True, slots=True)
class ReceiptAuthority:
    account_binding_hmac_sha256: str
    base_instructions_sha256: str
    request_body_sha256: str
    response_format_sha256: str
    response_schema_sha256: str
    output_text_sha256: str
    thread_id: str = "thread-provider-free-e2e"
    turn_id: str = "turn-provider-free-e2e-1"


class ReceiptVerifier:
    def __init__(
        self,
        *,
        authority: ReceiptAuthority,
        receipt_secret: bytes,
        canonicalizer: ReceiptCanonicalizer,
    ) -> None:
        if not isinstance(receipt_secret, bytes) or len(receipt_secret) < 32:
            raise ValueError("e2e_receipt_authority_invalid")
        self._authority = authority
        self._secret = bytes(receipt_secret)
        self._canonicalizer = canonicalizer

    def verify(self, receipt: dict[str, object]) -> str:
        root = exact_object(receipt, {"metadata", "usage"}, "e2e_receipt_invalid")
        metadata = exact_object(
            root["metadata"],
            {
                "schema_version",
                "attestation_level",
                "usage_source",
                "runtime_selection",
                "request_identity",
                "output_identity",
                "output_token_limit",
                "receipt_hmac_sha256",
            },
            "e2e_receipt_invalid",
        )
        usage = exact_object(
            root["usage"],
            {
                "prompt_tokens",
                "prompt_tokens_details",
                "completion_tokens",
                "completion_tokens_details",
                "total_tokens",
            },
            "e2e_receipt_invalid",
        )
        self._verify_usage(usage)
        self._verify_metadata(metadata)
        presented = require_digest(metadata["receipt_hmac_sha256"], "e2e_receipt_invalid")
        expected = hmac.new(
            self._secret,
            self._canonicalizer.canonical_bytes(receipt),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(presented, expected):
            raise E2EVerificationError("e2e_receipt_unauthenticated")
        return canonical_sha256(receipt)

    @staticmethod
    def _verify_usage(usage: dict[str, object]) -> None:
        scalar_names = ("prompt_tokens", "completion_tokens", "total_tokens")
        if any(
            not isinstance(usage[name], int) or isinstance(usage[name], bool)
            for name in scalar_names
        ):
            raise E2EVerificationError("e2e_receipt_usage_invalid")
        prompt_details = usage["prompt_tokens_details"]
        completion_details = usage["completion_tokens_details"]
        if (
            not isinstance(prompt_details, dict)
            or not isinstance(completion_details, dict)
            or not isinstance(prompt_details.get("cached_tokens"), int)
            or isinstance(prompt_details.get("cached_tokens"), bool)
            or not isinstance(completion_details.get("reasoning_tokens"), int)
            or isinstance(completion_details.get("reasoning_tokens"), bool)
        ):
            raise E2EVerificationError("e2e_receipt_usage_invalid")
        if usage != {
            "prompt_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens": 0,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        }:
            raise E2EVerificationError("e2e_receipt_usage_invalid")

    def _verify_metadata(self, metadata: dict[str, object]) -> None:
        selection = exact_object(
            metadata["runtime_selection"],
            {
                "account_binding_hmac_sha256",
                "thread_id",
                "turn_id",
                "model",
                "model_provider",
                "reasoning_effort",
                "service_tier",
                "execution_profile",
                "base_instructions_sha256",
            },
            "e2e_receipt_invalid",
        )
        request = exact_object(
            metadata["request_identity"],
            {
                "public_model",
                "client_requested_model",
                "configured_codex_model",
                "requested_codex_model",
                "request_body_sha256",
                "response_format_type",
                "response_format_sha256",
                "response_schema_sha256",
            },
            "e2e_receipt_invalid",
        )
        output = exact_object(
            metadata["output_identity"],
            {"output_text_sha256", "terminal_status"},
            "e2e_receipt_invalid",
        )
        limit = exact_object(
            metadata["output_token_limit"],
            {"requested_tokens", "enforced"},
            "e2e_receipt_invalid",
        )
        expected_model = "gpt-5.6-sol"
        if (
            metadata["schema_version"] != 2
            or metadata["attestation_level"] != "provider_receipt"
            or metadata["usage_source"] != "codex_thread_token_usage_updated"
            or selection["account_binding_hmac_sha256"]
            != self._authority.account_binding_hmac_sha256
            or selection["base_instructions_sha256"] != self._authority.base_instructions_sha256
            or safe_text(selection["thread_id"]) != self._authority.thread_id
            or safe_text(selection["turn_id"]) != self._authority.turn_id
            or selection["model"] != expected_model
            or selection["model_provider"] != "openai"
            or selection["reasoning_effort"] != "high"
            or selection["service_tier"] != "default"
            or selection["execution_profile"] != "stateless-completion"
            or any(
                request[key] != expected_model
                for key in (
                    "public_model",
                    "client_requested_model",
                    "configured_codex_model",
                    "requested_codex_model",
                )
            )
            or request["request_body_sha256"] != self._authority.request_body_sha256
            or request["response_format_type"] != "json_schema"
            or request["response_format_sha256"] != self._authority.response_format_sha256
            or request["response_schema_sha256"] != self._authority.response_schema_sha256
            or output
            != {
                "output_text_sha256": self._authority.output_text_sha256,
                "terminal_status": "completed",
            }
            or limit != {"requested_tokens": 4096, "enforced": False}
        ):
            raise E2EVerificationError("e2e_receipt_binding_invalid")


def sign_receipt(
    receipt: dict[str, object], *, secret: bytes, canonicalizer: ReceiptCanonicalizer
) -> dict[str, object]:
    signed = deepcopy(receipt)
    metadata = signed.get("metadata")
    if not isinstance(metadata, dict):
        raise E2EVerificationError("e2e_receipt_invalid")
    metadata["receipt_hmac_sha256"] = hmac.new(
        secret,
        canonicalizer.canonical_bytes(signed),
        hashlib.sha256,
    ).hexdigest()
    return signed
