from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import infinity_context_server.memory_comparison_subscription_chat as subject
import pytest
from infinity_context_server.memory_comparison_subscription_chat import (
    MAX_RESPONSE_BODY_BYTES,
    SUBSCRIPTION_CHAT_ENDPOINT_PATH,
    SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE,
    SUBSCRIPTION_RUNTIME_TRUST,
    SubscriptionChatClosedError,
    SubscriptionChatHTTPError,
    SubscriptionChatMalformedResponseError,
    SubscriptionChatRequestTooLargeError,
    SubscriptionChatResponseTooLargeError,
    SubscriptionRuntimeChatCompletions,
)


def _payload(*, usage: object = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "bridge answer"},
                "finish_reason": "stop",
            }
        ]
    }
    if usage is not None:
        payload["usage"] = usage
    return payload


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> SubscriptionRuntimeChatCompletions:
    return SubscriptionRuntimeChatCompletions(transport=httpx.MockTransport(handler), **kwargs)


def test_request_response_route_and_secret_safety() -> None:
    secret = "private-subscription-token"
    observed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json=_payload(usage={"prompt_tokens": 21, "completion_tokens": 7}),
        )

    adapter = _adapter(handler, bearer_token=secret)
    try:
        assert adapter.route_attestation.response_status == 0
        completion = adapter.complete(
            model="gpt-5.6-codex",
            system_prompt="system",
            user_prompt="question",
            max_output_tokens=321,
        )
        route = adapter.route_attestation
    finally:
        adapter.close()

    request = observed[0]
    assert request.method == "POST"
    assert str(request.url) == ("http://127.0.0.1:8890" + SUBSCRIPTION_CHAT_ENDPOINT_PATH)
    assert request.headers["authorization"] == f"Bearer {secret}"
    assert request.headers["accept-encoding"] == "identity"
    assert json.loads(request.content) == {
        "max_tokens": 321,
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
        ],
        "model": "gpt-5.6-codex",
    }
    assert completion.text == "bridge answer"
    assert (completion.prompt_tokens, completion.completion_tokens) == (21, 7)
    assert completion.token_usage_source == "provider_observed"
    assert completion.finish_reason == "stop"
    assert completion.finish_reason_source == "provider_observed"
    assert completion.provenance is None
    assert route.trust == SUBSCRIPTION_RUNTIME_TRUST
    assert route.origin == "http://127.0.0.1:8890"
    assert route.endpoint_path == SUBSCRIPTION_CHAT_ENDPOINT_PATH
    assert route.transport_evidence == SUBSCRIPTION_RUNTIME_TRANSPORT_EVIDENCE
    assert route.request_method == "POST"
    assert route.response_status == 200
    assert route.credential_binding_id is not None
    assert route.credential_binding_id.startswith("sha256:")
    assert secret not in repr(adapter)
    assert secret not in json.dumps(route.public_payload())
    assert adapter.output_limit_evidence == SUBSCRIPTION_OUTPUT_LIMIT_EVIDENCE


def test_optional_controls_and_estimated_usage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload())

    adapter = _adapter(handler)
    try:
        completion = adapter.complete(
            model="gpt-5.6-codex",
            system_prompt="abc",
            user_prompt="defgh",
            max_output_tokens=42,
            temperature=0,
            response_format={"type": "json_object"},
        )
    finally:
        adapter.close()

    request = json.loads(requests[0].content)
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert (completion.prompt_tokens, completion.completion_tokens) == (3, 4)
    assert completion.token_usage_source == "estimated_by_subscription_adapter"


