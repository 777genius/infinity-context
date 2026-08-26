from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import replace
from threading import Barrier

import pytest
from infinity_context_server.publishable_durable_scheduler.v2_completion import (
    SchedulerV2CompletionCoordinator,
)
from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    AttemptPhase,
    SchedulerV2Error,
    SlotBinding,
    StateRootFence,
)
from infinity_context_server.publishable_durable_scheduler.v2_coordinator import (
    SchedulerV2DispatchCoordinator,
)
from infinity_context_server.publishable_durable_scheduler.v2_evidence import (
    DatabasePredicateEvidence,
    DispatchBoundaryObservation,
    ProviderCompletionAttestation,
)
from infinity_context_server.publishable_durable_scheduler.v2_in_memory import (
    InMemorySchedulerV2Cas,
)

ROOT = StateRootFence("1" * 64, 7)
PAYLOAD = b'{"model":"bound","messages":["provider payload"]}'
INTENT = "2" * 64
RESULT = "3" * 64


class Clock:
    def __init__(self, now: int, *, wrong_predicate: bool = False) -> None:
        self.now = now
        self.wrong_predicate = wrong_predicate

    def observe(self, *, predicate_sha256: str) -> DatabasePredicateEvidence:
        predicate = "f" * 64 if self.wrong_predicate else predicate_sha256
        return DatabasePredicateEvidence(self.now, predicate)


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.receipts = []
        self.fail = fail

    def fsync_dispatch_started(self, receipt) -> None:
        self.receipts.append(receipt)
        if self.fail:
            raise OSError("fsync failed")


class Boundary:
    def __init__(self, *, fail: bool = False) -> None:
        self.payloads: list[bytes] = []
        self.fail = fail

    def invoke_once(self, payload: bytes) -> DispatchBoundaryObservation:
        self.payloads.append(payload)
        if self.fail:
            raise TimeoutError("boundary outcome unknown")
        return DispatchBoundaryObservation(RESULT)


class Verifier:
    def __init__(self, valid: bool) -> None:
        self.valid = valid
        self.seen: list[ProviderCompletionAttestation] = []

    def verify(self, attestation: ProviderCompletionAttestation) -> bool:
        self.seen.append(attestation)
        return self.valid


def binding(**changes: object) -> SlotBinding:
    values: dict[str, object] = {
        "suite_authority_sha256": "a" * 64,
        "run_authority_sha256": "b" * 64,
        "logical_call_sha256": "c" * 64,
        "account_id": "acct",
        "model_id": "model",
        "route_id": "route",
        "profile_id": "profile",
        "case_id": "case",
        "backend_id": "backend",
        "stage": "judge",
        "ordinal": 3,
        "token_ceiling": 100,
        "reservation_tokens": 80,
        "absolute_deadline_unix_ms": 1_000,
        "payload_byte_ceiling": 256,
    }
    values.update(changes)
    return SlotBinding(**values)  # type: ignore[arg-type]


def intent(store: InMemorySchedulerV2Cas, spec: SlotBinding | None = None):
    spec = spec or binding()
    receipt = store.prepare(
        spec,
        PAYLOAD,
        prepared_boot_id="prepare-boot",
        fence=ROOT,
        now_unix_ms=10,
        database_now_unix_ms=11,
    )
    receipt = store.record_durable_intent(
        spec.logical_slot_id,
        generation=0,
        expected_version=receipt.version,
        durable_intent_receipt_sha256=INTENT,
        dispatch_boot_id="dispatch-boot",
        fence=ROOT,
        now_unix_ms=20,
        database_now_unix_ms=21,
    )
    return spec, receipt


def consumed(store: InMemorySchedulerV2Cas, spec: SlotBinding | None = None):
    spec, receipt = intent(store, spec)
    request = store.issue_consume_request(
        spec.logical_slot_id,
        generation=0,
        expected_version=receipt.version,
        fence=ROOT,
        now_unix_ms=30,
        database_clock=Clock(31),
    )
    response = store.consume(request, fence=ROOT, database_clock=Clock(32))
    return spec, request, response


def invoke(store, response, *, payload=PAYLOAD, clock=None, fsync=None, boundary=None, post=41):
    fsync = fsync or Recorder()
    boundary = boundary or Boundary()
    result = SchedulerV2DispatchCoordinator(store).invoke_dispatch_boundary(
        response,
        payload,
        fence=ROOT,
        now_unix_ms=40,
        post_fsync_now_unix_ms=post,
        post_fsync_fence=ROOT,
        database_clock=clock or Clock(42),
        fsync_port=fsync,
        boundary=boundary,
    )
    return fsync, boundary, result


