"""Strict immutable readback of host-side runtime attestations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .docker_cli import SERVICES
from .immutable_evidence import (
    ImmutableJsonEvidence,
    read_immutable_json,
    require_immutable_json_unchanged,
)
from .runtime_attestation import ATTESTATION_FILE_PREFIX, ATTESTATION_SCHEMA

_TOP_LEVEL_KEYS = {
    "account_i_fence_commitment_sha256",
    "adapter_image_id",
    "anchor_container_inventory_sha256",
    "anchor_netns",
    "anchor_pidns",
    "bridge_ports",
    "compose_sha256",
    "deployment_inputs_sha256",
    "fleet",
    "host_exposure",
    "loopback_bindings_sha256",
    "observed_at_unix_ns",
    "project_name",
    "qdrant_image_id",
    "qdrant_ports",
    "schema_version",
    "secret_cross_wire_sha256",
    "services",
}
_FLEET_KEYS = {
    "bridges",
    "fleet_readiness_sha256",
    "pool_authority_sha256",
    "requested_mode",
}
_BRIDGE_KEYS = {
    "account_name",
    "bridge_id",
    "controller_pid",
    "generation",
    "launch_mode",
    "process",
    "readiness_receipt_sha256",
    "runtime_authority_sha256",
}


class AcceptanceAttestationError(RuntimeError):
    """Stable failure for invalid lifecycle attestation evidence."""


@dataclass(frozen=True, slots=True)
class BridgeLifecycleEvidence:
    account_name: str
    bridge_id: str
    generation: int
    launch_mode: str
    runtime_authority_sha256: str

    def stable_identity(self) -> tuple[str, str, str]:
        return (
            self.account_name,
            self.bridge_id,
            self.runtime_authority_sha256,
        )


@dataclass(frozen=True, slots=True)
class RuntimeAttestationReadback:
    immutable: ImmutableJsonEvidence
    project_name: str
    fleet_mode: str
    deployment_inputs_sha256: str
    bind_mounts: tuple[tuple[str, str], ...]
    bridges: tuple[BridgeLifecycleEvidence, BridgeLifecycleEvidence, BridgeLifecycleEvidence]

    @property
    def commitment_sha256(self) -> str:
        return self.immutable.commitment_sha256

    @property
    def path(self) -> Path:
        return self.immutable.path


def read_runtime_attestation(
    *,
    path: Path,
    directory: Path,
    expected_project: str,
    expected_mode: str,
    expected_commitment: str,
) -> RuntimeAttestationReadback:
    """Validate canonical bytes plus the exact project and lifecycle mode."""

    if expected_mode not in {"create", "reopen"} or not _sha256(expected_commitment):
        _fail("publishable_acceptance_attestation_input_invalid")
    immutable = read_immutable_json(
        path=path,
        directory=directory,
        prefix=ATTESTATION_FILE_PREFIX,
    )
    if immutable.commitment_sha256 != expected_commitment:
        _fail("publishable_acceptance_attestation_commitment_mismatch")
    payload = immutable.payload
    if (
        set(payload) != _TOP_LEVEL_KEYS
        or payload.get("schema_version") != ATTESTATION_SCHEMA
        or payload.get("project_name") != expected_project
        or not _sha256(payload.get("deployment_inputs_sha256"))
    ):
        _fail("publishable_acceptance_attestation_invalid")
    services = payload.get("services")
    if type(services) is not dict or set(services) != set(SERVICES):
        _fail("publishable_acceptance_attestation_services_invalid")
    bind_mounts: list[tuple[str, str]] = []
    for service in SERVICES:
        item = services.get(service)
        if type(item) is not dict or set(item) != {
            "bind_mounts_sha256",
            "container_id",
            "image_id",
            "pid",
        }:
            _fail("publishable_acceptance_attestation_services_invalid")
        binding = item.get("bind_mounts_sha256")
        if not _sha256(binding):
            _fail("publishable_acceptance_attestation_services_invalid")
        bind_mounts.append((service, binding))
    fleet = payload.get("fleet")
    if (
        type(fleet) is not dict
        or set(fleet) != _FLEET_KEYS
        or fleet.get("requested_mode") != expected_mode
    ):
        _fail("publishable_acceptance_attestation_fleet_invalid")
    raw_bridges = fleet.get("bridges")
    if type(raw_bridges) is not list or len(raw_bridges) != 3:
        _fail("publishable_acceptance_attestation_fleet_invalid")
    bridges = tuple(_bridge(item, expected_mode=expected_mode) for item in raw_bridges)
    if (
        len({item.account_name for item in bridges}) != 3
        or len({item.bridge_id for item in bridges}) != 3
    ):
        _fail("publishable_acceptance_attestation_fleet_invalid")
    return RuntimeAttestationReadback(
        immutable=immutable,
        project_name=expected_project,
        fleet_mode=expected_mode,
        deployment_inputs_sha256=payload["deployment_inputs_sha256"],  # type: ignore[arg-type]
        bind_mounts=tuple(bind_mounts),
        bridges=bridges,  # type: ignore[arg-type]
    )


def require_runtime_attestation_unchanged(
    evidence: RuntimeAttestationReadback,
    *,
    directory: Path,
) -> RuntimeAttestationReadback:
    """Re-read a prior runtime attestation and reject replacement or mutation."""

    if type(evidence) is not RuntimeAttestationReadback:
        _fail("publishable_acceptance_attestation_input_invalid")
    require_immutable_json_unchanged(
        evidence.immutable,
        directory=directory,
        prefix=ATTESTATION_FILE_PREFIX,
    )
    observed = read_runtime_attestation(
        path=evidence.path,
        directory=directory,
        expected_project=evidence.project_name,
        expected_mode=evidence.fleet_mode,
        expected_commitment=evidence.commitment_sha256,
    )
    if observed != evidence:
        _fail("publishable_acceptance_attestation_changed")
    return observed


def _bridge(value: object, *, expected_mode: str) -> BridgeLifecycleEvidence:
    if type(value) is not dict or set(value) != _BRIDGE_KEYS:
        _fail("publishable_acceptance_attestation_bridge_invalid")
    account_name = value.get("account_name")
    bridge_id = value.get("bridge_id")
    generation = value.get("generation")
    launch_mode = value.get("launch_mode")
    authority = value.get("runtime_authority_sha256")
    if (
        not isinstance(account_name, str)
        or not account_name
        or not isinstance(bridge_id, str)
        or not bridge_id
        or type(generation) is not int
        or generation < 1
        or launch_mode != expected_mode
        or not _sha256(authority)
    ):
        _fail("publishable_acceptance_attestation_bridge_invalid")
    return BridgeLifecycleEvidence(
        account_name=account_name,
        bridge_id=bridge_id,
        generation=generation,
        launch_mode=launch_mode,
        runtime_authority_sha256=authority,
    )


def _sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fail(code: str) -> None:
    raise AcceptanceAttestationError(code)


__all__ = (
    "AcceptanceAttestationError",
    "BridgeLifecycleEvidence",
    "RuntimeAttestationReadback",
    "read_runtime_attestation",
    "require_runtime_attestation_unchanged",
)
