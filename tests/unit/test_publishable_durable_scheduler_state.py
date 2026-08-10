from __future__ import annotations

from dataclasses import replace

import pytest
from infinity_context_server.publishable_durable_scheduler import (
    SchedulerCallPhase,
    SchedulerContractError,
    SchedulerRunPhase,
)
from publishable_durable_scheduler_test_support import (
    InMemorySchedulerStateStore,
    built_runs,
    sha,
)


@pytest.fixture(scope="module")
def prepared():
    suite, (locomo_run, locomo), (lme_run, lme) = built_runs()
    return suite, locomo_run, locomo, lme_run, lme


def _leased_bound_intent(store: InMemorySchedulerStateStore, call_id: str):
    validator = store.validator
    store.apply(
        call_id,
        lambda run, item: validator.acquire_lease(
            run,
            item,
            now_unix_ms=2_000,
            lease_id="lease-1",
            lease_expires_unix_ms=3_000,
        ),
    )
    store.apply(
        call_id,
        lambda run, item: validator.bind_request(
            run,
            item,
            lease_id="lease-1",
            request_sha256=sha("request"),
        ),
    )
    return store.apply(
        call_id,
        lambda run, item: validator.record_dispatch_intent(
            run,
            item,
            lease_id="lease-1",
            now_unix_ms=2_100,
            bridge_boot_authority_sha256=run.bridge_boot_authority_sha256,
            intent_sha256=sha("intent"),
        ),
    )


def test_exact_answer_then_judge_dependency_transition(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    answer, judge = manifest.shards[0].calls[:2]
    _leased_bound_intent(store, answer.logical_call_id)
    committed = store.apply(
        answer.logical_call_id,
        lambda run_state, item: store.validator.commit_outcome(
            run_state,
            item,
            intent_sha256=sha("intent"),
            receipt_sha256=sha("receipt"),
            completion_tokens=100,
            charged_tokens=100,
        ),
    )

    assert committed.phase is SchedulerCallPhase.COMMITTED
    assert store.run.phase is SchedulerRunPhase.ACTIVE
    assert store.run.consumed_tokens == 100
    store.apply(
        judge.logical_call_id,
        lambda run_state, item: store.validator.acquire_lease(
            run_state,
            item,
            now_unix_ms=2_100,
            lease_id="judge-lease",
            lease_expires_unix_ms=3_100,
            dependency=committed,
        ),
    )
    assert store.calls[judge.logical_call_id].phase is SchedulerCallPhase.LEASED


def test_judge_without_committed_answer_rejects(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    answer, judge = manifest.shards[0].calls[:2]

    with pytest.raises(SchedulerContractError, match="judge_dependency_state"):
        store.validator.acquire_lease(
            store.run,
            store.calls[judge.logical_call_id],
            now_unix_ms=2_000,
            lease_id="judge-lease",
            lease_expires_unix_ms=3_000,
            dependency=store.calls[answer.logical_call_id],
        )


def test_ambiguous_outcome_burns_ceiling_and_freezes_all_dispatch(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    first, _, second = manifest.shards[0].calls[:3]
    _leased_bound_intent(store, first.logical_call_id)
    unknown = store.apply(
        first.logical_call_id,
        lambda run_state, item: store.validator.record_ambiguous_outcome(
            run_state,
            item,
            intent_sha256=sha("intent"),
            ambiguity_sha256=sha("transport-ambiguous"),
        ),
    )

    assert unknown.phase is SchedulerCallPhase.OUTCOME_UNKNOWN
    assert store.run.phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    assert store.run.burned_tokens == first.token_ceiling
    with pytest.raises(SchedulerContractError, match="lease_acquire"):
        store.validator.acquire_lease(
            store.run,
            store.calls[second.logical_call_id],
            now_unix_ms=2_500,
            lease_id="other",
            lease_expires_unix_ms=3_500,
        )
    with pytest.raises(SchedulerContractError, match="lease_acquire"):
        store.validator.acquire_lease(
            store.run,
            unknown,
            now_unix_ms=2_500,
            lease_id="redispatch",
            lease_expires_unix_ms=3_500,
        )


def test_lease_reclaim_allowed_only_before_dispatch_intent(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    first = manifest.shards[0].calls[0]
    validator = store.validator
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.acquire_lease(
            run_state,
            item,
            now_unix_ms=2_000,
            lease_id="lease-1",
            lease_expires_unix_ms=3_000,
        ),
    )
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.bind_request(
            run_state,
            item,
            lease_id="lease-1",
            request_sha256=sha("request"),
        ),
    )
    reclaimed = store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.reclaim_expired_no_intent_lease(
            run_state,
            item,
            now_unix_ms=3_000,
            lease_id="lease-1",
        ),
    )
    assert reclaimed.phase is SchedulerCallPhase.PLANNED
    assert reclaimed.attempt_count == 1
    assert store.run.reserved_tokens == 0
    assert store.run.inflight_logical_call_id is None

    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.acquire_lease(
            run_state,
            item,
            now_unix_ms=3_001,
            lease_id="lease-2",
            lease_expires_unix_ms=4_000,
        ),
    )
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.bind_request(
            run_state,
            item,
            lease_id="lease-2",
            request_sha256=sha("request-2"),
        ),
    )
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.record_dispatch_intent(
            run_state,
            item,
            lease_id="lease-2",
            now_unix_ms=3_500,
            bridge_boot_authority_sha256=run_state.bridge_boot_authority_sha256,
            intent_sha256=sha("intent-2"),
        ),
    )
    with pytest.raises(SchedulerContractError, match="lease_reclaim"):
        validator.reclaim_expired_no_intent_lease(
            store.run,
            store.calls[first.logical_call_id],
            now_unix_ms=4_000,
            lease_id="lease-2",
        )


