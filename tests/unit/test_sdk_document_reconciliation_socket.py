from __future__ import annotations

import json
import socket
import time
from contextlib import AbstractContextManager, suppress
from threading import Condition, Event, Thread

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


def _response_body() -> bytes:
    return json.dumps(
        {
            "data": {
                "contract_version": "document-reconciliation.v1",
                "state": "present",
                "scope": {
                    "space_id": "space",
                    "memory_scope_id": "scope",
                    "thread_id": None,
                },
                "source_type": "opaque-kind",
                "source_external_id": "opaque-id",
                "document_id": "doc-1",
                "canonical_status": "active",
                "projection_generation": None,
                "profile_generation": None,
                "visibility": "accepted",
                "idempotency_key_matches": None,
            }
        },
        separators=(",", ":"),
    ).encode()


class _LocalHttpServer(AbstractContextManager["_LocalHttpServer"]):
    def __init__(self, *, body: bytes | None, response_delay: float = 0.0) -> None:
        self._body = body
        self._response_delay = response_delay
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self._listener.settimeout(0.05)
        self._stop = Event()
        self._condition = Condition()
        self._active: socket.socket | None = None
        self.accepted = 0
        self.peer_closed = 0
        self.thread = Thread(target=self._serve, name="infinity-test-http-server")
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._listener.getsockname()[1]}"

    def wait_for_accepted(self, count: int, timeout: float = 1.0) -> bool:
        return self._wait_for(lambda: self.accepted >= count, timeout)

    def wait_for_peer_closed(self, count: int, timeout: float = 0.3) -> bool:
        return self._wait_for(lambda: self.peer_closed >= count, timeout)

    def _wait_for(self, predicate, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not predicate():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self._active = connection
            connection.settimeout(0.05)
            try:
                self._read_request(connection)
                with self._condition:
                    self.accepted += 1
                    self._condition.notify_all()
                if self._body is not None:
                    self._stop.wait(self._response_delay)
                    response = (
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + f"Content-Length: {len(self._body)}\r\n\r\n".encode()
                        + self._body
                    )
                    connection.sendall(response)
                self._wait_for_eof(connection)
            except OSError:
                pass
            finally:
                connection.close()
                self._active = None

    def _read_request(self, connection: socket.socket) -> None:
        received = b""
        while b"\r\n\r\n" not in received and not self._stop.is_set():
            try:
                chunk = connection.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                return
            received += chunk

    def _wait_for_eof(self, connection: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                if connection.recv(4096) == b"":
                    with self._condition:
                        self.peer_closed += 1
                        self._condition.notify_all()
                    return
            except TimeoutError:
                continue

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        active = self._active
        if active is not None:
            with suppress(OSError):
                active.shutdown(socket.SHUT_RDWR)
        self._listener.close()
        self.thread.join(1)
        assert not self.thread.is_alive()


def _client(
    server: _LocalHttpServer,
    *,
    timeout: float = 0.75,
    explicit_transport: bool = True,
) -> InfinityContextClient:
    # Constructing the real transport outside the measured interval isolates the
    # socket cancellation contract from one-time platform CA discovery overhead.
    return InfinityContextClient(
        base_url=server.base_url,
        timeout=timeout,
        transport=httpx.AsyncHTTPTransport() if explicit_transport else None,
    )


def test_real_socket_cancellation_returns_around_fifty_ms_and_closes_peer() -> None:
    with _LocalHttpServer(body=None) as server:
        client = _client(server)
        cancelled = Event()

        def cancel_after_request() -> None:
            time.sleep(0.05)
            cancelled.set()

        controller = Thread(target=cancel_after_request)
        controller.start()
        started = time.monotonic()
        with pytest.raises(InfinityContextError) as captured:
            client.reconcile_exact_document(**INPUT, cancellation_event=cancelled)
        elapsed = time.monotonic() - started
        controller.join(1)

        assert captured.value.code == "memory.request_cancelled"
        assert 0.04 <= elapsed < 0.30
        assert server.wait_for_accepted(1)
        assert server.wait_for_peer_closed(1)
        assert not controller.is_alive()


def test_real_socket_absolute_deadline_returns_around_one_hundred_twenty_ms() -> None:
    with _LocalHttpServer(body=None) as server:
        client = _client(server)
        started = time.monotonic()
        with pytest.raises(InfinityContextError) as captured:
            client.reconcile_exact_document(
                **INPUT,
                absolute_deadline=started + 0.12,
            )
        elapsed = time.monotonic() - started

        assert captured.value.code == "memory.request_deadline_exceeded"
        assert 0.10 <= elapsed < 0.28
        assert server.wait_for_accepted(1)
        assert server.wait_for_peer_closed(1)


def test_real_socket_phase_timeout_remains_a_secondary_cap() -> None:
    with _LocalHttpServer(body=None) as server:
        client = _client(server, timeout=0.07)
        started = time.monotonic()
        with pytest.raises(InfinityContextError) as captured:
            client.reconcile_exact_document(
                **INPUT,
                absolute_deadline=started + 0.5,
            )
        elapsed = time.monotonic() - started

        assert captured.value.code == "memory.request_deadline_exceeded"
        assert 0.05 <= elapsed < 0.25
        assert server.wait_for_accepted(1)
        assert server.wait_for_peer_closed(1)


@pytest.mark.parametrize("cancelled", [False, True])
def test_default_real_socket_transport_keeps_control_bounds(cancelled: bool) -> None:
    with _LocalHttpServer(body=None) as server:
        client = _client(server, explicit_transport=False)
        cancellation_event = Event() if cancelled else None
        controller = None
        started = time.monotonic()
        if cancellation_event is not None:
            controller = Thread(target=lambda: (time.sleep(0.05), cancellation_event.set()))
            controller.start()
        with pytest.raises(InfinityContextError) as captured:
            client.reconcile_exact_document(
                **INPUT,
                cancellation_event=cancellation_event,
                absolute_deadline=started + 0.12,
            )
        elapsed = time.monotonic() - started
        if controller is not None:
            controller.join(1)

        expected = "memory.request_cancelled" if cancelled else "memory.request_deadline_exceeded"
        assert captured.value.code == expected
        assert elapsed < 0.3
        assert server.wait_for_accepted(1)
        assert server.wait_for_peer_closed(1)
        assert controller is None or not controller.is_alive()


def test_real_socket_response_wins_before_later_cancellation() -> None:
    with _LocalHttpServer(body=_response_body(), response_delay=0.01) as server:
        client = _client(server)
        cancelled = Event()

        def cancel_after_response() -> None:
            assert server.wait_for_accepted(1)
            time.sleep(0.08)
            cancelled.set()

        controller = Thread(target=cancel_after_response)
        controller.start()
        result = client.reconcile_exact_document(**INPUT, cancellation_event=cancelled)
        controller.join(1)

        assert result["data"]["state"] == "present"
        assert cancelled.is_set()
        assert server.wait_for_peer_closed(1)
        assert not controller.is_alive()


def test_real_socket_repeated_cancellation_closes_every_connection() -> None:
    calls = 5
    with _LocalHttpServer(body=None) as server:
        for call_number in range(1, calls + 1):
            cancelled = Event()

            def cancel_after_request(
                expected: int = call_number,
                event: Event = cancelled,
            ) -> None:
                assert server.wait_for_accepted(expected)
                time.sleep(0.02)
                event.set()

            controller = Thread(target=cancel_after_request)
            controller.start()
            with pytest.raises(InfinityContextError) as captured:
                _client(server).reconcile_exact_document(
                    **INPUT,
                    cancellation_event=cancelled,
                )
            controller.join(1)
            assert captured.value.code == "memory.request_cancelled"
            assert not controller.is_alive()
            assert server.wait_for_peer_closed(call_number)
        assert server.accepted == calls
        assert server.peer_closed == calls


def test_real_socket_malformed_response_fails_closed_after_cleanup() -> None:
    with _LocalHttpServer(body=b"{") as server:
        with pytest.raises(InfinityContextError) as captured:
            _client(server).reconcile_exact_document(**INPUT)

        assert captured.value.code == "memory.invalid_json"
        assert server.wait_for_peer_closed(1)


def test_async_http_transport_reconciles_without_breaking_ordinary_sync_calls() -> None:
    with _LocalHttpServer(body=_response_body()) as server:
        client = _client(server)
        assert client.reconcile_exact_document(**INPUT)["data"]["state"] == "present"
        assert server.wait_for_peer_closed(1)
        assert client.list_spaces()["data"]["state"] == "present"
        assert server.wait_for_peer_closed(2)
