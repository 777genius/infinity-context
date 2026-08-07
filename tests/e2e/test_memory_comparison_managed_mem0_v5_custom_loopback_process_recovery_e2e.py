"""Custom-loopback orchestration proof paired with the actual PR35 adapter gate."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from memory_comparison_managed_mem0_v5_custom_loopback_process_harness import (
    SECRETS,
    prepare_environment,
)

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).with_name(
    "memory_comparison_managed_mem0_v5_custom_loopback_process_harness.py"
)
ACTUAL_ADAPTER_ROOT = ROOT / "benchmarks" / "mem0-oss-adapter-v5"
ACTUAL_ADAPTER_SELECTORS = (
    "tests/test_composition_provider_free.py",
    "tests/test_app.py",
    "tests/test_request_binding.py",
    "tests/test_authenticated_evidence.py",
)
HOSTING_STATE_PARENT = Path(
    os.environ.get(
        "INFINITY_CONTEXT_HOSTING_E2E_ROOT",
        "/mnt/volume_ams3_1784742570542/infinity-context/e2e-state",
    )
)
PROCESS_TIMEOUT = 45.0
_CLEAN_PYTEST_SUMMARY = re.compile(
    r"^(?P<passed>[1-9][0-9]*) passed in [0-9]+(?:\.[0-9]+)?s$"
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _spawn(*arguments: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(HARNESS), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _runner(root: Path, mode: str) -> subprocess.Popen[bytes]:
    return _spawn("runner", "--root", str(root), "--mode", mode)


def _wait_path(
    path: Path,
    process: subprocess.Popen[bytes],
    timeout: float = PROCESS_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if process.poll() is not None:
            output, _ = process.communicate()
            raise AssertionError(output.decode(errors="replace"))
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.03)


def _wait_health(port: int) -> None:
    deadline = time.monotonic() + PROCESS_TIMEOUT
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                if response.status == 200:
                    payload = json.loads(response.read())
                    assert payload["service"] == "managed-v5-test-loopback"
                    return
        except Exception:
            pass
        if time.monotonic() >= deadline:
            raise AssertionError("adapter health timeout")
        time.sleep(0.05)


def _kill(process: subprocess.Popen[bytes]) -> bytes:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    output, _ = process.communicate(timeout=10)
    return output


def _stop(process: subprocess.Popen[bytes]) -> bytes:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        output, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        return _kill(process)
    return output


def _complete(process: subprocess.Popen[bytes]) -> bytes:
    try:
        output, _ = process.communicate(timeout=PROCESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill(process)
        raise AssertionError("child process timeout") from None
    assert process.returncode == 0, output.decode(errors="replace")
    return output


def _capture(root: Path, name: str, output: bytes) -> None:
    path = root / "results" / f"custom-loopback-{name}.log"
    path.write_bytes(output)
    os.chmod(path, 0o600)


def _read_json(path: Path):
    return json.loads(path.read_text())


def _events(db: Path) -> list[tuple[int, str, str, int, str]]:
    with sqlite3.connect(db) as connection:
        return connection.execute(
            "SELECT id,path,kind,pid,detail FROM events ORDER BY id"
        ).fetchall()


def _counts(db: Path) -> tuple[list[tuple[str, int]], tuple[int, int]]:
    with sqlite3.connect(db) as connection:
        operations = connection.execute(
            "SELECT operation_id,dispatch_commit_count FROM operations ORDER BY sequence"
        ).fetchall()
        cleanup = connection.execute(
            "SELECT commit_count,length(receipt_json) FROM cleanup WHERE singleton=1"
        ).fetchone()
    assert cleanup is not None
    return operations, cleanup


def _assert_checkpoint_head_consistent(root: Path) -> None:
    checkpoint = _read_json(root / "state" / "checkpoint.json")
    assert checkpoint["run_phase"] == "terminal"
    assert checkpoint["units"][0]["record_ids"] == ["record-0"]
    assert checkpoint["units"][1]["record_ids"] == []
    commitment = checkpoint["checkpoint_commitment_sha256"]
    with sqlite3.connect(root / "state" / "checkpoint-head.sqlite3") as connection:
        rows = connection.execute(
            "SELECT generation,head_commitment_sha256 FROM checkpoint_heads"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] >= 1
    assert rows[0][1] == commitment


def _parse_clean_actual_adapter_summary(stdout: str) -> int:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError("actual adapter pytest emitted no terminal summary")
    summary = lines[-1]
    match = _CLEAN_PYTEST_SUMMARY.fullmatch(summary)
    if match is None:
        raise AssertionError(f"unclean actual adapter pytest summary: {summary!r}")
    passed_count = int(match.group("passed"))
    if passed_count != 39:
        raise AssertionError(f"expected exactly 39 passed, got {passed_count}")
    return passed_count


def _run_actual_adapter_gate(root: Path) -> dict[str, object]:
    interpreter = (ACTUAL_ADAPTER_ROOT / ".venv" / "bin" / "python").absolute()
    command = [
        str(interpreter),
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        *ACTUAL_ADAPTER_SELECTORS,
    ]
    environment = os.environ.copy()
    environment["PYTEST_ADDOPTS"] = ""
    completed = subprocess.run(
        command,
        cwd=ACTUAL_ADAPTER_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=PROCESS_TIMEOUT,
        check=False,
    )
    stdout = completed.stdout.decode(errors="replace")
    stderr = completed.stderr.decode(errors="replace")
    assert completed.returncode == 0, stdout + stderr
    passed_count = _parse_clean_actual_adapter_summary(stdout)
    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=10
    ).strip()
    evidence = {
        "schema_version": "managed-v5.actual-pr35-adapter-paired-gate.v1",
        "proof_kind": "pinned_actual_pr35_adapter_provider_free_gate",
        "interpreter": str(interpreter),
        "command": command,
        "test_selectors": list(ACTUAL_ADAPTER_SELECTORS),
        "effective_pytest_addopts": environment["PYTEST_ADDOPTS"],
        "git_head": git_head,
        "completed_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "returncode": completed.returncode,
        "passed_count": passed_count,
        "outcome": f"{passed_count} passed",
        "stdout": stdout,
        "stderr": stderr,
    }
    path = root / "results" / "paired-actual-pr35-adapter-gate.json"
    path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    os.chmod(path, 0o600)
    return evidence


def _assert_no_secret_leaks(root: Path, config: dict[str, object]) -> None:
    configured = config["secret_paths"]
    assert type(configured) is dict
    secret_paths = {Path(value).resolve() for value in configured.values()}
    assert secret_paths == {(root / "secrets" / name).resolve() for name in SECRETS}
    for name, secret in SECRETS.items():
        path = (root / "secrets" / name).resolve()
        metadata = path.lstat()
        assert path.is_file() and not path.is_symlink()
        assert metadata.st_mode & 0o777 == 0o600
        assert path.read_bytes() == secret

    needles: set[bytes] = set()
    for secret in SECRETS.values():
        standard_base64 = base64.b64encode(secret)
        urlsafe_base64 = base64.urlsafe_b64encode(secret)
        needles.update(
            {
                secret,
                secret.hex().encode(),
                secret.hex().upper().encode(),
                standard_base64,
                standard_base64.rstrip(b"="),
                urlsafe_base64,
                urlsafe_base64.rstrip(b"="),
            }
        )
    scanned = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError(f"unexpected generated symlink: {path}")
        if not path.is_file() or path.resolve() in secret_paths:
            continue
        content = path.read_bytes()
        assert not any(needle in content for needle in needles), path
        scanned += 1
    assert scanned >= 15


@pytest.mark.parametrize(
    "summary",
    [
        "38 passed in 1.00s",
        "39 passed, 1 skipped in 1.00s",
        "1 failed, 39 passed in 1.00s",
        "39 passed, 1 error in 1.00s",
        "39 passed, 1 xfailed in 1.00s",
        "39 passed, 1 xpassed in 1.00s",
        "39 passed, 1 deselected in 1.00s",
        "39 passed, 1 warning in 1.00s",
        "39 passed in 1.00s\ntrailing output",
    ],
)
def test_actual_adapter_terminal_summary_parser_rejects_unclean_outcomes(
    summary: str,
) -> None:
    with pytest.raises(AssertionError):
        _parse_clean_actual_adapter_summary(summary)


def test_actual_adapter_terminal_summary_parser_accepts_exact_outcome() -> None:
    assert _parse_clean_actual_adapter_summary("progress\n39 passed in 1.00s\n") == 39


def test_managed_mem0_v5_custom_loopback_process_recovery_with_actual_adapter_gate() -> None:
    if not HOSTING_STATE_PARENT.parent.exists():
        pytest.skip("hosting /mnt volume is required")
    HOSTING_STATE_PARENT.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="managed-v5-custom-loopback-", dir=HOSTING_STATE_PARENT))
    os.chmod(root, 0o700)
    port = _free_port()
    config = prepare_environment(root, port)
    adapter = _spawn("adapter", "--root", str(root), "--port", str(port))
    children: list[subprocess.Popen[bytes]] = [adapter]
    try:
        _wait_health(port)

        dispatch_a = _runner(root, "dispatch-a")
        children.append(dispatch_a)
        try:
            _wait_path(root / "barriers" / "dispatch-committed", dispatch_a)
        except AssertionError as exc:
            raise AssertionError(f"{exc}\nAUDIT={_events(Path(config['audit_db']))}") from None
        _capture(root, "stdout-dispatch-a", _kill(dispatch_a))
        (root / "barriers" / "dispatch-released").touch()

        finish_b = _runner(root, "finish")
        children.append(finish_b)
        _capture(root, "stdout-finish", _complete(finish_b))
        search = _read_json(root / "results" / "custom-loopback-search.json")
        assert search == {
            "count": 1,
            "record_ids": ["record-0"],
            "source_ids": [config["units"][0]["source_id"]],
        }

        cleanup_a = _runner(root, "cleanup-a")
        children.append(cleanup_a)
        _wait_path(root / "barriers" / "cleanup-committed", cleanup_a)
        _capture(root, "stdout-cleanup-a", _kill(cleanup_a))
        (root / "barriers" / "cleanup-released").touch()

        cleanup_b = _runner(root, "cleanup-b")
        children.append(cleanup_b)
        _capture(root, "stdout-cleanup-b", _complete(cleanup_b))
        events_before_terminal = _events(Path(config["audit_db"]))

        terminal_c = _runner(root, "terminal-c")
        children.append(terminal_c)
        _capture(root, "stdout-terminal-c", _complete(terminal_c))
        events_after_terminal = _events(Path(config["audit_db"]))
        assert events_after_terminal == events_before_terminal

        terminal_b = (root / "results" / "custom-loopback-terminal-cleanup-b.json").read_bytes()
        terminal_c_bytes = (
            root / "results" / "custom-loopback-terminal-terminal-c.json"
        ).read_bytes()
        assert terminal_b == terminal_c_bytes
        terminal = json.loads(terminal_b)
        assert terminal["terminal_state"] == "deleted"
        assert terminal["deleted_operation_count"] == 2
        assert terminal["residual_record_count"] == 0

        operations, cleanup = _counts(Path(config["audit_db"]))
        assert len(operations) == 2
        assert all(commit_count == 1 for _, commit_count in operations)
        assert cleanup[0] == 1
        events = events_after_terminal
        paths = [path for _, path, kind, _, _ in events if kind == "http"]
        assert paths.count("/v5/operations/dispatch") == 2
        assert paths.count("/v5/runs/cleanup") == 2
        assert set(paths) == {
            "/health",
            "/v5/runs/admit",
            "/v5/operations/request-binding",
            "/v5/operations/dispatch",
            "/v5/operations/status",
            "/v5/operations/storage-observation",
            "/v5/runs/search",
            "/v5/runs/cleanup",
        }
        assert all(path == "/health" or path.startswith("/v5/") for path in paths)
        assert not any(path.startswith(("/memories", "/search", "/v3/")) for path in paths)
        operation_zero = config["units"][0]["operation_id_sha256"]
        dispatch_calls = [detail for _, _, kind, _, detail in events if kind == "dispatch_call"]
        assert len(dispatch_calls) == 2
        assert dispatch_calls.count(operation_zero) == 1
        cleanup_commit_id = next(
            event_id for event_id, _, kind, _, _ in events if kind == "cleanup_commit"
        )
        assert not any(
            event_id > cleanup_commit_id and kind == "status_call"
            for event_id, _, kind, _, _ in events
        )

        pids = {
            _read_json(path)["pid"]
            for path in (root / "results").glob("custom-loopback-pid-*.json")
        }
        assert len(pids) == 5
        assert adapter.pid not in pids
        _assert_checkpoint_head_consistent(root)
        _capture(root, "stdout-adapter", _stop(adapter))
        paired_gate = _run_actual_adapter_gate(root)
        assert paired_gate["outcome"] == "39 passed"
        assert paired_gate["passed_count"] == 39
        assert paired_gate["effective_pytest_addopts"] == ""
        assert paired_gate["git_head"]
        _assert_no_secret_leaks(root, config)
    finally:
        for process in reversed(children):
            if process.poll() is None:
                _kill(process)
        shutil.rmtree(root)
