from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

BENCHMARKS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BENCHMARKS_ROOT / "phase-c-canary"))

from phase_c_canary.receipt import NodePublicReceiptVerifier  # noqa: E402
from phase_c_canary.runtime_binding import RuntimeBindingComposition  # noqa: E402
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary  # noqa: E402

from e2e.canonical import canonical_bytes, canonical_sha256  # noqa: E402
from e2e.contracts import SYNTHETIC_OUTPUT  # noqa: E402
from e2e.fake_runtime import (  # noqa: E402
    AuthenticatedCallCounter,
    FakeRuntimeApplication,
    FakeRuntimeConfig,
)
from e2e.receipt import NodeReceiptCanonicalizer, ReceiptAuthority, ReceiptVerifier  # noqa: E402
from mem0_oss_adapter_v5.domain import OperationDispatchIntent  # noqa: E402
from mem0_oss_adapter_v5.extraction_contract import build_extraction_request  # noqa: E402
from mem0_oss_adapter_v5.subscription_runtime import (  # noqa: E402
    SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN,
    EstablishedReceiptV2Authority,
    SubscriptionRuntimeClient,
)

_HOSTING_RUNTIME_AUTHORITY = Path(
    "/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/"
    "e2e-runtime-authorities/e904ec95-uid65532-host296603"
)
_HOSTING_NODE = Path(
    "/mnt/volume_ams3_1784742570542/infinity-locomo-benchmark/"
    "e2e-runtime-authorities/node-b2959781/node"
)
_HOSTING_NODE_SHA256 = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"


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


def test_zero_usage_crosses_fake_runtime_and_established_authority(tmp_path) -> None:
    runtime_repo = _HOSTING_RUNTIME_AUTHORITY / "repo"
    artifact_manifest = _HOSTING_RUNTIME_AUTHORITY / "artifact-manifest.json"
    if not runtime_repo.is_dir() or not artifact_manifest.is_file() or not _HOSTING_NODE.is_file():
        pytest.skip("immutable hosting runtime authority is unavailable")
    assert __import__("hashlib").sha256(_HOSTING_NODE.read_bytes()).hexdigest() == (
        _HOSTING_NODE_SHA256
    )

    bearer = "b" * 64
    receipt_secret = b"r" * 64
    account = canonical_sha256("provider-free-e2e-account")
    base = canonical_sha256("provider-free-e2e-base-instructions")
    canonicalizer = NodeReceiptCanonicalizer(
        runtime_repo=runtime_repo,
        node_executable=_HOSTING_NODE,
    )
    application = FakeRuntimeApplication(
        config=FakeRuntimeConfig(bearer, receipt_secret, account, base),
        counter=AuthenticatedCallCounter(tmp_path / "counter.json", key=receipt_secret),
        canonicalizer=canonicalizer,
    )
    request = build_extraction_request(
        [{"role": "user", "content": "Alice likes tea."}],
        current_date="2026-08-06",
        timestamp="2024-03-10",
    )
    intent = OperationDispatchIntent(
        admission_commitment_sha256="a" * 64,
        operation_id_sha256="b" * 64,
        unit_identity_sha256="c" * 64,
        unit_sha256="d" * 64,
        scope_sha256="e" * 64,
        request_body_sha256=request.request_body_sha256,
        sequence=0,
    )
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    authority = EstablishedReceiptV2Authority(
        boundary=RuntimeReceiptV2Boundary(
            NodePublicReceiptVerifier(runtime_repo, node_executable=_HOSTING_NODE)
        ),
        runtime_binding=binding,
        receipt_secret=receipt_secret.decode(),
        runtime_source_sha256=binding.runtime_source_sha256,
    )

    def handler(raw: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=application.complete(
                authorization=raw.headers.get("authorization"),
                body=raw.content,
            ),
        )

    client = SubscriptionRuntimeClient(
        transport_origin=SUBSCRIPTION_RUNTIME_TRANSPORT_ORIGIN,
        bearer_token=bearer,
        expected_account_binding_hmac_sha256=account,
        expected_base_instructions_sha256=base,
        receipt_authority=authority,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.extract(request, intent)
    finally:
        client.close()

    assert result.memories[0].text == "Alice likes tea."
    assert result.receipt.public_payload()["usage"] == {
        "prompt_tokens": 0,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens": 0,
        "completion_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 0,
    }
