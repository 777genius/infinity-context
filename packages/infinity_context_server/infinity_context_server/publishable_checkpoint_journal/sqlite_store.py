"""SQLite connection, schema, and private-directory ownership for the journal."""

from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import final

from infinity_context_server.publishable_checkpoint_journal.domain import (
    CHECKPOINT_JOURNAL_SCHEMA_VERSION,
    CallPhase,
    CheckpointJournalError,
    JournalEvent,
    JournalRunState,
    ProviderCallState,
)
from infinity_context_server.publishable_checkpoint_journal.sqlite_rows import (
    iter_calls,
    iter_events,
    iter_pending_lifecycle_events,
    run_from_row,
)
from infinity_context_server.publishable_checkpoint_journal.sqlite_transaction import (
    SQLiteCheckpointJournalTransaction,
)

_REQUIRED_TABLES = frozenset(
    {
        "schema_meta",
        "run_state",
        "manifest_cases",
        "manifest_backend_targets",
        "evaluation_manifest",
        "case_lanes",
        "provider_calls",
        "private_provider_results",
        "receipt_events",
        "lifecycle_outbox",
    }
)
_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE run_state (
        run_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        profile_commitment_sha256 TEXT NOT NULL,
        dataset_commitment_sha256 TEXT NOT NULL,
        methodology_commitment_sha256 TEXT NOT NULL,
        source_commit_sha256 TEXT NOT NULL,
        runtime_pin_sha256 TEXT NOT NULL,
        case_manifest_sha256 TEXT NOT NULL,
        manifest_authority_commitment_sha256 TEXT NOT NULL,
        evaluation_manifest_commitment_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        journal_schema_version TEXT NOT NULL,
        expected_case_count INTEGER NOT NULL,
        expected_message_count INTEGER NOT NULL,
        expected_extraction_call_count INTEGER NOT NULL,
        expected_answer_judge_call_count INTEGER NOT NULL,
        phase TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        head_event_sha256 TEXT
    )
    """,
    """
    CREATE TABLE manifest_cases (
        run_id TEXT NOT NULL,
        case_ordinal INTEGER NOT NULL,
        case_id TEXT NOT NULL,
        case_alias TEXT NOT NULL,
        PRIMARY KEY (run_id, case_ordinal),
        UNIQUE (run_id, case_id),
        UNIQUE (run_id, case_alias),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id)
    )
    """,
    """
    CREATE TABLE manifest_backend_targets (
        run_id TEXT NOT NULL,
        backend_ordinal INTEGER NOT NULL,
        backend_role TEXT NOT NULL,
        backend_target_id TEXT NOT NULL,
        backend_target_commitment_sha256 TEXT NOT NULL,
        PRIMARY KEY (run_id, backend_ordinal),
        UNIQUE (run_id, backend_role),
        UNIQUE (run_id, backend_target_id),
        UNIQUE (run_id, backend_target_commitment_sha256),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id)
    )
    """,
    """
    CREATE TABLE evaluation_manifest (
        run_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        logical_call_id TEXT NOT NULL,
        replay_key TEXT NOT NULL,
        case_lane_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        case_alias TEXT NOT NULL,
        backend_role TEXT NOT NULL,
        backend_target_id TEXT NOT NULL,
        backend_target_commitment_sha256 TEXT NOT NULL,
        stage TEXT NOT NULL,
        depends_on_logical_call_id TEXT,
        PRIMARY KEY (run_id, ordinal),
        UNIQUE (run_id, logical_call_id),
        UNIQUE (run_id, replay_key),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id)
    )
    """,
    """
    CREATE TABLE case_lanes (
        run_id TEXT NOT NULL,
        case_lane_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        case_alias TEXT NOT NULL,
        backend_role TEXT NOT NULL,
        backend_target_id TEXT NOT NULL,
        backend_target_commitment_sha256 TEXT NOT NULL,
        answer_logical_call_id TEXT NOT NULL,
        judge_logical_call_id TEXT NOT NULL,
        PRIMARY KEY (run_id, case_lane_id),
        UNIQUE (run_id, case_id, backend_target_id),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id)
    )
    """,
    """
    CREATE TABLE provider_calls (
        run_id TEXT NOT NULL,
        logical_call_id TEXT NOT NULL,
        phase TEXT NOT NULL,
        request_commitment_sha256 TEXT,
        provider_receipt_id TEXT,
        result_commitment_sha256 TEXT,
        verifier_key_id TEXT,
        verification_commitment_sha256 TEXT,
        PRIMARY KEY (run_id, logical_call_id),
        UNIQUE (run_id, provider_receipt_id),
        FOREIGN KEY (run_id, logical_call_id)
            REFERENCES evaluation_manifest(run_id, logical_call_id)
    )
    """,
    """
    CREATE TABLE private_provider_results (
        run_id TEXT NOT NULL,
        logical_call_id TEXT NOT NULL,
        receipt_identity_json TEXT NOT NULL,
        request_commitment_sha256 TEXT NOT NULL,
        receipt_commitment_sha256 TEXT NOT NULL,
        verifier_key_id TEXT NOT NULL,
        verification_commitment_sha256 TEXT NOT NULL,
        PRIMARY KEY (run_id, logical_call_id),
        FOREIGN KEY (run_id, logical_call_id)
            REFERENCES provider_calls(run_id, logical_call_id)
    )
    """,
    """
    CREATE TABLE receipt_events (
        run_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        logical_call_id TEXT,
        payload_json TEXT NOT NULL,
        predecessor_event_sha256 TEXT,
        event_sha256 TEXT NOT NULL,
        signer_key_id TEXT NOT NULL,
        signature TEXT NOT NULL,
        PRIMARY KEY (run_id, sequence),
        UNIQUE (run_id, event_sha256),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id)
    )
    """,
    """
    CREATE TABLE lifecycle_outbox (
        run_id TEXT NOT NULL,
        event_sha256 TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, event_sha256),
        FOREIGN KEY (run_id, event_sha256)
            REFERENCES receipt_events(run_id, event_sha256)
    )
    """,
    """
    CREATE INDEX idx_provider_calls_run_phase
    ON provider_calls(run_id, phase, logical_call_id)
    """,
    """
    CREATE INDEX idx_lifecycle_outbox_pending
    ON lifecycle_outbox(run_id, delivered, event_sha256)
    """,
)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _schema_fingerprint(connection: sqlite3.Connection) -> tuple[object, ...]:
    objects = tuple(
        tuple(row)
        for row in connection.execute(
            """
            SELECT type, name, tbl_name
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        )
    )
    tables = tuple(
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    )
    columns: list[tuple[str, tuple[tuple[object, ...], ...]]] = []
    foreign_keys: list[tuple[str, tuple[tuple[object, ...], ...]]] = []
    indexes: list[tuple[str, tuple[tuple[object, ...], ...]]] = []
    for table in tables:
        quoted_table = _quote_identifier(table)
        columns.append(
            (
                table,
                tuple(
                    tuple(row) for row in connection.execute(f"PRAGMA table_xinfo({quoted_table})")
                ),
            )
        )
        foreign_keys.append(
            (
                table,
                tuple(
                    sorted(
                        tuple(row)
                        for row in connection.execute(f"PRAGMA foreign_key_list({quoted_table})")
                    )
                ),
            )
        )
        table_indexes: list[tuple[object, ...]] = []
        for row in connection.execute(f"PRAGMA index_list({quoted_table})"):
            index_name = str(row[1])
            table_indexes.append(
                (
                    index_name,
                    int(row[2]),
                    str(row[3]),
                    int(row[4]),
                    tuple(
                        tuple(index_row)
                        for index_row in connection.execute(
                            f"PRAGMA index_xinfo({_quote_identifier(index_name)})"
                        )
                    ),
                )
            )
        indexes.append((table, tuple(sorted(table_indexes))))
    return objects, tuple(columns), tuple(foreign_keys), tuple(indexes)


