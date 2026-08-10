"""Secret-free authority and receipt contracts for local bridge processes."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

from .contracts import BridgeAuthority, BridgePoolAuthority
from .json_boundary import canonical_json_bytes, exact_object

RUNTIME_PROCESS_AUTHORITY_SCHEMA = "subscription-runtime-process-authority.v1"
PENDING_LAUNCH_SCHEMA = "subscription-runtime-process-pending.v1"
LAUNCH_READINESS_SCHEMA = "subscription-runtime-process-readiness.v1"
FLEET_READINESS_SCHEMA = "subscription-runtime-process-fleet-readiness.v1"
GRACEFUL_STOP_SCHEMA = "subscription-runtime-process-stop.v1"
PROVIDER_RECEIPT_SCHEMA = "subscription-runtime-codex-execution-receipt.v2"

RUNTIME_ENTRYPOINT_RELATIVE = Path("repo/dist/openai-compatible-codex/cli.js")
RUNTIME_ARTIFACT_MANIFEST_NAME = "artifact-manifest.json"
LAUNCHER_RECEIPT_KEY_NAME = "launcher-receipt.key"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RESERVED_ACCOUNT = "account-i"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class BridgeProcessError(RuntimeError):
    """Stable, secret-free failure at the process launcher boundary."""


@dataclass(frozen=True, slots=True, repr=False)
class BridgePrivateFiles:
    """Private files are capabilities and are deliberately absent from repr/payloads."""

    api_key: Path
    attestation_secret: Path
    launcher_receipt_key: Path

    def __post_init__(self) -> None:
        paths = (self.api_key, self.attestation_secret, self.launcher_receipt_key)
        for path in paths:
            _require_lexical_absolute(path, "private_file")
        if len(set(paths)) != len(paths):
            _fail("bridge_process_private_files_overlap")

    def __repr__(self) -> str:
        return "BridgePrivateFiles(<private>)"


@dataclass(frozen=True, slots=True)
class AccountIRuntimeFence:
    """Lexical resources that this launcher must never inspect, bind, or signal."""

    pid: int
    port: int
    state_root: Path
    auth_root: Path

    def __post_init__(self) -> None:
        if type(self.pid) is not int or self.pid <= 1:
            _fail("bridge_process_account_i_pid_invalid")
        _require_port(self.port, "account_i")
        _require_lexical_absolute(self.state_root, "account_i_state_root")
        _require_lexical_absolute(self.auth_root, "account_i_auth_root")
        if _paths_overlap(self.state_root, self.auth_root):
            _fail("bridge_process_account_i_roots_overlap")


@dataclass(frozen=True, slots=True, repr=False)
class BridgeProcessSpec:
    """Reviewed public config plus opaque references to one account's private files."""

    account_name: str
    port: int
    authority: BridgeAuthority
    state_root: Path
    auth_root: Path
    private_files: BridgePrivateFiles
    runtime_root: Path
    runtime_artifact_manifest_sha256: str
    runtime_entrypoint_sha256: str
    node_executable: Path
    node_executable_sha256: str
    codex_executable: Path
    codex_executable_sha256: str
    readiness_timeout_seconds: float = 30.0
    shutdown_grace_seconds: float = 10.0

    def __post_init__(self) -> None:
        _require_identifier(self.account_name, "account_name")
        if _is_reserved_account(self.account_name):
            _fail("bridge_process_account_i_reserved")
        _require_port(self.port, "port")
        if type(self.authority) is not BridgeAuthority:
            _fail("bridge_process_authority_invalid")
        if self.authority.origin != f"http://127.0.0.1:{self.port}":
            _fail("bridge_process_origin_invalid")
        if self.authority.public_model != self.authority.CODEX_MODEL:
            _fail("bridge_process_public_model_invalid")
        for path, label in (
            (self.state_root, "state_root"),
            (self.auth_root, "auth_root"),
            (self.runtime_root, "runtime_root"),
            (self.node_executable, "node_executable"),
            (self.codex_executable, "codex_executable"),
        ):
            _require_lexical_absolute(path, label)
        if _paths_overlap(self.state_root, self.auth_root):
            _fail("bridge_process_private_roots_overlap")
        if any(
            _paths_overlap(self.runtime_root, private_root)
            for private_root in (self.state_root, self.auth_root)
        ):
            _fail("bridge_process_runtime_private_root_overlap")
        if any(_reserved_path(path) for path in (self.state_root, self.auth_root)):
            _fail("bridge_process_account_i_root_reserved")
        for path in (
            self.private_files.api_key,
            self.private_files.attestation_secret,
            self.private_files.launcher_receipt_key,
        ):
            if path.parent != self.auth_root:
                _fail("bridge_process_private_file_parent_invalid")
        if self.private_files.launcher_receipt_key.name != LAUNCHER_RECEIPT_KEY_NAME:
            _fail("bridge_process_launcher_key_name_invalid")
        for value, label in (
            (self.runtime_artifact_manifest_sha256, "runtime_manifest"),
            (self.runtime_entrypoint_sha256, "runtime_entrypoint"),
            (self.node_executable_sha256, "node_executable"),
            (self.codex_executable_sha256, "codex_executable"),
        ):
            _require_sha256(value, label)
        for value, label in (
            (self.readiness_timeout_seconds, "readiness_timeout"),
            (self.shutdown_grace_seconds, "shutdown_grace"),
        ):
            if (
                type(value) not in {int, float}
                or isinstance(value, bool)
                or not 0.05 <= float(value) <= 120.0
            ):
                _fail(f"bridge_process_{label}_invalid")

    @property
    def runtime_entrypoint(self) -> Path:
        return self.runtime_root / RUNTIME_ENTRYPOINT_RELATIVE

    @property
    def runtime_artifact_manifest(self) -> Path:
        return self.runtime_root / RUNTIME_ARTIFACT_MANIFEST_NAME

    def __repr__(self) -> str:
        return (
            "BridgeProcessSpec("
            f"account_name={self.account_name!r}, bridge_id={self.authority.bridge_id!r}, "
            f"port={self.port!r}, private_material=<bound>)"
        )


