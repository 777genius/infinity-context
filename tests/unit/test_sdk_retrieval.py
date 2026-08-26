from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from threading import Event

import httpx
import pytest
from infinity_context_contracts.features.context_building import (
    RetrievalCapabilityDto,
    RetrieveContextRequestDto,
)
from infinity_context_sdk import (
    InfinityContextClient,
    InfinityContextTransportCapabilityError,
    InfinityRetrievalContractError,
    InfinityRetrievalError,
)

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_contracts/infinity_context_contracts/fixtures/context_retrieval_v2"
)
TS_FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "packages/infinity_context_ts_sdk/fixtures/context_retrieval_v2"
)


def test_official_python_client_retrieval_matches_shared_locator_fixture() -> None:
    request, capability = _inputs()
    success = (FIXTURES / "success.json").read_bytes()
    seen = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen["method"] = http_request.method
        seen["path"] = http_request.url.path
        seen["body"] = json.loads(http_request.content)
        return httpx.Response(200, content=success)

    result = _client(handler).retrieve_context(request, capability=capability)

    assert (seen["method"], seen["path"]) == ("POST", "/v1/context/retrieve")
    assert seen["body"] == request.to_dict()
    assert result.to_dict() == json.loads(success)
    assert all("text" not in candidate for candidate in result.to_dict()["candidates"])


def test_official_python_client_rejects_unknown_response_fields_and_attestation_drift() -> None:
    request, capability = _inputs()
    body = json.loads((FIXTURES / "success.json").read_text())
    body["unexpected"] = True

    with pytest.raises(InfinityRetrievalContractError):
        _client(lambda _request: httpx.Response(200, json=body)).retrieve_context(
            request, capability=capability
        )

    changed = request.to_dict()
    changed["profile_id"] = "different-profile"
    with pytest.raises(InfinityRetrievalContractError):
        _client(lambda _request: httpx.Response(200, json={})).retrieve_context(
            RetrieveContextRequestDto.from_dict(changed), capability=capability
        )


def test_official_python_client_maps_strict_errors_and_transport_timeout() -> None:
    request, capability = _inputs()
    error = {
        "error": {
            "code": "memory.context_retrieval_unavailable",
            "message": "Retrieval is unavailable",
            "retryable": True,
        }
    }
    with pytest.raises(InfinityRetrievalError) as raised:
        _client(lambda _request: httpx.Response(503, json=error)).retrieve_context(
            request, capability=capability
        )
    assert raised.value.code == "memory.context_retrieval_unavailable"
    assert raised.value.retryable is True

    def timeout(http_request: httpx.Request):
        raise httpx.ReadTimeout("bounded", request=http_request)

    with pytest.raises(InfinityRetrievalError) as timed_out:
        _client(timeout).retrieve_context(request, capability=capability)
    assert timed_out.value.code == "memory.context_retrieval_deadline_exceeded"

    def unavailable(http_request: httpx.Request):
        raise httpx.ConnectError("unavailable", request=http_request)

    with pytest.raises(InfinityRetrievalError) as network:
        _client(unavailable).retrieve_context(request, capability=capability)
    assert network.value.code == "memory.context_retrieval_unavailable"


def test_official_python_client_rejects_shared_hostile_cross_envelopes() -> None:
    request, capability = _inputs()
    success = json.loads((FIXTURES / "success.json").read_text())
    fixture = json.loads((FIXTURES / "hostile_responses.json").read_text())
    for case in fixture["cases"]:
        body = json.loads(json.dumps(success))
        target = body
        for component in case["path"][:-1]:
            target = target[component]
        target[case["path"][-1]] = case["value"]
        with pytest.raises(InfinityRetrievalContractError, match=".*") as rejected:
            _client(lambda _request, body=body: httpx.Response(200, json=body)).retrieve_context(
                request, capability=capability
            )
        assert rejected.value.code == "memory.context_retrieval_contract_invalid", case["id"]


def test_official_python_client_enforces_absolute_slow_stream_budget_and_cancellation() -> None:
    request, capability = _inputs()
    success = (FIXTURES / "success.json").read_bytes()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for offset in range(0, len(success), 64):
                await __import__("asyncio").sleep(0.01)
                yield success[offset : offset + 64]

    client = InfinityContextClient(
        base_url="https://memory.invalid",
        token="test-token",
        timeout=0.04,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=SlowStream())),
    )
    with pytest.raises(InfinityRetrievalError) as expired:
        client.retrieve_context(request, capability=capability)
    assert expired.value.code == "memory.context_retrieval_deadline_exceeded"

    cancelled = Event()

    class CancellingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield success[:64]
            cancelled.set()
            yield success[64:]

    client = InfinityContextClient(
        base_url="https://memory.invalid",
        token="test-token",
        timeout=1,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=CancellingStream())
        ),
    )
    with pytest.raises(InfinityRetrievalError) as aborted:
        client.retrieve_context(request, capability=capability, cancellation_event=cancelled)
    assert aborted.value.code == "memory.context_retrieval_cancelled"
    assert aborted.value.retryable is False


