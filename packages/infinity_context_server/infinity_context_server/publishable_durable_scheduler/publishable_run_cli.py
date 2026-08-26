"""Installed secret-safe CLI for one resumable publishable evaluation suite."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP,
    PublishableRunDependencyFactoryPort,
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_orchestrator import (
    PublishableProductionCompositionOpener,
    PublishableRunOrchestrator,
)

PUBLISHABLE_RUN_CLI_SCHEMA = "memory-comparison-publishable-run-cli.v1"
PUBLISHABLE_RUN_CLI_SUCCESS = 0
PUBLISHABLE_RUN_CLI_FAILURE = 2
PUBLISHABLE_RUN_CLI_INCOMPLETE = 3


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise PublishableRunError("publishable_run_arguments_invalid") from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="infinity-context-publishable-run",
        description=(
            "Resume the exact sealed 2,040-case publishable evaluation and emit "
            "an authenticated secret-free publication receipt."
        ),
    )
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Acknowledge that this command may dispatch up to 8,160 live provider calls.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    dependency_factory: PublishableRunDependencyFactoryPort | None = None,
    composition_opener: PublishableProductionCompositionOpener | None = None,
) -> int:
    """Run the installed composition; tests may inject a provider-free factory."""

    try:
        args = _parser().parse_args(argv)
        if args.allow_live is not True:
            raise PublishableRunError("publishable_run_live_authorization_required")
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
        orchestrator = (
            PublishableRunOrchestrator(dependency_factory=selected)
            if composition_opener is None
            else PublishableRunOrchestrator(
                dependency_factory=selected,
                composition_opener=composition_opener,
            )
        )
        receipt = orchestrator.run(
            config=config,
            secrets=secrets,
        )
        rendered = json.dumps(
            receipt.payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (Exception, KeyboardInterrupt):
        print(_failure_json(), file=sys.stderr)
        return PUBLISHABLE_RUN_CLI_FAILURE
    print(rendered)
    return PUBLISHABLE_RUN_CLI_SUCCESS if receipt.publishable else PUBLISHABLE_RUN_CLI_INCOMPLETE


def _installed_dependency_factory(provider: str) -> PublishableRunDependencyFactoryPort:
    try:
        matches = tuple(
            importlib.metadata.entry_points(
                group=PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP,
                name=provider,
            )
        )
        if len(matches) != 1:
            raise LookupError
        loaded = matches[0].load()
        candidate = loaded() if isinstance(loaded, type) else loaded
        if not callable(getattr(candidate, "open_session", None)) and callable(candidate):
            candidate = candidate()
        if not callable(getattr(candidate, "open_session", None)):
            raise TypeError
        return candidate
    except Exception:
        raise PublishableRunError("publishable_run_dependency_provider_unavailable") from None


def _failure_json() -> str:
    return json.dumps(
        {
            "ok": False,
            "publishable": False,
            "reason_code": "publishable_run_failed",
            "schema_version": PUBLISHABLE_RUN_CLI_SCHEMA,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = (
    "PUBLISHABLE_RUN_CLI_FAILURE",
    "PUBLISHABLE_RUN_CLI_INCOMPLETE",
    "PUBLISHABLE_RUN_CLI_SCHEMA",
    "PUBLISHABLE_RUN_CLI_SUCCESS",
    "main",
)