@dataclass(frozen=True, slots=True)
class BridgeFleetSpec:
    """Exactly three new single-account processes, fenced away from account-i."""

    pool_id: str
    processes: tuple[BridgeProcessSpec, BridgeProcessSpec, BridgeProcessSpec]
    account_i_fence: AccountIRuntimeFence

    def __post_init__(self) -> None:
        _require_identifier(self.pool_id, "pool_id")
        if type(self.processes) is not tuple or len(self.processes) != 3:
            _fail("bridge_process_fleet_requires_three")
        if any(type(item) is not BridgeProcessSpec for item in self.processes):
            _fail("bridge_process_fleet_member_invalid")
        if type(self.account_i_fence) is not AccountIRuntimeFence:
            _fail("bridge_process_account_i_fence_required")
        _require_distinct((item.account_name for item in self.processes), "account")
        _require_distinct((item.authority.bridge_id for item in self.processes), "bridge")
        _require_distinct((item.port for item in self.processes), "port")
        roots = tuple(root for item in self.processes for root in (item.state_root, item.auth_root))
        for index, root in enumerate(roots):
            if any(_paths_overlap(root, other) for other in roots[index + 1 :]):
                _fail("bridge_process_fleet_roots_overlap")
            if any(
                _paths_overlap(root, protected)
                for protected in (
                    self.account_i_fence.state_root,
                    self.account_i_fence.auth_root,
                )
            ):
                _fail("bridge_process_account_i_root_collision")
        if self.account_i_fence.port in {item.port for item in self.processes}:
            _fail("bridge_process_account_i_port_collision")
        protected_roots = (
            self.account_i_fence.state_root,
            self.account_i_fence.auth_root,
        )
        for item in self.processes:
            public_paths = (
                item.runtime_root,
                item.node_executable,
                item.codex_executable,
            )
            if any(
                _paths_overlap(path, protected)
                for path in public_paths
                for protected in protected_roots
            ):
                _fail("bridge_process_account_i_public_path_collision")

    @property
    def pool(self) -> BridgePoolAuthority:
        return BridgePoolAuthority(
            pool_id=self.pool_id,
            bridges=tuple(item.authority for item in self.processes),
        )


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_ticks: int
    pgid: int
    boot_id: str

    def __post_init__(self) -> None:
        try:
            canonical_boot_id = str(UUID(self.boot_id))
        except (AttributeError, ValueError):
            canonical_boot_id = ""
        if (
            type(self.pid) is not int
            or self.pid <= 1
            or type(self.start_ticks) is not int
            or self.start_ticks <= 0
            or type(self.pgid) is not int
            or self.pgid != self.pid
            or canonical_boot_id != self.boot_id
        ):
            _fail("bridge_process_identity_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "boot_id": self.boot_id,
            "pgid": self.pgid,
            "pid": self.pid,
            "start_ticks": self.start_ticks,
        }

    @classmethod
    def from_payload(cls, value: object) -> ProcessIdentity:
        item = exact_object(
            value,
            required=frozenset({"boot_id", "pgid", "pid", "start_ticks"}),
            label="bridge_process_identity",
        )
        return cls(
            pid=item["pid"],
            start_ticks=item["start_ticks"],
            pgid=item["pgid"],
            boot_id=item["boot_id"],
        )