@cache
def _expected_schema_fingerprint() -> tuple[object, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA_STATEMENTS:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


@final
class SQLiteCheckpointJournal:
    """A local-only journal rooted in one explicit, private 0700 directory."""

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if not isinstance(database_path, Path) or not isinstance(private_directory, Path):
            raise TypeError("database_path and private_directory must be pathlib.Path")
        if database_path.parent != private_directory:
            raise ValueError("database_path must be directly inside private_directory")
        if (
            not isinstance(busy_timeout_ms, int)
            or isinstance(busy_timeout_ms, bool)
            or not 1 <= busy_timeout_ms <= 120_000
        ):
            raise ValueError("busy_timeout_ms must be an integer from 1 to 120000")
        self.database_path = database_path
        self.private_directory = private_directory
        self._busy_timeout_ms = busy_timeout_ms
        self._prepare_private_directory()
        self._assert_safe_existing_file(self.database_path, required_mode=0o600)
        self._initialize_schema()

    @property
    def schema_version(self) -> str:
        return CHECKPOINT_JOURNAL_SCHEMA_VERSION

    @contextmanager
    def write_transaction(self) -> Iterator[SQLiteCheckpointJournalTransaction]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield SQLiteCheckpointJournalTransaction(connection)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._secure_private_files()
            connection.close()

    def load_run(self, run_id: str) -> JournalRunState | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM run_state WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return run_from_row(row) if row is not None else None
        finally:
            self._secure_private_files()
            connection.close()

    def iter_calls(
        self,
        *,
        run_id: str,
        phases: tuple[CallPhase, ...] | None = None,
        batch_size: int = 256,
    ) -> Iterator[ProviderCallState]:
        connection = self._connect()
        try:
            yield from iter_calls(
                connection,
                run_id=run_id,
                phases=phases,
                batch_size=batch_size,
            )
        finally:
            self._secure_private_files()
            connection.close()

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[JournalEvent]:
        connection = self._connect()
        try:
            yield from iter_events(connection, run_id=run_id, batch_size=batch_size)
        finally:
            self._secure_private_files()
            connection.close()

    def iter_pending_lifecycle_events(
        self,
        *,
        run_id: str,
        batch_size: int = 64,
    ) -> Iterator[JournalEvent]:
        connection = self._connect()
        try:
            yield from iter_pending_lifecycle_events(
                connection,
                run_id=run_id,
                batch_size=batch_size,
            )
        finally:
            self._secure_private_files()
            connection.close()

    def pragma_values(self) -> dict[str, int | str]:
        connection = self._connect()
        try:
            return {
                "busy_timeout": int(connection.execute("PRAGMA busy_timeout").fetchone()[0]),
                "foreign_keys": int(connection.execute("PRAGMA foreign_keys").fetchone()[0]),
                "journal_mode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
                "synchronous": int(connection.execute("PRAGMA synchronous").fetchone()[0]),
            }
        finally:
            self._secure_private_files()
            connection.close()

    def _initialize_schema(self) -> None:
        connection = self._open_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            table_names = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            user_tables = table_names - {"sqlite_sequence"}
            if not user_tables:
                for statement in _SCHEMA_STATEMENTS:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES (?, ?)",
                    ("schema_version", CHECKPOINT_JOURNAL_SCHEMA_VERSION),
                )
            else:
                self._validate_existing_schema(connection, user_tables)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._secure_private_files()
            connection.close()

    @staticmethod
    def _validate_existing_schema(
        connection: sqlite3.Connection,
        table_names: set[str],
    ) -> None:
        if not table_names >= _REQUIRED_TABLES:
            raise CheckpointJournalError("checkpoint_journal_schema_tables_missing")
        if table_names != _REQUIRED_TABLES:
            raise CheckpointJournalError("checkpoint_journal_schema_layout_invalid")
        try:
            rows = tuple(
                tuple(row)
                for row in connection.execute(
                    "SELECT key, value FROM schema_meta ORDER BY key, rowid"
                )
            )
        except sqlite3.DatabaseError as error:
            raise CheckpointJournalError("checkpoint_journal_schema_version_invalid") from error
        version_rows = tuple(row for row in rows if row[0] == "schema_version")
        if not version_rows:
            raise CheckpointJournalError("checkpoint_journal_schema_version_missing")
        if len(version_rows) != 1:
            raise CheckpointJournalError("checkpoint_journal_schema_version_duplicate")
        if str(version_rows[0][1]) != CHECKPOINT_JOURNAL_SCHEMA_VERSION:
            raise CheckpointJournalError("checkpoint_journal_schema_version_mismatch")
        if rows != (("schema_version", CHECKPOINT_JOURNAL_SCHEMA_VERSION),):
            raise CheckpointJournalError("checkpoint_journal_schema_layout_invalid")
        try:
            fingerprint = _schema_fingerprint(connection)
        except sqlite3.DatabaseError as error:
            raise CheckpointJournalError("checkpoint_journal_schema_layout_invalid") from error
        if fingerprint != _expected_schema_fingerprint():
            raise CheckpointJournalError("checkpoint_journal_schema_layout_invalid")

    def _prepare_private_directory(self) -> None:
        if os.path.lexists(self.private_directory):
            self._assert_safe_directory()
            return
        self.private_directory.mkdir(mode=0o700)
        directory_stat = os.lstat(self.private_directory)
        if stat.S_IMODE(directory_stat.st_mode) != 0o700:
            os.chmod(self.private_directory, 0o700)
        self._assert_safe_directory()

    def _assert_safe_directory(self) -> None:
        directory_stat = os.lstat(self.private_directory)
        if (
            stat.S_ISLNK(directory_stat.st_mode)
            or not stat.S_ISDIR(directory_stat.st_mode)
            or directory_stat.st_uid != os.getuid()
            or stat.S_IMODE(directory_stat.st_mode) != 0o700
        ):
            raise CheckpointJournalError("checkpoint_journal_private_directory_unsafe")

    def _assert_safe_existing_file(self, path: Path, *, required_mode: int) -> None:
        if not os.path.lexists(path):
            return
        file_stat = os.lstat(path)
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.getuid()
            or stat.S_IMODE(file_stat.st_mode) != required_mode
        ):
            raise CheckpointJournalError("checkpoint_journal_private_file_unsafe")

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
        self._secure_private_files()
        return connection

    def _open_connection(self) -> sqlite3.Connection:
        self._assert_safe_directory()
        self._assert_safe_existing_file(self.database_path, required_mode=0o600)
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            check_same_thread=False,
            timeout=self._busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _secure_private_files(self) -> None:
        self._assert_safe_directory()
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if os.path.lexists(path):
                file_stat = os.lstat(path)
                if (
                    stat.S_ISLNK(file_stat.st_mode)
                    or not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.getuid()
                ):
                    raise CheckpointJournalError("checkpoint_journal_private_file_unsafe")
                if stat.S_IMODE(file_stat.st_mode) != 0o600:
                    os.chmod(path, 0o600)

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("SQLiteCheckpointJournal is final")


__all__ = ("SQLiteCheckpointJournal",)
