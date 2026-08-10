from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import BridgeJournal
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_run_orchestrator as orchestrator_module,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
    verify_publishable_run_attestation,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
    canonical_adapter_json,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_orchestrator import (
    PublishableRunOrchestrator,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    SchedulerStepDisposition,
)
from publishable_run_outer_test_support import (
    FakeRunScenario,
    ProviderFreeDependencyFactory,
    private_run_files,
    sha,
)


def test_invalid_adapter_session_is_closed_before_rejection(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)

    class InvalidSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    session = InvalidSession()

    class Factory:
        def open_session(self, **_arguments: object) -> InvalidSession:
            return session

    with pytest.raises(PublishableRunError, match="publishable_run_session_invalid"):
        PublishableRunOrchestrator(dependency_factory=Factory()).run(
            config=files.config,
            secrets=files.secrets,
        )

    assert session.closed is True


@pytest.mark.parametrize(
    "outer_key_index",
    range(5),
    ids=("official-cases", "locomo", "longmemeval", "suite-seal", "publication"),
)
def test_cross_layer_outer_key_reuse_rejects_before_provider_or_state_work(
    tmp_path: Path,
    outer_key_index: int,
) -> None:
    files = private_run_files(tmp_path)
    outer_keys = (
        files.secrets.official_case_authentication_key,
        *files.secrets.scheduler_authentication_keys,
        files.secrets.suite_seal_authentication_key,
        files.secrets.publication_receipt_authentication_key,
    )
    adapter_secrets = files.secrets.adapter_secrets()
    adapter_secrets["output_cipher_key_hex"] = outer_keys[outer_key_index].hex()
    crossed = replace(
        files.secrets,
        adapter_secrets_json=canonical_adapter_json(adapter_secrets, secret=True),
    )
    factory = ProviderFreeDependencyFactory()

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_cross_layer_secret_reuse",
    ):
        PublishableRunOrchestrator(
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        ).run(config=files.config, secrets=crossed)

    assert factory.session_modes == []
    assert not (files.config.publication_receipt_path.parent / ".provider").exists()
    assert not files.config.official_case_authority_path.exists()


@pytest.mark.parametrize("residue", ("one-scheduler", "receipt-only"))
def test_partial_state_generation_rejects_before_opening_adapter_session(
    tmp_path: Path,
    residue: str,
) -> None:
    files = private_run_files(tmp_path)
    path = (
        files.config.scheduler_database_paths[0]
        if residue == "one-scheduler"
        else files.config.publication_receipt_path
    )
    path.write_bytes(b"{}")
    path.chmod(0o600)
    factory = ProviderFreeDependencyFactory()

    with pytest.raises(PublishableRunError, match="publishable_run_state_generation_partial"):
        PublishableRunOrchestrator(
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        ).run(config=files.config, secrets=files.secrets)

    assert factory.session_modes == []
    assert not files.config.official_case_authority_path.exists()


def test_tampered_receipt_rejects_before_opening_adapter_session(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)
    for path in (*files.config.scheduler_database_paths, files.config.suite_seal_database_path):
        path.touch(mode=0o600)
    receipt = PublishableRunAttestation.create(
        suite_authority_sha256=sha("tampered-suite"),
        ordered_run_authority_sha256=(sha("tampered-run-0"), sha("tampered-run-1")),
        official_case_authority_root_sha256=sha("tampered-cases"),
        retrieval_authority_root_sha256=sha("tampered-retrieval"),
        extraction_suite_readback_sha256=sha("tampered-extraction"),
        production_composition_authority_sha256=sha("tampered-composition"),
        terminal_disposition=SchedulerStepDisposition.BLOCKED.value,
        case_count=0,
        evaluation_call_count=0,
        extraction_operation_count=0,
        provider_intent_count=0,
        provider_result_count=0,
        provider_call_count=0,
        provider_accounting_complete=True,
        authentication_key_id=files.config.publication_key_id,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
    )
    payload = receipt.payload()
    payload["authentication_hmac_sha256"] = "0" * 64
    files.config.publication_receipt_path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    files.config.publication_receipt_path.chmod(0o600)
    factory = ProviderFreeDependencyFactory()

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_receipt_authentication_invalid",
    ):
        PublishableRunOrchestrator(
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        ).run(config=files.config, secrets=files.secrets)

    assert factory.session_modes == []


