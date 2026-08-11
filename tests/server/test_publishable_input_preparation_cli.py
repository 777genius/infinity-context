from __future__ import annotations

import json
import tomllib
from pathlib import Path

from infinity_context_server.publishable_input_preparation.cli import (
    PUBLISHABLE_INPUT_CLI_FAILURE,
    PUBLISHABLE_INPUT_CLI_INCOMPLETE,
    PUBLISHABLE_INPUT_CLI_SUCCESS,
    main,
)
from infinity_context_server.publishable_input_preparation.contracts import (
    OpenedPublishableInputPreparationSession,
    PublishableInputPreparationError,
    PublishableInputPreparationPhase,
    PublishableInputPreparationProviderInputs,
    PublishableInputPreparationResult,
)
from publishable_run_outer_test_support import private_run_files, sha


class _Factory:
    def __init__(self) -> None:
        self.inputs: list[PublishableInputPreparationProviderInputs] = []

    async def open_session(self, *, inputs: PublishableInputPreparationProviderInputs):
        self.inputs.append(inputs)
        session = object.__new__(OpenedPublishableInputPreparationSession)
        object.__setattr__(session, "close_callbacks", ())
        object.__setattr__(session, "_closed", False)
        return session


def _provider_files(files) -> tuple[Path, Path]:
    config = files.root / "input-provider-config.json"
    secrets = files.root / "input-provider-secrets.json"
    for path in (config, secrets):
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o600)
    return config, secrets


class _Composition:
    def __init__(self, result: PublishableInputPreparationResult) -> None:
        self.result = result
        self.bounds: list[int] = []
        self.closed = False

    def dispatch_subscription_phase(self, *, max_subscription_steps: int):
        self.bounds.append(max_subscription_steps)
        return self.result

    def close(self) -> None:
        self.closed = True


def _result(*, complete: bool) -> PublishableInputPreparationResult:
    common = {
        "phase": (
            PublishableInputPreparationPhase.COMPLETE
            if complete
            else PublishableInputPreparationPhase.EXTRACTION_PENDING
        ),
        "suite_authority_sha256": sha("input-cli-suite"),
        "official_case_authority_root_sha256": sha("input-cli-cases"),
        "extraction_committed_receipt_count": 130_226 if complete else 17,
        "subscription_step_count": 0 if complete else 17,
    }
    if not complete:
        return PublishableInputPreparationResult(**common)
    return PublishableInputPreparationResult(
        **common,
        extraction_suite_readback_sha256=sha("input-cli-extraction-suite"),
        ordered_extraction_terminal_sha256=(
            sha("input-cli-terminal-locomo"),
            sha("input-cli-terminal-longmemeval"),
        ),
        ordered_extraction_authentication_hmac_sha256=(
            sha("input-cli-terminal-mac-locomo"),
            sha("input-cli-terminal-mac-longmemeval"),
        ),
        retrieval_authority_root_sha256=sha("input-cli-retrieval"),
        retrieval_group_count=4_080,
    )


def _switch_result() -> PublishableInputPreparationResult:
    return PublishableInputPreparationResult(
        phase=PublishableInputPreparationPhase.RUNTIME_SWITCH_REQUIRED,
        suite_authority_sha256=sha("input-cli-suite"),
        official_case_authority_root_sha256=sha("input-cli-cases"),
        extraction_committed_receipt_count=5_882,
        subscription_step_count=17,
        retrieval_group_count=3_080,
    )


def test_installed_cli_requires_explicit_dispatch_authorization_before_opening_provider(
    capsys,
) -> None:
    factory = _Factory()
    private = "/private/operator/material-must-not-render"
    status = main(
        [
            "--private-root",
            private,
            "--config",
            f"{private}/config.json",
            "--secrets",
            f"{private}/secrets.json",
            "--input-provider-config",
            f"{private}/input-config.json",
            "--input-provider-secrets",
            f"{private}/input-secrets.json",
            "--max-extraction-steps",
            "1",
        ],
        dependency_factory=factory,
    )
    captured = capsys.readouterr()
    assert status == PUBLISHABLE_INPUT_CLI_FAILURE
    assert factory.inputs == []
    assert private not in captured.err
    assert json.loads(captured.err) == {
        "ok": False,
        "reason_code": "publishable_input_preparation_failed",
        "schema_version": "memory-comparison-publishable-input-cli.v1",
    }


