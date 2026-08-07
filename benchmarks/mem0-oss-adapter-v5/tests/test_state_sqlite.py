from __future__ import annotations

import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mem0_oss_adapter_v5.state_sqlite import (
    OperationState,
    SqliteOperationState,
    StateError,
    StateTamperedError,
)

_KEY = b"k" * 32


def _sha(character: str) -> str:
    return character * 64


def _path(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root / "state.sqlite3"


def test_private_file_delete_journal_and_full_sync(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
    finally:
        connection.close()


def test_rejects_weak_key_relative_path_and_public_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        SqliteOperationState(Path("state.sqlite3"), hmac_key=_KEY)
    with pytest.raises(ValueError, match="32 bytes"):
        SqliteOperationState(_path(tmp_path), hmac_key=b"short")
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(StateError, match="group or others"):
        SqliteOperationState(public / "state.sqlite3", hmac_key=_KEY)


def test_exact_state_machine_and_reopen(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    admitted = state.admit(_sha("a"), _sha("b"))
    assert admitted.state is OperationState.ADMITTED
    assert state.reserve(_sha("a")).state is OperationState.RESERVED
    assert state.mark_dispatched(_sha("a")).state is OperationState.DISPATCHED
    assert state.mark_receipt_durable(_sha("a"), _sha("c")).state is OperationState.RECEIPT_DURABLE
    assert (
        state.mark_storage_verified(_sha("a"), _sha("d")).state is OperationState.STORAGE_VERIFIED
    )
    assert state.commit(_sha("a")).state is OperationState.COMMITTED
    cleaned = state.clean(_sha("a"), _sha("e"))
    assert cleaned.state is OperationState.CLEANED
    state.close()

    reopened = SqliteOperationState(path, hmac_key=_KEY)
    try:
        assert reopened.get(_sha("a")) == cleaned
        reopened.verify_inventory([_sha("a")])
    finally:
        reopened.close()


def test_crash_after_dispatch_is_quarantined_and_never_redispatched(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.reserve(_sha("a"))
    state.mark_dispatched(_sha("a"))
    state.close()

    reopened = SqliteOperationState(path, hmac_key=_KEY)
    try:
        report = reopened.recover()
        assert report.outcome_unknown == (_sha("a"),)
        assert report.retryable_reserved == ()
        assert reopened.recover().outcome_unknown == (_sha("a"),)
        with pytest.raises(StateError, match="late receipt"):
            reopened.mark_receipt_durable(_sha("a"), _sha("c"))
        with pytest.raises(StateError, match="requires RESERVED"):
            reopened.mark_dispatched(_sha("a"))
    finally:
        reopened.close()


def test_receipt_durable_and_storage_verified_resume_without_redispatch(tmp_path: Path) -> None:
    state = SqliteOperationState(_path(tmp_path), hmac_key=_KEY)
    for identity, request in ((_sha("a"), _sha("b")), (_sha("c"), _sha("d"))):
        state.admit(identity, request)
        state.reserve(identity)
        state.mark_dispatched(identity)
        state.mark_receipt_durable(identity, _sha("e"))
    state.mark_storage_verified(_sha("c"), _sha("f"))
    report = state.recover()
    assert report.resumable_receipt_durable == (_sha("a"),)
    assert report.resumable_storage_verified == (_sha("c"),)
    assert report.outcome_unknown == ()
    state.close()


@pytest.mark.parametrize(
    ("origin", "expected_receipt", "expected_storage", "expected_unknown"),
    [
        (OperationState.ADMITTED, None, None, False),
        (OperationState.RESERVED, None, None, False),
        (OperationState.DISPATCHED, None, None, True),
        (OperationState.RECEIPT_DURABLE, _sha("c"), None, False),
        (OperationState.STORAGE_VERIFIED, _sha("c"), _sha("d"), False),
    ],
)
def test_abort_cleaned_preserves_authenticated_origin_and_durable_evidence(
    tmp_path: Path,
    origin: OperationState,
    expected_receipt: str | None,
    expected_storage: str | None,
    expected_unknown: bool,
) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    if origin is not OperationState.ADMITTED:
        state.reserve(_sha("a"))
    if origin in {
        OperationState.DISPATCHED,
        OperationState.RECEIPT_DURABLE,
        OperationState.STORAGE_VERIFIED,
    }:
        state.mark_dispatched(_sha("a"))
    if origin is OperationState.DISPATCHED:
        state.recover()
    if origin in {OperationState.RECEIPT_DURABLE, OperationState.STORAGE_VERIFIED}:
        state.mark_receipt_durable(_sha("a"), _sha("c"))
    if origin is OperationState.STORAGE_VERIFIED:
        state.mark_storage_verified(_sha("a"), _sha("d"))
    aborted = state.abort_cleaned(
        _sha("a"),
        cleanup_result_sha256=_sha("e"),
        tombstone_commitment_sha256=_sha("f"),
    )
    assert aborted.state is OperationState.ABORT_CLEANED
    assert aborted.abort_origin_state is origin
    assert aborted.abort_result_sha256 == _sha("e")
    assert aborted.runtime_receipt_sha256 == expected_receipt
    assert aborted.storage_commitment_sha256 == expected_storage
    assert aborted.outcome_unknown is expected_unknown
    state.close()
    reopened = SqliteOperationState(path, hmac_key=_KEY)
    try:
        assert reopened.get(_sha("a")) == aborted
        assert reopened.recover().outcome_unknown == ()
        assert (
            reopened.abort_cleaned(
                _sha("a"),
                cleanup_result_sha256=_sha("e"),
                tombstone_commitment_sha256=_sha("f"),
            )
            == aborted
        )
    finally:
        reopened.close()


def test_abort_cleaned_rejects_known_dispatch_and_committed_terminals(tmp_path: Path) -> None:
    state = SqliteOperationState(_path(tmp_path), hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.reserve(_sha("a"))
    state.mark_dispatched(_sha("a"))
    with pytest.raises(StateError, match="known dispatched"):
        state.abort_cleaned(
            _sha("a"),
            cleanup_result_sha256=_sha("e"),
            tombstone_commitment_sha256=_sha("f"),
        )
    state.mark_receipt_durable(_sha("a"), _sha("c"))
    state.mark_storage_verified(_sha("a"), _sha("d"))
    state.commit(_sha("a"))
    with pytest.raises(StateError, match="cannot enter"):
        state.abort_cleaned(
            _sha("a"),
            cleanup_result_sha256=_sha("e"),
            tombstone_commitment_sha256=_sha("f"),
        )
    state.clean(_sha("a"), _sha("f"))
    with pytest.raises(StateError, match="cannot enter"):
        state.abort_cleaned(
            _sha("a"),
            cleanup_result_sha256=_sha("e"),
            tombstone_commitment_sha256=_sha("f"),
        )
    state.close()


def test_concurrent_abort_is_idempotent_and_evidence_is_write_once(tmp_path: Path) -> None:
    state = SqliteOperationState(_path(tmp_path), hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.reserve(_sha("a"))

    def abort(_: int):
        return state.abort_cleaned(
            _sha("a"),
            cleanup_result_sha256=_sha("e"),
            tombstone_commitment_sha256=_sha("f"),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = tuple(executor.map(abort, range(16)))
    assert all(record == records[0] for record in records)
    with pytest.raises(StateError, match="write-once"):
        state.abort_cleaned(
            _sha("a"),
            cleanup_result_sha256=_sha("1"),
            tombstone_commitment_sha256=_sha("f"),
        )
    state.close()


def test_abort_origin_or_result_tampering_fails_reopen(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.abort_cleaned(
        _sha("a"),
        cleanup_result_sha256=_sha("e"),
        tombstone_commitment_sha256=_sha("f"),
    )
    state.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE operations_v2 SET abort_result_sha256 = ? WHERE unit_identity_sha256 = ?",
            (_sha("1"), _sha("a")),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StateTamperedError, match="row HMAC"):
        SqliteOperationState(path, hmac_key=_KEY)


def test_concurrent_admission_is_idempotent_and_request_identity_is_write_once(
    tmp_path: Path,
) -> None:
    state = SqliteOperationState(_path(tmp_path), hmac_key=_KEY)
    with ThreadPoolExecutor(max_workers=8) as executor:
        records = tuple(executor.map(lambda _: state.admit(_sha("a"), _sha("b")), range(32)))
    assert all(record == records[0] for record in records)
    with pytest.raises(StateError, match="different request"):
        state.admit(_sha("a"), _sha("c"))
    state.close()


def test_row_tampering_and_wrong_key_fail_closed(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE operations_v2 SET request_sha256 = ? WHERE unit_identity_sha256 = ?",
            (_sha("c"), _sha("a")),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StateTamperedError, match="row HMAC"):
        SqliteOperationState(path, hmac_key=_KEY)
    with pytest.raises(StateTamperedError, match="schema authentication"):
        SqliteOperationState(path, hmac_key=b"z" * 32)


def test_schema_trigger_tampering_fails_closed(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TRIGGER hostile AFTER INSERT ON operations_v2 BEGIN SELECT 1; END"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(StateTamperedError, match="schema authentication"):
        SqliteOperationState(path, hmac_key=_KEY)


def test_deleted_row_is_detected_against_external_sealed_inventory(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.admit(_sha("c"), _sha("d"))
    state.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DELETE FROM operations_v2 WHERE unit_identity_sha256 = ?", (_sha("a"),))
        connection.commit()
    finally:
        connection.close()
    reopened = SqliteOperationState(path, hmac_key=_KEY)
    try:
        with pytest.raises(StateTamperedError, match="sealed input identities"):
            reopened.verify_inventory([_sha("a"), _sha("c")])
    finally:
        reopened.close()


def test_state_contains_hashes_only_and_no_forbidden_material(tmp_path: Path) -> None:
    path = _path(tmp_path)
    state = SqliteOperationState(path, hmac_key=_KEY)
    state.admit(_sha("a"), _sha("b"))
    state.reserve(_sha("a"))
    state.close()
    raw = path.read_bytes().lower()
    for forbidden in (b"prompt", b"output", b"bearer", b"@gmail.com", b"aixinfiniti"):
        assert forbidden not in raw


def test_existing_public_file_and_symlink_are_rejected(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.touch(mode=0o644)
    with pytest.raises(StateError, match="private regular file"):
        SqliteOperationState(path, hmac_key=_KEY)
    path.unlink()
    target = tmp_path / "target"
    target.touch()
    os.symlink(target, path)
    with pytest.raises(StateError, match="symlink"):
        SqliteOperationState(path, hmac_key=_KEY)


def test_dangling_state_symlink_is_rejected(tmp_path: Path) -> None:
    path = _path(tmp_path)
    os.symlink(tmp_path / "missing-target", path)
    with pytest.raises(StateError, match="symlink"):
        SqliteOperationState(path, hmac_key=_KEY)
