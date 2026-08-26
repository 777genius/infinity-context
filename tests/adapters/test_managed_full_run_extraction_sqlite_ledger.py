from __future__ import annotations

import inspect
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.managed_full_run_extraction_sqlite_ledger import (
    SQLiteManagedFullRunExtractionLedger,
)
from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_MAX_RECEIPTS,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionCheckpoint,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerError,
    ManagedFullRunExtractionReceipt,
)

_KEY = bytes(range(32))


def _sha(value: int) -> str:
    return f"{value:064x}"


def _context(expected: int) -> ManagedFullRunExtractionContext:
    return ManagedFullRunExtractionContext(
        profile_id="managed-mem0-v5-publishable",
        run_id_sha256=_sha(1),
        binding_commitment_sha256=_sha(2),
        methodology_commitment_sha256=_sha(3),
        admission_commitment_sha256=_sha(4),
        ingestion_root_sha256=_sha(5),
        a1_terminal_commitment_sha256=_sha(6),
        a1_manifest_context_sha256=_sha(8),
        runtime_binding_commitment_sha256=_sha(7),
        expected_receipt_count=expected,
    )


def _receipt(sequence: int, *, provider_offset: int = 0) -> ManagedFullRunExtractionReceipt:
    base = sequence * 10 + 100
    return ManagedFullRunExtractionReceipt(
        sequence=sequence,
        operation_id_sha256=_sha(base),
        unit_identity_sha256=_sha(base + 1),
        request_body_sha256=_sha(base + 2),
        output_text_sha256=_sha(base + 3),
        provider_receipt_sha256=_sha(base + 4 + provider_offset),
        runtime_binding_commitment_sha256=_sha(7),
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
    )


def _page(start: int, count: int) -> tuple[ManagedFullRunExtractionReceipt, ...]:
    return tuple(_receipt(sequence) for sequence in range(start, start + count))


def test_ledger_has_no_global_count_query() -> None:
    source = inspect.getsource(SQLiteManagedFullRunExtractionLedger).upper()
    assert "COUNT(*)" not in source


def test_page_resume_exact_replay_finalize_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "full-run.sqlite3"
    context = _context(1_025)
    ledger = SQLiteManagedFullRunExtractionLedger.open_or_create(path, authentication_key=_KEY)
    ledger.begin(context)
    first = _page(0, 512)
    ledger.append_page(first)
    assert ledger.read_checkpoint().next_sequence == 512
    assert ledger.full_scan_pass_count == 0
    assert ledger.full_scan_receipt_count == 0
    ledger.close()

    resumed = SQLiteManagedFullRunExtractionLedger.open_or_create(path, authentication_key=_KEY)
    assert resumed.full_scan_pass_count == 1
    assert resumed.full_scan_receipt_count == 512
    checkpoint = resumed.read_checkpoint()
    assert checkpoint == ManagedFullRunExtractionCheckpoint(
        context_commitment_sha256=context.commitment_sha256,
        receipt_count=512,
        expected_receipt_count=1_025,
        state="active",
    )
    assert checkpoint.next_sequence == 512
    assert resumed.readback() is None
    assert resumed.full_scan_pass_count == 1
    assert resumed.full_scan_receipt_count == 512
    resumed.begin(context)
    resumed.append_page(first)
    resumed.append_page(_page(512, 512))
    resumed.append_page(_page(1_024, 1))
    terminal = resumed.finalize()
    assert terminal.receipt_count == 1_025
    assert terminal.page_count == 3
    assert terminal.prompt_tokens == 3_075
    assert terminal.completion_tokens == 2_050
    assert terminal.total_tokens == 5_125
    assert resumed.read_checkpoint().terminal == terminal
    assert resumed.full_scan_pass_count == 2
    assert resumed.full_scan_receipt_count == 1_537
    assert resumed.max_scan_batch_size <= FULL_RUN_EXTRACTION_PAGE_SIZE
    assert resumed.finalize() == terminal
    assert resumed.readback() == terminal
    assert resumed.full_scan_pass_count == 2
    assert resumed.full_scan_receipt_count == 1_537
    resumed.close()

    reopened = SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=_KEY)
    assert reopened.full_scan_pass_count == 1
    assert reopened.full_scan_receipt_count == 1_025
    assert reopened.readback() == terminal
    assert reopened.read_checkpoint().next_sequence == 1_025
    assert reopened.full_scan_pass_count == 1
    assert reopened.full_scan_receipt_count == 1_025
    assert reopened.max_scan_batch_size <= FULL_RUN_EXTRACTION_PAGE_SIZE
    reopened.close()


def test_divergent_replay_and_partial_overlap_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "conflict.sqlite3"
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    ledger.begin(_context(513))
    ledger.append_page(_page(0, 512))
    divergent = list(_page(0, 512))
    divergent[10] = _receipt(10, provider_offset=1)
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="replay_conflict"):
        ledger.append_page(tuple(divergent))
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="overlap"):
        ledger.append_page(_page(511, 2))
    ledger.append_page(_page(512, 1))
    assert ledger.finalize().receipt_count == 513
    ledger.close()


def test_incomplete_finalize_and_sequence_gap_reject(tmp_path: Path) -> None:
    ledger = SQLiteManagedFullRunExtractionLedger.create(
        tmp_path / "incomplete.sqlite3", authentication_key=_KEY
    )
    ledger.begin(_context(2))
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="sequence_gap"):
        ledger.append_page(_page(1, 1))
    ledger.append_page(_page(0, 1))
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="count_incomplete"):
        ledger.finalize()
    ledger.close()


