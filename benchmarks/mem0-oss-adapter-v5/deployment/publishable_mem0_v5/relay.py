"""Single exposed HTTP relay for the adapter and authenticated bridge dispatch."""

from __future__ import annotations

import argparse
import json
import socket
import socketserver
import threading
from collections.abc import Sequence
from contextlib import suppress

from .bridge_dispatch import (
    DISPATCH_ROUTE,
    BridgeDispatchError,
    authenticate_dispatch,
    read_dispatch_body,
    read_request_head,
    render_upstream_request,
)

_CONTAINER_INTERFACES = "0.0.0.0"
_LOOPBACK = "127.0.0.1"
_LISTEN_PORT = 19_191
_ADAPTER_PORT = 19_091
_QDRANT_PORTS = (6_334, 6_335)
_FLEET_PORTS = (8_891, 8_892, 8_893)
_ALL_PORTS = (*_QDRANT_PORTS, *_FLEET_PORTS, _ADAPTER_PORT, _LISTEN_PORT)
_CONNECT_TIMEOUT_SECONDS = 2.0
_IO_TIMEOUT_SECONDS = 360.0
_COPY_BYTES = 64 * 1024
_MAX_CONNECTIONS = 64


class _RelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        if not isinstance(client, socket.socket):
            return
        client.settimeout(_IO_TIMEOUT_SECONDS)
        _configure_stream(client)
        try:
            request = read_request_head(client)
            if request.target == DISPATCH_ROUTE:
                _dispatch_bridge(client, request)
            else:
                _relay_adapter(client, request.raw + request.body_prefix)
        except BridgeDispatchError as exc:
            _send_error(client, exc)
        except OSError:
            _send_error(
                client,
                BridgeDispatchError(
                    "publishable_dispatch_upstream_unavailable",
                    status_code=502,
                ),
            )


class _RelayServer(socketserver.ThreadingTCPServer):
    address_family = socket.AF_INET
    allow_reuse_address = False
    daemon_threads = True
    block_on_close = False
    request_queue_size = _MAX_CONNECTIONS

    def __init__(self) -> None:
        self._slots = threading.BoundedSemaphore(_MAX_CONNECTIONS)
        super().__init__(
            (_CONTAINER_INTERFACES, _LISTEN_PORT),
            _RelayHandler,
            bind_and_activate=True,
        )

    def process_request(self, request: socket.socket, client_address: object) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: object) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def _dispatch_bridge(client: socket.socket, request: object) -> None:
    body = read_dispatch_body(client, request)  # type: ignore[arg-type]
    port = authenticate_dispatch(
        method=request.method,  # type: ignore[attr-defined]
        target=request.target,  # type: ignore[attr-defined]
        headers=request.headers,  # type: ignore[attr-defined]
        request_body=body,
    )
    rendered = render_upstream_request(
        request=request,  # type: ignore[arg-type]
        request_body=body,
        bridge_port=port,
    )
    upstream = _open_upstream(port)
    with upstream:
        upstream.sendall(rendered)
        _pump(upstream, client)


def _relay_adapter(client: socket.socket, initial: bytes) -> None:
    upstream = _open_upstream(_ADAPTER_PORT)
    with upstream:
        upstream.sendall(initial)
        request_pump = threading.Thread(
            target=_pump,
            args=(client, upstream),
            daemon=True,
            name="publishable-relay-adapter-request",
        )
        request_pump.start()
        _pump(upstream, client)
        _close_stream(client)
        _close_stream(upstream)
        request_pump.join(timeout=1.0)


def _open_upstream(port: int) -> socket.socket:
    try:
        upstream = socket.create_connection(
            (_LOOPBACK, port),
            timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except OSError as exc:
        raise BridgeDispatchError(
            "publishable_dispatch_upstream_unavailable",
            status_code=502,
        ) from exc
    upstream.settimeout(_IO_TIMEOUT_SECONDS)
    _configure_stream(upstream)
    return upstream


def _send_error(client: socket.socket, error: BridgeDispatchError) -> None:
    reasons = {400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 502: "Bad Gateway"}
    body = json.dumps(
        {"error": error.code},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    response = (
        f"HTTP/1.1 {error.status_code} {reasons[error.status_code]}\r\n"
        "Connection: close\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n"
    ).encode("ascii") + body
    with suppress(OSError):
        client.sendall(response)
    _close_stream(client)


def _configure_stream(value: socket.socket) -> None:
    value.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    value.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def _pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            chunk = source.recv(_COPY_BYTES)
            if not chunk:
                break
            destination.sendall(chunk)
    except OSError:
        pass
    finally:
        with suppress(OSError):
            destination.shutdown(socket.SHUT_WR)


def _close_stream(value: socket.socket) -> None:
    with suppress(OSError):
        value.shutdown(socket.SHUT_RDWR)


def _ports(component: str) -> tuple[int, ...]:
    return {
        "adapter": (_ADAPTER_PORT,),
        "all": _ALL_PORTS,
        "fleet": _FLEET_PORTS,
        "qdrant": _QDRANT_PORTS,
        "relay": (_LISTEN_PORT,),
    }[component]


def _healthy(ports: tuple[int, ...]) -> bool:
    for port in ports:
        try:
            with socket.create_connection(
                (_LOOPBACK, port),
                timeout=_CONNECT_TIMEOUT_SECONDS,
            ):
                pass
        except OSError:
            return False
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m publishable_mem0_v5.relay")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="serve the single adapter/bridge relay port")
    health = commands.add_parser("health", help="check a fixed provider-free port set")
    health.add_argument(
        "--component",
        choices=("adapter", "all", "fleet", "qdrant", "relay"),
        default="all",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "health":
        return 0 if _healthy(_ports(arguments.component)) else 1
    if arguments.command != "serve":
        return 2
    with _RelayServer() as server:
        server.serve_forever(poll_interval=0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("main",)
