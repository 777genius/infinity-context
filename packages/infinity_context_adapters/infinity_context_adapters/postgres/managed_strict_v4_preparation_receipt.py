"""Secure SQLite persistence for the strict-v4 full-preparation receipt."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from infinity_context_core.features.projection_receipts import ProjectionReceiptError
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3StoreReceipt,
    canonical_bytes,
)
from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    ManagedMem0V6ManifestContext,
    ManagedMem0V6PagedManifestAuthority,
    ManagedMem0V6PageStoreCommitReceipt,
)

from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
    close_strict_sqlite,
    create_strict_sqlite,
    open_strict_sqlite,
    unlink_strict_sqlite_binding,
    verify_strict_sqlite_binding,
)


class SQLiteStrictV4PreparationReceiptStore:
    """One immutable receipt per private file; divergent rewrites fail closed."""

    def __init__(self, path: Path, db: sqlite3.Connection, fd: int) -> None:
        self._path, self._db, self._fd = path, db, fd
        self._closed = False

    @classmethod
    def create(cls, path: str | os.PathLike[str]) -> SQLiteStrictV4PreparationReceiptStore:
        target = Path(path)
        db, fd = create_strict_sqlite(target)
        try:
            _initialize_schema(db)
            return cls(target, db, fd)
        except BaseException:
            try:
                with suppress(StrictV4SQLiteFileError, FileNotFoundError):
                    unlink_strict_sqlite_binding(target, fd)
            finally:
                close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open(cls, path: str | os.PathLike[str]) -> SQLiteStrictV4PreparationReceiptStore:
        target = Path(path)
        db, fd = open_strict_sqlite(target, readonly=False)
        try:
            _validate_schema(db)
            return cls(target, db, fd)
        except BaseException:
            close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open_or_create(cls, path: str | os.PathLike[str]) -> SQLiteStrictV4PreparationReceiptStore:
        """Initialize only a secure zero-table crash partial; preserve valid journals."""

        target = Path(path)
        if not target.exists():
            try:
                return cls.create(target)
            except Exception:
                if not target.exists():
                    raise
        db, fd = open_strict_sqlite(target, readonly=False)
        try:
            _initialize_schema(db)
            return cls(target, db, fd)
        except BaseException:
            close_strict_sqlite(db, fd)
            raise

    def write(self, receipt: StrictV4PreparationReceipt) -> None:
        self._ensure_open()
        verify_strict_sqlite_binding(self._path, self._fd)
        payload = canonical_bytes(receipt.payload()).decode("ascii")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            existing = self._db.execute(
                "SELECT payload_json FROM receipt WHERE singleton=1"
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != payload:
                    raise ProjectionReceiptError("projection_receipt.preparation_conflict")
                verify_strict_sqlite_binding(self._path, self._fd)
                self._db.commit()
                verify_strict_sqlite_binding(self._path, self._fd)
                return
            self._db.execute("INSERT INTO receipt VALUES(1,?)", (payload,))
            durable = self._db.execute(
                "SELECT payload_json FROM receipt WHERE singleton=1"
            ).fetchone()
            if durable is None or str(durable[0]) != payload:
                raise ProjectionReceiptError("projection_receipt.preparation_write_invalid")
            verify_strict_sqlite_binding(self._path, self._fd)
            self._db.commit()
            verify_strict_sqlite_binding(self._path, self._fd)
        except BaseException:
            self._db.rollback()
            raise

    def read(self) -> StrictV4PreparationReceipt:
        self._ensure_open()
        verify_strict_sqlite_binding(self._path, self._fd)
        row = self._db.execute("SELECT payload_json FROM receipt WHERE singleton=1").fetchone()
        verify_strict_sqlite_binding(self._path, self._fd)
        if row is None:
            raise ProjectionReceiptError("projection_receipt.preparation_missing")
        try:
            source = str(row[0])
            value = _strict_payload_json(source)
            if canonical_bytes(value).decode("ascii") != source:
                raise ProjectionReceiptError("projection_receipt.preparation_invalid")
            value["registered_at"] = datetime.fromisoformat(value["registered_at"])
            value["prepared_at"] = datetime.fromisoformat(value["prepared_at"])
            value["a1_context"] = ManagedMem0V6ManifestContext(**value["a1_context"])
            value["a1_authority"]["ordered_page_commitment_sha256"] = tuple(
                value["a1_authority"]["ordered_page_commitment_sha256"]
            )
            value["a1_authority"] = ManagedMem0V6PagedManifestAuthority(**value["a1_authority"])
            value["a1_store_receipt"] = ManagedMem0V6PageStoreCommitReceipt(
                **value["a1_store_receipt"]
            )
            value["a2_context"] = ManagedCleanupV3Context(**value["a2_context"])
            value["a2_authority"]["ordered_page_sha256"] = tuple(
                value["a2_authority"]["ordered_page_sha256"]
            )
            value["a2_authority"] = ManagedCleanupV3Authority(**value["a2_authority"])
            value["a2_store_receipt"] = ManagedCleanupV3StoreReceipt(**value["a2_store_receipt"])
            receipt = StrictV4PreparationReceipt(**value)
            verify_strict_sqlite_binding(self._path, self._fd)
            return receipt
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ProjectionReceiptError("projection_receipt.preparation_invalid") from exc

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            close_strict_sqlite(self._db, self._fd)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProjectionReceiptError("projection_receipt.preparation_store_closed")


def _initialize_schema(db: sqlite3.Connection) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        objects = _schema_objects(db)
        if not objects:
            db.execute(_SCHEMA_SQL)
        _validate_schema(db)
        db.commit()
    except BaseException:
        db.rollback()
        raise


_SCHEMA_SQL = (
    "CREATE TABLE receipt(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "payload_json TEXT NOT NULL) STRICT"
)


def _schema_objects(db: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    )


def _validate_schema(db: sqlite3.Connection) -> None:
    if _schema_objects(db) != (("table", "receipt", "receipt", _SCHEMA_SQL),):
        raise ProjectionReceiptError("projection_receipt.preparation_store_schema_invalid")
    columns = tuple(
        (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
        for row in db.execute("PRAGMA table_info(receipt)")
    )
    if columns != (
        ("singleton", "INTEGER", 0, 1),
        ("payload_json", "TEXT", 1, 0),
    ):
        raise ProjectionReceiptError("projection_receipt.preparation_store_schema_invalid")


def _strict_payload_json(source: str) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate receipt key")
            result[key] = value
        return result

    def reject_constant(token: str) -> object:
        raise ValueError(f"invalid receipt constant {token}")

    value = json.loads(
        source,
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )
    if type(value) is not dict:
        raise ValueError("receipt payload must be an object")
    return value


__all__ = ("SQLiteStrictV4PreparationReceiptStore",)
