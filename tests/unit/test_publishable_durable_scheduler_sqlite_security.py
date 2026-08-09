from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    ANSWER_CIPHERTEXT_BYTES_CAP,
    SchedulerSQLiteError,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_store import (
    SQLiteDurableSchedulerStore,
)
from publishable_durable_scheduler_test_support import built_runs, sha

_SECRET = b"s" * 32


@pytest.fixture(scope="module")
def prepared():
    suite, locomo, _ = built_runs()
    return suite, *locomo


def _store(tmp_path: Path, prepared):
    suite, run, manifest = prepared
    private = tmp_path / "private"
    return SQLiteDurableSchedulerStore(
        private / "scheduler.sqlite3",
        private_directory=private,
        authentication_secret=_SECRET,
        suite=suite,
        run=run,
        manifest=manifest,
    )


def _database(tmp_path: Path) -> Path:
    return tmp_path / "private" / "scheduler.sqlite3"


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


def _mutate(database: Path, statement: str, parameters: tuple[object, ...] = ()) -> None:
    connection = sqlite3.connect(database)
    try:
        connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def test_rejects_unsafe_directory_database_symlink_and_hardlink(tmp_path: Path, prepared) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o755)
    with pytest.raises(SchedulerSQLiteError, match="private_directory_unsafe"):
        _store(tmp_path, prepared)
    private.chmod(0o700)
    store = _store(tmp_path, prepared)
    store.verify()
    database = _database(tmp_path)
    database.chmod(0o644)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)
    database.chmod(0o600)
    hardlink = private / "scheduler-hardlink.sqlite3"
    os.link(database, hardlink)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)
    hardlink.unlink()
    database.unlink()
    target = private / "target.sqlite3"
    target.touch(mode=0o600)
    database.symlink_to(target.name)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)


@pytest.mark.skipif(os.geteuid() != 0, reason="foreign owner needs root test sandbox")
def test_rejects_foreign_owned_database(tmp_path: Path, prepared) -> None:
    _store(tmp_path, prepared)
    database = _database(tmp_path)
    os.chown(database, 65534, 65534)
    with pytest.raises(SchedulerSQLiteError, match="database_unsafe"):
        _store(tmp_path, prepared)


@pytest.mark.parametrize(
    ("statement", "match"),
    [
        ("UPDATE scheduler_calls SET phase = 'committed' WHERE ordinal = 0", "authentication"),
        ("UPDATE scheduler_runs SET consumed_tokens = 1", "authentication"),
        (
            "UPDATE scheduler_events SET event_kind = 'tampered' WHERE event_id = 1",
            "event_authentication",
        ),
    ],
)
def test_authenticated_rows_and_events_reject_tamper(
    tmp_path: Path, prepared, statement: str, match: str
) -> None:
    _store(tmp_path, prepared)
    _mutate(_database(tmp_path), statement)
    with pytest.raises(SchedulerSQLiteError, match=match):
        _store(tmp_path, prepared)


def test_ciphertext_tamper_and_oversize_are_rejected(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    call = store.read_calls(after_ordinal=-1, limit=1)[0]
    _intent(store, call.logical_call_id)
    with pytest.raises(SchedulerSQLiteError, match="ciphertext_invalid"):
        store.commit_outcome(
            call.logical_call_id,
            intent_sha256=sha("intent"),
            receipt_sha256=sha("receipt"),
            charged_tokens=1,
            answer_ciphertext=b"x" * (ANSWER_CIPHERTEXT_BYTES_CAP + 1),
        )
    store.commit_outcome(
        call.logical_call_id,
        intent_sha256=sha("intent"),
        receipt_sha256=sha("receipt"),
        charged_tokens=1,
        answer_ciphertext=b"opaque-ciphertext",
    )
    _mutate(
        _database(tmp_path),
        "UPDATE scheduler_calls SET answer_ciphertext = ? WHERE ordinal = 0",
        (b"tampered-ciphertext",),
    )
    with pytest.raises(SchedulerSQLiteError, match="ciphertext_authentication"):
        _store(tmp_path, prepared)


def test_event_tail_truncation_and_extra_schema_are_rejected(tmp_path: Path, prepared) -> None:
    store = _store(tmp_path, prepared)
    call = store.read_calls(after_ordinal=-1, limit=1)[0]
    store.acquire_lease(
        call.logical_call_id,
        now_unix_ms=2_000,
        lease_id="lease-1",
        lease_expires_unix_ms=3_000,
    )
    _mutate(_database(tmp_path), "DELETE FROM scheduler_events WHERE event_id = 2")
    with pytest.raises(SchedulerSQLiteError, match="event_head"):
        _store(tmp_path, prepared)

    other = tmp_path / "other"
    other.mkdir()
    _store(other, prepared)
    _mutate(_database(other), "CREATE TABLE untrusted_extra (value TEXT)")
    with pytest.raises(SchedulerSQLiteError, match="schema_invalid"):
        _store(other, prepared)


def test_corrupt_and_truncated_database_fail_closed(tmp_path: Path, prepared) -> None:
    _store(tmp_path, prepared)
    database = _database(tmp_path)
    database.write_bytes(b"not a sqlite database")
    database.chmod(0o600)
    with pytest.raises(SchedulerSQLiteError, match="integrity_invalid|schema_invalid"):
        _store(tmp_path, prepared)

    other = tmp_path / "truncated"
    other.mkdir()
    _store(other, prepared)
    truncated = _database(other)
    contents = truncated.read_bytes()
    truncated.write_bytes(contents[:4096])
    truncated.chmod(0o600)
    with pytest.raises(SchedulerSQLiteError, match="integrity_invalid|schema_invalid"):
        _store(other, prepared)
