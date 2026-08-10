"""Fail-closed image, namespace, mount, user, and port runtime attestation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .config import (
    ADAPTER_PORT,
    BRIDGE_PORTS,
    COMPOSE_SHA256,
    CONTAINER_GID,
    CONTAINER_UID,
    QDRANT_GRPC_PORT,
    QDRANT_HTTP_PORT,
    QDRANT_IMAGE,
    RELAY_PORT,
    PublishableLaneConfig,
)
from .docker_cli import NETWORK_KEY, SERVICES, CachedImages, DockerCli
from .preflight import (
    AccountIFenceEvidence,
    DeploymentInputEvidence,
    attest_account_i_fence,
    attest_deployment_inputs,
)
from .runtime_integrity import (
    FleetRuntimeEvidence,
    RuntimeIntegrityError,
)
from .runtime_integrity import (
    attest_anchor_container_inventory as _attest_anchor_container_inventory,
)
from .runtime_integrity import (
    attest_fleet_readiness as _attest_fleet_readiness,
)
from .runtime_integrity import (
    attest_loopback_bindings as _attest_loopback_bindings,
)

ATTESTATION_SCHEMA: Final = "publishable-mem0-v5-runtime-attestation.v2"
ATTESTATION_FILE_PREFIX: Final = "runtime-attestation-"
_MAX_COMPOSE_BYTES = 512 * 1024
_BRIDGE_SERVICES: Final = (
    "publishable-bridge-a",
    "publishable-bridge-b",
    "publishable-bridge-c",
)


class RuntimeAttestationError(RuntimeError):
    """Stable failure for any difference from the reviewed runtime topology."""


@dataclass(frozen=True, slots=True)
class NamespaceIdentity:
    device: int
    inode: int

    def __post_init__(self) -> None:
        if self.device < 0 or self.inode <= 0:
            _fail("publishable_attestation_namespace_invalid")

    def payload(self) -> dict[str, int]:
        return {"device": self.device, "inode": self.inode}


@dataclass(frozen=True, slots=True)
class ServiceRuntimeIdentity:
    container_id: str
    image_id: str
    pid: int
    bind_mounts_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "bind_mounts_sha256": self.bind_mounts_sha256,
            "container_id": self.container_id,
            "image_id": self.image_id,
            "pid": self.pid,
        }


@dataclass(frozen=True, slots=True)
class LaneRuntimeAttestation:
    project_name: str
    compose_sha256: str
    observed_at_unix_ns: int
    adapter_image_id: str
    qdrant_image_id: str
    anchor_netns: NamespaceIdentity
    anchor_pidns: NamespaceIdentity
    account_i_fence_commitment_sha256: str
    secret_cross_wire_sha256: str
    deployment_inputs_sha256: str
    anchor_container_inventory_sha256: str
    loopback_bindings_sha256: str
    fleet: FleetRuntimeEvidence
    services: Mapping[str, ServiceRuntimeIdentity]
    host_adapter_port: int

    def payload(self) -> dict[str, object]:
        return {
            "account_i_fence_commitment_sha256": (self.account_i_fence_commitment_sha256),
            "adapter_image_id": self.adapter_image_id,
            "anchor_netns": self.anchor_netns.payload(),
            "anchor_pidns": self.anchor_pidns.payload(),
            "bridge_ports": list(BRIDGE_PORTS),
            "compose_sha256": self.compose_sha256,
            "deployment_inputs_sha256": self.deployment_inputs_sha256,
            "fleet": self.fleet.payload(),
            "host_exposure": {
                "container_port": RELAY_PORT,
                "host_ip": "127.0.0.1",
                "host_port": self.host_adapter_port,
                "relayed_adapter_port": ADAPTER_PORT,
            },
            "observed_at_unix_ns": self.observed_at_unix_ns,
            "project_name": self.project_name,
            "qdrant_image_id": self.qdrant_image_id,
            "qdrant_ports": {
                "grpc": QDRANT_GRPC_PORT,
                "http": QDRANT_HTTP_PORT,
            },
            "schema_version": ATTESTATION_SCHEMA,
            "secret_cross_wire_sha256": self.secret_cross_wire_sha256,
            "anchor_container_inventory_sha256": (self.anchor_container_inventory_sha256),
            "loopback_bindings_sha256": self.loopback_bindings_sha256,
            "services": {name: self.services[name].payload() for name in sorted(self.services)},
        }

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.payload())).hexdigest()


def attest_runtime_lane(
    *,
    config: PublishableLaneConfig,
    docker: DockerCli,
    cached_images: CachedImages,
    account_i_before: AccountIFenceEvidence,
    deployment_before: DeploymentInputEvidence,
    secret_cross_wire_sha256: str,
    fleet_mode: str,
    proc_root: Path = Path("/proc"),
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
) -> LaneRuntimeAttestation:
    """Attest the exact running topology and recheck all pre-start anchors."""

    if (
        type(config) is not PublishableLaneConfig
        or type(docker) is not DockerCli
        or type(cached_images) is not CachedImages
        or type(account_i_before) is not AccountIFenceEvidence
        or type(deployment_before) is not DeploymentInputEvidence
        or fleet_mode not in {"create", "reopen"}
        or not proc_root.is_absolute()
        or not _sha256(secret_cross_wire_sha256)
    ):
        _fail("publishable_attestation_input_invalid")
    deployment_now = attest_deployment_inputs(
        config,
        config_file=docker.config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if deployment_now != deployment_before:
        _fail("publishable_attestation_deployment_inputs_changed")
    compose_sha256 = attest_compose_asset(docker.compose_file)
    current_images = docker.inspect_cached_images()
    if current_images != cached_images:
        _fail("publishable_attestation_cached_image_changed")
    container_ids = docker.container_ids()
    if set(container_ids.values()) & set(config.account_i_r16_fence.container_ids):
        _fail("publishable_attestation_account_i_container_collision")
    containers = docker.inspect_containers(container_ids)
    running_containers = docker.inspect_running_containers()
    network = docker.inspect_network()
    _attest_network(network, config=config, anchor_id=container_ids[SERVICES[0]])
    expected_mounts = _mount_policy(config, docker.config_file)

    anchor_id = container_ids["publishable-relay-anchor"]
    service_identities: dict[str, ServiceRuntimeIdentity] = {}
    namespace: NamespaceIdentity | None = None
    anchor_pidns: NamespaceIdentity | None = None
    pid_namespaces: dict[str, NamespaceIdentity] = {}
    lane_pids: set[int] = set()
    for service in SERVICES:
        value = containers[service]
        identity, netns, pidns = _attest_container(
            value,
            service=service,
            config=config,
            expected_container_id=container_ids[service],
            expected_image_id=(
                cached_images.qdrant_image_id
                if service == "publishable-qdrant"
                else cached_images.adapter_image_id
            ),
            anchor_id=anchor_id,
            expected_mounts=expected_mounts[service],
            fleet_mode=fleet_mode,
            proc_root=proc_root,
        )
        if identity.pid in lane_pids or identity.pid == config.account_i_r16_fence.pid:
            _fail("publishable_attestation_process_collision")
        lane_pids.add(identity.pid)
        if namespace is None:
            namespace = netns
            anchor_pidns = pidns
        elif netns != namespace:
            _fail("publishable_attestation_netns_mismatch")
        if pidns in pid_namespaces.values():
            _fail("publishable_attestation_pidns_collision")
        pid_namespaces[service] = pidns
        service_identities[service] = identity

    assert namespace is not None and anchor_pidns is not None
    if namespace.inode == config.account_i_r16_fence.netns_inode:
        _fail("publishable_attestation_account_i_netns_collision")
    try:
        container_inventory_sha256 = _attest_anchor_container_inventory(
            running_containers,
            expected_container_ids=container_ids,
            anchor_netns=namespace,
            anchor_pidns=anchor_pidns,
            proc_root=proc_root,
        )
        loopback_bindings_sha256 = _attest_loopback_bindings(
            proc_root=proc_root,
            anchor_pid=service_identities["publishable-relay-anchor"].pid,
            host_relay_port=config.host_adapter_port,
        )
    except RuntimeIntegrityError as exc:
        raise RuntimeAttestationError(str(exc)) from exc
    docker.require_all_internal_ports(anchor_id)
    try:
        fleet = _attest_fleet_readiness(
            config,
            fleet_mode=fleet_mode,
            anchor_netns=namespace,
            bridge_pidns=tuple(pid_namespaces[name] for name in _BRIDGE_SERVICES),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except RuntimeIntegrityError as exc:
        raise RuntimeAttestationError(str(exc)) from exc
    account_i_after = attest_account_i_fence(
        config.account_i_r16_fence,
        proc_root=proc_root,
    )
    if account_i_after != account_i_before:
        _fail("publishable_attestation_account_i_changed_during_start")
    try:
        final_inventory_sha256 = _attest_anchor_container_inventory(
            docker.inspect_running_containers(),
            expected_container_ids=container_ids,
            anchor_netns=namespace,
            anchor_pidns=anchor_pidns,
            proc_root=proc_root,
        )
    except RuntimeIntegrityError as exc:
        raise RuntimeAttestationError(str(exc)) from exc
    if final_inventory_sha256 != container_inventory_sha256:
        _fail("publishable_attestation_container_inventory_changed")
    try:
        final_fleet = _attest_fleet_readiness(
            config,
            fleet_mode=fleet_mode,
            anchor_netns=namespace,
            bridge_pidns=tuple(pid_namespaces[name] for name in _BRIDGE_SERVICES),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except RuntimeIntegrityError as exc:
        raise RuntimeAttestationError(str(exc)) from exc
    if final_fleet != fleet:
        _fail("publishable_attestation_fleet_readiness_changed")
    deployment_after = attest_deployment_inputs(
        config,
        config_file=docker.config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if deployment_after != deployment_before:
        _fail("publishable_attestation_deployment_inputs_changed")
    return LaneRuntimeAttestation(
        project_name=config.project_name,
        compose_sha256=compose_sha256,
        observed_at_unix_ns=time.time_ns(),
        adapter_image_id=cached_images.adapter_image_id,
        qdrant_image_id=cached_images.qdrant_image_id,
        anchor_netns=namespace,
        anchor_pidns=anchor_pidns,
        account_i_fence_commitment_sha256=account_i_after.commitment_sha256,
        secret_cross_wire_sha256=secret_cross_wire_sha256,
        deployment_inputs_sha256=deployment_before.commitment_sha256,
        anchor_container_inventory_sha256=container_inventory_sha256,
        loopback_bindings_sha256=loopback_bindings_sha256,
        fleet=fleet,
        services=service_identities,
        host_adapter_port=config.host_adapter_port,
    )


def attest_compose_asset(path: Path) -> str:
    """Require the byte-exact reviewed Compose file before invoking Compose."""

    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
        opened = os.fstat(descriptor)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or opened.st_nlink != 1
            or opened.st_size <= 0
            or opened.st_size > _MAX_COMPOSE_BYTES
            or stat.S_IMODE(opened.st_mode) & 0o022
        ):
            _fail("publishable_attestation_compose_unsafe")
        raw = os.read(descriptor, _MAX_COMPOSE_BYTES + 1)
        final = os.fstat(descriptor)
        if len(raw) != opened.st_size or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns):
            _fail("publishable_attestation_compose_changed")
    except OSError as exc:
        raise RuntimeAttestationError("publishable_attestation_compose_unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != COMPOSE_SHA256:
        _fail("publishable_attestation_compose_digest_mismatch")
    lowered = raw.lower()
    for forbidden in (b"network_mode: host", b"build:", b"docker pull", b"ollama"):
        if forbidden in lowered:
            _fail("publishable_attestation_compose_forbidden")
    return digest


def write_runtime_attestation(
    attestation: LaneRuntimeAttestation,
    directory: Path,
) -> Path:
    """Durably create one commitment-named, secret-free attestation file."""

    if type(attestation) is not LaneRuntimeAttestation or not directory.is_absolute():
        _fail("publishable_attestation_write_input_invalid")
    _require_private_directory(directory)
    destination = directory / (f"{ATTESTATION_FILE_PREFIX}{attestation.commitment_sha256}.json")
    raw = _canonical_json(attestation.payload()) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    previous_umask = os.umask(0o077)
    descriptor: int | None = None
    try:
        descriptor = os.open(destination, flags, 0o600)
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    except FileExistsError:
        if destination.read_bytes() != raw:
            _fail("publishable_attestation_existing_file_mismatch")
    except OSError as exc:
        raise RuntimeAttestationError("publishable_attestation_write_failed") from exc
    finally:
        os.umask(previous_umask)
        if descriptor is not None:
            os.close(descriptor)
    _fsync_directory(directory)
    return destination


def _attest_network(
    value: Mapping[str, Any],
    *,
    config: PublishableLaneConfig,
    anchor_id: str,
) -> None:
    labels = _mapping(value, "Labels")
    containers = _mapping(value, "Containers")
    if (
        value.get("Name") != f"{config.project_name}_{NETWORK_KEY}"
        or value.get("Driver") != "bridge"
        or value.get("Scope") != "local"
        or value.get("Internal") is not False
        or value.get("Attachable") is not False
        or value.get("Ingress") is not False
        or value.get("ConfigOnly") is not False
        or labels.get("com.docker.compose.project") != config.project_name
        or labels.get("com.docker.compose.network") != NETWORK_KEY
        or set(containers) != {anchor_id}
    ):
        _fail("publishable_attestation_network_invalid")


def _attest_container(
    value: Mapping[str, Any],
    *,
    service: str,
    config: PublishableLaneConfig,
    expected_container_id: str,
    expected_image_id: str,
    anchor_id: str,
    expected_mounts: Mapping[str, tuple[str, bool]],
    fleet_mode: str,
    proc_root: Path,
) -> tuple[ServiceRuntimeIdentity, NamespaceIdentity, NamespaceIdentity]:
    container_config = _mapping(value, "Config")
    host = _mapping(value, "HostConfig")
    state = _mapping(value, "State")
    network = _mapping(value, "NetworkSettings")
    labels = _mapping(container_config, "Labels")
    expected_network = f"{config.project_name}_{NETWORK_KEY}"
    network_mode = host.get("NetworkMode")
    if service == "publishable-relay-anchor":
        network_valid = network_mode == expected_network
        networks_valid = set(_mapping(network, "Networks")) == {expected_network}
    else:
        network_valid = _container_mode_matches(network_mode, anchor_id)
        networks_valid = not _mapping(network, "Networks")
    pid_mode = host.get("PidMode")
    pid_mode_valid = pid_mode in (None, "")
    security = host.get("SecurityOpt")
    health = state.get("Health")
    if (
        value.get("Id") != expected_container_id
        or value.get("Image") != expected_image_id
        or labels.get("com.docker.compose.project") != config.project_name
        or labels.get("com.docker.compose.service") != service
        or labels.get("com.docker.compose.container-number") != "1"
        or state.get("Running") is not True
        or state.get("Status") != "running"
        or not isinstance(health, Mapping)
        or health.get("Status") != "healthy"
        or container_config.get("User") != f"{CONTAINER_UID}:{CONTAINER_GID}"
        or host.get("ReadonlyRootfs") is not True
        or host.get("Privileged") is not False
        or host.get("CapAdd") not in (None, [])
        or host.get("CapDrop") != ["ALL"]
        or not isinstance(security, list)
        or {item.removesuffix(":true") for item in security} != {"no-new-privileges"}
        or host.get("PublishAllPorts") is not False
        or not network_valid
        or not networks_valid
        or not pid_mode_valid
    ):
        _fail("publishable_attestation_container_invalid")
    expected_reference = (
        QDRANT_IMAGE if service == "publishable-qdrant" else config.adapter_image_id
    )
    if container_config.get("Image") != expected_reference:
        _fail("publishable_attestation_container_image_invalid")
    _attest_command_and_environment(
        container_config,
        service=service,
        config=config,
        fleet_mode=fleet_mode,
    )
    observed_mounts = _attest_mounts(value, expected_mounts)
    _attest_ports(
        host,
        network,
        service=service,
        host_adapter_port=config.host_adapter_port,
    )
    pid = state.get("Pid")
    if type(pid) is not int or pid <= 1:
        _fail("publishable_attestation_container_pid_invalid")
    netns = _namespace(proc_root / str(pid) / "ns/net")
    pidns = _namespace(proc_root / str(pid) / "ns/pid")
    return (
        ServiceRuntimeIdentity(
            container_id=expected_container_id,
            image_id=expected_image_id,
            pid=pid,
            bind_mounts_sha256=hashlib.sha256(_canonical_json(observed_mounts)).hexdigest(),
        ),
        netns,
        pidns,
    )


def _attest_command_and_environment(
    value: Mapping[str, Any],
    *,
    service: str,
    config: PublishableLaneConfig,
    fleet_mode: str,
) -> None:
    bridge_commands = {
        service: [
            "python",
            "-m",
            "publishable_mem0_v5.fleet_controller",
            "serve",
            "--mode",
            fleet_mode,
            "--account-index",
            str(index),
        ]
        for index, service in enumerate(_BRIDGE_SERVICES)
    }
    expected_commands = {
        "publishable-relay-anchor": [
            "python",
            "-m",
            "publishable_mem0_v5.relay",
            "serve",
        ],
        **bridge_commands,
        "publishable-adapter": [
            "uvicorn",
            "mem0_oss_adapter_v5.composition:build_app_from_environment",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(ADAPTER_PORT),
            "--no-access-log",
            "--no-proxy-headers",
        ],
    }
    if service in expected_commands and value.get("Cmd") != expected_commands[service]:
        _fail("publishable_attestation_command_invalid")
    environment = value.get("Env")
    if not isinstance(environment, list):
        _fail("publishable_attestation_environment_invalid")
    pairs: list[tuple[str, str]] = []
    for item in environment:
        if not isinstance(item, str) or "=" not in item:
            _fail("publishable_attestation_environment_invalid")
        pairs.append(tuple(item.split("=", 1)))
    values = dict(pairs)
    if len(values) != len(pairs) or any(
        "ollama" in f"{key}={item}".casefold() for key, item in values.items()
    ):
        _fail("publishable_attestation_environment_invalid")
    bridge_environment = {
        "PYTHONPATH": "/opt/publishable/deployment:/opt/publishable/server",
        "HOME": "/run/publishable-bridge-state/current",
        "XDG_CACHE_HOME": "/run/publishable-bridge-state/current/cache",
        "XDG_CONFIG_HOME": "/run/publishable-bridge-state/current/config",
        "XDG_DATA_HOME": "/run/publishable-bridge-state/current/data",
        "XDG_STATE_HOME": "/run/publishable-bridge-state/current/xdg-state",
    }
    required = {
        "publishable-relay-anchor": {
            "PYTHONPATH": "/opt/publishable/deployment",
        },
        "publishable-qdrant": {
            "QDRANT__SERVICE__HOST": "127.0.0.1",
            "QDRANT__SERVICE__HTTP_PORT": str(QDRANT_HTTP_PORT),
            "QDRANT__SERVICE__GRPC_PORT": str(QDRANT_GRPC_PORT),
        },
        **{service: bridge_environment for service in _BRIDGE_SERVICES},
        "publishable-adapter": {
            "MEM0_V5_QDRANT_ORIGIN": f"http://127.0.0.1:{QDRANT_HTTP_PORT}",
            "MEM0_V5_RUNTIME_TRANSPORT_ORIGIN_FILE": ("/run/secrets/runtime-transport-origin"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
    }[service]
    if any(values.get(key) != expected for key, expected in required.items()):
        _fail("publishable_attestation_environment_invalid")


def _attest_mounts(
    value: Mapping[str, Any],
    expected: Mapping[str, tuple[str, bool]],
) -> dict[str, dict[str, object]]:
    mounts = value.get("Mounts")
    if not isinstance(mounts, list):
        _fail("publishable_attestation_mounts_invalid")
    observed: dict[str, tuple[str, bool]] = {}
    tmpfs_targets: set[str] = set()
    for mount in mounts:
        if not isinstance(mount, Mapping):
            _fail("publishable_attestation_mounts_invalid")
        mount_type = mount.get("Type")
        target = mount.get("Destination")
        if mount_type == "tmpfs":
            if not isinstance(target, str):
                _fail("publishable_attestation_mounts_invalid")
            tmpfs_targets.add(target)
            continue
        source = mount.get("Source")
        writable = mount.get("RW")
        if (
            mount_type != "bind"
            or not isinstance(source, str)
            or not Path(source).is_absolute()
            or not isinstance(target, str)
            or type(writable) is not bool
            or target in observed
        ):
            _fail("publishable_attestation_mounts_invalid")
        observed[target] = (source, writable)
    if observed != expected or tmpfs_targets not in ({"/tmp"}, set()):
        _fail("publishable_attestation_mounts_invalid")
    return {
        target: {"source": source, "writable": writable}
        for target, (source, writable) in sorted(observed.items())
    }


def _attest_ports(
    host: Mapping[str, Any],
    network: Mapping[str, Any],
    *,
    service: str,
    host_adapter_port: int,
) -> None:
    host_bindings = _published_bindings(host.get("PortBindings"))
    network_bindings = _published_bindings(network.get("Ports"))
    expected = (
        {f"{RELAY_PORT}/tcp": ({"HostIp": "127.0.0.1", "HostPort": str(host_adapter_port)},)}
        if service == "publishable-relay-anchor"
        else {}
    )
    if host_bindings != expected or network_bindings != expected:
        _fail("publishable_attestation_ports_invalid")


def _published_bindings(value: object) -> dict[str, tuple[dict[str, str], ...]]:
    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        _fail("publishable_attestation_ports_invalid")
    result: dict[str, tuple[dict[str, str], ...]] = {}
    for port, bindings in value.items():
        if bindings in (None, []):
            continue
        if not isinstance(port, str) or not isinstance(bindings, list):
            _fail("publishable_attestation_ports_invalid")
        normalized: list[dict[str, str]] = []
        for binding in bindings:
            if (
                not isinstance(binding, Mapping)
                or set(binding) != {"HostIp", "HostPort"}
                or not all(isinstance(item, str) for item in binding.values())
            ):
                _fail("publishable_attestation_ports_invalid")
            normalized.append(dict(binding))
        result[port] = tuple(normalized)
    return result


def _mount_policy(
    config: PublishableLaneConfig,
    config_file: Path,
) -> dict[str, dict[str, tuple[str, bool]]]:
    paths = config.paths
    bridge_mounts = {
        service: {
            "/run/publishable-config/config.json": (str(config_file), False),
            "/run/publishable-bridge-state": (
                str(paths.fleet_state_dir / account.account_name),
                True,
            ),
            "/run/publishable-bridge-auth": (
                str(paths.fleet_auth_dir / account.account_name),
                False,
            ),
            "/opt/publishable/runtime": (str(config.runtime.runtime_root), False),
            "/opt/publishable/bin/node": (str(config.runtime.node_executable), False),
            "/opt/publishable/bin/codex": (str(config.runtime.codex_executable), False),
            "/opt/publishable/server": (str(paths.server_package_dir), False),
            "/opt/publishable/deployment": (str(paths.deployment_dir), False),
        }
        for service, account in zip(_BRIDGE_SERVICES, config.bridges, strict=True)
    }
    return {
        "publishable-relay-anchor": {
            "/opt/publishable/deployment": (str(paths.deployment_dir), False),
        },
        "publishable-qdrant": {
            "/qdrant/storage": (str(paths.qdrant_state_dir), True),
        },
        **bridge_mounts,
        "publishable-adapter": {
            "/run/mem0-v5-input": (str(paths.input_dir), False),
            "/run/mem0-v5-state": (str(paths.adapter_state_dir), True),
            "/run/secrets": (str(paths.adapter_secret_dir), False),
            "/opt/publishable/runtime": (str(config.runtime.runtime_root), False),
            "/opt/publishable/source/phase-c": (str(paths.phase_c_authority_dir), False),
            "/run/source-authority": (str(paths.source_authority_dir), False),
            "/run/source-authority-pin": (str(paths.source_authority_pin_dir), False),
            "/run/source-authority-pin/manifest.sha256": (
                str(paths.source_authority_pin_sha256_file),
                False,
            ),
            "/opt/publishable/bin/node": (str(config.runtime.node_executable), False),
        },
    }


def _container_mode_matches(value: object, anchor_id: str) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("container:")
        and value.removeprefix("container:") in {anchor_id, anchor_id[:12]}
    )


def _namespace(path: Path) -> NamespaceIdentity:
    try:
        value = path.stat()
    except OSError as exc:
        raise RuntimeAttestationError("publishable_attestation_namespace_unavailable") from exc
    return NamespaceIdentity(device=value.st_dev, inode=value.st_ino)


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    item = value.get(key)
    if not isinstance(item, Mapping):
        _fail("publishable_attestation_inspect_shape_invalid")
    return item


def _require_private_directory(path: Path) -> None:
    try:
        value = path.lstat()
    except OSError as exc:
        raise RuntimeAttestationError("publishable_attestation_directory_unavailable") from exc
    if stat.S_ISLNK(value.st_mode) or not stat.S_ISDIR(value.st_mode):
        _fail("publishable_attestation_directory_unsafe")


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(descriptor, view[offset:])
        if written <= 0:
            _fail("publishable_attestation_short_write")
        offset += written


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise RuntimeAttestationError(code)


__all__ = (
    "ATTESTATION_FILE_PREFIX",
    "ATTESTATION_SCHEMA",
    "LaneRuntimeAttestation",
    "NamespaceIdentity",
    "RuntimeAttestationError",
    "ServiceRuntimeIdentity",
    "attest_compose_asset",
    "attest_runtime_lane",
    "write_runtime_attestation",
)
