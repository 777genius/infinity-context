"""Zero-token fake subscription runtime that emits authentic receipt-v2 evidence."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .canonical import (
    E2EVerificationError,
    atomic_private_write,
    canonical_bytes,
    canonical_sha256,
    exact_object,
    read_private_text,
    require_digest,
    sha256_bytes,
)
from .contracts import SYNTHETIC_OUTPUT
from .receipt import NodeReceiptCanonicalizer, ReceiptCanonicalizer, sign_receipt

_MAX_REQUEST_BYTES = 1_048_576


@dataclass(frozen=True, slots=True)
class FakeRuntimeConfig:
    bearer_token: str
    receipt_secret: bytes
    account_binding_hmac_sha256: str
    base_instructions_sha256: str


class AuthenticatedCallCounter:
    """Persists only call count and request digest, authenticated with a distinct derivation."""

    def __init__(self, path: Path, *, key: bytes) -> None:
        if not path.is_absolute() or len(key) < 32:
            raise ValueError("e2e_counter_configuration_invalid")
        self._path = path
        self._key = hashlib.sha256(b"e2e-call-counter\0" + key).digest()
        self._lock = threading.Lock()

    def increment(self, request_body_sha256: str) -> int:
        with self._lock:
            current = self.read()
            payload = {
                "call_count": current + 1,
                "request_body_sha256": request_body_sha256,
            }
            signed = {**payload, "counter_hmac_sha256": self._sign(payload)}
            atomic_private_write(self._path, canonical_bytes(signed))
            return current + 1

    def read(self) -> int:
        if not self._path.exists():
            return 0
        try:
            root = exact_object(
                json.loads(self._path.read_bytes()),
                {"call_count", "request_body_sha256", "counter_hmac_sha256"},
                "e2e_counter_invalid",
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise E2EVerificationError("e2e_counter_invalid") from None
        count = root["call_count"]
        request_sha = require_digest(root["request_body_sha256"], "e2e_counter_invalid")
        signature = require_digest(root["counter_hmac_sha256"], "e2e_counter_invalid")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 1
            or not hmac.compare_digest(
                signature, self._sign({"call_count": count, "request_body_sha256": request_sha})
            )
        ):
            raise E2EVerificationError("e2e_counter_invalid")
        return count

    def _sign(self, value: object) -> str:
        return hmac.new(self._key, canonical_bytes(value), hashlib.sha256).hexdigest()


class FakeRuntimeApplication:
    def __init__(
        self,
        *,
        config: FakeRuntimeConfig,
        counter: AuthenticatedCallCounter,
        canonicalizer: ReceiptCanonicalizer,
    ) -> None:
        self._config = config
        self._counter = counter
        self._canonicalizer = canonicalizer

    def complete(self, *, authorization: str | None, body: bytes) -> dict[str, object]:
        if authorization != "Bearer " + self._config.bearer_token:
            raise E2EVerificationError("e2e_fake_authentication_invalid")
        if not 1 <= len(body) <= _MAX_REQUEST_BYTES:
            raise E2EVerificationError("e2e_fake_request_invalid")
        request_sha = sha256_bytes(body)
        request = self._validate_request(body)
        if self._counter.increment(request_sha) != 1:
            raise E2EVerificationError("e2e_fake_second_provider_call")
        output_sha = hashlib.sha256(SYNTHETIC_OUTPUT.encode()).hexdigest()
        usage = {
            "prompt_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
            "completion_tokens": 0,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        }
        response_format = request["response_format"]
        assert isinstance(response_format, dict)
        schema = response_format["json_schema"]
        assert isinstance(schema, dict)
        metadata = {
            "schema_version": 2,
            "attestation_level": "provider_receipt",
            "usage_source": "codex_thread_token_usage_updated",
            "runtime_selection": {
                "account_binding_hmac_sha256": self._config.account_binding_hmac_sha256,
                "thread_id": "thread-provider-free-e2e",
                "turn_id": "turn-provider-free-e2e-1",
                "model": "gpt-5.6-sol",
                "model_provider": "openai",
                "reasoning_effort": "high",
                "service_tier": "default",
                "execution_profile": "stateless-completion",
                "base_instructions_sha256": self._config.base_instructions_sha256,
            },
            "request_identity": {
                "public_model": "gpt-5.6-sol",
                "client_requested_model": "gpt-5.6-sol",
                "configured_codex_model": "gpt-5.6-sol",
                "requested_codex_model": "gpt-5.6-sol",
                "request_body_sha256": request_sha,
                "response_format_type": "json_schema",
                "response_format_sha256": canonical_sha256(response_format),
                "response_schema_sha256": canonical_sha256(schema["schema"]),
            },
            "output_identity": {
                "output_text_sha256": output_sha,
                "terminal_status": "completed",
            },
            "output_token_limit": {"requested_tokens": 4096, "enforced": False},
            "receipt_hmac_sha256": "0" * 64,
        }
        receipt = sign_receipt(
            {"metadata": metadata, "usage": usage},
            secret=self._config.receipt_secret,
            canonicalizer=self._canonicalizer,
        )
        return {
            "id": "chatcmpl-provider-free-e2e",
            "object": "chat.completion",
            "created": 1,
            "model": "gpt-5.6-sol",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": SYNTHETIC_OUTPUT},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
            "system_fingerprint": "subscription-runtime-codex-bridge-v4:provider-free-e2e",
            "subscription_runtime": receipt["metadata"],
        }

    @staticmethod
    def _validate_request(body: bytes) -> dict[str, object]:
        try:
            root = exact_object(
                json.loads(body),
                {"max_tokens", "messages", "model", "response_format", "temperature"},
                "e2e_fake_request_invalid",
            )
            response_format = exact_object(
                root["response_format"],
                {"type", "json_schema"},
                "e2e_fake_request_invalid",
            )
            schema = exact_object(
                response_format["json_schema"],
                {"name", "strict", "schema"},
                "e2e_fake_request_invalid",
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise E2EVerificationError("e2e_fake_request_invalid") from None
        if (
            root["model"] != "gpt-5.6-sol"
            or root["max_tokens"] != 4096
            or root["temperature"] != 0
            or response_format["type"] != "json_schema"
            or schema["name"] != "mem0_memory_extraction_v5"
            or schema["strict"] is not True
            or not isinstance(schema["schema"], dict)
            or not isinstance(root["messages"], list)
            or len(root["messages"]) != 2
        ):
            raise E2EVerificationError("e2e_fake_request_invalid")
        return root


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(HTTPStatus.OK, {"ok": True, "provider_calls": 0})

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdecimal() or int(raw_length) > _MAX_REQUEST_BYTES:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request"})
            return
        try:
            value = self.server.application.complete(
                authorization=self.headers.get("Authorization"),
                body=self.rfile.read(int(raw_length)),
            )
        except E2EVerificationError as exc:
            status = (
                HTTPStatus.CONFLICT
                if str(exc) == "e2e_fake_second_provider_call"
                else HTTPStatus.BAD_REQUEST
            )
            self._json(status, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, value)

    def _json(self, status: HTTPStatus, value: object) -> None:
        body = canonical_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _Server(ThreadingHTTPServer):
    def __init__(self, application: FakeRuntimeApplication) -> None:
        super().__init__(("127.0.0.1", 8891), _Handler)
        self.application = application


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-repo", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--counter", type=Path, required=True)
    args = parser.parse_args()
    secret_dir = Path(os.environ["MEM0_V5_E2E_SECRET_DIR"])
    receipt_secret = read_private_text(secret_dir / "runtime-receipt-secret").encode()
    config = FakeRuntimeConfig(
        bearer_token=read_private_text(secret_dir / "runtime-bearer"),
        receipt_secret=receipt_secret,
        account_binding_hmac_sha256=require_digest(
            read_private_text(secret_dir / "account-binding-hmac-sha256")
        ),
        base_instructions_sha256=require_digest(
            read_private_text(secret_dir / "base-instructions-sha256")
        ),
    )
    application = FakeRuntimeApplication(
        config=config,
        counter=AuthenticatedCallCounter(args.counter, key=receipt_secret),
        canonicalizer=NodeReceiptCanonicalizer(
            runtime_repo=args.runtime_repo,
            node_executable=args.node,
        ),
    )
    _Server(application).serve_forever()


if __name__ == "__main__":
    main()
