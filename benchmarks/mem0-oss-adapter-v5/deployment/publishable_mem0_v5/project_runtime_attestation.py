"""Project-scoped runtime evidence without daemon-global or host-process observation."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .acceptance_attestation import _read_runtime_authentication_key, _wipe
from .config import (
    ADAPTER_PORT,
    BRIDGE_PORTS,
    CONTAINER_GID,
    CONTAINER_UID,
    QDRANT_GRPC_PORT,
    QDRANT_HTTP_PORT,
    QDRANT_IMAGE,
    RELAY_PORT,
    PublishableLaneConfig,
)
from .docker_cli import SERVICES, CachedImages, DockerCli, ProjectInspection
from .immutable_evidence import (
    ImmutableJsonEvidence,
    read_immutable_json,
    require_immutable_json_unchanged,
    write_immutable_json,
)
from .inventory_scope import PROJECT_INVENTORY_SCOPE
from .preflight import (
    DeploymentInputEvidence,
    attest_deployment_inputs,
)
from .runtime_attestation import (
    _attest_command_and_environment,
    _attest_mounts,
    _attest_network,
    _attest_ports,
    _canonical_json,
    _mapping,
    _mount_policy,
    attest_compose_asset,
)
from .runtime_integrity import (
    ProjectFleetRuntimeEvidence,
    RuntimeIntegrityError,
    attest_project_fleet_evidence,
    attest_relay_reachability,
)

PROJECT_ATTESTATION_SCHEMA: Final = "publishable-mem0-v5-project-runtime-attestation.v2"
PROJECT_ATTESTATION_FILE_PREFIX: Final = "project-runtime-attestation-"
PROJECT_ATTESTATION_HMAC_DOMAIN: Final = b"publishable-mem0-v5/project-runtime-attestation/v2\0"
_OBSERVATION_STATUS: Final = "NOT_OBSERVED_PROJECT_SCOPE"
_FLEET_KEYS: Final = {
    "bridges",
    "fleet_evidence_sha256",
    "pool_authority_sha256",
    "requested_mode",
}
_PROJECT_BRIDGE_KEYS: Final = {
    "account_name",
    "bridge_id",
    "lifecycle_inventory_sha256",
    "runtime_authority_sha256",
}
_TOP_LEVEL_KEYS: Final = {
    "adapter_image_id",
    "attestation_hmac_sha256",
    "bridge_ports",
    "compose_sha256",
    "project_isolation_authority_sha256",
    "deployment_inputs_sha256",
    "docker_authority",
    "fleet",
    "host_exposure",
    "inventory_scope",
    "observation_limits",
    "observed_at_unix_ns",
    "project_resources",
    "qdrant_image_id",
    "qdrant_ports",
    "relay_reachability_sha256",
    "schema_version",
    "secret_cross_wire_sha256",
    "services",
}


class ProjectRuntimeAttestationError(RuntimeError):
    """Stable failure for scoped runtime evidence or immutable readback."""


@dataclass(frozen=True, slots=True)
class ProjectServiceRuntimeIdentity:
    container_id: str
    image_id: str
    bind_mounts_sha256: str

    def payload(self) -> dict[str, str]:
        return {
            "bind_mounts_sha256": self.bind_mounts_sha256,
            "container_id": self.container_id,
            "image_id": self.image_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectBridgeLifecycleEvidence:
    """Stable authority plus opaque lifecycle metadata, never inferred active state."""

    account_name: str
    bridge_id: str
    lifecycle_inventory_sha256: str
    runtime_authority_sha256: str

    def stable_identity(self) -> tuple[str, str, str]:
        return (
            self.account_name,
            self.bridge_id,
            self.runtime_authority_sha256,
        )


@dataclass(frozen=True, slots=True)
class ProjectRuntimeAttestation:
    project_name: str
    docker_host: str
    compose_sha256: str
    observed_at_unix_ns: int
    adapter_image_id: str
    qdrant_image_id: str
    project_isolation_authority_sha256: str
    secret_cross_wire_sha256: str
    deployment_inputs_sha256: str
    project_resources: Mapping[str, object]
    relay_reachability_sha256: str
    fleet: ProjectFleetRuntimeEvidence
    services: Mapping[str, ProjectServiceRuntimeIdentity]
    host_adapter_port: int

    def payload(self) -> dict[str, object]:
        return {
            "adapter_image_id": self.adapter_image_id,
            "bridge_ports": list(BRIDGE_PORTS),
            "compose_sha256": self.compose_sha256,
            "project_isolation_authority_sha256": self.project_isolation_authority_sha256,
            "deployment_inputs_sha256": self.deployment_inputs_sha256,
            "docker_authority": {
                "docker_host": self.docker_host,
                "project_name": self.project_name,
            },
            "fleet": self.fleet.payload(),
            "host_exposure": {
                "container_port": RELAY_PORT,
                "host_ip": "127.0.0.1",
                "host_port": self.host_adapter_port,
                "relayed_adapter_port": ADAPTER_PORT,
            },
            "inventory_scope": PROJECT_INVENTORY_SCOPE,
            "observation_limits": {
                "daemon_global_container_inventory": _OBSERVATION_STATUS,
                "host_process_identities": _OBSERVATION_STATUS,
            },
            "observed_at_unix_ns": self.observed_at_unix_ns,
            "project_resources": dict(self.project_resources),
            "qdrant_image_id": self.qdrant_image_id,
            "qdrant_ports": {"grpc": QDRANT_GRPC_PORT, "http": QDRANT_HTTP_PORT},
            "relay_reachability_sha256": self.relay_reachability_sha256,
            "schema_version": PROJECT_ATTESTATION_SCHEMA,
            "secret_cross_wire_sha256": self.secret_cross_wire_sha256,
            "services": {name: self.services[name].payload() for name in sorted(self.services)},
        }


@dataclass(frozen=True, slots=True)
class ProjectRuntimeAttestationReadback:
    immutable: ImmutableJsonEvidence
    project_name: str
    fleet_mode: str
    deployment_inputs_sha256: str
    project_isolation_authority_sha256: str
    bind_mounts: tuple[tuple[str, str], ...]
    bridges: tuple[
        ProjectBridgeLifecycleEvidence,
        ProjectBridgeLifecycleEvidence,
        ProjectBridgeLifecycleEvidence,
    ]

    @property
    def commitment_sha256(self) -> str:
        return self.immutable.commitment_sha256

    @property
    def path(self) -> Path:
        return self.immutable.path


def attest_project_runtime_lane(
    *,
    config: PublishableLaneConfig,
    docker: DockerCli,
    cached_images: CachedImages,
    deployment_before: DeploymentInputEvidence,
    secret_cross_wire_sha256: str,
    fleet_mode: str,
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
) -> ProjectRuntimeAttestation:
    """Attest only exact Compose resources and authenticated project-local state."""

    if (
        type(config) is not PublishableLaneConfig
        or type(docker) is not DockerCli
        or type(cached_images) is not CachedImages
        or type(deployment_before) is not DeploymentInputEvidence
        or fleet_mode not in {"create", "reopen"}
        or not _sha256(secret_cross_wire_sha256)
    ):
        _fail("publishable_project_attestation_input_invalid")
    _require_deployment_unchanged(
        config,
        docker=docker,
        expected=deployment_before,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    compose_sha256 = attest_compose_asset(docker.compose_file)
    if docker.inspect_cached_images() != cached_images:
        _fail("publishable_project_attestation_cached_image_changed")

    first = docker.inspect_project(mode=fleet_mode)
    authority = config.project_isolation_authority
    if authority is None:
        _fail("publishable_project_attestation_project_authority_required")
    services = _attest_project_inspection(
        first,
        config=config,
        docker=docker,
        cached_images=cached_images,
        fleet_mode=fleet_mode,
    )
    docker.require_all_internal_ports(first.container_ids["publishable-relay-anchor"])
    try:
        fleet = attest_project_fleet_evidence(
            config,
            fleet_mode=fleet_mode,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        relay_sha256 = attest_relay_reachability(host_relay_port=config.host_adapter_port)
        final_fleet = attest_project_fleet_evidence(
            config,
            fleet_mode=fleet_mode,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    except RuntimeIntegrityError as exc:
        raise ProjectRuntimeAttestationError(str(exc)) from exc
    if final_fleet != fleet:
        _fail("publishable_project_attestation_fleet_changed")
    if type(fleet) is not ProjectFleetRuntimeEvidence:
        _fail("publishable_project_attestation_fleet_invalid")

    final = docker.inspect_project(mode=fleet_mode)
    final_services = _attest_project_inspection(
        final,
        config=config,
        docker=docker,
        cached_images=cached_images,
        fleet_mode=fleet_mode,
    )
    if _project_resources(final) != _project_resources(first) or final_services != services:
        _fail("publishable_project_attestation_inventory_changed")
    if docker.inspect_cached_images() != cached_images:
        _fail("publishable_project_attestation_cached_image_changed")
    _require_deployment_unchanged(
        config,
        docker=docker,
        expected=deployment_before,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return ProjectRuntimeAttestation(
        project_name=config.project_name,
        docker_host=config.docker_host,
        compose_sha256=compose_sha256,
        observed_at_unix_ns=time.time_ns(),
        adapter_image_id=cached_images.adapter_image_id,
        qdrant_image_id=cached_images.qdrant_image_id,
        project_isolation_authority_sha256=authority.commitment_sha256,
        secret_cross_wire_sha256=secret_cross_wire_sha256,
        deployment_inputs_sha256=deployment_before.commitment_sha256,
        project_resources=_project_resources(first),
        relay_reachability_sha256=relay_sha256,
        fleet=fleet,
        services=services,
        host_adapter_port=config.host_adapter_port,
    )


def write_project_runtime_attestation(
    attestation: ProjectRuntimeAttestation,
    directory: Path,
    *,
    authentication_key: bytes,
) -> ImmutableJsonEvidence:
    """Authenticate and durably create a scope-distinct project receipt."""

    if (
        type(attestation) is not ProjectRuntimeAttestation
        or not directory.is_absolute()
        or type(authentication_key) is not bytes
        or not 32 <= len(authentication_key) <= 4096
    ):
        _fail("publishable_project_attestation_write_input_invalid")
    try:
        key_text = authentication_key.decode("utf-8")
    except UnicodeDecodeError:
        _fail("publishable_project_attestation_write_input_invalid")
    if not key_text or key_text != key_text.strip():
        _fail("publishable_project_attestation_write_input_invalid")
    unsigned = attestation.payload()
    authentication = hmac.new(
        authentication_key,
        PROJECT_ATTESTATION_HMAC_DOMAIN + _canonical_json(unsigned),
        hashlib.sha256,
    ).hexdigest()
    return write_immutable_json(
        directory=directory,
        prefix=PROJECT_ATTESTATION_FILE_PREFIX,
        payload={**unsigned, "attestation_hmac_sha256": authentication},
    )


def read_project_runtime_attestation(
    *,
    path: Path,
    directory: Path,
    authentication_key_file: Path,
    expected_project: str,
    expected_docker_host: str,
    expected_mode: str,
    expected_commitment: str,
    expected_project_isolation_authority_sha256: str,
    expected_uid: int,
    expected_gid: int,
) -> ProjectRuntimeAttestationReadback:
    """Authenticate exact scoped authority, resources, project, and lifecycle mode."""

    if (
        expected_mode not in {"create", "reopen"}
        or not _sha256(expected_commitment)
        or not _sha256(expected_project_isolation_authority_sha256)
    ):
        _fail("publishable_project_attestation_read_input_invalid")
    immutable = read_immutable_json(
        path=path,
        directory=directory,
        prefix=PROJECT_ATTESTATION_FILE_PREFIX,
    )
    if immutable.commitment_sha256 != expected_commitment:
        _fail("publishable_project_attestation_commitment_mismatch")
    payload = immutable.payload
    if (
        set(payload) != _TOP_LEVEL_KEYS
        or payload.get("schema_version") != PROJECT_ATTESTATION_SCHEMA
        or payload.get("inventory_scope") != PROJECT_INVENTORY_SCOPE
        or payload.get("docker_authority")
        != {"docker_host": expected_docker_host, "project_name": expected_project}
        or payload.get("observation_limits")
        != {
            "daemon_global_container_inventory": _OBSERVATION_STATUS,
            "host_process_identities": _OBSERVATION_STATUS,
        }
        or not all(
            _sha256(payload.get(key))
            for key in (
                "attestation_hmac_sha256",
                "project_isolation_authority_sha256",
                "deployment_inputs_sha256",
                "relay_reachability_sha256",
                "secret_cross_wire_sha256",
            )
        )
    ):
        _fail("publishable_project_attestation_invalid")
    _authenticate_payload(
        payload,
        authentication_key_file=authentication_key_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    observed_authority = str(payload["project_isolation_authority_sha256"])
    if not hmac.compare_digest(
        observed_authority, expected_project_isolation_authority_sha256
    ):
        _fail("publishable_project_attestation_isolation_authority_mismatch")
    services = _services(payload.get("services"))
    resources = payload.get("project_resources")
    expected_ids = {name: services[name]["container_id"] for name in SERVICES}
    if resources != {
        "containers": expected_ids,
        "network_id": _resource_network_id(resources),
        "volumes": [],
    }:
        _fail("publishable_project_attestation_resources_invalid")
    fleet = payload.get("fleet")
    pool_authority_sha256: object = None
    fleet_evidence_sha256: object = None
    if (
        type(fleet) is not dict
        or set(fleet) != _FLEET_KEYS
        or fleet.get("requested_mode") != expected_mode
        or not _sha256(pool_authority_sha256 := fleet.get("pool_authority_sha256"))
        or not _sha256(fleet_evidence_sha256 := fleet.get("fleet_evidence_sha256"))
    ):
        _fail("publishable_project_attestation_fleet_invalid")
    raw_bridges = fleet.get("bridges")
    if type(raw_bridges) is not list or len(raw_bridges) != 3:
        _fail("publishable_project_attestation_fleet_invalid")
    bridges = tuple(_project_bridge(item) for item in raw_bridges)
    if (
        len({item.account_name for item in bridges}) != 3
        or len({item.bridge_id for item in bridges}) != 3
        or len({item.runtime_authority_sha256 for item in bridges}) != 3
        or len({item.lifecycle_inventory_sha256 for item in bridges}) != 3
    ):
        _fail("publishable_project_attestation_fleet_invalid")
    expected_fleet_evidence_sha256 = hashlib.sha256(
        _canonical_json(
            {
                "bridges": raw_bridges,
                "pool_authority_sha256": pool_authority_sha256,
                "requested_mode": expected_mode,
            }
        )
    ).hexdigest()
    if not hmac.compare_digest(str(fleet_evidence_sha256), expected_fleet_evidence_sha256):
        _fail("publishable_project_attestation_fleet_invalid")
    return ProjectRuntimeAttestationReadback(
        immutable=immutable,
        project_name=expected_project,
        fleet_mode=expected_mode,
        deployment_inputs_sha256=str(payload["deployment_inputs_sha256"]),
        project_isolation_authority_sha256=observed_authority,
        bind_mounts=tuple((name, str(services[name]["bind_mounts_sha256"])) for name in SERVICES),
        bridges=bridges,  # type: ignore[arg-type]
    )


def require_project_runtime_attestation_unchanged(
    evidence: ProjectRuntimeAttestationReadback,
    *,
    directory: Path,
    authentication_key_file: Path,
    expected_docker_host: str,
    expected_uid: int,
    expected_gid: int,
) -> ProjectRuntimeAttestationReadback:
    """Re-read one scoped receipt and reject replacement or authority drift."""

    if type(evidence) is not ProjectRuntimeAttestationReadback:
        _fail("publishable_project_attestation_read_input_invalid")
    require_immutable_json_unchanged(
        evidence.immutable,
        directory=directory,
        prefix=PROJECT_ATTESTATION_FILE_PREFIX,
    )
    observed = read_project_runtime_attestation(
        path=evidence.path,
        directory=directory,
        authentication_key_file=authentication_key_file,
        expected_project=evidence.project_name,
        expected_docker_host=expected_docker_host,
        expected_mode=evidence.fleet_mode,
        expected_commitment=evidence.commitment_sha256,
        expected_project_isolation_authority_sha256=(
            evidence.project_isolation_authority_sha256
        ),
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if observed != evidence:
        _fail("publishable_project_attestation_changed")
    return observed


def _attest_project_inspection(
    inspection: ProjectInspection,
    *,
    config: PublishableLaneConfig,
    docker: DockerCli,
    cached_images: CachedImages,
    fleet_mode: str,
) -> dict[str, ProjectServiceRuntimeIdentity]:
    if inspection.project_name != config.project_name:
        _fail("publishable_project_attestation_project_mismatch")
    anchor_id = inspection.container_ids["publishable-relay-anchor"]
    _attest_network(inspection.network, config=config, anchor_id=anchor_id)
    expected_mounts = _mount_policy(config, docker.config_file)
    result: dict[str, ProjectServiceRuntimeIdentity] = {}
    for service in SERVICES:
        value = inspection.containers[service]
        container_config = _mapping(value, "Config")
        host = _mapping(value, "HostConfig")
        state = _mapping(value, "State")
        network = _mapping(value, "NetworkSettings")
        labels = _mapping(container_config, "Labels")
        expected_network = docker.network_name
        network_mode = host.get("NetworkMode")
        network_valid = (
            network_mode == expected_network
            if service == "publishable-relay-anchor"
            else network_mode == f"container:{anchor_id}"
        )
        networks_valid = (
            set(_mapping(network, "Networks")) == {expected_network}
            if service == "publishable-relay-anchor"
            else not _mapping(network, "Networks")
        )
        health = state.get("Health")
        security = host.get("SecurityOpt")
        expected_image_id = (
            cached_images.qdrant_image_id
            if service == "publishable-qdrant"
            else cached_images.adapter_image_id
        )
        if (
            value.get("Id") != inspection.container_ids[service]
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
            or any(type(item) is not str for item in security)
            or {item.removesuffix(":true") for item in security} != {"no-new-privileges"}
            or host.get("PublishAllPorts") is not False
            or not network_valid
            or not networks_valid
            or host.get("PidMode") not in (None, "")
        ):
            _fail("publishable_project_attestation_container_invalid")
        expected_reference = (
            QDRANT_IMAGE if service == "publishable-qdrant" else config.adapter_image_id
        )
        if container_config.get("Image") != expected_reference:
            _fail("publishable_project_attestation_container_image_invalid")
        _attest_command_and_environment(
            container_config,
            service=service,
            config=config,
            fleet_mode=fleet_mode,
        )
        observed_mounts = _attest_mounts(value, expected_mounts[service])
        _attest_ports(
            host,
            network,
            service=service,
            host_adapter_port=config.host_adapter_port,
        )
        result[service] = ProjectServiceRuntimeIdentity(
            container_id=inspection.container_ids[service],
            image_id=expected_image_id,
            bind_mounts_sha256=hashlib.sha256(_canonical_json(observed_mounts)).hexdigest(),
        )
    return result


def _project_resources(inspection: ProjectInspection) -> dict[str, object]:
    return {
        "containers": {name: inspection.container_ids[name] for name in SERVICES},
        "network_id": inspection.network_id,
        "volumes": [],
    }


def _require_deployment_unchanged(
    config: PublishableLaneConfig,
    *,
    docker: DockerCli,
    expected: DeploymentInputEvidence,
    expected_uid: int,
    expected_gid: int,
) -> None:
    observed = attest_deployment_inputs(
        config,
        config_file=docker.config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if observed != expected:
        _fail("publishable_project_attestation_deployment_inputs_changed")


def _authenticate_payload(
    payload: dict[str, object],
    *,
    authentication_key_file: Path,
    expected_uid: int,
    expected_gid: int,
) -> None:
    signed = dict(payload)
    presented = signed.pop("attestation_hmac_sha256")
    key = _read_runtime_authentication_key(
        authentication_key_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    try:
        expected = hmac.new(
            key,
            PROJECT_ATTESTATION_HMAC_DOMAIN + _canonical_json(signed),
            hashlib.sha256,
        ).hexdigest()
        if not isinstance(presented, str) or not hmac.compare_digest(expected, presented):
            _fail("publishable_project_attestation_authentication_invalid")
    finally:
        _wipe(key)


def _services(value: object) -> dict[str, dict[str, object]]:
    if type(value) is not dict or set(value) != set(SERVICES):
        _fail("publishable_project_attestation_services_invalid")
    result: dict[str, dict[str, object]] = {}
    identifiers: set[str] = set()
    for service in SERVICES:
        item = value.get(service)
        if type(item) is not dict or set(item) != {
            "bind_mounts_sha256",
            "container_id",
            "image_id",
        }:
            _fail("publishable_project_attestation_services_invalid")
        identifier = item.get("container_id")
        if (
            not _sha256(item.get("bind_mounts_sha256"))
            or not _container_id(identifier)
            or not isinstance(item.get("image_id"), str)
            or identifier in identifiers
        ):
            _fail("publishable_project_attestation_services_invalid")
        identifiers.add(identifier)
        result[service] = item
    return result


def _project_bridge(value: object) -> ProjectBridgeLifecycleEvidence:
    if type(value) is not dict or set(value) != _PROJECT_BRIDGE_KEYS:
        _fail("publishable_project_attestation_bridge_invalid")
    account_name = value.get("account_name")
    bridge_id = value.get("bridge_id")
    runtime_authority = value.get("runtime_authority_sha256")
    lifecycle_inventory = value.get("lifecycle_inventory_sha256")
    if (
        type(account_name) is not str
        or not account_name
        or type(bridge_id) is not str
        or not bridge_id
        or not _sha256(runtime_authority)
        or not _sha256(lifecycle_inventory)
    ):
        _fail("publishable_project_attestation_bridge_invalid")
    return ProjectBridgeLifecycleEvidence(
        account_name=account_name,
        bridge_id=bridge_id,
        lifecycle_inventory_sha256=lifecycle_inventory,
        runtime_authority_sha256=runtime_authority,
    )


def _resource_network_id(value: object) -> str:
    if type(value) is not dict or set(value) != {"containers", "network_id", "volumes"}:
        _fail("publishable_project_attestation_resources_invalid")
    network_id = value.get("network_id")
    if not _container_id(network_id):
        _fail("publishable_project_attestation_resources_invalid")
    return network_id


def _container_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256(value: object) -> bool:
    return _container_id(value)


def _fail(code: str) -> None:
    raise ProjectRuntimeAttestationError(code)


__all__ = (
    "PROJECT_ATTESTATION_FILE_PREFIX",
    "PROJECT_ATTESTATION_HMAC_DOMAIN",
    "PROJECT_ATTESTATION_SCHEMA",
    "ProjectBridgeLifecycleEvidence",
    "ProjectRuntimeAttestation",
    "ProjectRuntimeAttestationError",
    "ProjectRuntimeAttestationReadback",
    "ProjectServiceRuntimeIdentity",
    "attest_project_runtime_lane",
    "read_project_runtime_attestation",
    "require_project_runtime_attestation_unchanged",
    "write_project_runtime_attestation",
)
