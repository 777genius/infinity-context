from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATHS = [
    PROJECT_ROOT / "packages" / "memo_stack_core",
    PROJECT_ROOT / "packages" / "memo_stack_server",
    PROJECT_ROOT / "packages" / "memo_stack_adapters",
    PROJECT_ROOT / "packages" / "memo_stack_sdk",
    PROJECT_ROOT / "packages" / "memo_stack_mcp",
]


@dataclass(frozen=True)
class MemoryServerHandle:
    base_url: str
    token: str
    env: dict[str, str]


@contextmanager
def run_memo_stack_server(
    tmp_path: Path,
    *,
    token: str = "test-token",
    database_name: str = "memory.db",
    extra_env: dict[str, str] | None = None,
) -> Iterator[MemoryServerHandle]:
    port = free_port()
    env = python_env(
        {
            "MEMORY_DEPLOY_PROFILE": "test",
            "MEMORY_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / database_name}",
            "MEMORY_AUTO_CREATE_SCHEMA": "true",
            "MEMORY_SERVICE_TOKEN": token,
            "MEMORY_HOST": "127.0.0.1",
            "MEMORY_PORT": str(port),
            "MEMORY_QDRANT_ENABLED": "false",
            "MEMORY_GRAPHITI_ENABLED": "false",
            "MEMORY_EMBEDDINGS_ENABLED": "false",
            **(extra_env or {}),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "memo_stack_server.main"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        wait_for_health(base_url, process)
        yield MemoryServerHandle(base_url=base_url, token=token, env=env)
    finally:
        stop_process(process)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 20
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"memo_stack_server exited early:\n{output}")
        try:
            response = httpx.get(f"{base_url}/v1/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"memo_stack_server did not become healthy: {last_error}")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def python_env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    paths = [str(path) for path in PACKAGE_PATHS]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.update(overrides)
    return env
