from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PHASE_C_ROOT = ROOT / "phase-c-canary"
sys.path.insert(0, str(PHASE_C_ROOT))

from phase_c_canary.receipt import NodePublicReceiptVerifier  # noqa: E402
from phase_c_canary.runtime_binding import RuntimeBindingComposition  # noqa: E402
from phase_c_canary.runtime_receipt_v2 import RuntimeReceiptV2Boundary  # noqa: E402

from mem0_oss_adapter_v5.domain import (  # noqa: E402
    AdapterContractError,
    OperationDispatchIntent,
    RuntimeCallDisposition,
    SanitizedRuntimeReceipt,
    require_authentic_runtime_outcome,
    require_authentic_runtime_result,
)
from mem0_oss_adapter_v5.extraction_contract import (  # noqa: E402
    EXTRACTION_MODEL,
    EXTRACTION_RESPONSE_FORMAT_SHA256,
    EXTRACTION_SCHEMA_SHA256,
    build_extraction_request,
)
from mem0_oss_adapter_v5.subscription_runtime import (  # noqa: E402
    MAX_RUNTIME_RESPONSE_BYTES,
    SUBSCRIPTION_RUNTIME_ENDPOINT,
    SUBSCRIPTION_RUNTIME_ORIGIN,
    EstablishedReceiptV2Authority,
    SubscriptionRuntimeClient,
    SubscriptionRuntimeError,
)

ACCOUNT_BINDING = "4" * 64
BASE_INSTRUCTIONS = "5" * 64
BEARER = "private-bearer-value"
RECEIPT_SECRET = "provider-free-fixture-secret-at-least-32-bytes"
RUNTIME_REPO = Path(
    "/mnt/volume_ams3_1784742570542/infinity-context/runtimes/subscription-runtime/e904ec95/repo"
)


def _request_and_intent() -> tuple[object, OperationDispatchIntent]:
    request = build_extraction_request(
        [{"role": "user", "content": "Alice likes tea."}],
        current_date="2026-08-06",
        timestamp="2024-03-10",
    )
    return request, OperationDispatchIntent(
        admission_commitment_sha256="a" * 64,
        operation_id_sha256="b" * 64,
        unit_identity_sha256="c" * 64,
        unit_sha256="d" * 64,
        scope_sha256="e" * 64,
        request_body_sha256=request.request_body_sha256,
        sequence=0,
    )


def _response(request: object, *, output: str | None = None) -> dict[str, object]:
    output = output or json.dumps(
        {
            "memory": [
                {
                    "id": "0",
                    "text": "Alice likes tea.",
                    "attributed_to": "user",
                    "linked_memory_ids": [],
                }
            ]
        },
        separators=(",", ":"),
    )
    output_hash = hashlib.sha256(output.encode()).hexdigest()
    usage = {
        "prompt_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 2},
        "completion_tokens": 4,
        "completion_tokens_details": {"reasoning_tokens": 1},
        "total_tokens": 14,
    }
    metadata = {
        "schema_version": 2,
        "attestation_level": "provider_receipt",
        "usage_source": "codex_thread_token_usage_updated",
        "runtime_selection": {
            "account_binding_hmac_sha256": ACCOUNT_BINDING,
            "thread_id": "thread-provider-free",
            "turn_id": "turn-provider-free",
            "model": EXTRACTION_MODEL,
            "model_provider": "openai",
            "reasoning_effort": "high",
            "service_tier": "default",
            "execution_profile": "stateless-completion",
            "base_instructions_sha256": BASE_INSTRUCTIONS,
        },
        "request_identity": {
            "public_model": EXTRACTION_MODEL,
            "client_requested_model": EXTRACTION_MODEL,
            "configured_codex_model": EXTRACTION_MODEL,
            "requested_codex_model": EXTRACTION_MODEL,
            "request_body_sha256": request.request_body_sha256,
            "response_format_type": "json_schema",
            "response_format_sha256": EXTRACTION_RESPONSE_FORMAT_SHA256,
            "response_schema_sha256": EXTRACTION_SCHEMA_SHA256,
        },
        "output_identity": {
            "output_text_sha256": output_hash,
            "terminal_status": "completed",
        },
        "output_token_limit": {"requested_tokens": request.max_tokens, "enforced": False},
        "receipt_hmac_sha256": "0" * 64,
    }
    receipt = _sign_receipt({"metadata": metadata, "usage": usage})
    return {
        "id": "chatcmpl-provider-free",
        "object": "chat.completion",
        "created": 1,
        "model": EXTRACTION_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": output},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
        "system_fingerprint": "subscription-runtime-codex-bridge-v4:fixture",
        "subscription_runtime": receipt["metadata"],
    }


