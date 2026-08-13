"""Host-side immutable inputs, account-i fencing, and secret cross-wire checks."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .config import (
    BASE_INSTRUCTIONS_SHA256,
    CONTAINER_GID,
    CONTAINER_UID,
    DEPLOYMENT_AUTHORITY_KEY_NAME,
    PROTECTED_ACCOUNT_I_AUTH_ROOT,
    PROTECTED_R16_ROOT,
    AccountIR16Fence,
    PublishableLaneConfig,
    load_lane_config,
    load_provider_free_project_lane_config,
)

_ADAPTER_RUNTIME_ORIGIN: Final = "http://127.0.0.1:8891"
_RUNTIME_ATTESTATION_SECRET_NAME: Final = "runtime-attestation-secret"
_MAX_PRIVATE_FILE_BYTES = 8192
_MAX_PUBLIC_FILE_BYTES = 32 * 1024 * 1024
_MAX_CLOSURE_BYTES = 256 * 1024 * 1024
_MAX_CLOSURE_FILES = 4096
_FILE_CLOSURE_SCHEMA = "publishable-mem0-v5-file-closure.v1"
_DEPLOYMENT_INPUT_SCHEMA = "publishable-mem0-v5-deployment-inputs.v1"


class DeploymentPreflightError(RuntimeError):
    """Stable failure before any Docker mutation is admitted."""


@dataclass(frozen=True, slots=True)
class AccountIFenceEvidence:
    """Exact live identity of protected account-i/r16 at one observation."""

    pid: int
    start_ticks: int
    boot_id: str
    netns_device: int
    netns_inode: int

    @property
    def commitment_sha256(self) -> str:
        raw = (
            f"{self.pid}:{self.start_ticks}:{self.boot_id}:{self.netns_device}:{self.netns_inode}"
        ).encode("ascii")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class PathIdentityEvidence:
    """Resolved inode and complete no-symlink parent-chain commitment."""

    path: str
    resolved_path: str
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    parent_chain_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
            "mtime_ns": self.mtime_ns,
            "parent_chain_sha256": self.parent_chain_sha256,
            "path": self.path,
            "resolved_path": self.resolved_path,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class FileClosureEvidence:
    """Every regular file name, size, and content digest under one bind root."""

    label: str
    root: PathIdentityEvidence
    file_count: int
    total_bytes: int
    closure_sha256: str
    closure_hmac_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "closure_hmac_sha256": self.closure_hmac_sha256,
            "closure_sha256": self.closure_sha256,
            "file_count": self.file_count,
            "label": self.label,
            "root": self.root.payload(),
            "total_bytes": self.total_bytes,
        }


@dataclass(frozen=True, slots=True)
class DeploymentInputEvidence:
    """Pre-start identity of every behavior-critical mutable host input."""

    config_file: PathIdentityEvidence
    config_sha256: str
    config_hmac_sha256: str
    deployment_closure: FileClosureEvidence
    server_closure: FileClosureEvidence
    runtime_root: PathIdentityEvidence
    node_executable: PathIdentityEvidence
    codex_executable: PathIdentityEvidence
    host_relay_port: int

    def payload(self) -> dict[str, object]:
        return {
            "codex_executable": self.codex_executable.payload(),
            "config_file": self.config_file.payload(),
            "config_hmac_sha256": self.config_hmac_sha256,
            "config_sha256": self.config_sha256,
            "deployment_closure": self.deployment_closure.payload(),
            "host_relay_port": self.host_relay_port,
            "node_executable": self.node_executable.payload(),
            "runtime_root": self.runtime_root.payload(),
            "schema_version": _DEPLOYMENT_INPUT_SCHEMA,
            "server_closure": self.server_closure.payload(),
        }

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.payload())).hexdigest()


def configuration_hmac_sha256(config: PublishableLaneConfig, key: bytes) -> str:
    """Sign strict parsed config semantics without the self-referential HMAC."""

    if type(config) is not PublishableLaneConfig or not 32 <= len(key) <= 8192:
        _fail("publishable_preflight_config_authentication_input_invalid")
    return hmac.new(
        key,
        _canonical_json(config.authentication_payload()),
        hashlib.sha256,
    ).hexdigest()


def measure_file_closure(
    root: Path,
    *,
    label: str,
    key: bytes,
) -> FileClosureEvidence:
    """Measure an exhaustive, race-checked, no-symlink regular-file closure."""

    if label not in {"deployment", "server"} or not 32 <= len(key) <= 8192:
        _fail("publishable_preflight_file_closure_input_invalid")
    root_evidence = _attest_public_path(root, label=label, kind="directory")
    rows: list[dict[str, object]] = []
    total_bytes = 0
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            directories.sort()
            files.sort()
            current_path = Path(current)
            current_metadata = current_path.lstat()
            if (
                stat.S_ISLNK(current_metadata.st_mode)
                or not stat.S_ISDIR(current_metadata.st_mode)
                or current_metadata.st_mode & 0o022
            ):
                _fail(f"publishable_preflight_{label}_closure_directory_unsafe")
            for directory in directories:
                child = current_path / directory
                metadata = child.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                    _fail(f"publishable_preflight_{label}_closure_entry_unsafe")
            for name in files:
                path = current_path / name
                relative = path.relative_to(root).as_posix()
                raw = _read_public_file(
                    path,
                    label=f"{label}_closure_file",
                    maximum_bytes=_MAX_PUBLIC_FILE_BYTES,
                    executable=False,
                )
                total_bytes += len(raw)
                if total_bytes > _MAX_CLOSURE_BYTES or len(rows) >= _MAX_CLOSURE_FILES:
                    _fail(f"publishable_preflight_{label}_closure_too_large")
                rows.append(
                    {
                        "path": relative,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "size": len(raw),
                    }
                )
    except OSError as exc:
        raise DeploymentPreflightError(
            f"publishable_preflight_{label}_closure_unavailable"
        ) from exc
    if not rows:
        _fail(f"publishable_preflight_{label}_closure_empty")
    material = _canonical_json(
        {
            "files": rows,
            "label": label,
            "resolved_root": root_evidence.resolved_path,
            "schema_version": _FILE_CLOSURE_SCHEMA,
        }
    )
    return FileClosureEvidence(
        label=label,
        root=root_evidence,
        file_count=len(rows),
        total_bytes=total_bytes,
        closure_sha256=hashlib.sha256(material).hexdigest(),
        closure_hmac_sha256=hmac.new(key, material, hashlib.sha256).hexdigest(),
    )


def attest_deployment_inputs(
    config: PublishableLaneConfig,
    *,
    config_file: Path,
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
) -> DeploymentInputEvidence:
    """Authenticate bind closures and fence resolved public inputs from r16."""

    if type(config) is not PublishableLaneConfig or not config_file.is_absolute():
        _fail("publishable_preflight_deployment_input_invalid")
    authority_key = _read_private_file(
        config.paths.adapter_secret_dir / DEPLOYMENT_AUTHORITY_KEY_NAME,
        "deployment_authority_key",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if not 32 <= len(authority_key) <= _MAX_PRIVATE_FILE_BYTES:
        _fail("publishable_preflight_deployment_authority_key_invalid")
    config_identity = _attest_public_path(
        config_file,
        label="config_file",
        kind="file",
    )
    config_raw = _read_public_file(
        config_file,
        label="config_file",
        maximum_bytes=256 * 1024,
        executable=False,
    )
    reload_config = (
        load_provider_free_project_lane_config(config_file)
        if config.project_isolation_authority is not None
        else load_lane_config(config_file)
    )
    if reload_config != config:
        _fail("publishable_preflight_config_changed_after_load")
    config_hmac = configuration_hmac_sha256(config, authority_key)
    if not hmac.compare_digest(
        config_hmac,
        config.bind_mount_authority.config_hmac_sha256,
    ):
        _fail("publishable_preflight_config_hmac_mismatch")
    deployment = measure_file_closure(
        config.paths.deployment_dir,
        label="deployment",
        key=authority_key,
    )
    server = measure_file_closure(
        config.paths.server_package_dir,
        label="server",
        key=authority_key,
    )
    expected = config.bind_mount_authority
    for actual, digest, authentication, label in (
        (
            deployment,
            expected.deployment_closure_sha256,
            expected.deployment_closure_hmac_sha256,
            "deployment",
        ),
        (
            server,
            expected.server_closure_sha256,
            expected.server_closure_hmac_sha256,
            "server",
        ),
    ):
        if not hmac.compare_digest(actual.closure_sha256, digest):
            _fail(f"publishable_preflight_{label}_closure_digest_mismatch")
        if not hmac.compare_digest(actual.closure_hmac_sha256, authentication):
            _fail(f"publishable_preflight_{label}_closure_hmac_mismatch")
    runtime = _attest_public_path(
        config.runtime.runtime_root,
        label="runtime_root",
        kind="directory",
    )
    node = _attest_public_path(
        config.runtime.node_executable,
        label="node_executable",
        kind="executable",
    )
    codex = _attest_public_path(
        config.runtime.codex_executable,
        label="codex_executable",
        kind="executable",
    )
    resolved = {
        item.resolved_path
        for item in (config_identity, deployment.root, server.root, runtime, node, codex)
    }
    if len(resolved) != 6:
        _fail("publishable_preflight_critical_paths_overlap")
    fence = config.account_i_r16_fence
    if fence is not None and config.host_adapter_port in {
        fence.port, *fence.protected_host_ports,
    }:
        _fail("publishable_preflight_host_relay_port_fence_collision")
    return DeploymentInputEvidence(
        config_file=config_identity,
        config_sha256=hashlib.sha256(config_raw).hexdigest(),
        config_hmac_sha256=config_hmac,
        deployment_closure=deployment,
        server_closure=server,
        runtime_root=runtime,
        node_executable=node,
        codex_executable=codex,
        host_relay_port=config.host_adapter_port,
    )


def attest_account_i_fence(
    fence: AccountIR16Fence,
    *,
    proc_root: Path = Path("/proc"),
) -> AccountIFenceEvidence:
    """Re-attest account-i without traversing either protected private root."""

    if type(fence) is not AccountIR16Fence or not proc_root.is_absolute():
        _fail("publishable_preflight_account_i_input_invalid")
    process_root = proc_root / str(fence.pid)
    try:
        boot_id = (proc_root / "sys/kernel/random/boot_id").read_text().strip()
        first_ticks = _process_start_ticks(process_root / "stat")
        netns = (process_root / "ns/net").stat()
        second_ticks = _process_start_ticks(process_root / "stat")
    except OSError as exc:
        raise DeploymentPreflightError("publishable_preflight_account_i_unavailable") from exc
    if (
        boot_id != fence.boot_id
        or first_ticks != fence.start_ticks
        or second_ticks != first_ticks
        or netns.st_ino != fence.netns_inode
    ):
        _fail("publishable_preflight_account_i_identity_changed")
    return AccountIFenceEvidence(
        pid=fence.pid,
        start_ticks=first_ticks,
        boot_id=boot_id,
        netns_device=netns.st_dev,
        netns_inode=netns.st_ino,
    )


def configured_account_i_fence_authority_sha256(fence: AccountIR16Fence) -> str:
    """Commit the authenticated config authority without observing host process state."""

    if type(fence) is not AccountIR16Fence:
        _fail("publishable_preflight_account_i_fence_authority_input_invalid")
    payload = {
        "auth_root": str(fence.auth_root),
        "boot_id": fence.boot_id,
        "container_ids": list(fence.container_ids),
        "netns_inode": fence.netns_inode,
        "pid": fence.pid,
        "port": fence.port,
        "protected_host_ports": list(fence.protected_host_ports),
        "start_ticks": fence.start_ticks,
        "state_root": str(fence.state_root),
        "status": "CONFIGURED_AUTHORITY_NOT_RUNTIME_REOBSERVED",
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def attest_secret_cross_wire(
    config: PublishableLaneConfig,
    *,
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
) -> str:
    """Bind adapter credentials to bridge one and prove fleet-wide secret separation."""

    if type(config) is not PublishableLaneConfig:
        _fail("publishable_preflight_config_invalid")
    adapter = config.paths.adapter_secret_dir
    bridge_auth_roots = tuple(
        config.paths.fleet_auth_dir / account.account_name for account in config.bridges
    )
    primary = bridge_auth_roots[0]
    for path, label in (
        (adapter, "adapter_secret_root"),
        *((path, "bridge_auth_root") for path in bridge_auth_roots),
    ):
        _require_private_directory(
            path,
            label,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )

    isolated_secrets = tuple(
        _read_private_file(
            auth_root / name,
            "bridge_isolated_secret",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        for auth_root in bridge_auth_roots
        for name in (
            "ingress-api-key.secret",
            "attestation-hmac.secret",
            "launcher-receipt.key",
        )
    )
    if len(set(isolated_secrets)) != len(isolated_secrets):
        _fail("publishable_preflight_bridge_secret_reuse")

    pairs = (
        (adapter / "runtime-bearer", primary / "ingress-api-key.secret"),
        (adapter / "runtime-receipt-secret", primary / "attestation-hmac.secret"),
        (
            adapter / "account-binding-hmac-sha256",
            primary / "account-binding-hmac-sha256",
        ),
        (adapter / "base-instructions-sha256", primary / "base-instructions-sha256"),
        (adapter / "runtime-transport-origin", primary / "runtime-transport-origin"),
    )
    pair_commitments: list[str] = []
    for adapter_path, primary_path in pairs:
        adapter_raw = _read_private_file(
            adapter_path,
            "adapter_cross_wire",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        primary_raw = _read_private_file(
            primary_path,
            "primary_cross_wire",
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        if not hmac.compare_digest(adapter_raw, primary_raw):
            _fail("publishable_preflight_secret_cross_wire")
        pair_commitments.append(hashlib.sha256(adapter_raw).hexdigest())

    binding = _private_text(
        adapter / "account-binding-hmac-sha256",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    base = _private_text(
        adapter / "base-instructions-sha256",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    origin = _private_text(
        adapter / "runtime-transport-origin",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if not hmac.compare_digest(binding, config.bridges[0].account_binding_hmac_sha256):
        _fail("publishable_preflight_account_binding_cross_wire")
    if not hmac.compare_digest(base, BASE_INSTRUCTIONS_SHA256):
        _fail("publishable_preflight_base_instructions_cross_wire")
    if origin != _ADAPTER_RUNTIME_ORIGIN:
        _fail("publishable_preflight_runtime_origin_cross_wire")

    return hashlib.sha256("".join(pair_commitments).encode("ascii")).hexdigest()


def load_runtime_attestation_key(
    config: PublishableLaneConfig,
    *,
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
) -> bytes:
    """Read the adapter's endpoint and host-receipt authentication root."""

    if type(config) is not PublishableLaneConfig:
        _fail("publishable_preflight_config_invalid")
    root = config.paths.adapter_secret_dir
    _require_private_directory(
        root,
        "adapter_secret_root",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    key = _read_private_file(
        root / _RUNTIME_ATTESTATION_SECRET_NAME,
        "runtime_attestation_key",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        text = key.decode("utf-8")
    except UnicodeDecodeError:
        _fail("publishable_preflight_runtime_attestation_key_invalid")
    if not 32 <= len(key) <= 4096 or not text or text != text.strip():
        _fail("publishable_preflight_runtime_attestation_key_invalid")
    return key


def _attest_public_path(
    path: Path,
    *,
    label: str,
    kind: str,
) -> PathIdentityEvidence:
    if (
        kind not in {"directory", "file", "executable"}
        or not path.is_absolute()
        or Path(os.path.normpath(path)) != path
    ):
        _fail(f"publishable_preflight_{label}_path_invalid")
    first = _path_chain(path, label=label)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentPreflightError(f"publishable_preflight_{label}_unavailable") from exc
    second = _path_chain(path, label=label)
    if first != second or resolved != path:
        _fail(f"publishable_preflight_{label}_symlink_or_change")
    leaf = second[-1][1]
    if kind == "directory":
        valid_kind = stat.S_ISDIR(leaf.st_mode)
    else:
        valid_kind = stat.S_ISREG(leaf.st_mode) and leaf.st_nlink == 1
    if (
        not valid_kind
        or leaf.st_mode & 0o022
        or (kind == "executable" and not leaf.st_mode & 0o111)
    ):
        _fail(f"publishable_preflight_{label}_unsafe")
    protected = tuple(
        item.resolve(strict=False) for item in (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    )
    if any(
        _paths_overlap(candidate, item)
        for candidate in (path, resolved)
        for item in (*protected, PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    ):
        _fail(f"publishable_preflight_{label}_protected_collision")
    chain_payload = [
        {
            "device": metadata.st_dev,
            "inode": metadata.st_ino,
            "mode": stat.S_IMODE(metadata.st_mode),
            "path": str(item),
        }
        for item, metadata in second
    ]
    return PathIdentityEvidence(
        path=str(path),
        resolved_path=str(resolved),
        device=leaf.st_dev,
        inode=leaf.st_ino,
        mode=stat.S_IMODE(leaf.st_mode),
        size=leaf.st_size,
        mtime_ns=leaf.st_mtime_ns,
        parent_chain_sha256=hashlib.sha256(_canonical_json(chain_payload)).hexdigest(),
    )


def _path_chain(path: Path, *, label: str) -> tuple[tuple[Path, os.stat_result], ...]:
    reverse: list[Path] = []
    current = path
    while True:
        reverse.append(current)
        if current.parent == current:
            break
        current = current.parent
    result: list[tuple[Path, os.stat_result]] = []
    try:
        for index, item in enumerate(reversed(reverse)):
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode) or (
                index < len(reverse) - 1 and not stat.S_ISDIR(metadata.st_mode)
            ):
                _fail(f"publishable_preflight_{label}_symlink_or_change")
            result.append((item, metadata))
    except OSError as exc:
        raise DeploymentPreflightError(f"publishable_preflight_{label}_unavailable") from exc
    return tuple(result)


def _read_public_file(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
    executable: bool,
) -> bytes:
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
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_mode & 0o022
            or (executable and not opened.st_mode & 0o111)
            or opened.st_size < 0
            or opened.st_size > maximum_bytes
        ):
            _fail(f"publishable_preflight_{label}_unsafe")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        final = os.fstat(descriptor)
        if (
            len(raw) != opened.st_size
            or len(raw) > maximum_bytes
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            != (
                final.st_dev,
                final.st_ino,
                final.st_size,
                final.st_mtime_ns,
            )
        ):
            _fail(f"publishable_preflight_{label}_changed")
        return raw
    except OSError as exc:
        raise DeploymentPreflightError(f"publishable_preflight_{label}_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _process_start_ticks(path: Path) -> int:
    raw = path.read_text()
    closing = raw.rfind(")")
    if closing <= 0:
        _fail("publishable_preflight_account_i_stat_invalid")
    fields = raw[closing + 2 :].split()
    try:
        value = int(fields[19])
    except (IndexError, ValueError):
        _fail("publishable_preflight_account_i_stat_invalid")
    if value <= 0:
        _fail("publishable_preflight_account_i_stat_invalid")
    return value


def _private_text(path: Path, *, expected_uid: int, expected_gid: int) -> str:
    raw = _read_private_file(
        path,
        "cross_wire_text",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        _fail("publishable_preflight_cross_wire_text_invalid")
    if not value or value != value.strip():
        _fail("publishable_preflight_cross_wire_text_invalid")
    return value


def _read_private_file(
    path: Path,
    label: str,
    *,
    expected_uid: int,
    expected_gid: int,
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_nlink != 1
            or (opened.st_uid, opened.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_size <= 0
            or opened.st_size > _MAX_PRIVATE_FILE_BYTES
        ):
            _fail(f"publishable_preflight_{label}_unsafe")
        raw = os.read(descriptor, _MAX_PRIVATE_FILE_BYTES + 1)
        final = os.fstat(descriptor)
        if (
            not raw
            or len(raw) > _MAX_PRIVATE_FILE_BYTES
            or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            )
            != (
                final.st_dev,
                final.st_ino,
                final.st_size,
                final.st_mtime_ns,
            )
        ):
            _fail(f"publishable_preflight_{label}_changed")
        return raw
    except OSError as exc:
        raise DeploymentPreflightError(f"publishable_preflight_{label}_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_private_directory(
    path: Path,
    label: str,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise DeploymentPreflightError(f"publishable_preflight_{label}_unavailable") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail(f"publishable_preflight_{label}_unsafe")


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fail(code: str) -> None:
    raise DeploymentPreflightError(code)


__all__ = (
    "AccountIFenceEvidence",
    "DeploymentInputEvidence",
    "DeploymentPreflightError",
    "FileClosureEvidence",
    "PathIdentityEvidence",
    "attest_account_i_fence",
    "attest_deployment_inputs",
    "attest_secret_cross_wire",
    "configuration_hmac_sha256",
    "configured_account_i_fence_authority_sha256",
    "load_runtime_attestation_key",
    "measure_file_closure",
)
