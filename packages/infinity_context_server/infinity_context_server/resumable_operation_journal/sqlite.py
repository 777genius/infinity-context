"""Strict schema-v4 SQLite adapter for the resumable operation journal."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import final

from infinity_context_server.resumable_operation_journal.domain import (
    OPERATION_JOURNAL_SCHEMA_VERSION,
    LogicalOperationIdentity,
    OperationEvent,
    OperationJournalError,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    OperationRunIdentity,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    RetryDisposition,
    VerifiedOperationReceipt,
    canonical_json,
    operation_states_commitment,
    sha256_commitment,
    verified_receipts_commitment,
)

_TABLES = frozenset(
    {
        "schema_meta",
        "operation_runs",
        "operation_manifest",
        "operation_states",
        "operation_receipts",
        "operation_events",
        "notification_outbox",
    }
)

_SCHEMA = (
    """CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """
    CREATE TABLE operation_runs (
        run_id TEXT PRIMARY KEY,
        operation_namespace TEXT NOT NULL,
        manifest_commitment_sha256 TEXT NOT NULL,
        policy_commitment_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        expected_operation_count INTEGER NOT NULL,
        journal_schema_version TEXT NOT NULL,
        phase TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        head_event_sha256 TEXT
    )
    """,
    """
    CREATE TABLE operation_manifest (
        run_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        logical_operation_id TEXT NOT NULL,
        replay_key TEXT NOT NULL,
        operation_key TEXT NOT NULL,
        operation_kind TEXT NOT NULL,
        authority_commitment_sha256 TEXT NOT NULL,
        retry_disposition TEXT NOT NULL,
        PRIMARY KEY (run_id, ordinal),
        UNIQUE (run_id, logical_operation_id),
        UNIQUE (run_id, replay_key),
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE operation_states (
        run_id TEXT NOT NULL,
        logical_operation_id TEXT NOT NULL,
        phase TEXT NOT NULL,
        request_commitment_sha256 TEXT,
        receipt_id TEXT,
        result_commitment_sha256 TEXT,
        verifier_key_id TEXT,
        verification_commitment_sha256 TEXT,
        PRIMARY KEY (run_id, logical_operation_id),
        UNIQUE (run_id, receipt_id),
        FOREIGN KEY (run_id, logical_operation_id)
            REFERENCES operation_manifest(run_id, logical_operation_id)
    )
    """,
    """
    CREATE TABLE operation_receipts (
        run_id TEXT NOT NULL,
        logical_operation_id TEXT NOT NULL,
        receipt_identity_json TEXT NOT NULL,
        receipt_commitment_sha256 TEXT NOT NULL,
        verifier_key_id TEXT NOT NULL,
        verification_commitment_sha256 TEXT NOT NULL,
        PRIMARY KEY (run_id, logical_operation_id),
        FOREIGN KEY (run_id, logical_operation_id)
            REFERENCES operation_states(run_id, logical_operation_id)
    )
    """,
    """
    CREATE TABLE operation_events (
        run_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        logical_operation_id TEXT,
        payload_json TEXT NOT NULL,
        predecessor_event_sha256 TEXT,
        event_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        signature TEXT NOT NULL,
        PRIMARY KEY (run_id, sequence),
        UNIQUE (run_id, event_sha256),
        FOREIGN KEY (run_id) REFERENCES operation_runs(run_id)
    )
    """,
    """
    CREATE TABLE notification_outbox (
        run_id TEXT NOT NULL,
        event_sha256 TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, event_sha256),
        FOREIGN KEY (run_id, event_sha256)
            REFERENCES operation_events(run_id, event_sha256)
    )
    """,
    """CREATE INDEX idx_operation_states_phase
       ON operation_states(run_id, phase, logical_operation_id)""",
    """CREATE INDEX idx_operation_outbox_pending
       ON notification_outbox(run_id, delivered, event_sha256)""",
)