@dataclass(frozen=True, slots=True)
class RuntimeProcessAuthority:
    account_name: str
    bridge_authority: BridgeAuthority
    state_root_identity_sha256: str
    auth_root_identity_sha256: str
    private_material_binding_hmac_sha256: str
    runtime_artifact_manifest_sha256: str
    runtime_entrypoint_sha256: str
    node_executable_sha256: str
    codex_executable_sha256: str

    CODEX_MODEL: ClassVar[str] = "gpt-5.6-sol"
    REASONING_EFFORT: ClassVar[str] = "high"
    SERVICE_TIER: ClassVar[str] = "priority"
    MAX_CONCURRENT_REQUESTS: ClassVar[int] = 1
    MAX_ACCOUNT_CYCLES: ClassVar[int] = 1
    REQUEST_BODY_MAX_BYTES: ClassVar[int] = 4 * 1024 * 1024
    PROVIDER_RECOVERY: ClassVar[str] = "durable-intent-readback-no-redispatch"

    def __post_init__(self) -> None:
        _require_identifier(self.account_name, "runtime_account_name")
        if _is_reserved_account(self.account_name):
            _fail("bridge_process_account_i_reserved")
        if type(self.bridge_authority) is not BridgeAuthority:
            _fail("bridge_process_runtime_bridge_authority_invalid")
        for value, label in (
            (self.state_root_identity_sha256, "state_root_identity"),
            (self.auth_root_identity_sha256, "auth_root_identity"),
            (self.private_material_binding_hmac_sha256, "private_material_binding_hmac"),
            (self.runtime_artifact_manifest_sha256, "runtime_manifest"),
            (self.runtime_entrypoint_sha256, "runtime_entrypoint"),
            (self.node_executable_sha256, "node_executable"),
            (self.codex_executable_sha256, "codex_executable"),
        ):
            _require_sha256(value, label)

    @property
    def commitment_sha256(self) -> str:
        return _commitment(self.public_payload())

    def public_payload(self) -> dict[str, object]:
        return {
            "account_count": 1,
            "account_name": self.account_name,
            "auth_root_identity_sha256": self.auth_root_identity_sha256,
            "bridge_authority": self.bridge_authority.public_payload(),
            "bridge_authority_sha256": self.bridge_authority.commitment_sha256,
            "codex_executable_sha256": self.codex_executable_sha256,
            "codex_model": self.CODEX_MODEL,
            "environment_policy": "minimal-fixed-no-ambient-credentials",
            "max_account_cycles": self.MAX_ACCOUNT_CYCLES,
            "max_concurrent_requests": self.MAX_CONCURRENT_REQUESTS,
            "node_executable_sha256": self.node_executable_sha256,
            "private_material_binding_hmac_sha256": (self.private_material_binding_hmac_sha256),
            "provider_call_recovery": self.PROVIDER_RECOVERY,
            "provider_receipt_schema": PROVIDER_RECEIPT_SCHEMA,
            "readiness_method": "GET",
            "readiness_provider_calls": 0,
            "readiness_route": "/health",
            "reasoning_effort": self.REASONING_EFFORT,
            "request_body_max_bytes": self.REQUEST_BODY_MAX_BYTES,
            "runtime_artifact_manifest_sha256": self.runtime_artifact_manifest_sha256,
            "runtime_entrypoint_sha256": self.runtime_entrypoint_sha256,
            "schema_version": RUNTIME_PROCESS_AUTHORITY_SCHEMA,
            "service_tier": self.SERVICE_TIER,
            "state_root_identity_sha256": self.state_root_identity_sha256,
        }


