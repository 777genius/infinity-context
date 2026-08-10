"""Installed cached-only deployment and runtime-attestation command."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from .acceptance import DockerAcceptanceError, run_docker_acceptance
from .acceptance_attestation import AcceptanceAttestationError
from .acceptance_identity import AcceptanceDriverIdentityError
from .config import DeploymentConfigError
from .deployment import DeploymentOutcome, deploy
from .docker_cli import DockerCliError
from .immutable_evidence import ImmutableEvidenceError
from .preflight import DeploymentPreflightError
from .provider_attestation import ProviderAttestationError
from .runtime_attestation import RuntimeAttestationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infinity-context-publishable-mem0-v5",
        description=("Operate the cached-only isolated publishable Mem0 OSS v5 lane."),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "attest"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--fleet-mode", choices=("create", "reopen"), required=True)
    acceptance = commands.add_parser(
        "acceptance",
        help="run the provider-free create/stop/reopen/exact-cleanup lifecycle",
    )
    acceptance.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command == "acceptance":
            outcome = run_docker_acceptance(config_file=arguments.config)
        else:
            outcome = deploy(
                config_file=arguments.config,
                fleet_mode=arguments.fleet_mode,
                start=arguments.command == "start",
            )
    except (
        AcceptanceAttestationError,
        AcceptanceDriverIdentityError,
        DeploymentConfigError,
        DeploymentPreflightError,
        DockerAcceptanceError,
        DockerCliError,
        ImmutableEvidenceError,
        ProviderAttestationError,
        RuntimeAttestationError,
    ) as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    print(json.dumps(outcome.payload(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("DeploymentOutcome", "deploy", "main", "run_docker_acceptance")