def _schema_fingerprint(connection: sqlite3.Connection) -> tuple[object, ...]:
    objects = tuple(
        tuple(row)
        for row in connection.execute(
            """SELECT type, name, tbl_name, sql FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        )
    )
    columns = tuple(
        (
            table,
            tuple(tuple(row) for row in connection.execute(f'PRAGMA table_xinfo("{table}")')),
        )
        for table in sorted(_TABLES)
    )
    return objects, columns


@cache
def _expected_fingerprint() -> tuple[object, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


@final
class SQLiteOperationJournalTransaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_run(self, run_id: str) -> OperationRunState | None:
        row = self._connection.execute(
            "SELECT * FROM operation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _run_from_row(row) if row is not None else None

    def put_run(self, state: OperationRunState) -> None:
        identity = state.identity
        self._connection.execute(
            """
            INSERT INTO operation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                phase=excluded.phase,
                event_count=excluded.event_count,
                head_event_sha256=excluded.head_event_sha256
            """,
            (
                identity.run_id,
                identity.operation_namespace,
                identity.manifest_commitment_sha256,
                identity.policy_commitment_sha256,
                identity.signer_key_id,
                identity.expected_operation_count,
                identity.journal_schema_version,
                state.phase.value,
                state.event_count,
                state.head_event_sha256,
            ),
        )

    def put_manifest(self, manifest: OperationManifest) -> None:
        self._connection.executemany(
            """
            INSERT INTO operation_manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    operation.run_id,
                    operation.ordinal,
                    operation.logical_operation_id,
                    operation.replay_key,
                    operation.operation_key,
                    operation.operation_kind,
                    operation.authority_commitment_sha256,
                    operation.retry_disposition.value,
                )
                for operation in manifest.operations
            ),
        )

    def get_manifest_operation(
        self, *, run_id: str, ordinal: int
    ) -> LogicalOperationIdentity | None:
        row = self._connection.execute(
            "SELECT * FROM operation_manifest WHERE run_id = ? AND ordinal = ?",
            (run_id, ordinal),
        ).fetchone()
        return _identity_from_row(row) if row is not None else None

    def iter_manifest(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[LogicalOperationIdentity]:
        cursor = self._connection.execute(
            "SELECT * FROM operation_manifest WHERE run_id = ? ORDER BY ordinal", (run_id,)
        )
        yield from _batched(cursor, _identity_from_row, batch_size)

    def get_operation(self, *, run_id: str, logical_operation_id: str) -> OperationState | None:
        row = self._connection.execute(
            """
            SELECT m.*, s.phase, s.request_commitment_sha256, s.receipt_id,
                   s.result_commitment_sha256, s.verifier_key_id,
                   s.verification_commitment_sha256
            FROM operation_states s
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE s.run_id = ? AND s.logical_operation_id = ?
            """,
            (run_id, logical_operation_id),
        ).fetchone()
        return _state_from_row(row) if row is not None else None

    def put_operation(self, state: OperationState) -> None:
        receipt = state.receipt
        self._connection.execute(
            """
            INSERT INTO operation_states VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, logical_operation_id) DO UPDATE SET
                phase=excluded.phase,
                request_commitment_sha256=excluded.request_commitment_sha256,
                receipt_id=excluded.receipt_id,
                result_commitment_sha256=excluded.result_commitment_sha256,
                verifier_key_id=excluded.verifier_key_id,
                verification_commitment_sha256=excluded.verification_commitment_sha256
            """,
            (
                state.identity.run_id,
                state.identity.logical_operation_id,
                state.phase.value,
                state.request_commitment_sha256,
                receipt.receipt_id if receipt else None,
                receipt.result_commitment_sha256 if receipt else None,
                state.verifier_key_id,
                state.verification_commitment_sha256,
            ),
        )

    def put_receipt(self, *, state: OperationState, verified: VerifiedOperationReceipt) -> None:
        self._connection.execute(
            "INSERT INTO operation_receipts VALUES (?, ?, ?, ?, ?, ?)",
            (
                state.identity.run_id,
                state.identity.logical_operation_id,
                canonical_json(verified.receipt.identity_payload()),
                sha256_commitment(verified.receipt.identity_payload()),
                verified.verifier_key_id,
                verified.verification_commitment_sha256,
            ),
        )

    def append_event(self, event: OperationEvent) -> None:
        self._connection.execute(
            "INSERT INTO operation_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.run_id,
                event.sequence,
                event.event_type,
                event.logical_operation_id,
                event.payload_json,
                event.predecessor_event_sha256,
                event.event_sha256,
                event.signer_key_id,
                event.signature,
            ),
        )

    def enqueue_notification(self, event: OperationEvent) -> None:
        self._connection.execute(
            "INSERT INTO notification_outbox(run_id, event_sha256) VALUES (?, ?)",
            (event.run_id, event.event_sha256),
        )

    def mark_notification_delivered(self, *, run_id: str, event_sha256: str) -> None:
        cursor = self._connection.execute(
            """UPDATE notification_outbox SET delivered = 1
               WHERE run_id = ? AND event_sha256 = ?""",
            (run_id, event_sha256),
        )
        if cursor.rowcount != 1:
            raise OperationJournalError("operation_journal_notification_missing")

    def iter_operations(self, *, run_id: str, batch_size: int = 256) -> Iterator[OperationState]:
        cursor = self._connection.execute(
            """
            SELECT m.*, s.phase, s.request_commitment_sha256, s.receipt_id,
                   s.result_commitment_sha256, s.verifier_key_id,
                   s.verification_commitment_sha256
            FROM operation_states s
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE s.run_id = ? ORDER BY m.ordinal
            """,
            (run_id,),
        )
        yield from _batched(cursor, _state_from_row, batch_size)

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[OperationEvent]:
        cursor = self._connection.execute(
            "SELECT * FROM operation_events WHERE run_id = ? ORDER BY sequence", (run_id,)
        )
        yield from _batched(cursor, _event_from_row, batch_size)

    def iter_verified_receipts(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[VerifiedOperationReceipt]:
        cursor = self._connection.execute(
            """
            SELECT m.*, r.receipt_identity_json, r.receipt_commitment_sha256,
                   r.verifier_key_id, r.verification_commitment_sha256
            FROM operation_receipts r
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE r.run_id = ? ORDER BY m.ordinal
            """,
            (run_id,),
        )
        yield from _batched(cursor, _verified_receipt_from_row, batch_size)

    def phase_counts(self, *, run_id: str) -> dict[str, int]:
        return {
            str(row[0]): int(row[1])
            for row in self._connection.execute(
                "SELECT phase, COUNT(*) FROM operation_states WHERE run_id = ? GROUP BY phase",
                (run_id,),
            )
        }

    def state_commitment(self, *, run_id: str) -> str:
        return operation_states_commitment(self.iter_operations(run_id=run_id))

    def receipt_count(self, *, run_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM operation_receipts WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row[0])

    def receipts_commitment(self, *, run_id: str) -> str:
        return verified_receipts_commitment(self.iter_verified_receipts(run_id=run_id))


@final
class SQLiteOperationJournal:
    """Local-only adapter which never migrates or accepts a v3 database."""

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if database_path.parent != private_directory:
            raise ValueError("database_path must be directly inside private_directory")
        if not 1 <= busy_timeout_ms <= 120_000 or isinstance(busy_timeout_ms, bool):
            raise ValueError("busy_timeout_ms must be from 1 to 120000")
        self.database_path = database_path
        self.private_directory = private_directory
        self._busy_timeout_ms = busy_timeout_ms
        self._prepare_directory()
        self._assert_safe_file(database_path)
        self._initialize_schema()

    @property
    def schema_version(self) -> str:
        return OPERATION_JOURNAL_SCHEMA_VERSION

    @contextmanager
    def write_transaction(self) -> Iterator[SQLiteOperationJournalTransaction]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield SQLiteOperationJournalTransaction(connection)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._secure_files()
            connection.close()

    def iter_pending_notifications(
        self, *, run_id: str, batch_size: int = 64
    ) -> Iterator[OperationEvent]:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                SELECT e.* FROM notification_outbox o
                JOIN operation_events e USING (run_id, event_sha256)
                WHERE o.run_id = ? AND o.delivered = 0 ORDER BY e.sequence
                """,
                (run_id,),
            )
            if not 1 <= batch_size <= 4096 or isinstance(batch_size, bool):
                raise ValueError("batch_size must be from 1 to 4096")
            events = tuple(_event_from_row(row) for row in cursor.fetchmany(batch_size))
            cursor.close()
        finally:
            self._secure_files()
            connection.close()
        return iter(events)

    def _initialize_schema(self) -> None:
        connection = self._open_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            } - {"sqlite_sequence"}
            if not tables:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_meta VALUES (?, ?)",
                    ("schema_version", OPERATION_JOURNAL_SCHEMA_VERSION),
                )
            else:
                self._validate_schema(connection, tables)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._secure_files()
            connection.close()

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection, tables: set[str]) -> None:
        if tables != _TABLES:
            raise OperationJournalError("operation_journal_schema_layout_invalid")
        rows = tuple(
            tuple(row)
            for row in connection.execute("SELECT key, value FROM schema_meta ORDER BY key")
        )
        if rows != (("schema_version", OPERATION_JOURNAL_SCHEMA_VERSION),):
            raise OperationJournalError("operation_journal_schema_version_mismatch")
        if _schema_fingerprint(connection) != _expected_fingerprint():
            raise OperationJournalError("operation_journal_schema_layout_invalid")

    def _connect(self) -> sqlite3.Connection:
        connection = self._open_connection()
        try:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        except BaseException:
            connection.close()
            raise
        self._secure_files()
        return connection

    def _open_connection(self) -> sqlite3.Connection:
        self._assert_safe_directory()
        self._assert_safe_file(self.database_path)
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            check_same_thread=False,
            timeout=self._busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _prepare_directory(self) -> None:
        if not os.path.lexists(self.private_directory):
            self.private_directory.mkdir(mode=0o700)
            os.chmod(self.private_directory, 0o700)
        self._assert_safe_directory()

    def _assert_safe_directory(self) -> None:
        info = os.lstat(self.private_directory)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise OperationJournalError("operation_journal_private_directory_unsafe")

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
            raise OperationJournalError("operation_journal_private_file_unsafe")

    def _secure_files(self) -> None:
        self._assert_safe_directory()
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if os.path.lexists(path):
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise OperationJournalError("operation_journal_private_file_unsafe")
                if stat.S_IMODE(info.st_mode) != 0o600:
                    os.chmod(path, 0o600)


def _batched(cursor: sqlite3.Cursor, factory: object, batch_size: int) -> Iterator[object]:
    if not 1 <= batch_size <= 4096 or isinstance(batch_size, bool):
        raise ValueError("batch_size must be from 1 to 4096")
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            yield factory(row)  # type: ignore[operator]


def _identity_from_row(row: sqlite3.Row) -> LogicalOperationIdentity:
    identity = LogicalOperationIdentity(
        run_id=str(row["run_id"]),
        operation_key=str(row["operation_key"]),
        operation_kind=str(row["operation_kind"]),
        ordinal=int(row["ordinal"]),
        authority_commitment_sha256=str(row["authority_commitment_sha256"]),
        retry_disposition=RetryDisposition(str(row["retry_disposition"])),
    )
    if identity.logical_operation_id != str(
        row["logical_operation_id"]
    ) or identity.replay_key != str(row["replay_key"]):
        raise OperationJournalError("operation_journal_manifest_row_tampered")
    return identity


def _state_from_row(row: sqlite3.Row) -> OperationState:
    identity = _identity_from_row(row)
    phase = OperationPhase(str(row["phase"]))
    receipt = None
    if phase is OperationPhase.COMMITTED:
        receipt = OperationReceipt(
            run_id=identity.run_id,
            logical_operation_id=identity.logical_operation_id,
            request_commitment_sha256=str(row["request_commitment_sha256"]),
            receipt_id=str(row["receipt_id"]),
            result_commitment_sha256=str(row["result_commitment_sha256"]),
        )
    return OperationState(
        identity=identity,
        phase=phase,
        request_commitment_sha256=_optional(row["request_commitment_sha256"]),
        receipt=receipt,
        verifier_key_id=_optional(row["verifier_key_id"]),
        verification_commitment_sha256=_optional(row["verification_commitment_sha256"]),
    )


def _run_from_row(row: sqlite3.Row) -> OperationRunState:
    return OperationRunState(
        identity=OperationRunIdentity(
            run_id=str(row["run_id"]),
            operation_namespace=str(row["operation_namespace"]),
            manifest_commitment_sha256=str(row["manifest_commitment_sha256"]),
            policy_commitment_sha256=str(row["policy_commitment_sha256"]),
            signer_key_id=str(row["signer_key_id"]),
            expected_operation_count=int(row["expected_operation_count"]),
            journal_schema_version=str(row["journal_schema_version"]),
        ),
        phase=OperationRunPhase(str(row["phase"])),
        event_count=int(row["event_count"]),
        head_event_sha256=_optional(row["head_event_sha256"]),
    )


def _event_from_row(row: sqlite3.Row) -> OperationEvent:
    return OperationEvent(
        run_id=str(row["run_id"]),
        sequence=int(row["sequence"]),
        event_type=str(row["event_type"]),
        logical_operation_id=_optional(row["logical_operation_id"]),
        payload_json=str(row["payload_json"]),
        predecessor_event_sha256=_optional(row["predecessor_event_sha256"]),
        event_sha256=str(row["event_sha256"]),
        signer_key_id=str(row["signer_key_id"]),
        signature=str(row["signature"]),
    )


def _verified_receipt_from_row(row: sqlite3.Row) -> VerifiedOperationReceipt:
    identity = _identity_from_row(row)
    try:
        payload = json.loads(str(row["receipt_identity_json"]))
    except (TypeError, ValueError) as error:
        raise OperationJournalError("operation_journal_receipt_row_tampered") from error
    if not isinstance(payload, dict) or canonical_json(payload) != str(
        row["receipt_identity_json"]
    ):
        raise OperationJournalError("operation_journal_receipt_row_tampered")
    receipt = OperationReceipt(
        run_id=str(payload.get("run_id", "")),
        logical_operation_id=str(payload.get("logical_operation_id", "")),
        request_commitment_sha256=str(payload.get("request_commitment_sha256", "")),
        receipt_id=str(payload.get("receipt_id", "")),
        result_commitment_sha256=str(payload.get("result_commitment_sha256", "")),
    )
    if (
        receipt.run_id != identity.run_id
        or receipt.logical_operation_id != identity.logical_operation_id
        or receipt.identity_payload() != payload
        or sha256_commitment(payload) != str(row["receipt_commitment_sha256"])
    ):
        raise OperationJournalError("operation_journal_receipt_row_tampered")
    return VerifiedOperationReceipt(
        receipt=receipt,
        verifier_key_id=str(row["verifier_key_id"]),
        verification_commitment_sha256=str(row["verification_commitment_sha256"]),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


__all__ = ("SQLiteOperationJournal",)
