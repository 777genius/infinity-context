"""Private authenticated SQLite CAS authority for managed Mem0-v5 checkpoint heads.

HMACs authenticate schema and rows while transactional CAS rejects stale concurrent writers.
They do not establish freshness: replaying a complete valid prior database is indistinguishable
from legitimate older state without an anchor in a separate failure domain. Production therefore
requires an external freshness anchor and a dedicated runtime UID. The UID boundary matters:
another process with the same UID can read the HMAC key or interfere with SQLite journal paths;
fd binding and pathname checks reduce races but do not claim protection from that peer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import final

from infinity_context_server.memory_comparison_managed_run_contract import ManagedRunError
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import is_sha256

_SCHEMA_VERSION = "managed-mem0-v5-checkpoint-head.v1"
_UNAVAILABLE = "managed Mem0 v5 checkpoint head storage is unavailable"
_CORRUPT = "managed Mem0 v5 checkpoint head authentication failed"
_CONFLICT = "managed Mem0 v5 checkpoint head conflict"
_INPUT_INVALID = "managed Mem0 v5 checkpoint head input is invalid"

_CREATE_META = """
CREATE TABLE IF NOT EXISTS checkpoint_head_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version TEXT NOT NULL,
    structural_fingerprint_sha256 TEXT NOT NULL,
    schema_hmac_sha256 TEXT NOT NULL
)
"""
_CREATE_HEADS = """
CREATE TABLE IF NOT EXISTS checkpoint_heads (
    authority_commitment_sha256 TEXT NOT NULL,
    admission_commitment_sha256 TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    previous_commitment_sha256 TEXT,
    head_commitment_sha256 TEXT NOT NULL,
    row_hmac_sha256 TEXT NOT NULL,
    PRIMARY KEY (authority_commitment_sha256, admission_commitment_sha256)
)
"""


def _normalized_sql(value: str) -> str:
    return " ".join(value.split())


_EXPECTED_TABLES = {
    "checkpoint_head_meta": _normalized_sql(_CREATE_META).replace(" IF NOT EXISTS", ""),
    "checkpoint_heads": _normalized_sql(_CREATE_HEADS).replace(" IF NOT EXISTS", ""),
}
_STRUCTURAL_FINGERPRINT = hashlib.sha256(
    json.dumps(_EXPECTED_TABLES, sort_keys=True, separators=(",", ":")).encode("ascii")
).hexdigest()


@final
class SQLiteManagedMem0V5CheckpointHead:
    """Cross-process HMAC-authenticated implementation of the checkpoint-head port."""

    __slots__ = ("_hmac_key", "_path")

    def __init__(self, path: Path, *, hmac_key: bytes, require_existing: bool = False) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or path.name in {"", ".", ".."}
            or type(hmac_key) is not bytes
            or len(hmac_key) < 32
            or type(require_existing) is not bool
        ):
            raise ManagedRunError(_INPUT_INVALID)
        self._path = path
        self._hmac_key = bytes(hmac_key)
        try:
            newly_created = self._prepare_private_storage(require_existing=require_existing)
            with self._connection() as connection:
                if newly_created:
                    self._initialize_new(connection)
                else:
                    connection.execute("BEGIN")
                    try:
                        self._verify_schema(connection)
                        self._verify_all_heads(connection)
                    except BaseException:
                        connection.execute("ROLLBACK")
                        raise
                    else:
                        connection.execute("COMMIT")
        except ManagedRunError:
            raise
        except (OSError, sqlite3.Error):
            raise ManagedRunError(_UNAVAILABLE) from None

    def _initialize_new(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(_CREATE_META)
            connection.execute(_CREATE_HEADS)
            connection.execute(
                """INSERT INTO checkpoint_head_meta
                   (singleton, schema_version, structural_fingerprint_sha256,
                    schema_hmac_sha256) VALUES (1, ?, ?, ?)""",
                (_SCHEMA_VERSION, _STRUCTURAL_FINGERPRINT, self._schema_hmac()),
            )
            self._verify_schema(connection)
            self._verify_all_heads(connection)
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")

    def load_head(
        self,
        *,
        authority_commitment_sha256: str,
        admission_commitment_sha256: str,
    ) -> str | None:
        authority, admission = _binding(
            authority_commitment_sha256,
            admission_commitment_sha256,
        )
        try:
            with self._connection() as connection:
                connection.execute("BEGIN")
                try:
                    self._verify_schema(connection)
                    row = self._select(connection, authority, admission)
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
            return None if row is None else row[4]
        except ManagedRunError:
            raise
        except (OSError, sqlite3.Error):
            raise ManagedRunError(_UNAVAILABLE) from None

    def require_empty(self) -> None:
        """Authenticate the complete store and reject every persisted head row."""

        try:
            with self._connection() as connection:
                connection.execute("BEGIN")
                try:
                    self._verify_schema(connection)
                    self._verify_all_heads(connection)
                    row = connection.execute("SELECT COUNT(*) FROM checkpoint_heads").fetchone()
                    if row is None or type(row[0]) is not int or row[0] != 0:
                        raise ManagedRunError(_CORRUPT)
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
        except ManagedRunError:
            raise
        except (OSError, sqlite3.Error):
            raise ManagedRunError(_UNAVAILABLE) from None

    def compare_and_swap_head(
        self,
        *,
        authority_commitment_sha256: str,
        admission_commitment_sha256: str,
        expected_commitment_sha256: str | None,
        next_commitment_sha256: str,
    ) -> None:
        authority, admission = _binding(
            authority_commitment_sha256,
            admission_commitment_sha256,
        )
        expected = _optional_digest(expected_commitment_sha256)
        next_head = _digest(next_commitment_sha256)
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    self._verify_schema(connection)
                    row = self._select(connection, authority, admission)
                    if row is None:
                        if expected is not None:
                            raise ManagedRunError(_CONFLICT)
                        self._insert(connection, authority, admission, next_head)
                    else:
                        self._advance(
                            connection,
                            row,
                            expected_commitment_sha256=expected,
                            next_commitment_sha256=next_head,
                        )
                except BaseException:
                    connection.execute("ROLLBACK")
                    raise
                else:
                    connection.execute("COMMIT")
        except ManagedRunError:
            raise
        except (OSError, sqlite3.Error):
            raise ManagedRunError(_UNAVAILABLE) from None

    def _advance(
        self,
        connection: sqlite3.Connection,
        row: tuple[object, ...],
        *,
        expected_commitment_sha256: str | None,
        next_commitment_sha256: str,
    ) -> None:
        authority, admission, generation, previous, current, _row_hmac = row
        if current == next_commitment_sha256:
            if expected_commitment_sha256 in {previous, current}:
                return
            raise ManagedRunError(_CONFLICT)
        if current != expected_commitment_sha256:
            raise ManagedRunError(_CONFLICT)
        next_generation = generation + 1
        next_hmac = self._row_hmac(
            authority,
            admission,
            next_generation,
            current,
            next_commitment_sha256,
        )
        changed = connection.execute(
            """UPDATE checkpoint_heads
               SET generation = ?, previous_commitment_sha256 = ?,
                   head_commitment_sha256 = ?, row_hmac_sha256 = ?
               WHERE authority_commitment_sha256 = ?
                 AND admission_commitment_sha256 = ?
                 AND generation = ? AND row_hmac_sha256 = ?""",
            (
                next_generation,
                current,
                next_commitment_sha256,
                next_hmac,
                authority,
                admission,
                generation,
                _row_hmac,
            ),
        ).rowcount
        if changed != 1:
            raise ManagedRunError(_CONFLICT)

    def _insert(
        self,
        connection: sqlite3.Connection,
        authority: str,
        admission: str,
        next_head: str,
    ) -> None:
        connection.execute(
            """INSERT INTO checkpoint_heads
               (authority_commitment_sha256, admission_commitment_sha256, generation,
                previous_commitment_sha256, head_commitment_sha256, row_hmac_sha256)
               VALUES (?, ?, 0, NULL, ?, ?)""",
            (
                authority,
                admission,
                next_head,
                self._row_hmac(authority, admission, 0, None, next_head),
            ),
        )

    def _select(
        self,
        connection: sqlite3.Connection,
        authority: str,
        admission: str,
    ) -> tuple[object, ...] | None:
        row = connection.execute(
            """SELECT authority_commitment_sha256, admission_commitment_sha256,
                      generation, previous_commitment_sha256,
                      head_commitment_sha256, row_hmac_sha256
               FROM checkpoint_heads
               WHERE authority_commitment_sha256 = ? AND admission_commitment_sha256 = ?""",
            (authority, admission),
        ).fetchone()
        if row is None:
            return None
        self._authenticate_row(row)
        return row

    def _authenticate_row(self, row: tuple[object, ...]) -> None:
        if (
            len(row) != 6
            or not is_sha256(row[0])
            or not is_sha256(row[1])
            or type(row[2]) is not int
            or row[2] < 0
            or (row[3] is not None and not is_sha256(row[3]))
            or not is_sha256(row[4])
            or not is_sha256(row[5])
        ):
            raise ManagedRunError(_CORRUPT)
        if row[2] == 0 and row[3] is not None:
            raise ManagedRunError(_CORRUPT)
        if row[2] > 0 and row[3] is None:
            raise ManagedRunError(_CORRUPT)
        expected = self._row_hmac(row[0], row[1], row[2], row[3], row[4])
        if not hmac.compare_digest(row[5], expected):
            raise ManagedRunError(_CORRUPT)

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = {
            name: _normalized_sql(str(sql))
            for kind, name, sql in rows
            if kind == "table" and not str(name).startswith("sqlite_")
        }
        unexpected = [
            (kind, name)
            for kind, name, sql in rows
            if kind in {"trigger", "view"} or (kind == "index" and sql is not None)
        ]
        meta = connection.execute(
            """SELECT schema_version, structural_fingerprint_sha256, schema_hmac_sha256
               FROM checkpoint_head_meta WHERE singleton = 1"""
        ).fetchall()
        if (
            tables != _EXPECTED_TABLES
            or unexpected
            or meta != [(_SCHEMA_VERSION, _STRUCTURAL_FINGERPRINT, self._schema_hmac())]
        ):
            raise ManagedRunError(_CORRUPT)

    def _verify_all_heads(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """SELECT authority_commitment_sha256, admission_commitment_sha256,
                      generation, previous_commitment_sha256,
                      head_commitment_sha256, row_hmac_sha256
               FROM checkpoint_heads"""
        ).fetchall()
        for row in rows:
            self._authenticate_row(row)

    def _schema_hmac(self) -> str:
        return _hmac(
            self._hmac_key,
            {
                "domain": "managed-mem0-v5-checkpoint-head-schema/v1",
                "schema_version": _SCHEMA_VERSION,
                "structural_fingerprint_sha256": _STRUCTURAL_FINGERPRINT,
            },
        )

    def _row_hmac(
        self,
        authority: str,
        admission: str,
        generation: int,
        previous: str | None,
        head: str,
    ) -> str:
        return _hmac(
            self._hmac_key,
            {
                "admission_commitment_sha256": admission,
                "authority_commitment_sha256": authority,
                "domain": "managed-mem0-v5-checkpoint-head-row/v1",
                "generation": generation,
                "head_commitment_sha256": head,
                "previous_commitment_sha256": previous,
            },
        )

    def _prepare_private_storage(self, *, require_existing: bool) -> bool:
        directory = self._path.parent
        if not os.path.lexists(directory):
            if require_existing:
                raise ManagedRunError(_UNAVAILABLE)
            directory.mkdir(mode=0o700, parents=True)
        _require_private_directory(directory)
        self._assert_surfaces()
        newly_created = not os.path.lexists(self._path)
        if newly_created:
            if require_existing:
                raise ManagedRunError(_UNAVAILABLE)
            directory_fd = _open_directory(directory)
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
                descriptor = os.open(self._path.name, flags, 0o600, dir_fd=directory_fd)
                os.close(descriptor)
            finally:
                os.close(directory_fd)
        _require_private_file(self._path)
        return newly_created

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        _require_private_directory(self._path.parent)
        self._assert_surfaces()
        directory_fd, database_fd = self._open_bound_database()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                f"file:/proc/self/fd/{database_fd}?mode=rw",
                uri=True,
                isolation_level=None,
                timeout=10.0,
                check_same_thread=False,
            )
            connection.execute("PRAGMA trusted_schema = OFF")
            mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
            if mode is None or str(mode[0]).lower() != "delete":
                raise ManagedRunError(_UNAVAILABLE)
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            self._assert_surfaces()
            yield connection
        finally:
            try:
                if connection is not None:
                    connection.close()
                self._assert_bound_database(directory_fd, database_fd)
            finally:
                os.close(database_fd)
                os.close(directory_fd)
            self._assert_surfaces()

    def _open_bound_database(self) -> tuple[int, int]:
        directory_fd = _open_directory(self._path.parent)
        try:
            database_fd = os.open(
                self._path.name,
                os.O_RDWR | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except BaseException:
            os.close(directory_fd)
            raise
        try:
            self._assert_bound_database(directory_fd, database_fd)
        except BaseException:
            os.close(database_fd)
            os.close(directory_fd)
            raise
        return directory_fd, database_fd

    def _assert_bound_database(self, directory_fd: int, database_fd: int) -> None:
        directory_info = os.fstat(directory_fd)
        path_directory_info = os.lstat(self._path.parent)
        database_info = os.fstat(database_fd)
        path_database_info = os.stat(
            self._path.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISDIR(directory_info.st_mode)
            or directory_info.st_uid != os.getuid()
            or stat.S_IMODE(directory_info.st_mode) != 0o700
            or (directory_info.st_dev, directory_info.st_ino)
            != (path_directory_info.st_dev, path_directory_info.st_ino)
            or not stat.S_ISREG(database_info.st_mode)
            or database_info.st_uid != os.getuid()
            or stat.S_IMODE(database_info.st_mode) != 0o600
            or (database_info.st_dev, database_info.st_ino)
            != (path_database_info.st_dev, path_database_info.st_ino)
        ):
            raise ManagedRunError(_UNAVAILABLE)

    def _assert_surfaces(self) -> None:
        for surface in self._surfaces():
            if os.path.lexists(surface):
                _require_private_file(surface)

    def _surfaces(self) -> tuple[Path, ...]:
        return (
            self._path,
            Path(f"{self._path}-journal"),
            Path(f"{self._path}-wal"),
            Path(f"{self._path}-shm"),
            Path(f"{self._path}-lock"),
        )


def _binding(authority: object, admission: object) -> tuple[str, str]:
    return _digest(authority), _digest(admission)


def _digest(value: object) -> str:
    if not is_sha256(value):
        raise ManagedRunError(_INPUT_INVALID)
    return value


def _optional_digest(value: object) -> str | None:
    return None if value is None else _digest(value)


def _open_directory(path: Path) -> int:
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _require_private_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        raise ManagedRunError(_UNAVAILABLE) from None
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ManagedRunError(_UNAVAILABLE)


def _require_private_file(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        raise ManagedRunError(_UNAVAILABLE) from None
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ManagedRunError(_UNAVAILABLE)


def _hmac(key: bytes, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


__all__ = ["SQLiteManagedMem0V5CheckpointHead"]
