"""Application use case for starting or attesting one publishable lane."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import (
    CONTAINER_GID,
    CONTAINER_UID,
    DeploymentConfigError,
    load_lane_config,
    load_provider_free_project_lane_config,
)
from .docker_cli import CommandRunner, DockerCli
from .inventory_scope import (
    GLOBAL_INVENTORY_SCOPE,
    PROJECT_INVENTORY_SCOPE,
    InventoryScope,
    require_inventory_scope,
)
from .preflight import (
    attest_account_i_fence,
    attest_deployment_inputs,
    attest_secret_cross_wire,
    load_runtime_attestation_key,
)
from .project_runtime_attestation import (
    attest_project_runtime_lane,
    write_project_runtime_attestation,
)
from .runtime_attestation import (
    attest_compose_asset,
    attest_runtime_lane,
    write_runtime_attestation,
)


@dataclass(frozen=True, slots=True)
class DeploymentOutcome:
    attestation_file: Path
    attestation_sha256: str

    def payload(self) -> dict[str, str]:
        return {
            "attestation_file": str(self.attestation_file),
            "attestation_sha256": self.attestation_sha256,
            "outcome": "READY",
        }


def deploy(
    *,
    config_file: Path,
    fleet_mode: str,
    start: bool,
    runner: CommandRunner | None = None,
    proc_root: Path = Path("/proc"),
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
    inventory_scope: InventoryScope = GLOBAL_INVENTORY_SCOPE,
) -> DeploymentOutcome:
    """Preflight, optionally start, then attest the exact ready lane."""

    try:
        inventory_scope = require_inventory_scope(inventory_scope)
    except ValueError as exc:
        raise DeploymentConfigError(str(exc)) from exc
    if not config_file.is_absolute() or fleet_mode not in {"create", "reopen"}:
        raise DeploymentConfigError("publishable_deploy_input_invalid")
    config = (
        load_provider_free_project_lane_config(config_file)
        if inventory_scope == PROJECT_INVENTORY_SCOPE
        else load_lane_config(config_file)
    )
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        if config.project_isolation_authority is None or config.account_i_r16_fence is not None:
            raise DeploymentConfigError("publishable_deploy_scope_authority_mismatch")
    elif config.account_i_r16_fence is None or config.project_isolation_authority is not None:
        raise DeploymentConfigError("publishable_deploy_scope_authority_mismatch")
    docker = DockerCli(config, config_file=config_file, runner=runner)
    attest_compose_asset(docker.compose_file)
    deployment = attest_deployment_inputs(
        config,
        config_file=config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    account_i = (
        attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
        if inventory_scope == GLOBAL_INVENTORY_SCOPE
        else None
    )
    cross_wire = attest_secret_cross_wire(
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    attestation_key = load_runtime_attestation_key(
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    cached = docker.inspect_cached_images()
    if start:
        docker.start(mode=fleet_mode)
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        project_attestation = attest_project_runtime_lane(
            config=config,
            docker=docker,
            cached_images=cached,
            deployment_before=deployment,
            secret_cross_wire_sha256=cross_wire,
            fleet_mode=fleet_mode,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        project_receipt = write_project_runtime_attestation(
            project_attestation,
            config.paths.attestation_dir,
            authentication_key=attestation_key,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        receipt_path = project_receipt.path
        receipt_sha256 = project_receipt.commitment_sha256
    else:
        assert account_i is not None
        attestation = attest_runtime_lane(
            config=config,
            docker=docker,
            cached_images=cached,
            account_i_before=account_i,
            deployment_before=deployment,
            secret_cross_wire_sha256=cross_wire,
            fleet_mode=fleet_mode,
            proc_root=proc_root,
        )
        receipt = write_runtime_attestation(
            attestation,
            config.paths.attestation_dir,
            authentication_key=attestation_key,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        receipt_path = receipt.path
        receipt_sha256 = receipt.sha256
    return DeploymentOutcome(
        attestation_file=receipt_path,
        attestation_sha256=receipt_sha256,
    )


LaneDeployer = Callable[..., DeploymentOutcome]


__all__ = ("DeploymentOutcome", "LaneDeployer", "deploy")
