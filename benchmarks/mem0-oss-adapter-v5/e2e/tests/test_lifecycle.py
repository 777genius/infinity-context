from __future__ import annotations

import socket
import threading

import pytest

from e2e.canonical import E2EVerificationError
from e2e.lifecycle import (
    REQUEST,
    SUCCESS,
    DockerAdapterLifecycle,
    require_pinned_docker_host,
)


@pytest.mark.parametrize(
    "value", [None, "", "unix:///var/run/docker.sock", "unix:///run/user/994/docker.sock"]
)
def test_lifecycle_rejects_missing_or_unpinned_docker_host(monkeypatch, value) -> None:
    environment = {} if value is None else {"DOCKER_HOST": value}
    with pytest.raises(ValueError, match="e2e_docker_host_invalid"):
        require_pinned_docker_host(environment)


def test_child_lifecycle_uses_one_fixed_socket_request_and_no_docker(monkeypatch) -> None:
    parent, child = socket.socketpair()
    observed = []

    def broker() -> None:
        observed.append(parent.recv(32))
        parent.sendall(SUCCESS)
        parent.shutdown(socket.SHUT_WR)
        parent.close()

    thread = threading.Thread(target=broker)
    thread.start()
    lifecycle = DockerAdapterLifecycle(lifecycle_fd=child.detach())
    monkeypatch.setattr(lifecycle, "_healthy", lambda: True)
    lifecycle.crash_and_restart()
    thread.join()
    assert observed == [REQUEST]
    with pytest.raises(E2EVerificationError, match="e2e_adapter_restart_failed"):
        lifecycle.crash_and_restart()


@pytest.mark.parametrize("response", [b"", b"error-v1\n", b"ok-v1\nextra"])
def test_child_lifecycle_rejects_malformed_broker_response(monkeypatch, response) -> None:
    parent, child = socket.socketpair()

    def broker() -> None:
        parent.recv(32)
        if response:
            parent.sendall(response)
        parent.close()

    thread = threading.Thread(target=broker)
    thread.start()
    lifecycle = DockerAdapterLifecycle(lifecycle_fd=child.detach())
    monkeypatch.setattr(lifecycle, "_healthy", lambda: True)
    with pytest.raises(E2EVerificationError, match="e2e_adapter_restart_failed"):
        lifecycle.crash_and_restart()
    thread.join()
