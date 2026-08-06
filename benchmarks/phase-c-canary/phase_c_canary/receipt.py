from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .environment import build_runtime_environment
from .hashing import sha256_file


class ReceiptVerificationError(ValueError):
    pass


class RuntimeReceiptVerifierPort(Protocol):
    def verify(self, *, receipt: dict[str, Any], secret: str) -> None: ...


_ROOT_KEYS = {"metadata", "usage"}
_METADATA_KEYS = {
    "schema_version",
    "attestation_level",
    "usage_source",
    "runtime_selection",
    "request_identity",
    "output_identity",
    "output_token_limit",
    "receipt_hmac_sha256",
}
_SELECTION_KEYS = {
    "account_binding_hmac_sha256",
    "thread_id",
    "turn_id",
    "model",
    "model_provider",
    "reasoning_effort",
    "service_tier",
    "execution_profile",
    "base_instructions_sha256",
}
_REQUEST_KEYS = {
    "public_model",
    "client_requested_model",
    "configured_codex_model",
    "requested_codex_model",
    "request_body_sha256",
    "response_format_type",
    "response_format_sha256",
    "response_schema_sha256",
}
_OUTPUT_KEYS = {"output_text_sha256", "terminal_status"}
_LIMIT_KEYS = {"requested_tokens", "enforced"}
_USAGE_REQUIRED = {"prompt_tokens", "completion_tokens", "total_tokens"}
_USAGE_OPTIONAL = {"prompt_tokens_details", "completion_tokens_details"}


def validate_receipt_shape(receipt: dict[str, Any]) -> None:
    _exact(receipt, _ROOT_KEYS, "receipt")
    metadata = _mapping(receipt["metadata"], "metadata")
    usage = _mapping(receipt["usage"], "usage")
    _exact(metadata, _METADATA_KEYS, "metadata")
    _exact(
        _mapping(metadata["runtime_selection"], "runtime_selection"),
        _SELECTION_KEYS,
        "runtime_selection",
    )
    _exact(
        _mapping(metadata["request_identity"], "request_identity"),
        _REQUEST_KEYS,
        "request_identity",
    )
    _exact(
        _mapping(metadata["output_identity"], "output_identity"),
        _OUTPUT_KEYS,
        "output_identity",
    )
    _exact(
        _mapping(metadata["output_token_limit"], "output_token_limit"),
        _LIMIT_KEYS,
        "output_token_limit",
    )
    usage_keys = set(usage)
    if not usage_keys >= _USAGE_REQUIRED or not usage_keys <= _USAGE_REQUIRED | _USAGE_OPTIONAL:
        raise ReceiptVerificationError("usage keys do not match receipt v2")
    if metadata["schema_version"] != 2:
        raise ReceiptVerificationError("receipt schema must be v2")
    if metadata["attestation_level"] != "provider_receipt":
        raise ReceiptVerificationError("receipt is not provider attested")
    if metadata["usage_source"] != "codex_thread_token_usage_updated":
        raise ReceiptVerificationError("receipt usage source is not provider observed")
    selection = _mapping(metadata["runtime_selection"], "runtime_selection")
    if selection["execution_profile"] != "stateless-completion":
        raise ReceiptVerificationError("receipt did not use stateless-completion")
    if metadata["output_token_limit"].get("enforced") is not False:
        raise ReceiptVerificationError("unexpected runtime output-token enforcement")
    prompt_details = usage.get("prompt_tokens_details")
    if prompt_details is not None:
        _allowed_optional(
            _mapping(prompt_details, "prompt_tokens_details"),
            required={"cached_tokens"},
            optional={"cache_write_tokens"},
            label="prompt_tokens_details",
        )
    completion_details = usage.get("completion_tokens_details")
    if completion_details is not None:
        _exact(
            _mapping(completion_details, "completion_tokens_details"),
            {"reasoning_tokens"},
            "completion_tokens_details",
        )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptVerificationError(f"{label} must be an object")
    return value


def _exact(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ReceiptVerificationError(f"{label} has missing or additional keys")


def _allowed_optional(
    value: dict[str, Any], *, required: set[str], optional: set[str], label: str
) -> None:
    if not required <= set(value) or not set(value) <= required | optional:
        raise ReceiptVerificationError(f"{label} has missing or additional keys")


@dataclass(frozen=True, slots=True)
class NodePublicReceiptVerifier(RuntimeReceiptVerifierPort):
    runtime_repo: Path
    node_executable: Path = Path("/usr/local/bin/node")

    def verify(self, *, receipt: dict[str, Any], secret: str) -> None:
        validate_receipt_shape(receipt)
        verifier_url = self._verified_module_url()
        payload = json.dumps(
            {"receipt": receipt, "secret": secret, "verifier_url": verifier_url},
            separators=(",", ":"),
        )
        result = subprocess.run(
            [str(self.node_executable), "--input-type=module", "-e", _NODE_VERIFIER],
            cwd=self.runtime_repo,
            env=build_runtime_environment(
                {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
                required=frozenset(),
            ),
            input=payload,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0 or result.stdout != "verified\n":
            raise ReceiptVerificationError(
                f"immutable runtime public verifier rejected receipt (exit={result.returncode})"
            )

    def _verified_module_url(self) -> str:
        manifest_path = self.runtime_repo.parent / "artifact-manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries: dict[str, dict[str, Any]] = {}
            for entry in manifest["artifactFiles"]:
                relative = entry["path"]
                if relative in entries:
                    raise ReceiptVerificationError("runtime artifact paths are duplicated")
                entries[relative] = entry
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ReceiptVerificationError("runtime artifact manifest is invalid") from exc
        try:
            for relative in (_VERIFIER_MODULE, _CANONICAL_BYTES_MODULE):
                entry = entries.get(relative)
                path = self.runtime_repo / relative
                if (
                    not isinstance(entry, dict)
                    or set(entry) != {"path", "size", "sha256"}
                    or path.is_symlink()
                    or path.resolve(strict=True)
                    != (self.runtime_repo.resolve(strict=True) / relative)
                    or path.stat().st_size != entry["size"]
                    or sha256_file(path) != entry["sha256"]
                ):
                    raise ReceiptVerificationError(f"runtime verifier closure drifted: {relative}")
        except OSError as exc:
            raise ReceiptVerificationError("runtime verifier closure is incomplete") from exc
        return (self.runtime_repo / _VERIFIER_MODULE).resolve(strict=True).as_uri()


_VERIFIER_MODULE = (
    "dist/openai-compatible-codex/chat-completions/adapters/crypto/"
    "node-runtime-attestation-verifier.js"
)
_CANONICAL_BYTES_MODULE = (
    "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
)


_NODE_VERIFIER = r"""
let body = "";
for await (const chunk of process.stdin) body += chunk;
const {receipt, secret, verifier_url} = JSON.parse(body);
if (import.meta.resolve(verifier_url) !== verifier_url) process.exit(4);
const {verifyOpenAiBridgeRuntimeAttestationHmac} = await import(verifier_url);
const metadata = receipt.metadata;
const ok = verifyOpenAiBridgeRuntimeAttestationHmac({
  attestationSecret: secret,
  expectedHmacSha256: metadata.receipt_hmac_sha256,
  attestation: {
    selection: metadata.runtime_selection,
    requestIdentity: metadata.request_identity,
    outputIdentity: metadata.output_identity,
    usage: receipt.usage,
    requestedOutputTokenLimit: metadata.output_token_limit.requested_tokens ?? undefined,
  },
});
if (!ok) process.exit(3);
process.stdout.write("verified\n");
"""
