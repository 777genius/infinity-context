"""Durable Mem0 v5 evidence-store tests split from the HTTP adapter contract."""

import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_mem0_oss_v5_persistence import (
    Mem0V5EvidenceStoreError,
    Mem0V5StoreCheckpoint,
)
from test_memory_comparison_mem0_oss_v5_adapters import (
    AUTH_KEY,
    CHECKPOINT_KEY,
    Mem0OssFullRunAdmission,
    Mem0OssManifestUnit,
    Mem0OssReceiptDisposition,
    RuntimeReceiptVerificationResult,
    SQLiteMem0V5EvidenceStore,
    _abort_cleanup,
    _admission,
    _admission_many,
    _cleanup,
    _created_store,
    _digest,
    _receipt,
    _receipt_at,
    _seal,
    _storage,
)


def test_store_recomputes_exact_seal_inventory_cleanup_and_reopens(tmp_path: Path) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    storage = _storage(receipt)
    seal = _seal(admission, receipt, storage)
    cleanup = _cleanup(admission, receipt, storage, seal)
    path = tmp_path / "evidence.sqlite3"
    store = _created_store(path)
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=receipt)
    store.put_storage(unit_index=0, storage=storage)
    store.put_seal(seal)
    store.put_cleanup(cleanup)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()

    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    assert len(list(reopened.iter_public_evidence())) == 6
    reopened.close()
    assert path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("count", [500, 5_882])
def test_large_admission_is_chunked_and_validation_query_count_is_bounded(
    tmp_path: Path, count: int
) -> None:
    admission, units = _admission_many(count)
    store = _created_store(tmp_path / f"large-{count}.sqlite3")
    statements: list[str] = []
    store._connection.set_trace_callback(statements.append)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    evidence = list(store.iter_public_evidence())
    select_count = sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    expected_pages = (count + 63) // 64
    assert len(evidence) == expected_pages + 1
    assert all(len(json.dumps(item["payload"]).encode()) < 64_000 for item in evidence)
    assert select_count < 40
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=tmp_path / f"large-{count}.sqlite3",
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    reopened.close()


def test_second_admission_is_rejected_without_replacing_original_authority(
    tmp_path: Path,
) -> None:
    path = tmp_path / "second-admission.sqlite3"
    original, original_units = _admission()
    replacement, replacement_units = _admission_many(1)
    store = _created_store(path)
    store.put_admission(original, units=original_units)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_order_invalid"):
        store.put_admission(replacement, units=replacement_units)
    store.validate()
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    admission_evidence = list(reopened.iter_public_evidence())[0]
    assert admission_evidence["subject_sha256"] == original.commitment_sha256
    reopened.close()


def test_store_rejects_cross_operation_storage_failed_seal_and_forged_roots(
    tmp_path: Path,
) -> None:
    admission, units = _admission()
    failed = _receipt(admission, disposition=Mem0OssReceiptDisposition.PROVIDER_FAILED)
    store = _created_store(tmp_path / "failed.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=failed)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_order_invalid"):
        store.put_storage(unit_index=0, storage=_storage(failed))
    completed = _receipt(admission)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_seal(_seal(admission, completed, _storage(completed)))
    forged = _cleanup(admission, failed, None, None)
    object.__setattr__(forged, "operation_inventory_root_sha256", _digest("forged"))
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_cleanup(forged)
    store.close()


def test_store_rejects_route_substitution_and_arbitrary_cleanup_count(tmp_path: Path) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    forged_route = replace(receipt, route_sha256=_digest("other-route"))
    store = _created_store(tmp_path / "bindings.sqlite3")
    store.put_admission(admission, units=units)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_payload_invalid"):
        store.put_receipt(unit_index=0, receipt=forged_route)
    store.put_receipt(unit_index=0, receipt=receipt)
    storage = _storage(receipt)
    store.put_storage(unit_index=0, storage=storage)
    seal = _seal(admission, receipt, storage)
    store.put_seal(seal)
    forged_cleanup = _cleanup(admission, receipt, storage, seal)
    object.__setattr__(forged_cleanup, "deleted_operation_count", 0)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        store.put_cleanup(forged_cleanup)
    store.close()


