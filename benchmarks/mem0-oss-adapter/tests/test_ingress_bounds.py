from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mem0_oss_adapter.app import (
    _MAX_BODY_FRAGMENTS,
    _MAX_EMPTY_BODY_FRAGMENTS,
    _BoundedIngressBodyMiddleware,
    create_app,
)
from mem0_oss_adapter.models import (
    MAX_MESSAGE_CONTENT_BYTES,
    MAX_MESSAGE_COUNT,
    MAX_METADATA_BYTES,
    MAX_QUERY_BYTES,
    MAX_REQUEST_BODY_BYTES,
    AddRequest,
    Message,
    PersistedSourceMetadata,
    SearchRequest,
)

from .conftest import FakeOssPort


def _metadata(*, blob: str = "", nested: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": "source-1",
        "source_sha256": "a" * 64,
        "blob": blob,
    }
    if nested is not None:
        payload["nested"] = nested
    return payload


def _add_request(*, metadata: dict[str, object] | None = None) -> AddRequest:
    return AddRequest(
        messages=[{"role": "user", "content": "x"}],
        user_id="user-1",
        run_id="run-1",
        metadata=_metadata() if metadata is None else metadata,
        timestamp=1,
    )


def test_message_count_and_utf8_content_caps_are_exact() -> None:
    assert (
        len(
            AddRequest(
                messages=[{"role": "user", "content": "x"}] * MAX_MESSAGE_COUNT,
                user_id="user-1",
                run_id="run-1",
                metadata=_metadata(),
                timestamp=1,
            ).messages
        )
        == MAX_MESSAGE_COUNT
    )
    with pytest.raises(ValueError):
        AddRequest(
            messages=[{"role": "user", "content": "x"}] * (MAX_MESSAGE_COUNT + 1),
            user_id="user-1",
            run_id="run-1",
            metadata=_metadata(),
            timestamp=1,
        )

    assert Message(role="user", content="é" * (MAX_MESSAGE_CONTENT_BYTES // 2)).content
    with pytest.raises(ValueError):
        Message(role="user", content="é" * (MAX_MESSAGE_CONTENT_BYTES // 2 + 1))


def test_metadata_byte_and_depth_caps_are_exact() -> None:
    base = _metadata()
    overhead = len(json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode())
    exact = _metadata(blob="x" * (MAX_METADATA_BYTES - overhead))

    assert _add_request(metadata=exact).metadata["blob"] == exact["blob"]
    with pytest.raises(ValueError):
        _add_request(metadata=_metadata(blob="x" * (MAX_METADATA_BYTES - overhead + 1)))

    accepted = {"a": {"b": {"c": {"d": "value"}}}}
    rejected = {"a": {"b": {"c": {"d": {"e": "value"}}}}}
    assert _add_request(metadata=_metadata(nested=accepted)).metadata["nested"] == accepted
    with pytest.raises(ValueError):
        _add_request(metadata=_metadata(nested=rejected))


def test_query_utf8_byte_cap_is_exact() -> None:
    filters = {"user_id": "user-1", "run_id": "run-1"}

    assert SearchRequest(
        query="é" * (MAX_QUERY_BYTES // 2),
        filters=filters,
        limit=1,
        top_k=1,
    ).query
    with pytest.raises(ValueError):
        SearchRequest(
            query="é" * (MAX_QUERY_BYTES // 2 + 1),
            filters=filters,
            limit=1,
            top_k=1,
        )


@pytest.mark.parametrize("field", ("user_id", "run_id", "agent_id"))
@pytest.mark.parametrize("unsafe_value", ("scope&run_id=other", "scope=value"))
def test_scope_identifiers_reject_mem0_session_scope_delimiters(
    field: str,
    unsafe_value: str,
) -> None:
    payload = {
        "messages": [{"role": "user", "content": "x"}],
        "user_id": "user-1",
        "run_id": "run-1",
        "metadata": _metadata(),
        "timestamp": 1,
    }
    payload[field] = unsafe_value

    with pytest.raises(ValueError):
        AddRequest.model_validate(payload)


def test_source_identifier_can_preserve_a_path_separator() -> None:
    assert (
        PersistedSourceMetadata(
            source_id="sources/session-1/turn-1",
            source_sha256="a" * 64,
        ).source_id
        == "sources/session-1/turn-1"
    )


def test_total_raw_request_bytes_are_rejected_before_model_or_provider() -> None:
    client = TestClient(create_app(FakeOssPort()))
    headers = {"content-type": "application/json"}

    at_cap = client.post("/memories", headers=headers, content=b"x" * MAX_REQUEST_BODY_BYTES)
    over_cap = client.post(
        "/memories",
        headers=headers,
        content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
    )

    assert at_cap.status_code == 422
    assert over_cap.status_code == 413
    assert over_cap.json() == {"detail": "request_body_too_large"}


def test_chunked_body_is_stopped_at_the_cap_without_unbounded_buffering() -> None:
    port = FakeOssPort()
    app = create_app(port)
    received_messages = 0
    sent: list[dict[str, Any]] = []
    chunks = iter(
        (
            {"type": "http.request", "body": b"x" * MAX_REQUEST_BODY_BYTES, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": True},
        )
    )

    async def receive() -> dict[str, Any]:
        nonlocal received_messages
        received_messages += 1
        return next(chunks)

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    _run_asgi(app, receive=receive, send=send)

    assert received_messages == 2
    assert port.add_calls == []
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    assert sent[1]["body"] == b'{"detail":"request_body_too_large"}'


@pytest.mark.parametrize(
    ("fragment", "fragment_limit"),
    (
        (b"x", _MAX_BODY_FRAGMENTS),
        (b"", _MAX_EMPTY_BODY_FRAGMENTS),
    ),
)
def test_fragment_flood_is_stopped_before_fastapi_or_provider(
    fragment: bytes,
    fragment_limit: int,
) -> None:
    port = FakeOssPort()
    app = create_app(port)
    received_messages = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal received_messages
        received_messages += 1
        return {"type": "http.request", "body": fragment, "more_body": True}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    _run_asgi(app, receive=receive, send=send)

    assert received_messages == fragment_limit + 1
    assert port.add_calls == []
    assert sent[0]["status"] == 413
    assert sent[1]["body"] == b'{"detail":"request_body_too_large"}'


def test_valid_fragments_are_coalesced_into_one_minimal_replay_message() -> None:
    replayed: list[dict[str, Any]] = []

    async def downstream(_scope: Any, receive: Any, send: Any) -> None:
        replayed.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = _BoundedIngressBodyMiddleware(downstream)
    fragments = iter(
        (
            {"type": "http.request", "body": b'{"a":', "more_body": True},
            {"type": "http.request", "body": b"1}", "more_body": False},
        )
    )

    async def receive() -> dict[str, Any]:
        return next(fragments)

    async def send(_message: dict[str, Any]) -> None:
        return None

    _run_asgi(app, receive=receive, send=send)

    assert replayed == [{"type": "http.request", "body": b'{"a":1}', "more_body": False}]


def _run_asgi(
    app: Any,
    *,
    receive: Any,
    send: Any,
) -> None:
    asyncio.run(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/memories",
                "raw_path": b"/memories",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"content-type", b"application/json")],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )
    )
