from __future__ import annotations

import socketserver
from pathlib import Path

import pytest
from publishable_mem0_v5 import relay, runtime_attestation, runtime_integrity
from publishable_mem0_v5.runtime_integrity import RuntimeIntegrityError

_PRIVATE_PORTS = (6334, 6335, 8891, 8892, 8893, 19091)
_HEALTH_BODY = b'{"ok":true,"service":"mem0-oss-adapter-v5","provider_calls":"dispatch_only"}'


def test_relay_listens_on_container_interfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def capture_init(
        _server: object,
        address: tuple[str, int],
        handler: object,
        bind_and_activate: bool,
    ) -> None:
        observed.update(
            address=address,
            bind_and_activate=bind_and_activate,
            handler=handler,
        )

    monkeypatch.setattr(socketserver.ThreadingTCPServer, "__init__", capture_init)
    relay._RelayServer()

    assert observed["address"] == ("0.0.0.0", 19191)
    assert observed["bind_and_activate"] is True


def test_runtime_binding_rejects_container_loopback_only_relay(tmp_path: Path) -> None:
    proc_root = _write_listener_fixture(tmp_path, relay_address="00000000")
    commitment = runtime_integrity.attest_socket_bindings(
        proc_root=proc_root,
        anchor_pid=201,
        host_relay_port=29191,
    )
    assert len(commitment) == 64

    _write_listener_fixture(tmp_path, relay_address="0100007F")
    with pytest.raises(RuntimeIntegrityError, match="relay_binding_invalid"):
        runtime_integrity.attest_socket_bindings(
            proc_root=proc_root,
            anchor_pid=201,
            host_relay_port=29191,
        )


@pytest.mark.parametrize(
    "binding",
    [
        {},
        {"19191/tcp": [{"HostIp": "0.0.0.0", "HostPort": "29191"}]},
        {"19191/tcp": [{"HostIp": "127.0.0.1", "HostPort": "29192"}]},
    ],
)
def test_published_relay_contract_rejects_missing_or_wrong_host_binding(
    binding: dict[str, list[dict[str, str]]],
) -> None:
    with pytest.raises(runtime_attestation.RuntimeAttestationError, match="ports_invalid"):
        runtime_attestation._attest_ports(
            {"PortBindings": binding},
            {"Ports": binding},
            service="publishable-relay-anchor",
            host_adapter_port=29191,
        )


def test_relay_reachability_probes_exact_provider_free_host_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            observed.update(host=host, port=port, timeout=timeout)

        def request(self, method: str, route: str, *, headers: dict[str, str]) -> None:
            observed.update(method=method, route=route, headers=headers)

        def getresponse(self) -> _Response:
            return _Response(status=200, body=_HEALTH_BODY)

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(runtime_integrity.http.client, "HTTPConnection", Connection)
    commitment = runtime_integrity.attest_relay_reachability(host_relay_port=29191)

    assert len(commitment) == 64
    assert observed == {
        "closed": True,
        "headers": {
            "Accept": "application/json",
            "Connection": "close",
            "Host": "127.0.0.1:29191",
        },
        "host": "127.0.0.1",
        "method": "GET",
        "port": 29191,
        "route": "/health",
        "timeout": 2.0,
    }


def test_relay_reachability_rejects_missing_host_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingConnection:
        def __init__(self, _host: str, _port: int, *, timeout: float) -> None:
            del timeout

        def request(self, _method: str, _route: str, *, headers: dict[str, str]) -> None:
            del headers
            raise ConnectionRefusedError

        def close(self) -> None:
            pass

    monkeypatch.setattr(runtime_integrity.http.client, "HTTPConnection", MissingConnection)
    with pytest.raises(RuntimeIntegrityError, match="relay_unreachable"):
        runtime_integrity.attest_relay_reachability(host_relay_port=29191)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (503, _HEALTH_BODY),
        (200, b'{"ok":true,"service":"wrong-listener","provider_calls":"dispatch_only"}'),
    ],
)
def test_relay_reachability_rejects_wrong_host_listener(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: bytes,
) -> None:
    class WrongConnection:
        def __init__(self, _host: str, _port: int, *, timeout: float) -> None:
            del timeout

        def request(self, _method: str, _route: str, *, headers: dict[str, str]) -> None:
            del headers

        def getresponse(self) -> _Response:
            return _Response(status=status, body=body)

        def close(self) -> None:
            pass

    monkeypatch.setattr(runtime_integrity.http.client, "HTTPConnection", WrongConnection)
    with pytest.raises(RuntimeIntegrityError, match="relay_response_invalid"):
        runtime_integrity.attest_relay_reachability(host_relay_port=29191)


class _Response:
    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, amount: int) -> bytes:
        assert amount == 4097
        return self._body


def _write_listener_fixture(tmp_path: Path, *, relay_address: str) -> Path:
    proc_root = tmp_path / "proc"
    network_root = proc_root / "201/net"
    network_root.mkdir(parents=True, exist_ok=True)
    rows = [("0100007F", port) for port in _PRIVATE_PORTS]
    rows.append((relay_address, 19191))
    (network_root / "tcp").write_text(_listener_table(rows), encoding="ascii")
    (network_root / "tcp6").write_text(_listener_table([]), encoding="ascii")
    return proc_root


def _listener_table(rows: list[tuple[str, int]]) -> str:
    lines = ["sl local_address rem_address st"]
    lines.extend(
        f"{index}: {address}:{port:04X} 00000000:0000 0A"
        for index, (address, port) in enumerate(rows)
    )
    return "\n".join(lines) + "\n"
