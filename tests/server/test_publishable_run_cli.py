from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.features.subscription_runtime_bridge import BridgeJournal
from infinity_context_server.publishable_durable_scheduler import (
    SchedulerStepDisposition,
)
from infinity_context_server.publishable_durable_scheduler import publishable_run_cli as cli_module
from infinity_context_server.publishable_durable_scheduler import (
    publishable_run_orchestrator as orchestrator_module,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
    verify_publishable_run_attestation,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_cli import (
    PUBLISHABLE_RUN_CLI_FAILURE,
    PUBLISHABLE_RUN_CLI_INCOMPLETE,
    PUBLISHABLE_RUN_CLI_SCHEMA,
    PUBLISHABLE_RUN_CLI_SUCCESS,
    main,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP,
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
)
from publishable_mem0_v5.run_provider import (
    PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
    Mem0InfinityPublishableRunDependencyFactory,
)
from publishable_run_outer_test_support import (
    PRIVATE_ADAPTER_SENTINEL,
    FakeRunScenario,
    ProviderFreeDependencyFactory,
    private_run_files,
)

_CRASHED_PROVIDER_PREFIX = 137


@pytest.fixture(autouse=True)
def _admitted_execution_contract_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise CLI lifecycle below the separately covered static profile gate."""

    monkeypatch.setattr(
        orchestrator_module,
        "_issue_publishable_execution_authority",
        object,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "_require_publishable_execution_authority",
        lambda *_arguments, **_keywords: None,
    )


def test_cli_crash_restart_and_exact_resume_emit_one_authenticated_public_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = private_run_files(tmp_path)
    factory = ProviderFreeDependencyFactory(crash_after_committed_count=_CRASHED_PROVIDER_PREFIX)
    monkeypatch.setattr(BridgeJournal, "statistics", factory.patched_statistics)

    assert (
        main(
            files.argv,
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        )
        == PUBLISHABLE_RUN_CLI_FAILURE
    )
    crashed = capsys.readouterr()
    assert crashed.out == ""
    assert json.loads(crashed.err) == {
        "ok": False,
        "publishable": False,
        "reason_code": "publishable_run_failed",
        "schema_version": PUBLISHABLE_RUN_CLI_SCHEMA,
    }
    assert files.config.official_case_authority_path.exists()
    assert all(path.exists() for path in files.config.scheduler_database_paths)
    assert files.config.suite_seal_database_path.exists()
    checkpoint = PublishableRunAttestation.from_payload(
        json.loads(files.config.publication_receipt_path.read_bytes())
    )
    assert checkpoint.terminal_disposition == "prepared"
    assert checkpoint.publishable is False
    assert checkpoint.evaluation_call_count == 0
    assert checkpoint.provider_intent_count == checkpoint.provider_result_count == 0
    assert verify_publishable_run_attestation(
        checkpoint,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=files.config.publication_key_id,
    )
    assert factory.state.committed_call_count == _CRASHED_PROVIDER_PREFIX
    assert factory.state.provider_count == _CRASHED_PROVIDER_PREFIX
    assert factory.state.dispatch_accounting == [_CRASHED_PROVIDER_PREFIX]

    assert (
        main(
            files.argv,
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        )
        == PUBLISHABLE_RUN_CLI_SUCCESS
    )
    completed = capsys.readouterr()
    assert completed.err == ""
    payload = json.loads(completed.out)
    receipt = PublishableRunAttestation.from_payload(payload)
    assert receipt.publishable is True
    assert receipt.case_count == PUBLISHABLE_SUITE_CASE_COUNT
    assert receipt.evaluation_call_count == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    assert receipt.extraction_operation_count == PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT
    assert receipt.provider_intent_count == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    assert receipt.provider_result_count == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    assert receipt.provider_call_count == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT
    assert receipt.provider_accounting_complete is True
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=files.config.publication_key_id,
    )
    assert all(needle not in completed.out for needle in files.private_needles())
    persisted_before_resume = files.config.publication_receipt_path.read_bytes()
    provider_count_before_resume = factory.state.provider_count

    assert (
        main(
            files.argv,
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        )
        == PUBLISHABLE_RUN_CLI_SUCCESS
    )
    resumed = capsys.readouterr()
    assert resumed.err == ""
    assert resumed.out == completed.out
    assert files.config.publication_receipt_path.read_bytes() == persisted_before_resume
    assert factory.state.provider_count == provider_count_before_resume
    assert [mode.value for mode in factory.session_modes] == ["create", "resume", "resume"]
    assert [mode.value for mode in factory.state.composition_modes] == [
        "create",
        "resume",
        "resume",
        "resume",
        "resume",
    ]
    assert factory.state.dispatch_accounting == [
        _CRASHED_PROVIDER_PREFIX,
        PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT - _CRASHED_PROVIDER_PREFIX,
        0,
        0,
        0,
    ]
    assert len(factory.case_authority_roots) == 3
    assert len(set(factory.case_authority_roots)) == 1


def test_cli_emits_authenticated_incomplete_receipt_and_exit_three(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = private_run_files(tmp_path)
    scenario = FakeRunScenario(SchedulerStepDisposition.BLOCKED, 127, 127)
    factory = ProviderFreeDependencyFactory(scenario=scenario)
    monkeypatch.setattr(BridgeJournal, "statistics", factory.patched_statistics)

    assert (
        main(
            files.argv,
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        )
        == PUBLISHABLE_RUN_CLI_INCOMPLETE
    )

    captured = capsys.readouterr()
    assert captured.err == ""
    receipt = PublishableRunAttestation.from_payload(json.loads(captured.out))
    assert receipt.publishable is False
    assert receipt.terminal_disposition == SchedulerStepDisposition.BLOCKED.value
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=files.config.publication_key_id,
    )
    assert json.loads(files.config.publication_receipt_path.read_bytes()) == receipt.payload()
    assert all(needle not in captured.out for needle in files.private_needles())


def test_cli_redacts_private_adapter_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = private_run_files(tmp_path)

    class RaisingFactory:
        def open_session(self, **_arguments: object) -> object:
            raise RuntimeError(PRIVATE_ADAPTER_SENTINEL)

    assert main(files.argv, dependency_factory=RaisingFactory()) == PUBLISHABLE_RUN_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert PRIVATE_ADAPTER_SENTINEL not in captured.err
    assert json.loads(captured.err) == {
        "ok": False,
        "publishable": False,
        "reason_code": "publishable_run_failed",
        "schema_version": PUBLISHABLE_RUN_CLI_SCHEMA,
    }


def test_cli_requires_explicit_live_provider_authorization(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = private_run_files(tmp_path)

    assert main(files.argv[:-1], dependency_factory=object()) == PUBLISHABLE_RUN_CLI_FAILURE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "ok": False,
        "publishable": False,
        "reason_code": "publishable_run_failed",
        "schema_version": PUBLISHABLE_RUN_CLI_SCHEMA,
    }
    assert not files.config.official_case_authority_path.exists()


def test_installed_dependency_factory_requires_one_valid_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = SimpleNamespace(open_session=lambda **_arguments: None)
    entry_point = SimpleNamespace(load=lambda: expected)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda **_arguments: (entry_point,),
    )

    assert cli_module._installed_dependency_factory("tests.provider-free") is expected


@pytest.mark.parametrize(
    "entry_points",
    (
        (),
        (SimpleNamespace(load=lambda: object()),),
        (
            SimpleNamespace(load=lambda: object()),
            SimpleNamespace(load=lambda: object()),
        ),
    ),
    ids=("missing", "invalid", "duplicate"),
)
def test_installed_dependency_factory_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    entry_points: tuple[object, ...],
) -> None:
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda **_arguments: entry_points,
    )

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_dependency_provider_unavailable",
    ):
        cli_module._installed_dependency_factory("tests.provider-free")


def test_root_distribution_registers_publishable_run_console_script() -> None:
    project_root = Path(__file__).resolve().parents[2]
    with (project_root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)
    with (project_root / "packages/infinity_context_server/pyproject.toml").open("rb") as stream:
        server_project = tomllib.load(stream)
    with (project_root / "uv.lock").open("rb") as stream:
        lock = tomllib.load(stream)

    assert project["project"]["scripts"]["infinity-context-publishable-run"] == (
        "infinity_context_server.publishable_durable_scheduler.publishable_run_cli:main"
    )
    assert project["project"]["entry-points"][PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP][
        PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME
    ] == ("publishable_mem0_v5.run_provider:Mem0InfinityPublishableRunDependencyFactory")
    assert "cryptography==50.0.0" in project["project"]["dependencies"]
    assert "cryptography>=50.0.0,<51.0.0" in server_project["project"]["dependencies"]
    cryptography = tuple(
        package for package in lock["package"] if package["name"] == "cryptography"
    )
    assert len(cryptography) == 1
    assert cryptography[0]["version"] == "50.0.0"


def test_installed_metadata_loads_production_publishable_run_provider() -> None:
    matches = tuple(
        importlib.metadata.entry_points(
            group=PUBLISHABLE_RUN_DEPENDENCY_ENTRYPOINT_GROUP,
            name=PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME,
        )
    )

    assert len(matches) == 1
    loaded = matches[0].load()
    assert loaded is Mem0InfinityPublishableRunDependencyFactory
    provider = cli_module._installed_dependency_factory(PUBLISHABLE_MEM0_INFINITY_PROVIDER_NAME)
    assert type(provider) is Mem0InfinityPublishableRunDependencyFactory
    assert callable(provider.open_session)
    assert not hasattr(provider, "mint_activation")
    assert not hasattr(provider, "mint_publication")
