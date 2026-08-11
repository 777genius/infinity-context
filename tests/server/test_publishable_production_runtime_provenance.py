"""Provider-free rejection tests for production runtime provenance."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeAuthority,
    BridgeJournal,
    BridgePoolAuthority,
    HmacJournalIntegrity,
)
from infinity_context_server.features.subscription_runtime_bridge.process_contracts import (
    BridgeFleetReadinessReceipt,
)
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
    SchedulerBridgeBootAuthority,
    SchedulerRunnerError,
    build_publishable_production_runtime_provenance,
    open_publishable_production_composition,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition as production_composition,
)
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter as scheduler_bridge,
)
from scheduler_subscription_bridge_composition_test_support import (
    BRIDGE_JOURNAL_KEY,
    bridge_fleet_readiness,
    official_suite_and_manifests,
    run_store_specs,
    sha,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
    BoundedAttestedFakeTransport,
    CountingOfficialCaseReader,
    CountingRetrievalEvidenceReader,
    DeterministicNonceSource,
    DeterministicOutputKeyResolver,
    synthetic_extraction_suite_readback,
)
from subscription_runtime_bridge_test_support import FakeSecrets


@pytest.fixture
def _admitted_execution_contract_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise provenance below the separately covered static profile gate."""

    monkeypatch.setattr(
        production_composition,
        "_require_active_publishable_production_execution",
        lambda _suite: None,
    )


def test_unadmitted_caller_rejects_before_runtime_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = bridge_fleet_readiness()
    suite, _, _, _ = official_suite_and_manifests(readiness)
    provenance_calls = 0

    def forbidden_runtime_provenance(**_keywords: object) -> None:
        nonlocal provenance_calls
        provenance_calls += 1
        raise AssertionError("unadmitted caller reached runtime provenance")

    monkeypatch.setattr(
        production_composition,
        "build_publishable_production_runtime_provenance",
        forbidden_runtime_provenance,
    )

    with pytest.raises(
        SchedulerRunnerError,
        match="publishable_production_execution_authority_invalid",
    ):
        open_publishable_production_composition(
            mode=PublishableProductionOpenMode.CREATE,
            suite=suite,
            run_stores=(),
            extraction_suite=object(),
            official_case_authority=object(),
            retrieval_capture_authority=object(),
            output_cipher=object(),
            bridge_keys=object(),
            bridge_fleet_readiness=readiness,
            bridge_transport=object(),
            bridge_journal=object(),
            clock=lambda: 0,
            lease_id_factory=lambda: "must-not-open",
        )

    assert provenance_calls == 0


def test_runtime_provenance_admission_binds_exact_backends_and_every_bridge() -> None:
    readiness = bridge_fleet_readiness()
    suite, _, _, _ = official_suite_and_manifests(readiness)

    provenance = build_publishable_production_runtime_provenance(
        suite=suite,
        bridge_fleet_readiness=readiness,
    )

    assert provenance.scheduler_runtime_provenance_sha256 == suite.runtime_provenance_sha256
    assert provenance.ordered_backend_identities == suite.ordered_runs[0].backends
    assert provenance.ordered_backend_identities == suite.ordered_runs[1].backends
    assert provenance.bridge_pool_authority_sha256 == readiness.pool.commitment_sha256
    assert provenance.bridge_fleet_readiness_sha256 == readiness.commitment_sha256
    assert provenance.bridge_boot_nonce_sha256 == readiness.commitment_sha256
    assert provenance.bridge_boot_authority_sha256 == suite.bridge_boot.commitment_sha256
    assert tuple(item.bridge_index for item in provenance.ordered_bridges) == (0, 1, 2)
    for admitted, bridge, launch in zip(
        provenance.ordered_bridges,
        readiness.pool.bridges,
        readiness.launches,
        strict=True,
    ):
        assert admitted.bridge_id == bridge.bridge_id == launch.pending.bridge_id
        assert admitted.account_name == launch.pending.account_name
        assert admitted.bridge_authority_sha256 == bridge.commitment_sha256
        assert admitted.runtime_authority_sha256 == launch.runtime_authority_sha256
        assert admitted.readiness_receipt_sha256 == launch.commitment_sha256
        assert admitted.public_model == "gpt-5.6-sol"
        assert admitted.reasoning_effort == "high"
        assert admitted.service_tier == "priority"
        assert admitted.base_instructions_sha256 == bridge.base_instructions_sha256