@dataclass(frozen=True, slots=True)
class PendingLaunchMetadata:
    account_name: str
    bridge_id: str
    generation: int
    launch_id: str
    mode: Literal["create", "reopen"]
    process: ProcessIdentity
    runtime_authority_sha256: str
    started_at_unix_ms: int
    receipt_hmac_sha256: str

    def __post_init__(self) -> None:
        _require_identifier(self.account_name, "pending_account")
        _require_identifier(self.bridge_id, "pending_bridge")
        _require_positive_int(self.generation, "pending_generation")
        _require_sha256(self.launch_id, "pending_launch_id")
        if self.mode not in {"create", "reopen"}:
            _fail("bridge_process_pending_mode_invalid")
        if type(self.process) is not ProcessIdentity:
            _fail("bridge_process_pending_identity_invalid")
        _require_sha256(self.runtime_authority_sha256, "pending_runtime_authority")
        _require_safe_int(self.started_at_unix_ms, "pending_started_at")
        _require_sha256(self.receipt_hmac_sha256, "pending_receipt_hmac")

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "account_name": self.account_name,
            "bridge_id": self.bridge_id,
            "generation": self.generation,
            "launch_id": self.launch_id,
            "mode": self.mode,
            "process": self.process.public_payload(),
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "schema_version": PENDING_LAUNCH_SCHEMA,
            "started_at_unix_ms": self.started_at_unix_ms,
        }

    def public_payload(self) -> dict[str, object]:
        return {**self.unsigned_payload(), "receipt_hmac_sha256": self.receipt_hmac_sha256}

    def verify(self, key: bytes) -> None:
        _verify_hmac(key, self.unsigned_payload(), self.receipt_hmac_sha256, "pending")

    @classmethod
    def issue(
        cls,
        *,
        account_name: str,
        bridge_id: str,
        generation: int,
        launch_id: str,
        mode: Literal["create", "reopen"],
        process: ProcessIdentity,
        runtime_authority_sha256: str,
        started_at_unix_ms: int,
        key: bytes,
    ) -> PendingLaunchMetadata:
        material = cls(
            account_name=account_name,
            bridge_id=bridge_id,
            generation=generation,
            launch_id=launch_id,
            mode=mode,
            process=process,
            runtime_authority_sha256=runtime_authority_sha256,
            started_at_unix_ms=started_at_unix_ms,
            receipt_hmac_sha256="0" * 64,
        )
        return _replace_hmac(material, _sign(key, material.unsigned_payload()))

    @classmethod
    def from_payload(cls, value: object) -> PendingLaunchMetadata:
        item = exact_object(
            value,
            required=frozenset(
                {
                    "account_name",
                    "bridge_id",
                    "generation",
                    "launch_id",
                    "mode",
                    "process",
                    "receipt_hmac_sha256",
                    "runtime_authority_sha256",
                    "schema_version",
                    "started_at_unix_ms",
                }
            ),
            label="bridge_process_pending",
        )
        if item["schema_version"] != PENDING_LAUNCH_SCHEMA:
            _fail("bridge_process_pending_schema_invalid")
        return cls(
            account_name=item["account_name"],
            bridge_id=item["bridge_id"],
            generation=item["generation"],
            launch_id=item["launch_id"],
            mode=item["mode"],
            process=ProcessIdentity.from_payload(item["process"]),
            runtime_authority_sha256=item["runtime_authority_sha256"],
            started_at_unix_ms=item["started_at_unix_ms"],
            receipt_hmac_sha256=item["receipt_hmac_sha256"],
        )


