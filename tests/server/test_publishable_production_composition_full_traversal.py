"""True provider-free 2,040-pair traversal through the production composition."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest
from infinity_context_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    HmacJournalIntegrity,
    OutputCipherKey,
    SubscriptionRuntimeBridgeAdapter,
    TerminalBridgeCall,
    TerminalOutcome,
)
from infinity_context_server.processes.subscription_runtime_bridge_process_composition import (
    create_new_subscription_runtime_bridge_processes,
    reopen_subscription_runtime_bridge_processes,
)
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
    open_publishable_production_composition,
    scheduler_subscription_bridge_adapter,
    scheduler_subscription_bridge_composition,
)
from infinity_context_server.publishable_durable_scheduler import (
    publishable_production_composition as production_composition,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_contracts import (
    EXPECTED_PAIRED_OUTCOME_COUNT,
)
from infinity_context_server.publishable_durable_scheduler.paired_outcome_production import (
    PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256,
)
from infinity_context_server.publishable_durable_scheduler.publishable_run_attestation import (
    PublishableRunAttestation,
    verify_publishable_run_attestation,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    SchedulerRunnerError,
    SchedulerStepDisposition,
    SchedulerSuiteSealStoreSpec,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_CASE_BYTES_CAP,
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
)
from infinity_context_server.publishable_durable_scheduler.suite_seal_store import (
    SQLiteSchedulerSuiteSealStore,
)
from scheduler_subscription_bridge_composition_test_support import (
    BRIDGE_JOURNAL_KEY,
    official_suite_and_manifests,
    run_store_specs,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
    FULL_TRAVERSAL_CASE_READ_CAP,
    FULL_TRAVERSAL_NONCE_CAP,
    BoundedAttestedFakeTransport,
    CountingOfficialCaseReader,
    CountingRetrievalEvidenceReader,
    DeterministicNonceSource,
    DeterministicOutputKeyResolver,
    synthetic_extraction_suite_readback,
)
from subscription_runtime_bridge_process_test_support import (
    LAUNCHER_KEY,
    FakeProcessHarness,
    build_fleet_spec,
)
from subscription_runtime_bridge_test_support import FakeSecrets


def test_real_launcher_receipts_reject_crosswired_key_and_accept_exact_launch_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_spec = build_fleet_spec(tmp_path / "runtime-processes")
    process_harness = FakeProcessHarness()
    process_harness.install(monkeypatch)
    runtime_processes = create_new_subscription_runtime_bridge_processes(
        process_spec,
        control=process_harness.control,
    )
    readiness = runtime_processes.readiness
    crosswired_key = b"crosswired-launcher-receipt-key-" + b"x" * 32
    assert crosswired_key != LAUNCHER_KEY

    try:
        with pytest.raises(
            SchedulerRunnerError,
            match="scheduler_subscription_bridge_launch_receipt_unauthenticated",
        ):
            scheduler_subscription_bridge_adapter.verify_fleet_launch_receipts(
                readiness,
                FakeSecrets(
                    readiness.pool,
                    launcher_receipt_key=crosswired_key,
                ),
            )

        exact_keys = FakeSecrets(
            readiness.pool,
            launcher_receipt_key=LAUNCHER_KEY,
        )
        assert (
            scheduler_subscription_bridge_adapter.verify_fleet_launch_receipts(
                readiness,
                exact_keys,
            )
            == readiness.pool
        )
        assert all(
            exact_keys.launcher_receipt_key(bridge.bridge_id) == LAUNCHER_KEY
            for bridge in readiness.pool.bridges
        )
    finally:
        runtime_processes.stop_all(reason="launcher-key-regression-complete")


@pytest.fixture
def _admitted_execution_contract_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the traversal below the separately covered production gate."""

    monkeypatch.setattr(
        production_composition,
        "_require_active_publishable_production_execution",
        lambda _suite: None,
    )