def test_forged_suite_boot_nonce_rejects_before_journal_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _admitted_execution_contract_test: None,
) -> None:
    trusted = bridge_fleet_readiness()
    suite, runs, manifests, _ = official_suite_and_manifests(trusted)
    forged = replace(
        suite,
        bridge_boot=replace(suite.bridge_boot, boot_nonce_sha256=sha("forged-suite-nonce")),
    )

    assert forged.commitment_sha256 != suite.commitment_sha256
    _assert_pre_journal_rejection(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        trusted_suite=suite,
        opened_suite=forged,
        runs=runs,
        manifests=manifests,
        readiness=trusted,
        error="publishable_production_runtime_provenance_mismatch",
    )


def test_compatible_foreign_fleet_rejects_before_journal_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _admitted_execution_contract_test: None,
) -> None:
    trusted = bridge_fleet_readiness()
    suite, runs, manifests, _ = official_suite_and_manifests(trusted)
    foreign_pool = BridgePoolAuthority(
        pool_id="foreign-publishable-scheduler-pool",
        bridges=tuple(
            replace(
                bridge,
                bridge_id=f"foreign-scheduler-bridge-{index}",
                origin=f"http://127.0.0.1:{46_200 + index}",
                account_binding_hmac_sha256=sha(f"foreign-account:{index}"),
            )
            for index, bridge in enumerate(trusted.pool.bridges)
        ),
    )
    foreign = bridge_fleet_readiness(foreign_pool)

    assert foreign.commitment_sha256 != trusted.commitment_sha256
    _assert_pre_journal_rejection(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        trusted_suite=suite,
        opened_suite=suite,
        runs=runs,
        manifests=manifests,
        readiness=foreign,
        error="publishable_production_runtime_provenance_mismatch",
    )


def test_account_and_port_reorder_rejects_before_journal_or_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _admitted_execution_contract_test: None,
) -> None:
    trusted = bridge_fleet_readiness()
    suite, runs, manifests, _ = official_suite_and_manifests(trusted)
    order = (1, 0, 2)
    reordered = BridgeFleetReadinessReceipt(
        pool=BridgePoolAuthority(
            pool_id=trusted.pool.pool_id,
            bridges=tuple(trusted.pool.bridges[index] for index in order),
        ),
        launches=tuple(trusted.launches[index] for index in order),
    )

    assert tuple(item.pending.account_name for item in reordered.launches) != tuple(
        item.pending.account_name for item in trusted.launches
    )
    assert tuple(item.origin for item in reordered.pool.bridges) != tuple(
        item.origin for item in trusted.pool.bridges
    )
    _assert_pre_journal_rejection(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        trusted_suite=suite,
        opened_suite=suite,
        runs=runs,
        manifests=manifests,
        readiness=reordered,
        error="publishable_production_runtime_provenance_mismatch",
    )


