from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_fresh_chain_canary import cli
from infinity_context_server.publishable_fresh_chain_canary.authorization import (
    FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION,
)

_ARGS = (
    "--private-root",
    "/private",
    "--config",
    "/private/config.json",
    "--secrets",
    "/private/secrets.json",
    "--allow-live-1-plus-4",
)
_ENTRYPOINT = "infinity_context_server.publishable_fresh_chain_canary.cli:main"


class _Evidence:
    publishable = False
    activation_evidence = True

    def payload(self) -> dict[str, object]:
        return {
            "activation_evidence": True,
            "case_id": "conv-26:qa:1",
            "measured_physical_attempt_count": 5,
            "publishable": False,
            "receipt": {"publishable": False},
        }


def _install(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    config = SimpleNamespace(dependency_provider="tests.provider-free")
    secrets = object()
    monkeypatch.setattr(
        cli,
        "load_publishable_run_files",
        lambda **_arguments: (config, secrets),
    )

    class _Orchestrator:
        def __init__(self, dependency_factory: object) -> None:
            calls.append(dependency_factory)

        def run(
            self,
            *,
            config: object,
            secrets: object,
            authorization: object,
        ) -> _Evidence:
            calls.extend((config, secrets, authorization))
            return _Evidence()

    monkeypatch.setattr(cli, "FreshChainCanaryOrchestrator", _Orchestrator)
    return calls


def test_cli_emits_only_fixed_nonpublishable_activation_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _install(monkeypatch)
    factory = object()

    assert cli.main(_ARGS, dependency_factory=factory) == cli.FRESH_CHAIN_CLI_SUCCESS

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["case_id"] == "conv-26:qa:1"
    assert payload["measured_physical_attempt_count"] == 5
    assert payload["publishable"] is False
    assert payload["receipt"]["publishable"] is False
    assert calls[0] is factory
    assert calls[-1] is FRESH_CHAIN_ONE_PLUS_FOUR_AUTHORIZATION


@pytest.mark.parametrize(
    "arguments",
    (
        _ARGS[:-1],
        (*_ARGS[:-1], "--allow-live"),
        (*_ARGS[:-1], "--allow-live-1"),
        (*_ARGS[:-1], "--allow-live-1-plus-4=true"),
        (*_ARGS, "--allow-live-1-plus-4"),
        (*_ARGS, "--case-id", "other"),
        (*_ARGS, "--expected-provider-call-count", "4"),
    ),
    ids=(
        "missing-exact-flag",
        "ordinary-live",
        "abbreviated-live",
        "equals-form-live",
        "duplicate-exact-live",
        "case-override",
        "count-override",
    ),
)
def test_cli_rejects_missing_or_broadened_authorization_before_file_load(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_publishable_run_files",
        lambda **_arguments: touched.append("load"),
    )

    assert cli.main(arguments, dependency_factory=object()) == cli.FRESH_CHAIN_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "activation_evidence": False,
        "ok": False,
        "publishable": False,
        "reason_code": "fresh_chain_canary_failed",
        "schema_version": cli.FRESH_CHAIN_CLI_SCHEMA,
    }
    assert touched == []


def test_cli_surface_and_help_use_exact_fresh_chain_terms() -> None:
    parser = cli._parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}

    assert option_strings == {
        "-h",
        "--help",
        "--private-root",
        "--config",
        "--secrets",
        "--allow-live-1-plus-4",
    }
    assert parser.allow_abbrev is False
    help_text = parser.format_help()
    assert "fresh-chain canary" in help_text
    assert "subscription-runtime-worker-authenticated" in help_text
    assert "operator-local HMAC" in help_text
    assert "conv-26:qa:1" in help_text


def test_project_registers_required_fresh_chain_console_script() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)

    assert (
        project["project"]["scripts"]["infinity-context-publishable-fresh-chain-canary"]
        == _ENTRYPOINT
    )


def test_installed_provider_resolution_requires_fresh_chain_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _EntryPoint:
        def load(self):
            return lambda: SimpleNamespace(open_session=lambda **_arguments: object())

    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda **_arguments: (_EntryPoint(),),
    )

    with pytest.raises(
        cli.FreshChainCanaryError,
        match="fresh_chain_dependency_provider_unavailable",
    ):
        cli._installed_dependency_factory("old-provider")


def test_installed_provider_resolution_is_pinned_to_production_composer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = SimpleNamespace(open_fresh_chain_session=lambda **_arguments: object())
    observed: list[dict[str, object]] = []

    class _EntryPoint:
        def load(self):
            return lambda: factory

    def _entry_points(**arguments: object):
        observed.append(arguments)
        return (_EntryPoint(),)

    monkeypatch.setattr(importlib.metadata, "entry_points", _entry_points)

    assert (
        cli._installed_dependency_factory(cli.FRESH_CHAIN_PRODUCTION_DEPENDENCY_PROVIDER) is factory
    )
    assert observed == [
        {
            "group": "infinity_context.publishable_run_dependencies",
            "name": "mem0-infinity-production-v1",
        }
    ]
