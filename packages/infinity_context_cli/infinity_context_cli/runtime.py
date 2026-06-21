"""Local runtime adapters for Infinity Context CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from infinity_context_cli.config import InfinityContextCliConfig


@dataclass(frozen=True)
class RuntimeResult:
    ok: bool
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class RuntimePort(Protocol):
    def up(self, compose_profile: str) -> RuntimeResult: ...

    def down(self) -> RuntimeResult: ...

    def logs(self, service: str | None, tail: int) -> RuntimeResult: ...


class DockerComposeRuntime:
    def __init__(self, *, config: InfinityContextCliConfig) -> None:
        self._config = config

    def up(self, compose_profile: str) -> RuntimeResult:
        if compose_profile == "full":
            command = (
                "docker",
                "compose",
                "--profile",
                "full",
                "up",
                "-d",
                "infinity_context_server_full",
                "infinity_context_worker_full",
                "infinity_context_extraction_worker_full",
            )
        else:
            command = (
                "docker",
                "compose",
                "--profile",
                "lite",
                "up",
                "-d",
                "infinity_context_server",
                "infinity_context_worker",
                "infinity_context_extraction_worker",
            )
        return self._run(command)

    def down(self) -> RuntimeResult:
        return self._run(("docker", "compose", "--profile", "lite", "--profile", "full", "down"))

    def logs(self, service: str | None, tail: int) -> RuntimeResult:
        command = ["docker", "compose", "logs", f"--tail={max(1, tail)}"]
        if service:
            command.append(service)
        return self._run(tuple(command))

    def _run(self, command: tuple[str, ...]) -> RuntimeResult:
        if not self._compose_file().exists():
            return RuntimeResult(
                ok=False,
                command=command,
                returncode=127,
                stdout="",
                stderr=f"docker-compose.yml not found under {self._config.repo_dir}",
            )
        process = subprocess.run(
            command,
            cwd=self._config.repo_dir,
            env=_compose_env(self._config),
            text=True,
            capture_output=True,
            check=False,
        )
        return RuntimeResult(
            ok=process.returncode == 0,
            command=command,
            returncode=process.returncode,
            stdout=process.stdout,
            stderr=process.stderr,
        )

    def _compose_file(self) -> Path:
        return self._config.repo_dir / "docker-compose.yml"


def docker_compose_published_server_urls(config: InfinityContextCliConfig) -> list[str]:
    """Return published local API URLs from docker compose, without mutating runtime state."""
    if not docker_compose_available() or not (config.repo_dir / "docker-compose.yml").exists():
        return []
    urls: list[str] = []
    for env in _compose_detection_envs(config):
        for service in ("infinity_context_server", "infinity_context_server_full"):
            process = _compose_port(config=config, service=service, env=env)
            if process is None or process.returncode != 0:
                continue
            url = _published_url_from_compose_port(process.stdout)
            if url and url not in urls:
                urls.append(url)
    return urls


def docker_available() -> bool:
    return shutil.which("docker") is not None


def docker_compose_available() -> bool:
    if not docker_available():
        return False
    process = subprocess.run(
        ("docker", "compose", "version"),
        text=True,
        capture_output=True,
        check=False,
    )
    return process.returncode == 0


def _compose_env(config: InfinityContextCliConfig) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("MEMORY_SERVICE_TOKEN", config.service_token)
    env.setdefault("COMPOSE_PROJECT_NAME", config.compose_project_name)
    if config.env_path.exists():
        env.setdefault("INFINITY_CONTEXT_ENV_FILE", str(config.env_path))
    return env


def _compose_detection_envs(config: InfinityContextCliConfig) -> list[dict[str, str]]:
    configured = _compose_env(config)
    default_project = configured.copy()
    default_project.pop("COMPOSE_PROJECT_NAME", None)
    return [configured, default_project]


def _compose_port(
    *,
    config: InfinityContextCliConfig,
    service: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ("docker", "compose", "port", service, "7788"),
            cwd=config.repo_dir,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _published_url_from_compose_port(output: str) -> str | None:
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not first_line:
        return None
    host, separator, port = first_line.rpartition(":")
    if not separator or not port.isdigit():
        return None
    clean_host = host.strip("[]")
    if clean_host in {"", "0.0.0.0", "::", "[::]"}:
        clean_host = "127.0.0.1"
    return f"http://{clean_host}:{port}"
