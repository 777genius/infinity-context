"""Exact SQLite schema and private-file boundary for scheduler v4."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from pathlib import Path
from typing import Final

from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteError,
)

_SCHEMA: Final = (
    """CREATE TABLE scheduler_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        schema_fingerprint_sha256 TEXT NOT NULL,
        row_mac TEXT NOT NULL
    )""",
    """CREATE TABLE scheduler_manifests (
        run_id TEXT PRIMARY KEY,
        suite_authority_sha256 TEXT NOT NULL,
        run_authority_sha256 TEXT NOT NULL,
        manifest_authority_sha256 TEXT NOT NULL,
        case_manifest_sha256 TEXT NOT NULL,
        call_count INTEGER NOT NULL CHECK (call_count > 0),
        shard_count INTEGER NOT NULL CHECK (shard_count > 0),
        row_mac TEXT NOT NULL
    )""",
    """CREATE TABLE scheduler_shards (
        run_id TEXT NOT NULL,
        shard_index INTEGER NOT NULL CHECK (shard_index >= 0),
        shard_sha256 TEXT NOT NULL,
        start_ordinal INTEGER NOT NULL CHECK (start_ordinal >= 0),
        end_ordinal INTEGER NOT NULL CHECK (end_ordinal > start_ordinal),
        row_mac TEXT NOT NULL,
        PRIMARY KEY (run_id, shard_index),
        FOREIGN KEY (run_id) REFERENCES scheduler_manifests(run_id)
    )""",
    """CREATE TABLE scheduler_runs (
        run_id TEXT PRIMARY KEY,
        run_authority_sha256 TEXT NOT NULL,
        bridge_boot_authority_sha256 TEXT NOT NULL,
        dispatch_not_before_unix_ms INTEGER NOT NULL,
        dispatch_deadline_unix_ms INTEGER NOT NULL,
        token_ceiling INTEGER NOT NULL,
        expected_call_count INTEGER NOT NULL,
        phase TEXT NOT NULL,
        reserved_tokens INTEGER NOT NULL,
        consumed_tokens INTEGER NOT NULL,
        burned_tokens INTEGER NOT NULL,
        inflight_logical_call_id TEXT,
        version INTEGER NOT NULL,
        event_head_sha256 TEXT NOT NULL,
        row_mac TEXT NOT NULL,
        FOREIGN KEY (run_id) REFERENCES scheduler_manifests(run_id)
    )""",
    """CREATE TABLE scheduler_calls (
        run_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        shard_index INTEGER NOT NULL CHECK (shard_index >= 0),
        logical_call_id TEXT NOT NULL UNIQUE,
        stage TEXT NOT NULL,
        token_ceiling INTEGER NOT NULL,
        depends_on_logical_call_id TEXT,
        phase TEXT NOT NULL,
        attempt_count INTEGER NOT NULL,
        lease_id TEXT,
        lease_expires_unix_ms INTEGER,
        request_sha256 TEXT,
        intent_sha256 TEXT,
        terminal_evidence_sha256 TEXT,
        charged_tokens INTEGER NOT NULL,
        answer_ciphertext BLOB,
        answer_ciphertext_sha256 TEXT,
        answer_ciphertext_bytes INTEGER NOT NULL,
        version INTEGER NOT NULL,
        row_mac TEXT NOT NULL,
        PRIMARY KEY (run_id, ordinal),
        FOREIGN KEY (run_id, shard_index) REFERENCES scheduler_shards(run_id, shard_index)
    )""",
    """CREATE INDEX scheduler_calls_run_phase_ordinal
        ON scheduler_calls(run_id, phase, ordinal)""",
    """CREATE TABLE scheduler_events (
        event_id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL,
        logical_call_id TEXT,
        event_kind TEXT NOT NULL,
        run_version INTEGER NOT NULL,
        call_version INTEGER,
        state_sha256 TEXT NOT NULL,
        previous_event_sha256 TEXT NOT NULL,
        event_sha256 TEXT NOT NULL UNIQUE,
        FOREIGN KEY (run_id) REFERENCES scheduler_runs(run_id),
        FOREIGN KEY (logical_call_id) REFERENCES scheduler_calls(logical_call_id)
    )""",
)


def schema_fingerprint_sha256() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for statement in _SCHEMA:
            connection.execute(statement)
        return _fingerprint(connection)
    finally:
        connection.close()


def open_scheduler_connection(
    database_path: Path,
    *,
    private_directory: Path,
) -> sqlite3.Connection:
    database = _paths(database_path, private_directory)
    existed = database.exists()
    if existed:
        _file(database)
    else:
        _create_private_database(database)
    try:
        connection = sqlite3.connect(
            database,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
    except sqlite3.DatabaseError as error:
        raise SchedulerSQLiteError("scheduler_sqlite_open_failed") from error
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA journal_mode = DELETE")
        _file(database)
        _ensure_schema(connection)
        _validate_database(connection)
        return connection
    except sqlite3.DatabaseError as error:
        connection.close()
        raise SchedulerSQLiteError("scheduler_sqlite_integrity_invalid") from error
    except BaseException:
        connection.close()
        raise


def _ensure_schema(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("BEGIN IMMEDIATE")
        tables = _user_schema(connection)
        if not tables:
            for statement in _SCHEMA:
                connection.execute(statement)
        elif _fingerprint(connection) != schema_fingerprint_sha256():
            raise SchedulerSQLiteError("scheduler_sqlite_schema_invalid")
        connection.commit()
    except sqlite3.DatabaseError as error:
        connection.rollback()
        raise SchedulerSQLiteError("scheduler_sqlite_schema_invalid") from error
    except BaseException:
        connection.rollback()
        raise


def _validate_database(connection: sqlite3.Connection) -> None:
    try:
        if _fingerprint(connection) != schema_fingerprint_sha256():
            raise SchedulerSQLiteError("scheduler_sqlite_schema_invalid")
        quick = connection.execute("PRAGMA quick_check").fetchone()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchone()
        if quick is None or quick[0] != "ok" or foreign is not None:
            raise SchedulerSQLiteError("scheduler_sqlite_integrity_invalid")
    except sqlite3.DatabaseError as error:
        raise SchedulerSQLiteError("scheduler_sqlite_integrity_invalid") from error


def _fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type, name, tbl_name, sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
    ).fetchall()
    encoded = repr(tuple(tuple(row) for row in rows)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _user_schema(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            """SELECT type, name FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        )
    )