def _sign_receipt(receipt: dict[str, object]) -> dict[str, object]:
    signed = copy.deepcopy(receipt)
    canonical_url = (
        RUNTIME_REPO / "dist/openai-compatible-codex/chat-completions/domain/runtime-attestation.js"
    ).as_uri()
    script = r"""
import {createHmac} from "node:crypto";
let body = ""; for await (const chunk of process.stdin) body += chunk;
const {receipt, secret, canonical_url} = JSON.parse(body); const m = receipt.metadata;
const {openAiBridgeRuntimeAttestationCanonicalBytes} = await import(canonical_url);
const bytes = openAiBridgeRuntimeAttestationCanonicalBytes({
  selection:m.runtime_selection, requestIdentity:m.request_identity,
  outputIdentity:m.output_identity, usage:receipt.usage,
  requestedOutputTokenLimit:m.output_token_limit.requested_tokens,
});
process.stdout.write(createHmac("sha256", secret).update(bytes).digest("hex"));
"""
    completed = subprocess.run(
        ["/usr/local/bin/node", "--input-type=module", "-e", script],
        cwd=RUNTIME_REPO,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        input=json.dumps(
            {"receipt": signed, "secret": RECEIPT_SECRET, "canonical_url": canonical_url}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    signed["metadata"]["receipt_hmac_sha256"] = completed.stdout
    return signed


def _authority(boundary: object | None = None) -> EstablishedReceiptV2Authority:
    binding = RuntimeBindingComposition.compose_phase_c_canary().issue()
    return EstablishedReceiptV2Authority(
        boundary=(
            RuntimeReceiptV2Boundary(NodePublicReceiptVerifier(RUNTIME_REPO))
            if boundary is None
            else boundary
        ),
        runtime_binding=binding,
        receipt_secret=RECEIPT_SECRET,
        runtime_source_sha256=binding.runtime_source_sha256,
    )


def _client(
    handler: object,
    *,
    authority: EstablishedReceiptV2Authority | None = None,
) -> SubscriptionRuntimeClient:
    return SubscriptionRuntimeClient(
        origin=SUBSCRIPTION_RUNTIME_ORIGIN,
        bearer_token=BEARER,
        expected_account_binding_hmac_sha256=ACCOUNT_BINDING,
        expected_base_instructions_sha256=BASE_INSTRUCTIONS,
        receipt_authority=_authority() if authority is None else authority,
        timeout_seconds=3,
        transport=httpx.MockTransport(handler),
    )


def test_exact_request_returns_only_parsed_memories_and_sanitized_receipt() -> None:
    request, intent = _request_and_intent()
    private_output = "Alice likes tea."
    seen: list[httpx.Request] = []

    def handler(raw: httpx.Request) -> httpx.Response:
        seen.append(raw)
        assert str(raw.url) == SUBSCRIPTION_RUNTIME_ENDPOINT
        assert raw.method == "POST"
        assert raw.headers["authorization"] == f"Bearer {BEARER}"
        assert raw.headers["accept-encoding"] == "identity"
        assert raw.content == request.body
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(request),
        )

    client = _client(handler)
    result = client.extract(request, intent)
    client.close()
    assert len(seen) == 1
    assert result.memories[0].text == private_output
    receipt_payload = result.receipt.public_payload()
    assert set(receipt_payload) == {"metadata", "usage"}
    serialized_receipt = json.dumps(receipt_payload, sort_keys=True)
    assert private_output not in serialized_receipt
    assert private_output not in repr(result)
    assert BEARER not in repr(client)
    assert result.outcome.disposition is RuntimeCallDisposition.RECEIPT_DURABLE
    assert result.outcome.redispatch_allowed is False


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8890",
        "http://127.0.0.1:8891",
        "https://127.0.0.1:8890",
        "http://127.0.0.1:8890/path",
        "http://user@127.0.0.1:8890",
    ],
)
def test_route_is_exact_not_merely_loopback(origin: str) -> None:
    with pytest.raises(AdapterContractError, match="mem0_v5_subscription_route_invalid"):
        SubscriptionRuntimeClient(
            origin=origin,
            bearer_token=BEARER,
            expected_account_binding_hmac_sha256=ACCOUNT_BINDING,
            expected_base_instructions_sha256=BASE_INSTRUCTIONS,
            receipt_authority=_authority(),
        )


