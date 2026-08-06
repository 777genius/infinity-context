from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from e2e.canonical import canonical_bytes, canonical_sha256
from e2e.contracts import SYNTHETIC_OUTPUT
from e2e.fake_runtime import (
    AuthenticatedCallCounter,
    FakeRuntimeApplication,
    FakeRuntimeConfig,
)
from e2e.receipt import NodeReceiptCanonicalizer, ReceiptAuthority, ReceiptVerifier


class _Canonicalizer:
    def canonical_bytes(self, receipt: dict[str, object]) -> bytes:
        metadata = receipt["metadata"]
        assert isinstance(metadata, dict)
        return canonical_bytes(
            {
                "selection": metadata["runtime_selection"],
                "request_identity": metadata["request_identity"],
                "output_identity": metadata["output_identity"],
                "usage": receipt["usage"],
                "requested_tokens": metadata["output_token_limit"]["requested_tokens"],
            }
        )


def _request() -> bytes:
    schema = {
        "type": "object",
        "properties": {"memory": {"type": "array"}},
        "required": ["memory"],
        "additionalProperties": False,
    }
    return canonical_bytes(
        {
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": "synthetic-system"},
                {"role": "user", "content": "synthetic-user"},
            ],
            "model": "gpt-5.6-sol",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "mem0_memory_extraction_v5",
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": 0,
        }
    )


def test_fake_runtime_issues_zero_token_authentic_receipt_once(tmp_path) -> None:
    secret = b"r" * 32
    account = canonical_sha256("account")
    base = canonical_sha256("base")
    counter = AuthenticatedCallCounter(tmp_path / "counter.json", key=secret)
    application = FakeRuntimeApplication(
        config=FakeRuntimeConfig("b" * 32, secret, account, base),
        counter=counter,
        canonicalizer=_Canonicalizer(),
    )
    request = _request()
    response = application.complete(authorization="Bearer " + "b" * 32, body=request)
    receipt = {
        "metadata": response["subscription_runtime"],
        "usage": response["usage"],
    }
    response_format = json.loads(request)["response_format"]
    verifier = ReceiptVerifier(
        authority=ReceiptAuthority(
            account_binding_hmac_sha256=account,
            base_instructions_sha256=base,
            request_body_sha256=__import__("hashlib").sha256(request).hexdigest(),
            response_format_sha256=canonical_sha256(response_format),
            response_schema_sha256=canonical_sha256(response_format["json_schema"]["schema"]),
            output_text_sha256=__import__("hashlib").sha256(SYNTHETIC_OUTPUT.encode()).hexdigest(),
        ),
        receipt_secret=secret,
        canonicalizer=_Canonicalizer(),
    )
    assert len(verifier.verify(receipt)) == 64
    assert response["usage"]["total_tokens"] == 0
    assert counter.read() == 1
    assert b"synthetic-user" not in (tmp_path / "counter.json").read_bytes()
    with pytest.raises(RuntimeError, match="e2e_fake_second_provider_call"):
        application.complete(authorization="Bearer " + "b" * 32, body=request)
    assert counter.read() == 2


def test_receipt_hmac_tamper_is_rejected(tmp_path) -> None:
    secret = b"r" * 32
    account = canonical_sha256("account")
    base = canonical_sha256("base")
    request = _request()
    response = FakeRuntimeApplication(
        config=FakeRuntimeConfig("b" * 32, secret, account, base),
        counter=AuthenticatedCallCounter(tmp_path / "counter.json", key=secret),
        canonicalizer=_Canonicalizer(),
    ).complete(authorization="Bearer " + "b" * 32, body=request)
    receipt = {"metadata": response["subscription_runtime"], "usage": response["usage"]}
    forged = deepcopy(receipt)
    forged["metadata"]["receipt_hmac_sha256"] = "f" * 64
    response_format = json.loads(request)["response_format"]
    verifier = ReceiptVerifier(
        authority=ReceiptAuthority(
            account,
            base,
            __import__("hashlib").sha256(request).hexdigest(),
            canonical_sha256(response_format),
            canonical_sha256(response_format["json_schema"]["schema"]),
            __import__("hashlib").sha256(SYNTHETIC_OUTPUT.encode()).hexdigest(),
        ),
        receipt_secret=secret,
        canonicalizer=_Canonicalizer(),
    )
    with pytest.raises(RuntimeError, match="e2e_receipt_unauthenticated"):
        verifier.verify(forged)


def test_receipt_round_trip_invokes_immutable_e904_js_canonicalizer(tmp_path) -> None:
    authority = Path(
        os.environ.get(
            "MEM0_V5_RUNTIME_AUTHORITY_DIR",
            "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95",
        )
    )
    runtime_repo = authority / "repo"
    node = Path(os.environ.get("MEM0_V5_NODE_EXECUTABLE_SOURCE", "/usr/local/bin/node"))
    module = (
        runtime_repo / "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
    )
    if not module.is_file() or not node.is_file():
        pytest.skip("immutable e904 JS authority is unavailable on this test host")
    secret = b"r" * 32
    account = canonical_sha256("account")
    base = canonical_sha256("base")
    request = _request()
    canonicalizer = NodeReceiptCanonicalizer(runtime_repo=runtime_repo, node_executable=node)
    response = FakeRuntimeApplication(
        config=FakeRuntimeConfig("b" * 32, secret, account, base),
        counter=AuthenticatedCallCounter(tmp_path / "counter.json", key=secret),
        canonicalizer=canonicalizer,
    ).complete(authorization="Bearer " + "b" * 32, body=request)
    receipt = {"metadata": response["subscription_runtime"], "usage": response["usage"]}
    response_format = json.loads(request)["response_format"]
    verifier = ReceiptVerifier(
        authority=ReceiptAuthority(
            account,
            base,
            __import__("hashlib").sha256(request).hexdigest(),
            canonical_sha256(response_format),
            canonical_sha256(response_format["json_schema"]["schema"]),
            __import__("hashlib").sha256(SYNTHETIC_OUTPUT.encode()).hexdigest(),
        ),
        receipt_secret=secret,
        canonicalizer=canonicalizer,
    )
    assert len(verifier.verify(receipt)) == 64
