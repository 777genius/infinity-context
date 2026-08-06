from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from phase_c_canary.journal import (
    PROVIDER_USAGE_STRUCTURAL_FINGERPRINT,
    JournalError,
    ProviderUsageJournal,
    SlotState,
)


@pytest.fixture
def journal(tmp_path: Path):
    value = ProviderUsageJournal(tmp_path / "usage.sqlite3")
    yield value
    value.close()


def test_crash_before_dispatch_remains_retryable(journal: ProviderUsageJournal) -> None:
    journal.reserve("slot-1", {"prompt": "one"})
    retryable, unknown = journal.recover()
    assert retryable == ("slot-1",)
    assert unknown == ()
    assert journal.get("slot-1").state is SlotState.RESERVED


def test_crash_after_dispatch_becomes_unknown_and_is_not_retryable(
    journal: ProviderUsageJournal,
) -> None:
    journal.reserve("slot-1", {"prompt": "one"})
    journal.mark_dispatched("slot-1")
    retryable, unknown = journal.recover()
    assert retryable == ()
    assert unknown == ("slot-1",)
    assert journal.get("slot-1").state is SlotState.OUTCOME_UNKNOWN
    with pytest.raises(JournalError):
        journal.mark_dispatched("slot-1")


def test_outcome_unknown_is_returned_on_every_restart(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    first = ProviderUsageJournal(path)
    first.reserve("slot-1", {"prompt": "one"})
    first.mark_dispatched("slot-1")
    assert first.recover() == ((), ("slot-1",))
    first.close()
    second = ProviderUsageJournal(path)
    try:
        assert second.recover() == ((), ("slot-1",))
    finally:
        second.close()


def test_response_and_receipt_commit_atomically(journal: ProviderUsageJournal) -> None:
    journal.reserve("slot-1", {"prompt": "one"})
    journal.mark_dispatched("slot-1")
    journal.commit_result("slot-1", {"text": "ok"}, {"signed": True})
    record = journal.get("slot-1")
    assert record.state is SlotState.COMMITTED
    assert record.envelope == {"text": "ok"}
    assert record.receipt == {"signed": True}


def test_slot_request_identity_is_write_once(journal: ProviderUsageJournal) -> None:
    journal.reserve("slot-1", {"prompt": "one"})
    with pytest.raises(JournalError, match="different request"):
        journal.reserve("slot-1", {"prompt": "two"})


def test_exact_structural_fingerprint_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    journal = ProviderUsageJournal(path)
    journal.close()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT schema_version, structural_fingerprint FROM provider_usage_meta"
        ).fetchall() == [(3, PROVIDER_USAGE_STRUCTURAL_FINGERPRINT)]
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()
            == []
        )
    finally:
        connection.close()


def test_trigger_injection_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "usage.sqlite3"
    journal = ProviderUsageJournal(path)
    journal.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TRIGGER forbidden AFTER INSERT ON provider_usage_v3 BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(JournalError, match="structural fingerprint"):
        ProviderUsageJournal(path)
