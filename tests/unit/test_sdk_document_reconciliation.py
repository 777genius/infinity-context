from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event, Thread
from threading import enumerate as enumerate_threads

import httpx
import pytest
from infinity_context_sdk import InfinityContextClient
from infinity_context_sdk.async_facade import run_on_owned_loop
from infinity_context_sdk.errors import (
    InfinityContextError,
    InfinityContextTransportCapabilityError,
)

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


def test_python_sdk_cancellation_cleans_up_async_request_and_client() -> None:
    entered = Event()
    released = Event()
    closed = Event()
    cancelled = Event()
    residual_tasks: list[str] = []

    class BlockingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

        async def aclose(self) -> None:
            current = asyncio.current_task()
            residual_tasks.extend(
                task.get_name() for task in asyncio.all_tasks() if task is not current
            )
            closed.set()

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
    assert closed.is_set()
    assert residual_tasks == []


def test_python_sdk_simultaneous_response_and_cancellation_fails_deterministically() -> None:
    cancelled = Event()

    class RacingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            cancelled.set()
            return httpx.Response(200, json=_response())

    with pytest.raises(InfinityContextError) as captured:
        InfinityContextClient(transport=RacingTransport()).reconcile_exact_document(
            **INPUT,
            cancellation_event=cancelled,
        )

    assert captured.value.code == "memory.request_cancelled"


def test_python_sdk_repeated_calls_close_every_private_event_loop(monkeypatch) -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    new_event_loop = asyncio.events.new_event_loop

    def tracked_event_loop() -> asyncio.AbstractEventLoop:
        loop = new_event_loop()
        loops.append(loop)
        return loop

    monkeypatch.setattr(asyncio.events, "new_event_loop", tracked_event_loop)
    for _ in range(5):
        result = InfinityContextClient(
            transport=_response_transport(_response())
        ).reconcile_exact_document(**INPUT)
        assert result["data"]["state"] == "present"

    assert len(loops) == 5
    assert all(loop.is_closed() for loop in loops)
    assert not any(
        thread.name.startswith("infinity-bounded-read") and thread.is_alive()
        for thread in enumerate_threads()
    )


def test_python_sdk_rejects_blocking_sync_transport_before_handler_call() -> None:
    calls = 0

    class SyncTransport(httpx.BaseTransport):
        def handle_request(self, _request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            Event().wait()
            raise AssertionError("indefinitely blocking handler returned")

    started = time.monotonic()
    with pytest.raises(InfinityContextTransportCapabilityError) as captured:
        InfinityContextClient(transport=SyncTransport()).reconcile_exact_document(**INPUT)

    assert captured.value.code == "memory.transport_capability_invalid"
    assert calls == 0
    assert time.monotonic() - started < 0.1
    assert not any(
        thread.name == "infinity-sdk-owned-loop" and thread.is_alive()
        for thread in enumerate_threads()
    )


def test_python_sdk_sync_transport_can_pair_with_explicit_async_transport() -> None:
    sync_calls = 0

    class SyncTransport(httpx.BaseTransport):
        def handle_request(self, _request: httpx.Request) -> httpx.Response:
            nonlocal sync_calls
            sync_calls += 1
            return httpx.Response(200, json={"data": []})

    client = InfinityContextClient(
        transport=SyncTransport(),
        async_transport=_response_transport(_response()),
    )
    assert client.list_spaces() == {"data": []}
    assert client.reconcile_exact_document(**INPUT)["data"]["state"] == "present"
    assert sync_calls == 1


def test_python_sdk_reconciliation_runs_from_an_active_event_loop() -> None:
    async def call_successfully() -> dict[str, object]:
        return InfinityContextClient(
            transport=_response_transport(_response())
        ).reconcile_exact_document(**INPUT)

    result = asyncio.run(call_successfully())
    assert result["data"]["state"] == "present"


def test_python_sdk_active_event_loop_cancellation_cleans_up() -> None:
    entered = Event()
    released = Event()
    cancelled = Event()

    class BlockingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, _request: httpx.Request) -> httpx.Response:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

    def cancel() -> None:
        assert entered.wait(1)
        cancelled.set()

    async def call_and_cancel() -> None:
        controller = Thread(target=cancel)
        controller.start()
        with pytest.raises(InfinityContextError) as captured:
            InfinityContextClient(transport=BlockingTransport()).reconcile_exact_document(
                **INPUT, cancellation_event=cancelled
            )
        controller.join(1)
        assert captured.value.code == "memory.request_cancelled"
        assert not controller.is_alive()

    asyncio.run(call_and_cancel())
    assert released.is_set()


def test_python_sdk_concurrent_bounded_calls_join_every_owned_loop() -> None:
    calls = 12
    transport = _response_transport(_response())
    client = InfinityContextClient(transport=transport)

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(
            executor.map(
                lambda _index: client.reconcile_exact_document(**INPUT),
                range(calls),
            )
        )

    assert len(results) == calls
    assert all(result["data"]["state"] == "present" for result in results)
    assert not any(
        thread.name == "infinity-sdk-owned-loop" and thread.is_alive()
        for thread in enumerate_threads()
    )


def test_owned_loop_thread_is_explicitly_non_daemon_from_normal_and_daemon_callers() -> None:
    observed: list[tuple[bool, bool]] = []

    async def observe() -> bool:
        from threading import current_thread

        return current_thread().daemon

    def call() -> None:
        from threading import current_thread

        observed.append((current_thread().daemon, run_on_owned_loop(observe)))

    normal = Thread(target=call, daemon=False)
    daemon = Thread(target=call, daemon=True)
    normal.start()
    daemon.start()
    normal.join(1)
    daemon.join(1)

    assert sorted(observed) == [
        (False, False),
        (True, False),
    ]
    assert not normal.is_alive()
    assert not daemon.is_alive()
    assert not any(
        thread.name == "infinity-sdk-owned-loop" and thread.is_alive()
        for thread in enumerate_threads()
    )


@pytest.mark.parametrize("exception", [RuntimeError("failed"), asyncio.CancelledError()])
def test_owned_loop_joins_before_propagating_exceptions(exception: BaseException) -> None:
    async def fail() -> None:
        raise exception

    match = "failed" if isinstance(exception, RuntimeError) else None
    with pytest.raises(type(exception), match=match):
        run_on_owned_loop(fail)

    assert not any(
        thread.name == "infinity-sdk-owned-loop" and thread.is_alive()
        for thread in enumerate_threads()
    )


def test_interpreter_waits_for_owned_loop_started_by_daemon_caller(tmp_path: Path) -> None:
    marker = tmp_path / "owned-loop-finished"
    script = textwrap.dedent(
        f"""
        import asyncio
        from pathlib import Path
        from threading import Event, Thread

        from infinity_context_sdk.async_facade import run_on_owned_loop

        started = Event()

        async def finish():
            started.set()
            await asyncio.sleep(0.05)
            Path({str(marker)!r}).write_text("finished", encoding="utf-8")

        Thread(target=lambda: run_on_owned_loop(finish), daemon=True).start()
        assert started.wait(1)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert completed.returncode == 0, completed.stderr
    assert marker.read_text(encoding="utf-8") == "finished"
