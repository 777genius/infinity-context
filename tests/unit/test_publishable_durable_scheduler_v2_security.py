from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from infinity_context_server.publishable_durable_scheduler.v2_contracts import (
    SchedulerV2Error,
    StateRootFence,
)
from infinity_context_server.publishable_durable_scheduler.v2_in_memory import (
    InMemorySchedulerV2Cas,
)

from tests.unit.test_publishable_durable_scheduler_v2 import (
    INTENT,
    ROOT,
    Clock,
    binding,
    consumed,
    intent,
)


def test_prepare_boot_cannot_dispatch_and_stale_fence_is_rejected() -> None:
    store = InMemorySchedulerV2Cas()
    spec = binding()
    prepared = store.prepare(
        spec,
        b"payload",
        prepared_boot_id="prepare-boot",
        fence=ROOT,
        now_unix_ms=10,
        database_now_unix_ms=11,
    )
    arguments = dict(
        logical_slot_id=spec.logical_slot_id,
        generation=0,
        expected_version=prepared.version,
        durable_intent_receipt_sha256=INTENT,
        now_unix_ms=20,
        database_now_unix_ms=21,
    )
    with pytest.raises(SchedulerV2Error, match="dispatch_boot_not_fresh"):
        store.record_durable_intent(**arguments, dispatch_boot_id="prepare-boot", fence=ROOT)
    with pytest.raises(SchedulerV2Error, match="state_root_fence_changed"):
        store.record_durable_intent(
            **arguments,
            dispatch_boot_id="dispatch-boot",
            fence=StateRootFence("9" * 64, 8),
        )


def test_concurrent_consume_mints_exactly_one_fresh_response() -> None:
    store = InMemorySchedulerV2Cas()
    spec, receipt = intent(store)
    request = store.issue_consume_request(
        spec.logical_slot_id,
        generation=0,
        expected_version=receipt.version,
        fence=ROOT,
        now_unix_ms=30,
        database_clock=Clock(31),
    )

    def consume_once(_: int) -> bool:
        try:
            store.consume(request, fence=ROOT, database_clock=Clock(32))
            return True
        except SchedulerV2Error:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume_once, range(2)))
    assert results.count(True) == 1


def test_generation_advance_is_impossible_after_cas_consumption() -> None:
    store = InMemorySchedulerV2Cas()
    spec, _, _ = consumed(store)
    with pytest.raises(SchedulerV2Error, match="predispatch_not_proven"):
        store.prove_predispatch_no_consumption(spec.logical_slot_id, receipt_sha256="4" * 64)
