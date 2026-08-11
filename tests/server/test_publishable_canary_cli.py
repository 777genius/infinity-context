from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_durable_scheduler import publishable_canary_cli as cli

_FIXED_ARGS = (
    "--private-root",
    "/private",
    "--config",
    "/private/config.json",
    "--secrets",
    "/private/secrets.json",
    "--allow-live",
)
_ENTRY_POINT = "infinity_context_server.publishable_durable_scheduler.publishable_canary_cli:main"


class _Evidence:
    def __init__(
        self,
        *,
        activation_evidence: bool = True,
        publishable: bool = False,
    ) -> None:
        self.activation_evidence = activation_evidence
        self.publishable = publishable

    def payload(self) -> dict[str, object]:
        return {
            "activation_evidence": self.activation_evidence,
            "publishable": self.publishable,
            "receipt_sha256": "a" * 64,
            "schema_version": "test.activation-evidence.v1",
        }


def _install_provider_free_run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidence: _Evidence | None = None,
    error: Exception | None = None,
) -> tuple[object, object, list[tuple[object, object, object]]]:
    config = SimpleNamespace(dependency_provider="tests.provider-free")
    secrets = object()
    calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(cli, "load_publishable_run_files", lambda **_arguments: (config, secrets))

    class _Orchestrator:
        def __init__(self, *, dependency_factory: object) -> None:
            self._dependency_factory = dependency_factory

        def run(self, *, config: object, secrets: object) -> _Evidence:
            calls.append((self._dependency_factory, config, secrets))
            if error is not None:
                raise error
            assert evidence is not None
            return evidence

    monkeypatch.setattr(cli, "PublishableCanaryOrchestrator", _Orchestrator)
    return config, secrets, calls


def _failure_payload() -> dict[str, object]:
    return {
        "activation_evidence": False,
        "ok": False,
        "publishable": False,
        "reason_code": "publishable_canary_failed",
        "schema_version": cli.PUBLISHABLE_CANARY_CLI_SCHEMA,
    }


def test_cli_emits_only_nonpublishable_complete_activation_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = _Evidence()
    config, secrets, calls = _install_provider_free_run(monkeypatch, evidence=evidence)
    factory = object()
    monkeypatch.setattr(
        cli,
        "_installed_dependency_factory",
        lambda _provider: pytest.fail("installed provider resolution was not expected"),
    )

    assert cli.main(_FIXED_ARGS, dependency_factory=factory) == cli.PUBLISHABLE_CANARY_CLI_SUCCESS

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == evidence.payload()
    assert json.loads(captured.out)["publishable"] is False
    assert calls == [(factory, config, secrets)]


def test_cli_reuses_installed_publishable_dependency_resolution(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = _Evidence()
    config, secrets, calls = _install_provider_free_run(monkeypatch, evidence=evidence)
    installed_factory = object()
    requested: list[str] = []

    def installed(provider: str) -> object:
        requested.append(provider)
        return installed_factory

    monkeypatch.setattr(cli, "_installed_dependency_factory", installed)

    assert cli.main(_FIXED_ARGS) == cli.PUBLISHABLE_CANARY_CLI_SUCCESS

    assert capsys.readouterr().err == ""
    assert requested == ["tests.provider-free"]
    assert calls == [(installed_factory, config, secrets)]


@pytest.mark.parametrize(
    "activation_evidence,publishable",
    ((False, False), (True, True)),
    ids=("not-complete", "claims-publishable"),
)
def test_cli_fails_closed_unless_activation_is_complete_and_nonpublishable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    activation_evidence: bool,
    publishable: bool,
) -> None:
    _install_provider_free_run(
        monkeypatch,
        evidence=_Evidence(
            activation_evidence=activation_evidence,
            publishable=publishable,
        ),
    )

    assert cli.main(_FIXED_ARGS, dependency_factory=object()) == cli.PUBLISHABLE_CANARY_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == _failure_payload()


def test_cli_redacts_provider_and_orchestrator_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_sentinel = "private-canary-provider-output"
    _install_provider_free_run(monkeypatch, error=RuntimeError(private_sentinel))

    assert cli.main(_FIXED_ARGS, dependency_factory=object()) == cli.PUBLISHABLE_CANARY_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert private_sentinel not in captured.err
    assert json.loads(captured.err) == _failure_payload()


@pytest.mark.parametrize(
    "untrusted_arguments",
    (
        ("--case-id", "another-case"),
        ("--case-index", "1"),
        ("--expected-provider-call-count", "3"),
        ("--max-dispatches", "3"),
        ("--batch-size", "1"),
    ),
    ids=("case-id", "case-index", "call-count", "dispatch-limit", "batch-size"),
)
def test_cli_rejects_scope_or_count_injection_before_loading_or_provider_use(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    untrusted_arguments: tuple[str, str],
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_publishable_run_files",
        lambda **_arguments: touched.append("load"),
    )
    monkeypatch.setattr(
        cli,
        "_installed_dependency_factory",
        lambda _provider: touched.append("provider"),
    )

    assert cli.main((*_FIXED_ARGS, *untrusted_arguments)) == cli.PUBLISHABLE_CANARY_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == _failure_payload()
    assert touched == []


def test_cli_requires_explicit_live_authorization_before_loading_files(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_publishable_run_files",
        lambda **_arguments: touched.append("load"),
    )

    assert (
        cli.main(_FIXED_ARGS[:-1], dependency_factory=object())
        == cli.PUBLISHABLE_CANARY_CLI_FAILURE
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == _failure_payload()
    assert touched == []


def test_cli_exposes_only_fixed_paths_and_live_authorization() -> None:
    option_strings = {
        option for action in cli._parser()._actions for option in action.option_strings
    }

    assert option_strings == {
        "-h",
        "--help",
        "--private-root",
        "--config",
        "--secrets",
        "--allow-live",
    }
    assert "exactly 4 live provider calls" in cli._parser().format_help()


def test_root_distribution_registers_publishable_canary_console_script() -> None:
    project_root = Path(__file__).resolve().parents[2]
    with (project_root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)

    assert project["project"]["scripts"]["infinity-context-publishable-canary"] == _ENTRY_POINT


def test_installed_metadata_loads_publishable_canary_console_script() -> None:
    matches = tuple(
        importlib.metadata.entry_points(
            group="console_scripts",
            name="infinity-context-publishable-canary",
        )
    )

    assert len(matches) == 1
    assert matches[0].value == _ENTRY_POINT
    assert matches[0].load() is cli.main
