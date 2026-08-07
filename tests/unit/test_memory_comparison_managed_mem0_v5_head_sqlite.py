from __future__ import annotations

import multiprocessing
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from infinity_context_server.memory_comparison_managed_mem0_v5_head_sqlite import (
    SQLiteManagedMem0V5CheckpointHead,
)
from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError

_KEY = b"checkpoint-head-key-material-0001"


def _sha(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _path(tmp_path: Path) -> Path:
    return tmp_path / "private" / "checkpoint-head.sqlite3"


def _store(tmp_path: Path, *, key: bytes = _KEY) -> SQLiteManagedMem0V5CheckpointHead:
    return SQLiteManagedMem0V5CheckpointHead(_path(tmp_path), hmac_key=key)


def _cas(
    store: SQLiteManagedMem0V5CheckpointHead,
    *,
    expected: str | None,
    next_head: str,
) -> None:
    store.compare_and_swap_head(
        authority_commitment_sha256=_sha("authority"),
        admission_commitment_sha256=_sha("admission"),
        expected_commitment_sha256=expected,
        next_commitment_sha256=next_head,
    )


def _load(store: SQLiteManagedMem0V5CheckpointHead) -> str | None:
    return store.load_head(
        authority_commitment_sha256=_sha("authority"),
        admission_commitment_sha256=_sha("admission"),
    )


def test_restart_permissions_and_exact_idempotent_replay(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _sha("head-0")
    second = _sha("head-1")
    assert _load(store) is None
    _cas(store, expected=None, next_head=first)
    _cas(store, expected=None, next_head=first)
    _cas(store, expected=first, next_head=second)
    _cas(store, expected=first, next_head=second)
    _cas(store, expected=second, next_head=second)

    restarted = _store(tmp_path)
    assert _load(restarted) == second
    assert stat.S_IMODE(os.lstat(_path(tmp_path).parent).st_mode) == 0o700
    assert stat.S_IMODE(os.lstat(_path(tmp_path)).st_mode) == 0o600
    with sqlite3.connect(_path(tmp_path)) as connection:
        assert connection.execute(
            "SELECT generation, previous_commitment_sha256, head_commitment_sha256 "
            "FROM checkpoint_heads"
        ).fetchone() == (1, first, second)


def test_two_instances_reject_stale_compare_and_swap(tmp_path: Path) -> None:
    first = _store(tmp_path)
    second = _store(tmp_path)
    head_0, head_1, divergent = _sha("head-0"), _sha("head-1"), _sha("divergent")
    _cas(first, expected=None, next_head=head_0)
    _cas(first, expected=head_0, next_head=head_1)
    with pytest.raises(ManagedRunError, match="head conflict"):
        _cas(second, expected=head_0, next_head=divergent)
    assert _load(second) == head_1


def test_concurrent_threads_have_one_cas_winner(tmp_path: Path) -> None:
    initial = _sha("initial")
    _cas(_store(tmp_path), expected=None, next_head=initial)

    def attempt(index: int) -> bool:
        try:
            _cas(_store(tmp_path), expected=initial, next_head=_sha(f"winner-{index}"))
        except ManagedRunError as exc:
            assert "head conflict" in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        winners = tuple(executor.map(attempt, range(8)))
    assert winners.count(True) == 1


def _process_cas(
    path: str,
    key: bytes,
    expected: str,
    next_head: str,
    start: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    store = SQLiteManagedMem0V5CheckpointHead(Path(path), hmac_key=key)
    start.wait(timeout=10)
    try:
        _cas(store, expected=expected, next_head=next_head)
    except ManagedRunError:
        results.put("conflict")
    else:
        results.put("winner")


def test_concurrent_processes_have_one_cas_winner(tmp_path: Path) -> None:
    initial = _sha("initial")
    _cas(_store(tmp_path), expected=None, next_head=initial)
    context = multiprocessing.get_context("fork")
    start = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_process_cas,
            args=(
                str(_path(tmp_path)),
                _KEY,
                initial,
                _sha(f"process-{index}"),
                start,
                results,
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in processes) == ["conflict", "winner"]


def test_wrong_key_and_errors_do_not_leak_key(tmp_path: Path) -> None:
    store = _store(tmp_path)
    secret_text = _KEY.decode()
    assert secret_text not in repr(store)
    with pytest.raises(ManagedRunError) as failure:
        _store(tmp_path, key=b"wrong-checkpoint-head-key-000000")
    assert secret_text not in str(failure.value)
    assert "wrong-checkpoint" not in str(failure.value)


def test_row_tampering_and_partial_rollback_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first, second = _sha("head-0"), _sha("head-1")
    _cas(store, expected=None, next_head=first)
    _cas(store, expected=first, next_head=second)
    with sqlite3.connect(_path(tmp_path)) as connection:
        connection.execute(
            """UPDATE checkpoint_heads SET generation = 0,
               previous_commitment_sha256 = NULL, head_commitment_sha256 = ?""",
            (first,),
        )
    with pytest.raises(ManagedRunError, match="authentication failed"):
        _load(store)


def test_meta_tampering_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(_path(tmp_path)) as connection:
        connection.execute(
            "UPDATE checkpoint_head_meta SET structural_fingerprint_sha256 = ?",
            (_sha("tampered"),),
        )
    with pytest.raises(ManagedRunError, match="authentication failed"):
        _load(store)


def test_schema_tampering_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(_path(tmp_path)) as connection:
        connection.execute(
            "CREATE TRIGGER hostile AFTER INSERT ON checkpoint_heads BEGIN SELECT 1; END"
        )
    with pytest.raises(ManagedRunError, match="authentication failed"):
        _load(store)


@pytest.mark.parametrize("suffix", ("", "-journal", "-lock", "-wal", "-shm"))
def test_symlink_storage_surfaces_are_rejected(tmp_path: Path, suffix: str) -> None:
    path = _path(tmp_path)
    path.parent.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_bytes(b"not a database")
    Path(f"{path}{suffix}").symlink_to(target)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)


@pytest.mark.parametrize("suffix", ("", "-journal", "-lock"))
def test_nonregular_storage_surfaces_are_rejected(tmp_path: Path, suffix: str) -> None:
    path = _path(tmp_path)
    path.parent.mkdir(mode=0o700)
    Path(f"{path}{suffix}").mkdir(mode=0o700)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)


def test_unsafe_permissions_are_rejected(tmp_path: Path) -> None:
    _store(tmp_path)
    os.chmod(_path(tmp_path), 0o640)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        _store(tmp_path)
    os.chmod(_path(tmp_path), 0o600)
    os.chmod(_path(tmp_path).parent, 0o750)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        _store(tmp_path)


def test_unsafe_lock_surface_permissions_are_rejected(tmp_path: Path) -> None:
    path = _path(tmp_path)
    _store(tmp_path)
    lock = Path(f"{path}-lock")
    lock.write_bytes(b"lock")
    os.chmod(lock, 0o640)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)


