"""Kernel inventory, socket, and authenticated fleet runtime evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from infinity_context_server.features.subscription_runtime_bridge.contracts import (
    BridgeAuthority,
    BridgePoolAuthority,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    PROVIDER_RECEIPT_SCHEMA,
    RUNTIME_PROCESS_AUTHORITY_SCHEMA,
    BridgeFleetReadinessReceipt,
    BridgeLaunchReceipt,
    BridgeProcessError,
    RuntimeProcessAuthority,
)

from .config import BASE_INSTRUCTIONS_SHA256, BRIDGE_PORTS, PublishableLaneConfig
from .docker_cli import SERVICES

_MAX_FLEET_METADATA_BYTES = 256 * 1024
_LIFECYCLE_ROOT = ".infinity-context-bridge-launcher"
_ACTIVE_FILE = "active.json"
_READINESS_FILE = "readiness.json"
_RUNTIME_AUTHORITY_FILE = "runtime-authority.json"
_CONTROL_FILE = ".controller-readiness.json"
_CONTROL_SCHEMA = "publishable-mem0-v5-fleet-controller-readiness.v1"
_EXPECTED_LOOPBACK_PORTS = (6334, 6335, 8891, 8892, 8893, 19091, 19191)
_IPV4_LOOPBACK_HEX = "0100007F"


class RuntimeIntegrityError(RuntimeError):
    """Stable fail-closed error for independently observed runtime evidence."""


class NamespaceEvidence(Protocol):
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class BridgeRuntimeIdentity:
    account_name: str
    bridge_id: str
    generation: int
    launch_mode: str
    process: Mapping[str, object]
    runtime_authority_sha256: str
    readiness_receipt_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "account_name": self.account_name,
            "bridge_id": self.bridge_id,
            "generation": self.generation,
            "launch_mode": self.launch_mode,
            "process": dict(self.process),
            "readiness_receipt_sha256": self.readiness_receipt_sha256,
            "runtime_authority_sha256": self.runtime_authority_sha256,
        }


@dataclass(frozen=True, slots=True)
class FleetRuntimeEvidence:
    requested_mode: str
    controller_pid: int
    pool_authority_sha256: str
    fleet_readiness_sha256: str
    bridges: tuple[
        BridgeRuntimeIdentity,
        BridgeRuntimeIdentity,
        BridgeRuntimeIdentity,
    ]

    def payload(self) -> dict[str, object]:
        return {
            "bridges": [item.payload() for item in self.bridges],
            "controller_pid": self.controller_pid,
            "fleet_readiness_sha256": self.fleet_readiness_sha256,
            "pool_authority_sha256": self.pool_authority_sha256,
            "requested_mode": self.requested_mode,
        }


def attest_anchor_container_inventory(
    running: Mapping[str, Mapping[str, Any]],
    *,
    expected_container_ids: Mapping[str, str],
    anchor_netns: NamespaceEvidence,
    anchor_pidns: NamespaceEvidence,
    proc_root: Path,
) -> str:
    """Bind every daemon container sharing either anchor namespace."""

    if set(expected_container_ids) != set(SERVICES) or not proc_root.is_absolute():
        _fail("publishable_attestation_container_inventory_input_invalid")
    expected_ids = set(expected_container_ids.values())
    if len(expected_ids) != len(SERVICES) or not expected_ids.issubset(running):
        _fail("publishable_attestation_container_inventory_incomplete")
    service_by_id = {identifier: service for service, identifier in expected_container_ids.items()}
    anchored: list[dict[str, object]] = []
    for identifier, value in sorted(running.items()):
        if value.get("Id") != identifier:
            _fail("publishable_attestation_container_inventory_invalid")
        state = _mapping(value, "State")
        pid = state.get("Pid")
        if state.get("Running") is not True or type(pid) is not int or pid <= 1:
            _fail("publishable_attestation_container_inventory_raced")
        netns = _namespace_tuple(proc_root / str(pid) / "ns/net")
        pidns = _namespace_tuple(proc_root / str(pid) / "ns/pid")
        shares_anchor = netns == (anchor_netns.device, anchor_netns.inode) or pidns == (
            anchor_pidns.device,
            anchor_pidns.inode,
        )
        if not shares_anchor:
            continue
        if identifier not in expected_ids:
            _fail("publishable_attestation_unexpected_anchor_container")
        anchored.append(
            {
                "container_id": identifier,
                "netns": {"device": netns[0], "inode": netns[1]},
                "pid": pid,
                "pidns": {"device": pidns[0], "inode": pidns[1]},
                "service": service_by_id[identifier],
            }
        )
    if {item["container_id"] for item in anchored} != expected_ids:
        _fail("publishable_attestation_container_inventory_incomplete")
    return hashlib.sha256(_canonical_json(anchored)).hexdigest()


def attest_loopback_bindings(
    *,
    proc_root: Path,
    anchor_pid: int,
    host_relay_port: int,
) -> str:
    """Require kernel-observed internal listeners to be IPv4 loopback only."""

    if not proc_root.is_absolute() or anchor_pid <= 1 or not 1024 <= host_relay_port <= 65535:
        _fail("publishable_attestation_loopback_input_invalid")
    network_root = proc_root / str(anchor_pid) / "net"
    listeners = [
        *_read_listener_table(network_root / "tcp", family="ipv4"),
        *_read_listener_table(network_root / "tcp6", family="ipv6"),
    ]
    rows: list[dict[str, object]] = []
    for port in _EXPECTED_LOOPBACK_PORTS:
        observed = [item for item in listeners if item["port"] == port]
        expected = {
            "address": _IPV4_LOOPBACK_HEX,
            "family": "ipv4",
            "port": port,
        }
        if observed != [expected]:
            _fail("publishable_attestation_loopback_bindings_invalid")
        rows.append(expected)
    host_rows: list[dict[str, object]] = []
    host_net = proc_root / "net"
    if (host_net / "tcp").exists() and (host_net / "tcp6").exists():
        host_listeners = [
            *_read_listener_table(host_net / "tcp", family="ipv4"),
            *_read_listener_table(host_net / "tcp6", family="ipv6"),
        ]
        host_rows = [item for item in host_listeners if item["port"] == host_relay_port]
        if any(
            item["family"] != "ipv4" or item["address"] != _IPV4_LOOPBACK_HEX for item in host_rows
        ):
            _fail("publishable_attestation_host_relay_binding_invalid")
    return hashlib.sha256(
        _canonical_json(
            {
                "host_relay_listeners": host_rows,
                "host_relay_port": host_relay_port,
                "internal_listeners": rows,
            }
        )
    ).hexdigest()


def attest_fleet_readiness(
    config: PublishableLaneConfig,
    *,
    fleet_mode: str,
    anchor_netns: NamespaceEvidence,
    anchor_pidns: NamespaceEvidence,
    expected_uid: int,
    expected_gid: int,
) -> FleetRuntimeEvidence:
    """Verify all launch receipts with distinct launcher keys and bind control state."""

    if type(config) is not PublishableLaneConfig or fleet_mode not in {"create", "reopen"}:
        _fail("publishable_attestation_fleet_input_invalid")
    authorities = tuple(
        BridgeAuthority(
            bridge_id=item.bridge_id,
            origin=f"http://127.0.0.1:{port}",
            account_binding_hmac_sha256=item.account_binding_hmac_sha256,
            public_model="gpt-5.6-sol",
            base_instructions_sha256=BASE_INSTRUCTIONS_SHA256,
        )
        for item, port in zip(config.bridges, BRIDGE_PORTS, strict=True)
    )
    pool = BridgePoolAuthority(
        pool_id=f"{config.project_name}-runtime-pool",
        bridges=authorities,
    )
    receipts: list[BridgeLaunchReceipt] = []
    identities: list[BridgeRuntimeIdentity] = []
    try:
        for account, authority in zip(config.bridges, authorities, strict=True):
            receipt, identity = _attest_bridge_readiness(
                config,
                account_name=account.account_name,
                bridge_id=account.bridge_id,
                authority=authority,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
            )
            receipts.append(receipt)
            identities.append(identity)
    except (BridgeProcessError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeIntegrityError("publishable_attestation_fleet_receipt_invalid") from exc
    if len({item.process["pid"] for item in identities}) != 3:
        _fail("publishable_attestation_fleet_process_identity_duplicate")
    fleet_receipt = BridgeFleetReadinessReceipt(
        pool=pool,
        launches=tuple(receipts),  # type: ignore[arg-type]
    )
    public_readiness = fleet_receipt.public_payload()
    control = _read_private_json(
        config.paths.fleet_state_dir / _CONTROL_FILE,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if set(control) != {
        "anchor_namespace_sha256",
        "bridge_ports",
        "controller_pid",
        "fleet_readiness",
        "fleet_readiness_sha256",
        "project_name",
        "schema_version",
    }:
        _fail("publishable_attestation_fleet_control_invalid")
    namespace_sha256 = hashlib.sha256(
        (
            f"net:{anchor_netns.device}:{anchor_netns.inode};"
            f"pid:{anchor_pidns.device}:{anchor_pidns.inode}"
        ).encode("ascii")
    ).hexdigest()
    readiness_sha256 = hashlib.sha256(_canonical_json(public_readiness)).hexdigest()
    controller_pid = control.get("controller_pid")
    if (
        control.get("schema_version") != _CONTROL_SCHEMA
        or control.get("project_name") != config.project_name
        or control.get("anchor_namespace_sha256") != namespace_sha256
        or control.get("bridge_ports") != list(BRIDGE_PORTS)
        or type(controller_pid) is not int
        or controller_pid <= 1
        or control.get("fleet_readiness") != public_readiness
        or not hmac.compare_digest(str(control.get("fleet_readiness_sha256")), readiness_sha256)
    ):
        _fail("publishable_attestation_fleet_control_mismatch")
    return FleetRuntimeEvidence(
        requested_mode=fleet_mode,
        controller_pid=controller_pid,
        pool_authority_sha256=pool.commitment_sha256,
        fleet_readiness_sha256=readiness_sha256,
        bridges=tuple(identities),  # type: ignore[arg-type]
    )


def _attest_bridge_readiness(
    config: PublishableLaneConfig,
    *,
    account_name: str,
    bridge_id: str,
    authority: BridgeAuthority,
    expected_uid: int,
    expected_gid: int,
) -> tuple[BridgeLaunchReceipt, BridgeRuntimeIdentity]:
    state_root = config.paths.fleet_state_dir / account_name
    auth_root = config.paths.fleet_auth_dir / account_name
    lifecycle = state_root / _LIFECYCLE_ROOT
    for path in (state_root, auth_root, lifecycle):
        _require_private_directory(path, expected_uid, expected_gid)
    key = _read_private_bytes(
        auth_root / "launcher-receipt.key",
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        maximum_bytes=8192,
    )
    if not 32 <= len(key) <= 8192:
        _fail("publishable_attestation_fleet_launcher_key_invalid")
    active_path = lifecycle / _ACTIVE_FILE
    active = _read_private_json(
        active_path,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    generation = active.get("generation")
    if type(generation) is not int or not 1 <= generation <= 9_999_999:
        _fail("publishable_attestation_fleet_generation_invalid")
    generation_root = lifecycle / f"generation-{generation:07d}"
    _require_private_directory(generation_root, expected_uid, expected_gid)
    readiness = BridgeLaunchReceipt.from_payload(
        _read_private_json(
            generation_root / _READINESS_FILE,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    )
    readiness.verify(key)
    if readiness.pending.public_payload() != active:
        _fail("publishable_attestation_fleet_active_mismatch")
    if (
        readiness.pending.account_name != account_name
        or readiness.pending.bridge_id != bridge_id
        or readiness.bridge_authority_sha256 != authority.commitment_sha256
    ):
        _fail("publishable_attestation_fleet_bridge_identity_mismatch")
    runtime_authority = _read_private_json(
        lifecycle / _RUNTIME_AUTHORITY_FILE,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _attest_runtime_authority(
        runtime_authority,
        config=config,
        account_name=account_name,
        authority=authority,
        expected_sha256=readiness.runtime_authority_sha256,
    )
    if (
        _read_private_json(
            active_path,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        != active
    ):
        _fail("publishable_attestation_fleet_active_changed")
    return readiness, BridgeRuntimeIdentity(
        account_name=account_name,
        bridge_id=bridge_id,
        generation=generation,
        launch_mode=readiness.pending.mode,
        process=readiness.pending.process.public_payload(),
        runtime_authority_sha256=readiness.runtime_authority_sha256,
        readiness_receipt_sha256=readiness.commitment_sha256,
    )


def _attest_runtime_authority(
    value: Mapping[str, object],
    *,
    config: PublishableLaneConfig,
    account_name: str,
    authority: BridgeAuthority,
    expected_sha256: str,
) -> None:
    dynamic = {
        "auth_root_identity_sha256",
        "private_material_binding_hmac_sha256",
        "state_root_identity_sha256",
    }
    expected: dict[str, object] = {
        "account_count": 1,
        "account_name": account_name,
        "bridge_authority": authority.public_payload(),
        "bridge_authority_sha256": authority.commitment_sha256,
        "codex_executable_sha256": config.runtime.codex_executable_sha256,
        "codex_model": RuntimeProcessAuthority.CODEX_MODEL,
        "environment_policy": "minimal-fixed-no-ambient-credentials",
        "max_account_cycles": RuntimeProcessAuthority.MAX_ACCOUNT_CYCLES,
        "max_concurrent_requests": RuntimeProcessAuthority.MAX_CONCURRENT_REQUESTS,
        "node_executable_sha256": config.runtime.node_executable_sha256,
        "provider_call_recovery": RuntimeProcessAuthority.PROVIDER_RECOVERY,
        "provider_receipt_schema": PROVIDER_RECEIPT_SCHEMA,
        "readiness_method": "GET",
        "readiness_provider_calls": 0,
        "readiness_route": "/health",
        "reasoning_effort": RuntimeProcessAuthority.REASONING_EFFORT,
        "request_body_max_bytes": RuntimeProcessAuthority.REQUEST_BODY_MAX_BYTES,
        "runtime_artifact_manifest_sha256": (config.runtime.runtime_artifact_manifest_sha256),
        "runtime_entrypoint_sha256": config.runtime.runtime_entrypoint_sha256,
        "schema_version": RUNTIME_PROCESS_AUTHORITY_SCHEMA,
        "service_tier": RuntimeProcessAuthority.SERVICE_TIER,
    }
    if set(value) != set(expected) | dynamic or any(
        value.get(name) != item for name, item in expected.items()
    ):
        _fail("publishable_attestation_runtime_authority_invalid")
    if any(not _sha256(value.get(name)) for name in dynamic):
        _fail("publishable_attestation_runtime_authority_invalid")
    actual_sha256 = hashlib.sha256(_canonical_json(value)).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        _fail("publishable_attestation_runtime_authority_mismatch")


def _read_listener_table(path: Path, *, family: str) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeIntegrityError(
            "publishable_attestation_loopback_bindings_unavailable"
        ) from exc
    if not lines:
        _fail("publishable_attestation_loopback_bindings_invalid")
    result: list[dict[str, object]] = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4 or ":" not in fields[1]:
            _fail("publishable_attestation_loopback_bindings_invalid")
        if fields[3] != "0A":
            continue
        address, encoded_port = fields[1].split(":", 1)
        try:
            port = int(encoded_port, 16)
        except ValueError:
            _fail("publishable_attestation_loopback_bindings_invalid")
        result.append({"address": address.upper(), "family": family, "port": port})
    return result


def _read_private_json(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
) -> dict[str, object]:
    raw = _read_private_bytes(
        path,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        maximum_bytes=_MAX_FLEET_METADATA_BYTES,
    )
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RuntimeIntegrityError) as exc:
        raise RuntimeIntegrityError("publishable_attestation_fleet_json_invalid") from exc
    if type(value) is not dict or _canonical_json(value) != raw:
        _fail("publishable_attestation_fleet_json_invalid")
    return value


def _read_private_bytes(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    maximum_bytes: int,
) -> bytes:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or (opened.st_uid, opened.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or not 0 < opened.st_size <= maximum_bytes
        ):
            _fail("publishable_attestation_fleet_file_unsafe")
        raw = os.read(descriptor, maximum_bytes + 1)
        final = os.fstat(descriptor)
        if len(raw) != opened.st_size or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            _fail("publishable_attestation_fleet_file_changed")
        return raw
    except OSError as exc:
        raise RuntimeIntegrityError("publishable_attestation_fleet_file_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_private_directory(path: Path, expected_uid: int, expected_gid: int) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise RuntimeIntegrityError("publishable_attestation_fleet_directory_unavailable") from exc
    if (
        stat.S_ISLNK(value.st_mode)
        or not stat.S_ISDIR(value.st_mode)
        or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        _fail("publishable_attestation_fleet_directory_unsafe")


def _namespace_tuple(path: Path) -> tuple[int, int]:
    try:
        value = path.stat()
    except OSError as exc:
        raise RuntimeIntegrityError(
            "publishable_attestation_container_namespace_unavailable"
        ) from exc
    return value.st_dev, value.st_ino


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        _fail("publishable_attestation_container_inventory_invalid")
    return item


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("publishable_attestation_fleet_json_duplicate_key")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise RuntimeIntegrityError(code)


__all__ = (
    "BridgeRuntimeIdentity",
    "FleetRuntimeEvidence",
    "RuntimeIntegrityError",
    "attest_anchor_container_inventory",
    "attest_fleet_readiness",
    "attest_loopback_bindings",
)
