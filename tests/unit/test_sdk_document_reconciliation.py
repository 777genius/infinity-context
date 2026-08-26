from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as enumerate_threads

import httpx
import pytest
from infinity_context_sdk import InfinityContextClient
from infinity_context_sdk.errors import InfinityContextError

CAPABILITY = {
    "exact_reconciliation": {
        "contract_version": "document-reconciliation.v1",
        "endpoint": "/v1/documents/reconcile-exact",
        "max_deadline_ms": 10_000,
        "max_response_bytes": 65_536,
        "read_only": True,
    }
}
INPUT = {
    "capability": CAPABILITY,
    "space_id": "space",
    "memory_scope_id": "scope",
    "source_type": "opaque-kind",
    "source_external_id": "opaque-id",
    "deadline_ms": 500,
}


def _response(**changes):
    data = {
        "contract_version": "document-reconciliation.v1",
        "state": "present",
        "scope": {"space_id": "space", "memory_scope_id": "scope", "thread_id": None},
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "document_id": "doc-1",
        "canonical_status": "active",
        "projection_generation": None,
        "profile_generation": None,
        "visibility": "accepted",
        "idempotency_key_matches": None,
    }
    data.update(changes)
    return {"data": data}


def _response_transport(value):
    def handler(_request):
        return httpx.Response(200, json=value)

    return httpx.MockTransport(handler)


def test_python_sdk_parity_validates_capability_and_performs_one_bounded_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_response())

    result = InfinityContextClient(transport=httpx.MockTransport(handler)).reconcile_exact_document(
        **INPUT
    )
    assert result["data"]["state"] == "present"
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/documents/reconcile-exact"
    assert json.loads(requests[0].content)["deadline_ms"] == 500


def test_python_sdk_fails_closed_on_unattested_malformed_or_oversized_responses() -> None:
    client = InfinityContextClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    )
    with pytest.raises(ValueError, match="capability"):
        client.reconcile_exact_document(**{**INPUT, "capability": {}})
    with pytest.raises(ValueError, match="malformed"):
        client.reconcile_exact_document(**INPUT)

    oversized = InfinityContextClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b'"' + b"x" * 65_537 + b'"')
        )
    )
    with pytest.raises(InfinityContextError) as captured:
        oversized.reconcile_exact_document(**INPUT)
    assert captured.value.code == "memory.response_byte_limit_exceeded"


def test_python_sdk_does_not_leak_opaque_identity_in_validation_errors() -> None:
    secret = "secret-opaque-identity"
    with pytest.raises(ValueError) as captured:
        InfinityContextClient().reconcile_exact_document(
            **{**INPUT, "source_external_id": f"{secret}\x00"}
        )
    assert secret not in str(captured.value)


def test_python_sdk_rejects_every_shared_hostile_decoder_fixture() -> None:
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "packages/infinity_context_ts_sdk/fixtures/document_reconciliation"
            / "hostile_responses.json"
        ).read_text()
    )
    for case in fixture["cases"]:
        response = _response(
            projection_generation="projection-2",
            profile_generation="profile-4",
            idempotency_key_matches=True,
        )
        target = response["data"]
        for segment in case["path"][:-1]:
            target = target[segment]
        if case.get("operation") == "delete":
            del target[case["path"][-1]]
        else:
            target[case["path"][-1]] = case["value"]
        hostile_response = deepcopy(response)
        client = InfinityContextClient(transport=_response_transport(hostile_response))
        hostile_input = {
            **INPUT,
            "projection_generation": "projection-2",
            "profile_generation": "profile-4",
        }
        with pytest.raises(ValueError):
            client.reconcile_exact_document(**hostile_input)


def test_python_sdk_honors_pre_cancel_and_absolute_deadline_without_transport_call() -> None:
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_response())

    client = InfinityContextClient(transport=httpx.MockTransport(handler))
    cancelled = Event()
    cancelled.set()
    with pytest.raises(InfinityContextError) as cancellation:
        client.reconcile_exact_document(**INPUT, cancellation_event=cancelled)
    assert cancellation.value.code == "memory.request_cancelled"
    with pytest.raises(InfinityContextError) as deadline:
        client.reconcile_exact_document(**INPUT, absolute_deadline=time.monotonic() - 0.001)
    assert deadline.value.code == "memory.request_deadline_exceeded"
    assert calls == 0


def test_python_sdk_cancellation_interrupts_blocked_transport_and_joins_watcher() -> None:
    entered = Event()
    released = Event()
    cancelled = Event()

    class BlockingTransport(httpx.BaseTransport):
        def handle_request(self, _request: httpx.Request) -> httpx.Response:
            entered.set()
            assert released.wait(1)
            raise httpx.ReadError("closed for cancellation")

        def close(self) -> None:
            released.set()

    def cancel_after_entry() -> None:
        assert entered.wait(1)
        cancelled.set()

    controller = Thread(target=cancel_after_entry)
    controller.start()
    with pytest.raises(InfinityContextError) as captured:
        InfinityContextClient(transport=BlockingTransport()).reconcile_exact_document(
            **INPUT, cancellation_event=cancelled
        )
    controller.join()

    assert captured.value.code == "memory.request_cancelled"
    assert released.is_set()
    assert not any(
        thread.name == "infinity-bounded-read-cancellation" and thread.is_alive()
        for thread in enumerate_threads()
    )
