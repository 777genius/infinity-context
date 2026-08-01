from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from infinity_context_server.memory_comparison_provider_provenance import (
    canonical_request_sha256,
)
from infinity_context_server.memory_comparison_subscription_chat import (
    SubscriptionChatClosedError,
    SubscriptionRuntimeChatCompletions,
)
from infinity_context_server.memory_comparison_subscription_live_probe import (
    SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
    SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS,
    SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT,
    SUBSCRIPTION_LIVE_PROBE_USER_PROMPT,
    SubscriptionRuntimeLiveProbeError,
    run_subscription_runtime_live_probe,
)
from infinity_context_server.memory_comparison_subscription_probe import (
    inspect_verified_subscription_runtime_probe,
)

_MODEL = "gpt-5.6-sol"
_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> SubscriptionRuntimeChatCompletions:
    return SubscriptionRuntimeChatCompletions(
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )


def _success_payload(
    *,
    text: str = SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE,
    prompt_tokens: int = 19,
    completion_tokens: int = 2,
    include_usage: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ]
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    return payload


def test_one_attempt_seals_only_canonical_digests_and_usage_then_closes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    planned_route = adapter.route_attestation

    evidence = run_subscription_runtime_live_probe(
        adapter,
        expected_route=planned_route,
        model=_MODEL,
        clock=lambda: _NOW,
    )

    assert len(requests) == 1
    request_payload = json.loads(requests[0].content)
    assert request_payload == {
        "max_tokens": SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT},
            {"role": "user", "content": SUBSCRIPTION_LIVE_PROBE_USER_PROMPT},
        ],
        "model": _MODEL,
    }
    observation = inspect_verified_subscription_runtime_probe(evidence, now=_NOW)
    assert observation.model == _MODEL
    assert observation.total_tokens == 21
    assert observation.route.response_status == 200
    assert observation.request_evidence_sha256 == canonical_request_sha256(
        endpoint_path=planned_route.endpoint_path,
        payload=request_payload,
    )
    assert len(observation.response_evidence_sha256) == 64
    public_json = json.dumps(observation.public_payload(), sort_keys=True)
    assert SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT not in public_json
    assert SUBSCRIPTION_LIVE_PROBE_USER_PROMPT not in public_json
    assert SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE not in public_json

    with pytest.raises(SubscriptionChatClosedError):
        adapter.complete(
            model=_MODEL,
            system_prompt="unused",
            user_prompt="unused",
            max_output_tokens=1,
        )


def test_retryable_http_failure_is_one_attempt_sanitized_and_closed() -> None:
    secret = "private-response-body"
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text=secret)

    adapter = _adapter(handler)

    with pytest.raises(SubscriptionRuntimeLiveProbeError) as raised:
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1
    assert raised.value.code == "subscription_live_probe_failed"
    assert str(raised.value) == "subscription_live_probe_failed"
    assert secret not in repr(raised.value)
    with pytest.raises(SubscriptionChatClosedError):
        adapter.complete(
            model=_MODEL,
            system_prompt="unused",
            user_prompt="unused",
            max_output_tokens=1,
        )


@pytest.mark.parametrize(
    ("payload", "code"),
    (
        (
            _success_payload(text="READY!"),
            "subscription_live_probe_response_invalid",
        ),
        (
            _success_payload(completion_tokens=SUBSCRIPTION_LIVE_PROBE_MAX_OUTPUT_TOKENS + 1),
            "subscription_live_probe_usage_invalid",
        ),
        (
            _success_payload(include_usage=False),
            "subscription_live_probe_usage_invalid",
        ),
        (
            _success_payload(prompt_tokens=511, completion_tokens=2),
            "subscription_live_probe_usage_invalid",
        ),
    ),
)
def test_invalid_response_or_usage_fails_closed_after_one_attempt(
    payload: dict[str, object],
    code: str,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    adapter = _adapter(handler)

    with pytest.raises(SubscriptionRuntimeLiveProbeError) as raised:
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1
    assert raised.value.code == code
    with pytest.raises(SubscriptionChatClosedError):
        adapter.complete(
            model=_MODEL,
            system_prompt="unused",
            user_prompt="unused",
            max_output_tokens=1,
        )


def test_route_mismatch_is_rejected_before_attempt_and_adapter_is_closed() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    mismatched = replace(
        adapter.route_attestation,
        credential_binding_id="sha256:" + ("7" * 64),
    )

    with pytest.raises(
        SubscriptionRuntimeLiveProbeError,
        match="subscription_live_probe_route_invalid",
    ):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=mismatched,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 0
    with pytest.raises(SubscriptionChatClosedError):
        adapter.complete(
            model=_MODEL,
            system_prompt="unused",
            user_prompt="unused",
            max_output_tokens=1,
        )


def test_clock_failure_is_sanitized_after_exactly_one_attempt() -> None:
    calls = 0
    secret = "private-clock-error"

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    def bad_clock() -> datetime:
        raise RuntimeError(secret)

    adapter = _adapter(handler)
    with pytest.raises(SubscriptionRuntimeLiveProbeError) as raised:
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=_MODEL,
            clock=bad_clock,
        )

    assert calls == 1
    assert raised.value.code == "subscription_live_probe_failed"
    assert secret not in repr(raised.value)


def test_invalid_model_is_rejected_without_provider_attempt() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    with pytest.raises(
        SubscriptionRuntimeLiveProbeError,
        match="subscription_live_probe_request_invalid",
    ):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=" model-with-spaces ",
            clock=lambda: _NOW,
        )

    assert calls == 0
