"""Installed secret-safe CLI for resumable publishable input preparation."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import stat
import sys
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from pathlib import Path

from infinity_context_server.publishable_durable_scheduler.publishable_run_config import (
    load_publishable_run_files,
)

from .composition import (
    PUBLISHABLE_INPUT_MAX_RECOVERY_STATUS_READS,
    PUBLISHABLE_INPUT_MAX_SUBSCRIPTION_STEPS,
    PublishableInputPreparationComposition,
    open_publishable_input_preparation,
)
from .contracts import (
    PUBLISHABLE_INPUT_PREPARATION_DEPENDENCY_ENTRYPOINT_GROUP,
    OpenedPublishableInputPreparationSession,
    PublishableInputPreparationDependencyFactoryPort,
    PublishableInputPreparationError,
    PublishableInputPreparationPhase,
    PublishableInputPreparationProviderInputs,
)
from .provider_files import load_publishable_input_provider_files

PUBLISHABLE_INPUT_CLI_SCHEMA = "memory-comparison-publishable-input-cli.v1"
PUBLISHABLE_INPUT_CLI_SUCCESS = 0
PUBLISHABLE_INPUT_CLI_FAILURE = 2
PUBLISHABLE_INPUT_CLI_INCOMPLETE = 3

CompositionOpener = Callable[..., Awaitable[PublishableInputPreparationComposition]]


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise PublishableInputPreparationError("publishable_input_arguments_invalid") from None


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="infinity-context-publishable-inputs",
        description=(
            "Resume exact 130,226-receipt extraction and seal the 4,080-group "
            "retrieval authority across the required LoCoMo-to-LongMemEval runtime reopen."
        ),
    )
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--secrets", required=True, type=Path)
    parser.add_argument("--input-provider-config", required=True, type=Path)
    parser.add_argument("--input-provider-secrets", required=True, type=Path)
    parser.add_argument(
        "--max-extraction-steps",
        "--max-subscription-dispatches",
        dest="max_extraction_steps",
        required=True,
        type=int,
        help=(
            "Maximum extraction worker steps for this invocation. Each step dispatches "
            "at most one new operation; crash recovery can additionally status-read "
            "committed receipts up to the fixed 130,226-receipt suite ceiling."
        ),
    )
    parser.add_argument(
        "--allow-subscription-dispatch",
        action="store_true",
        help=(
            "Explicitly authorize bounded subscription extraction and the final "
            "run-scoped partition of the 4,080-request retrieval capture."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    dependency_factory: PublishableInputPreparationDependencyFactoryPort | None = None,
    composition_opener: CompositionOpener = open_publishable_input_preparation,
) -> int:
    """Run one bounded batch; tests may inject a provider-free dependency factory."""

    composition: PublishableInputPreparationComposition | None = None
    try:
        args = _parser().parse_args(argv)
        if args.allow_subscription_dispatch is not True:
            _fail("publishable_input_subscription_authorization_required")
        if (
            type(args.max_extraction_steps) is not int
            or not 1 <= args.max_extraction_steps <= PUBLISHABLE_INPUT_MAX_SUBSCRIPTION_STEPS
        ):
            _fail("publishable_input_subscription_step_bound_invalid")
        config, secrets = load_publishable_run_files(
            private_root=args.private_root,
            config_path=args.config,
            secrets_path=args.secrets,
        )
        input_config_json, input_secrets_json = load_publishable_input_provider_files(
            private_root=args.private_root,
            config_path=args.input_provider_config,
            secrets_path=args.input_provider_secrets,
            reserved_paths=(
                args.config,
                args.secrets,
                config.official_case_authority_path,
                *config.scheduler_database_paths,
                config.suite_seal_database_path,
                config.publication_receipt_path,
            ),
        )
        selected = (
            dependency_factory
            if dependency_factory is not None
            else _installed_dependency_factory(config.dependency_provider)
        )
        if not callable(getattr(selected, "open_session", None)):
            _fail("publishable_input_dependency_provider_unavailable")
        provider_inputs = PublishableInputPreparationProviderInputs(
            state_root=_input_provider_state_root(config.publication_receipt_path.parent),
            run_adapter_config_json=config.adapter_config_json,
            run_adapter_secrets_json=secrets.adapter_secrets_json,
            input_config_json=input_config_json,
            input_secrets_json=input_secrets_json,
        )
        composition = asyncio.run(
            _open_composition(
                factory=selected,
                inputs=provider_inputs,
                config=config,
                secrets=secrets,
                composition_opener=composition_opener,
            )
        )
        result = composition.dispatch_subscription_phase(
            max_subscription_steps=args.max_extraction_steps,
        )
        rendered = json.dumps(
            {
                **result.payload(),
                "extraction_boundary_operation_upper_bound": (
                    0
                    if result.complete and result.subscription_step_count == 0
                    else result.subscription_step_count
                    + PUBLISHABLE_INPUT_MAX_RECOVERY_STATUS_READS
                ),
                "ok": True,
                "operator_action": (
                    "activate-longmemeval-runtime-and-reopen"
                    if result.phase is PublishableInputPreparationPhase.RUNTIME_SWITCH_REQUIRED
                    else "none"
                ),
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (Exception, KeyboardInterrupt):
        print(_failure_json(), file=sys.stderr)
        return PUBLISHABLE_INPUT_CLI_FAILURE
    finally:
        if composition is not None:
            with suppress(BaseException):
                composition.close()
    print(rendered)
    return PUBLISHABLE_INPUT_CLI_SUCCESS if result.complete else PUBLISHABLE_INPUT_CLI_INCOMPLETE


async def _open_composition(
    *,
    factory: PublishableInputPreparationDependencyFactoryPort,
    inputs: PublishableInputPreparationProviderInputs,
    config: object,
    secrets: object,
    composition_opener: CompositionOpener,
) -> PublishableInputPreparationComposition:
    session = await factory.open_session(inputs=inputs)
    if type(session) is not OpenedPublishableInputPreparationSession:
        _close_session(session)
        _fail("publishable_input_session_invalid")
    try:
        return await composition_opener(
            config=config,
            secrets=secrets,
            session=session,
        )
    except BaseException:
        _close_session(session)
        raise


def _installed_dependency_factory(
    provider: str,
) -> PublishableInputPreparationDependencyFactoryPort:
    try:
        matches = tuple(
            importlib.metadata.entry_points(
                group=PUBLISHABLE_INPUT_PREPARATION_DEPENDENCY_ENTRYPOINT_GROUP,
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
        _fail("publishable_input_dependency_provider_unavailable")


def _input_provider_state_root(parent: Path) -> Path:
    root = parent / ".input-provider"
    try:
        parent_value = parent.lstat()
        if (
            stat.S_ISLNK(parent_value.st_mode)
            or not stat.S_ISDIR(parent_value.st_mode)
            or parent_value.st_uid != os.geteuid()
            or stat.S_IMODE(parent_value.st_mode) != 0o700
        ):
            _fail("publishable_input_provider_state_parent_invalid")
        with suppress(FileExistsError):
            root.mkdir(mode=0o700)
        value = root.lstat()
        if (
            root.resolve(strict=True) != root
            or stat.S_ISLNK(value.st_mode)
            or not stat.S_ISDIR(value.st_mode)
            or value.st_uid != os.geteuid()
            or stat.S_IMODE(value.st_mode) != 0o700
        ):
            _fail("publishable_input_provider_state_invalid")
    except PublishableInputPreparationError:
        raise
    except OSError:
        _fail("publishable_input_provider_state_invalid")
    return root


def _close_session(session: object) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        with suppress(BaseException):
            close()


def _failure_json() -> str:
    return json.dumps(
        {
            "ok": False,
            "reason_code": "publishable_input_preparation_failed",
            "schema_version": PUBLISHABLE_INPUT_CLI_SCHEMA,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fail(code: str) -> None:
    raise PublishableInputPreparationError(code) from None


__all__ = (
    "PUBLISHABLE_INPUT_CLI_FAILURE",
    "PUBLISHABLE_INPUT_CLI_INCOMPLETE",
    "PUBLISHABLE_INPUT_CLI_SCHEMA",
    "PUBLISHABLE_INPUT_CLI_SUCCESS",
    "main",
)
