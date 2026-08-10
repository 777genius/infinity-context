"""Linux production launcher for three isolated subscription-runtime bridges.

Readiness is a bounded, provider-free ``GET /health``.  This module has no
chat-completions path and never adopts or signals a PID without exact Linux
process identity plus an authenticated local launch record.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import os
import signal
import subprocess
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import Literal, final

from .json_boundary import (
    BridgeJsonError,
    canonical_json_bytes,
    exact_object,
    strict_json_loads,
)
from .process_contracts import (
    CODEX_EXECUTABLE_MAX_BYTES,
    BridgeFleetReadinessReceipt,
    BridgeFleetSpec,
    BridgeLaunchReceipt,
    BridgeProcessError,
    BridgeProcessSpec,
    GracefulStopMetadata,
    PendingLaunchMetadata,
    ProcessIdentity,
    RuntimeHealthEvidence,
    RuntimeProcessAuthority,
)
from .process_control import LinuxProcessControl, ProcessControlPort
from .process_files import (
    StateLock as _StateLock,
)
from .process_files import (
    private_directory_identity as _private_directory_identity,
)
from .process_files import (
    read_private_file as _secure_read_private_file,
)
from .process_files import (
    read_private_json as _secure_read_private_json,
)
from .process_files import (
    sha256_private_file as _secure_sha256_private_file,
)
from .process_files import (
    verify_private_directory as _verify_private_directory,
)
from .process_files import (
    verify_private_file as _verify_private_file,
)
from .process_files import (
    verify_public_file as _verify_public_file,
)
from .process_files import (
    write_private_json_once as _secure_write_private_json_once,
)
from .process_files import (
    write_private_json_replace as _secure_write_private_json_replace,
)

_LAUNCHER_DIRECTORY = ".infinity-context-bridge-launcher"
_AUTHORITY_FILE = "runtime-authority.json"
_ACTIVE_FILE = "active.json"
_PENDING_FILE = "pending.json"
_READINESS_FILE = "readiness.json"
_STOP_FILE = "stop.json"
_MAX_METADATA_BYTES = 128 * 1024
_MAX_HEALTH_BYTES = 4096
_MAX_ARTIFACT_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_SECRET_BYTES = 4096
_HEALTH_RETRY_SECONDS = 0.05


@dataclass(frozen=True, slots=True, repr=False)
class _PrivateMaterial:
    api_key: str
    attestation_secret: str
    launcher_key: bytes
    binding_hmac_sha256: str

    def __repr__(self) -> str:
        return "_PrivateMaterial(<private>)"


@final
class RunningBridgeProcess:
    """One exact ready generation.  Repr and public views contain no secrets."""

    __slots__ = (
        "_control",
        "_popen",
        "_protected_pid",
        "_spec",
        "authority",
        "readiness",
        "reopened",
    )

    def __init__(
        self,
        *,
        spec: BridgeProcessSpec,
        authority: RuntimeProcessAuthority,
        readiness: BridgeLaunchReceipt,
        protected_pid: int,
        control: ProcessControlPort,
        popen: subprocess.Popen[bytes] | None,
        reopened: bool,
    ) -> None:
        self._spec = spec
        self.authority = authority
        self.readiness = readiness
        self._protected_pid = protected_pid
        self._control = control
        self._popen = popen
        self.reopened = reopened

    @property
    def command(self) -> tuple[str, str, str]:
        """The fixed, secret-free command shape used for this process."""

        return (
            str(self._spec.node_executable),
            str(self._spec.runtime_entrypoint),
            "serve",
        )

    def stop(self, *, reason: str = "operator-shutdown") -> GracefulStopMetadata:
        """SIGTERM once, bounded escalation, then immutable authenticated metadata."""

        _require_stop_reason(reason)
        key = _load_private_material(self._spec).launcher_key
        generation_root = _generation_root(self._spec.state_root, self.readiness.pending.generation)
        stop_path = generation_root / _STOP_FILE
        if stop_path.exists():
            metadata = GracefulStopMetadata.from_payload(_read_private_json(stop_path))
            metadata.verify(key)
            _require_stop_binding(metadata, self.readiness)
            return metadata

        pending = self.readiness.pending
        if (
            pending.process.pid == self._protected_pid
            or pending.process.pgid == self._protected_pid
        ):
            _fail("bridge_process_account_i_signal_refused")
        if pending.process.pgid == self._control.current_pgid():
            _fail("bridge_process_launcher_group_signal_refused")
        requested_at = _unix_ms()
        current = self._control.identity(pending.process.pid)
        signal_sent = current == pending.process
        escalated = False
        if signal_sent:
            self._control.signal_group(pending.process.pgid, signal.SIGTERM)
            if not self._wait_terminal(self._spec.shutdown_grace_seconds):
                current = self._control.identity(pending.process.pid)
                if current == pending.process:
                    self._control.signal_group(pending.process.pgid, signal.SIGKILL)
                    escalated = True
                if not self._wait_terminal(2.0):
                    _fail("bridge_process_stop_timeout")
        exit_code = self._popen.poll() if self._popen is not None else None
        metadata = GracefulStopMetadata.issue(
            pending=pending,
            readiness_receipt_sha256=self.readiness.commitment_sha256,
            reason=reason,
            requested_at_unix_ms=requested_at,
            stopped_at_unix_ms=max(requested_at, _unix_ms()),
            signal_sent=signal_sent,
            escalated=escalated,
            exit_code=exit_code,
            key=key,
        )
        _write_private_json_once(stop_path, metadata.public_payload())
        return metadata

    def reap(self) -> int | None:
        """Provider-free best-effort reap for a locally spawned detached test/controller."""

        return self._popen.poll() if self._popen is not None else None

    def _wait_terminal(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if self._popen is not None and self._popen.poll() is not None:
                return True
            if self._control.identity(self.readiness.pending.process.pid) != (
                self.readiness.pending.process
            ):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_HEALTH_RETRY_SECONDS, remaining))

    def __repr__(self) -> str:
        return (
            "RunningBridgeProcess("
            f"bridge_id={self.readiness.pending.bridge_id!r}, "
            f"generation={self.readiness.pending.generation!r}, "
            f"readiness_receipt_sha256={self.readiness.commitment_sha256!r})"
        )


@final
class ProductionBridgeFleet:
    """Resource-owning composition for exactly three new coding-account bridges."""

    __slots__ = (
        "_detached",
        "_locks",
        "_spec",
        "_stop_receipts",
        "processes",
        "readiness",
    )

    def __init__(
        self,
        *,
        spec: BridgeFleetSpec,
        processes: tuple[RunningBridgeProcess, RunningBridgeProcess, RunningBridgeProcess],
        locks: tuple[_StateLock, _StateLock, _StateLock],
    ) -> None:
        if (
            type(processes) is not tuple
            or len(processes) != 3
            or type(locks) is not tuple
            or len(locks) != 3
        ):
            _fail("bridge_process_fleet_runtime_members_invalid")
        for expected, process in zip(spec.processes, processes, strict=True):
            if (
                type(process) is not RunningBridgeProcess
                or process.authority.bridge_authority != expected.authority
                or process.readiness.runtime_authority_sha256 != process.authority.commitment_sha256
            ):
                _fail("bridge_process_fleet_runtime_authority_mismatch")
        self._spec = spec
        self.processes = processes
        self._locks = locks
        self._detached = False
        self._stop_receipts: (
            tuple[GracefulStopMetadata, GracefulStopMetadata, GracefulStopMetadata] | None
        ) = None
        self.readiness = BridgeFleetReadinessReceipt(
            pool=spec.pool,
            launches=tuple(item.readiness for item in processes),
        )

    @classmethod
    def create_new(
        cls,
        spec: BridgeFleetSpec,
        *,
        control: ProcessControlPort | None = None,
    ) -> ProductionBridgeFleet:
        """Create only from three empty private state roots; never auto-reopen."""

        return cls._open(spec, mode="create", control=control or LinuxProcessControl())

    @classmethod
    def reopen(
        cls,
        spec: BridgeFleetSpec,
        *,
        control: ProcessControlPort | None = None,
    ) -> ProductionBridgeFleet:
        """Reattach exact live generations or restart on the same durable roots."""

        return cls._open(spec, mode="reopen", control=control or LinuxProcessControl())

    @classmethod
    def _open(
        cls,
        spec: BridgeFleetSpec,
        *,
        mode: Literal["create", "reopen"],
        control: ProcessControlPort,
    ) -> ProductionBridgeFleet:
        if type(spec) is not BridgeFleetSpec:
            _fail("bridge_process_fleet_spec_invalid")
        _preflight_public(spec)
        _preflight_private_roots(spec, create=mode == "create")
        locks: list[_StateLock] = []
        processes: list[RunningBridgeProcess] = []
        try:
            for item in spec.processes:
                locks.append(
                    _StateLock.acquire(
                        item.state_root, _LAUNCHER_DIRECTORY, create=mode == "create"
                    )
                )
            for item, lock in zip(spec.processes, locks, strict=True):
                process = (
                    _start_generation(
                        item,
                        lock=lock,
                        generation=1,
                        mode="create",
                        protected_pid=spec.account_i_fence.pid,
                        control=control,
                    )
                    if mode == "create"
                    else _reopen_or_restart(
                        item,
                        lock=lock,
                        protected_pid=spec.account_i_fence.pid,
                        control=control,
                    )
                )
                processes.append(process)
            return cls(
                spec=spec,
                processes=tuple(processes),
                locks=tuple(locks),
            )
        except BaseException:
            for process in reversed(processes):
                with suppress(Exception):
                    process.stop(reason="partial-start-failure")
            for lock in reversed(locks):
                lock.close()
            raise

    def stop_all(
        self, *, reason: str = "operator-shutdown"
    ) -> tuple[GracefulStopMetadata, GracefulStopMetadata, GracefulStopMetadata]:
        if self._stop_receipts is not None:
            return self._stop_receipts
        if self._detached:
            _fail("bridge_process_fleet_controller_detached")
        by_bridge: dict[str, GracefulStopMetadata] = {}
        failure: BaseException | None = None
        for process in reversed(self.processes):
            try:
                by_bridge[process.readiness.pending.bridge_id] = process.stop(reason=reason)
            except BaseException as exc:
                if failure is None:
                    failure = exc
        self.close_controller()
        if failure is not None:
            raise failure
        result = tuple(by_bridge[item.authority.bridge_id] for item in self._spec.processes)
        self._stop_receipts = result
        return self._stop_receipts

    def close_controller(self) -> None:
        """Release ownership locks without signaling; used after stop or controller loss."""

        if self._detached:
            return
        self._detached = True
        for lock in reversed(self._locks):
            lock.close()

    def __enter__(self) -> ProductionBridgeFleet:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if not self._detached:
            self.stop_all(reason="context-exit")

    def __repr__(self) -> str:
        return (
            "ProductionBridgeFleet("
            f"pool_authority_sha256={self.readiness.pool.commitment_sha256!r}, "
            f"readiness_receipt_sha256={self.readiness.commitment_sha256!r}, "
            "private_material=<bound>)"
        )


def _start_generation(
    spec: BridgeProcessSpec,
    *,
    lock: _StateLock,
    generation: int,
    mode: Literal["create", "reopen"],
    protected_pid: int,
    control: ProcessControlPort,
) -> RunningBridgeProcess:
    material = _load_private_material(spec)
    authority = _runtime_authority(spec, material)
    _store_or_verify_authority(lock.lifecycle_root, authority, create=mode == "create")
    generation_root = _create_generation_root(spec.state_root, generation)
    launch_id = token_hex(32)
    environment = _child_environment(spec, material)
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [str(spec.node_executable), str(spec.runtime_entrypoint), "serve"],
            cwd=spec.state_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            shell=False,
            start_new_session=True,
            restore_signals=True,
            umask=0o077,
        )
    except OSError as exc:
        raise BridgeProcessError("bridge_process_spawn_failed") from exc
    finally:
        for name in (
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_API_KEY",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_ATTESTATION_SECRET",
        ):
            environment.pop(name, None)
    try:
        identity = _await_process_identity(process, control, protected_pid)
    except BaseException:
        if process.pid != protected_pid:
            with suppress(OSError):
                process.terminate()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2.0)
        raise
    try:
        pending = PendingLaunchMetadata.issue(
            account_name=spec.account_name,
            bridge_id=spec.authority.bridge_id,
            generation=generation,
            launch_id=launch_id,
            mode=mode,
            process=identity,
            runtime_authority_sha256=authority.commitment_sha256,
            started_at_unix_ms=_unix_ms(),
            key=material.launcher_key,
        )
        _write_private_json_once(generation_root / _PENDING_FILE, pending.public_payload())
        _write_private_json_replace(lock.lifecycle_root / _ACTIVE_FILE, pending.public_payload())
        health = _wait_for_health(spec, identity=identity, control=control, popen=process)
        _revalidate_launch_material(spec, authority, material)
        if control.identity(identity.pid) != identity:
            _fail("bridge_process_identity_changed_before_ready")
        readiness = BridgeLaunchReceipt.issue(
            pending=pending,
            health=health,
            bridge_authority_sha256=spec.authority.commitment_sha256,
            runtime_authority_sha256=authority.commitment_sha256,
            ready_at_unix_ms=max(_unix_ms(), health.observed_at_unix_ms),
            key=material.launcher_key,
        )
        _write_private_json_once(generation_root / _READINESS_FILE, readiness.public_payload())
        return RunningBridgeProcess(
            spec=spec,
            authority=authority,
            readiness=readiness,
            protected_pid=protected_pid,
            control=control,
            popen=process,
            reopened=False,
        )
    except BaseException:
        _terminate_failed_start(process, identity, protected_pid, control)
        raise


def _reopen_or_restart(
    spec: BridgeProcessSpec,
    *,
    lock: _StateLock,
    protected_pid: int,
    control: ProcessControlPort,
) -> RunningBridgeProcess:
    material = _load_private_material(spec)
    authority = _runtime_authority(spec, material)
    _store_or_verify_authority(lock.lifecycle_root, authority, create=False)
    pending = PendingLaunchMetadata.from_payload(
        _read_private_json(lock.lifecycle_root / _ACTIVE_FILE)
    )
    pending.verify(material.launcher_key)
    _require_pending_binding(spec, authority, pending)
    if pending.process.pid == protected_pid or pending.process.pgid == protected_pid:
        _fail("bridge_process_account_i_pid_collision")
    generation_root = _generation_root(spec.state_root, pending.generation)
    readiness_path = generation_root / _READINESS_FILE
    current = control.identity(pending.process.pid)
    if current == pending.process:
        if readiness_path.exists():
            readiness = BridgeLaunchReceipt.from_payload(_read_private_json(readiness_path))
            readiness.verify(material.launcher_key)
            _require_readiness_binding(spec, authority, pending, readiness)
            observed = _wait_for_health(spec, identity=pending.process, control=control, popen=None)
            if observed.response_body_sha256 != readiness.health.response_body_sha256:
                _fail("bridge_process_reopen_health_changed")
        else:
            health = _wait_for_health(spec, identity=pending.process, control=control, popen=None)
            readiness = BridgeLaunchReceipt.issue(
                pending=pending,
                health=health,
                bridge_authority_sha256=spec.authority.commitment_sha256,
                runtime_authority_sha256=authority.commitment_sha256,
                ready_at_unix_ms=max(_unix_ms(), health.observed_at_unix_ms),
                key=material.launcher_key,
            )
            _write_private_json_once(readiness_path, readiness.public_payload())
        _revalidate_launch_material(spec, authority, material)
        return RunningBridgeProcess(
            spec=spec,
            authority=authority,
            readiness=readiness,
            protected_pid=protected_pid,
            control=control,
            popen=None,
            reopened=True,
        )
    if readiness_path.exists():
        prior = BridgeLaunchReceipt.from_payload(_read_private_json(readiness_path))
        prior.verify(material.launcher_key)
        _require_readiness_binding(spec, authority, pending, prior)
        _record_observed_exit(spec, prior, material.launcher_key)
    return _start_generation(
        spec,
        lock=lock,
        generation=pending.generation + 1,
        mode="reopen",
        protected_pid=protected_pid,
        control=control,
    )


def _runtime_authority(
    spec: BridgeProcessSpec, material: _PrivateMaterial
) -> RuntimeProcessAuthority:
    return RuntimeProcessAuthority(
        account_name=spec.account_name,
        bridge_authority=spec.authority,
        state_root_identity_sha256=_private_directory_identity(spec.state_root, "state_root"),
        auth_root_identity_sha256=_private_directory_identity(spec.auth_root, "auth_root"),
        private_material_binding_hmac_sha256=material.binding_hmac_sha256,
        runtime_artifact_manifest_sha256=spec.runtime_artifact_manifest_sha256,
        runtime_entrypoint_sha256=spec.runtime_entrypoint_sha256,
        node_executable_sha256=spec.node_executable_sha256,
        codex_executable_sha256=spec.codex_executable_sha256,
    )


def _preflight_public(spec: BridgeFleetSpec) -> None:
    for item in spec.processes:
        _verify_public_material(item)


def _verify_public_material(item: BridgeProcessSpec) -> None:
    for path, digest, executable, maximum, label in (
        (
            item.runtime_artifact_manifest,
            item.runtime_artifact_manifest_sha256,
            False,
            _MAX_ARTIFACT_MANIFEST_BYTES,
            "runtime_manifest",
        ),
        (
            item.runtime_entrypoint,
            item.runtime_entrypoint_sha256,
            False,
            16 * 1024 * 1024,
            "runtime_entrypoint",
        ),
        (
            item.node_executable,
            item.node_executable_sha256,
            True,
            256 * 1024 * 1024,
            "node_executable",
        ),
        (
            item.codex_executable,
            item.codex_executable_sha256,
            True,
            CODEX_EXECUTABLE_MAX_BYTES,
            "codex_executable",
        ),
    ):
        _verify_public_file(
            path,
            digest,
            executable=executable,
            maximum_bytes=maximum,
            label=label,
        )


def _preflight_private_roots(spec: BridgeFleetSpec, *, create: bool) -> None:
    for item in spec.processes:
        _verify_private_directory(item.state_root, "state_root")
        _verify_private_directory(item.auth_root, "auth_root")
        account_root = item.auth_root / item.account_name
        _verify_private_directory(account_root, "account_auth_root")
        _verify_private_file(account_root / "auth.json", "account_auth")
        _load_private_material(item)
        if create:
            try:
                if any(item.state_root.iterdir()):
                    _fail("bridge_process_new_state_not_empty")
            except OSError as exc:
                raise BridgeProcessError("bridge_process_state_inspection_failed") from exc
        else:
            _verify_private_directory(item.state_root / _LAUNCHER_DIRECTORY, "lifecycle_root")


def _load_private_material(spec: BridgeProcessSpec) -> _PrivateMaterial:
    api_raw = _read_private_file(spec.private_files.api_key, "api_key")
    attestation_raw = _read_private_file(
        spec.private_files.attestation_secret, "attestation_secret"
    )
    launcher_key = _read_private_file(spec.private_files.launcher_receipt_key, "launcher_key")
    account_auth_sha256 = _sha256_private_file(
        spec.auth_root / spec.account_name / "auth.json", "account_auth"
    )
    api_key = _secret_text(api_raw, "api_key")
    attestation_secret = _secret_text(attestation_raw, "attestation_secret")
    if not 32 <= len(launcher_key) <= _MAX_SECRET_BYTES:
        _fail("bridge_process_launcher_key_invalid")
    private_binding = hmac.new(
        launcher_key,
        canonical_json_bytes(
            {
                "account_auth_sha256": account_auth_sha256,
                "api_key_sha256": hashlib.sha256(api_raw).hexdigest(),
                "attestation_secret_sha256": hashlib.sha256(attestation_raw).hexdigest(),
            }
        ),
        hashlib.sha256,
    ).hexdigest()
    return _PrivateMaterial(
        api_key=api_key,
        attestation_secret=attestation_secret,
        launcher_key=launcher_key,
        binding_hmac_sha256=private_binding,
    )


def _child_environment(spec: BridgeProcessSpec, material: _PrivateMaterial) -> dict[str, str]:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "TZ": "UTC",
    }
    home = spec.state_root / "process-home"
    temporary = spec.state_root / "tmp"
    runtime_state = spec.state_root / "runtime"
    for path in (home, temporary, runtime_state):
        try:
            path.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise BridgeProcessError("bridge_process_child_root_create_failed") from exc
        _verify_private_directory(path, "child_root")
    environment.update(
        {
            "HOME": str(home),
            "NO_PROXY": "127.0.0.1",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_ACCOUNTS": spec.account_name,
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_API_KEY": material.api_key,
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_ATTESTATION_SECRET": (material.attestation_secret),
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_AUTH_ROOT": str(spec.auth_root),
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_CODEX_BINARY": str(spec.codex_executable),
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_CODEX_MODEL": "gpt-5.6-sol",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_HOST": "127.0.0.1",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_MAX_ACCOUNT_CYCLES": "1",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_MAX_BODY_BYTES": str(
                RuntimeProcessAuthority.REQUEST_BODY_MAX_BYTES
            ),
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_MAX_CONCURRENT": "1",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_PORT": str(spec.port),
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_PUBLIC_MODEL": "gpt-5.6-sol",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_REASONING_EFFORT": "high",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_SERVICE_TIER": "priority",
            "SUBSCRIPTION_RUNTIME_OPENAI_BRIDGE_STATE_DIR": str(runtime_state),
            "TMPDIR": str(temporary),
        }
    )
    return environment


def _wait_for_health(
    spec: BridgeProcessSpec,
    *,
    identity: ProcessIdentity,
    control: ProcessControlPort,
    popen: subprocess.Popen[bytes] | None,
) -> RuntimeHealthEvidence:
    deadline = time.monotonic() + float(spec.readiness_timeout_seconds)
    last_contract_error: BridgeProcessError | None = None
    while True:
        if popen is not None and popen.poll() is not None:
            _fail("bridge_process_exited_before_ready")
        if control.identity(identity.pid) != identity:
            _fail("bridge_process_identity_changed_before_ready")
        try:
            return _probe_health_once(spec)
        except (ConnectionError, OSError, TimeoutError):
            pass
        except BridgeProcessError as exc:
            last_contract_error = exc
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if last_contract_error is not None:
                raise BridgeProcessError("bridge_process_readiness_contract_invalid") from None
            _fail("bridge_process_readiness_timeout")
        time.sleep(min(_HEALTH_RETRY_SECONDS, remaining))


def _probe_health_once(spec: BridgeProcessSpec) -> RuntimeHealthEvidence:
    connection = http.client.HTTPConnection("127.0.0.1", spec.port, timeout=0.5)
    try:
        connection.request(
            "GET",
            "/health",
            headers={"Accept": "application/json", "Connection": "close"},
        )
        response = connection.getresponse()
        raw = response.read(_MAX_HEALTH_BYTES + 1)
    finally:
        connection.close()
    if response.status != 200 or len(raw) > _MAX_HEALTH_BYTES:
        _fail("bridge_process_health_http_invalid")
    try:
        value = exact_object(
            strict_json_loads(raw, maximum_bytes=_MAX_HEALTH_BYTES),
            required=frozenset(
                {
                    "accountCount",
                    "activeRequests",
                    "model",
                    "ok",
                    "queuedRequests",
                    "service",
                }
            ),
            label="bridge_process_health_response",
        )
    except BridgeJsonError as exc:
        raise BridgeProcessError("bridge_process_health_json_invalid") from exc
    if value != {
        "accountCount": 1,
        "activeRequests": 0,
        "model": spec.authority.public_model,
        "ok": True,
        "queuedRequests": 0,
        "service": "subscription-runtime-openai-compatible-codex",
    }:
        _fail("bridge_process_health_body_invalid")
    return RuntimeHealthEvidence(
        response_body_sha256=hashlib.sha256(raw).hexdigest(),
        observed_at_unix_ms=_unix_ms(),
    )


def _await_process_identity(
    process: subprocess.Popen[bytes],
    control: ProcessControlPort,
    protected_pid: int,
) -> ProcessIdentity:
    if process.pid == protected_pid:
        _fail("bridge_process_account_i_pid_collision")
    deadline = time.monotonic() + 1.0
    while True:
        if process.poll() is not None:
            _fail("bridge_process_exited_during_spawn")
        identity = control.identity(process.pid)
        if identity is not None:
            if identity.pid == protected_pid or identity.pgid == protected_pid:
                _fail("bridge_process_account_i_pid_collision")
            if identity.pgid == control.current_pgid():
                _fail("bridge_process_session_isolation_failed")
            return identity
        if time.monotonic() >= deadline:
            _fail("bridge_process_identity_unavailable")
        time.sleep(0.01)


def _record_observed_exit(
    spec: BridgeProcessSpec, readiness: BridgeLaunchReceipt, key: bytes
) -> GracefulStopMetadata:
    stop_path = _generation_root(spec.state_root, readiness.pending.generation) / _STOP_FILE
    if stop_path.exists():
        existing = GracefulStopMetadata.from_payload(_read_private_json(stop_path))
        existing.verify(key)
        _require_stop_binding(existing, readiness)
        return existing
    observed_at = _unix_ms()
    metadata = GracefulStopMetadata.issue(
        pending=readiness.pending,
        readiness_receipt_sha256=readiness.commitment_sha256,
        reason="process-exit-observed",
        requested_at_unix_ms=observed_at,
        stopped_at_unix_ms=observed_at,
        signal_sent=False,
        escalated=False,
        exit_code=None,
        key=key,
    )
    _write_private_json_once(stop_path, metadata.public_payload())
    return metadata


def _terminate_failed_start(
    process: subprocess.Popen[bytes],
    identity: ProcessIdentity,
    protected_pid: int,
    control: ProcessControlPort,
) -> None:
    if identity.pid == protected_pid or identity.pgid == protected_pid:
        return
    if control.identity(identity.pid) == identity and identity.pgid != control.current_pgid():
        with suppress(Exception):
            control.signal_group(identity.pgid, signal.SIGTERM)
    deadline = time.monotonic() + 2.0
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(_HEALTH_RETRY_SECONDS)
    if process.poll() is None and control.identity(identity.pid) == identity:
        with suppress(Exception):
            control.signal_group(identity.pgid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=2.0)


def _store_or_verify_authority(
    lifecycle_root: Path, authority: RuntimeProcessAuthority, *, create: bool
) -> None:
    path = lifecycle_root / _AUTHORITY_FILE
    payload = authority.public_payload()
    if create:
        _write_private_json_once(path, payload)
        return
    if _read_private_json(path) != payload:
        _fail("bridge_process_runtime_authority_changed")


def _revalidate_launch_material(
    spec: BridgeProcessSpec,
    expected: RuntimeProcessAuthority,
    material: _PrivateMaterial,
) -> None:
    _verify_public_material(spec)
    current = _load_private_material(spec)
    if not hmac.compare_digest(current.binding_hmac_sha256, material.binding_hmac_sha256):
        _fail("bridge_process_private_material_changed")
    if _runtime_authority(spec, current) != expected:
        _fail("bridge_process_runtime_authority_changed")


def _require_pending_binding(
    spec: BridgeProcessSpec,
    authority: RuntimeProcessAuthority,
    pending: PendingLaunchMetadata,
) -> None:
    if (
        pending.account_name != spec.account_name
        or pending.bridge_id != spec.authority.bridge_id
        or pending.runtime_authority_sha256 != authority.commitment_sha256
    ):
        _fail("bridge_process_pending_binding_mismatch")


def _require_readiness_binding(
    spec: BridgeProcessSpec,
    authority: RuntimeProcessAuthority,
    pending: PendingLaunchMetadata,
    readiness: BridgeLaunchReceipt,
) -> None:
    _require_pending_binding(spec, authority, pending)
    if (
        readiness.pending != pending
        or readiness.bridge_authority_sha256 != spec.authority.commitment_sha256
        or readiness.runtime_authority_sha256 != authority.commitment_sha256
    ):
        _fail("bridge_process_readiness_binding_mismatch")


def _require_stop_binding(metadata: GracefulStopMetadata, readiness: BridgeLaunchReceipt) -> None:
    if (
        metadata.pending != readiness.pending
        or metadata.readiness_receipt_sha256 != readiness.commitment_sha256
    ):
        _fail("bridge_process_stop_binding_mismatch")


def _require_stop_reason(reason: object) -> None:
    if (
        not isinstance(reason, str)
        or not reason
        or len(reason) > 128
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in reason)
    ):
        _fail("bridge_process_stop_reason_invalid")


def _create_generation_root(state_root: Path, generation: int) -> Path:
    path = _generation_root(state_root, generation)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise BridgeProcessError("bridge_process_generation_exists") from exc
    except OSError as exc:
        raise BridgeProcessError("bridge_process_generation_create_failed") from exc
    _verify_private_directory(path, "generation_root")
    return path


def _generation_root(state_root: Path, generation: int) -> Path:
    if type(generation) is not int or not 1 <= generation <= 9_999_999:
        _fail("bridge_process_generation_invalid")
    return state_root / _LAUNCHER_DIRECTORY / f"generation-{generation:07d}"


def _read_private_file(path: Path, label: str) -> bytes:
    return _secure_read_private_file(path, label, maximum_bytes=_MAX_SECRET_BYTES)


def _sha256_private_file(path: Path, label: str) -> str:
    return _secure_sha256_private_file(path, label, maximum_bytes=16 * 1024 * 1024)


def _secret_text(raw: bytes, label: str) -> str:
    if not 32 <= len(raw) <= _MAX_SECRET_BYTES or b"\0" in raw or b"\r" in raw or b"\n" in raw:
        _fail(f"bridge_process_{label}_invalid")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BridgeProcessError(f"bridge_process_{label}_invalid") from exc


def _read_private_json(path: Path) -> dict[str, object]:
    return _secure_read_private_json(path, maximum_bytes=_MAX_METADATA_BYTES)


def _write_private_json_once(path: Path, payload: object) -> None:
    _secure_write_private_json_once(path, payload, maximum_bytes=_MAX_METADATA_BYTES)


def _write_private_json_replace(path: Path, payload: object) -> None:
    _secure_write_private_json_replace(path, payload, maximum_bytes=_MAX_METADATA_BYTES)


def _unix_ms() -> int:
    value = time.time_ns() // 1_000_000
    if not 0 <= value <= 9_007_199_254_740_991:
        _fail("bridge_process_clock_invalid")
    return value


def _fail(code: str) -> None:
    raise BridgeProcessError(code)


__all__ = (
    "LinuxProcessControl",
    "ProcessControlPort",
    "ProductionBridgeFleet",
    "RunningBridgeProcess",
)
