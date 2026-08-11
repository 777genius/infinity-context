from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.features.subscription_runtime_bridge import (
    AuthenticatedPreDispatchAbsence,
    BridgeAuthority,
    BridgeDivergenceError,
    BridgeJournal,
    BridgePoolAuthority,
    HmacJournalIntegrity,
    OutcomeUnknown,
    SubscriptionRuntimeBridgeAdapter,
    canonical_openai_request_body,
)
from infinity_context_server.features.subscription_runtime_bridge.request_contract import (
    derive_bridge_intent,
)
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_adapter as scheduler_bridge_adapter,
)
from infinity_context_server.publishable_durable_scheduler import (
    scheduler_subscription_bridge_composition as scheduler_bridge_composition,
)
from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
)
from infinity_context_server.publishable_durable_scheduler.resumable_runner import (
    PublishableResumableEvaluationRunner,
)
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT,
    SchedulerDispatchEnvelope,
    SchedulerDispatchReadbackDisposition,
    SchedulerPrivateAnswerReadCapability,
    SchedulerRenderedRequest,
    SchedulerRequestContext,
    SchedulerRunnerError,
    SchedulerStepDisposition,
    bound_request_sha256,
    dispatch_intent_sha256,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerRunPhase,
)
from scheduler_subscription_bridge_composition_test_support import (
    BRIDGE_JOURNAL_KEY,
    AuthenticatedExtractionReader,
    EmbeddedAadCipher,
    EmbeddedAadDecryptor,
    SyntheticCaseReader,
    SyntheticRetrievalReader,
    bridge_fleet_readiness,
    official_suite_and_manifests,
    run_store_specs,
    seed_all_scheduler_calls,
    sha,
)
from subscription_runtime_bridge_test_support import AttestedFakeTransport, FakeSecrets

_RENDERER_POLICY = sha("scheduler-bridge-compatible-renderer")
_PRIVATE_ANSWER_POLICY = sha("scheduler-bridge-compatible-private-answer")


@pytest.fixture(scope="module")
def authority():
    readiness = bridge_fleet_readiness()
    return readiness, official_suite_and_manifests(readiness)


class _CompatibleRenderer:
    renderer_policy_sha256 = _RENDERER_POLICY
    private_answer_policy_sha256 = _PRIVATE_ANSWER_POLICY

    def render(self, context) -> SchedulerRenderedRequest:
        dependency_sha256 = None
        if context.call.stage is SchedulerCallStage.JUDGE:
            ciphertext = context.dependency_answer_ciphertext
            dependency_sha256 = hashlib.sha256(ciphertext).hexdigest()
        payload = _request(
            prompt=f"private:{context.call.logical_call_id}",
            output_tokens=context.call.token_ceiling,
        )
        return SchedulerRenderedRequest(
            renderer_policy_sha256=self.renderer_policy_sha256,
            private_answer_policy_sha256=self.private_answer_policy_sha256,
            dependency_answer_ciphertext_sha256=dependency_sha256,
            payload=payload,
        )


class _OutputTokenCrosswireRenderer(_CompatibleRenderer):
    def render(self, context) -> SchedulerRenderedRequest:
        rendered = super().render(context)
        return replace(
            rendered,
            payload=_request(
                prompt=f"private:{context.call.logical_call_id}",
                output_tokens=context.call.token_ceiling - 1,
            ),
        )


class _CrashTransport:
    def __init__(self) -> None:
        self.calls = 0

    def post_once(
        self,
        *,
        origin: str,
        route: str,
        bearer_token: str,
        request_body: bytes,
        maximum_response_bytes: int,
    ) -> bytes:
        del origin, route, bearer_token, request_body, maximum_response_bytes
        self.calls += 1
        raise RuntimeError("provider-free simulated transport interruption")