def test_checkpoint_contract_rejects_impossible_progress() -> None:
    checkpoint = ManagedFullRunExtractionCheckpoint(
        context_commitment_sha256=_context(2).commitment_sha256,
        receipt_count=1,
        expected_receipt_count=2,
        state="active",
    )
    for mutation in (
        {"receipt_count": 3},
        {"expected_receipt_count": True},
        {"state": "unknown"},
    ):
        with pytest.raises(ManagedFullRunExtractionLedgerError, match="checkpoint_invalid"):
            replace(checkpoint, **mutation)


@pytest.mark.parametrize("mutation", ["delete", "payload", "mac", "state"])
def test_reopen_rejects_missing_or_tampered_authenticated_material(
    tmp_path: Path,
    mutation: str,
) -> None:
    path = tmp_path / f"tamper-{mutation}.sqlite3"
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    ledger.begin(_context(3))
    ledger.append_page(_page(0, 3))
    ledger.finalize()
    ledger.close()

    db = sqlite3.connect(path)
    if mutation == "delete":
        db.execute("DELETE FROM receipts WHERE sequence=1")
    elif mutation == "payload":
        db.execute("UPDATE receipts SET payload_json='{}' WHERE sequence=1")
    elif mutation == "mac":
        db.execute(
            "UPDATE receipts SET row_mac_sha256=? WHERE sequence=1",
            (_sha(999),),
        )
    else:
        db.execute(
            "UPDATE run SET state_mac_sha256=? WHERE singleton=1",
            (_sha(999),),
        )
    db.commit()
    db.close()

    with pytest.raises(ManagedFullRunExtractionLedgerError):
        SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=_KEY)


def test_open_session_rejects_external_receipt_change_without_rescan(
    tmp_path: Path,
) -> None:
    path = tmp_path / "changed-session.sqlite3"
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    ledger.begin(_context(1))
    ledger.append_page(_page(0, 1))
    ledger.finalize()
    work = (ledger.full_scan_pass_count, ledger.full_scan_receipt_count)

    db = sqlite3.connect(path)
    db.execute("UPDATE receipts SET payload_json='{}' WHERE sequence=0")
    db.commit()
    db.close()

    with pytest.raises(ManagedFullRunExtractionLedgerError, match="session_changed"):
        ledger.readback()
    assert (ledger.full_scan_pass_count, ledger.full_scan_receipt_count) == work
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="session_changed"):
        ledger.close()


def test_wrong_key_and_rogue_schema_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "wrong-key.sqlite3"
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    ledger.begin(_context(1))
    ledger.append_page(_page(0, 1))
    ledger.close()
    with pytest.raises(
        ManagedFullRunExtractionLedgerError,
        match="authentication_invalid",
    ):
        SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=b"x" * 32)

    db = sqlite3.connect(path)
    db.execute(
        "CREATE TRIGGER suppress_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(IGNORE); END"
    )
    db.commit()
    db.close()
    with pytest.raises(ManagedFullRunExtractionLedgerError, match="schema_invalid"):
        SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=_KEY)


def test_secure_zero_table_bootstrap_is_recoverable(tmp_path: Path) -> None:
    path = tmp_path / "bootstrap.sqlite3"
    path.touch(mode=0o600)
    ledger = SQLiteManagedFullRunExtractionLedger.open_or_create(path, authentication_key=_KEY)
    ledger.begin(_context(1))
    ledger.append_page(_page(0, 1))
    assert ledger.finalize().receipt_count == 1
    ledger.close()


def test_full_124344_receipt_capacity_is_paged_and_bounded(tmp_path: Path) -> None:
    path = tmp_path / "full-capacity.sqlite3"
    ledger = SQLiteManagedFullRunExtractionLedger.create(path, authentication_key=_KEY)
    ledger.begin(_context(FULL_RUN_EXTRACTION_MAX_RECEIPTS))
    for start in range(
        0,
        FULL_RUN_EXTRACTION_MAX_RECEIPTS,
        FULL_RUN_EXTRACTION_PAGE_SIZE,
    ):
        count = min(
            FULL_RUN_EXTRACTION_PAGE_SIZE,
            FULL_RUN_EXTRACTION_MAX_RECEIPTS - start,
        )
        ledger.append_page(_page(start, count))
    assert ledger.read_checkpoint().receipt_count == FULL_RUN_EXTRACTION_MAX_RECEIPTS
    assert ledger.full_scan_pass_count == 0
    assert ledger.full_scan_receipt_count == 0
    terminal = ledger.finalize()
    assert terminal.receipt_count == FULL_RUN_EXTRACTION_MAX_RECEIPTS
    assert terminal.page_count == 243
    assert terminal.total_tokens == FULL_RUN_EXTRACTION_MAX_RECEIPTS * 5
    assert ledger.full_scan_pass_count == 1
    assert ledger.full_scan_receipt_count == FULL_RUN_EXTRACTION_MAX_RECEIPTS
    assert ledger.max_scan_batch_size <= FULL_RUN_EXTRACTION_PAGE_SIZE
    ledger.close()

    reopened = SQLiteManagedFullRunExtractionLedger.open(path, authentication_key=_KEY)
    assert reopened.full_scan_pass_count == 1
    assert reopened.full_scan_receipt_count == FULL_RUN_EXTRACTION_MAX_RECEIPTS
    assert reopened.readback() == terminal
    assert reopened.full_scan_pass_count == 1
    assert reopened.full_scan_receipt_count == FULL_RUN_EXTRACTION_MAX_RECEIPTS
    assert reopened.max_scan_batch_size <= FULL_RUN_EXTRACTION_PAGE_SIZE
    reopened.close()
