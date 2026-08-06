"""Narrow Docker lifecycle adapter used only for the tested service restart."""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

from .canonical import E2EVerificationError

_PROJECT = re.compile(r"^mem0-v5-e2e-[a-z0-9][a-z0-9-]{0,40}$")
PINNED_DOCKER_HOST = "unix:///run/infinity-locomo-docker/docker.sock"


def require_pinned_docker_host(environment: Mapping[str, str] | None = None) -> str:
    value = (os.environ if environment is None else environment).get("DOCKER_HOST")
    if value != PINNED_DOCKER_HOST:
        raise ValueError("e2e_docker_host_invalid")
    return value


class DockerAdapterLifecycle:
    def __init__(self, *, compose_file: Path, project_name: str, host_port: int = 19091) -> None:
        require_pinned_docker_host()
        if (
            not compose_file.is_absolute()
            or not compose_file.is_file()
            or _PROJECT.fullmatch(project_name) is None
        ):
            raise ValueError("e2e_lifecycle_configuration_invalid")
        self._compose = compose_file
        self._project = project_name
        self._host_port = host_port

    def crash_and_restart(self) -> None:
        base = ["docker", "compose", "-p", self._project, "-f", str(self._compose)]
        self._run([*base, "kill", "--signal", "KILL", "mem0-oss-adapter-v5"])
        self._run([*base, "start", "mem0-oss-adapter-v5"])
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._healthy():
                return
            time.sleep(0.25)
        raise E2EVerificationError("e2e_adapter_restart_failed")

    @staticmethod
    def _run(command: list[str]) -> None:
        try:
            require_pinned_docker_host()
        except ValueError:
            raise E2EVerificationError("e2e_docker_host_invalid") from None
        try:
            subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=True,
            )
        except Exception:
            raise E2EVerificationError("e2e_adapter_restart_failed") from None

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
