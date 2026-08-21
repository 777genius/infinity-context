"""Secret-safe CLI for the exact authenticated fresh-chain 1+4 canary."""

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
)

from .authorization import (
    FRESH_CHAIN_LIVE_1_PLUS_4_FLAG,
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)
from .contracts import (
    FreshChainCanaryDependencyFactoryPort,
    FreshChainCanaryError,
)
from .orchestrator import FreshChainCanaryOrchestrator

FRESH_CHAIN_CLI_SCHEMA = "memory-comparison-publishable-fresh-chain-canary-cli.v1"
FRESH_CHAIN_CLI_SUCCESS = 0
FRESH_CHAIN_CLI_FAILURE = 2
FRESH_CHAIN_PRODUCTION_DEPENDENCY_PROVIDER = "mem0-infinity-production-v1"


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise FreshChainCanaryError("fresh_chain_arguments_invalid") from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="infinity-context-publishable-fresh-chain-canary",
        allow_abbrev=False,
        description=(
            "Run the fixed fresh-chain canary through the exact authenticated "
            "subscription runtime worker path and emit operator-local HMAC "
            "activation evidence that is never publishable."
        ),
        epilog=(
            "Provider identity: subscription-runtime-worker-authenticated. "
            "Evidence authentication: operator-local HMAC."
        ),
    )
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    parser.add_argument(
        FRESH_CHAIN_LIVE_1_PLUS_4_FLAG,
        action="store_true",
        help=(
            "Authorize only one fresh Mem0 extraction followed by exactly four "
            "ordered evaluation calls for conv-26:qa:1; authenticated terminal "
            "replay performs zero calls."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    dependency_factory: FreshChainCanaryDependencyFactoryPort | None = None,
) -> int:
    """Run the provider-ready canary; tests inject a provider-free factory."""

    try:
        raw_arguments = tuple(sys.argv[1:] if argv is None else argv)
        if "--allow-live" in raw_arguments:
            raise FreshChainCanaryError("fresh_chain_arguments_invalid")
        if raw_arguments.count(FRESH_CHAIN_LIVE_1_PLUS_4_FLAG) != 1:
            raise FreshChainCanaryError("fresh_chain_live_1_plus_4_authorization_required")
        args = _parser().parse_args(raw_arguments)
        if args.allow_live_1_plus_4 is not True:
            raise FreshChainCanaryError("fresh_chain_live_1_plus_4_authorization_required")
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
        evidence = FreshChainCanaryOrchestrator(dependency_factory=selected).run(
            config=config,
            secrets=secrets,
            authorization=FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
        )
        payload = evidence.payload()
        receipt = payload.get("receipt") if type(payload) is dict else None
        if (
            evidence.publishable is not False
            or evidence.activation_evidence is not True
            or type(payload) is not dict
            or payload.get("publishable") is not False
            or payload.get("activation_evidence") is not True
            or type(receipt) is not dict
            or receipt.get("publishable") is not False
            or payload.get("case_id") != "conv-26:qa:1"
            or payload.get("measured_physical_attempt_count") != 5
        ):
            raise FreshChainCanaryError("fresh_chain_activation_evidence_incomplete")
        rendered = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (Exception, KeyboardInterrupt):
        print(_failure_json(), file=sys.stderr)
        return FRESH_CHAIN_CLI_FAILURE
    print(rendered)
    return FRESH_CHAIN_CLI_SUCCESS


def _installed_dependency_factory(provider: str) -> FreshChainCanaryDependencyFactoryPort:
    try:
        if provider != FRESH_CHAIN_PRODUCTION_DEPENDENCY_PROVIDER:
            raise LookupError
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
        if not callable(getattr(candidate, "open_fresh_chain_session", None)) and callable(
            candidate
        ):
            candidate = candidate()
        if not callable(getattr(candidate, "open_fresh_chain_session", None)):
            raise TypeError
        return candidate
    except Exception:
        raise FreshChainCanaryError("fresh_chain_dependency_provider_unavailable") from None


def _failure_json() -> str:
    return json.dumps(
        {
            "activation_evidence": False,
            "ok": False,
            "publishable": False,
            "reason_code": "fresh_chain_canary_failed",
            "schema_version": FRESH_CHAIN_CLI_SCHEMA,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = (
    "FRESH_CHAIN_CLI_FAILURE",
    "FRESH_CHAIN_CLI_SCHEMA",
    "FRESH_CHAIN_CLI_SUCCESS",
    "FRESH_CHAIN_PRODUCTION_DEPENDENCY_PROVIDER",
    "main",
)