def test_matching_default_tier_fleet_and_forged_suite_are_rejected_pre_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _admitted_execution_contract_test: None,
) -> None:
    trusted = bridge_fleet_readiness()
    suite, runs, manifests, _ = official_suite_and_manifests(trusted)
    bridge = trusted.pool.bridges[0]
    default_type = type(
        "DefaultTierBridgeAuthority",
        (BridgeAuthority,),
        {"SERVICE_TIER": "default"},
    )
    default_bridge = default_type(
        bridge_id=bridge.bridge_id,
        origin=bridge.origin,
        account_binding_hmac_sha256=bridge.account_binding_hmac_sha256,
        public_model=bridge.public_model,
        base_instructions_sha256=bridge.base_instructions_sha256,
        route=bridge.route,
    )
    default_pool = BridgePoolAuthority(
        pool_id=trusted.pool.pool_id,
        bridges=(default_bridge, *trusted.pool.bridges[1:]),
    )
    default_readiness = bridge_fleet_readiness(default_pool)
    forged_boot = SchedulerBridgeBootAuthority(
        bridge_id=default_pool.pool_id,
        implementation_sha256=(
            scheduler_bridge.SCHEDULER_SUBSCRIPTION_BRIDGE_IMPLEMENTATION_SHA256
        ),
        runtime_authority_sha256=default_pool.commitment_sha256,
        boot_nonce_sha256=default_readiness.commitment_sha256,
        receipt_verifier_policy_sha256=(
            scheduler_bridge.SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256
        ),
    )
    forged_suite = replace(suite, bridge_boot=forged_boot)

    assert forged_suite.bridge_boot.runtime_authority_sha256 == default_pool.commitment_sha256
    _assert_pre_journal_rejection(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        trusted_suite=suite,
        opened_suite=forged_suite,
        runs=runs,
        manifests=manifests,
        readiness=default_readiness,
        error="scheduler_subscription_bridge_runtime_authority_invalid",
    )


def _assert_pre_journal_rejection(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    trusted_suite,
    opened_suite,
    runs,
    manifests,
    readiness: BridgeFleetReadinessReceipt,
    error: str,
) -> None:
    specs = run_store_specs(tmp_path / "scheduler", trusted_suite, runs, manifests)
    extraction = synthetic_extraction_suite_readback(trusted_suite, specs)
    secrets = FakeSecrets(readiness.pool)
    transport = BoundedAttestedFakeTransport(readiness.pool, secrets)
    cases = CountingOfficialCaseReader()
    retrieval = CountingRetrievalEvidenceReader()
    journal = BridgeJournal.create(
        tmp_path / "bridge" / "journal.sqlite3",
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    audit_calls = 0
    lease_calls = 0

    def forbidden_audit(_journal: BridgeJournal) -> None:
        nonlocal audit_calls
        audit_calls += 1
        raise AssertionError("runtime mismatch reached bridge journal audit")

    def lease_id() -> str:
        nonlocal lease_calls
        lease_calls += 1
        return "runtime-provenance-lease"

    monkeypatch.setattr(BridgeJournal, "audit", forbidden_audit)
    try:
        with pytest.raises(SchedulerRunnerError, match=error):
            open_publishable_production_composition(
                mode=PublishableProductionOpenMode.CREATE,
                suite=opened_suite,
                run_stores=specs,
                extraction_suite=extraction,
                official_case_authority=cases,
                retrieval_capture_authority=retrieval,
                output_cipher=Aes256GcmOutputCipher(
                    key_resolver=DeterministicOutputKeyResolver(),
                    maximum_ciphertext_bytes=1024 * 1024,
                    nonce_source=DeterministicNonceSource(),
                ),
                bridge_keys=secrets,
                bridge_fleet_readiness=readiness,
                bridge_transport=transport,
                bridge_journal=journal,
                clock=lambda: 2_000,
                lease_id_factory=lease_id,
            )
        statistics = journal.statistics()
        assert (statistics.event_count, statistics.intent_count, statistics.result_count) == (
            0,
            0,
            0,
        )
    finally:
        journal.close()

    assert audit_calls == 0
    assert lease_calls == 0
    assert transport.call_count == 0
    assert cases.read_count == 0
    assert retrieval.read_count == 0
    assert all(not spec.database_path.exists() for spec in specs)
    assert not (specs[0].private_directory / "suite-seal.sqlite3").exists()
