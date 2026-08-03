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
    SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
    SubscriptionChatClosedError,
    SubscriptionChatRequestError,
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
    include_provenance: bool = True,
    observed_model: str = _MODEL,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
    if include_usage:
        payload["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "usage_source": SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE,
        }
    if include_provenance:
        payload.update(
            {
                "id": "chatcmpl-subscription-probe-1",
                "model": observed_model,
                "system_fingerprint": "subscription-runtime-codex-bridge-v1",
            }
        )
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
    assert observation.usage_source == SUBSCRIPTION_RUNTIME_ESTIMATED_USAGE_SOURCE
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


def test_missing_bridge_usage_uses_bounded_adapter_estimate() -> None:
    adapter = _adapter(lambda _: httpx.Response(200, json=_success_payload(include_usage=False)))

    evidence = run_subscription_runtime_live_probe(
        adapter,
        expected_route=adapter.route_attestation,
        model=_MODEL,
        clock=lambda: _NOW,
    )

    observation = inspect_verified_subscription_runtime_probe(evidence, now=_NOW)
    estimated_prompt = (
        len(f"{SUBSCRIPTION_LIVE_PROBE_SYSTEM_PROMPT}\n{SUBSCRIPTION_LIVE_PROBE_USER_PROMPT}") + 3
    ) // 4
    estimated_completion = (len(SUBSCRIPTION_LIVE_PROBE_EXPECTED_RESPONSE) + 3) // 4
    assert observation.total_tokens == estimated_prompt + estimated_completion
    assert observation.usage_source == "estimated_by_subscription_adapter"


@pytest.mark.parametrize(
    "payload",
    [
        _success_payload(include_provenance=False),
        _success_payload(observed_model="gpt-5.6-different"),
        {
            **_success_payload(),
            "system_fingerprint": " unsafe fingerprint ",
        },
    ],
)
def test_missing_or_mismatched_provenance_fails_closed(
    payload: dict[str, object],
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    adapter = _adapter(handler)
    with pytest.raises(
        SubscriptionRuntimeLiveProbeError,
        match="subscription_live_probe_response_invalid",
    ):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1


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


def test_prior_success_cannot_be_hidden_by_a_later_readiness_probe() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    planned_route = adapter.route_attestation
    adapter.complete(
        model=_MODEL,
        system_prompt="ordinary",
        user_prompt="ordinary",
        max_output_tokens=8,
    )

    with pytest.raises(SubscriptionRuntimeLiveProbeError):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=planned_route,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1


def test_prior_unknown_delivery_cannot_be_hidden_by_successful_second_response() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("private timeout", request=request)
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    planned_route = adapter.route_attestation
    with pytest.raises(SubscriptionChatRequestError):
        adapter.complete(
            model=_MODEL,
            system_prompt="ordinary",
            user_prompt="ordinary",
            max_output_tokens=8,
        )

    with pytest.raises(SubscriptionRuntimeLiveProbeError):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=planned_route,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1


def test_retry_capable_adapter_is_ineligible_even_before_first_attempt() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    adapter = SubscriptionRuntimeChatCompletions(
        transport=httpx.MockTransport(handler),
        max_retries=1,
    )

    with pytest.raises(SubscriptionRuntimeLiveProbeError):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=adapter.route_attestation,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 0


def test_transport_error_burns_the_only_probe_attempt() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("private connection detail", request=request)

    adapter = _adapter(handler)
    planned_route = adapter.route_attestation

    with pytest.raises(SubscriptionRuntimeLiveProbeError) as raised:
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=planned_route,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert raised.value.code == "subscription_live_probe_failed"
    assert calls == 1
    with pytest.raises(SubscriptionRuntimeLiveProbeError):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=planned_route,
            model=_MODEL,
            clock=lambda: _NOW,
        )
    assert calls == 1


def test_successful_probe_is_single_use_and_second_probe_cannot_send() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_success_payload())

    adapter = _adapter(handler)
    planned_route = adapter.route_attestation
    run_subscription_runtime_live_probe(
        adapter,
        expected_route=planned_route,
        model=_MODEL,
        clock=lambda: _NOW,
    )

    with pytest.raises(SubscriptionRuntimeLiveProbeError):
        run_subscription_runtime_live_probe(
            adapter,
            expected_route=planned_route,
            model=_MODEL,
            clock=lambda: _NOW,
        )

    assert calls == 1
