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
from .config import CONTAINER_GID, CONTAINER_UID, PublishableLaneConfig, load_lane_config
from .deployment import LaneDeployer, deploy
from .docker_cli import CommandRunner, DockerCli, ProjectResources
from .immutable_evidence import write_immutable_json
from .preflight import DeploymentInputEvidence, attest_deployment_inputs
from .provider_attestation import (
    ProviderAttestationEvidence,
    ProviderFreeRuntimeAttestor,
    ProviderFreeRuntimeProbe,
)
from .runtime_attestation import attest_compose_asset

ACCEPTANCE_SCHEMA: Final = "publishable-mem0-v5-docker-acceptance.v1"
ACCEPTANCE_FILE_PREFIX: Final = "docker-acceptance-"
CLEAN_STATE_STATUS: Final = "NOT_RUN_REQUIRES_AUTHORITATIVE_RUN_ADMISSION"
DeploymentInputAttestor = Callable[..., DeploymentInputEvidence]
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
) -> DockerAcceptanceOutcome:
    """Create, attest, stop, reopen, re-attest, and exactly clean one project."""

    if (
        not config_file.is_absolute()
        or not proc_root.is_absolute()
        or not callable(lane_deployer)
        or not callable(deployment_attestor)
    ):
        _fail("publishable_acceptance_input_invalid")
    config = load_lane_config(config_file)
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
    create: RuntimeAttestationReadback | None = None
    reopen: RuntimeAttestationReadback | None = None
    create_provider: ProviderAttestationEvidence | None = None
    reopen_provider: ProviderAttestationEvidence | None = None
    try:
        cleanup_armed = True
        create_outcome = lane_deployer(
            config_file=config_file,
            fleet_mode="create",
            start=True,
            runner=runner,
            proc_root=proc_root,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        create = read_runtime_attestation(
            path=create_outcome.attestation_file,
            directory=config.paths.attestation_dir,
            expected_project=config.project_name,
            expected_mode="create",
            expected_commitment=create_outcome.attestation_sha256,
        )
        _require_deployment_inputs(create, deployment_before)
        create_provider = probe.attest(
            fleet_mode="create",
            runtime_attestation_sha256=create.commitment_sha256,
        )
        docker.stop(mode="create")
        docker.require_stopped(mode="create")
        _require_state_unchanged(
            state_before,
            config,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        require_runtime_attestation_unchanged(
            create,
            directory=config.paths.attestation_dir,
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
        reopen_outcome = lane_deployer(
            config_file=config_file,
            fleet_mode="reopen",
            start=True,
            runner=runner,
            proc_root=proc_root,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        reopen = read_runtime_attestation(
            path=reopen_outcome.attestation_file,
            directory=config.paths.attestation_dir,
            expected_project=config.project_name,
            expected_mode="reopen",
            expected_commitment=reopen_outcome.attestation_sha256,
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
        require_runtime_attestation_unchanged(
            create,
            directory=config.paths.attestation_dir,
        )
        require_runtime_attestation_unchanged(
            reopen,
            directory=config.paths.attestation_dir,
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
    require_runtime_attestation_unchanged(create, directory=config.paths.attestation_dir)
    require_runtime_attestation_unchanged(reopen, directory=config.paths.attestation_dir)
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
        ),
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
    )


def _cleanup_exact_project(
    docker: DockerCli,
    *,
    mode: str,
) -> tuple[BaseException | None, ProjectResources | None]:
    failures: list[BaseException] = []
    try:
        docker.teardown(mode=mode)
    except BaseException as exc:
        failures.append(exc)
    resources: ProjectResources | None = None
    try:
        resources = docker.project_resources()
        if not resources.empty:
            failures.append(DockerAcceptanceError("publishable_acceptance_cleanup_incomplete"))
    except BaseException as exc:
        failures.append(exc)
    return (failures[0] if failures else None, resources)


def _require_lifecycle_transition(
    create: RuntimeAttestationReadback,
    reopen: RuntimeAttestationReadback,
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
    attestation: RuntimeAttestationReadback,
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
    create: RuntimeAttestationReadback,
    reopen: RuntimeAttestationReadback,
    create_provider: ProviderAttestationEvidence,
    reopen_provider: ProviderAttestationEvidence,
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
