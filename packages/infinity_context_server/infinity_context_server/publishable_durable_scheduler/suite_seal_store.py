"""Authenticated exact-idempotent SQLite sidecar for one two-run suite seal."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final, final

from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.runner_contracts import (
    SUITE_SEAL_READBACK_POLICY_SHA256,
    SchedulerRunnerError,
    SchedulerSuiteSeal,
    is_sha256,
    suite_seal_from_material,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SchedulerSQLiteAuthenticator,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_schema import (
    prepare_private_database,
    validate_private_database_file,
)

_SCHEMA_VERSION = "publishable-durable-scheduler-suite-seal-sqlite.v1"
_SCHEMA: Final = (
    """CREATE TABLE suite_seal_meta (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        schema_fingerprint_sha256 TEXT NOT NULL,
        suite_authority_sha256 TEXT NOT NULL,
        seal_commitment_sha256 TEXT,
        readback_policy_sha256 TEXT NOT NULL,
        row_mac TEXT NOT NULL
    )""",
    """CREATE TABLE suite_seals (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        suite_authority_sha256 TEXT NOT NULL,
        seal_commitment_sha256 TEXT NOT NULL,
        material_json TEXT NOT NULL,
        row_mac TEXT NOT NULL
    )""",
)


@final
class SQLiteSchedulerSuiteSealStore:
    """Persist one authenticated suite seal; exact replay returns the stored value."""

    __slots__ = ("_auth", "_database_path", "_private_directory", "_suite_authority")

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        authentication_secret: bytes,
        suite_authority_sha256: str,
    ) -> None:
        if not is_sha256(suite_authority_sha256):
            _fail("scheduler_runner_suite_seal_store_authority_invalid")
        self._database_path = database_path
        self._private_directory = private_directory
        self._auth = SchedulerSQLiteAuthenticator(authentication_secret)
        self._suite_authority = suite_authority_sha256
        with self._immediate():
            pass

    @property
    def readback_policy_sha256(self) -> str:
        return SUITE_SEAL_READBACK_POLICY_SHA256

    def read(self) -> SchedulerSuiteSeal | None:
        with self._immediate() as connection:
            return self._read(connection)

    def persist_exact(self, seal: SchedulerSuiteSeal) -> SchedulerSuiteSeal:
        if type(seal) is not SchedulerSuiteSeal:
            _fail("scheduler_runner_suite_seal_invalid")
        SchedulerSuiteSeal.__post_init__(seal)
        with self._immediate() as connection:
            existing = self._read(connection)
            if existing is not None:
                if existing != seal:
                    _fail("scheduler_runner_suite_seal_divergent")
                return existing
            if seal.suite_authority_sha256 != self._suite_authority:
                _fail("scheduler_runner_suite_seal_divergent")
            material_json = canonical_json(seal.material()).decode("ascii")
            values = {
                "singleton": 1,
                "suite_authority_sha256": self._suite_authority,
                "seal_commitment_sha256": seal.commitment_sha256,
                "material_json": material_json,
            }
            connection.execute(
                "INSERT INTO suite_seals VALUES (?, ?, ?, ?, ?)",
                (*values.values(), self._auth.sign("suite-seal-row", values)),
            )
            meta = self._meta_values(seal_commitment_sha256=seal.commitment_sha256)
            cursor = connection.execute(
                """UPDATE suite_seal_meta
                   SET seal_commitment_sha256 = ?, row_mac = ?
                   WHERE singleton = 1 AND seal_commitment_sha256 IS NULL""",
                (
                    seal.commitment_sha256,
                    self._auth.sign("suite-seal-meta-row", meta),
                ),
            )
            if cursor.rowcount != 1:
                _fail("scheduler_runner_suite_seal_concurrent_write")
            return self._read(connection) or _raise_missing()

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        connection, initialize = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_ready(connection, initialize=initialize)
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _connection(self) -> tuple[sqlite3.Connection, bool]:
        database, initialize = prepare_private_database(
            self._database_path,
            private_directory=self._private_directory,
        )
        try:
            connection = sqlite3.connect(
                database,
                timeout=10.0,
                isolation_level=None,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            validate_private_database_file(database)
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA journal_mode = DELETE")
            return connection, initialize
        except (sqlite3.DatabaseError, IndexError, TypeError) as error:
            if "connection" in locals():
                connection.close()
            _fail_from("scheduler_runner_suite_seal_integrity_invalid", error)
        except BaseException:
            if "connection" in locals():
                connection.close()
            raise

    def _ensure_ready(self, connection: sqlite3.Connection, *, initialize: bool) -> None:
        rows = _user_schema(connection)
        if initialize:
            if rows:
                _fail("scheduler_runner_suite_seal_schema_invalid")
            for statement in _SCHEMA:
                connection.execute(statement)
            values = self._meta_values(seal_commitment_sha256=None)
            connection.execute(
                "INSERT INTO suite_seal_meta VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*values.values(), self._auth.sign("suite-seal-meta-row", values)),
            )
        else:
            if not rows or _fingerprint(connection) != _schema_fingerprint():
                _fail("scheduler_runner_suite_seal_schema_invalid")
            if connection.execute("SELECT * FROM suite_seal_meta").fetchone() is None:
                _fail("scheduler_runner_suite_seal_meta_missing")
            self._read(connection)
        try:
            quick = connection.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as error:
            _fail_from("scheduler_runner_suite_seal_integrity_invalid", error)
        if quick is None or quick[0] != "ok":
            _fail("scheduler_runner_suite_seal_integrity_invalid")

    def _read(self, connection: sqlite3.Connection) -> SchedulerSuiteSeal | None:
        meta_row = connection.execute("SELECT * FROM suite_seal_meta").fetchone()
        if meta_row is None:
            _fail("scheduler_runner_suite_seal_meta_missing")
        meta = self._verify_meta(meta_row)
        row = connection.execute("SELECT * FROM suite_seals").fetchone()
        if row is None:
            if meta["seal_commitment_sha256"] is not None:
                _fail("scheduler_runner_suite_seal_missing")
            return None
        values = {
            "singleton": row["singleton"],
            "suite_authority_sha256": row["suite_authority_sha256"],
            "seal_commitment_sha256": row["seal_commitment_sha256"],
            "material_json": row["material_json"],
        }
        if not self._auth.verify("suite-seal-row", values, row["row_mac"]):
            _fail("scheduler_runner_suite_seal_authentication_invalid")
        if (
            values["suite_authority_sha256"] != self._suite_authority
            or values["seal_commitment_sha256"] != meta["seal_commitment_sha256"]
            or type(values["material_json"]) is not str
        ):
            _fail("scheduler_runner_suite_seal_binding_invalid")
        try:
            material = json.loads(values["material_json"])
        except (json.JSONDecodeError, TypeError) as error:
            _fail_from("scheduler_runner_suite_seal_material_invalid", error)
        if canonical_json(material).decode("ascii") != values["material_json"]:
            _fail("scheduler_runner_suite_seal_material_invalid")
        seal = suite_seal_from_material(material)
        if (
            seal.commitment_sha256 != values["seal_commitment_sha256"]
            or seal.suite_authority_sha256 != self._suite_authority
            or seal.seal_readback_policy_sha256 != SUITE_SEAL_READBACK_POLICY_SHA256
        ):
            _fail("scheduler_runner_suite_seal_binding_invalid")
        return seal

    def _verify_meta(self, row: sqlite3.Row) -> dict[str, object]:
        values = {
            "singleton": row["singleton"],
            "schema_version": row["schema_version"],
            "schema_fingerprint_sha256": row["schema_fingerprint_sha256"],
            "suite_authority_sha256": row["suite_authority_sha256"],
            "seal_commitment_sha256": row["seal_commitment_sha256"],
            "readback_policy_sha256": row["readback_policy_sha256"],
        }
        if not self._auth.verify("suite-seal-meta-row", values, row["row_mac"]):
            _fail("scheduler_runner_suite_seal_authentication_invalid")
        expected = self._meta_values(seal_commitment_sha256=values["seal_commitment_sha256"])
        if values != expected:
            _fail("scheduler_runner_suite_seal_meta_invalid")
        return values

    def _meta_values(self, *, seal_commitment_sha256: object) -> dict[str, object]:
        return {
            "singleton": 1,
            "schema_version": _SCHEMA_VERSION,
            "schema_fingerprint_sha256": _schema_fingerprint(),
            "suite_authority_sha256": self._suite_authority,
            "seal_commitment_sha256": seal_commitment_sha256,
            "readback_policy_sha256": SUITE_SEAL_READBACK_POLICY_SHA256,
        }


def _schema_fingerprint() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        return _fingerprint(connection)
    finally:
        connection.close()


def _fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type, name, tbl_name, sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
    ).fetchall()
    return hashlib.sha256(repr(tuple(tuple(row) for row in rows)).encode()).hexdigest()


def _user_schema(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            """SELECT type, name FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"""
        )
    )


def _raise_missing() -> SchedulerSuiteSeal:
    _fail("scheduler_runner_suite_seal_missing")


def _fail_from(code: str, error: BaseException) -> None:
    raise SchedulerRunnerError(code) from error


def _fail(code: str) -> None:
    raise SchedulerRunnerError(code)


__all__ = ("SQLiteSchedulerSuiteSealStore",)