def test_truncated_database_fails_closed(tmp_path: Path) -> None:
    _store(tmp_path)
    _path(tmp_path).write_bytes(b"truncated")
    os.chmod(_path(tmp_path), 0o600)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        _store(tmp_path)


def test_existing_zero_byte_database_is_not_healed(tmp_path: Path) -> None:
    path = _path(tmp_path)
    path.parent.mkdir(mode=0o700)
    path.touch(mode=0o600)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)
    assert path.stat().st_size == 0


@pytest.mark.parametrize("table", ("checkpoint_head_meta", "checkpoint_heads"))
def test_dropped_authenticated_table_is_not_healed(tmp_path: Path, table: str) -> None:
    path = _path(tmp_path)
    _store(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(f"DROP TABLE {table}")
    with pytest.raises(ManagedRunError):
        SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)
    with sqlite3.connect(path) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    assert table not in names


def test_valid_complete_old_database_replay_is_documented_not_detected(tmp_path: Path) -> None:
    path = _path(tmp_path)
    store = _store(tmp_path)
    old_head, current_head = _sha("old-head"), _sha("current-head")
    _cas(store, expected=None, next_head=old_head)
    valid_old_database = path.read_bytes()
    _cas(store, expected=old_head, next_head=current_head)
    assert _load(store) == current_head

    path.write_bytes(valid_old_database)
    os.chmod(path, 0o600)
    replayed = SQLiteManagedMem0V5CheckpointHead(path, hmac_key=_KEY)
    assert _load(replayed) == old_head


def test_pathname_inode_swap_is_detected_after_bound_fd_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _path(tmp_path)
    store = _store(tmp_path)
    _cas(store, expected=None, next_head=_sha("head"))
    original_verify = SQLiteManagedMem0V5CheckpointHead._verify_schema
    swapped = False

    def verify_after_swap(self, connection):
        nonlocal swapped
        if not swapped:
            swapped = True
            replacement = path.read_bytes()
            path.rename(path.with_suffix(".replaced"))
            path.write_bytes(replacement)
            os.chmod(path, 0o600)
        return original_verify(self, connection)

    monkeypatch.setattr(SQLiteManagedMem0V5CheckpointHead, "_verify_schema", verify_after_swap)
    with pytest.raises(ManagedRunError, match="storage is unavailable"):
        _load(store)


def test_exact_lowercase_sha256_inputs_are_required(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ManagedRunError, match="input is invalid"):
        store.load_head(
            authority_commitment_sha256=_sha("authority").upper(),
            admission_commitment_sha256=_sha("admission"),
        )
    with pytest.raises(ManagedRunError, match="input is invalid"):
        _cas(store, expected=None, next_head="0" * 63)


def test_key_must_be_separate_bytes_with_at_least_32_bytes(tmp_path: Path) -> None:
    for value in (b"short", bytearray(b"x" * 32), "x" * 32):
        with pytest.raises(ManagedRunError, match="input is invalid"):
            SQLiteManagedMem0V5CheckpointHead(_path(tmp_path), hmac_key=value)  # type: ignore[arg-type]
