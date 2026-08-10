"""Provider-free fixtures derived from the runtime's public schema-v2 contract."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any

from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeAuthority,
    BridgeCallBinding,
    BridgePoolAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.json_boundary import (
    canonical_json_bytes,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    canonical_openai_request_body,
)

JOURNAL_KEY = b"journal-integrity-key-32-bytes-minimum-value"
OUTPUT_KEY = b"test-output-key-32-bytes-minimum-value"


def make_pool(size: int = 1) -> BridgePoolAuthority:
    bridges = tuple(
        BridgeAuthority(
            bridge_id=f"bridge-{index}",
            origin=f"http://127.0.0.1:{43100 + index}",
            account_binding_hmac_sha256=hashlib.sha256(f"account-{index}".encode()).hexdigest(),
            public_model="subscription-codex",
            base_instructions_sha256=hashlib.sha256(
                f"base-instructions-{index}".encode()
            ).hexdigest(),
        )
        for index in range(size)
    )
    return BridgePoolAuthority(pool_id="publishable-runtime-pool", bridges=bridges)


def make_binding(index: int = 0, *, operation: str = "answer") -> BridgeCallBinding:
    return BridgeCallBinding(
        intent_id=f"intent-{operation}-{index}",
        logical_operation=operation,
        logical_call_id=f"call-{index}",
    )


def make_request(
    public_model: str = "subscription-codex",
    *,
    prompt: str = "private prompt",
    output_tokens: int = 32,
) -> bytes:
    return canonical_openai_request_body(
        {
            "max_completion_tokens": output_tokens,
            "messages": [{"content": prompt, "role": "user"}],
            "model": public_model,
        }
    )


TEST_LAUNCHER_RECEIPT_KEY = b"scheduler-bridge-test-launcher-receipt-key-material"


class FakeSecrets:
    __slots__ = ("_attestation", "_bearers", "_launcher_receipt_key")

    def __init__(
        self,
        pool: BridgePoolAuthority,
        *,
        launcher_receipt_key: bytes = TEST_LAUNCHER_RECEIPT_KEY,
    ) -> None:
        self._bearers = {
            bridge.bridge_id: f"bearer-for-{bridge.bridge_id}" for bridge in pool.bridges
        }
        self._attestation = {
            bridge.bridge_id: hashlib.sha256(
                f"attestation-secret-{bridge.bridge_id}".encode()
            ).digest()
            for bridge in pool.bridges
        }
        self._launcher_receipt_key = launcher_receipt_key

    def authorization_bearer(self, bridge_id: str) -> str:
        return self._bearers[bridge_id]

    def attestation_secret(self, bridge_id: str) -> bytes:
        return self._attestation[bridge_id]

    def launcher_receipt_key(self, bridge_id: str) -> bytes:
        if bridge_id not in self._bearers:
            raise KeyError(bridge_id)
        return self._launcher_receipt_key


class TestAuthenticatedCipher:
    """Test double only: models AEAD key/AAD failure without shipping production crypto."""

    __test__ = False
    __slots__ = ("_key",)

    def __init__(self, key: bytes = OUTPUT_KEY) -> None:
        self._key = key

    def seal(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        nonce = hashlib.sha256(self._key + associated_data + plaintext).digest()[:16]
        encrypted = _xor(plaintext, _stream(self._key, nonce, len(plaintext)))
        tag = hmac.new(
            self._key,
            b"test-aead-v1\0" + associated_data + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        return nonce + encrypted + tag

    def open(self, ciphertext: bytes, *, associated_data: bytes) -> bytes:
        if len(ciphertext) < 48:
            raise ValueError("test_ciphertext_invalid")
        nonce, encrypted, tag = ciphertext[:16], ciphertext[16:-32], ciphertext[-32:]
        expected = hmac.new(
            self._key,
            b"test-aead-v1\0" + associated_data + nonce + encrypted,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("test_authentication_failed")
        return _xor(encrypted, _stream(self._key, nonce, len(encrypted)))


class AttestedFakeTransport:
    __slots__ = ("calls", "_mutate", "_pool", "_raw_mutate", "_secrets")

    def __init__(
        self,
        pool: BridgePoolAuthority,
        secrets: FakeSecrets,
        *,
        mutate: Callable[[dict[str, Any]], None] | None = None,
        raw_mutate: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self._pool = pool
        self._secrets = secrets
        self._mutate = mutate
        self._raw_mutate = raw_mutate
        self.calls: list[tuple[str, bytes]] = []

    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes:
        del maximum_response_bytes
        bridge = next(item for item in self._pool.bridges if item.origin == origin)
        assert route == bridge.route
        assert bearer_token == self._secrets.authorization_bearer(bridge.bridge_id)
        self.calls.append((bridge.bridge_id, request_body))
        response = build_runtime_response(
            bridge=bridge,
            request_body=request_body,
            secret=self._secrets.attestation_secret(bridge.bridge_id),
        )
        if self._mutate is not None:
            self._mutate(response)
        raw = canonical_json_bytes(response)
        return raw if self._raw_mutate is None else self._raw_mutate(raw)


def build_runtime_response(
    *,
    bridge: BridgeAuthority,
    request_body: bytes,
    secret: bytes,
    output_text: str = "private completion",
) -> dict[str, Any]:
    request = json.loads(request_body)
    response_format_type, response_format_hash, schema_hash = _response_format_identity(
        request.get("response_format")
    )
    output_limit = request.get("max_completion_tokens", request.get("max_tokens"))
    usage = {
        "prompt_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens": 4,
        "completion_tokens_details": {"reasoning_tokens": 1},
        "total_tokens": 14,
    }
    selection = {
        "account_binding_hmac_sha256": bridge.account_binding_hmac_sha256,
        "thread_id": f"thread-{bridge.bridge_id}",
        "turn_id": f"turn-{bridge.bridge_id}",
        "model": bridge.CODEX_MODEL,
        "model_provider": bridge.MODEL_PROVIDER,
        "reasoning_effort": bridge.REASONING_EFFORT,
        "service_tier": bridge.SERVICE_TIER,
        "execution_profile": bridge.EXECUTION_PROFILE,
        "base_instructions_sha256": bridge.base_instructions_sha256,
    }
    request_identity = {
        "public_model": bridge.public_model,
        "client_requested_model": bridge.public_model,
        "configured_codex_model": bridge.CODEX_MODEL,
        "requested_codex_model": bridge.CODEX_MODEL,
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "response_format_type": response_format_type,
        "response_format_sha256": response_format_hash,
        "response_schema_sha256": schema_hash,
    }
    output_identity = {
        "output_text_sha256": hashlib.sha256(output_text.encode()).hexdigest(),
        "terminal_status": "completed",
    }
    canonical = runtime_attestation_canonical_bytes(
        selection=selection,
        request_identity=request_identity,
        output_identity=output_identity,
        usage=usage,
        requested_tokens=output_limit,
    )
    fingerprint = (
        "subscription-runtime-codex-bridge-v4:"
        + hashlib.sha256(
            json.dumps(
                [
                    "codex-app-server",
                    bridge.public_model,
                    bridge.CODEX_MODEL,
                    bridge.EXECUTION_PROFILE,
                    bridge.base_instructions_sha256,
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    return {
        "id": "chatcmpl-public-contract",
        "object": "chat.completion",
        "created": 1_786_320_000,
        "model": bridge.CODEX_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output_text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "system_fingerprint": fingerprint,
        "subscription_runtime": {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": selection,
            "request_identity": request_identity,
            "output_identity": output_identity,
            "output_token_limit": {"requested_tokens": output_limit, "enforced": False},
            "receipt_hmac_sha256": hmac.new(secret, canonical, hashlib.sha256).hexdigest(),
        },
    }


def runtime_attestation_canonical_bytes(
    *,
    selection: dict[str, Any],
    request_identity: dict[str, Any],
    output_identity: dict[str, Any],
    usage: dict[str, Any],
    requested_tokens: int,
) -> bytes:
    """Independent transcription of openAiBridgeRuntimeAttestationCanonicalBytes."""

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
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def _response_format_identity(value: object) -> tuple[str, str, str | None]:
    if not isinstance(value, dict) or value.get("type", "text") == "text":
        text = {"type": "text"}
        return "text", hashlib.sha256(canonical_json_bytes(text)).hexdigest(), None
    schema = value["json_schema"]["schema"]
    return (
        "json_schema",
        hashlib.sha256(_runtime_semantic_json_bytes(value)).hexdigest(),
        hashlib.sha256(_runtime_semantic_json_bytes(schema)).hexdigest(),
    )


def _runtime_semantic_json_bytes(value: object) -> bytes:
    """Independent transcription of canonicalValue plus JSON.stringify."""

    def canonical(item: object) -> object:
        if isinstance(item, list):
            return [canonical(child) for child in item]
        if not isinstance(item, dict):
            return item
        return {
            key: canonical(item[key])
            for key in sorted(
                item,
                key=lambda candidate: candidate.encode("utf-16-be", errors="surrogatepass"),
            )
        }

    return json.dumps(
        canonical(value),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
    result = bytearray()
    counter = 0
    while len(result) < length:
        result.extend(hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(result[:length])


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(first ^ second for first, second in zip(left, right, strict=True))