def attestation(receipt, *, result=RESULT, used=23) -> ProviderCompletionAttestation:
    return ProviderCompletionAttestation(
        logical_slot_id=receipt.logical_slot_id,
        generation=receipt.generation,
        dispatch_receipt_sha256=receipt.commitment_sha256,
        result_sha256=result,
        used_tokens=used,
        bridge_boot_id="dispatch-boot",
        attestation=b"external-signature",
    )


def test_logical_slot_uses_authorities_not_account_route_or_attempt_metadata() -> None:
    original = binding()
    assert (
        original.logical_slot_id
        == "9b90e9b1893c281865c0ed4b3d0480fe425cc91083f1eb42533e72c8f955477b"
    )
    assert (
        original.commitment_sha256
        == "b74579983e6413410ebb6bfd4ca2be68be57f2792de30fc0085cd4a078743077"
    )
    metadata_changed = replace(original, account_id="other", route_id="other", base_attempt=99)
    assert metadata_changed.logical_slot_id == original.logical_slot_id
    assert (
        replace(original, logical_call_sha256="d" * 64).logical_slot_id != original.logical_slot_id
    )
    store = InMemorySchedulerV2Cas()
    intent(store, original)
    with pytest.raises(SchedulerV2Error, match="slot_already_exists_or_tombstoned"):
        store.prepare(
            metadata_changed,
            PAYLOAD,
            prepared_boot_id="new",
            fence=ROOT,
            now_unix_ms=22,
            database_now_unix_ms=23,
        )


def test_paid_seams_are_explicitly_false_and_bool_is_not_int() -> None:
    assert binding().paid_go_ready is False
    assert InMemorySchedulerV2Cas.paid_go_ready is False
    assert SchedulerV2DispatchCoordinator.paid_go_ready is False
    assert SchedulerV2CompletionCoordinator.paid_go_ready is False
    with pytest.raises(SchedulerV2Error, match="slot_binding_invalid"):
        binding(ordinal=True)
    with pytest.raises(SchedulerV2Error, match="state_epoch_invalid"):
        StateRootFence("1" * 64, True)


def test_cas_requires_trusted_db_predicate_and_stores_both_evidences() -> None:
    store = InMemorySchedulerV2Cas()
    spec, receipt = intent(store)
    with pytest.raises(SchedulerV2Error, match="database_predicate_evidence_invalid"):
        store.issue_consume_request(
            spec.logical_slot_id,
            generation=0,
            expected_version=receipt.version,
            fence=ROOT,
            now_unix_ms=30,
            database_clock=Clock(31, wrong_predicate=True),
        )
    request = store.issue_consume_request(
        spec.logical_slot_id,
        generation=0,
        expected_version=receipt.version,
        fence=ROOT,
        now_unix_ms=30,
        database_clock=Clock(31),
    )
    with pytest.raises(SchedulerV2Error, match="database_predicate_evidence_invalid"):
        store.consume(request, fence=ROOT, database_clock=Clock(32, wrong_predicate=True))
    response = store.consume(request, fence=ROOT, database_clock=Clock(32))
    assert request.issue_database_evidence.observed_unix_ms == 31
    assert len(response.consume_database_evidence_sha256) == 64


def test_expired_db_observation_never_consumes() -> None:
    store = InMemorySchedulerV2Cas()
    spec, receipt = intent(store)
    with pytest.raises(SchedulerV2Error, match="database_predicate_evidence_invalid"):
        store.issue_consume_request(
            spec.logical_slot_id,
            generation=0,
            expected_version=receipt.version,
            fence=ROOT,
            now_unix_ms=30,
            database_clock=Clock(1_000),
        )


@pytest.mark.parametrize("challenge", (b"x" * 31, bytearray(b"x" * 32)))
def test_nonce_exact_type_and_length(challenge: object) -> None:
    store = InMemorySchedulerV2Cas(challenge_source=lambda _: challenge)  # type: ignore[arg-type]
    spec, receipt = intent(store)
    with pytest.raises(SchedulerV2Error, match="challenge_source_invalid"):
        store.issue_consume_request(
            spec.logical_slot_id,
            generation=0,
            expected_version=receipt.version,
            fence=ROOT,
            now_unix_ms=30,
            database_clock=Clock(31),
        )


def test_nonce_replay_and_tampered_db_evidence_never_reaches_boundary() -> None:
    store = InMemorySchedulerV2Cas()
    _, request, response = consumed(store)
    with pytest.raises(SchedulerV2Error, match="consume_not_fresh"):
        store.consume(request, fence=ROOT, database_clock=Clock(33))
    boundary = Boundary()
    tampered = replace(response, consume_database_evidence_sha256="e" * 64)
    with pytest.raises(SchedulerV2Error, match="consume_response_not_fresh"):
        invoke(store, tampered, boundary=boundary)
    assert boundary.payloads == []