@pytest.mark.parametrize(
    ("scenario", "expected_disposition", "expected_accounting_complete"),
    (
        (
            FakeRunScenario(SchedulerStepDisposition.BLOCKED, 127, 127),
            SchedulerStepDisposition.BLOCKED.value,
            True,
        ),
        (
            FakeRunScenario(
                SchedulerStepDisposition.EVALUATION_COMPLETE,
                PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
                PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT - 1,
            ),
            SchedulerStepDisposition.SEALED.value,
            False,
        ),
    ),
    ids=("incomplete", "provider-count-mismatch"),
)
def test_incomplete_or_mismatched_run_cannot_be_publishable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: FakeRunScenario,
    expected_disposition: str,
    expected_accounting_complete: bool,
) -> None:
    files = private_run_files(tmp_path)
    factory = ProviderFreeDependencyFactory(scenario=scenario)
    monkeypatch.setattr(BridgeJournal, "statistics", factory.patched_statistics)

    receipt = PublishableRunOrchestrator(
        dependency_factory=factory,
        composition_opener=factory.open_composition,
    ).run(config=files.config, secrets=files.secrets)

    assert receipt.publishable is False
    assert receipt.terminal_disposition == expected_disposition
    assert receipt.provider_intent_count == scenario.provider_count
    assert receipt.provider_result_count == scenario.provider_count
    assert receipt.provider_call_count == scenario.provider_count
    assert receipt.provider_accounting_complete is expected_accounting_complete
    assert verify_publishable_run_attestation(
        receipt,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=files.config.publication_key_id,
    )
    assert json.loads(files.config.publication_receipt_path.read_bytes()) == receipt.payload()

    if expected_disposition == SchedulerStepDisposition.BLOCKED.value:
        assert receipt.suite_seal_sha256 is None
        assert factory.state.composition_modes == [PublishableProductionOpenMode.CREATE]
    else:
        assert receipt.suite_seal_sha256 is not None
        assert factory.state.dispatch_accounting == [scenario.provider_count, 0]


def test_seal_crash_preserves_authority_checkpoint_and_rejects_root_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = private_run_files(tmp_path)
    factory = ProviderFreeDependencyFactory()
    monkeypatch.setattr(BridgeJournal, "statistics", factory.patched_statistics)
    persist = orchestrator_module._persist_exact_receipt

    def crash_before_terminal_receipt(receipt, *, config, secrets):
        if receipt.terminal_disposition == SchedulerStepDisposition.SEALED.value:
            raise RuntimeError("synthetic_crash_after_seal")
        return persist(receipt, config=config, secrets=secrets)

    monkeypatch.setattr(
        orchestrator_module,
        "_persist_exact_receipt",
        crash_before_terminal_receipt,
    )
    orchestrator = PublishableRunOrchestrator(
        dependency_factory=factory,
        composition_opener=factory.open_composition,
    )

    with pytest.raises(RuntimeError, match="synthetic_crash_after_seal"):
        orchestrator.run(config=files.config, secrets=files.secrets)

    checkpoint = PublishableRunAttestation.from_payload(
        json.loads(files.config.publication_receipt_path.read_bytes())
    )
    assert checkpoint.terminal_disposition == "prepared"
    assert checkpoint.publishable is False
    assert factory.state.sealed is True
    assert verify_publishable_run_attestation(
        checkpoint,
        authentication_secret=files.secrets.publication_receipt_authentication_key,
        expected_authentication_key_id=files.config.publication_key_id,
    )
    dispatch_accounting = list(factory.state.dispatch_accounting)
    original_retrieval_root = factory.retrieval_authority_root_sha256
    factory.retrieval_authority_root_sha256 = sha("substituted-retrieval-authority")
    monkeypatch.setattr(orchestrator_module, "_persist_exact_receipt", persist)

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_authority_binding_divergent",
    ):
        orchestrator.run(config=files.config, secrets=files.secrets)

    assert factory.state.dispatch_accounting == dispatch_accounting
    assert (
        files.config.publication_receipt_path.read_bytes()
        == json.dumps(
            checkpoint.payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )

    factory.retrieval_authority_root_sha256 = original_retrieval_root
    completed = orchestrator.run(config=files.config, secrets=files.secrets)

    assert completed.publishable is True
    assert completed.terminal_disposition == SchedulerStepDisposition.SEALED.value
    assert factory.state.dispatch_accounting == [*dispatch_accounting, 0, 0]


def test_hostile_provider_receives_only_redacted_provider_inputs_without_signing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = private_run_files(tmp_path)
    delegate = ProviderFreeDependencyFactory(
        scenario=FakeRunScenario(SchedulerStepDisposition.BLOCKED, 1, 1)
    )
    monkeypatch.setattr(BridgeJournal, "statistics", delegate.patched_statistics)

    class HostileProvider:
        def open_session(self, *, inputs, mode):
            assert not hasattr(inputs, "__dict__")
            assert not hasattr(inputs, "publication_receipt_authentication_key")
            assert not hasattr(inputs, "publication_signing_key")
            assert not hasattr(inputs, "official_case_authentication_key")
            assert not hasattr(inputs, "scheduler_authentication_keys")
            assert not hasattr(inputs, "suite_seal_authentication_key")
            rendered = repr(inputs).encode()
            signing_key = files.secrets.publication_receipt_authentication_key
            assert signing_key not in inputs.adapter_config_json
            assert signing_key not in inputs.adapter_secrets_json
            assert signing_key.hex().encode() not in inputs.adapter_config_json
            assert signing_key.hex().encode() not in inputs.adapter_secrets_json
            assert signing_key not in rendered
            with pytest.raises(TypeError, match="private material"):
                inputs.__reduce_ex__(5)
            return delegate.open_session(inputs=inputs, mode=mode)

    receipt = PublishableRunOrchestrator(
        dependency_factory=HostileProvider(),
        composition_opener=delegate.open_composition,
    ).run(config=files.config, secrets=files.secrets)

    assert receipt.publishable is False
    assert receipt.provider_call_count == 1