def _paths(database_path: Path, private_directory: Path) -> Path:
    if not isinstance(database_path, Path) or not isinstance(private_directory, Path):
        raise SchedulerSQLiteError("scheduler_sqlite_path_invalid")
    if not private_directory.exists():
        private_directory.mkdir(mode=0o700, parents=False)
    info = private_directory.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
        or info.st_nlink < 2
    ):
        raise SchedulerSQLiteError("scheduler_sqlite_private_directory_unsafe")
    if database_path.parent != private_directory or database_path.name in {"", ".", ".."}:
        raise SchedulerSQLiteError("scheduler_sqlite_path_invalid")
    return database_path


def _file(database: Path) -> None:
    try:
        info = database.lstat()
    except FileNotFoundError as error:
        raise SchedulerSQLiteError("scheduler_sqlite_database_missing") from error
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise SchedulerSQLiteError("scheduler_sqlite_database_unsafe")


def _create_private_database(database: Path) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(database, flags, 0o600)
    except OSError as error:
        raise SchedulerSQLiteError("scheduler_sqlite_database_unsafe") from error
    try:
        os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
        ):
            raise SchedulerSQLiteError("scheduler_sqlite_database_unsafe")
    finally:
        os.close(descriptor)


__all__ = ("open_scheduler_connection", "schema_fingerprint_sha256")
