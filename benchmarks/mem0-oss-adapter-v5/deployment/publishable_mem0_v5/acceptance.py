"""Authoritative provider-free Docker lifecycle acceptance use case."""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final

from .acceptance_attestation import (
    RuntimeAttestationReadback,
    read_runtime_attestation,
    require_runtime_attestation_unchanged,
)
from .acceptance_identity import (
    ACCEPTANCE_DRIVER_IDENTITY_KIND,
    AcceptanceDriverIdentity,
    attest_acceptance_driver,
    require_acceptance_driver_unchanged,
)
from .config import (
    CONTAINER_GID,
    CONTAINER_UID,
    PINNED_DOCKER_HOST,
    PublishableLaneConfig,
    load_lane_config,
    load_provider_free_project_lane_config,
)
from .deployment import DeploymentOutcome, LaneDeployer, deploy
from .docker_cli import (
    CommandRunner,
    DockerCli,
    ProjectResourceObservation,
    ProjectResources,
)
from .immutable_evidence import write_immutable_json
from .inventory_scope import (
    GLOBAL_INVENTORY_SCOPE,
    PROJECT_INVENTORY_SCOPE,
    InventoryScope,
    require_inventory_scope,
)
from .preflight import DeploymentInputEvidence, attest_deployment_inputs
from .project_runtime_attestation import (
    ProjectRuntimeAttestationReadback,
    read_project_runtime_attestation,
    require_project_runtime_attestation_unchanged,
)
from .provider_attestation import (
    ProviderAttestationEvidence,
    ProviderFreeRuntimeAttestor,
    ProviderFreeRuntimeProbe,
)
from .runtime_attestation import attest_compose_asset

ACCEPTANCE_SCHEMA: Final = "publishable-mem0-v5-docker-acceptance.v2"
ACCEPTANCE_FILE_PREFIX: Final = "docker-acceptance-"
CLEAN_STATE_STATUS: Final = "NOT_RUN_REQUIRES_AUTHORITATIVE_RUN_ADMISSION"
DeploymentInputAttestor = Callable[..., DeploymentInputEvidence]
AcceptanceRuntimeReadback = RuntimeAttestationReadback | ProjectRuntimeAttestationReadback
_LIFECYCLE = (
    "create",
    "attest-create",
    "provider-free-attest-create",
    "controlled-stop-preserve-state",
    "reopen",
    "attest-reopen",
    "provider-free-attest-reopen",
    "exact-project-teardown",
    "zero-project-resource-verification",
)


class DockerAcceptanceError(RuntimeError):
    """Stable failure for lifecycle orchestration or cleanup verification."""


@dataclass(frozen=True, slots=True)
class StateDirectoryIdentity:
    path: str
    device: int
    inode: int
    uid: int
    gid: int
    mode: int

    def payload(self) -> dict[str, object]:
        return {
            "device": self.device,
            "gid": self.gid,
            "inode": self.inode,
            "mode": self.mode,
            "path": self.path,
            "uid": self.uid,
        }