def test_official_python_client_interrupts_a_blocked_read() -> None:
    request, capability = _inputs()
    cancelled = Event()
    transport_cancelled = Event()

    class BlockedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await __import__("asyncio").Event().wait()
                yield b"{}"
            finally:
                transport_cancelled.set()

    client = InfinityContextClient(
        base_url="https://memory.invalid",
        token="test-token",
        timeout=1,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=BlockedStream())),
    )
    timer = __import__("threading").Timer(0.02, cancelled.set)
    timer.start()
    started = time.monotonic()
    with pytest.raises(InfinityRetrievalError) as aborted:
        client.retrieve_context(request, capability=capability, cancellation_event=cancelled)
    timer.join(timeout=1)
    assert aborted.value.code == "memory.context_retrieval_cancelled"
    assert time.monotonic() - started < 0.5
    assert transport_cancelled.wait(0.2)
    assert not [
        thread
        for thread in __import__("threading").enumerate()
        if thread.name.startswith("infinity-retrieval")
    ]


def test_official_python_client_deadline_aborts_blocked_read_without_residual_work() -> None:
    request, capability = _inputs()
    transport_cancelled = Event()

    class BlockedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await __import__("asyncio").Event().wait()
                yield b"{}"
            finally:
                transport_cancelled.set()

    client = InfinityContextClient(
        base_url="https://memory.invalid",
        token="test-token",
        timeout=0.03,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=BlockedStream())),
    )
    with pytest.raises(InfinityRetrievalError) as expired:
        client.retrieve_context(request, capability=capability)
    assert expired.value.code == "memory.context_retrieval_deadline_exceeded"
    assert transport_cancelled.wait(0.2)
    assert not [
        thread
        for thread in __import__("threading").enumerate()
        if thread.name.startswith("infinity-retrieval")
    ]


def test_retrieval_rejects_sync_only_transport_before_handler_call() -> None:
    request, capability = _inputs()
    calls = 0

    class BlockingSyncTransport(httpx.BaseTransport):
        def handle_request(self, _request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            Event().wait()
            raise AssertionError("indefinitely blocking handler returned")

    with pytest.raises(InfinityContextTransportCapabilityError) as captured:
        InfinityContextClient(transport=BlockingSyncTransport()).retrieve_context(
            request, capability=capability
        )

    assert captured.value.code == "memory.transport_capability_invalid"
    assert calls == 0


def test_retrieval_runs_from_an_active_event_loop_on_explicit_async_seam() -> None:
    request, capability = _inputs()
    success = (FIXTURES / "success.json").read_bytes()
    client = InfinityContextClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": []})),
        async_transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=success)),
    )

    async def call() -> object:
        return client.retrieve_context(request, capability=capability)

    assert asyncio.run(call()).to_dict() == json.loads(success)
    assert client.list_spaces() == {"data": []}


def test_official_python_and_typescript_parity_fixture_bytes_are_identical() -> None:
    python_files = sorted(path.name for path in FIXTURES.iterdir() if path.is_file())
    typescript_files = sorted(path.name for path in TS_FIXTURES.iterdir() if path.is_file())
    assert python_files == typescript_files
    assert {name: (FIXTURES / name).read_bytes() for name in python_files} == {
        name: (TS_FIXTURES / name).read_bytes() for name in typescript_files
    }
    outcomes = json.loads((FIXTURES / "transport_outcomes.json").read_text())["outcomes"]
    assert [(item["kind"], item["code"], item["retryable"]) for item in outcomes] == [
        ("deadline", "memory.context_retrieval_deadline_exceeded", True),
        ("cancelled", "memory.context_retrieval_cancelled", False),
        ("unavailable", "memory.context_retrieval_unavailable", True),
    ]


def _inputs():
    request = RetrieveContextRequestDto.from_dict(
        json.loads((FIXTURES / "request.json").read_text())
    )
    capability = RetrievalCapabilityDto.from_dict(
        json.loads((FIXTURES / "capability.json").read_text())
    )
    return request, capability


def _client(handler):
    return InfinityContextClient(
        base_url="https://memory.invalid",
        token="test-token",
        timeout=0.1,
        transport=httpx.MockTransport(handler),
    )
