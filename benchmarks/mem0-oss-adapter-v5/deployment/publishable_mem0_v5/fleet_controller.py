"""Lifecycle controller for one container-isolated bridge account."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import signal
import socket
import stat
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import Final, Literal, Protocol

from infinity_context_runtime_bridge import process_launcher
from infinity_context_runtime_bridge.process_contracts import (
    BridgeLaunchReceipt,
    BridgeProcessError,
)
from infinity_context_runtime_bridge.process_control import (
    LinuxProcessControl,
)
from infinity_context_runtime_bridge.process_files import (
    StateLock,
    verify_private_directory,
    verify_private_file,
)

from .config import PublishableLaneConfig, load_runtime_lane_config
from .fleet_spec import (
    CONTAINER_BRIDGE_STATE_BASE,
    AnchorNamespaceEvidence,
    IsolatedBridgeSpec,
    attest_anchor_namespace,
    build_isolated_bridge_spec,
)

CONTAINER_CONFIG_FILE: Final = Path("/run/publishable-config/config.json")
_RECOVERY_DIRECTORY = ".partial-start-recovery"
_CONTROL_NAME = ".controller-readiness.json"
_LIFECYCLE = ".infinity-context-bridge-launcher"
_ACTIVE = "active.json"
_MAX_CONTROL_BYTES = 256 * 1024


class FleetControllerError(RuntimeError):
    """Stable sanitized isolated-controller error."""


class BridgeRuntime(Protocol):
    @property
    def readiness(self) -> BridgeLaunchReceipt: ...

    def reap(self) -> int | None: ...

    def stop(self, *, reason: str) -> object: ...


class BridgeFactory(Protocol):
    def create_new(self, spec: IsolatedBridgeSpec) -> BridgeRuntime: ...

    def reopen(self, spec: IsolatedBridgeSpec) -> BridgeRuntime: ...


@dataclass(slots=True)
class _ProductionBridgeRuntime:
    running: process_launcher.RunningBridgeProcess
    lock: StateLock
    _closed: bool = field(default=False, init=False)

    @property
    def readiness(self) -> BridgeLaunchReceipt:
        return self.running.readiness

    def reap(self) -> int | None:
        return self.running.reap()

    def stop(self, *, reason: str) -> object:
        if self._closed:
            return None
        try:
            return self.running.stop(reason=reason)
        finally:
            self._closed = True
            self.lock.close()


@dataclass(frozen=True, slots=True)
class _ProductionBridgeFactory:
    def create_new(self, spec: IsolatedBridgeSpec) -> BridgeRuntime:
        return self._open(spec, mode="create")

    def reopen(self, spec: IsolatedBridgeSpec) -> BridgeRuntime:
        return self._open(spec, mode="reopen")

    @staticmethod
    def _open(
        spec: IsolatedBridgeSpec,
        *,
        mode: Literal["create", "reopen"],
    ) -> BridgeRuntime:
        item = spec.process
        _preflight_process(item=item, mode=mode)
        lock = StateLock.acquire(item.state_root, _LIFECYCLE, create=mode == "create")
        control = LinuxProcessControl()
        try:
            running = (
                process_launcher._start_generation(
                    item,
                    lock=lock,
                    generation=1,
                    mode="create",
                    protected_pid=(
                        spec.account_i_fence.pid if spec.account_i_fence is not None else None
                    ),
                    control=control,
                )
                if mode == "create"
                else process_launcher._reopen_or_restart(
                    item,
                    lock=lock,
                    protected_pid=(
                        spec.account_i_fence.pid if spec.account_i_fence is not None else None
                    ),
                    control=control,
                )
            )
            return _ProductionBridgeRuntime(running=running, lock=lock)
        except BaseException:
            lock.close()
            raise


def open_bridge_with_partial_recovery(
    *,
    spec: IsolatedBridgeSpec,
    mode: Literal["create", "reopen"],
    factory: BridgeFactory | None = None,
) -> BridgeRuntime:
    """Open one account, recoverably replacing only its incomplete state root."""

    if type(spec) is not IsolatedBridgeSpec:
        _fail("publishable_fleet_controller_input_invalid")
    if mode not in {"create", "reopen"}:
        _fail("publishable_fleet_controller_mode_invalid")
    selected = factory or _ProductionBridgeFactory()
    disposition = _state_disposition(spec)
    if mode == "create" and disposition == "complete":
        _fail("publishable_fleet_already_initialized")
    if mode == "reopen" and disposition == "empty":
        _fail("publishable_fleet_not_initialized")
    if disposition == "partial":
        _archive_partial_state(spec=spec, reason="preopen-partial")
        mode = "create"
    try:
        return selected.create_new(spec) if mode == "create" else selected.reopen(spec)
    except BaseException as first_error:
        if mode != "create":
            raise
        try:
            _archive_partial_state(spec=spec, reason="create-failed")
        except BaseException as recovery_error:
            raise first_error from recovery_error
        return selected.create_new(spec)


def serve(
    config_file: Path,
    *,
    account_index: int,
    mode: Literal["create", "reopen"],
) -> None:
    """Own one account runtime until normal stop or a controller failure."""

    config = load_runtime_lane_config(config_file)
    namespace = attest_anchor_namespace(config)
    spec = build_isolated_bridge_spec(config, account_index=account_index)
    _remove_stale_control_file()
    runtime: BridgeRuntime | None = None
    stop = threading.Event()
    previous: dict[int, object] = {}

    def request_stop(signum: int, frame: object) -> None:
        del signum, frame
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, request_stop)
    try:
        runtime = open_bridge_with_partial_recovery(spec=spec, mode=mode)
        _write_control_file(
            config=config,
            namespace=namespace,
            spec=spec,
            runtime=runtime,
        )
        while not stop.wait(0.5):
            if runtime.reap() is not None:
                _fail("publishable_fleet_process_exited")
    finally:
        with suppress(OSError):
            _control_file().unlink()
        if runtime is not None:
            runtime.stop(reason="container-stop" if stop.is_set() else "controller-failure")
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def health(config_file: Path, *, account_index: int) -> None:
    """Provider-free health for one controller receipt and one bridge GET."""

    config = load_runtime_lane_config(config_file)
    namespace = attest_anchor_namespace(config)
    spec = build_isolated_bridge_spec(config, account_index=account_index)
    payload = _read_control_file()
    expected = {
        "project_name": config.project_name,
        "account_index": account_index,
        "account_name": spec.process.account_name,
        "bridge_id": spec.process.authority.bridge_id,
        "bridge_port": spec.process.port,
        "anchor_namespace_sha256": namespace.identity_sha256,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        _fail("publishable_fleet_health_control_mismatch")
    pid = payload.get("controller_pid")
    if type(pid) is not int or pid <= 1 or not _pid_exists(pid):
        _fail("publishable_fleet_health_controller_missing")
    readiness = payload.get("bridge_readiness")
    if type(readiness) is not dict:
        _fail("publishable_fleet_health_readiness_invalid")
    encoded = _canonical_json(readiness)
    if payload.get("bridge_readiness_sha256") != hashlib.sha256(encoded).hexdigest():
        _fail("publishable_fleet_health_readiness_mismatch")
    if (
        readiness.get("bridge_authority_sha256") != spec.process.authority.commitment_sha256
        or not isinstance(readiness.get("pending_launch"), dict)
        or readiness["pending_launch"].get("bridge_id") != spec.process.authority.bridge_id
    ):
        _fail("publishable_fleet_health_readiness_crosswire")
    _probe_bridge_health(spec.process.port)


def _preflight_process(*, item: object, mode: Literal["create", "reopen"]) -> None:
    if mode not in {"create", "reopen"}:
        _fail("publishable_fleet_controller_mode_invalid")
    try:
        process_launcher._verify_public_material(item)  # type: ignore[arg-type]
        verify_private_directory(item.state_root, "state_root")  # type: ignore[attr-defined]
        verify_private_directory(item.auth_root, "auth_root")  # type: ignore[attr-defined]
        account_root = item.auth_root / item.account_name  # type: ignore[attr-defined]
        verify_private_directory(account_root, "account_auth_root")
        verify_private_file(account_root / "auth.json", "account_auth")
        process_launcher._load_private_material(item)  # type: ignore[arg-type]
        entries = tuple(item.state_root.iterdir())  # type: ignore[attr-defined]
    except BridgeProcessError:
        raise
    except (AttributeError, OSError) as exc:
        raise FleetControllerError("publishable_fleet_process_preflight_failed") from exc
    if mode == "create" and entries:
        _fail("publishable_fleet_new_state_not_empty")
    if mode == "reopen":
        verify_private_directory(
            item.state_root / _LIFECYCLE,  # type: ignore[attr-defined]
            "lifecycle_root",
        )


def _state_disposition(
    spec: IsolatedBridgeSpec,
) -> Literal["empty", "partial", "complete"]:
    root = spec.process.state_root
    _require_private_directory(root, "state_root")
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_state_inspection_failed") from exc
    if not entries:
        return "empty"
    if (root / _LIFECYCLE / _ACTIVE).is_file():
        return "complete"
    return "partial"


def _archive_partial_state(*, spec: IsolatedBridgeSpec, reason: str) -> None:
    """Rename only this account's current root after proving it is not live."""

    if reason not in {"preopen-partial", "create-failed"}:
        _fail("publishable_fleet_recovery_reason_invalid")
    if _tcp_open(spec.process.port):
        _fail("publishable_fleet_partial_port_live")
    root = spec.process.state_root
    _require_private_directory(root, "state_root")
    active = root / _LIFECYCLE / _ACTIVE
    if active.is_file():
        pid = _untrusted_pending_pid(active)
        if pid is not None and _pid_exists(pid):
            _fail("publishable_fleet_partial_pid_live")
    base = root.parent
    _require_private_directory(base, "state_base")
    recovery_root = base / _RECOVERY_DIRECTORY
    _mkdir_private(recovery_root)
    recovery = recovery_root / f"{time.time_ns()}-{token_hex(8)}"
    try:
        os.rename(root, recovery)
        root.mkdir(mode=0o700)
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_partial_archive_failed") from exc
    _fsync_directory(base)
    _fsync_directory(recovery_root)


