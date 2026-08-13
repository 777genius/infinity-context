"""Build one bridge process from one container-private account mount."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from infinity_context_server.features.subscription_runtime_bridge.contracts import (
    BridgeAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    AccountIRuntimeFence,
    BridgePrivateFiles,
    BridgeProcessSpec,
)

from .config import BASE_INSTRUCTIONS_SHA256, BRIDGE_PORTS, PublishableLaneConfig

CONTAINER_RUNTIME_ROOT: Final = Path("/opt/publishable/runtime")
CONTAINER_NODE_EXECUTABLE: Final = Path("/opt/publishable/bin/node")
CONTAINER_CODEX_EXECUTABLE: Final = Path("/opt/publishable/bin/codex")
CONTAINER_BRIDGE_STATE_BASE: Final = Path("/run/publishable-bridge-state")
CONTAINER_BRIDGE_STATE_ROOT: Final = CONTAINER_BRIDGE_STATE_BASE / "current"
CONTAINER_BRIDGE_AUTH_ROOT: Final = Path("/run/publishable-bridge-auth")
PRIMARY_RUNTIME_ORIGIN: Final = "http://127.0.0.1:8891"

_API_KEY = "ingress-api-key.secret"
_ATTESTATION_SECRET = "attestation-hmac.secret"
_LAUNCHER_KEY = "launcher-receipt.key"
_ACCOUNT_BINDING = "account-binding-hmac-sha256"
_BASE_INSTRUCTIONS = "base-instructions-sha256"
_RUNTIME_ORIGIN = "runtime-transport-origin"
_MAX_PRIVATE_FILE_BYTES = 8192


class FleetSpecBuildError(RuntimeError):
    """Stable failure at the isolated bridge composition boundary."""


@dataclass(frozen=True, slots=True)
class AnchorNamespaceEvidence:
    """Kernel namespace identity observed before this account's secret reads."""

    netns_device: int
    netns_inode: int
    pidns_device: int
    pidns_inode: int

    @property
    def identity_sha256(self) -> str:
        value = (
            f"net:{self.netns_device}:{self.netns_inode};pid:{self.pidns_device}:{self.pidns_inode}"
        )
        return hashlib.sha256(value.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class IsolatedBridgeSpec:
    """One account process plus its public fleet and protected-process bindings."""

    account_index: int
    pool_id: str
    process: BridgeProcessSpec
    account_i_fence: AccountIRuntimeFence | None

    def __post_init__(self) -> None:
        if (
            type(self.account_index) is not int
            or self.account_index not in range(len(BRIDGE_PORTS))
            or not self.pool_id
            or type(self.process) is not BridgeProcessSpec
            or (
                self.account_i_fence is not None
                and type(self.account_i_fence) is not AccountIRuntimeFence
            )
        ):
            _fail("publishable_bridge_spec_invalid")
        if self.process.port != BRIDGE_PORTS[self.account_index]:
            _fail("publishable_bridge_spec_port_crosswire")


def attest_anchor_namespace(
    config: PublishableLaneConfig,
    *,
    proc_root: Path = Path("/proc"),
) -> AnchorNamespaceEvidence:
    """Prove this controller shares PID 1's netns and not account-i's netns."""

    if type(config) is not PublishableLaneConfig or not proc_root.is_absolute():
        _fail("publishable_fleet_namespace_input_invalid")
    try:
        own_net = (proc_root / "self/ns/net").stat()
        anchor_net = (proc_root / "1/ns/net").stat()
        own_pid = (proc_root / "self/ns/pid").stat()
        anchor_pid = (proc_root / "1/ns/pid").stat()
    except OSError as exc:
        raise FleetSpecBuildError("publishable_fleet_namespace_unavailable") from exc
    if (own_net.st_dev, own_net.st_ino) != (anchor_net.st_dev, anchor_net.st_ino):
        _fail("publishable_fleet_anchor_netns_mismatch")
    if (own_pid.st_dev, own_pid.st_ino) != (anchor_pid.st_dev, anchor_pid.st_ino):
        _fail("publishable_fleet_anchor_pidns_mismatch")
    if (
        config.account_i_r16_fence is not None
        and own_net.st_ino == config.account_i_r16_fence.netns_inode
    ):
        _fail("publishable_fleet_account_i_netns_collision")
    if proc_root == Path("/proc") and os.getpid() == 1:
        _fail("publishable_fleet_controller_is_anchor")
    return AnchorNamespaceEvidence(
        netns_device=own_net.st_dev,
        netns_inode=own_net.st_ino,
        pidns_device=own_pid.st_dev,
        pidns_inode=own_pid.st_ino,
    )


def build_isolated_bridge_spec(
    config: PublishableLaneConfig,
    *,
    account_index: int,
    proc_root: Path = Path("/proc"),
) -> IsolatedBridgeSpec:
    """Build exactly the account visible in this container's two private mounts."""

    if type(account_index) is not int or account_index not in range(len(BRIDGE_PORTS)):
        _fail("publishable_bridge_account_index_invalid")
    attest_anchor_namespace(config, proc_root=proc_root)
    account = config.bridges[account_index]
    port = BRIDGE_PORTS[account_index]
    _require_private_directory(CONTAINER_BRIDGE_STATE_BASE, "state_base")
    _require_private_directory(CONTAINER_BRIDGE_STATE_ROOT, "state_root")
    _require_private_directory(CONTAINER_BRIDGE_AUTH_ROOT, "auth_root")
    _require_private_directory(
        CONTAINER_BRIDGE_AUTH_ROOT / account.account_name,
        "account_auth_root",
    )
    binding = _read_private_text(
        CONTAINER_BRIDGE_AUTH_ROOT / _ACCOUNT_BINDING,
        "account_binding",
    )
    base_instructions = _read_private_text(
        CONTAINER_BRIDGE_AUTH_ROOT / _BASE_INSTRUCTIONS,
        "base_instructions",
    )
    if not hmac.compare_digest(binding, account.account_binding_hmac_sha256):
        _fail("publishable_fleet_account_binding_crosswire")
    if not hmac.compare_digest(base_instructions, BASE_INSTRUCTIONS_SHA256):
        _fail("publishable_fleet_base_instructions_crosswire")
    private_files = BridgePrivateFiles(
        api_key=CONTAINER_BRIDGE_AUTH_ROOT / _API_KEY,
        attestation_secret=CONTAINER_BRIDGE_AUTH_ROOT / _ATTESTATION_SECRET,
        launcher_receipt_key=CONTAINER_BRIDGE_AUTH_ROOT / _LAUNCHER_KEY,
    )
    for path, label in (
        (private_files.api_key, "api_key"),
        (private_files.attestation_secret, "attestation_secret"),
        (private_files.launcher_receipt_key, "launcher_key"),
    ):
        _read_private_bytes(path, label)
    if account_index == 0:
        origin = _read_private_text(
            CONTAINER_BRIDGE_AUTH_ROOT / _RUNTIME_ORIGIN,
            "runtime_origin",
        )
        if origin != PRIMARY_RUNTIME_ORIGIN:
            _fail("publishable_fleet_primary_runtime_origin_crosswire")
    authority = BridgeAuthority(
        bridge_id=account.bridge_id,
        origin=f"http://127.0.0.1:{port}",
        account_binding_hmac_sha256=account.account_binding_hmac_sha256,
        public_model="gpt-5.6-sol",
        base_instructions_sha256=BASE_INSTRUCTIONS_SHA256,
    )
    fence = config.account_i_r16_fence
    return IsolatedBridgeSpec(
        account_index=account_index,
        pool_id=f"{config.project_name}-runtime-pool",
        process=BridgeProcessSpec(
            account_name=account.account_name,
            port=port,
            authority=authority,
            state_root=CONTAINER_BRIDGE_STATE_ROOT,
            auth_root=CONTAINER_BRIDGE_AUTH_ROOT,
            private_files=private_files,
            runtime_root=CONTAINER_RUNTIME_ROOT,
            runtime_artifact_manifest_sha256=(config.runtime.runtime_artifact_manifest_sha256),
            runtime_entrypoint_sha256=config.runtime.runtime_entrypoint_sha256,
            node_executable=CONTAINER_NODE_EXECUTABLE,
            node_executable_sha256=config.runtime.node_executable_sha256,
            codex_executable=CONTAINER_CODEX_EXECUTABLE,
            codex_executable_sha256=config.runtime.codex_executable_sha256,
        ),
        account_i_fence=(
            AccountIRuntimeFence(
                pid=fence.pid,
                port=fence.port,
                state_root=fence.state_root,
                auth_root=fence.auth_root,
            )
            if fence is not None
            else None
        ),
    )


def _require_private_directory(path: Path, label: str) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise FleetSpecBuildError(f"publishable_fleet_{label}_unavailable") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail(f"publishable_fleet_{label}_unsafe")


def _read_private_text(path: Path, label: str) -> str:
    raw = _read_private_bytes(path, label)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail(f"publishable_fleet_{label}_invalid")
    if not value or value != value.strip():
        _fail(f"publishable_fleet_{label}_invalid")
    return value


def _read_private_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            _fail(f"publishable_fleet_{label}_unsafe")
        raw = os.read(descriptor, _MAX_PRIVATE_FILE_BYTES + 1)
        if not raw or len(raw) > _MAX_PRIVATE_FILE_BYTES:
            _fail(f"publishable_fleet_{label}_size_invalid")
        final = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            _fail(f"publishable_fleet_{label}_changed")
        return raw
    except OSError as exc:
        raise FleetSpecBuildError(f"publishable_fleet_{label}_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fail(code: str) -> None:
    raise FleetSpecBuildError(code)


__all__ = (
    "AnchorNamespaceEvidence",
    "FleetSpecBuildError",
    "IsolatedBridgeSpec",
    "attest_anchor_namespace",
    "build_isolated_bridge_spec",
)