def test_exact_fsynced_marker_has_dispatch_count_one_before_boundary() -> None:
    store = InMemorySchedulerV2Cas()
    _, _, response = consumed(store)
    fsync, boundary, (started, observation) = invoke(store, response)
    assert fsync.receipts == [started]
    assert started.provider_dispatches == 1
    assert boundary.payloads == [PAYLOAD]
    assert observation.result_sha256 == RESULT
    assert not hasattr(SchedulerV2DispatchCoordinator(store), "mark_dispatch_started")
    with pytest.raises(SchedulerV2Error, match="consume_response_not_fresh"):
        invoke(store, response)


def test_coordinator_cannot_mint_completion_and_external_verifier_controls_refund() -> None:
    store = InMemorySchedulerV2Cas()
    _, _, response = consumed(store)
    _, _, (started, _) = invoke(store, response)
    coordinator = SchedulerV2DispatchCoordinator(store)
    assert not hasattr(coordinator, "make_bridge_completion")
    assert not hasattr(coordinator, "complete")
    forged = attestation(started)
    with pytest.raises(SchedulerV2Error, match="completion_attestation_invalid"):
        SchedulerV2CompletionCoordinator(store, verifier=Verifier(False)).complete(forged)
    verified = SchedulerV2CompletionCoordinator(store, verifier=Verifier(True)).complete(forged)
    assert (verified.charged_tokens, verified.refunded_tokens, verified.burned_tokens) == (
        23,
        57,
        0,
    )


def test_completion_binds_external_result_and_usage() -> None:
    store = InMemorySchedulerV2Cas()
    _, _, response = consumed(store)
    _, _, (started, _) = invoke(store, response)
    with pytest.raises(SchedulerV2Error, match="completion_attestation_invalid"):
        SchedulerV2CompletionCoordinator(store, verifier=Verifier(True)).complete(
            attestation(started, result="f" * 64)
        )
    with pytest.raises(SchedulerV2Error, match="completion_attestation_invalid"):
        SchedulerV2CompletionCoordinator(store, verifier=Verifier(True)).complete(
            attestation(started, used=81)
        )


@pytest.mark.parametrize("failure", ("fsync", "boundary", "deadline"))
def test_post_cas_failures_burn_full_reservation_and_block_retry(failure: str) -> None:
    store = InMemorySchedulerV2Cas()
    spec, _, response = consumed(store)
    arguments = {
        "fsync": {"fsync": Recorder(fail=True)},
        "boundary": {"boundary": Boundary(fail=True)},
        "deadline": {"clock": Clock(1_000)},
    }[failure]
    with pytest.raises((OSError, TimeoutError, SchedulerV2Error)):
        invoke(store, response, **arguments)
    frozen = store.lookup(spec.logical_slot_id)
    assert frozen is not None and frozen.phase is AttemptPhase.OUTCOME_UNKNOWN
    assert (frozen.provider_dispatches, frozen.burned_tokens) == (1, 80)
    with pytest.raises(SchedulerV2Error, match="consume_response_not_fresh"):
        invoke(store, response)


def test_payload_swap_is_rejected_before_boundary() -> None:
    store = InMemorySchedulerV2Cas()
    _, _, response = consumed(store)
    boundary = Boundary()
    with pytest.raises(SchedulerV2Error, match="dispatch_payload_changed"):
        invoke(store, response, payload=b"changed", boundary=boundary)
    assert boundary.payloads == []


def test_generation_requires_proven_no_consumption_and_prior_receipt() -> None:
    store = InMemorySchedulerV2Cas()
    spec, _ = intent(store)
    proven = store.prove_predispatch_no_consumption(spec.logical_slot_id, receipt_sha256="4" * 64)
    with pytest.raises(SchedulerV2Error, match="generation_advance_invalid"):
        store.advance_generation(spec.logical_slot_id, prior_receipt_sha256="5" * 64)
    advanced = store.advance_generation(
        spec.logical_slot_id, prior_receipt_sha256=proven.commitment_sha256
    )
    assert advanced.generation == 1


def test_lookup_nonmutation_and_concurrent_reconcile_prepare_are_atomic() -> None:
    store = InMemorySchedulerV2Cas()
    spec = binding()
    assert store.lookup(spec.logical_slot_id) is None
    barrier = Barrier(2)

    def prepare_race():
        barrier.wait()
        with suppress(SchedulerV2Error):
            intent(store, spec)

    def reconcile_race():
        barrier.wait()
        store.reconcile_missing(spec, fence=ROOT)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (prepare_race, reconcile_race)))
    final = store.lookup(spec.logical_slot_id)
    assert final is not None and final.phase is AttemptPhase.TOMBSTONED