@dataclass(frozen=True, slots=True)
class RuntimeHealthEvidence:
    response_body_sha256: str
    observed_at_unix_ms: int

    def __post_init__(self) -> None:
        _require_sha256(self.response_body_sha256, "health_response_body")
        _require_safe_int(self.observed_at_unix_ms, "health_observed_at")

    def public_payload(self) -> dict[str, object]:
        return {
            "account_count": 1,
            "active_requests": 0,
            "method": "GET",
            "model": "gpt-5.6-sol",
            "observed_at_unix_ms": self.observed_at_unix_ms,
            "provider_calls": 0,
            "queued_requests": 0,
            "response_body_sha256": self.response_body_sha256,
            "route": "/health",
            "service": "subscription-runtime-openai-compatible-codex",
            "status_code": 200,
        }

    @classmethod
    def from_payload(cls, value: object) -> RuntimeHealthEvidence:
        item = exact_object(
            value,
            required=frozenset(
                {
                    "account_count",
                    "active_requests",
                    "method",
                    "model",
                    "observed_at_unix_ms",
                    "provider_calls",
                    "queued_requests",
                    "response_body_sha256",
                    "route",
                    "service",
                    "status_code",
                }
            ),
            label="bridge_process_health",
        )
        expected = {
            "account_count": 1,
            "active_requests": 0,
            "method": "GET",
            "model": "gpt-5.6-sol",
            "provider_calls": 0,
            "queued_requests": 0,
            "route": "/health",
            "service": "subscription-runtime-openai-compatible-codex",
            "status_code": 200,
        }
        if any(item[key] != value for key, value in expected.items()):
            _fail("bridge_process_health_contract_invalid")
        return cls(
            response_body_sha256=item["response_body_sha256"],
            observed_at_unix_ms=item["observed_at_unix_ms"],
        )