def test_failed_usage_and_failed_receipt_projection_are_exact(tmp_path: Path) -> None:
    admission, units = _admission()
    failed = _receipt(admission, disposition=Mem0OssReceiptDisposition.PROVIDER_FAILED)
    cleanup = _cleanup(admission, failed, None, None)
    store = _created_store(tmp_path / "failed-cleanup.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=failed)
    store.put_cleanup(cleanup)
    payload = list(store.iter_public_evidence())[-1]["payload"]
    assert payload["failed_receipts"] == [cleanup.failed_receipts[0].public_payload()]
    assert payload["provider_observed_extraction_calls"] == 1
    store.close()


@pytest.mark.parametrize(("dispatched", "deleted"), [(False, 0), (True, 1)])
def test_unsealed_abort_accepts_zero_or_partial_authenticated_deleted_count(
    tmp_path: Path, dispatched: bool, deleted: int
) -> None:
    admission, units = _admission_many(2)
    receipts: dict[int, RuntimeReceiptVerificationResult] = {}
    store = _created_store(tmp_path / f"abort-{dispatched}.sqlite3")
    store.put_admission(admission, units=units)
    if dispatched:
        receipts[0] = _receipt_at(admission, units, 0)
        store.put_receipt(unit_index=0, receipt=receipts[0])
    cleanup = _abort_cleanup(
        admission,
        units,
        receipts,
        deleted_operation_count=deleted,
    )
    store.put_cleanup(cleanup)
    assert list(store.iter_public_evidence())[-1]["payload"]["deleted_operation_count"] == deleted
    store.close()


@pytest.mark.parametrize("mutation", ["receipt", "storage", "seal", "cleanup", "admission"])
def test_cleanup_is_terminal_for_every_store_mutator(tmp_path: Path, mutation: str) -> None:
    admission, units = _admission()
    receipt = _receipt(admission)
    storage = _storage(receipt)
    seal = _seal(admission, receipt, storage)
    cleanup = _cleanup(admission, receipt, storage, seal)
    store = _created_store(tmp_path / f"terminal-{mutation}.sqlite3")
    store.put_admission(admission, units=units)
    store.put_receipt(unit_index=0, receipt=receipt)
    store.put_storage(unit_index=0, storage=storage)
    store.put_seal(seal)
    store.put_cleanup(cleanup)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_terminal_invalid"):
        if mutation == "receipt":
            store.put_receipt(unit_index=0, receipt=receipt)
        elif mutation == "storage":
            store.put_storage(unit_index=0, storage=storage)
        elif mutation == "seal":
            store.put_seal(seal)
        elif mutation == "cleanup":
            store.put_cleanup(cleanup)
        else:
            store.put_admission(admission, units=units)
    store.validate()
    store.close()


@pytest.mark.parametrize("mutation", ["row", "delete", "schema"])
def test_store_tamper_and_deletion_fail_closed(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "tampered.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    connection = sqlite3.connect(path)
    if mutation == "row":
        connection.execute("UPDATE evidence SET payload_json='{}' WHERE sequence=1")
    elif mutation == "delete":
        connection.execute("DELETE FROM evidence WHERE sequence=1")
    else:
        connection.execute("CREATE TRIGGER forged AFTER INSERT ON evidence BEGIN SELECT 1; END")
    connection.commit()
    connection.close()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=checkpoint,
            checkpoint_key=CHECKPOINT_KEY,
        )


def test_store_detects_whole_file_deletion_and_rollback_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "rollback.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    old = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.put_receipt(unit_index=0, receipt=_receipt(admission))
    current = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=old,
            checkpoint_key=CHECKPOINT_KEY,
        )
    path.unlink()
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=current,
            checkpoint_key=CHECKPOINT_KEY,
        )


def test_store_rejects_tampered_external_checkpoint_and_implicit_recreate(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.sqlite3"
    admission, units = _admission()
    store = _created_store(path)
    store.put_admission(admission, units=units)
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()
    replacement = "0" if checkpoint.token[-1] != "0" else "1"
    forged = Mem0V5StoreCheckpoint(token=checkpoint.token[:-1] + replacement)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=forged,
            checkpoint_key=CHECKPOINT_KEY,
        )
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        SQLiteMem0V5EvidenceStore.create(path=path, authentication_key=AUTH_KEY)


def test_checkpoint_rejects_deleted_head_row_without_full_semantic_scan(tmp_path: Path) -> None:
    admission, units = _admission()
    store = _created_store(tmp_path / "deleted-head.sqlite3")
    store.put_admission(admission, units=units)
    store._connection.execute(
        "DELETE FROM evidence WHERE sequence = (SELECT MAX(sequence) FROM evidence)"
    )
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_corrupt"):
        store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    store.close()


def test_single_owner_and_concurrent_admissions_are_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    candidates = (_admission(), _admission_many(1))
    store = _created_store(path)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def write(candidate: tuple[Mem0OssFullRunAdmission, tuple[Mem0OssManifestUnit, ...]]) -> None:
        barrier.wait()
        try:
            store.put_admission(candidate[0], units=candidate[1])
            outcomes.append("written")
        except Mem0V5EvidenceStoreError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=write, args=(candidate,)) for candidate in candidates]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["mem0_v5_evidence_store_order_invalid", "written"]
    store.validate()
    checkpoint = store.issue_checkpoint(checkpoint_key=CHECKPOINT_KEY)
    with pytest.raises(Mem0V5EvidenceStoreError, match="mem0_v5_evidence_store_busy"):
        SQLiteMem0V5EvidenceStore.reopen(
            path=path,
            authentication_key=AUTH_KEY,
            checkpoint=checkpoint,
            checkpoint_key=CHECKPOINT_KEY,
        )
    store.close()
    reopened = SQLiteMem0V5EvidenceStore.reopen(
        path=path,
        authentication_key=AUTH_KEY,
        checkpoint=checkpoint,
        checkpoint_key=CHECKPOINT_KEY,
    )
    reopened.close()
