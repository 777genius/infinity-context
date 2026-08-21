from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import (
    managed_strict_v4_preparation_receipt as subject,
)
from infinity_context_adapters.postgres import managed_strict_v4_sqlite_files as sqlite_files
from infinity_context_adapters.postgres.managed_strict_v4_preparation_receipt import (
    SQLiteStrictV4PreparationReceiptStore,
)
from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptError


class _Receipt:
    def payload(self) -> dict[str, object]:
        return {"schema_version": "strict-v4-test", "receipt_sha256": "1" * 64}


def test_open_or_create_recovers_secure_zero_table_bootstrap(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"
    path.touch(mode=0o600)
    store = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    store.write(_Receipt())  # type: ignore[arg-type]
    store.close()
    reopened = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    reopened.write(_Receipt())  # type: ignore[arg-type]
    reopened.close()


def test_open_or_create_rejects_foreign_partial_schema(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE foreign_state(value TEXT) STRICT")
    db.close()
    path.chmod(0o600)
    with pytest.raises(ProjectionReceiptError, match="schema_invalid"):
        SQLiteStrictV4PreparationReceiptStore.open_or_create(path)


def test_open_or_create_rejects_trigger_that_could_drop_receipt_write(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"
    store = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    store.close()
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TRIGGER suppress_receipt BEFORE INSERT ON receipt BEGIN SELECT RAISE(IGNORE); END"
    )
    db.commit()
    db.close()
    with pytest.raises(ProjectionReceiptError, match="schema_invalid"):
        SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    with pytest.raises(ProjectionReceiptError, match="schema_invalid"):
        SQLiteStrictV4PreparationReceiptStore.open(path)


def test_identical_concurrent_writes_are_exact_idempotent(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"

    def write() -> None:
        store = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
        try:
            store.write(_Receipt())  # type: ignore[arg-type]
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(write) for _ in range(2)]
        for future in futures:
            future.result()


def test_read_and_write_reject_rename_replacement_after_open(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"
    old_path = tmp_path / "old-receipt.sqlite3"
    store = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    store.write(_Receipt())  # type: ignore[arg-type]
    path.rename(old_path)
    replacement = SQLiteStrictV4PreparationReceiptStore.open_or_create(path)
    replacement.close()
    try:
        with pytest.raises(StrictV4SQLiteFileError, match="replaced"):
            store.read()
        with pytest.raises(StrictV4SQLiteFileError, match="replaced"):
            store.write(_Receipt())  # type: ignore[arg-type]
    finally:
        store.close()


def test_create_failure_never_unlinks_a_racing_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.chmod(0o700)
    path = tmp_path / "receipt.sqlite3"
    old_path = tmp_path / "old-receipt.sqlite3"
    replacement = b"replacement-must-survive"

    def fail(db: sqlite3.Connection) -> None:
        del db
        path.rename(old_path)
        path.write_bytes(replacement)
        path.chmod(0o600)
        raise RuntimeError("injected schema failure")

    monkeypatch.setattr(subject, "_initialize_schema", fail)
    with pytest.raises(RuntimeError, match="injected"):
        SQLiteStrictV4PreparationReceiptStore.create(path)
    assert path.read_bytes() == replacement


@pytest.mark.parametrize(
    "source",
    [
        '{"a":1,"a":2}',
        '{"a":NaN}',
        '{"a":Infinity}',
        "[]",
    ],
)
def test_receipt_json_rejects_ambiguous_or_non_finite_material(source: str) -> None:
    with pytest.raises(ValueError):
        subject._strict_payload_json(source)


def test_shared_connect_failure_unlinks_and_direct_receipt_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "receipt-connect-retry.sqlite"
    original = sqlite_files._connect
    failed = False

    def fail_once(fd: int, *, readonly: bool):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected receipt connect failure")
        return original(fd, readonly=readonly)

    monkeypatch.setattr(sqlite_files, "_connect", fail_once)
    with pytest.raises(RuntimeError, match="injected receipt connect failure"):
        SQLiteStrictV4PreparationReceiptStore.create(path)
    assert not path.exists()
    store = SQLiteStrictV4PreparationReceiptStore.create(path)
    store.close()