@dataclass(frozen=True, slots=True)
class BridgeLaunchReceipt:
    pending: PendingLaunchMetadata
    health: RuntimeHealthEvidence
    bridge_authority_sha256: str
    runtime_authority_sha256: str
    ready_at_unix_ms: int
    receipt_hmac_sha256: str

    def __post_init__(self) -> None:
        if type(self.pending) is not PendingLaunchMetadata:
            _fail("bridge_process_readiness_pending_invalid")
        if type(self.health) is not RuntimeHealthEvidence:
            _fail("bridge_process_readiness_health_invalid")
        _require_sha256(self.bridge_authority_sha256, "readiness_bridge_authority")
        _require_sha256(self.runtime_authority_sha256, "readiness_runtime_authority")
        if self.runtime_authority_sha256 != self.pending.runtime_authority_sha256:
            _fail("bridge_process_readiness_authority_mismatch")
        _require_safe_int(self.ready_at_unix_ms, "readiness_ready_at")
        if self.ready_at_unix_ms < self.pending.started_at_unix_ms:
            _fail("bridge_process_readiness_time_invalid")
        _require_sha256(self.receipt_hmac_sha256, "readiness_receipt_hmac")

    @property
    def commitment_sha256(self) -> str:
        return _commitment(self.public_payload())

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "bridge_authority_sha256": self.bridge_authority_sha256,
            "health": self.health.public_payload(),
            "pending_launch": self.pending.public_payload(),
            "ready_at_unix_ms": self.ready_at_unix_ms,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "schema_version": LAUNCH_READINESS_SCHEMA,
        }

    def public_payload(self) -> dict[str, object]:
        return {**self.unsigned_payload(), "receipt_hmac_sha256": self.receipt_hmac_sha256}

    def verify(self, key: bytes) -> None:
        self.pending.verify(key)
        _verify_hmac(key, self.unsigned_payload(), self.receipt_hmac_sha256, "readiness")

    @classmethod
    def issue(
        cls,
        *,
        pending: PendingLaunchMetadata,
        health: RuntimeHealthEvidence,
        bridge_authority_sha256: str,
        runtime_authority_sha256: str,
        ready_at_unix_ms: int,
        key: bytes,
    ) -> BridgeLaunchReceipt:
        material = cls(
            pending=pending,
            health=health,
            bridge_authority_sha256=bridge_authority_sha256,
            runtime_authority_sha256=runtime_authority_sha256,
            ready_at_unix_ms=ready_at_unix_ms,
            receipt_hmac_sha256="0" * 64,
        )
        return _replace_hmac(material, _sign(key, material.unsigned_payload()))

    @classmethod
    def from_payload(cls, value: object) -> BridgeLaunchReceipt:
        item = exact_object(
            value,
            required=frozenset(
                {
                    "bridge_authority_sha256",
                    "health",
                    "pending_launch",
                    "ready_at_unix_ms",
                    "receipt_hmac_sha256",
                    "runtime_authority_sha256",
                    "schema_version",
                }
            ),
            label="bridge_process_readiness",
        )
        if item["schema_version"] != LAUNCH_READINESS_SCHEMA:
            _fail("bridge_process_readiness_schema_invalid")
        return cls(
            pending=PendingLaunchMetadata.from_payload(item["pending_launch"]),
            health=RuntimeHealthEvidence.from_payload(item["health"]),
            bridge_authority_sha256=item["bridge_authority_sha256"],
            runtime_authority_sha256=item["runtime_authority_sha256"],
            ready_at_unix_ms=item["ready_at_unix_ms"],
            receipt_hmac_sha256=item["receipt_hmac_sha256"],
        )


