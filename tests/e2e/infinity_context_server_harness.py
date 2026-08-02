from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATHS = [
    PROJECT_ROOT / "packages" / "infinity_context_core",
    PROJECT_ROOT / "packages" / "infinity_context_server",
    PROJECT_ROOT / "packages" / "infinity_context_adapters",
    PROJECT_ROOT / "packages" / "infinity_context_sdk",
    PROJECT_ROOT / "packages" / "infinity_context_obsidian",
    PROJECT_ROOT / "packages" / "infinity_context_mcp",
    PROJECT_ROOT / "packages" / "infinity_context_cli",
]


@dataclass(frozen=True)
class MemoryServerHandle:
    base_url: str
    token: str
    env: dict[str, str]


_LOG_LIMIT_BYTES = 128 * 1024
_FAILURE_TAIL_BYTES = 8 * 1024
_WORKER_STARTUP_SECONDS = 0.2
_DRAIN_CHUNK_BYTES = 8 * 1024


class _BoundedTempLog:
    def __init__(self, directory: Path, *, name: str) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f"{name}-",
            suffix=".log",
            dir=directory,
            delete=False,
        ) as handle:
            self._path = Path(handle.name)
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            current = self._path.read_bytes()
            self._path.write_bytes((current + data)[-_LOG_LIMIT_BYTES:])

    def tail(self, *, limit: int = _FAILURE_TAIL_BYTES) -> str:
        with self._lock:
            return self._path.read_bytes()[-limit:].decode("utf-8", errors="replace")


    @property
    def path(self) -> Path:
        return self._path


@dataclass(frozen=True)
class _LoggedProcess:
    process: subprocess.Popen[bytes]
    log: _BoundedTempLog
    drainer: threading.Thread


@contextmanager
def run_infinity_context_server(
    tmp_path: Path,
    *,
    token: str = "test-token",
    database_name: str = "memory.db",
    extra_env: dict[str, str] | None = None,
    projection_worker: bool = False,
) -> Iterator[MemoryServerHandle]:
    port = free_port()
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
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
            "TMPDIR": str(temp_dir),
            "TMP": str(temp_dir),
            "TEMP": str(temp_dir),
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            **(extra_env or {}),
        }
    )
    server = _start_logged_process(
        [sys.executable, "-m", "infinity_context_server.main"],
        env=env,
        log_dir=temp_dir,
        name="infinity-context-server",
    )
    worker: _LoggedProcess | None = None
    try:
        base_url = f"http://127.0.0.1:{port}"
        wait_for_health(base_url, server)
        if projection_worker:
            worker = _start_logged_process(
                [
                    sys.executable,
                    "-m",
                    "infinity_context_server.worker",
                    "--loop",
                    "--role",
                    "projection",
                    "--limit",
                    "500",
                    "--concurrency",
                    "4",
                    "--sleep-seconds",
                    "0.05",
                ],
                env=env,
                log_dir=temp_dir,
                name="infinity-context-projection-worker",
            )
            _wait_for_liveness(worker, label="infinity_context projection worker")
        try:
            yield MemoryServerHandle(base_url=base_url, token=token, env=env)
        except BaseException as exc:
            _attach_process_tails(exc, server=server, worker=worker)
            _require_liveness(server, label="infinity_context_server")
            if worker is not None:
                _require_liveness(worker, label="infinity_context projection worker")
            raise
        else:
            _require_liveness(server, label="infinity_context_server")
            if worker is not None:
                _require_liveness(worker, label="infinity_context projection worker")
    finally:
        if worker is not None:
            stop_process(worker)
        stop_process(server)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_logged_process(
    command: list[str],
    *,
    env: dict[str, str],
    log_dir: Path,
    name: str,
) -> _LoggedProcess:
    log = _BoundedTempLog(log_dir, name=name)
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
    )
    if process.stdout is None:
        raise AssertionError(f"{name} log stream is unavailable")
    drainer = threading.Thread(
        target=_drain_process_output,
        args=(process.stdout, log),
        name=f"{name}-log-drainer",
        daemon=True,
    )
    drainer.start()
    return _LoggedProcess(process, log, drainer)


def _drain_process_output(stream: object, log: _BoundedTempLog) -> None:
    read = stream.read
    close = stream.close
    try:
        while True:
            chunk = read(_DRAIN_CHUNK_BYTES)
            if not chunk:
                return
            log.append(chunk)
    finally:
        close()


def wait_for_health(base_url: str, server: _LoggedProcess) -> None:
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        _require_liveness(server, label="infinity_context_server")
        try:
            response = httpx.get(f"{base_url}/v1/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(
        f"infinity_context_server did not become healthy: {last_error}; "
        f"log tail:\n{server.log.tail()}"
    )


def _wait_for_liveness(process: _LoggedProcess, *, label: str) -> None:
    deadline = time.monotonic() + _WORKER_STARTUP_SECONDS
    while time.monotonic() < deadline:
        _require_liveness(process, label=label)
        time.sleep(0.02)
    _require_liveness(process, label=label)


def _attach_process_tails(
    error: BaseException,
    *,
    server: _LoggedProcess,
    worker: _LoggedProcess | None,
) -> None:
    worker_tail = "<not started>" if worker is None else worker.log.tail()
    error.add_note(
        "infinity_context_server log tail:\n"
        f"{server.log.tail()}\n"
        "infinity_context projection worker log tail:\n"
        f"{worker_tail}"
    )


def _require_liveness(process: _LoggedProcess, *, label: str) -> None:
    exit_code = process.process.poll()
    if exit_code is not None:
        raise AssertionError(
            f"{label} exited early with code {exit_code}; log tail:\n{process.log.tail()}"
        )


def stop_process(running: _LoggedProcess) -> None:
    process = running.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    running.drainer.join(timeout=2)


def python_env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    paths = [str(path) for path in PACKAGE_PATHS]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env.update(overrides)
    return env
