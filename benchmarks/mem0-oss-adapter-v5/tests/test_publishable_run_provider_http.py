from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from publishable_mem0_v5 import run_provider_preflight

from tests.publishable_run_provider_http_test_support import (
    StreamingClient,
    StreamingResponse,
    runtime_attestation_request,
)


def _key(label: str) -> bytes:
    return hashlib.sha256(f"private-key:{label}".encode()).digest()


def test_endpoint_attestation_streams_and_parses_bounded_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = json.dumps(
        {"provider_calls": 0, "schema_version": "test-response.v1"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    response = StreamingResponse((raw[:11], raw[11:]))
    client = StreamingClient(response)
    monkeypatch.setattr(httpx, "Client", client.construct)

    payload = run_provider_preflight._post_runtime_attestation(
        endpoint="http://127.0.0.1:29192",
        timeout_seconds=3,
        root_secret=_key("streaming-root"),
        request=runtime_attestation_request(),
    )

    assert payload == {"provider_calls": 0, "schema_version": "test-response.v1"}
    assert response.chunk_reads == 2
    assert response.content_reads == 0
    assert client.init_kwargs == {
        "base_url": "http://127.0.0.1:29192",
        "follow_redirects": False,
        "timeout": 3,
        "trust_env": False,
    }
    assert client.stream_calls[0][0] == ("POST", "/v5/runtime/attest")


def test_endpoint_attestation_stops_streaming_immediately_above_32_kib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = StreamingResponse(
        (b"x" * (32 * 1024), b"x", b"must-not-be-read"),
        fail_if_third_chunk_is_read=True,
    )
    client = StreamingClient(response)
    monkeypatch.setattr(httpx, "Client", client.construct)

    with pytest.raises(PublishableRunError, match="endpoint_attestation_failed"):
        run_provider_preflight._post_runtime_attestation(
            endpoint="http://127.0.0.1:29192",
            timeout_seconds=3,
            root_secret=_key("streaming-root"),
            request=runtime_attestation_request(),
        )

    assert response.chunk_reads == 2
    assert response.content_reads == 0