@dataclass(frozen=True, slots=True)
class BridgeFleetReadinessReceipt:
    pool: BridgePoolAuthority
    launches: tuple[BridgeLaunchReceipt, BridgeLaunchReceipt, BridgeLaunchReceipt]

    def __post_init__(self) -> None:
        if type(self.pool) is not BridgePoolAuthority or len(self.pool.bridges) != 3:
            _fail("bridge_process_fleet_readiness_pool_invalid")
        if type(self.launches) is not tuple or len(self.launches) != 3:
            _fail("bridge_process_fleet_readiness_launches_invalid")
        for bridge, launch in zip(self.pool.bridges, self.launches, strict=True):
            if (
                type(launch) is not BridgeLaunchReceipt
                or launch.pending.bridge_id != bridge.bridge_id
                or launch.bridge_authority_sha256 != bridge.commitment_sha256
            ):
                _fail("bridge_process_fleet_readiness_order_invalid")

    @property
    def commitment_sha256(self) -> str:
        return _commitment(self.public_payload())

    def public_payload(self) -> dict[str, object]:
        return {
            "ordered_processes": [
                {
                    "bridge_authority_sha256": launch.bridge_authority_sha256,
                    "bridge_id": launch.pending.bridge_id,
                    "generation": launch.pending.generation,
                    "launch_id": launch.pending.launch_id,
                    "readiness_receipt_sha256": launch.commitment_sha256,
                    "runtime_authority_sha256": launch.runtime_authority_sha256,
                }
                for launch in self.launches
            ],
            "pool_authority_sha256": self.pool.commitment_sha256,
            "pool_id": self.pool.pool_id,
            "provider_calls": 0,
            "schema_version": FLEET_READINESS_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class GracefulStopMetadata:
    pending: PendingLaunchMetadata
    readiness_receipt_sha256: str
    reason: str
    requested_at_unix_ms: int
    stopped_at_unix_ms: int
    signal_sent: bool
    escalated: bool
    exit_code: int | None
    receipt_hmac_sha256: str

    def __post_init__(self) -> None:
        if type(self.pending) is not PendingLaunchMetadata:
            _fail("bridge_process_stop_pending_invalid")
        _require_sha256(self.readiness_receipt_sha256, "stop_readiness_receipt")
        _require_identifier(self.reason, "stop_reason")
        _require_safe_int(self.requested_at_unix_ms, "stop_requested_at")
        _require_safe_int(self.stopped_at_unix_ms, "stop_stopped_at")
        if self.stopped_at_unix_ms < self.requested_at_unix_ms:
            _fail("bridge_process_stop_time_invalid")
        if type(self.signal_sent) is not bool or type(self.escalated) is not bool:
            _fail("bridge_process_stop_signal_invalid")
        if self.escalated and not self.signal_sent:
            _fail("bridge_process_stop_escalation_invalid")
        if self.exit_code is not None and type(self.exit_code) is not int:
            _fail("bridge_process_stop_exit_code_invalid")
        _require_sha256(self.receipt_hmac_sha256, "stop_receipt_hmac")

    @property
    def commitment_sha256(self) -> str:
        return _commitment(self.public_payload())

    def unsigned_payload(self) -> dict[str, object]:
        return {
            "escalated": self.escalated,
            "exit_code": self.exit_code,
            "graceful": self.signal_sent and not self.escalated,
            "pending_launch": self.pending.public_payload(),
            "provider_calls": 0,
            "readiness_receipt_sha256": self.readiness_receipt_sha256,
            "reason": self.reason,
            "requested_at_unix_ms": self.requested_at_unix_ms,
            "schema_version": GRACEFUL_STOP_SCHEMA,
            "signal": "SIGTERM" if self.signal_sent else None,
            "signal_sent": self.signal_sent,
            "stopped_at_unix_ms": self.stopped_at_unix_ms,
        }

    def public_payload(self) -> dict[str, object]:
        return {**self.unsigned_payload(), "receipt_hmac_sha256": self.receipt_hmac_sha256}

    def verify(self, key: bytes) -> None:
        self.pending.verify(key)
        _verify_hmac(key, self.unsigned_payload(), self.receipt_hmac_sha256, "stop")

    @classmethod
    def issue(
        cls,
        *,
        pending: PendingLaunchMetadata,
        readiness_receipt_sha256: str,
        reason: str,
        requested_at_unix_ms: int,
        stopped_at_unix_ms: int,
        signal_sent: bool,
        escalated: bool,
        exit_code: int | None,
        key: bytes,
    ) -> GracefulStopMetadata:
        material = cls(
            pending=pending,
            readiness_receipt_sha256=readiness_receipt_sha256,
            reason=reason,
            requested_at_unix_ms=requested_at_unix_ms,
            stopped_at_unix_ms=stopped_at_unix_ms,
            signal_sent=signal_sent,
            escalated=escalated,
            exit_code=exit_code,
            receipt_hmac_sha256="0" * 64,
        )
        return _replace_hmac(material, _sign(key, material.unsigned_payload()))

    @classmethod
    def from_payload(cls, value: object) -> GracefulStopMetadata:
        item = exact_object(
            value,
            required=frozenset(
                {
                    "escalated",
                    "exit_code",
                    "graceful",
                    "pending_launch",
                    "provider_calls",
                    "readiness_receipt_sha256",
                    "reason",
                    "receipt_hmac_sha256",
                    "requested_at_unix_ms",
                    "schema_version",
                    "signal",
                    "signal_sent",
                    "stopped_at_unix_ms",
                }
            ),
            label="bridge_process_stop",
        )
        if (
            item["schema_version"] != GRACEFUL_STOP_SCHEMA
            or item["provider_calls"] != 0
            or item["graceful"] is not (item["signal_sent"] and not item["escalated"])
            or item["signal"] != ("SIGTERM" if item["signal_sent"] else None)
        ):
            _fail("bridge_process_stop_schema_invalid")
        return cls(
            pending=PendingLaunchMetadata.from_payload(item["pending_launch"]),
            readiness_receipt_sha256=item["readiness_receipt_sha256"],
            reason=item["reason"],
            requested_at_unix_ms=item["requested_at_unix_ms"],
            stopped_at_unix_ms=item["stopped_at_unix_ms"],
            signal_sent=item["signal_sent"],
            escalated=item["escalated"],
            exit_code=item["exit_code"],
            receipt_hmac_sha256=item["receipt_hmac_sha256"],
        )


def _replace_hmac(value, receipt_hmac_sha256: str):
    fields = {
        name: getattr(value, name)
        for name in value.__dataclass_fields__  # noqa: SLF001 - local frozen contract helper
    }
    fields["receipt_hmac_sha256"] = receipt_hmac_sha256
    return type(value)(**fields)


def _sign(key: bytes, payload: object) -> str:
    _require_hmac_key(key)
    return hmac.new(key, canonical_json_bytes(payload), hashlib.sha256).hexdigest()


def _verify_hmac(key: bytes, payload: object, actual: str, label: str) -> None:
    expected = _sign(key, payload)
    if not hmac.compare_digest(expected, actual):
        _fail(f"bridge_process_{label}_hmac_mismatch")


def _require_hmac_key(key: object) -> None:
    if type(key) is not bytes or not 32 <= len(key) <= 4096:
        _fail("bridge_process_launcher_key_invalid")


def _commitment(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_identifier(value: object, label: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        _fail(f"bridge_process_{label}_invalid")


def _require_sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"bridge_process_{label}_sha256_invalid")


def _require_safe_int(value: object, label: str) -> None:
    if type(value) is not int or not 0 <= value <= _MAX_SAFE_INTEGER:
        _fail(f"bridge_process_{label}_invalid")


def _require_positive_int(value: object, label: str) -> None:
    _require_safe_int(value, label)
    if value == 0:
        _fail(f"bridge_process_{label}_invalid")


def _require_port(value: object, label: str) -> None:
    if type(value) is not int or not 1024 <= value <= 65535:
        _fail(f"bridge_process_{label}_invalid")


def _require_lexical_absolute(path: object, label: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute():
        _fail(f"bridge_process_{label}_invalid")
    normalized = Path(os.path.abspath(os.fspath(path)))
    if path != normalized or path.name in {"", ".", ".."}:
        _fail(f"bridge_process_{label}_invalid")


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _is_reserved_account(value: str) -> bool:
    return value.casefold().replace("_", "-") == _RESERVED_ACCOUNT


def _reserved_path(path: Path) -> bool:
    return any(_is_reserved_account(part) for part in path.parts)


def _require_distinct(values, label: str) -> None:
    material = tuple(values)
    if len(set(material)) != len(material):
        _fail(f"bridge_process_fleet_{label}_duplicate")


def _fail(code: str) -> None:
    raise BridgeProcessError(code)


__all__ = (
    "AccountIRuntimeFence",
    "BridgeFleetReadinessReceipt",
    "BridgeFleetSpec",
    "BridgeLaunchReceipt",
    "BridgePrivateFiles",
    "BridgeProcessError",
    "BridgeProcessSpec",
    "GracefulStopMetadata",
    "PendingLaunchMetadata",
    "ProcessIdentity",
    "RuntimeHealthEvidence",
    "RuntimeProcessAuthority",
)