def _write_control_file(
    *,
    config: PublishableLaneConfig,
    namespace: AnchorNamespaceEvidence,
    spec: IsolatedBridgeSpec,
    runtime: BridgeRuntime,
) -> None:
    readiness = runtime.readiness.public_payload()
    payload = {
        "schema_version": "publishable-mem0-v5-bridge-controller-readiness.v2",
        "project_name": config.project_name,
        "controller_pid": os.getpid(),
        "account_index": spec.account_index,
        "account_name": spec.process.account_name,
        "bridge_id": spec.process.authority.bridge_id,
        "bridge_port": spec.process.port,
        "anchor_namespace_sha256": namespace.identity_sha256,
        "bridge_readiness": readiness,
        "bridge_readiness_sha256": hashlib.sha256(_canonical_json(readiness)).hexdigest(),
    }
    raw = _canonical_json(payload)
    if len(raw) > _MAX_CONTROL_BYTES:
        _fail("publishable_fleet_control_size_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    try:
        descriptor = os.open(_control_file(), flags, 0o600)
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_control_create_failed") from exc
    finally:
        os.umask(previous_umask)
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(CONTAINER_BRIDGE_STATE_BASE)


def _read_control_file() -> dict[str, object]:
    path = _control_file()
    try:
        metadata = path.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > _MAX_CONTROL_BYTES
        ):
            _fail("publishable_fleet_control_unsafe")
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise FleetControllerError("publishable_fleet_control_unavailable") from exc
    if type(value) is not dict or value.get("schema_version") != (
        "publishable-mem0-v5-bridge-controller-readiness.v2"
    ):
        _fail("publishable_fleet_control_invalid")
    return value