def test_only_one_inflight_call_prevents_terminal_reservation_stranding(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    first, _, second = manifest.shards[0].calls[:3]
    store.apply(
        first.logical_call_id,
        lambda run_state, item: store.validator.acquire_lease(
            run_state,
            item,
            now_unix_ms=2_000,
            lease_id="first",
            lease_expires_unix_ms=3_000,
        ),
    )
    assert store.run.inflight_logical_call_id == first.logical_call_id
    with pytest.raises(SchedulerContractError, match="lease_acquire"):
        store.validator.acquire_lease(
            store.run,
            store.calls[second.logical_call_id],
            now_unix_ms=2_001,
            lease_id="second",
            lease_expires_unix_ms=3_001,
        )


def test_cross_run_and_immutable_authority_drift_reject(prepared) -> None:
    suite, locomo_run, locomo, lme_run, lme = prepared
    locomo_store = InMemorySchedulerStateStore(suite, locomo_run, locomo)
    lme_store = InMemorySchedulerStateStore(suite, lme_run, lme)
    foreign = next(iter(lme_store.calls.values()))

    hostile_call = replace(locomo.shards[0].calls[0], case_id="hostile-case")
    with pytest.raises(SchedulerContractError, match="manifest_membership"):
        locomo_store.validator.initial_call(hostile_call, shard=locomo.shards[0])

    with pytest.raises(SchedulerContractError, match="cross_run"):
        locomo_store.validator.acquire_lease(
            locomo_store.run,
            foreign,
            now_unix_ms=2_000,
            lease_id="foreign",
            lease_expires_unix_ms=3_000,
        )
    drifted = replace(
        locomo_store.run,
        dispatch_deadline_unix_ms=locomo_store.run.dispatch_deadline_unix_ms + 1,
    )
    own = next(iter(locomo_store.calls.values()))
    with pytest.raises(SchedulerContractError, match="authority_drift"):
        locomo_store.validator.acquire_lease(
            drifted,
            own,
            now_unix_ms=2_000,
            lease_id="drifted",
            lease_expires_unix_ms=3_000,
        )


def test_wrong_bridge_boot_and_deadline_reject(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    first = manifest.shards[0].calls[0]
    validator = store.validator
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.acquire_lease(
            run_state,
            item,
            now_unix_ms=2_000,
            lease_id="lease-1",
            lease_expires_unix_ms=3_000,
        ),
    )
    store.apply(
        first.logical_call_id,
        lambda run_state, item: validator.bind_request(
            run_state,
            item,
            lease_id="lease-1",
            request_sha256=sha("request"),
        ),
    )
    with pytest.raises(SchedulerContractError, match="dispatch_intent"):
        validator.record_dispatch_intent(
            store.run,
            store.calls[first.logical_call_id],
            lease_id="lease-1",
            now_unix_ms=2_100,
            bridge_boot_authority_sha256=sha("spoofed-boot"),
            intent_sha256=sha("intent"),
        )
    with pytest.raises(SchedulerContractError, match="dispatch_intent"):
        validator.record_dispatch_intent(
            store.run,
            store.calls[first.logical_call_id],
            lease_id="lease-1",
            now_unix_ms=3_000,
            bridge_boot_authority_sha256=store.run.bridge_boot_authority_sha256,
            intent_sha256=sha("late-intent"),
        )

    fresh = InMemorySchedulerStateStore(suite, run, manifest)
    with pytest.raises(SchedulerContractError, match="lease_acquire"):
        validator.acquire_lease(
            fresh.run,
            fresh.calls[first.logical_call_id],
            now_unix_ms=fresh.run.dispatch_deadline_unix_ms,
            lease_id="late",
            lease_expires_unix_ms=fresh.run.dispatch_deadline_unix_ms + 1,
        )

    exhausted = validator.exhaust_deadline(
        fresh.run,
        tuple(sorted(fresh.calls.values(), key=lambda item: item.ordinal)),
        now_unix_ms=fresh.run.dispatch_deadline_unix_ms,
    )
    assert exhausted.phase is SchedulerRunPhase.DEADLINE_EXHAUSTED


def test_known_failure_is_terminal_and_state_queries_are_bounded(prepared) -> None:
    suite, run, manifest, _, _ = prepared
    store = InMemorySchedulerStateStore(suite, run, manifest)
    first = manifest.shards[0].calls[0]
    _leased_bound_intent(store, first.logical_call_id)
    failed = store.apply(
        first.logical_call_id,
        lambda run_state, item: store.validator.record_known_failure(
            run_state,
            item,
            intent_sha256=sha("intent"),
            failure_sha256=sha("known-failure"),
            charged_tokens=7,
        ),
    )
    assert failed.phase is SchedulerCallPhase.FAILED_KNOWN
    assert store.run.phase is SchedulerRunPhase.FAILED_KNOWN
    assert len(store.read_page(after_ordinal=-1, limit=256)) == 256
    assert tuple(item.ordinal for item in store.read_page(after_ordinal=255, limit=3)) == (
        256,
        257,
        258,
    )
    with pytest.raises(SchedulerContractError, match="state_query"):
        store.read_page(after_ordinal=-1, limit=257)