@dataclass(frozen=True, slots=True)
class StateDirectorySnapshot:
    directories: tuple[StateDirectoryIdentity, ...]

    @property
    def commitment_sha256(self) -> str:
        return hashlib.sha256(
            _canonical_json({"directories": [item.payload() for item in self.directories]})
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class DockerAcceptanceOutcome:
    acceptance_file: Path
    acceptance_sha256: str
    project_name: str
    create_attestation_sha256: str
    reopen_attestation_sha256: str
    package_closure_sha256: str
    deployment_closure_sha256: str
    deployment_closure_hmac_sha256: str
    deployment_inputs_sha256: str
    adapter_source_commit_sha1: str
    adapter_source_tree_sha1: str
    phase_c_infinity_commit_sha1: str
    inventory_scope: InventoryScope = GLOBAL_INVENTORY_SCOPE
    docker_host: str = PINNED_DOCKER_HOST

    def payload(self) -> dict[str, object]:
        return {
            "acceptance_file": str(self.acceptance_file),
            "acceptance_sha256": self.acceptance_sha256,
            "authenticated_empty_state": {
                "reason": "requires authoritative run admission and durable run-bound proof",
                "status": CLEAN_STATE_STATUS,
            },
            "cleanup": {"containers": 0, "networks": 0, "volumes": 0},
            "create_attestation_sha256": self.create_attestation_sha256,
            "docker_inventory": _docker_inventory_payload(
                docker_host=self.docker_host,
                project_name=self.project_name,
                inventory_scope=self.inventory_scope,
            ),
            "deployment_authority": {
                "deployment_closure_hmac_sha256": self.deployment_closure_hmac_sha256,
                "deployment_closure_sha256": self.deployment_closure_sha256,
                "deployment_inputs_sha256": self.deployment_inputs_sha256,
            },
            "outcome": "ACCEPTED_PROVIDER_FREE",
            "phase_c_infinity_commit_sha1": self.phase_c_infinity_commit_sha1,
            "project_name": self.project_name,
            "provider_call_verification": _provider_call_verification(),
            "reopen_attestation_sha256": self.reopen_attestation_sha256,
            "acceptance_driver": {
                "git_commit": {"status": "NOT_EMBEDDED_IN_INSTALLED_ARTIFACT"},
                "identity_kind": ACCEPTANCE_DRIVER_IDENTITY_KIND,
                "package_closure_sha256": self.package_closure_sha256,
            },
            "adapter_source_commit_sha1": self.adapter_source_commit_sha1,
            "adapter_source_tree_sha1": self.adapter_source_tree_sha1,
        }


def run_docker_acceptance(
    *,
    config_file: Path,
    runner: CommandRunner | None = None,
    proc_root: Path = Path("/proc"),
    expected_uid: int = CONTAINER_UID,
    expected_gid: int = CONTAINER_GID,
    lane_deployer: LaneDeployer = deploy,
    runtime_probe: ProviderFreeRuntimeProbe | None = None,
    deployment_attestor: DeploymentInputAttestor = attest_deployment_inputs,
    inventory_scope: InventoryScope = GLOBAL_INVENTORY_SCOPE,
    expected_project_name: str | None = None,
    expected_docker_host: str | None = None,
) -> DockerAcceptanceOutcome:
    """Create, attest, stop, reopen, re-attest, and exactly clean one project."""

    try:
        inventory_scope = require_inventory_scope(inventory_scope)
    except ValueError as exc:
        raise DockerAcceptanceError(str(exc)) from exc
    if (
        not config_file.is_absolute()
        or not proc_root.is_absolute()
        or not callable(lane_deployer)
        or not callable(deployment_attestor)
    ):
        _fail("publishable_acceptance_input_invalid")
    config = (
        load_provider_free_project_lane_config(config_file)
        if inventory_scope == PROJECT_INVENTORY_SCOPE
        else load_lane_config(config_file)
    )
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        if config.project_isolation_authority is None or config.account_i_r16_fence is not None:
            _fail("publishable_acceptance_scope_authority_mismatch")
    elif config.account_i_r16_fence is None or config.project_isolation_authority is not None:
        _fail("publishable_acceptance_scope_authority_mismatch")
    _require_inventory_authority(
        config,
        inventory_scope=inventory_scope,
        expected_project_name=expected_project_name,
        expected_docker_host=expected_docker_host,
    )
    authentication_key_file = config.paths.adapter_secret_dir / "runtime-attestation-secret"
    driver = attest_acceptance_driver(config)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    attest_compose_asset(docker.compose_file)
    deployment_before = deployment_attestor(
        config,
        config_file=config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    state_before = _state_snapshot(
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    project_observations: list[ProjectResourceObservation] = []
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        initial_observation = docker.observe_project_resources()
        project_observations.append(initial_observation)
        initial = ProjectResources(
            containers=initial_observation.containers,
            networks=initial_observation.networks,
            volumes=initial_observation.volumes,
        )
    else:
        initial = docker.project_resources()
    if not initial.empty:
        _fail("publishable_acceptance_project_not_empty")
    probe = runtime_probe or ProviderFreeRuntimeAttestor(
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )

    cleanup_armed = False
    cleanup_mode = "create"
    primary_failure: BaseException | None = None
    primary_traceback: TracebackType | None = None
    cleanup_failure: BaseException | None = None
    cleanup: ProjectResources | None = None
    create: AcceptanceRuntimeReadback | None = None
    reopen: AcceptanceRuntimeReadback | None = None
    create_provider: ProviderAttestationEvidence | None = None
    reopen_provider: ProviderAttestationEvidence | None = None
    try:
        cleanup_armed = True
        create_outcome = _deploy_lane(
            lane_deployer,
            config_file=config_file,
            fleet_mode="create",
            runner=runner,
            proc_root=proc_root,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            inventory_scope=inventory_scope,
        )
        if inventory_scope == PROJECT_INVENTORY_SCOPE:
            project_observations.append(docker.inspect_project(mode="create").resources)
        create = _read_runtime_attestation(
            inventory_scope=inventory_scope,
            path=create_outcome.attestation_file,
            directory=config.paths.attestation_dir,
            authentication_key_file=authentication_key_file,
            expected_project=config.project_name,
            expected_docker_host=config.docker_host,
            expected_mode="create",
            expected_commitment=create_outcome.attestation_sha256,
            expected_project_isolation_authority_sha256=(
                config.project_isolation_authority.commitment_sha256
                if config.project_isolation_authority is not None else None
            ),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _require_deployment_inputs(create, deployment_before)
        create_provider = probe.attest(
            fleet_mode="create",
            runtime_attestation_sha256=create.commitment_sha256,
        )
        docker.stop(mode="create")
        if inventory_scope == PROJECT_INVENTORY_SCOPE:
            docker.require_project_stopped(mode="create")
        else:
            docker.require_stopped(mode="create")
        _require_state_unchanged(
            state_before,
            config,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _require_runtime_attestation_unchanged(
            create,
            inventory_scope=inventory_scope,
            directory=config.paths.attestation_dir,
            authentication_key_file=authentication_key_file,
            expected_docker_host=config.docker_host,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        probe.require_unchanged(create_provider)
        require_acceptance_driver_unchanged(driver, config)
        _require_deployment_inputs_current(
            deployment_before,
            config=config,
            config_file=config_file,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            deployment_attestor=deployment_attestor,
        )

        cleanup_mode = "reopen"
        reopen_outcome = _deploy_lane(
            lane_deployer,
            config_file=config_file,
            fleet_mode="reopen",
            runner=runner,
            proc_root=proc_root,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            inventory_scope=inventory_scope,
        )
        if inventory_scope == PROJECT_INVENTORY_SCOPE:
            project_observations.append(docker.inspect_project(mode="reopen").resources)
        reopen = _read_runtime_attestation(
            inventory_scope=inventory_scope,
            path=reopen_outcome.attestation_file,
            directory=config.paths.attestation_dir,
            authentication_key_file=authentication_key_file,
            expected_project=config.project_name,
            expected_docker_host=config.docker_host,
            expected_mode="reopen",
            expected_commitment=reopen_outcome.attestation_sha256,
            expected_project_isolation_authority_sha256=(
                config.project_isolation_authority.commitment_sha256
                if config.project_isolation_authority is not None else None
            ),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        reopen_provider = probe.attest(
            fleet_mode="reopen",
            runtime_attestation_sha256=reopen.commitment_sha256,
        )
        _require_lifecycle_transition(create, reopen, create_provider, reopen_provider)
        _require_state_unchanged(
            state_before,
            config,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _require_runtime_attestation_unchanged(
            create,
            inventory_scope=inventory_scope,
            directory=config.paths.attestation_dir,
            authentication_key_file=authentication_key_file,
            expected_docker_host=config.docker_host,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        _require_runtime_attestation_unchanged(
            reopen,
            inventory_scope=inventory_scope,
            directory=config.paths.attestation_dir,
            authentication_key_file=authentication_key_file,
            expected_docker_host=config.docker_host,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        probe.require_unchanged(create_provider)
        probe.require_unchanged(reopen_provider)
    except BaseException as exc:
        primary_failure = exc
        primary_traceback = exc.__traceback__
    finally:
        if cleanup_armed:
            cleanup_failure, cleanup = _cleanup_exact_project(
                docker,
                mode=cleanup_mode,
                inventory_scope=inventory_scope,
                project_observations=tuple(project_observations),
            )

    if cleanup_failure is not None:
        failure = DockerAcceptanceError("publishable_acceptance_cleanup_failed")
        if primary_failure is not None:
            failure.add_note(f"primary_failure_type={type(primary_failure).__name__}")
        raise failure from cleanup_failure
    if primary_failure is not None:
        raise primary_failure.with_traceback(primary_traceback)
    if (
        cleanup is None
        or not cleanup.empty
        or create is None
        or reopen is None
        or create_provider is None
        or reopen_provider is None
    ):
        _fail("publishable_acceptance_incomplete")

    _require_state_unchanged(
        state_before,
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _require_runtime_attestation_unchanged(
        create,
        inventory_scope=inventory_scope,
        directory=config.paths.attestation_dir,
        authentication_key_file=authentication_key_file,
        expected_docker_host=config.docker_host,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    _require_runtime_attestation_unchanged(
        reopen,
        inventory_scope=inventory_scope,
        directory=config.paths.attestation_dir,
        authentication_key_file=authentication_key_file,
        expected_docker_host=config.docker_host,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    probe.require_unchanged(create_provider)
    probe.require_unchanged(reopen_provider)
    require_acceptance_driver_unchanged(driver, config)
    _require_deployment_inputs_current(
        deployment_before,
        config=config,
        config_file=config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        deployment_attestor=deployment_attestor,
    )
    report = write_immutable_json(
        directory=config.paths.attestation_dir,
        prefix=ACCEPTANCE_FILE_PREFIX,
        payload=_acceptance_payload(
            config=config,
            driver=driver,
            state=state_before,
            cleanup=cleanup,
            create=create,
            reopen=reopen,
            create_provider=create_provider,
            reopen_provider=reopen_provider,
            inventory_scope=inventory_scope,
        ),
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    return DockerAcceptanceOutcome(
        acceptance_file=report.path,
        acceptance_sha256=report.commitment_sha256,
        project_name=config.project_name,
        create_attestation_sha256=create.commitment_sha256,
        reopen_attestation_sha256=reopen.commitment_sha256,
        package_closure_sha256=driver.package_closure_sha256,
        deployment_closure_sha256=driver.deployment_closure_sha256,
        deployment_closure_hmac_sha256=driver.deployment_closure_hmac_sha256,
        deployment_inputs_sha256=create.deployment_inputs_sha256,
        adapter_source_commit_sha1=create_provider.source_commit_sha1,
        adapter_source_tree_sha1=create_provider.source_tree_sha1,
        phase_c_infinity_commit_sha1=create_provider.phase_c_infinity_commit_sha1,
        inventory_scope=inventory_scope,
        docker_host=config.docker_host,
    )


def _cleanup_exact_project(
    docker: DockerCli,
    *,
    mode: str,
    inventory_scope: InventoryScope,
    project_observations: tuple[ProjectResourceObservation, ...],
) -> tuple[BaseException | None, ProjectResources | None]:
    failures: list[BaseException] = []
    exact_observations = list(project_observations)
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        try:
            exact_observations.append(docker.observe_project_resources())
        except BaseException as exc:
            failures.append(exc)
    try:
        docker.teardown(mode=mode)
    except BaseException as exc:
        failures.append(exc)
    resources: ProjectResources | None = None
    try:
        if inventory_scope == PROJECT_INVENTORY_SCOPE and exact_observations:
            resources = docker.require_project_absent(*exact_observations)
        else:
            resources = docker.project_resources()
            if not resources.empty:
                failures.append(DockerAcceptanceError("publishable_acceptance_cleanup_incomplete"))
    except BaseException as exc:
        failures.append(exc)
    return (failures[0] if failures else None, resources)


def _require_lifecycle_transition(
    create: AcceptanceRuntimeReadback,
    reopen: AcceptanceRuntimeReadback,
    create_provider: ProviderAttestationEvidence,
    reopen_provider: ProviderAttestationEvidence,
) -> None:
    if (
        create.project_name != reopen.project_name
        or create.deployment_inputs_sha256 != reopen.deployment_inputs_sha256
        or create.bind_mounts != reopen.bind_mounts
        or create.commitment_sha256 == reopen.commitment_sha256
        or create_provider.runtime_attestation_sha256 != create.commitment_sha256
        or reopen_provider.runtime_attestation_sha256 != reopen.commitment_sha256
        or create_provider.authority_identity() != reopen_provider.authority_identity()
    ):
        _fail("publishable_acceptance_reopen_identity_mismatch")
    if (
        type(create) is ProjectRuntimeAttestationReadback
        and type(reopen) is ProjectRuntimeAttestationReadback
    ):
        if create.fleet_mode != "create" or reopen.fleet_mode != "reopen":
            _fail("publishable_acceptance_reopen_state_mismatch")
        for first, second in zip(create.bridges, reopen.bridges, strict=True):
            if (
                first.stable_identity() != second.stable_identity()
                or first.lifecycle_inventory_sha256 == second.lifecycle_inventory_sha256
            ):
                _fail("publishable_acceptance_reopen_state_mismatch")
        return
    if (
        type(create) is not RuntimeAttestationReadback
        or type(reopen) is not RuntimeAttestationReadback
    ):
        _fail("publishable_acceptance_attestation_scope_mismatch")
    for first, second in zip(create.bridges, reopen.bridges, strict=True):
        if (
            first.stable_identity() != second.stable_identity()
            or second.generation != first.generation + 1
        ):
            _fail("publishable_acceptance_reopen_state_mismatch")


def _state_snapshot(
    config: PublishableLaneConfig,
    *,
    expected_uid: int,
    expected_gid: int,
) -> StateDirectorySnapshot:
    paths = (
        config.paths.adapter_state_dir,
        config.paths.qdrant_state_dir,
        config.paths.fleet_state_dir,
        *(config.paths.fleet_state_dir / account.account_name for account in config.bridges),
    )
    identities: list[StateDirectoryIdentity] = []
    for path in paths:
        try:
            value = path.lstat()
        except OSError as exc:
            raise DockerAcceptanceError("publishable_acceptance_state_unavailable") from exc
        if (
            stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or (value.st_uid, value.st_gid) != (expected_uid, expected_gid)
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            _fail("publishable_acceptance_state_unsafe")
        identities.append(
            StateDirectoryIdentity(
                path=str(path),
                device=value.st_dev,
                inode=value.st_ino,
                uid=value.st_uid,
                gid=value.st_gid,
                mode=stat.S_IMODE(value.st_mode),
            )
        )
    if len(set(paths)) != len(paths):
        _fail("publishable_acceptance_state_paths_invalid")
    return StateDirectorySnapshot(directories=tuple(identities))


def _require_state_unchanged(
    expected: StateDirectorySnapshot,
    config: PublishableLaneConfig,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    if (
        _state_snapshot(
            config,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        != expected
    ):
        _fail("publishable_acceptance_state_identity_changed")


def _require_deployment_inputs(
    attestation: AcceptanceRuntimeReadback,
    expected: DeploymentInputEvidence,
) -> None:
    if attestation.deployment_inputs_sha256 != expected.commitment_sha256:
        _fail("publishable_acceptance_deployment_inputs_mismatch")


def _require_deployment_inputs_current(
    expected: DeploymentInputEvidence,
    *,
    config: PublishableLaneConfig,
    config_file: Path,
    expected_uid: int,
    expected_gid: int,
    deployment_attestor: DeploymentInputAttestor,
) -> None:
    observed = deployment_attestor(
        config,
        config_file=config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    if observed != expected:
        _fail("publishable_acceptance_deployment_inputs_changed")


def _acceptance_payload(
    *,
    config: PublishableLaneConfig,
    driver: AcceptanceDriverIdentity,
    state: StateDirectorySnapshot,
    cleanup: ProjectResources,
    create: AcceptanceRuntimeReadback,
    reopen: AcceptanceRuntimeReadback,
    create_provider: ProviderAttestationEvidence,
    reopen_provider: ProviderAttestationEvidence,
    inventory_scope: InventoryScope,
) -> dict[str, object]:
    return {
        "authenticated_empty_state": {
            "reason": "requires authoritative run admission and durable run-bound proof",
            "status": CLEAN_STATE_STATUS,
        },
        "cleanup": cleanup.payload(),
        "acceptance_driver": driver.payload(),
        "create": {
            "provider_attestation_sha256": create_provider.commitment_sha256,
            "runtime_attestation_sha256": create.commitment_sha256,
        },
        "deployment_authority": driver.deployment_authority_payload(
            deployment_inputs_sha256=create.deployment_inputs_sha256
        ),
        "docker_inventory": _docker_inventory_payload(
            docker_host=config.docker_host,
            project_name=config.project_name,
            inventory_scope=inventory_scope,
        ),
        "lifecycle": list(_LIFECYCLE),
        "phase_c_infinity_commit_sha1": create_provider.phase_c_infinity_commit_sha1,
        "phase_c_infinity_tree_sha1": create_provider.phase_c_infinity_tree_sha1,
        "project_name": config.project_name,
        "provider_call_verification": _provider_call_verification(),
        "reopen": {
            "provider_attestation_sha256": reopen_provider.commitment_sha256,
            "runtime_attestation_sha256": reopen.commitment_sha256,
        },
        "schema_version": ACCEPTANCE_SCHEMA,
        "adapter_source_commit_sha1": create_provider.source_commit_sha1,
        "adapter_source_tree_sha1": create_provider.source_tree_sha1,
        "state_directory_identity_sha256": state.commitment_sha256,
    }


def _provider_call_verification() -> dict[str, object]:
    return {
        "acceptance_driver_provider_dispatch_operations": 0,
        "authenticated_runtime_probe_provider_calls": {"create": 0, "reopen": 0},
        "historical_or_concurrent_provider_call_counter": "NOT_AVAILABLE",
        "scope": "fixed acceptance command operations",
        "status": "VERIFIED_PROVIDER_FREE",
    }


def _require_inventory_authority(
    config: PublishableLaneConfig,
    *,
    inventory_scope: InventoryScope,
    expected_project_name: str | None,
    expected_docker_host: str | None,
) -> None:
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        if (
            expected_project_name != config.project_name
            or expected_docker_host != config.docker_host
        ):
            _fail("publishable_acceptance_project_authority_invalid")
        return
    if expected_project_name not in (None, config.project_name) or expected_docker_host not in (
        None,
        config.docker_host,
    ):
        _fail("publishable_acceptance_global_authority_invalid")


def _deploy_lane(
    lane_deployer: LaneDeployer,
    *,
    config_file: Path,
    fleet_mode: str,
    runner: CommandRunner | None,
    proc_root: Path,
    expected_uid: int,
    expected_gid: int,
    inventory_scope: InventoryScope,
) -> DeploymentOutcome:
    arguments: dict[str, object] = {
        "config_file": config_file,
        "fleet_mode": fleet_mode,
        "start": True,
        "runner": runner,
        "proc_root": proc_root,
        "expected_uid": expected_uid,
        "expected_gid": expected_gid,
    }
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        arguments["inventory_scope"] = inventory_scope
    return lane_deployer(**arguments)


def _read_runtime_attestation(
    *,
    inventory_scope: InventoryScope,
    path: Path,
    directory: Path,
    authentication_key_file: Path,
    expected_project: str,
    expected_docker_host: str,
    expected_mode: str,
    expected_commitment: str,
    expected_project_isolation_authority_sha256: str | None,
    expected_uid: int,
    expected_gid: int,
) -> AcceptanceRuntimeReadback:
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        return read_project_runtime_attestation(
            path=path,
            directory=directory,
            authentication_key_file=authentication_key_file,
            expected_project=expected_project,
            expected_docker_host=expected_docker_host,
            expected_mode=expected_mode,
            expected_commitment=expected_commitment,
            expected_project_isolation_authority_sha256=(
                expected_project_isolation_authority_sha256 or ""
            ),
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    return read_runtime_attestation(
        path=path,
        directory=directory,
        authentication_key_file=authentication_key_file,
        expected_project=expected_project,
        expected_mode=expected_mode,
        expected_commitment=expected_commitment,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )


def _require_runtime_attestation_unchanged(
    evidence: AcceptanceRuntimeReadback,
    *,
    inventory_scope: InventoryScope,
    directory: Path,
    authentication_key_file: Path,
    expected_docker_host: str,
    expected_uid: int,
    expected_gid: int,
) -> AcceptanceRuntimeReadback:
    if inventory_scope == PROJECT_INVENTORY_SCOPE:
        if type(evidence) is not ProjectRuntimeAttestationReadback:
            _fail("publishable_acceptance_attestation_scope_mismatch")
        return require_project_runtime_attestation_unchanged(
            evidence,
            directory=directory,
            authentication_key_file=authentication_key_file,
            expected_docker_host=expected_docker_host,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
    if type(evidence) is not RuntimeAttestationReadback:
        _fail("publishable_acceptance_attestation_scope_mismatch")
    return require_runtime_attestation_unchanged(
        evidence,
        directory=directory,
        authentication_key_file=authentication_key_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )


def _docker_inventory_payload(
    *,
    docker_host: str,
    project_name: str,
    inventory_scope: InventoryScope,
) -> dict[str, str]:
    scoped = inventory_scope == PROJECT_INVENTORY_SCOPE
    return {
        "daemon_global_container_inventory": (
            "NOT_OBSERVED_PROJECT_SCOPE" if scoped else "OBSERVED_STRICT_GLOBAL"
        ),
        "docker_host": docker_host,
        "host_process_identities": (
            "NOT_OBSERVED_PROJECT_SCOPE" if scoped else "OBSERVED_STRICT_GLOBAL"
        ),
        "project_name": project_name,
        "scope": inventory_scope,
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _fail(code: str) -> None:
    raise DockerAcceptanceError(code)


__all__ = (
    "ACCEPTANCE_FILE_PREFIX",
    "ACCEPTANCE_SCHEMA",
    "CLEAN_STATE_STATUS",
    "DeploymentInputAttestor",
    "DockerAcceptanceError",
    "DockerAcceptanceOutcome",
    "run_docker_acceptance",
)