def test_production_composition_traverses_exact_2040_pairs_and_replays_with_zero_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _admitted_execution_contract_test: None,
) -> None:
    process_spec = build_fleet_spec(tmp_path / "runtime-processes")
    process_harness = FakeProcessHarness()
    process_harness.install(monkeypatch)
    runtime_processes = create_new_subscription_runtime_bridge_processes(
        process_spec,
        control=process_harness.control,
    )
    readiness = runtime_processes.readiness
    pool = readiness.pool
    suite, runs, manifests, case_groups = official_suite_and_manifests(readiness)
    specs = run_store_specs(tmp_path / "scheduler", suite, runs, manifests)
    extraction_suite = synthetic_extraction_suite_readback(suite, specs)
    secrets = FakeSecrets(pool, launcher_receipt_key=LAUNCHER_KEY)
    transport = BoundedAttestedFakeTransport(pool, secrets)
    case_authority = CountingOfficialCaseReader()
    retrieval_authority = CountingRetrievalEvidenceReader()
    key_resolver = DeterministicOutputKeyResolver()
    nonce_source = DeterministicNonceSource()
    cipher = Aes256GcmOutputCipher(
        key_resolver=key_resolver,
        maximum_ciphertext_bytes=SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
        nonce_source=nonce_source,
    )
    journal_path = tmp_path / "bridge" / "journal.sqlite3"
    journal = BridgeJournal.create(
        journal_path,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    lease_number = 0

    def next_lease_id() -> str:
        nonlocal lease_number
        lease_number += 1
        return f"full-traversal-lease-{lease_number}"

    with pytest.raises(SchedulerRunnerError, match="resume_store_missing"):
        open_publishable_production_composition(
            mode=PublishableProductionOpenMode.RESUME,
            suite=suite,
            run_stores=specs,
            extraction_suite=extraction_suite,
            official_case_authority=case_authority,
            retrieval_capture_authority=retrieval_authority,
            output_cipher=cipher,
            bridge_keys=secrets,
            bridge_fleet_readiness=readiness,
            bridge_transport=transport,
            bridge_journal=journal,
            clock=lambda: 2_000,
            lease_id_factory=next_lease_id,
            lease_duration_ms=1_000,
        )
    assert transport.call_count == 0

    composition = open_publishable_production_composition(
        mode=PublishableProductionOpenMode.CREATE,
        suite=suite,
        run_stores=specs,
        extraction_suite=extraction_suite,
        official_case_authority=case_authority,
        retrieval_capture_authority=retrieval_authority,
        output_cipher=cipher,
        bridge_keys=secrets,
        bridge_fleet_readiness=readiness,
        bridge_transport=transport,
        bridge_journal=journal,
        clock=lambda: 2_000,
        lease_id_factory=next_lease_id,
        lease_duration_ms=1_000,
    )
    assert transport.call_count == 0
    assert composition.runner.case_count == PUBLISHABLE_SUITE_CASE_COUNT == 2_040
    assert composition.runner.evaluation_call_count == (PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT)
    assert composition.runner.production_bridge_adapter_ready is True
    assert composition.scheduler.suite_seal_binding_policy_sha256 == (
        PUBLISHABLE_PAIRED_OUTCOME_SEALING_POLICY_SHA256
    )
    assert composition.runner.readiness_blockers == ()
    assert composition.runner.paid_go_ready is False
    assert composition.fleet_readiness_sha256 == readiness.commitment_sha256
    assert composition.bridge_boot_authority_sha256 == (
        runtime_processes.bridge_boot.commitment_sha256
    )
    assert composition.bridge_pool_authority_sha256 == (
        runtime_processes.bridge_pool.commitment_sha256
    )
    assert composition.admission_commitment_sha256 == composition.authority_sha256
    assert composition.runtime_provenance.scheduler_runtime_provenance_sha256 == (
        suite.runtime_provenance_sha256
    )
    assert composition.runtime_provenance.ordered_backend_identities == (
        suite.ordered_runs[0].backends
    )
    assert composition.runtime_provenance.bridge_boot_nonce_sha256 == readiness.commitment_sha256
    assert (
        tuple(item.public_model for item in composition.runtime_provenance.ordered_bridges)
        == ("gpt-5.6-sol",) * 3
    )
    assert (
        tuple(item.reasoning_effort for item in composition.runtime_provenance.ordered_bridges)
        == ("high",) * 3
    )
    assert (
        tuple(item.service_tier for item in composition.runtime_provenance.ordered_bridges)
        == ("priority",) * 3
    )
    assert suite.bridge_boot == runtime_processes.bridge_boot
    assert process_harness.provider_dispatches == 0
    assert "private" not in repr(composition).lower().replace("private_capabilities", "")

    with pytest.raises(SchedulerRunnerError, match="create_store_exists"):
        open_publishable_production_composition(
            mode=PublishableProductionOpenMode.CREATE,
            suite=suite,
            run_stores=specs,
            extraction_suite=extraction_suite,
            official_case_authority=case_authority,
            retrieval_capture_authority=retrieval_authority,
            output_cipher=cipher,
            bridge_keys=secrets,
            bridge_fleet_readiness=readiness,
            bridge_transport=transport,
            bridge_journal=journal,
            clock=lambda: 2_000,
            lease_id_factory=next_lease_id,
        )
    assert transport.call_count == 0

    ordinal_by_run = [0, 0]
    calls_by_benchmark_backend_stage = {
        (benchmark, backend, stage): 0
        for benchmark in ("locomo", "longmemeval")
        for backend in ("infinity-context", "mem0")
        for stage in ("answer", "judge")
    }
    while True:
        step = composition.runner.run_next()
        if step.disposition is SchedulerStepDisposition.EVALUATION_COMPLETE:
            break
        assert step.disposition is SchedulerStepDisposition.COMMITTED
        assert step.provider_dispatches == 1
        run_index = 0 if step.run_id == runs[0].binding.run_id else 1
        assert step.run_id == runs[run_index].binding.run_id
        ordinal = ordinal_by_run[run_index]
        call = manifests[run_index].shards[ordinal // 256].calls[ordinal % 256]
        assert step.logical_call_id == call.logical_call_id
        key = (
            runs[run_index].binding.profile.benchmark.value,
            call.backend_role,
            call.stage.value,
        )
        calls_by_benchmark_backend_stage[key] += 1
        ordinal_by_run[run_index] += 1

    assert tuple(ordinal_by_run) == tuple(run.binding.profile.call_count for run in runs)
    assert sum(calls_by_benchmark_backend_stage.values()) == 8_160
    for backend in ("infinity-context", "mem0"):
        for stage in ("answer", "judge"):
            assert calls_by_benchmark_backend_stage[("locomo", backend, stage)] == 1_540
            assert calls_by_benchmark_backend_stage[("longmemeval", backend, stage)] == 500

    assert transport.call_count == 8_160
    assert sum(transport.call_count_by_bridge_id.values()) == 8_160
    assert all(count > 0 for count in transport.call_count_by_bridge_id.values())
    assert 0 < transport.maximum_request_bytes_observed <= SCHEDULER_OFFICIAL_CASE_BYTES_CAP
    assert (
        0
        < transport.maximum_response_bytes_observed
        <= SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP
    )
    assert case_authority.read_count == 8_160
    assert case_authority.read_count_by_benchmark == {
        "locomo": 6_160,
        "longmemeval": 2_000,
    }
    assert retrieval_authority.read_count == 4_080
    assert retrieval_authority.read_count_by_backend_role == {
        "infinity-context": 2_040,
        "mem0": 2_040,
    }
    assert retrieval_authority.read_count_by_benchmark_and_backend == {
        ("locomo", "infinity-context"): 1_540,
        ("locomo", "mem0"): 1_540,
        ("longmemeval", "infinity-context"): 500,
        ("longmemeval", "mem0"): 500,
    }
    assert key_resolver.active_key_call_count == 8_160
    assert key_resolver.resolve_key_call_count == 4_080
    assert nonce_source.call_count == FULL_TRAVERSAL_NONCE_CAP == 8_160
    assert journal.statistics().intent_count == 8_160
    assert journal.statistics().result_count == 8_160
    assert journal.statistics().physical_receipt_count == 8_160
    assert journal.statistics().event_count == 16_320
    assert len(transport.authenticated_physical_receipt_sha256) == 8_160
    assert len(transport.request_identity_nonces) == 8_160

    legacy_root = tmp_path / "legacy-unpaired-scheduler"
    copytree(tmp_path / "scheduler", legacy_root)
    legacy_specs = tuple(
        replace(
            spec,
            database_path=(
                legacy_root / spec.run.binding.profile.benchmark.value / "scheduler.sqlite3"
            ),
            private_directory=(legacy_root / spec.run.binding.profile.benchmark.value),
        )
        for spec in specs
    )
    legacy_seal_store = SchedulerSuiteSealStoreSpec(
        database_path=legacy_specs[0].private_directory / "suite-seal.sqlite3",
        private_directory=legacy_specs[0].private_directory,
        authentication_secret=legacy_specs[0].authentication_secret,
    )
    legacy_scheduler = (
        scheduler_subscription_bridge_composition.open_scheduler_subscription_bridge_composition(
            suite=suite,
            run_stores=legacy_specs,
            case_reader=case_authority,
            retrieval_reader=retrieval_authority,
            output_cipher=cipher,
            bridge_keys=secrets,
            bridge_fleet_readiness=readiness,
            bridge_transport=transport,
            bridge_journal=journal,
            extraction_terminal_reader=composition.extraction_terminals,
            clock=lambda: 2_000,
            lease_id_factory=lambda: "legacy-unpaired-must-not-dispatch",
            suite_seal_store=legacy_seal_store,
        )
    )
    legacy_unpaired_seal = legacy_scheduler.runner.seal()
    assert legacy_unpaired_seal.paired_outcome is None
    with pytest.raises(
        SchedulerRunnerError,
        match="scheduler_runner_suite_seal_binding_missing",
    ):
        open_publishable_production_composition(
            mode=PublishableProductionOpenMode.RESUME,
            suite=suite,
            run_stores=legacy_specs,
            extraction_suite=extraction_suite,
            official_case_authority=case_authority,
            retrieval_capture_authority=retrieval_authority,
            output_cipher=cipher,
            bridge_keys=secrets,
            bridge_fleet_readiness=readiness,
            bridge_transport=transport,
            bridge_journal=journal,
            clock=lambda: 2_000,
            lease_id_factory=lambda: "legacy-paired-reopen-must-not-dispatch",
            suite_seal_store=legacy_seal_store,
        )
    assert case_authority.read_count == 8_160
    assert transport.call_count == 8_160

    with monkeypatch.context() as case_authority_patch:
        case_authority_patch.setattr(
            CountingOfficialCaseReader,
            "authority_root_sha256",
            "0" * 64,
        )
        with pytest.raises(
            SchedulerRunnerError,
            match="paired_outcome_production_case_authority_drift",
        ):
            composition.runner.seal()
    assert case_authority.read_count == 8_160

    first_judge_id = manifests[0].shards[0].calls[1].logical_call_id
    exact_lookup = SubscriptionRuntimeBridgeAdapter.lookup_logical_call

    def hide_first_judge(self, logical_call_id):
        if logical_call_id == first_judge_id:
            return None
        return exact_lookup(self, logical_call_id)

    with monkeypatch.context() as missing_patch:
        missing_patch.setattr(
            SubscriptionRuntimeBridgeAdapter,
            "lookup_logical_call",
            hide_first_judge,
        )
        with pytest.raises(SchedulerRunnerError, match="paired_outcome_production_judge_missing"):
            composition.runner.seal()
    assert transport.call_count == 8_160

    second_judge_id = manifests[0].shards[0].calls[3].logical_call_id

    def crosswire_same_intent_result(self, logical_call_id):
        expected = exact_lookup(self, logical_call_id)
        if logical_call_id != first_judge_id:
            return expected
        other = exact_lookup(self, second_judge_id)
        assert type(expected) is TerminalBridgeCall
        assert type(other) is TerminalBridgeCall
        return TerminalBridgeCall(
            readback=TerminalOutcome(
                intent=expected.readback.intent,
                result=other.readback.result,
            ),
            private_output=other.private_output,
            transport_dispatched=False,
        )

    with monkeypatch.context() as receipt_tamper_patch:
        receipt_tamper_patch.setattr(
            SubscriptionRuntimeBridgeAdapter,
            "lookup_logical_call",
            crosswire_same_intent_result,
        )
        with pytest.raises(
            SchedulerRunnerError,
            match="paired_outcome_production_judge_receipt_crosswire",
        ):
            composition.runner.seal()
    assert transport.call_count == 8_160

    def crosswire_private_output(self, logical_call_id):
        expected = exact_lookup(self, logical_call_id)
        if logical_call_id != first_judge_id:
            return expected
        other = exact_lookup(self, second_judge_id)
        assert type(expected) is TerminalBridgeCall
        assert type(other) is TerminalBridgeCall
        return TerminalBridgeCall(
            readback=expected.readback,
            private_output=other.private_output,
            transport_dispatched=False,
        )

    with monkeypatch.context() as plaintext_tamper_patch:
        plaintext_tamper_patch.setattr(
            SubscriptionRuntimeBridgeAdapter,
            "lookup_logical_call",
            crosswire_private_output,
        )
        with pytest.raises(
            SchedulerRunnerError,
            match="paired_outcome_production_judge_plaintext_crosswire",
        ):
            composition.runner.seal()
    assert transport.call_count == 8_160

    original_output_key = key_resolver._key
    wrong_output_key = OutputCipherKey(
        original_output_key.key_id,
        b"x" * 32,
    )
    with monkeypatch.context() as tamper_patch:
        tamper_patch.setattr(key_resolver, "_key", wrong_output_key)
        with pytest.raises(
            SchedulerRunnerError,
            match="paired_outcome_production_judge_read_failed",
        ):
            composition.runner.seal()
    assert transport.call_count == 8_160

    interrupted_seals = []

    def interrupt_after_run_seals(_store, candidate):
        interrupted_seals.append(candidate)
        raise KeyboardInterrupt("simulated-suite-sidecar-crash")

    with monkeypatch.context() as crash_patch:
        crash_patch.setattr(
            SQLiteSchedulerSuiteSealStore,
            "persist_exact",
            interrupt_after_run_seals,
        )
        with pytest.raises(KeyboardInterrupt, match="simulated-suite-sidecar-crash"):
            composition.runner.seal()
    assert len(interrupted_seals) == 1
    interrupted_seal = interrupted_seals[0]
    assert interrupted_seal.paired_outcome is not None
    assert interrupted_seal.paired_outcome.pair_count == EXPECTED_PAIRED_OUTCOME_COUNT
    assert interrupted_seal.paired_outcome.paired_superiority_criterion_met is True
    assert case_authority.read_count == FULL_TRAVERSAL_CASE_READ_CAP
    assert transport.call_count == 8_160

    journal.close()
    journal = BridgeJournal.open(
        journal_path,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    crash_reopen_case_authority = CountingOfficialCaseReader()
    composition = open_publishable_production_composition(
        mode=PublishableProductionOpenMode.RESUME,
        suite=suite,
        run_stores=specs,
        extraction_suite=extraction_suite,
        official_case_authority=crash_reopen_case_authority,
        retrieval_capture_authority=CountingRetrievalEvidenceReader(),
        output_cipher=cipher,
        bridge_keys=secrets,
        bridge_fleet_readiness=readiness,
        bridge_transport=transport,
        bridge_journal=journal,
        clock=lambda: 2_500,
        lease_id_factory=lambda: "crash-reopen-must-not-dispatch",
    )
    seal = composition.runner.seal()
    assert seal == interrupted_seal
    assert crash_reopen_case_authority.read_count == EXPECTED_PAIRED_OUTCOME_COUNT
    assert transport.call_count == 8_160
    assert seal.runtime_provenance_sha256 == suite.runtime_provenance_sha256
    assert seal.case_count == 2_040
    assert seal.evaluation_call_count == 8_160
    assert PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT == 130_226
    assert seal.extraction_operation_count == PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT
    assert seal.charged_tokens == 8_160 * 14
    assert seal.paired_outcome is not None
    assert seal.paired_outcome.pair_count == EXPECTED_PAIRED_OUTCOME_COUNT == 2_040
    assert seal.paired_outcome.paired_superiority_criterion_met is True
    publication_secret = b"full-traversal-publication-attestation-secret"
    publication = PublishableRunAttestation.create(
        suite_authority_sha256=suite.commitment_sha256,
        ordered_run_authority_sha256=seal.ordered_run_authority_sha256,
        official_case_authority_root_sha256=case_authority.authority_root_sha256,
        retrieval_authority_root_sha256=retrieval_authority.authority_root_sha256,
        extraction_suite_readback_sha256=(extraction_suite.suite_readback_commitment_sha256),
        production_composition_authority_sha256=composition.authority_sha256,
        suite_seal_sha256=seal.commitment_sha256,
        terminal_disposition="sealed",
        case_count=seal.case_count,
        evaluation_call_count=seal.evaluation_call_count,
        extraction_operation_count=seal.extraction_operation_count,
        provider_intent_count=journal.statistics().intent_count,
        provider_result_count=journal.statistics().result_count,
        provider_call_count=transport.call_count,
        provider_accounting_complete=True,
        charged_tokens=seal.charged_tokens,
        call_ledger=seal.call_ledger,
        paired_outcome=seal.paired_outcome,
        authentication_key_id="full-traversal-publication-key-v1",
        authentication_secret=publication_secret,
    )
    assert publication.publishable is True
    assert publication.paired_outcome == seal.paired_outcome
    assert verify_publishable_run_attestation(
        publication,
        authentication_secret=publication_secret,
        expected_authentication_key_id="full-traversal-publication-key-v1",
    )
    assert sum(len(items) for items in case_groups) == 2_040
    calls_before_replay = transport.call_count
    journal.close()
    runtime_processes.close_controller()
    reopened_runtime_processes = reopen_subscription_runtime_bridge_processes(
        process_spec,
        control=process_harness.control,
    )
    assert reopened_runtime_processes.readiness == readiness
    assert reopened_runtime_processes.bridge_pool == runtime_processes.bridge_pool
    assert reopened_runtime_processes.bridge_boot == runtime_processes.bridge_boot
    readiness = reopened_runtime_processes.readiness

    wrong_journal = BridgeJournal.create(
        tmp_path / "wrong-bridge" / "journal.sqlite3",
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    try:
        with pytest.raises(SchedulerRunnerError, match="bundle_journal_missing"):
            open_publishable_production_composition(
                mode=PublishableProductionOpenMode.RESUME,
                suite=suite,
                run_stores=specs,
                extraction_suite=extraction_suite,
                official_case_authority=CountingOfficialCaseReader(),
                retrieval_capture_authority=CountingRetrievalEvidenceReader(),
                output_cipher=Aes256GcmOutputCipher(
                    key_resolver=DeterministicOutputKeyResolver(),
                    maximum_ciphertext_bytes=(SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP),
                    nonce_source=DeterministicNonceSource(start_index=8_160),
                ),
                bridge_keys=secrets,
                bridge_fleet_readiness=readiness,
                bridge_transport=transport,
                bridge_journal=wrong_journal,
                clock=lambda: 3_000,
                lease_id_factory=lambda: "wrong-journal-must-not-dispatch",
            )
    finally:
        wrong_journal.close()
    assert transport.call_count == calls_before_replay

    replay_journal = BridgeJournal.open(
        journal_path,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    replay_case_authority = CountingOfficialCaseReader()
    replay_retrieval_authority = CountingRetrievalEvidenceReader()
    replay = open_publishable_production_composition(
        mode=PublishableProductionOpenMode.RESUME,
        suite=suite,
        run_stores=specs,
        extraction_suite=extraction_suite,
        official_case_authority=replay_case_authority,
        retrieval_capture_authority=replay_retrieval_authority,
        output_cipher=Aes256GcmOutputCipher(
            key_resolver=DeterministicOutputKeyResolver(),
            maximum_ciphertext_bytes=SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
            nonce_source=DeterministicNonceSource(start_index=8_160),
        ),
        bridge_keys=secrets,
        bridge_fleet_readiness=readiness,
        bridge_transport=transport,
        bridge_journal=replay_journal,
        clock=lambda: 3_000,
        lease_id_factory=lambda: "replay-must-not-dispatch",
    )
    assert replay.runner.run_next().disposition is SchedulerStepDisposition.SEALED
    assert replay.runner.seal() == seal
    assert replay_case_authority.read_count == 0
    assert replay_retrieval_authority.read_count == 0
    assert transport.call_count == calls_before_replay
    replay_journal.close()
    reopened_runtime_processes.stop_all(reason="full-traversal-complete")