def test_transport_failure_is_secret_safe_outcome_unknown_and_not_retried() -> None:
    request, intent = _request_and_intent()
    attempts = 0
    private_error = "provider-output-and-secret-value"

    def handler(raw: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(private_error, request=raw)

    client = _client(handler)
    with pytest.raises(SubscriptionRuntimeError) as caught:
        client.extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_transport_failed"
    assert caught.value.outcome.intent.commitment_payload() == intent.commitment_payload()
    assert caught.value.outcome.intent is not intent
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
    assert caught.value.outcome.redispatch_allowed is False
    assert private_error not in str(caught.value)
    assert private_error not in repr(caught.value)
    assert BEARER not in str(caught.value)
    assert attempts == 1
    with pytest.raises(SubscriptionRuntimeError, match="mem0_v5_subscription_operation_consumed"):
        client.extract(request, intent)
    assert attempts == 1


def test_unexpected_transport_exception_is_also_sanitized() -> None:
    request, intent = _request_and_intent()
    secret = "unexpected-private-transport-detail"

    def handler(_: httpx.Request) -> httpx.Response:
        raise RuntimeError(secret)

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_transport_failed"
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_redirect_is_not_followed_and_is_outcome_unknown() -> None:
    request, intent = _request_and_intent()
    attempts = 0

    def handler(raw: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(307, headers={"location": "http://127.0.0.1:8891/private"})

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_http_failed"
    assert caught.value.status_code == 307
    assert caught.value.outcome.intent.commitment_payload() == intent.commitment_payload()
    assert caught.value.outcome.intent is not intent
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
    assert attempts == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"raw_prompt": "private"}),
        lambda value: value["subscription_runtime"]["runtime_selection"].update(
            {"email": "private@example.test"}
        ),
        lambda value: value["subscription_runtime"]["request_identity"].update(
            {"request_body_sha256": "f" * 64}
        ),
        lambda value: value["subscription_runtime"]["output_identity"].update(
            {"output_text_sha256": "f" * 64}
        ),
        lambda value: value["usage"].update({"total_tokens": 15}),
        lambda value: value["subscription_runtime"].update({"receipt_hmac_sha256": "not-a-digest"}),
        lambda value: value["subscription_runtime"].update({"receipt_hmac_sha256": "f" * 64}),
    ],
)
def test_receipt_tamper_and_private_schema_drift_fail_closed(mutation: object) -> None:
    request, intent = _request_and_intent()
    payload = copy.deepcopy(_response(request))
    mutation(payload)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=payload,
        )

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_response_invalid"
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
    assert "private@example.test" not in str(caught.value)


def test_malformed_extraction_output_is_sanitized_after_one_attempt() -> None:
    request, intent = _request_and_intent()
    secret_output = "not-json-private-output"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(request, output=secret_output),
        )

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
    assert secret_output not in str(caught.value)
    assert secret_output not in repr(caught.value)


def test_receipt_verifier_internal_failure_is_sanitized() -> None:
    request, intent = _request_and_intent()
    secret = "private-verifier-internal-detail"

    class RaisingBoundary:
        def verify(self, **_: object) -> object:
            raise RuntimeError(secret)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(request),
        )

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler, authority=_authority(RaisingBoundary())).extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_response_invalid"
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)


def test_preflight_request_binding_error_does_not_attempt_transport() -> None:
    request, intent = _request_and_intent()
    bad_intent = OperationDispatchIntent(
        intent.admission_commitment_sha256,
        intent.operation_id_sha256,
        intent.unit_identity_sha256,
        intent.unit_sha256,
        intent.scope_sha256,
        "f" * 64,
        intent.sequence,
    )
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, bad_intent)
    assert caught.value.outcome.disposition is RuntimeCallDisposition.NOT_DISPATCHED
    assert caught.value.outcome.redispatch_allowed is True
    assert attempts == 0


