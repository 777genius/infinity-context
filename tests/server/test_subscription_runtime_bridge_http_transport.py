from __future__ import annotations

import httpx
import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    BridgeTransportError,
    HttpxOneShotBridgeTransport,
)


def test_exact_post_headers_body_and_single_send() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            headers={"content-length": "11"},
            stream=_Chunks(b'{"ok":true}'),
        )

    transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(handler),
    )
    body = b'{"messages":[]}'

    response = transport.post_once(
        origin="http://127.0.0.1:43100",
        route="/v1/chat/completions",
        bearer_token="private-bearer",
        request_body=body,
        maximum_response_bytes=1024,
    )

    assert response == b'{"ok":true}'
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert str(calls[0].url) == "http://127.0.0.1:43100/v1/chat/completions"
    assert calls[0].headers["authorization"] == "Bearer private-bearer"
    assert calls[0].headers["accept-encoding"] == "identity"
    assert calls[0].content == body


def test_redirect_is_not_followed_and_failure_is_not_retried() -> None:
    redirects = 0

    def redirect_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal redirects
        redirects += 1
        return httpx.Response(307, headers={"location": "http://127.0.0.1:43101/other"})

    redirect_transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(redirect_handler),
    )
    with pytest.raises(BridgeTransportError, match="status_invalid"):
        _post(redirect_transport)
    assert redirects == 1

    failures = 0

    def failure_handler(request: httpx.Request) -> httpx.Response:
        nonlocal failures
        failures += 1
        raise httpx.ConnectError("provider-free simulated failure", request=request)

    failure_transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(failure_handler),
    )
    with pytest.raises(BridgeTransportError, match="transport_failed"):
        _post(failure_transport)
    assert failures == 1


def test_request_response_and_streamed_response_bounds() -> None:
    request_transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=2,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"{}")),
    )
    with pytest.raises(BridgeTransportError, match="request_size"):
        _post(request_transport, body=b"123")

    declared_transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"0123456789")),
    )
    with pytest.raises(BridgeTransportError, match="response_too_large"):
        _post(declared_transport, maximum_response_bytes=5)

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            yield b"123"
            yield b"456"

    streamed_transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=Chunks())),
    )
    with pytest.raises(BridgeTransportError, match="response_too_large"):
        _post(streamed_transport, maximum_response_bytes=5)


def test_streaming_does_not_retain_per_chunk_objects() -> None:
    class TrackedChunk(bytes):
        alive = 0

        def __new__(cls, value: bytes):
            instance = super().__new__(cls, value)
            cls.alive += 1
            return instance

        def __del__(self) -> None:
            type(self).alive -= 1

    class ManyChunks(httpx.SyncByteStream):
        def __iter__(self):
            for _index in range(100):
                assert TrackedChunk.alive <= 2
                yield TrackedChunk(b"x")

    transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=ManyChunks())),
    )

    assert _post(transport, maximum_response_bytes=100) == b"x" * 100


def test_environment_proxy_is_explicitly_disabled(monkeypatch) -> None:
    captured: dict[str, object] = {}
    real_client = httpx.Client

    class CapturingClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._inner = real_client(**kwargs)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *args) -> None:
            self._inner.__exit__(*args)

        def stream(self, *args, **kwargs):
            return self._inner.stream(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", CapturingClient)
    transport = HttpxOneShotBridgeTransport(
        maximum_request_bytes=1024,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=_Chunks(b"{}"))),
    )
    response = _post(transport)
    assert response == b"{}"
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False


def _post(
    transport: HttpxOneShotBridgeTransport,
    *,
    body: bytes = b"{}",
    maximum_response_bytes: int = 1024,
) -> bytes:
    return transport.post_once(
        origin="http://127.0.0.1:43100",
        route="/v1/chat/completions",
        bearer_token="private-bearer",
        request_body=body,
        maximum_response_bytes=maximum_response_bytes,
    )


class _Chunks(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks
