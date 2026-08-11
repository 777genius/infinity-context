"""Outer fail-closed and isolation tests for the installed canary lifecycle."""

from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_canary_orchestrator as canary,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from publishable_run_outer_test_support import private_run_files


class _RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def open_session(self, **arguments: object) -> object:
        self.calls.append(arguments)
        raise AssertionError("provider session must not open")


def test_missing_official_authority_rejects_before_state_or_provider(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)
    factory = _RecordingFactory()

    with pytest.raises(
        PublishableRunError,
        match="publishable_canary_official_case_authority_missing",
    ):
        canary.PublishableCanaryOrchestrator(dependency_factory=factory).run(
            config=files.config,
            secrets=files.secrets,
        )

    assert factory.calls == []
    assert not (
        files.config.publication_receipt_path.parent / canary.PUBLISHABLE_CANARY_STATE_DIRECTORY
    ).exists()


def test_layout_ignores_caller_batch_and_domain_separates_full_run_state(
    tmp_path: Path,
) -> None:
    files = private_run_files(tmp_path)
    files.config.official_case_authority_path.touch(mode=0o600)

    layout = canary._open_layout(files.config, files.secrets)

    assert layout.mode is PublishableProductionOpenMode.CREATE
    assert layout.config.max_dispatches_per_batch == 4
    assert layout.config.official_case_authority_path == files.config.official_case_authority_path
    assert layout.config.scheduler_database_paths != files.config.scheduler_database_paths
    assert layout.config.suite_seal_database_path != files.config.suite_seal_database_path
    assert layout.config.publication_receipt_path != files.config.publication_receipt_path
    assert layout.config.adapter_config_json == files.config.adapter_config_json
    assert layout.secrets.adapter_secrets_json == files.secrets.adapter_secrets_json
    assert layout.secrets.official_case_authentication_key == (
        files.secrets.official_case_authentication_key
    )
    assert layout.secrets.scheduler_authentication_keys != (
        files.secrets.scheduler_authentication_keys
    )
    assert layout.secrets.suite_seal_authentication_key != (
        files.secrets.suite_seal_authentication_key
    )
    assert layout.secrets.publication_receipt_authentication_key != (
        files.secrets.publication_receipt_authentication_key
    )
    assert stat.S_IMODE(layout.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(layout.provider_root.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    "full_path_role",
    ("official", "scheduler", "seal", "receipt"),
)
def test_canary_root_cannot_overlap_any_full_run_state_path(
    tmp_path: Path,
    full_path_role: str,
) -> None:
    files = private_run_files(tmp_path)
    root = files.config.publication_receipt_path.parent / canary.PUBLISHABLE_CANARY_STATE_DIRECTORY
    changes: dict[str, object] = {}
    if full_path_role == "official":
        changes["official_case_authority_path"] = root
    elif full_path_role == "scheduler":
        changes["scheduler_database_paths"] = (
            root,
            files.config.scheduler_database_paths[1],
        )
    elif full_path_role == "seal":
        changes["suite_seal_database_path"] = root
    else:
        changes["publication_receipt_path"] = root
    config = replace(files.config, **changes)

    with pytest.raises(
        PublishableRunError,
        match="publishable_canary_state_path_overlap",
    ):
        canary._open_layout(config, files.secrets)

    assert not root.exists()


def test_terminal_evidence_cannot_resume_incomplete_scheduler_state() -> None:
    receipts = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    paired = "e" * 64
    prior = SimpleNamespace(
        provider_accounting_complete=True,
        measured_provider_intent_count=4,
        measured_provider_result_count=4,
        measured_provider_call_count=4,
        ordered_provider_receipt_sha256=receipts,
        paired_outcome_evidence_sha256=paired,
    )
    partial = canary.PublishableCanaryMeasurement(
        committed_call_count=3,
        provider_intent_count=3,
        provider_result_count=3,
        ordered_receipt_sha256=receipts[:3],
        paired_path_evidence_sha256=None,
    )

    with pytest.raises(
        PublishableRunError,
        match="publishable_canary_terminal_state_divergent",
    ):
        canary._require_prior_measurement(prior, partial)  # type: ignore[arg-type]

    complete = canary.PublishableCanaryMeasurement(4, 4, 4, receipts, paired)
    canary._require_prior_measurement(prior, complete)  # type: ignore[arg-type]


@pytest.mark.parametrize("residue", ("partial-state", "tampered-evidence"))
def test_partial_or_tampered_canary_state_rejects_before_provider(
    tmp_path: Path,
    residue: str,
) -> None:
    files = private_run_files(tmp_path)
    files.config.official_case_authority_path.touch(mode=0o600)
    layout = canary._open_layout(files.config, files.secrets)
    paths = (
        *layout.config.scheduler_database_paths,
        layout.config.suite_seal_database_path,
    )
    selected = paths[:1] if residue == "partial-state" else paths
    for path in selected:
        path.touch(mode=0o600)
    if residue == "tampered-evidence":
        layout.config.publication_receipt_path.write_bytes(b"{}")
        layout.config.publication_receipt_path.chmod(0o600)
    factory = _RecordingFactory()

    expected = (
        "publishable_canary_state_generation_partial"
        if residue == "partial-state"
        else "publishable_canary_activation_evidence_invalid"
    )
    with pytest.raises(PublishableRunError, match=expected):
        canary.PublishableCanaryOrchestrator(dependency_factory=factory).run(
            config=files.config,
            secrets=files.secrets,
        )

    assert factory.calls == []
