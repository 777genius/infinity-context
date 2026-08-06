"""Authenticated SQLite projection for normalized Infinity ingestion results."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from pathlib import Path

from infinity_context_server.memory_comparison_infinity_ingestion_contracts import (
    InfinityIngestionError,
    InfinityIngestionReceipt,
    infinity_ingestion_receipt_from_payload,
)
from infinity_context_server.resumable_operation_journal.domain import canonical_json
from infinity_context_server.resumable_operation_journal.ports import (
    OperationJournalSignerPort,
)

_SCHEMA_VERSION = "infinity-ingestion-results.v1"
_SQLITE_FAILURE = "Infinity result storage is unavailable"
_CREATE = """
CREATE TABLE IF NOT EXISTS infinity_ingestion_results (
    logical_operation_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    signer_key_id TEXT NOT NULL,
    signature TEXT NOT NULL
)
"""


class SQLiteInfinityIngestionResultStore:
    """Small durable result projection authenticated independently with HMAC."""

    def __init__(
        self,
        path: Path,
        *,
        signer: OperationJournalSignerPort,
        private_directory: Path,
    ) -> None:
        self._path = path
        self._signer = signer
        if path.parent != private_directory:
            raise InfinityIngestionError("Infinity result store must use its private directory")
        if not os.path.lexists(private_directory):
            private_directory.mkdir(mode=0o700, parents=True)
        self._assert_safe_directory()
        self._assert_safe_file(self._path)
        self._initialize()

    def load(self, logical_operation_id: str) -> InfinityIngestionReceipt | None:
        try:
            connection = self._connect()
            try:
                row = connection.execute(
                    """SELECT result_json, result_sha256, signer_key_id, signature
                       FROM infinity_ingestion_results WHERE logical_operation_id = ?""",
                    (logical_operation_id,),
                ).fetchone()
            finally:
                connection.close()
                self._secure_files()
        except sqlite3.Error:
            raise InfinityIngestionError(_SQLITE_FAILURE) from None
        if row is None:
            return None
        result_json, result_sha256, signer_key_id, signature = row
        expected_sha = hashlib.sha256(result_json.encode("ascii")).hexdigest()
        if (
            signer_key_id != self._signer.key_id
            or result_sha256 != expected_sha
            or not self._signer.verify(
                _signature_message(logical_operation_id, result_sha256), signature
            )
        ):
            raise InfinityIngestionError("stored Infinity result authentication failed")
        try:
            payload = json.loads(result_json)
        except (TypeError, ValueError) as exc:
            raise InfinityIngestionError("stored Infinity result JSON is invalid") from exc
        if canonical_json(payload) != result_json:
            raise InfinityIngestionError("stored Infinity result is not canonical")
        return infinity_ingestion_receipt_from_payload(payload)

    def save(self, logical_operation_id: str, receipt: InfinityIngestionReceipt) -> None:
        receipt.validate()
        result_json = canonical_json(receipt.payload())
        result_sha256 = hashlib.sha256(result_json.encode("ascii")).hexdigest()
        signature = self._signer.sign(_signature_message(logical_operation_id, result_sha256))
        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """SELECT result_json, result_sha256, signer_key_id, signature
                       FROM infinity_ingestion_results WHERE logical_operation_id = ?""",
                    (logical_operation_id,),
                ).fetchone()
                exact = (result_json, result_sha256, self._signer.key_id, signature)
                if existing is None:
                    connection.execute(
                        """INSERT INTO infinity_ingestion_results
                           (logical_operation_id, result_json, result_sha256,
                            signer_key_id, signature)
                           VALUES (?, ?, ?, ?, ?)""",
                        (logical_operation_id, *exact),
                    )
                elif existing != exact:
                    raise InfinityIngestionError("Infinity result replay is divergent")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
                self._secure_files()
        except sqlite3.Error:
            raise InfinityIngestionError(_SQLITE_FAILURE) from None

    def _initialize(self) -> None:
        try:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS infinity_ingestion_schema (version TEXT NOT NULL)"
                )
                versions = connection.execute(
                    "SELECT version FROM infinity_ingestion_schema"
                ).fetchall()
                if not versions:
                    connection.execute(
                        "INSERT INTO infinity_ingestion_schema (version) VALUES (?)",
                        (_SCHEMA_VERSION,),
                    )
                elif versions != [(_SCHEMA_VERSION,)]:
                    raise InfinityIngestionError("Infinity result store schema is divergent")
                connection.execute(_CREATE)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
                self._secure_files()
        except sqlite3.Error:
            raise InfinityIngestionError(_SQLITE_FAILURE) from None

    def _connect(self) -> sqlite3.Connection:
        self._assert_safe_directory()
        self._assert_safe_storage_files()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._path,
                timeout=10.0,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            self._secure_files()
            return connection
        except BaseException:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    raise InfinityIngestionError(_SQLITE_FAILURE) from None
            raise

    def _assert_safe_directory(self) -> None:
        info = os.lstat(self._path.parent)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise InfinityIngestionError("Infinity result private directory is unsafe")

    @staticmethod
    def _assert_safe_file(path: Path) -> None:
        if not os.path.lexists(path):
            return
        info = os.lstat(path)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise InfinityIngestionError("Infinity result private file is unsafe")

    def _assert_safe_storage_files(self) -> None:
        for path in self._storage_files():
            self._assert_safe_file(path)

    def _storage_files(self) -> tuple[Path, Path, Path]:
        return self._path, Path(f"{self._path}-wal"), Path(f"{self._path}-shm")

    def _secure_files(self) -> None:
        self._assert_safe_directory()
        for path in self._storage_files():
            if not os.path.lexists(path):
                continue
            info = os.lstat(path)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
            ):
                raise InfinityIngestionError("Infinity result private file is unsafe")
            if stat.S_IMODE(info.st_mode) != 0o600:
                os.chmod(path, 0o600)


def _signature_message(logical_operation_id: str, result_sha256: str) -> bytes:
    return canonical_json(
        {
            "logical_operation_id": logical_operation_id,
            "result_sha256": result_sha256,
            "schema_version": _SCHEMA_VERSION,
        }
    ).encode("ascii")


__all__ = ["SQLiteInfinityIngestionResultStore"]
