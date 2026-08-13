"""Strict public configuration for the isolated publishable Mem0 v5 lane.

The configuration contains paths and public commitments only.  Secret values
remain in private files below the configured lane roots and are never rendered
into Compose arguments, logs, or attestations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

CONFIG_SCHEMA: Final = "publishable-mem0-v5-isolated-lane.v2"
PROJECT_CONFIG_SCHEMA: Final = "publishable-mem0-v5-project-lane.v1"
CONFIG_AUTHENTICATION_SCHEMA: Final = "publishable-mem0-v5-config-authentication.v1"
PINNED_DOCKER_HOST: Final = "unix:///run/infinity-locomo-docker/docker.sock"
DEPLOYMENT_AUTHORITY_KEY_NAME: Final = "deployment-authority-hmac.secret"
COMPOSE_SHA256: Final = "064cc0d6edb2353d928dc2b6c9b7e1524348658fb5c85d0efdcf6dd3e9178c37"
QDRANT_IMAGE: Final = (
    "qdrant/qdrant:v1.18.3@sha256:ecc81d662bb9bb734db879b94461eb44be38604fc259491d478ad7e673238a0d"
)
QDRANT_HTTP_PORT: Final = 6334
QDRANT_GRPC_PORT: Final = 6335
ADAPTER_PORT: Final = 19091
RELAY_PORT: Final = 19191
BRIDGE_PORTS: Final = (8891, 8892, 8893)
BASE_INSTRUCTIONS_SHA256: Final = "5c15d6c502d380282a933d4f20a886a06c9d04d3b5d7c918b95df0b0acf33671"
SOURCE_MANIFEST_SHA256: Final = "4293c131829fc9bdf56b5bf77459c0ec528f99ebb898ba27553f718301788d79"
SOURCE_COMMIT_SHA1: Final = "a7c4e9e56a9e2779cce6edef917368dab23056d0"
SOURCE_COMMIT_SHA256: Final = "301bf3f836375b564392d9964969337149219438329536f1790f3ab0c850455f"
RUNTIME_PIN_SHA256: Final = "3637ce6c0b6b7f3b0b88bd3e8083178c7fc85df70869e89f958a35ae85709474"
RUNTIME_MANIFEST_SHA256: Final = "789018b5b15a1299252895babdc550c3d5322c54a1d9c82656f93d31423a0850"
RUNTIME_ENTRYPOINT_SHA256: Final = (
    "83db85671ec5da675706c903e5b8ed1ae0cb307014d7c10a10be34f1700762fd"
)
NODE_EXECUTABLE_SHA256: Final = "b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd"
PROTECTED_ACCOUNT_I_AUTH_ROOT: Final = Path("/var/data/codex-home/live-codex-auth/account-i")
PROTECTED_R16_ROOT: Final = Path(
    "/mnt/volume_ams3_1784742570542/infinity-context/live-canaries/mem0-v5-live-d7bf1ac4-r16"
)
CONTAINER_UID: Final = 65532
CONTAINER_GID: Final = 65532

_MAX_CONFIG_BYTES = 256 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT = re.compile(r"^mem0-v5-publishable-[a-z0-9][a-z0-9-]{5,63}$")
_ACCOUNT = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")


class DeploymentConfigError(ValueError):
    """Stable fail-closed public configuration error."""


@dataclass(frozen=True, slots=True)
class BridgeAccountConfig:
    """Public authority for one new, non-account-i runtime account."""

    account_name: str
    bridge_id: str
    account_binding_hmac_sha256: str

    def __post_init__(self) -> None:
        if _ACCOUNT.fullmatch(self.account_name) is None or _reserved(self.account_name):
            _fail("publishable_lane_bridge_account_invalid")
        if _IDENTIFIER.fullmatch(self.bridge_id) is None:
            _fail("publishable_lane_bridge_id_invalid")
        _require_sha256(self.account_binding_hmac_sha256, "bridge_account_binding")


@dataclass(frozen=True, slots=True)
class BindMountAuthorityConfig:
    """Reviewed hashes and keyed commitments for mutable host bind sources."""

    config_hmac_sha256: str
    deployment_closure_sha256: str
    deployment_closure_hmac_sha256: str
    server_closure_sha256: str
    server_closure_hmac_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.config_hmac_sha256, "config_hmac"),
            (self.deployment_closure_sha256, "deployment_closure"),
            (self.deployment_closure_hmac_sha256, "deployment_closure_hmac"),
            (self.server_closure_sha256, "server_closure"),
            (self.server_closure_hmac_sha256, "server_closure_hmac"),
        ):
            _require_sha256(value, label)

    def payload(self, *, include_config_hmac: bool = True) -> dict[str, str]:
        result = {
            "deployment_closure_hmac_sha256": self.deployment_closure_hmac_sha256,
            "deployment_closure_sha256": self.deployment_closure_sha256,
            "server_closure_hmac_sha256": self.server_closure_hmac_sha256,
            "server_closure_sha256": self.server_closure_sha256,
        }
        if include_config_hmac:
            result["config_hmac_sha256"] = self.config_hmac_sha256
        return result


@dataclass(frozen=True, slots=True)
class RuntimeAuthorityConfig:
    """Immutable runtime and executable paths with their reviewed digests."""

    runtime_root: Path
    runtime_artifact_manifest_sha256: str
    runtime_entrypoint_sha256: str
    node_executable: Path
    node_executable_sha256: str
    codex_executable: Path
    codex_executable_sha256: str
    runtime_pin_sha256: str = RUNTIME_PIN_SHA256
    source_commit_sha256: str = SOURCE_COMMIT_SHA256

    def __post_init__(self) -> None:
        for path, label in (
            (self.runtime_root, "runtime_root"),
            (self.node_executable, "node_executable"),
            (self.codex_executable, "codex_executable"),
        ):
            _require_absolute_path(path, label)
        if self.runtime_artifact_manifest_sha256 != RUNTIME_MANIFEST_SHA256:
            _fail("publishable_lane_runtime_manifest_pin_invalid")
        if self.runtime_entrypoint_sha256 != RUNTIME_ENTRYPOINT_SHA256:
            _fail("publishable_lane_runtime_entrypoint_pin_invalid")
        if self.node_executable_sha256 != NODE_EXECUTABLE_SHA256:
            _fail("publishable_lane_node_pin_invalid")
        _require_sha256(self.codex_executable_sha256, "codex_executable")
        if self.runtime_pin_sha256 != RUNTIME_PIN_SHA256:
            _fail("publishable_lane_runtime_pin_stale")
        if self.source_commit_sha256 != SOURCE_COMMIT_SHA256:
            _fail("publishable_lane_runtime_source_cross_wire")
        if self.node_executable == self.codex_executable:
            _fail("publishable_lane_executable_paths_overlap")


@dataclass(frozen=True, slots=True)
class LanePaths:
    """Host paths mounted only into the new Compose project."""

    run_root: Path
    input_dir: Path
    adapter_state_dir: Path
    qdrant_state_dir: Path
    adapter_secret_dir: Path
    fleet_state_dir: Path
    fleet_auth_dir: Path
    attestation_dir: Path
    phase_c_authority_dir: Path
    source_authority_dir: Path
    source_authority_pin_dir: Path
    source_authority_pin_sha256_file: Path
    server_package_dir: Path
    deployment_dir: Path

    def __post_init__(self) -> None:
        values = tuple((value, name) for name, value in _dataclass_items(self))
        for path, label in values:
            _require_absolute_path(path, label)
        private = (
            self.input_dir,
            self.adapter_state_dir,
            self.qdrant_state_dir,
            self.adapter_secret_dir,
            self.fleet_state_dir,
            self.fleet_auth_dir,
            self.attestation_dir,
        )
        if any(not _strict_descendant(path, self.run_root) for path in private):
            _fail("publishable_lane_private_path_outside_run_root")
        if len(set(private)) != len(private):
            _fail("publishable_lane_private_paths_overlap")
        for index, path in enumerate(private):
            if any(_paths_overlap(path, other) for other in private[index + 1 :]):
                _fail("publishable_lane_private_paths_overlap")
        protected = (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
        if any(
            _paths_overlap(path, item)
            for path in (self.run_root, *values_paths(values))
            for item in protected
        ):
            _fail("publishable_lane_protected_path_collision")
        if self.source_authority_pin_sha256_file.parent != self.source_authority_pin_dir:
            _fail("publishable_lane_source_pin_path_invalid")


@dataclass(frozen=True, slots=True)
class AccountIR16Fence:
    """Opaque host authority that must be reattested but never traversed or mutated."""

    pid: int
    start_ticks: int
    boot_id: str
    netns_inode: int
    port: int
    state_root: Path
    auth_root: Path
    protected_host_ports: tuple[int, ...]
    container_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.pid) is not int or self.pid <= 1:
            _fail("publishable_lane_account_i_pid_invalid")
        if type(self.start_ticks) is not int or self.start_ticks <= 0:
            _fail("publishable_lane_account_i_start_ticks_invalid")
        try:
            canonical_boot_id = str(UUID(self.boot_id))
        except (AttributeError, ValueError):
            canonical_boot_id = ""
        if canonical_boot_id != self.boot_id:
            _fail("publishable_lane_account_i_boot_id_invalid")
        if type(self.netns_inode) is not int or self.netns_inode <= 0:
            _fail("publishable_lane_account_i_netns_invalid")
        _require_port(self.port, "account_i")
        if self.state_root != PROTECTED_R16_ROOT or self.auth_root != PROTECTED_ACCOUNT_I_AUTH_ROOT:
            _fail("publishable_lane_account_i_roots_invalid")
        if (
            type(self.protected_host_ports) is not tuple
            or len(self.protected_host_ports) < 4
            or len(set(self.protected_host_ports)) != len(self.protected_host_ports)
        ):
            _fail("publishable_lane_protected_ports_invalid")
        for port in self.protected_host_ports:
            _require_port(port, "protected")
        if not {6334, 8891, 8892, 19091}.issubset(self.protected_host_ports):
            _fail("publishable_lane_r16_ports_incomplete")
        if (
            type(self.container_ids) is not tuple
            or not 1 <= len(self.container_ids) <= 16
            or len(set(self.container_ids)) != len(self.container_ids)
            or any(_CONTAINER_ID.fullmatch(value) is None for value in self.container_ids)
        ):
            _fail("publishable_lane_account_i_container_ids_invalid")


@dataclass(frozen=True, slots=True)
class ProjectIsolationAuthority:
    """Explicit project-only isolation contract, containing no host PID authority."""

    inventory_scope: str
    project_name: str
    docker_host: str
    pid_mode: str
    daemon_global_observation: bool
    host_process_observation: bool

    def __post_init__(self) -> None:
        if (
            self.inventory_scope != "project"
            or _PROJECT.fullmatch(self.project_name) is None
            or self.docker_host != PINNED_DOCKER_HOST
            or self.pid_mode not in {"private", "empty"}
            or self.daemon_global_observation is not False
            or self.host_process_observation is not False
        ):
            _fail("publishable_lane_project_isolation_authority_invalid")

    def payload(self) -> dict[str, object]:
        return {
            "daemon_global_observation": False,
            "docker_host": self.docker_host,
            "host_process_observation": False,
            "inventory_scope": "project",
            "pid_mode": self.pid_mode,
            "project_name": self.project_name,
        }

    @property
    def commitment_sha256(self) -> str:
        raw = json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class PublishableLaneConfig:
    """Complete reviewed public authority for one new isolated lane."""

    project_name: str
    adapter_image_id: str
    host_adapter_port: int
    docker_host: str
    source_manifest_sha256: str
    bind_mount_authority: BindMountAuthorityConfig
    paths: LanePaths
    runtime: RuntimeAuthorityConfig
    bridges: tuple[BridgeAccountConfig, BridgeAccountConfig, BridgeAccountConfig]
    account_i_r16_fence: AccountIR16Fence | None = None
    project_isolation_authority: ProjectIsolationAuthority | None = None

    def __post_init__(self) -> None:
        if _PROJECT.fullmatch(self.project_name) is None or _reserved(self.project_name):
            _fail("publishable_lane_project_name_invalid")
        if self.paths.run_root.name != self.project_name:
            _fail("publishable_lane_run_root_project_mismatch")
        if _IMAGE_ID.fullmatch(self.adapter_image_id) is None:
            _fail("publishable_lane_adapter_image_id_invalid")
        _require_port(self.host_adapter_port, "host_adapter")
        if (self.account_i_r16_fence is None) == (self.project_isolation_authority is None):
            _fail("publishable_lane_exactly_one_isolation_authority_required")
        if self.project_isolation_authority is not None and (
            self.project_isolation_authority.project_name != self.project_name
            or self.project_isolation_authority.docker_host != self.docker_host
        ):
            _fail("publishable_lane_project_isolation_authority_cross_wire")
        protected_ports = () if self.account_i_r16_fence is None else (
            self.account_i_r16_fence.port, *self.account_i_r16_fence.protected_host_ports
        )
        forbidden = {
            ADAPTER_PORT,
            QDRANT_HTTP_PORT,
            QDRANT_GRPC_PORT,
            RELAY_PORT,
            *BRIDGE_PORTS,
            *protected_ports,
        }
        if self.host_adapter_port in forbidden:
            _fail("publishable_lane_host_adapter_port_collision")
        if self.docker_host != PINNED_DOCKER_HOST:
            _fail("publishable_lane_docker_host_invalid")
        _require_absolute_path(Path(self.docker_host.removeprefix("unix://")), "docker_socket")
        if self.source_manifest_sha256 != SOURCE_MANIFEST_SHA256:
            _fail("publishable_lane_source_manifest_pin_invalid")
        if type(self.bridges) is not tuple or len(self.bridges) != 3:
            _fail("publishable_lane_requires_three_bridges")
        if any(type(item) is not BridgeAccountConfig for item in self.bridges):
            _fail("publishable_lane_bridge_invalid")
        if len({item.account_name for item in self.bridges}) != 3:
            _fail("publishable_lane_bridge_account_duplicate")
        if len({item.bridge_id for item in self.bridges}) != 3:
            _fail("publishable_lane_bridge_id_duplicate")
        if len({item.account_binding_hmac_sha256 for item in self.bridges}) != 3:
            _fail("publishable_lane_bridge_binding_duplicate")
        if self.account_i_r16_fence is not None and self.account_i_r16_fence.port in BRIDGE_PORTS:
            _fail("publishable_lane_account_i_internal_port_collision")

    def authentication_payload(self) -> dict[str, object]:
        """Canonical secret-free semantics covered by the config HMAC."""

        payload = self.public_payload()
        authority = dict(payload["bind_mount_authority"])
        authority.pop("config_hmac_sha256")
        payload["bind_mount_authority"] = authority
        return {
            "config": payload,
            "schema_version": CONFIG_AUTHENTICATION_SCHEMA,
        }

    def public_payload(self) -> dict[str, object]:
        """Render the exact strict JSON shape accepted by :func:`load_lane_config`."""

        paths = {name: str(getattr(self.paths, name)) for name in self.paths.__dataclass_fields__}
        runtime = {
            name: (
                str(getattr(self.runtime, name))
                if isinstance(getattr(self.runtime, name), Path)
                else getattr(self.runtime, name)
            )
            for name in self.runtime.__dataclass_fields__
        }
        fence = None if self.account_i_r16_fence is None else {
            "auth_root": str(self.account_i_r16_fence.auth_root),
            "boot_id": self.account_i_r16_fence.boot_id,
            "container_ids": list(self.account_i_r16_fence.container_ids),
            "netns_inode": self.account_i_r16_fence.netns_inode,
            "pid": self.account_i_r16_fence.pid,
            "port": self.account_i_r16_fence.port,
            "protected_host_ports": list(self.account_i_r16_fence.protected_host_ports),
            "start_ticks": self.account_i_r16_fence.start_ticks,
            "state_root": str(self.account_i_r16_fence.state_root),
        }
        result = {
            "adapter_image_id": self.adapter_image_id,
            "bind_mount_authority": self.bind_mount_authority.payload(),
            "bridges": [
                {
                    "account_binding_hmac_sha256": item.account_binding_hmac_sha256,
                    "account_name": item.account_name,
                    "bridge_id": item.bridge_id,
                }
                for item in self.bridges
            ],
            "docker_host": self.docker_host,
            "host_adapter_port": self.host_adapter_port,
            "paths": paths,
            "project_name": self.project_name,
            "runtime": runtime,
            "schema_version": (
                CONFIG_SCHEMA if fence is not None else PROJECT_CONFIG_SCHEMA
            ),
            "source_manifest_sha256": self.source_manifest_sha256,
        }
        if fence is not None:
            result["account_i_r16_fence"] = fence
        else:
            result["project_isolation_authority"] = (
                self.project_isolation_authority.payload()
            )
        return result

    def compose_environment(self, *, config_file: Path, fleet_mode: str) -> MappingProxyType:
        """Render the only environment admitted to the fixed Compose asset."""

        if fleet_mode not in {"create", "reopen"}:
            _fail("publishable_lane_fleet_mode_invalid")
        _require_absolute_path(config_file, "config_file")
        environment = {
            "DOCKER_HOST": self.docker_host,
            "MEM0_V5_PUBLISHABLE_ADAPTER_IMAGE_ID": self.adapter_image_id,
            "MEM0_V5_PUBLISHABLE_ADAPTER_SECRET_DIR": str(self.paths.adapter_secret_dir),
            "MEM0_V5_PUBLISHABLE_ADAPTER_STATE_DIR": str(self.paths.adapter_state_dir),
            "MEM0_V5_PUBLISHABLE_CODEX_EXECUTABLE_SOURCE": str(self.runtime.codex_executable),
            "MEM0_V5_PUBLISHABLE_CONFIG_FILE": str(config_file),
            "MEM0_V5_PUBLISHABLE_DEPLOYMENT_DIR": str(self.paths.deployment_dir),
            "MEM0_V5_PUBLISHABLE_FLEET_MODE": fleet_mode,
            "MEM0_V5_PUBLISHABLE_HOST_ADAPTER_PORT": str(self.host_adapter_port),
            "MEM0_V5_PUBLISHABLE_INPUT_DIR": str(self.paths.input_dir),
            "MEM0_V5_PUBLISHABLE_NODE_EXECUTABLE_SOURCE": str(self.runtime.node_executable),
            "MEM0_V5_PUBLISHABLE_PHASE_C_AUTHORITY_DIR": str(self.paths.phase_c_authority_dir),
            "MEM0_V5_PUBLISHABLE_QDRANT_STATE_DIR": str(self.paths.qdrant_state_dir),
            "MEM0_V5_PUBLISHABLE_RUNTIME_AUTHORITY_DIR": str(self.runtime.runtime_root),
            "MEM0_V5_PUBLISHABLE_SERVER_PACKAGE_DIR": str(self.paths.server_package_dir),
            "MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_DIR": str(self.paths.source_authority_dir),
            "MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_PIN_DIR": str(
                self.paths.source_authority_pin_dir
            ),
            "MEM0_V5_PUBLISHABLE_SOURCE_AUTHORITY_PIN_SHA256_FILE": str(
                self.paths.source_authority_pin_sha256_file
            ),
        }
        for label, bridge in zip(("A", "B", "C"), self.bridges, strict=True):
            environment[f"MEM0_V5_PUBLISHABLE_BRIDGE_{label}_AUTH_DIR"] = str(
                self.paths.fleet_auth_dir / bridge.account_name
            )
            environment[f"MEM0_V5_PUBLISHABLE_BRIDGE_{label}_STATE_DIR"] = str(
                self.paths.fleet_state_dir / bridge.account_name
            )
        return MappingProxyType(environment)


def load_lane_config(path: Path) -> PublishableLaneConfig:
    """Read one duplicate-key-free canonical JSON configuration."""

    _require_absolute_path(path, "config_file")
    raw = _read_config_bytes(path)
    if not raw or len(raw) > _MAX_CONFIG_BYTES:
        _fail("publishable_lane_config_size_invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DeploymentConfigError) as exc:
        raise DeploymentConfigError("publishable_lane_config_json_invalid") from exc
    root = _object(
        value,
        {
            "schema_version",
            "project_name",
            "adapter_image_id",
            "host_adapter_port",
            "docker_host",
            "source_manifest_sha256",
            "bind_mount_authority",
            "paths",
            "runtime",
            "bridges",
            "account_i_r16_fence",
        },
        "root",
    )
    if root["schema_version"] != CONFIG_SCHEMA:
        _fail("publishable_lane_config_schema_invalid")
    paths = _parse_paths(root["paths"])
    runtime = _parse_runtime(root["runtime"])
    bridges_value = root["bridges"]
    if type(bridges_value) is not list or len(bridges_value) != 3:
        _fail("publishable_lane_requires_three_bridges")
    bridges = tuple(_parse_bridge(item) for item in bridges_value)
    return PublishableLaneConfig(
        project_name=_string(root["project_name"], "project_name"),
        adapter_image_id=_string(root["adapter_image_id"], "adapter_image_id"),
        host_adapter_port=_integer(root["host_adapter_port"], "host_adapter_port"),
        docker_host=_string(root["docker_host"], "docker_host"),
        source_manifest_sha256=_string(root["source_manifest_sha256"], "source_manifest_sha256"),
        bind_mount_authority=_parse_bind_mount_authority(root["bind_mount_authority"]),
        paths=paths,
        runtime=runtime,
        bridges=bridges,
        account_i_r16_fence=_parse_fence(root["account_i_r16_fence"]),
    )


def load_provider_free_project_lane_config(path: Path) -> PublishableLaneConfig:
    """Read the distinct project-only schema without accepting production v2."""

    _require_absolute_path(path, "config_file")
    raw = _read_config_bytes(path)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DeploymentConfigError) as exc:
        raise DeploymentConfigError("publishable_lane_config_json_invalid") from exc
    root = _object(value, {
        "schema_version", "project_name", "adapter_image_id", "host_adapter_port",
        "docker_host", "source_manifest_sha256", "bind_mount_authority", "paths",
        "runtime", "bridges", "project_isolation_authority",
    }, "root")
    if root["schema_version"] != PROJECT_CONFIG_SCHEMA:
        _fail("publishable_lane_project_config_schema_invalid")
    project = _object(root["project_isolation_authority"], {
        "inventory_scope", "project_name", "docker_host", "pid_mode",
        "daemon_global_observation", "host_process_observation",
    }, "project_isolation_authority")
    bridges_value = root["bridges"]
    if type(bridges_value) is not list or len(bridges_value) != 3:
        _fail("publishable_lane_requires_three_bridges")
    return PublishableLaneConfig(
        project_name=_string(root["project_name"], "project_name"),
        adapter_image_id=_string(root["adapter_image_id"], "adapter_image_id"),
        host_adapter_port=_integer(root["host_adapter_port"], "host_adapter_port"),
        docker_host=_string(root["docker_host"], "docker_host"),
        source_manifest_sha256=_string(root["source_manifest_sha256"], "source_manifest_sha256"),
        bind_mount_authority=_parse_bind_mount_authority(root["bind_mount_authority"]),
        paths=_parse_paths(root["paths"]), runtime=_parse_runtime(root["runtime"]),
        bridges=tuple(_parse_bridge(item) for item in bridges_value),
        project_isolation_authority=ProjectIsolationAuthority(
            inventory_scope=_string(
                project["inventory_scope"], "project_isolation_authority.inventory_scope"
            ),
            project_name=_string(
                project["project_name"], "project_isolation_authority.project_name"
            ),
            docker_host=_string(
                project["docker_host"], "project_isolation_authority.docker_host"
            ),
            pid_mode=_string(
                project["pid_mode"], "project_isolation_authority.pid_mode"
            ),
            daemon_global_observation=_exact_false(
                project["daemon_global_observation"],
                "project_isolation_authority.daemon_global_observation",
            ),
            host_process_observation=_exact_false(
                project["host_process_observation"],
                "project_isolation_authority.host_process_observation",
            ),
        ),
    )


def load_runtime_lane_config(path: Path) -> PublishableLaneConfig:
    """Dispatch only by the exact declared schema used inside lane containers."""

    _require_absolute_path(path, "config_file")
    raw = _read_config_bytes(path)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, DeploymentConfigError) as exc:
        raise DeploymentConfigError("publishable_lane_config_json_invalid") from exc
    if type(value) is not dict or type(value.get("schema_version")) is not str:
        _fail("publishable_lane_config_schema_invalid")
    schema = value["schema_version"]
    if schema == CONFIG_SCHEMA:
        return load_lane_config(path)
    if schema == PROJECT_CONFIG_SCHEMA:
        return load_provider_free_project_lane_config(path)
    _fail("publishable_lane_config_schema_invalid")


def _parse_paths(value: object) -> LanePaths:
    names = {
        "run_root",
        "input_dir",
        "adapter_state_dir",
        "qdrant_state_dir",
        "adapter_secret_dir",
        "fleet_state_dir",
        "fleet_auth_dir",
        "attestation_dir",
        "phase_c_authority_dir",
        "source_authority_dir",
        "source_authority_pin_dir",
        "source_authority_pin_sha256_file",
        "server_package_dir",
        "deployment_dir",
    }
    item = _object(value, names, "paths")
    return LanePaths(**{name: Path(_string(item[name], name)) for name in names})


def _parse_runtime(value: object) -> RuntimeAuthorityConfig:
    names = {
        "runtime_root",
        "runtime_artifact_manifest_sha256",
        "runtime_entrypoint_sha256",
        "node_executable",
        "node_executable_sha256",
        "codex_executable",
        "codex_executable_sha256",
        "runtime_pin_sha256",
        "source_commit_sha256",
    }
    item = _object(value, names, "runtime")
    return RuntimeAuthorityConfig(
        runtime_root=Path(_string(item["runtime_root"], "runtime_root")),
        runtime_artifact_manifest_sha256=_string(
            item["runtime_artifact_manifest_sha256"], "runtime_artifact_manifest_sha256"
        ),
        runtime_entrypoint_sha256=_string(
            item["runtime_entrypoint_sha256"], "runtime_entrypoint_sha256"
        ),
        node_executable=Path(_string(item["node_executable"], "node_executable")),
        node_executable_sha256=_string(item["node_executable_sha256"], "node_executable_sha256"),
        codex_executable=Path(_string(item["codex_executable"], "codex_executable")),
        codex_executable_sha256=_string(item["codex_executable_sha256"], "codex_executable_sha256"),
        runtime_pin_sha256=_string(item["runtime_pin_sha256"], "runtime_pin_sha256"),
        source_commit_sha256=_string(item["source_commit_sha256"], "source_commit_sha256"),
    )


def _parse_bind_mount_authority(value: object) -> BindMountAuthorityConfig:
    names = {
        "config_hmac_sha256",
        "deployment_closure_sha256",
        "deployment_closure_hmac_sha256",
        "server_closure_sha256",
        "server_closure_hmac_sha256",
    }
    item = _object(value, names, "bind_mount_authority")
    return BindMountAuthorityConfig(**{name: _string(item[name], name) for name in names})


def _parse_bridge(value: object) -> BridgeAccountConfig:
    item = _object(
        value,
        {"account_name", "bridge_id", "account_binding_hmac_sha256"},
        "bridge",
    )
    return BridgeAccountConfig(
        account_name=_string(item["account_name"], "account_name"),
        bridge_id=_string(item["bridge_id"], "bridge_id"),
        account_binding_hmac_sha256=_string(
            item["account_binding_hmac_sha256"], "account_binding_hmac_sha256"
        ),
    )


def _parse_fence(value: object) -> AccountIR16Fence:
    names = {
        "pid",
        "start_ticks",
        "boot_id",
        "netns_inode",
        "port",
        "state_root",
        "auth_root",
        "protected_host_ports",
        "container_ids",
    }
    item = _object(value, names, "account_i_r16_fence")
    ports = item["protected_host_ports"]
    containers = item["container_ids"]
    if type(ports) is not list or type(containers) is not list:
        _fail("publishable_lane_account_i_fence_invalid")
    return AccountIR16Fence(
        pid=_integer(item["pid"], "pid"),
        start_ticks=_integer(item["start_ticks"], "start_ticks"),
        boot_id=_string(item["boot_id"], "boot_id"),
        netns_inode=_integer(item["netns_inode"], "netns_inode"),
        port=_integer(item["port"], "port"),
        state_root=Path(_string(item["state_root"], "state_root")),
        auth_root=Path(_string(item["auth_root"], "auth_root")),
        protected_host_ports=tuple(_integer(port, "protected_port") for port in ports),
        container_ids=tuple(_string(container, "container_id") for container in containers),
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("publishable_lane_config_duplicate_key")
        result[key] = value
    return result


def _read_config_bytes(path: Path) -> bytes:
    current = path
    chain: list[Path] = []
    while True:
        chain.append(current)
        if current.parent == current:
            break
        current = current.parent
    try:
        for index, item in enumerate(reversed(chain)):
            metadata = item.lstat()
            if stat.S_ISLNK(metadata.st_mode) or (
                index < len(chain) - 1 and not stat.S_ISDIR(metadata.st_mode)
            ):
                _fail("publishable_lane_config_path_unsafe")
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DeploymentConfigError("publishable_lane_config_unavailable") from exc
    protected = tuple(
        item.resolve(strict=False) for item in (PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    )
    if resolved != path or any(
        _paths_overlap(candidate, item)
        for candidate in (path, resolved)
        for item in (*protected, PROTECTED_ACCOUNT_I_AUTH_ROOT, PROTECTED_R16_ROOT)
    ):
        _fail("publishable_lane_config_path_unsafe")
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_mode & 0o022
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_size <= 0
            or opened.st_size > _MAX_CONFIG_BYTES
        ):
            _fail("publishable_lane_config_file_unsafe")
        raw = os.read(descriptor, _MAX_CONFIG_BYTES + 1)
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
            _fail("publishable_lane_config_file_changed")
        return raw
    except OSError as exc:
        raise DeploymentConfigError("publishable_lane_config_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _object(value: object, required: set[str], label: str) -> dict[str, Any]:
    if (
        type(value) is not dict
        or set(value) != required
        or any(type(key) is not str for key in value)
    ):
        _fail(f"publishable_lane_{label}_fields_invalid")
    return value


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        _fail(f"publishable_lane_{label}_invalid")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        _fail(f"publishable_lane_{label}_invalid")
    return value


def _exact_false(value: object, label: str) -> bool:
    if value is not False:
        _fail(f"publishable_lane_{label}_invalid")
    return False


def _require_port(value: object, label: str) -> None:
    if type(value) is not int or not 1024 <= value <= 65535:
        _fail(f"publishable_lane_{label}_port_invalid")


def _require_sha256(value: object, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail(f"publishable_lane_{label}_sha256_invalid")


def _require_absolute_path(value: object, label: str) -> None:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or Path(os.path.normpath(value)) != value
    ):
        _fail(f"publishable_lane_{label}_path_invalid")


def _strict_descendant(path: Path, parent: Path) -> bool:
    return path != parent and parent in path.parents


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _reserved(value: str) -> bool:
    canonical = value.casefold().replace("_", "-")
    return "account-i" in canonical or canonical == "r16" or canonical.endswith("-r16")


def _dataclass_items(value: LanePaths) -> tuple[tuple[str, Path], ...]:
    return tuple((name, getattr(value, name)) for name in value.__dataclass_fields__)


def values_paths(values: tuple[tuple[Path, str], ...]) -> tuple[Path, ...]:
    return tuple(path for path, _ in values)


def _fail(code: str) -> None:
    raise DeploymentConfigError(code)


__all__ = (
    "ADAPTER_PORT",
    "BASE_INSTRUCTIONS_SHA256",
    "BRIDGE_PORTS",
    "COMPOSE_SHA256",
    "CONFIG_AUTHENTICATION_SCHEMA",
    "CONFIG_SCHEMA",
    "CONTAINER_GID",
    "CONTAINER_UID",
    "DEPLOYMENT_AUTHORITY_KEY_NAME",
    "PINNED_DOCKER_HOST",
    "PROJECT_CONFIG_SCHEMA",
    "PROTECTED_ACCOUNT_I_AUTH_ROOT",
    "PROTECTED_R16_ROOT",
    "QDRANT_GRPC_PORT",
    "QDRANT_HTTP_PORT",
    "QDRANT_IMAGE",
    "RELAY_PORT",
    "RUNTIME_PIN_SHA256",
    "SOURCE_COMMIT_SHA1",
    "SOURCE_COMMIT_SHA256",
    "SOURCE_MANIFEST_SHA256",
    "BindMountAuthorityConfig",
    "DeploymentConfigError",
    "ProjectIsolationAuthority",
    "PublishableLaneConfig",
    "load_lane_config",
    "load_provider_free_project_lane_config",
    "load_runtime_lane_config",
)
