"""Unprivileged lifecycle client for the provider-free E2E."""

from __future__ import annotations

import http.client
import json
import os
import socket
import time
from collections.abc import Mapping

from .canonical import E2EVerificationError

PINNED_DOCKER_HOST = "unix:///run/infinity-locomo-docker/docker.sock"
REQUEST = b"restart-v1\n"
SUCCESS = b"ok-v1\n"


def require_pinned_docker_host(environment: Mapping[str, str] | None = None) -> str:
    value = (os.environ if environment is None else environment).get("DOCKER_HOST")
    if value != PINNED_DOCKER_HOST:
        raise ValueError("e2e_docker_host_invalid")
    return value


class DockerAdapterLifecycle:
    """Request one fixed restart without Docker access in the child."""

    def __init__(self, *, lifecycle_fd: int, host_port: int = 19091) -> None:
        if not isinstance(lifecycle_fd, int) or lifecycle_fd < 3:
            raise ValueError("e2e_lifecycle_configuration_invalid")
        self._channel = socket.socket(fileno=lifecycle_fd)
        self._host_port = host_port
        self._used = False

    def crash_and_restart(self) -> None:
        if self._used:
            raise E2EVerificationError("e2e_adapter_restart_failed")
        self._used = True
        try:
            self._channel.settimeout(70)
            self._channel.sendall(REQUEST)
            self._channel.shutdown(socket.SHUT_WR)
            response = _read_bounded(self._channel, len(SUCCESS))
        except Exception:
            raise E2EVerificationError("e2e_adapter_restart_failed") from None
        finally:
            self._channel.close()
        if response != SUCCESS:
            raise E2EVerificationError("e2e_adapter_restart_failed")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._healthy():
                return
            time.sleep(0.25)
        raise E2EVerificationError("e2e_adapter_restart_failed")

    def _healthy(self) -> bool:
        connection = http.client.HTTPConnection("127.0.0.1", self._host_port, timeout=1)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            value = json.loads(response.read(4097))
            return response.status == 200 and value == {
                "ok": True,
                "service": "mem0-oss-adapter-v5",
                "provider_calls": "dispatch_only",
            }
        except Exception:
            return False
        finally:
            connection.close()


def _read_bounded(channel: socket.socket, limit: int) -> bytes:
    value = bytearray()
    while len(value) <= limit:
        chunk = channel.recv(limit + 1 - len(value))
        if not chunk:
            break
        value.extend(chunk)
    return bytes(value)