def test_client_disables_env_proxy_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.Client
    client_kwargs: list[dict[str, object]] = []
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/private"})

    def client_factory(**kwargs: object) -> httpx.Client:
        client_kwargs.append(dict(kwargs))
        return original_client(**kwargs)

    monkeypatch.setattr(subject.httpx, "Client", client_factory)
    adapter = SubscriptionRuntimeChatCompletions(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(SubscriptionChatHTTPError) as raised:
            adapter.complete(
                model="gpt-5.6-codex",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
            )
    finally:
        adapter.close()

    assert calls == 1
    assert raised.value.status_code == 302
    assert str(raised.value) == "subscription_chat_http_error"
    assert client_kwargs[0]["follow_redirects"] is False
    assert client_kwargs[0]["trust_env"] is False


@pytest.mark.parametrize(
    "origin",
    [
        "http://10.0.0.1:8890",
        "http://169.254.169.254:8890",
        "http://[::ffff:127.0.0.1]:8890",
        "http://localhost:8890",
        "http://user:pass@127.0.0.1:8890",
        "http://127.0.0.1:8890?target=private",
        "http://127.0.0.1:8890/#fragment",
        "http://127.0.0.1:8890/custom",
    ],
)
def test_rejects_unsafe_origin_before_client(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    def forbidden_client(**_: object) -> None:
        raise AssertionError("HTTP client must not be created")

    monkeypatch.setattr(subject.httpx, "Client", forbidden_client)
    with pytest.raises(ValueError, match="loopback URL"):
        SubscriptionRuntimeChatCompletions(origin=origin)


def test_normalizes_ipv6_loopback() -> None:
    adapter = SubscriptionRuntimeChatCompletions(
        origin="http://[0:0:0:0:0:0:0:1]:8890",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=_payload())),
    )
    try:
        assert adapter.route_attestation.origin == "http://[::1]:8890"
    finally:
        adapter.close()


def test_bounded_response_and_fixed_error() -> None:
    private_body = "private-response-body"
    adapter = _adapter(
        lambda _: httpx.Response(
            200,
            content=private_body.encode(),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(MAX_RESPONSE_BODY_BYTES + 1),
            },
        )
    )
    try:
        with pytest.raises(SubscriptionChatResponseTooLargeError) as raised:
            adapter.complete(
                model="gpt-5.6-codex",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
            )
    finally:
        adapter.close()
    assert str(raised.value) == "subscription_chat_response_too_large"
    assert private_body not in str(raised.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "user", "content": "private-malformed-output"}}]
            },
        ),
    ],
)
def test_malformed_response_is_sanitized(response: httpx.Response) -> None:
    adapter = _adapter(lambda _: response)
    try:
        with pytest.raises(SubscriptionChatMalformedResponseError) as raised:
            adapter.complete(
                model="gpt-5.6-codex",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
            )
    finally:
        adapter.close()
    assert str(raised.value) == "subscription_chat_malformed_response"
    assert "private-malformed-output" not in str(raised.value)


def test_http_error_never_exposes_response_or_bearer() -> None:
    secret = "private-bearer-token"
    private_body = f"failure body with {secret}"
    adapter = _adapter(
        lambda _: httpx.Response(500, text=private_body),
        bearer_token=secret,
    )
    try:
        with pytest.raises(SubscriptionChatHTTPError) as raised:
            adapter.complete(
                model="gpt-5.6-codex",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
            )
    finally:
        adapter.close()

    assert raised.value.status_code == 500
    assert str(raised.value) == "subscription_chat_http_error"
    assert secret not in str(raised.value)
    assert private_body not in str(raised.value)
    assert secret not in repr(adapter)


def test_controls_size_and_close() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=_payload(usage={"prompt_tokens": 1, "completion_tokens": 2}),
        )

    adapter = _adapter(handler)
    try:
        with pytest.raises(ValueError, match="temperature"):
            adapter.complete(
                model="m",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
                temperature=0.1,
            )
        with pytest.raises(ValueError, match="response format"):
            adapter.complete(
                model="m",
                system_prompt="s",
                user_prompt="u",
                max_output_tokens=10,
                response_format={"type": "text"},
            )
        with pytest.raises(SubscriptionChatRequestTooLargeError):
            adapter.complete(
                model="m",
                system_prompt="x" * 1_048_576,
                user_prompt="u",
                max_output_tokens=10,
            )
        completion = adapter.complete(
            model="m",
            system_prompt="s",
            user_prompt="u",
            max_output_tokens=10,
        )
    finally:
        adapter.close()
    assert calls == 1
    assert completion.text == "bridge answer"
    adapter.close()
    with pytest.raises(SubscriptionChatClosedError):
        adapter.complete(
            model="m",
            system_prompt="s",
            user_prompt="u",
            max_output_tokens=10,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 181},
        {"timeout_seconds": 0},
        {"max_retries": 2},
        {"max_retries": 1},
        {"max_retries": -1},
        {"bearer_token": object()},
    ],
)
def test_constructor_bounds(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SubscriptionRuntimeChatCompletions(**kwargs)
