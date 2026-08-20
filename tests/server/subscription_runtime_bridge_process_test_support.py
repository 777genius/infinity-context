"""Fake-process support for the subscription runtime launcher tests."""

from __future__ import annotations

import hashlib
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infinity_context_runtime_bridge import process_launcher
from infinity_context_runtime_bridge.contracts import (
    BridgeAuthority,
)
from infinity_context_runtime_bridge.process_contracts import (
    AccountIRuntimeFence,
    BridgeFleetSpec,
    BridgePrivateFiles,
    BridgeProcessSpec,
    ProcessIdentity,
    RuntimeHealthEvidence,
)
from infinity_context_server.memory_comparison_publishable_methodology import (
    SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
)

API_SECRET = "test-api-capability-" + "a" * 48
ATTESTATION_SECRET = "test-attestation-capability-" + "b" * 48
LAUNCHER_KEY = b"test-launcher-receipt-key-" + b"c" * 40
BOOT_ID = "11111111-2222-4333-8444-555555555555"
ACCOUNT_I_PID = 49_001
ACCOUNT_I_PORT = 45_000
BRIDGE_PORTS = (45_101, 45_102, 45_103)
BRIDGE_ACCOUNTS = ("account-j", "account-k", "account-l")


def sha(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def build_fleet_spec(tmp_path: Path) -> BridgeFleetSpec:
    """Create private fake resources for three new accounts, never account-i."""

    public_root = tmp_path / "reviewed-runtime"
    runtime_root = public_root / "runtime-root"
    runtime_entrypoint = runtime_root / "repo/dist/openai-compatible-codex/cli.js"
    runtime_entrypoint.parent.mkdir(parents=True)
    runtime_entrypoint.write_bytes(b"reviewed fake runtime entrypoint\n")
    runtime_manifest = runtime_root / "artifact-manifest.json"
    runtime_manifest.write_bytes(b'{"artifact":"reviewed-test-runtime"}\n')
    binaries = public_root / "binaries"
    binaries.mkdir()
    node_executable = binaries / "node"
    codex_executable = binaries / "codex"
    node_executable.write_bytes(b"reviewed fake node executable\n")
    codex_executable.write_bytes(b"reviewed fake codex executable\n")
    node_executable.chmod(0o500)
    codex_executable.chmod(0o500)

    processes: list[BridgeProcessSpec] = []
    for index, (account_name, port) in enumerate(zip(BRIDGE_ACCOUNTS, BRIDGE_PORTS, strict=True)):
        state_root = tmp_path / f"private-state-{index}"
        auth_root = tmp_path / f"private-auth-{index}"
        state_root.mkdir(mode=0o700)
        auth_root.mkdir(mode=0o700)
        account_auth_root = auth_root / account_name
        account_auth_root.mkdir(mode=0o700)
        _write_private(account_auth_root / "auth.json", b'{"kind":"fake-account-auth"}\n')
        api_key = auth_root / "ingress-api-key.secret"
        attestation = auth_root / "attestation-hmac.secret"
        launcher_key = auth_root / "launcher-receipt.key"
        _write_private(api_key, API_SECRET.encode())
        _write_private(attestation, ATTESTATION_SECRET.encode())
        _write_private(launcher_key, LAUNCHER_KEY)
        authority = BridgeAuthority(
            bridge_id=f"new-runtime-bridge-{index}",
            origin=f"http://127.0.0.1:{port}",
            account_binding_hmac_sha256=sha(f"account-binding:{account_name}"),
            public_model="gpt-5.6-sol",
            base_instructions_sha256=SUBSCRIPTION_RUNTIME_BASE_INSTRUCTIONS_SHA256,
        )
        processes.append(
            BridgeProcessSpec(
                account_name=account_name,
                port=port,
                authority=authority,
                state_root=state_root,
                auth_root=auth_root,
                private_files=BridgePrivateFiles(
                    api_key=api_key,
                    attestation_secret=attestation,
                    launcher_receipt_key=launcher_key,
                ),
                runtime_root=runtime_root,
                runtime_artifact_manifest_sha256=_file_sha256(runtime_manifest),
                runtime_entrypoint_sha256=_file_sha256(runtime_entrypoint),
                node_executable=node_executable,
                node_executable_sha256=_file_sha256(node_executable),
                codex_executable=codex_executable,
                codex_executable_sha256=_file_sha256(codex_executable),
                readiness_timeout_seconds=0.1,
                shutdown_grace_seconds=0.05,
            )
        )
    return BridgeFleetSpec(
        pool_id="three-new-runtime-bridges",
        processes=tuple(processes),
        account_i_fence=AccountIRuntimeFence(
            pid=ACCOUNT_I_PID,
            port=ACCOUNT_I_PORT,
            state_root=tmp_path / "protected-existing-state-root",
            auth_root=tmp_path / "protected-existing-auth-root",
        ),
    )


@dataclass(slots=True, repr=False)
class SpawnRecord:
    command: tuple[str, ...]
    cwd: Path
    environment: dict[str, str] = field(repr=False)
    stdin: object
    stdout: object
    stderr: object
    close_fds: bool
    shell: bool
    start_new_session: bool
    restore_signals: bool
    umask: int
    pid: int

    def __repr__(self) -> str:
        return (
            "SpawnRecord("
            f"command={self.command!r}, cwd={str(self.cwd)!r}, pid={self.pid!r}, "
            "environment=<private>)"
        )


class FakePopen:
    """Small Popen surface; it never starts a host process."""

    __slots__ = ("_control", "pid", "returncode")

    def __init__(self, *, pid: int, control: FakeProcessControl) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self._control = control

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self._control.terminate(self.pid, returncode=-signal.SIGTERM)

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            raise subprocess.TimeoutExpired(("fake-process",), 0)
        return self.returncode


class FakeProcessControl:
    __slots__ = ("_identities", "_processes", "signals", "launcher_pgid")

    def __init__(self) -> None:
        self._identities: dict[int, ProcessIdentity] = {}
        self._processes: dict[int, FakePopen] = {}
        self.signals: list[tuple[int, int]] = []
        self.launcher_pgid = 40_000

    def register(self, process: FakePopen, *, start_ticks: int) -> None:
        identity = ProcessIdentity(
            pid=process.pid,
            start_ticks=start_ticks,
            pgid=process.pid,
            boot_id=BOOT_ID,
        )
        self._identities[process.pid] = identity
        self._processes[process.pid] = process

    def identity(self, pid: int) -> ProcessIdentity | None:
        return self._identities.get(pid)

    def signal_group(self, pgid: int, signum: int) -> None:
        self.signals.append((pgid, signum))
        if signum not in {signal.SIGTERM, signal.SIGKILL}:
            raise AssertionError("unexpected fake signal")
        self.terminate(pgid, returncode=-signum)

    def current_pgid(self) -> int:
        return self.launcher_pgid

    def terminate(self, pid: int, *, returncode: int) -> None:
        process = self._processes.get(pid)
        if process is not None:
            process.returncode = returncode
        self._identities.pop(pid, None)

    def lose_identity(self, pid: int, *, replacement_start_ticks: int | None = None) -> None:
        if replacement_start_ticks is None:
            self.terminate(pid, returncode=17)
            return
        self._identities[pid] = ProcessIdentity(
            pid=pid,
            start_ticks=replacement_start_ticks,
            pgid=pid,
            boot_id=BOOT_ID,
        )


class FakeProcessHarness:
    """Records spawn and health activity without exposing a provider-call surface."""

    __slots__ = (
        "control",
        "health_calls",
        "next_pid",
        "provider_dispatches",
        "spawn_records",
    )

    def __init__(self) -> None:
        self.control = FakeProcessControl()
        self.next_pid = 51_000
        self.spawn_records: list[SpawnRecord] = []
        self.health_calls: list[int] = []
        self.provider_dispatches = 0

    def install(self, monkeypatch) -> None:
        monkeypatch.setattr(process_launcher.subprocess, "Popen", self.spawn)
        monkeypatch.setattr(process_launcher, "_probe_health_once", self.probe_health)

    def spawn(self, args: list[str], **kwargs: Any) -> FakePopen:
        pid = self.next_pid
        self.next_pid += 1
        environment = dict(kwargs["env"])
        process = FakePopen(pid=pid, control=self.control)
        self.control.register(process, start_ticks=700_000 + pid)
        self.spawn_records.append(
            SpawnRecord(
                command=tuple(args),
                cwd=Path(kwargs["cwd"]),
                environment=environment,
                stdin=kwargs["stdin"],
                stdout=kwargs["stdout"],
                stderr=kwargs["stderr"],
                close_fds=kwargs["close_fds"],
                shell=kwargs["shell"],
                start_new_session=kwargs["start_new_session"],
                restore_signals=kwargs["restore_signals"],
                umask=kwargs["umask"],
                pid=pid,
            )
        )
        return process

    def probe_health(self, spec: BridgeProcessSpec) -> RuntimeHealthEvidence:
        self.health_calls.append(spec.port)
        body = (
            b'{"accountCount":1,"activeRequests":0,"model":"gpt-5.6-sol",'
            b'"ok":true,"queuedRequests":0,'
            b'"service":"subscription-runtime-openai-compatible-codex"}'
        )
        return RuntimeHealthEvidence(
            response_body_sha256=hashlib.sha256(body).hexdigest(),
            observed_at_unix_ms=1_786_320_000_000 + len(self.health_calls),
        )


def private_state_bytes(spec: BridgeProcessSpec) -> bytes:
    chunks: list[bytes] = []
    for path in sorted(spec.state_root.rglob("*")):
        if path.is_file():
            chunks.append(path.read_bytes())
    return b"\n".join(chunks)


def _write_private(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = (
    "ACCOUNT_I_PID",
    "ACCOUNT_I_PORT",
    "API_SECRET",
    "ATTESTATION_SECRET",
    "BOOT_ID",
    "BRIDGE_ACCOUNTS",
    "BRIDGE_PORTS",
    "FakeProcessHarness",
    "LAUNCHER_KEY",
    "build_fleet_spec",
    "private_state_bytes",
    "sha",
)