def test_exact_benchmark_backend_answer_judge_translation_and_private_redaction(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    journal, transport, seam = _seam(tmp_path, readiness, suite)
    observed = []

    for run, manifest in zip(runs, manifests, strict=True):
        for backend_index in (0, 1):
            answer_call = manifest.shards[0].calls[backend_index * 2]
            answer_envelope = _envelope(
                suite,
                run,
                answer_call,
                payload=_request(
                    prompt=(
                        f"{run.binding.profile.benchmark.value}:{answer_call.backend_role}:answer"
                    ),
                ),
            )
            answer = seam.invoke_once(answer_envelope)
            ciphertext = answer.private_output_ciphertext
            assert ciphertext is not None
            assert answer.receipt.charged_tokens == 14
            assert seam.verify(receipt=answer.receipt, envelope=answer_envelope)
            assert (
                scheduler_bridge_adapter.bridge_call_binding(answer_envelope).intent_id
                == answer_envelope.intent_sha256
            )

            judge_call = manifest.shards[0].calls[backend_index * 2 + 1]
            judge_envelope = _envelope(
                suite,
                run,
                judge_call,
                payload=_request(
                    prompt=(
                        f"{run.binding.profile.benchmark.value}:{judge_call.backend_role}:judge"
                    ),
                ),
                dependency_ciphertext=ciphertext,
            )
            judge = seam.invoke_once(judge_envelope)
            dependency_sha256 = hashlib.sha256(ciphertext).hexdigest()
            assert judge.private_output_ciphertext is None
            assert judge.receipt.dependency_answer_ciphertext_sha256 == dependency_sha256
            assert scheduler_bridge_adapter.bridge_call_binding(
                judge_envelope
            ).logical_operation == (f"scheduler-judge:{dependency_sha256}")
            assert seam.verify(receipt=judge.receipt, envelope=judge_envelope)
            observed.append(
                (
                    run.binding.profile.benchmark.value,
                    answer_call.backend_role,
                    answer.receipt.charged_tokens + judge.receipt.charged_tokens,
                )
            )

            assert b"private completion" not in answer.receipt.attestation
            assert "private completion" not in repr(answer)
            assert "private completion" not in repr(seam)

    assert observed == [
        ("locomo", "infinity-context", 28),
        ("locomo", "mem0", 28),
        ("longmemeval", "infinity-context", 28),
        ("longmemeval", "mem0", 28),
    ]
    assert [body for _, body in transport.calls] == [
        _request(prompt=f"{benchmark}:{backend}:answer")
        if index % 2 == 0
        else _request(prompt=f"{benchmark}:{backend}:judge")
        for benchmark, backend, _ in observed
        for index in (0, 1)
    ]
    journal.close()


def test_known_terminal_crash_recovery_and_pre_dispatch_absence_add_zero_transport_calls(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    journal, transport, seam = _seam(tmp_path, readiness, suite)
    envelope = _envelope(
        suite,
        runs[0],
        manifests[0].shards[0].calls[0],
        payload=_request(prompt="dispatch-then-crash"),
    )

    seam.invoke_once(envelope)
    calls_after_dispatch = len(transport.calls)
    journal.close()
    reopened_journal, _, reopened = _seam(
        tmp_path,
        readiness,
        suite,
        transport=transport,
        reopen=True,
    )
    recovered = reopened.lookup(envelope)
    assert recovered.disposition is SchedulerDispatchReadbackDisposition.FOUND
    assert recovered.outcome is not None
    assert reopened.authenticate(readback=recovered, envelope=envelope)
    assert reopened.verify(receipt=recovered.outcome.receipt, envelope=envelope)
    assert len(transport.calls) == calls_after_dispatch

    absent = _envelope(
        suite,
        runs[1],
        manifests[1].shards[0].calls[0],
        payload=_request(prompt="never-dispatched"),
    )
    missing = reopened.lookup(absent)
    assert missing.disposition is SchedulerDispatchReadbackDisposition.TERMINAL_ABSENT
    assert missing.outcome is None
    assert reopened.authenticate(readback=missing, envelope=absent)
    assert len(transport.calls) == calls_after_dispatch
    reopened_journal.close()


def test_output_token_crosswire_fails_before_intent_or_transport(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    journal, transport, seam = _seam(tmp_path, readiness, suite)
    envelope = _envelope(
        suite,
        runs[0],
        manifests[0].shards[0].calls[0],
        payload=_request(prompt="token-crosswire", output_tokens=4_095),
    )

    with pytest.raises(SchedulerRunnerError, match="intent_crosswire"):
        seam.invoke_once(envelope)
    assert transport.calls == []
    assert journal.statistics().event_count == 0
    assert journal.statistics().intent_count == 0
    assert journal.statistics().result_count == 0
    with pytest.raises(SchedulerRunnerError, match="intent_crosswire"):
        seam.lookup(envelope)
    journal.close()


def test_runner_output_token_crosswire_fails_before_scheduler_dispatch_intent(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    specs = run_store_specs(tmp_path / "scheduler", suite, runs, manifests)
    journal, transport, seam = _seam(tmp_path / "bridge", readiness, suite)
    lease_calls = 0

    def lease_id() -> str:
        nonlocal lease_calls
        lease_calls += 1
        return "output-token-crosswire-lease"

    runner = PublishableResumableEvaluationRunner.open(
        suite=suite,
        run_stores=specs,
        request_renderer=_OutputTokenCrosswireRenderer(),
        boundary=seam,
        receipt_verifier=seam,
        extraction_terminal_reader=AuthenticatedExtractionReader(suite, specs),
        reconciliation=seam,
        clock=lambda: 2_000,
        lease_id_factory=lease_id,
        lease_duration_ms=1_000,
    )
    first_call = manifests[0].shards[0].calls[0]

    with pytest.raises(SchedulerRunnerError, match="intent_crosswire"):
        runner.run_next()

    state = runner._entries[0].store.read_call(first_call.logical_call_id)
    assert state.phase is SchedulerCallPhase.PLANNED
    assert state.attempt_count == 0
    assert lease_calls == 0
    assert transport.calls == []
    statistics = journal.statistics()
    assert (statistics.event_count, statistics.intent_count, statistics.result_count) == (0, 0, 0)
    journal.close()


def test_runner_known_terminal_recovery_and_unknown_freeze_never_redispatch(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    known_specs = run_store_specs(tmp_path / "known-scheduler", suite, runs, manifests)
    known_journal, known_transport, known_seam = _seam(
        tmp_path / "known-bridge",
        readiness,
        suite,
    )
    known_runner = _runner(suite, known_specs, known_seam, now=2_000)
    known_envelope = _seed_dispatch_intent(known_runner)
    known_seam.invoke_once(known_envelope)
    assert len(known_transport.calls) == 1

    recovered = _runner(suite, known_specs, known_seam, now=3_000)
    recovered_call = recovered._entries[0].store.read_call(known_envelope.logical_call_id)
    assert recovered_call.phase is SchedulerCallPhase.COMMITTED
    assert recovered_call.charged_tokens == 14
    assert len(known_transport.calls) == 1
    known_journal.close()

    unknown_specs = run_store_specs(tmp_path / "unknown-scheduler", suite, runs, manifests)
    crash_transport = _CrashTransport()
    unknown_journal, _, unknown_seam = _seam(
        tmp_path / "unknown-bridge",
        readiness,
        suite,
        transport=crash_transport,
    )
    unknown_runner = _runner(suite, unknown_specs, unknown_seam, now=2_000)
    unknown_envelope = _seed_dispatch_intent(unknown_runner)
    with pytest.raises(RuntimeError, match="simulated transport interruption"):
        unknown_seam.invoke_once(unknown_envelope)
    ambiguous = unknown_seam.lookup(unknown_envelope)
    assert ambiguous.disposition is SchedulerDispatchReadbackDisposition.AMBIGUOUS
    assert unknown_seam.authenticate(readback=ambiguous, envelope=unknown_envelope)
    assert crash_transport.calls == 1

    frozen = _runner(suite, unknown_specs, unknown_seam, now=3_000)
    assert frozen._entries[0].store.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    assert frozen.run_next().disposition is SchedulerStepDisposition.FROZEN_OUTCOME_UNKNOWN
    with pytest.raises(SchedulerRunnerError, match="outcome_unknown"):
        unknown_seam.invoke_once(unknown_envelope)
    assert crash_transport.calls == 1
    unknown_journal.close()


def test_authenticated_pre_dispatch_absence_is_exact_reopenable_and_tamper_evident(
    tmp_path: Path,
) -> None:
    readiness = bridge_fleet_readiness()
    pool = readiness.pool
    suite, runs, manifests, _ = official_suite_and_manifests(readiness)
    call = manifests[0].shards[0].calls[0]
    envelope_binding = scheduler_bridge_adapter.bridge_call_binding(
        _envelope(
            suite,
            runs[0],
            call,
            payload=_request(prompt="authenticated-absence"),
        )
    )
    database = tmp_path / "bridge" / "journal.sqlite3"
    journal = BridgeJournal.create(
        database,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    proof = journal.lookup_pre_dispatch(envelope_binding)
    assert type(proof) is AuthenticatedPreDispatchAbsence
    assert journal.authenticate_pre_dispatch_absence(proof)
    assert proof.journal_generation_sha256 == journal.generation_sha256
    assert not journal.authenticate_pre_dispatch_absence(
        replace(proof, proof_hmac_sha256=sha("forged-absence-proof"))
    )
    generation = journal.generation_sha256
    journal.close()

    reopened = BridgeJournal.open(
        database,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    assert reopened.generation_sha256 == generation
    assert reopened.authenticate_pre_dispatch_absence(proof)
    divergent_binding = replace(envelope_binding, intent_id=sha("divergent-intent"))
    _, divergent_intent = derive_bridge_intent(
        pool=pool,
        binding=divergent_binding,
        request_body=_request(prompt="authenticated-absence"),
        maximum_request_bytes=4 * 1024 * 1024,
    )
    assert reopened.record_intent(divergent_intent).dispatch_granted is True
    assert isinstance(reopened.lookup_outcome(divergent_binding.intent_id), OutcomeUnknown)
    with pytest.raises(BridgeDivergenceError, match="logical_call_divergence"):
        reopened.lookup_pre_dispatch(envelope_binding)
    reopened.close()

    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE bridge_journal_metadata SET journal_generation_sha256 = ?",
            (sha("tampered-generation"),),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(RuntimeError):
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY))


def test_runner_recovers_same_generation_pre_dispatch_gap_and_replay_calls_once(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    specs = run_store_specs(tmp_path / "scheduler", suite, runs, manifests)
    journal, transport, seam = _seam(tmp_path / "bridge", readiness, suite)
    interrupted = _runner(suite, specs, seam, now=2_000)
    envelope = _seed_dispatch_intent(interrupted)
    assert transport.calls == []
    generation = journal.generation_sha256
    journal.close()

    reopened_journal, _, reopened_seam = _seam(
        tmp_path / "bridge",
        readiness,
        suite,
        transport=transport,
        reopen=True,
    )
    assert reopened_journal.generation_sha256 == generation
    recovered = _runner(suite, specs, reopened_seam, now=3_000)
    ready = recovered._entries[0].store.read_call(envelope.logical_call_id)
    assert ready.phase is SchedulerCallPhase.PLANNED
    assert ready.attempt_count == 1
    assert ready.terminal_evidence_sha256 is not None
    committed = recovered.run_next()
    assert committed.disposition is SchedulerStepDisposition.COMMITTED
    assert committed.provider_dispatches == 1
    assert len(transport.calls) == 1
    reopened_journal.close()

    replay_journal, _, replay_seam = _seam(
        tmp_path / "bridge",
        readiness,
        suite,
        transport=transport,
        reopen=True,
    )
    replay = _runner(suite, specs, replay_seam, now=4_000)
    replayed_call = replay._entries[0].store.read_call(envelope.logical_call_id)
    assert replayed_call.phase is SchedulerCallPhase.COMMITTED
    assert replayed_call.attempt_count == 2
    assert len(transport.calls) == 1
    replay_journal.close()


def test_pre_dispatch_recovery_wrong_generation_and_logical_divergence_freeze(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    wrong_specs = run_store_specs(tmp_path / "wrong-scheduler", suite, runs, manifests)
    old_journal, _, old_seam = _seam(tmp_path / "old-bridge", readiness, suite)
    old_runner = _runner(suite, wrong_specs, old_seam, now=2_000)
    _seed_dispatch_intent(old_runner)
    old_journal.close()

    wrong_journal, wrong_transport, wrong_seam = _seam(
        tmp_path / "wrong-bridge",
        readiness,
        suite,
    )
    wrong_generation = _runner(suite, wrong_specs, wrong_seam, now=3_000)
    assert wrong_generation._entries[0].store.read_run().phase is (
        SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    )
    assert wrong_transport.calls == []
    wrong_journal.close()

    divergent_specs = run_store_specs(
        tmp_path / "divergent-scheduler",
        suite,
        runs,
        manifests,
    )
    divergent_journal, divergent_transport, divergent_seam = _seam(
        tmp_path / "divergent-bridge",
        readiness,
        suite,
    )
    divergent_runner = _runner(suite, divergent_specs, divergent_seam, now=2_000)
    expected = _seed_dispatch_intent(divergent_runner)
    observed = replace(expected, intent_sha256=sha("observed-divergent-intent"))
    divergent_seam.invoke_once(observed)
    assert len(divergent_transport.calls) == 1
    divergent_journal.close()

    reopened_journal, _, reopened_seam = _seam(
        tmp_path / "divergent-bridge",
        readiness,
        suite,
        transport=divergent_transport,
        reopen=True,
    )
    divergent = _runner(suite, divergent_specs, reopened_seam, now=3_000)
    assert divergent._entries[0].store.read_run().phase is (
        SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    )
    assert len(divergent_transport.calls) == 1
    reopened_journal.close()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("public_model", "gpt-crosswired"),
        ("CODEX_MODEL", "gpt-crosswired"),
        ("REASONING_EFFORT", "low"),
        ("SERVICE_TIER", "default"),
        ("MODEL_PROVIDER", "crosswired"),
        ("EXECUTION_PROFILE", "stateful-crosswired"),
        ("base_instructions_sha256", sha("crosswired-base-instructions")),
    ),
)
def test_official_composition_rejects_runtime_boot_crosswire_before_open(
    tmp_path: Path,
    authority,
    field: str,
    value: str,
) -> None:
    readiness, (suite, _, _, _) = authority
    pool = readiness.pool
    bridge = pool.bridges[0]
    if field in {"public_model", "base_instructions_sha256"}:
        crosswired = replace(bridge, **{field: value})
    else:
        authority_type = type(
            f"Crosswired{field}",
            (BridgeAuthority,),
            {field: value},
        )
        crosswired = authority_type(
            bridge_id=bridge.bridge_id,
            origin=bridge.origin,
            account_binding_hmac_sha256=bridge.account_binding_hmac_sha256,
            public_model=bridge.public_model,
            base_instructions_sha256=bridge.base_instructions_sha256,
            route=bridge.route,
        )
    crosswired_pool = BridgePoolAuthority(
        pool_id=pool.pool_id,
        bridges=(crosswired, *pool.bridges[1:]),
    )
    crosswired_readiness = bridge_fleet_readiness(crosswired_pool)
    journal = BridgeJournal.create(
        tmp_path / field.lower() / "bridge.sqlite3",
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    try:
        with pytest.raises(
            SchedulerRunnerError,
            match="scheduler_subscription_bridge_runtime_authority_invalid",
        ):
            scheduler_bridge_composition.open_scheduler_subscription_bridge_composition(
                suite=suite,
                run_stores=(),  # type: ignore[arg-type]
                case_reader=object(),  # type: ignore[arg-type]
                retrieval_reader=object(),  # type: ignore[arg-type]
                private_output_decryptor=object(),  # type: ignore[arg-type]
                output_cipher=object(),  # type: ignore[arg-type]
                bridge_keys=object(),  # type: ignore[arg-type]
                bridge_fleet_readiness=crosswired_readiness,
                bridge_transport=object(),  # type: ignore[arg-type]
                bridge_journal=journal,
                extraction_terminal_reader=object(),  # type: ignore[arg-type]
                clock=lambda: 2_000,
                lease_id_factory=lambda: "runtime-crosswire-lease",
            )
        statistics = journal.statistics()
        assert (statistics.event_count, statistics.intent_count, statistics.result_count) == (
            0,
            0,
            0,
        )
    finally:
        journal.close()


def test_divergence_crosswire_and_deterministic_three_bridge_sharding(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, _) = authority
    pool = readiness.pool
    journal, transport, seam = _seam(tmp_path, readiness, suite)
    first = _envelope(
        suite,
        runs[0],
        manifests[0].shards[0].calls[0],
        payload=_request(prompt="private-crosswire-canary"),
    )
    seam.invoke_once(first)
    divergent = replace(first, payload=_request(prompt="substituted-private-canary"))
    with pytest.raises(SchedulerRunnerError, match="intent_crosswire") as error:
        seam.lookup(divergent)
    assert "private-crosswire-canary" not in str(error.value)
    with pytest.raises(BridgeDivergenceError):
        seam.invoke_once(divergent)

    expected_bridges = []
    start = len(transport.calls)
    calls = tuple(call for shard in manifests[0].shards[:1] for call in shard.calls[4:28])
    for index, call in enumerate(calls):
        dependency = (
            None
            if call.stage is SchedulerCallStage.ANSWER
            else f"synthetic-dependency:{call.depends_on_logical_call_id}".encode()
        )
        envelope = _envelope(
            suite,
            runs[0],
            call,
            payload=_request(prompt=f"shard:{index}"),
            dependency_ciphertext=dependency,
        )
        expected_bridges.append(
            pool.select(scheduler_bridge_adapter.bridge_call_binding(envelope)).bridge_id
        )
        seam.invoke_once(envelope)
    actual_bridges = [bridge_id for bridge_id, _ in transport.calls[start:]]
    assert actual_bridges == expected_bridges
    assert set(actual_bridges) == {bridge.bridge_id for bridge in pool.bridges}
    journal.close()


def test_official_composition_suite_seal_replay_and_synthetic_2040_traversal(
    tmp_path: Path,
    authority,
) -> None:
    readiness, (suite, runs, manifests, case_groups) = authority
    pool = readiness.pool
    specs = run_store_specs(tmp_path / "scheduler", suite, runs, manifests)
    extraction_reader = AuthenticatedExtractionReader(suite, specs)
    secrets = FakeSecrets(pool)
    transport = AttestedFakeTransport(pool, secrets)
    cipher = EmbeddedAadCipher()
    decryptor = EmbeddedAadDecryptor(cipher)
    bridge_database = tmp_path / "bridge" / "journal.sqlite3"
    journal = BridgeJournal.create(
        bridge_database,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    composition = scheduler_bridge_composition.open_scheduler_subscription_bridge_composition(
        suite=suite,
        run_stores=specs,
        case_reader=SyntheticCaseReader(),
        retrieval_reader=SyntheticRetrievalReader(),
        private_output_decryptor=decryptor,
        output_cipher=cipher,
        bridge_keys=secrets,
        bridge_fleet_readiness=readiness,
        bridge_transport=transport,
        bridge_journal=journal,
        extraction_terminal_reader=extraction_reader,
        clock=lambda: 2_000,
        lease_id_factory=lambda: "official-composition-lease",
        lease_duration_ms=1_000,
    )
    assert transport.calls == []
    assert composition.scheduler_bridge.policy_sha256 == (
        scheduler_bridge_adapter.SCHEDULER_SUBSCRIPTION_BRIDGE_RECEIPT_POLICY_SHA256
    )
    assert composition.scheduler_bridge.readback_policy_sha256 != (
        scheduler_bridge_adapter.SCHEDULER_SUBSCRIPTION_BRIDGE_READBACK_POLICY_SHA256
    )
    assert composition.runner.production_bridge_adapter_ready is True
    assert composition.runner.readiness_blockers == ()
    assert composition.runner.paid_go_ready is False
    assert "private" not in repr(composition).lower().replace("private_capabilities", "")

    answer_call, judge_call = manifests[0].shards[0].calls[:2]
    official_answer = composition.renderer.render(
        SchedulerRequestContext(
            suite=suite,
            run=runs[0],
            call=answer_call,
            dependency_answer_capability=None,
        )
    )
    assert b'"reasoning_effort"' not in official_answer.payload
    assert b'"service_tier"' not in official_answer.payload
    assert composition.renderer.policy.material()["runtime_boot"]["reasoning_effort"] == "high"
    assert composition.renderer.policy.material()["runtime_boot"]["service_tier"] == "priority"
    answer_ciphertext = cipher.seal(
        b"private completion",
        associated_data=b"provider-free-official-render-test",
    )
    official_judge = composition.renderer.render(
        SchedulerRequestContext(
            suite=suite,
            run=runs[0],
            call=judge_call,
            dependency_answer_capability=SchedulerPrivateAnswerReadCapability(answer_ciphertext),
        )
    )
    assert (
        official_judge.dependency_answer_ciphertext_sha256
        == hashlib.sha256(answer_ciphertext).hexdigest()
    )
    assert decryptor.observed_ciphertext_sha256 == [
        official_judge.dependency_answer_ciphertext_sha256
    ]

    traversed_cases = sum(len(items) for items in case_groups)
    traversed_calls = sum(len(shard.calls) for manifest in manifests for shard in manifest.shards)
    assert traversed_cases == 2_040
    assert traversed_calls == PUBLISHABLE_SUITE_EVALUATION_CALL_COUNT == 8_160
    assert tuple(item.backend_role for item in suite.ordered_runs[0].backends) == (
        "infinity-context",
        "mem0",
    )
    for manifest in manifests:
        for shard in manifest.shards:
            for offset in range(0, len(shard.calls), 2):
                answer, judge = shard.calls[offset : offset + 2]
                assert answer.stage is SchedulerCallStage.ANSWER
                assert judge.stage is SchedulerCallStage.JUDGE
                assert judge.depends_on_logical_call_id == answer.logical_call_id

    locomo_steps = tuple(composition.runner.run_next() for _ in range(4))
    assert all(item.disposition is SchedulerStepDisposition.COMMITTED for item in locomo_steps)
    assert tuple(item.run_id for item in locomo_steps) == (runs[0].binding.run_id,) * 4
    seed_all_scheduler_calls(composition.runner, charged_tokens=14, entry_indexes=(0,))
    longmem_steps = tuple(composition.runner.run_next() for _ in range(4))
    assert all(item.disposition is SchedulerStepDisposition.COMMITTED for item in longmem_steps)
    assert tuple(item.run_id for item in longmem_steps) == (runs[1].binding.run_id,) * 4
    assert len(transport.calls) == 8
    seed_all_scheduler_calls(composition.runner, charged_tokens=14, entry_indexes=(1,))
    assert composition.runner.run_next().disposition is SchedulerStepDisposition.EVALUATION_COMPLETE
    seal = composition.runner.seal()
    assert seal.case_count == 2_040
    assert seal.evaluation_call_count == 8_160
    assert seal.charged_tokens == 8_160 * 14
    calls_before_replay = len(transport.calls)
    journal.close()

    reopened_journal = BridgeJournal.open(
        bridge_database,
        integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY),
    )
    replay = scheduler_bridge_composition.open_scheduler_subscription_bridge_composition(
        suite=suite,
        run_stores=specs,
        case_reader=SyntheticCaseReader(),
        retrieval_reader=SyntheticRetrievalReader(),
        private_output_decryptor=EmbeddedAadDecryptor(cipher),
        output_cipher=cipher,
        bridge_keys=secrets,
        bridge_fleet_readiness=readiness,
        bridge_transport=transport,
        bridge_journal=reopened_journal,
        extraction_terminal_reader=extraction_reader,
        clock=lambda: 3_000,
        lease_id_factory=lambda: "official-composition-replay",
        lease_duration_ms=1_000,
    )
    assert replay.runner.run_next().disposition is SchedulerStepDisposition.SEALED
    assert replay.runner.seal() == seal
    assert len(transport.calls) == calls_before_replay
    reopened_journal.close()


def _seam(
    tmp_path: Path,
    readiness,
    suite,
    *,
    transport=None,
    reopen: bool = False,
):
    pool = readiness.pool
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = tmp_path / "bridge" / "journal.sqlite3"
    secrets = FakeSecrets(pool)
    selected_transport = transport or AttestedFakeTransport(pool, secrets)
    journal = (
        BridgeJournal.open(database, integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY))
        if reopen
        else BridgeJournal.create(database, integrity=HmacJournalIntegrity(BRIDGE_JOURNAL_KEY))
    )
    bridge = SubscriptionRuntimeBridgeAdapter(
        pool=pool,
        secrets=secrets,
        transport=selected_transport,
        journal=journal,
        output_cipher=EmbeddedAadCipher(),
        maximum_request_bytes=4 * 1024 * 1024,
        maximum_response_bytes=1024 * 1024,
    )
    return (
        journal,
        selected_transport,
        scheduler_bridge_adapter.SchedulerSubscriptionBridgeAdapter(
            suite=suite,
            fleet_readiness=readiness,
            bridge=bridge,
            keys=secrets,
        ),
    )


def _request(*, prompt: str, output_tokens: int = 4_096) -> bytes:
    return canonical_openai_request_body(
        {
            "max_tokens": output_tokens,
            "messages": [{"content": prompt, "role": "user"}],
            "model": "gpt-5.6-sol",
        }
    )


def _envelope(
    suite,
    run,
    call,
    *,
    payload: bytes,
    dependency_ciphertext: bytes | None = None,
    lease_id: str = "scheduler-bridge-lease",
) -> SchedulerDispatchEnvelope:
    dependency_sha256 = (
        None if dependency_ciphertext is None else hashlib.sha256(dependency_ciphertext).hexdigest()
    )
    request_sha256 = bound_request_sha256(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
        renderer_policy_sha256=_RENDERER_POLICY,
        private_answer_policy_sha256=_PRIVATE_ANSWER_POLICY,
        dependency_answer_ciphertext_sha256=dependency_sha256,
        call=call,
        payload=payload,
    )
    deadline = run.binding.limits.dispatch_deadline_unix_ms
    intent_sha256 = dispatch_intent_sha256(
        envelope_binding={
            "attempt_count": 1,
            "bridge_boot_authority_sha256": suite.bridge_boot.commitment_sha256,
            "dispatch_deadline_unix_ms": deadline,
            "dependency_answer_ciphertext_sha256": dependency_sha256,
            "lease_id": lease_id,
            "logical_call_id": call.logical_call_id,
            "private_answer_policy_sha256": _PRIVATE_ANSWER_POLICY,
            "renderer_policy_sha256": _RENDERER_POLICY,
            "request_sha256": request_sha256,
            "run_authority_sha256": run.commitment_sha256,
            "suite_authority_sha256": suite.commitment_sha256,
            "token_ceiling": call.token_ceiling,
        }
    )
    return SchedulerDispatchEnvelope(
        suite_authority_sha256=suite.commitment_sha256,
        run_authority_sha256=run.commitment_sha256,
        bridge_boot_authority_sha256=suite.bridge_boot.commitment_sha256,
        logical_call_id=call.logical_call_id,
        stage=call.stage,
        ordinal=call.ordinal,
        renderer_policy_sha256=_RENDERER_POLICY,
        private_answer_policy_sha256=_PRIVATE_ANSWER_POLICY,
        dependency_answer_ciphertext_sha256=dependency_sha256,
        request_sha256=request_sha256,
        intent_sha256=intent_sha256,
        token_ceiling=call.token_ceiling,
        dispatch_deadline_unix_ms=deadline,
        payload=payload,
    )


def _runner(suite, specs, seam, *, now: int):
    return PublishableResumableEvaluationRunner.open(
        suite=suite,
        run_stores=specs,
        request_renderer=_CompatibleRenderer(),
        boundary=seam,
        receipt_verifier=seam,
        extraction_terminal_reader=AuthenticatedExtractionReader(suite, specs),
        reconciliation=seam,
        clock=lambda: now,
        lease_id_factory=lambda: "scheduler-recovery-lease",
        lease_duration_ms=1_000,
    )


def _seed_dispatch_intent(runner) -> SchedulerDispatchEnvelope:
    entry = runner._entries[0]
    call = entry.manifest.shards[0].calls[0]
    rendered = runner._render_request(entry, call)
    request_sha256 = bound_request_sha256(
        suite_authority_sha256=runner._suite.commitment_sha256,
        run_authority_sha256=entry.run.commitment_sha256,
        bridge_boot_authority_sha256=runner._suite.bridge_boot.commitment_sha256,
        renderer_policy_sha256=rendered.renderer_policy_sha256,
        private_answer_policy_sha256=rendered.private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=rendered.dependency_answer_ciphertext_sha256,
        call=call,
        payload=rendered.payload,
    )
    lease_id = "scheduler-recovery-lease"
    leased = entry.store.acquire_lease(
        call.logical_call_id,
        now_unix_ms=2_000,
        lease_id=lease_id,
        lease_expires_unix_ms=3_000,
    )
    entry.store.bind_request(
        call.logical_call_id,
        lease_id=lease_id,
        request_sha256=request_sha256,
    )
    deadline = entry.run.binding.limits.dispatch_deadline_unix_ms
    intent_sha256 = dispatch_intent_sha256(
        envelope_binding={
            "attempt_count": leased.attempt_count,
            "bridge_boot_authority_sha256": runner._suite.bridge_boot.commitment_sha256,
            "dispatch_deadline_unix_ms": deadline,
            "dependency_answer_ciphertext_sha256": (rendered.dependency_answer_ciphertext_sha256),
            "lease_id": lease_id,
            "logical_call_id": call.logical_call_id,
            "private_answer_policy_sha256": rendered.private_answer_policy_sha256,
            "readback_policy_sha256": runner._outcome_readback_policy_sha256,
            "renderer_policy_sha256": rendered.renderer_policy_sha256,
            "request_sha256": request_sha256,
            "run_authority_sha256": entry.run.commitment_sha256,
            "suite_authority_sha256": runner._suite.commitment_sha256,
            "token_ceiling": call.token_ceiling,
        }
    )
    entry.store.record_dispatch_intent(
        call.logical_call_id,
        lease_id=lease_id,
        now_unix_ms=2_100,
        bridge_boot_authority_sha256=runner._suite.bridge_boot.commitment_sha256,
        intent_sha256=intent_sha256,
    )
    return SchedulerDispatchEnvelope(
        suite_authority_sha256=runner._suite.commitment_sha256,
        run_authority_sha256=entry.run.commitment_sha256,
        bridge_boot_authority_sha256=runner._suite.bridge_boot.commitment_sha256,
        logical_call_id=call.logical_call_id,
        stage=call.stage,
        ordinal=call.ordinal,
        renderer_policy_sha256=rendered.renderer_policy_sha256,
        private_answer_policy_sha256=rendered.private_answer_policy_sha256,
        dependency_answer_ciphertext_sha256=rendered.dependency_answer_ciphertext_sha256,
        request_sha256=request_sha256,
        intent_sha256=intent_sha256,
        token_ceiling=call.token_ceiling,
        dispatch_deadline_unix_ms=deadline,
        payload=rendered.payload,
    )
