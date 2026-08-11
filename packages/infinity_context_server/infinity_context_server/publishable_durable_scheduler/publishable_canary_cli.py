"""Installed secret-safe CLI for the exact one-case publishable canary."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from infinity_context_server.publishable_durable_scheduler.publishable_canary_orchestrator import (
    PublishableCanaryOrchestrator,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_cli import (
    _installed_dependency_factory,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunDependencyFactoryPort,
    PublishableRunError,
)

PUBLISHABLE_CANARY_CLI_SCHEMA = "memory-comparison-publishable-one-case-canary-cli.v1"
PUBLISHABLE_CANARY_CLI_SUCCESS = 0
PUBLISHABLE_CANARY_CLI_FAILURE = 2


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise PublishableRunError("publishable_canary_arguments_invalid") from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="infinity-context-publishable-canary",
        description=(
            "Run the exact authenticated one-case same-lane canary and emit "
            "non-publishable activation evidence."
        ),
    )
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help=(
            "Acknowledge exactly 4 live provider calls on first execution; "
            "an authenticated replay dispatches zero calls."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    dependency_factory: PublishableRunDependencyFactoryPort | None = None,
) -> int:
    """Run the installed canary; tests may inject a provider-free factory."""

    try:
        args = _parser().parse_args(argv)
        if args.allow_live is not True:
            raise PublishableRunError("publishable_canary_live_authorization_required")
        config, secrets = load_publishable_run_files(
            private_root=args.private_root,
            config_path=args.config,
            secrets_path=args.secrets,
        )
        selected = (
            dependency_factory
            if dependency_factory is not None
            else _installed_dependency_factory(config.dependency_provider)
        )
        evidence = PublishableCanaryOrchestrator(dependency_factory=selected).run(
            config=config,
            secrets=secrets,
        )
        payload = evidence.payload()
        if (
            evidence.publishable is not False
            or evidence.activation_evidence is not True
            or type(payload) is not dict
            or payload.get("publishable") is not False
            or payload.get("activation_evidence") is not True
        ):
            raise PublishableRunError("publishable_canary_activation_incomplete")
        rendered = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (Exception, KeyboardInterrupt):
        print(_failure_json(), file=sys.stderr)
        return PUBLISHABLE_CANARY_CLI_FAILURE
    print(rendered)
    return PUBLISHABLE_CANARY_CLI_SUCCESS


def _failure_json() -> str:
    return json.dumps(
        {
            "activation_evidence": False,
            "ok": False,
            "publishable": False,
            "reason_code": "publishable_canary_failed",
            "schema_version": PUBLISHABLE_CANARY_CLI_SCHEMA,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = (
    "PUBLISHABLE_CANARY_CLI_FAILURE",
    "PUBLISHABLE_CANARY_CLI_SCHEMA",
    "PUBLISHABLE_CANARY_CLI_SUCCESS",
    "main",
)
