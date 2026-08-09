from __future__ import annotations

import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteError,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallPhase,
    SchedulerRunPhase,
)
from publishable_durable_scheduler_test_support import built_runs, sha

_SECRET = b"s" * 32


@pytest.fixture(scope="module")
def prepared():
    suite, locomo, _ = built_runs()
    return suite, *locomo


def _store(tmp_path: Path, prepared, *, secret: bytes = _SECRET):
    suite, run, manifest = prepared
    private = tmp_path / "private"
    return SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=secret,
        suite=suite,
        run=run,
        manifest=manifest,
    )


def _intent(store: SQLiteDurableSchedulerStore, call_id: str) -> None:
    store.acquire_lease(
        call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    store.bind_request(call_id, lease_id="lease-1", request_sha256=sha("request"))
    store.record_dispatch_intent(
        call_id,
        lease_id="lease-1",
        now_unix_ms=2_100,
        bridge_boot_authority_sha256=store.read_run().bridge_boot_authority_sha256,
        intent_sha256=sha("intent"),
    )


def test_initial_manifest_reopen_and_bounded_queries(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    database = tmp_path / "private" / "scheduler.sqlite3"
    assert store.paid_go_ready is False
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    assert len(store.read_calls(after_ordinal=-1, limit=257)) == 257
    assert tuple(item.event_kind for item in store.read_events(after_event_id=-1, limit=257)) == (
        "manifest_initialized",
    )
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run() == store.read_run()
    with pytest.raises(SchedulerSQLiteError, match="query_invalid"):
        store.read_calls(after_ordinal=-1, limit=258)
    with pytest.raises(SchedulerSQLiteError, match="authentication"):
        _store(tmp_path, prepared, secret=b"x" * 32)


def test_longmemeval_exact_run_reopens_and_cross_run_is_rejected(tmp_path: Path) -> None:
    suite, locomo, longmemeval = built_runs()
    run, manifest = longmemeval
    private = tmp_path / "private"
    store = SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )
    observed = []
    after = -1
    while True:
        page = store.read_calls(after_ordinal=after, limit=257)
        observed.extend(page)
        if len(page) < 257:
            break
        after = page[-1].ordinal
    assert len(observed) == 2_000
    assert observed[-1].ordinal == 1_999
    reopened = SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )
    assert reopened.read_run().expected_call_count == 2_000
    with pytest.raises(SchedulerSQLiteError, match="manifest_drift"):
        SQLiteDurableSchedulerStore(
            private / "scheduler.sqlite3",
            private_directory=private,
            authentication_secret=_SECRET,
            suite=suite,
            run=locomo[0],
            manifest=locomo[1],
        )


def test_atomic_answer_commit_persists_only_opaque_ciphertext(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    first = store.read_calls(after_ordinal=-1, limit=1)[0]
    _intent(store, first.logical_call_id)
    ciphertext = os.urandom(96)
    committed = store.commit_outcome(
        first.logical_call_id,
        intent_sha256=sha("intent"),
        receipt_sha256=sha("receipt"),
        charged_tokens=17,
        answer_ciphertext=ciphertext,
    )
    assert committed.phase is SchedulerCallPhase.COMMITTED
    assert store.read_private_answer_ciphertext(first.logical_call_id) == ciphertext
    assert store.read_run().consumed_tokens == 17
    assert tuple(item.event_kind for item in store.read_events(after_event_id=-1, limit=257)) == (
        "manifest_initialized",
        "lease_acquired",
        "request_bound",
        "dispatch_intent_recorded",
        "outcome_committed",
    )
    reopened = _store(tmp_path, prepared)
    assert reopened.read_private_answer_ciphertext(first.logical_call_id) == ciphertext

    connection = sqlite3.connect(tmp_path / "private" / "scheduler.sqlite3")
    try:
        event_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(scheduler_events)")
        )
        assert not {"body", "payload", "plaintext", "ciphertext"}.intersection(event_columns)
    finally:
        connection.close()


def test_outcome_unknown_freeze_survives_restart(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    first, _, second = store.read_calls(after_ordinal=-1, limit=3)
    _intent(store, first.logical_call_id)
    unknown = store.record_ambiguous_outcome(
        first.logical_call_id,
        intent_sha256=sha("intent"),
        ambiguity_sha256=sha("ambiguous"),
    )
    assert unknown.phase is SchedulerCallPhase.OUTCOME_UNKNOWN
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().phase is SchedulerRunPhase.FROZEN_OUTCOME_UNKNOWN
    assert reopened.read_run().inflight_logical_call_id is None
    assert reopened.read_run().burned_tokens == first.token_ceiling
    with pytest.raises(SchedulerSQLiteError, match="lease_acquire"):
        reopened.acquire_lease(
            second.logical_call_id,
            now_unix_ms=2_500,
            lease_id="forbidden",
            lease_expires_unix_ms=3_500,
        )


def test_no_intent_reclaim_is_durable_and_releases_single_inflight(
    tmp_path: Path, prepared
) -> None:
    store = _store(tmp_path, prepared)
    first = store.read_calls(after_ordinal=-1, limit=1)[0]
    store.acquire_lease(
        first.logical_call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    store.bind_request(
        first.logical_call_id,
        lease_id="lease-1",
        request_sha256=sha("request"),
    )
    reclaimed = store.reclaim_expired_no_intent_lease(
        first.logical_call_id,
        now_unix_ms=3_000,
        lease_id="lease-1",
    )
    assert reclaimed.phase is SchedulerCallPhase.PLANNED
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().reserved_tokens == 0
    assert reopened.read_run().inflight_logical_call_id is None
    assert reopened.read_call(first.logical_call_id).attempt_count == 1


def test_concurrent_stores_preserve_exact_single_inflight(tmp_path: Path, prepared) -> None:
    first_store = _store(tmp_path, prepared)
    second_store = _store(tmp_path, prepared)
    first, _, second = first_store.read_calls(after_ordinal=-1, limit=3)
    barrier = Barrier(2)

    def acquire(store: SQLiteDurableSchedulerStore, logical_call_id: str, lease_id: str) -> str:
        barrier.wait()
        try:
            store.acquire_lease(
                logical_call_id,
                now_unix_ms=2_000,
                lease_id=lease_id,
                lease_expires_unix_ms=3_000,
            )
        except SchedulerSQLiteError as error:
            return error.code
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            future.result()
            for future in (
                executor.submit(acquire, first_store, first.logical_call_id, "first"),
                executor.submit(acquire, second_store, second.logical_call_id, "second"),
            )
        )
    assert results.count("ok") == 1
    assert sum("lease_acquire_invalid" in item for item in results) == 1
    reopened = _store(tmp_path, prepared)
    assert reopened.read_run().inflight_logical_call_id in {
        first.logical_call_id,
        second.logical_call_id,
    }
