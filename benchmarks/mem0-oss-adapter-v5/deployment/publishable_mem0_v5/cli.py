"""Installed cached-only deployment and runtime-attestation command."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .config import (
    CONTAINER_GID,
    CONTAINER_UID,
    DeploymentConfigError,
    load_lane_config,
)
from .docker_cli import CommandRunner, DockerCli, DockerCliError
from .preflight import (
    DeploymentPreflightError,
    attest_account_i_fence,
    attest_deployment_inputs,
    attest_secret_cross_wire,
)
from .runtime_attestation import (
    RuntimeAttestationError,
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
) -> DeploymentOutcome:
    """Preflight, optionally start, then attest the exact ready lane."""

    if not config_file.is_absolute() or fleet_mode not in {"create", "reopen"}:
        raise DeploymentConfigError("publishable_deploy_input_invalid")
    config = load_lane_config(config_file)
    docker = DockerCli(config, config_file=config_file, runner=runner)
    attest_compose_asset(docker.compose_file)
    deployment = attest_deployment_inputs(
        config,
        config_file=config_file,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    account_i = attest_account_i_fence(config.account_i_r16_fence, proc_root=proc_root)
    cross_wire = attest_secret_cross_wire(
        config,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
    )
    cached = docker.inspect_cached_images()
    if start:
        docker.start(mode=fleet_mode)
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
    destination = write_runtime_attestation(attestation, config.paths.attestation_dir)
    return DeploymentOutcome(
        attestation_file=destination,
        attestation_sha256=attestation.commitment_sha256,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-publishable-mem0-v5",
        description=("Start or attest the cached-only isolated publishable Mem0 OSS v5 lane."),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "attest"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--fleet-mode", choices=("create", "reopen"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        outcome = deploy(
            config_file=arguments.config,
            fleet_mode=arguments.fleet_mode,
            start=arguments.command == "start",
        )
    except (
        DeploymentConfigError,
        DeploymentPreflightError,
        DockerCliError,
        RuntimeAttestationError,
    ) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    print(json.dumps(outcome.payload(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("DeploymentOutcome", "deploy", "main")