def _remove_stale_control_file() -> None:
    path = _control_file()
    if not path.exists():
        return
    value = _read_control_file()
    pid = value.get("controller_pid")
    if type(pid) is int and pid > 1 and _pid_exists(pid):
        _fail("publishable_fleet_controller_already_live")
    try:
        path.unlink()
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_control_remove_failed") from exc


def _control_file() -> Path:
    return CONTAINER_BRIDGE_STATE_BASE / _CONTROL_NAME


def _probe_bridge_health(port: int) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
    try:
        connection.request("GET", "/health", headers={"Connection": "close"})
        response = connection.getresponse()
        raw = response.read(4097)
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_health_unavailable") from exc
    finally:
        connection.close()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        _fail("publishable_fleet_health_invalid")
    if (
        response.status != 200
        or len(raw) > 4096
        or type(value) is not dict
        or value.get("ok") is not True
        or value.get("service") != "subscription-runtime-openai-compatible-codex"
        or value.get("model") != "gpt-5.6-sol"
        or value.get("accountCount") != 1
    ):
        _fail("publishable_fleet_health_invalid")


def _untrusted_pending_pid(path: Path) -> int | None:
    try:
        raw = path.read_bytes()
        if len(raw) > 128 * 1024:
            return None
        value = json.loads(raw)
        pid = value.get("process", {}).get("pid")
        return pid if type(pid) is int and pid > 1 else None
    except (AttributeError, OSError, json.JSONDecodeError):
        return None


def _pid_exists(pid: int) -> bool:
    return Path(f"/proc/{pid}").is_dir()


def _tcp_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _require_private_directory(path: Path, label: str) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise FleetControllerError(f"publishable_fleet_{label}_unavailable") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail(f"publishable_fleet_{label}_unsafe")


def _mkdir_private(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        _require_private_directory(path, "recovery_root")
    except OSError as exc:
        raise FleetControllerError("publishable_fleet_recovery_root_failed") from exc


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            _fail("publishable_fleet_control_short_write")
        written += count


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publishable-mem0-v5-fleet-controller")
    subcommands = parser.add_subparsers(dest="command", required=True)
    serve_parser = subcommands.add_parser("serve")
    serve_parser.add_argument("--mode", choices=("create", "reopen"), required=True)
    serve_parser.add_argument("--account-index", type=int, choices=range(3), required=True)
    serve_parser.add_argument("--config", type=Path, default=CONTAINER_CONFIG_FILE)
    health_parser = subcommands.add_parser("health")
    health_parser.add_argument("--account-index", type=int, choices=range(3), required=True)
    health_parser.add_argument("--config", type=Path, default=CONTAINER_CONFIG_FILE)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "serve":
            serve(
                arguments.config,
                account_index=arguments.account_index,
                mode=arguments.mode,
            )
        else:
            health(arguments.config, account_index=arguments.account_index)
        return 0
    except (FleetControllerError, ValueError, RuntimeError) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2


def _fail(code: str) -> None:
    raise FleetControllerError(code)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = (
    "FleetControllerError",
    "health",
    "main",
    "open_bridge_with_partial_recovery",
    "serve",
)