def test_cli_opens_private_provider_state_dispatches_bound_and_reports_complete(
    tmp_path: Path,
    capsys,
) -> None:
    files = private_run_files(tmp_path)
    factory = _Factory()
    composition = _Composition(_result(complete=True))
    input_config, input_secrets = _provider_files(files)

    async def open_composition(**arguments):
        assert arguments["config"] == files.config
        assert arguments["secrets"] == files.secrets
        assert type(arguments["session"]) is OpenedPublishableInputPreparationSession
        return composition

    status = main(
        [
            "--private-root",
            str(files.root),
            "--config",
            str(files.config_path),
            "--secrets",
            str(files.secrets_path),
            "--input-provider-config",
            str(input_config),
            "--input-provider-secrets",
            str(input_secrets),
            "--max-extraction-steps",
            "130226",
            "--allow-subscription-dispatch",
        ],
        dependency_factory=factory,
        composition_opener=open_composition,
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert status == PUBLISHABLE_INPUT_CLI_SUCCESS
    assert captured.err == ""
    assert payload["complete"] is True
    assert payload["operator_action"] == "none"
    assert payload["extraction_committed_receipt_count"] == 130_226
    assert payload["retrieval_group_count"] == 4_080
    assert payload["extraction_boundary_operation_upper_bound"] == 0
    assert composition.bounds == [130_226]
    assert composition.closed is True
    assert len(factory.inputs) == 1
    assert factory.inputs[0].state_root == files.config.publication_receipt_path.parent / (
        ".input-provider"
    )
    assert factory.inputs[0].state_root.stat().st_mode & 0o777 == 0o700


def test_cli_returns_distinct_incomplete_status_and_fixed_recovery_ceiling(
    tmp_path: Path,
    capsys,
) -> None:
    files = private_run_files(tmp_path)
    input_config, input_secrets = _provider_files(files)
    composition = _Composition(_switch_result())

    async def open_composition(**_arguments):
        return composition

    status = main(
        [
            "--private-root",
            str(files.root),
            "--config",
            str(files.config_path),
            "--secrets",
            str(files.secrets_path),
            "--input-provider-config",
            str(input_config),
            "--input-provider-secrets",
            str(input_secrets),
            "--max-subscription-dispatches",
            "17",
            "--allow-subscription-dispatch",
        ],
        dependency_factory=_Factory(),
        composition_opener=open_composition,
    )
    payload = json.loads(capsys.readouterr().out)
    assert status == PUBLISHABLE_INPUT_CLI_INCOMPLETE
    assert payload["complete"] is False
    assert payload["phase"] == "runtime_switch_required"
    assert payload["operator_action"] == "activate-longmemeval-runtime-and-reopen"
    assert payload["retrieval_group_count"] == 3_080
    assert payload["subscription_step_count"] == 17
    assert payload["extraction_boundary_operation_upper_bound"] == 130_226 + 17


def test_cli_surfaces_explicit_extraction_recovery_operator_action(
    tmp_path: Path,
    capsys,
) -> None:
    files = private_run_files(tmp_path)
    input_config, input_secrets = _provider_files(files)
    composition = _Composition(_result(complete=False))

    def fail_closed(*, max_subscription_steps: int):
        assert max_subscription_steps == 1
        raise PublishableInputPreparationError(
            "publishable_input_extraction_recovery_operator_action_required"
        )

    composition.dispatch_subscription_phase = fail_closed  # type: ignore[method-assign]

    async def open_composition(**_arguments):
        return composition

    status = main(
        [
            "--private-root",
            str(files.root),
            "--config",
            str(files.config_path),
            "--secrets",
            str(files.secrets_path),
            "--input-provider-config",
            str(input_config),
            "--input-provider-secrets",
            str(input_secrets),
            "--max-extraction-steps",
            "1",
            "--allow-subscription-dispatch",
        ],
        dependency_factory=_Factory(),
        composition_opener=open_composition,
    )

    captured = capsys.readouterr()
    assert status == PUBLISHABLE_INPUT_CLI_FAILURE
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "ok": False,
        "operator_action": ("stop-retain-private-state-and-escalate-manual-receipt-reconciliation"),
        "reason_code": "publishable_input_extraction_recovery_operator_action_required",
        "schema_version": "memory-comparison-publishable-input-cli.v1",
    }
    assert composition.closed is True


def test_publishable_input_command_is_installed() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["infinity-context-publishable-inputs"] == (
        "infinity_context_server.publishable_input_preparation.cli:main"
    )
