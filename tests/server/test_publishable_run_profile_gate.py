from __future__ import annotations

from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
    SchedulerRunnerError,
    open_publishable_production_composition,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_contracts import (
    PublishableRunError,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_orchestrator import (
    PublishableRunOrchestrator,
)
from publishable_run_outer_test_support import (
    ProviderFreeDependencyFactory,
    private_run_files,
)


def test_active_blocked_profile_rejects_before_state_or_provider_session(tmp_path: Path) -> None:
    files = private_run_files(tmp_path)
    factory = ProviderFreeDependencyFactory()

    with pytest.raises(
        PublishableRunError,
        match="publishable_run_execution_profile_blocked",
    ):
        PublishableRunOrchestrator(
            dependency_factory=factory,
            composition_opener=factory.open_composition,
        ).run(config=files.config, secrets=files.secrets)

    assert factory.session_modes == []
    assert factory.provider_inputs == []
    assert factory.state.composition_modes == []
    assert not (files.config.publication_receipt_path.parent / ".provider").exists()
    assert not files.config.official_case_authority_path.exists()
    assert not any(path.exists() for path in files.config.scheduler_database_paths)
    assert not files.config.suite_seal_database_path.exists()
    assert not files.config.publication_receipt_path.exists()


def test_production_composition_rechecks_active_profile_before_capabilities(
    tmp_path: Path,
) -> None:
    factory = ProviderFreeDependencyFactory()

    with pytest.raises(
        SchedulerRunnerError,
        match="publishable_production_execution_authority_invalid",
    ):
        open_publishable_production_composition(
            mode=PublishableProductionOpenMode.CREATE,
            suite=factory.suite,
            run_stores=(),
            extraction_suite=object(),
            official_case_authority=object(),
            retrieval_capture_authority=object(),
            output_cipher=object(),
            bridge_keys=object(),
            bridge_fleet_readiness=object(),
            bridge_transport=object(),
            bridge_journal=object(),
            clock=lambda: 0,
            lease_id_factory=lambda: "must-not-open",
        )

    assert factory.session_modes == []
    assert factory.state.composition_modes == []
    assert list(tmp_path.iterdir()) == []
