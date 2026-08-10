"""True provider-free 2,040-pair traversal through the production composition."""

from __future__ import annotations

from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    Aes256GcmOutputCipher,
    BridgeJournal,
    HmacJournalIntegrity,
)
from infinity_context_server.processes.subscription_runtime_bridge_process_composition import (
    create_new_subscription_runtime_bridge_processes,
    reopen_subscription_runtime_bridge_processes,
)
from infinity_context_server.publishable_durable_scheduler import (
    PublishableProductionOpenMode,
    open_publishable_production_composition,
    scheduler_subscription_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_CASE_COUNT,
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT,
    SchedulerRunnerError,
    SchedulerStepDisposition,
)
from infinity_context_server.publishable_durable_scheduler.runner_request_composition import (
    SCHEDULER_OFFICIAL_CASE_BYTES_CAP,
    SCHEDULER_PRIVATE_ANSWER_CIPHERTEXT_BYTES_CAP,
)
from scheduler_subscription_bridge_composition_test_support import (
    BRIDGE_JOURNAL_KEY,
    official_suite_and_manifests,
    run_store_specs,
)
from scheduler_subscription_bridge_full_traversal_test_support import (
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


def test_production_composition_traverses_exact_2040_pairs_and_replays_with_zero_calls(
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
    assert journal.statistics().event_count == 16_320

    seal = composition.runner.seal()
    assert seal.runtime_provenance_sha256 == suite.runtime_provenance_sha256
    assert seal.case_count == 2_040
    assert seal.evaluation_call_count == 8_160
    assert seal.extraction_operation_count == (
        PUBLISHABLE_SUITE_EXTRACTION_OPERATION_COUNT == 130_226
    )
    assert seal.charged_tokens == 8_160 * 14
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