def test_mutated_request_and_intent_impostors_are_rejected_before_transport() -> None:
    request, intent = _request_and_intent()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    client = _client(handler)
    object.__setattr__(request, "request_body_sha256", "f" * 64)
    with pytest.raises(SubscriptionRuntimeError) as caught:
        client.extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_request_invalid"
    assert caught.value.outcome is None
    assert attempts == 0

    request, intent = _request_and_intent()
    object.__setattr__(intent, "operation_id_sha256", "f" * 64)
    with pytest.raises(SubscriptionRuntimeError) as caught:
        client.extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_request_invalid"
    assert caught.value.outcome is None
    assert attempts == 0

    forged_request = object.__new__(type(request))
    with pytest.raises(SubscriptionRuntimeError, match="mem0_v5_subscription_request_invalid"):
        client.extract(forged_request, intent)
    assert attempts == 0


def test_safe_receipt_is_verifier_issued_and_result_mutation_is_detected() -> None:
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_receipt_unverified"):
        SanitizedRuntimeReceipt(
            {"metadata": {}, "usage": {}},
            verified_receipt_sha256="0" * 64,
        )

    request, intent = _request_and_intent()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(request),
        )

    result = _client(handler).extract(request, intent)
    require_authentic_runtime_result(result)
    object.__setattr__(result, "output_text_sha256", "f" * 64)
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_result_unauthentic"):
        require_authentic_runtime_result(result)


def test_runtime_outcome_is_sealed_and_nested_mutation_fails_closed() -> None:
    request, intent = _request_and_intent()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=_response(request),
        )

    result = _client(handler).extract(request, intent)
    outcome = result.outcome
    require_authentic_runtime_outcome(outcome)
    assert outcome.redispatch_allowed is False
    object.__setattr__(outcome, "disposition", RuntimeCallDisposition.NOT_DISPATCHED)
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_outcome_unauthentic"):
        _ = outcome.redispatch_allowed

    nested = result.outcome
    object.__setattr__(nested.intent, "operation_id_sha256", "f" * 64)
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_outcome_unauthentic"):
        require_authentic_runtime_outcome(nested)

    forged = object.__new__(type(outcome))
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_outcome_unauthentic"):
        require_authentic_runtime_outcome(forged)

    class OutcomeImpostor(type(outcome)):
        pass

    impostor = object.__new__(OutcomeImpostor)
    with pytest.raises(AdapterContractError, match="mem0_v5_runtime_outcome_unauthentic"):
        require_authentic_runtime_outcome(impostor)


def test_dispatch_snapshots_request_and_intent_before_lock_controlled_mutation() -> None:
    request, intent = _request_and_intent()
    original_body = request.body
    original_request_sha256 = request.request_body_sha256
    original_operation_sha256 = intent.operation_id_sha256
    response_payload = _response(request)
    private_raced_body = b"private-raced-prompt-that-must-never-leave"
    seen: list[bytes] = []

    def handler(raw: httpx.Request) -> httpx.Response:
        seen.append(raw.content)
        assert raw.headers["authorization"] == f"Bearer {BEARER}"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json=response_payload,
        )

    class MutatingLock:
        def __enter__(self) -> MutatingLock:
            object.__setattr__(request, "body", private_raced_body)
            object.__setattr__(request, "request_body_sha256", "f" * 64)
            object.__setattr__(intent, "operation_id_sha256", "e" * 64)
            object.__setattr__(intent, "request_body_sha256", "f" * 64)
            return self

        def __exit__(self, *_: object) -> None:
            return None

    client = _client(handler)
    object.__setattr__(client, "_lock", MutatingLock())
    result = client.extract(request, intent)
    assert seen == [original_body]
    assert private_raced_body not in seen
    assert result.intent.operation_id_sha256 == original_operation_sha256
    assert result.intent.request_body_sha256 == original_request_sha256
    assert original_operation_sha256 in client._consumed_operations
    assert "e" * 64 not in client._consumed_operations


def test_content_type_bound_fails_closed() -> None:
    request, intent = _request_and_intent()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"x" * 10,
        )

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN


def test_declared_response_size_bound_fails_before_body_parse() -> None:
    request, intent = _request_and_intent()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-length": str(MAX_RUNTIME_RESPONSE_BYTES + 1),
            },
            content=b"{}",
        )

    with pytest.raises(SubscriptionRuntimeError) as caught:
        _client(handler).extract(request, intent)
    assert caught.value.code == "mem0_v5_subscription_response_invalid"
    assert caught.value.outcome.disposition is RuntimeCallDisposition.OUTCOME_UNKNOWN
