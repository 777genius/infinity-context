"""Private, authenticated SQLite operation state for the v5 benchmark adapter."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = 2
_CREATE_OPERATIONS = """CREATE TABLE IF NOT EXISTS operations_v2 (
  unit_identity_sha256 TEXT PRIMARY KEY,
  request_sha256 TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN (
    'ADMITTED','RESERVED','DISPATCHED','RECEIPT_DURABLE',
    'STORAGE_VERIFIED','COMMITTED','CLEANED','ABORT_CLEANED')),
  runtime_receipt_sha256 TEXT,
  storage_commitment_sha256 TEXT,
  tombstone_commitment_sha256 TEXT,
  abort_origin_state TEXT,
  abort_result_sha256 TEXT,
  outcome_unknown INTEGER NOT NULL CHECK(outcome_unknown IN (0,1)),
  row_hmac TEXT NOT NULL,
  CHECK ((tombstone_commitment_sha256 IS NOT NULL) =
         (state IN ('CLEANED','ABORT_CLEANED'))),
  CHECK ((abort_origin_state IS NOT NULL AND abort_result_sha256 IS NOT NULL) =
         (state = 'ABORT_CLEANED')),
  CHECK (abort_origin_state IS NULL OR abort_origin_state IN
         ('ADMITTED','RESERVED','DISPATCHED','RECEIPT_DURABLE','STORAGE_VERIFIED')),
  CHECK (outcome_unknown = 0 OR state = 'DISPATCHED' OR
         (state = 'ABORT_CLEANED' AND abort_origin_state = 'DISPATCHED'))
) STRICT"""
_CREATE_META = """CREATE TABLE IF NOT EXISTS adapter_state_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_version INTEGER NOT NULL CHECK(schema_version = 2),
  structural_fingerprint TEXT NOT NULL,
  schema_hmac TEXT NOT NULL
) STRICT"""


def _stored_sql(value: str) -> str:
    return " ".join(value.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE", 1).split())


_EXPECTED_TABLES = {
    "adapter_state_meta": _stored_sql(_CREATE_META),
    "operations_v2": _stored_sql(_CREATE_OPERATIONS),
}
STRUCTURAL_FINGERPRINT = hashlib.sha256(
    json.dumps(_EXPECTED_TABLES, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()


class StateError(RuntimeError):
    """The durable operation state cannot be safely used."""


class StateTamperedError(StateError):
    """Authenticated state or schema evidence differs from the expected value."""


class OperationState(StrEnum):
    ADMITTED = "ADMITTED"
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    RECEIPT_DURABLE = "RECEIPT_DURABLE"
    STORAGE_VERIFIED = "STORAGE_VERIFIED"
    COMMITTED = "COMMITTED"
    CLEANED = "CLEANED"
    ABORT_CLEANED = "ABORT_CLEANED"


@dataclass(frozen=True, slots=True)
class OperationRecord:
    unit_identity_sha256: str
    request_sha256: str
    state: OperationState
    runtime_receipt_sha256: str | None
    storage_commitment_sha256: str | None
    tombstone_commitment_sha256: str | None
    abort_origin_state: OperationState | None
    abort_result_sha256: str | None
    outcome_unknown: bool


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    retryable_reserved: tuple[str, ...]
    resumable_receipt_durable: tuple[str, ...]
    resumable_storage_verified: tuple[str, ...]
    outcome_unknown: tuple[str, ...]


class SqliteOperationState:
    """HMAC-authenticated state machine with conservative dispatch recovery."""

    def __init__(self, path: Path, *, hmac_key: bytes) -> None:
        self._path = _prepare_private_path(path)
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("state HMAC key must contain at least 32 bytes")
        self._hmac_key = hmac_key
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self._path,
            isolation_level=None,
            check_same_thread=False,
            timeout=30,
        )
        try:
            self._connection.execute("PRAGMA trusted_schema=OFF")
            mode = self._connection.execute("PRAGMA journal_mode=DELETE").fetchone()
            if mode is None or str(mode[0]).lower() != "delete":
                raise StateError("operation state requires SQLite DELETE journal mode")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute(_CREATE_OPERATIONS)
            self._connection.execute(_CREATE_META)
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            self._initialize_and_verify_schema()
            self.verify_all()
        except Exception:
            self._connection.close()
            raise

    def __enter__(self) -> SqliteOperationState:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def admit(self, unit_identity_sha256: str, request_sha256: str) -> OperationRecord:
        identity = _digest(unit_identity_sha256, "unit identity")
        request = _digest(request_sha256, "request")
        record = OperationRecord(
            unit_identity_sha256=identity,
            request_sha256=request,
            state=OperationState.ADMITTED,
            runtime_receipt_sha256=None,
            storage_commitment_sha256=None,
            tombstone_commitment_sha256=None,
            abort_origin_state=None,
            abort_result_sha256=None,
            outcome_unknown=False,
        )
        with self._transaction():
            self._connection.execute(
                """INSERT OR IGNORE INTO operations_v2
                   VALUES (?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, ?)""",
                (identity, request, record.state.value, self._row_hmac(record)),
            )
            persisted = self._get_in_transaction(identity)
            if persisted.request_sha256 != request:
                raise StateError("unit identity was reused with a different request")
        return persisted

    def reserve(self, unit_identity_sha256: str) -> OperationRecord:
        return self._transition(
            unit_identity_sha256, OperationState.ADMITTED, OperationState.RESERVED
        )

    def mark_dispatched(self, unit_identity_sha256: str) -> OperationRecord:
        return self._transition(
            unit_identity_sha256, OperationState.RESERVED, OperationState.DISPATCHED
        )

    def mark_receipt_durable(
        self, unit_identity_sha256: str, receipt_sha256: str
    ) -> OperationRecord:
        return self._transition(
            unit_identity_sha256,
            OperationState.DISPATCHED,
            OperationState.RECEIPT_DURABLE,
            runtime_receipt_sha256=_digest(receipt_sha256, "runtime receipt"),
            require_known_outcome=True,
        )

    def mark_storage_verified(
        self, unit_identity_sha256: str, storage_commitment_sha256: str
    ) -> OperationRecord:
        return self._transition(
            unit_identity_sha256,
            OperationState.RECEIPT_DURABLE,
            OperationState.STORAGE_VERIFIED,
            storage_commitment_sha256=_digest(storage_commitment_sha256, "storage commitment"),
        )

    def commit(self, unit_identity_sha256: str) -> OperationRecord:
        return self._transition(
            unit_identity_sha256, OperationState.STORAGE_VERIFIED, OperationState.COMMITTED
        )

    def clean(self, unit_identity_sha256: str, tombstone_commitment_sha256: str) -> OperationRecord:
        return self._transition(
            unit_identity_sha256,
            OperationState.COMMITTED,
            OperationState.CLEANED,
            tombstone_commitment_sha256=_digest(
                tombstone_commitment_sha256, "tombstone commitment"
            ),
        )

    def abort_cleaned(
        self,
        unit_identity_sha256: str,
        *,
        cleanup_result_sha256: str,
        tombstone_commitment_sha256: str,
    ) -> OperationRecord:
        """Seal abort cleanup without erasing durable receipt or storage evidence."""

        identity = _digest(unit_identity_sha256, "unit identity")
        result_sha = _digest(cleanup_result_sha256, "abort cleanup result")
        tombstone_sha = _digest(tombstone_commitment_sha256, "tombstone commitment")
        with self._transaction():
            current = self._get_in_transaction(identity)
            if current.state is OperationState.ABORT_CLEANED:
                if (
                    current.abort_result_sha256 != result_sha
                    or current.tombstone_commitment_sha256 != tombstone_sha
                ):
                    raise StateError("abort cleanup evidence is write-once")
                return current
            allowed = {
                OperationState.ADMITTED,
                OperationState.RESERVED,
                OperationState.DISPATCHED,
                OperationState.RECEIPT_DURABLE,
                OperationState.STORAGE_VERIFIED,
            }
            if current.state not in allowed:
                raise StateError("operation state cannot enter abort cleanup")
            if current.state is OperationState.DISPATCHED and not current.outcome_unknown:
                raise StateError("known dispatched operation cannot enter abort cleanup")
            updated = dataclass_replace(
                current,
                state=OperationState.ABORT_CLEANED,
                tombstone_commitment_sha256=tombstone_sha,
                abort_origin_state=current.state,
                abort_result_sha256=result_sha,
            )
            self._write_record(updated, expected=current)
        return updated

    def get(self, unit_identity_sha256: str) -> OperationRecord:
        identity = _digest(unit_identity_sha256, "unit identity")
        with self._lock:
            self._verify_schema()
            return self._get_in_transaction(identity)

    def get_many(self, unit_identity_sha256: Iterable[str]) -> tuple[OperationRecord, ...]:
        """Authenticate one exact identity inventory with one locked state query."""

        identities = tuple(_digest(value, "unit identity") for value in unit_identity_sha256)
        if not identities or len(set(identities)) != len(identities):
            raise ValueError("unit identity inventory must be nonempty and unique")
        with self._lock:
            self._verify_schema()
            by_identity = {
                record.unit_identity_sha256: record for record in self._all_in_transaction()
            }
        if any(identity not in by_identity for identity in identities):
            raise StateError("unknown operation identity")
        return tuple(by_identity[identity] for identity in identities)

    def recover(self) -> RecoveryReport:
        """Quarantine dispatched operations; never make a provider call retryable."""

        with self._transaction():
            records = self._all_in_transaction()
            for record in records:
                if record.state is OperationState.DISPATCHED and not record.outcome_unknown:
                    quarantined = dataclass_replace(record, outcome_unknown=True)
                    self._write_record(quarantined, expected=record)
            records = self._all_in_transaction()
        return RecoveryReport(
            retryable_reserved=_identities(records, OperationState.RESERVED),
            resumable_receipt_durable=_identities(records, OperationState.RECEIPT_DURABLE),
            resumable_storage_verified=_identities(records, OperationState.STORAGE_VERIFIED),
            outcome_unknown=tuple(
                record.unit_identity_sha256
                for record in records
                if record.state is OperationState.DISPATCHED and record.outcome_unknown
            ),
        )

    def verify_inventory(self, expected_unit_identity_sha256: Iterable[str]) -> None:
        """Compare with identities independently derived from the sealed input manifest."""

        expected = tuple(
            sorted({_digest(value, "unit identity") for value in expected_unit_identity_sha256})
        )
        with self._lock:
            self._verify_schema()
            actual = tuple(record.unit_identity_sha256 for record in self._all_in_transaction())
        if actual != expected:
            raise StateTamperedError(
                "operation state inventory differs from sealed input identities"
            )

    def verify_all(self) -> None:
        with self._lock:
            self._verify_schema()
            self._all_in_transaction()

    def _transition(
        self,
        identity_value: str,
        expected_state: OperationState,
        next_state: OperationState,
        *,
        runtime_receipt_sha256: str | None = None,
        storage_commitment_sha256: str | None = None,
        tombstone_commitment_sha256: str | None = None,
        require_known_outcome: bool = False,
    ) -> OperationRecord:
        identity = _digest(identity_value, "unit identity")
        with self._transaction():
            current = self._get_in_transaction(identity)
            if current.state is not expected_state:
                message = (
                    f"operation transition requires {expected_state.value}, "
                    f"got {current.state.value}"
                )
                raise StateError(message)
            if require_known_outcome and current.outcome_unknown:
                raise StateError("outcome-unknown dispatch cannot accept a late receipt")
            updated = dataclass_replace(
                current,
                state=next_state,
                runtime_receipt_sha256=runtime_receipt_sha256 or current.runtime_receipt_sha256,
                storage_commitment_sha256=(
                    storage_commitment_sha256 or current.storage_commitment_sha256
                ),
                tombstone_commitment_sha256=(
                    tombstone_commitment_sha256 or current.tombstone_commitment_sha256
                ),
            )
            self._write_record(updated, expected=current)
        return updated

    def _write_record(self, updated: OperationRecord, *, expected: OperationRecord) -> None:
        changed = self._connection.execute(
            """UPDATE operations_v2
               SET state = ?, runtime_receipt_sha256 = ?, storage_commitment_sha256 = ?,
                   tombstone_commitment_sha256 = ?, abort_origin_state = ?,
                   abort_result_sha256 = ?, outcome_unknown = ?, row_hmac = ?
               WHERE unit_identity_sha256 = ? AND state = ? AND outcome_unknown = ?
                     AND row_hmac = ?""",
            (
                updated.state.value,
                updated.runtime_receipt_sha256,
                updated.storage_commitment_sha256,
                updated.tombstone_commitment_sha256,
                updated.abort_origin_state.value if updated.abort_origin_state else None,
                updated.abort_result_sha256,
                int(updated.outcome_unknown),
                self._row_hmac(updated),
                updated.unit_identity_sha256,
                expected.state.value,
                int(expected.outcome_unknown),
                self._row_hmac(expected),
            ),
        ).rowcount
        if changed != 1:
            raise StateTamperedError("authenticated operation row changed concurrently")

    def _get_in_transaction(self, identity: str) -> OperationRecord:
        row = self._connection.execute(
            """SELECT unit_identity_sha256, request_sha256, state,
                      runtime_receipt_sha256, storage_commitment_sha256,
                      tombstone_commitment_sha256, abort_origin_state,
                      abort_result_sha256, outcome_unknown, row_hmac
               FROM operations_v2 WHERE unit_identity_sha256 = ?""",
            (identity,),
        ).fetchone()
        if row is None:
            raise StateError("unknown operation identity")
        return self._authenticated_record(row)

    def _all_in_transaction(self) -> tuple[OperationRecord, ...]:
        rows = self._connection.execute(
            """SELECT unit_identity_sha256, request_sha256, state,
                      runtime_receipt_sha256, storage_commitment_sha256,
                      tombstone_commitment_sha256, abort_origin_state,
                      abort_result_sha256, outcome_unknown, row_hmac
               FROM operations_v2 ORDER BY unit_identity_sha256"""
        ).fetchall()
        return tuple(self._authenticated_record(row) for row in rows)

    def _authenticated_record(self, row: tuple[object, ...]) -> OperationRecord:
        try:
            record = OperationRecord(
                unit_identity_sha256=_digest(row[0], "stored unit identity"),
                request_sha256=_digest(row[1], "stored request"),
                state=OperationState(str(row[2])),
                runtime_receipt_sha256=_optional_digest(row[3], "stored runtime receipt"),
                storage_commitment_sha256=_optional_digest(row[4], "stored storage commitment"),
                tombstone_commitment_sha256=_optional_digest(row[5], "stored tombstone commitment"),
                abort_origin_state=OperationState(str(row[6])) if row[6] is not None else None,
                abort_result_sha256=_optional_digest(row[7], "stored abort cleanup result"),
                outcome_unknown=bool(_zero_or_one(row[8])),
            )
        except (TypeError, ValueError) as exc:
            raise StateTamperedError("operation row has invalid authenticated fields") from exc
        stored_hmac = row[9]
        try:
            expected_hmac = self._row_hmac(record)
        except ValueError as exc:
            raise StateTamperedError("operation row has invalid authenticated state") from exc
        if not isinstance(stored_hmac, str) or not hmac.compare_digest(stored_hmac, expected_hmac):
            raise StateTamperedError("operation row HMAC mismatch")
        return record

    def _row_hmac(self, record: OperationRecord) -> str:
        _validate_record_semantics(record)
        payload = {
            "abort_origin_state": (
                record.abort_origin_state.value if record.abort_origin_state else None
            ),
            "abort_result_sha256": record.abort_result_sha256,
            "outcome_unknown": record.outcome_unknown,
            "request_sha256": record.request_sha256,
            "runtime_receipt_sha256": record.runtime_receipt_sha256,
            "state": record.state.value,
            "storage_commitment_sha256": record.storage_commitment_sha256,
            "tombstone_commitment_sha256": record.tombstone_commitment_sha256,
            "unit_identity_sha256": record.unit_identity_sha256,
        }
        return _hmac(self._hmac_key, payload)

    def _initialize_and_verify_schema(self) -> None:
        schema_hmac = _hmac(
            self._hmac_key,
            {"schema_version": _SCHEMA_VERSION, "fingerprint": STRUCTURAL_FINGERPRINT},
        )
        with self._transaction(verify_schema=False):
            self._connection.execute(
                "INSERT OR IGNORE INTO adapter_state_meta VALUES (1, ?, ?, ?)",
                (_SCHEMA_VERSION, STRUCTURAL_FINGERPRINT, schema_hmac),
            )
        self._verify_schema()

    def _verify_schema(self) -> None:
        rows = self._connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        tables = {
            name: " ".join(str(sql).split())
            for kind, name, sql in rows
            if kind == "table" and not str(name).startswith("sqlite_")
        }
        unexpected = [
            (kind, name)
            for kind, name, sql in rows
            if kind in {"trigger", "view"} or (kind == "index" and sql is not None)
        ]
        meta = self._connection.execute(
            "SELECT schema_version, structural_fingerprint, schema_hmac FROM adapter_state_meta"
        ).fetchall()
        expected_hmac = _hmac(
            self._hmac_key,
            {"schema_version": _SCHEMA_VERSION, "fingerprint": STRUCTURAL_FINGERPRINT},
        )
        if (
            tables != _EXPECTED_TABLES
            or unexpected
            or len(meta) != 1
            or meta[0][:2] != (_SCHEMA_VERSION, STRUCTURAL_FINGERPRINT)
            or not isinstance(meta[0][2], str)
            or not hmac.compare_digest(meta[0][2], expected_hmac)
        ):
            raise StateTamperedError("operation state schema authentication failed")

    class _Transaction:
        def __init__(self, owner: SqliteOperationState, *, verify_schema: bool) -> None:
            self._owner = owner
            self._verify_schema = verify_schema

        def __enter__(self) -> None:
            self._owner._lock.acquire()
            try:
                if self._verify_schema:
                    self._owner._verify_schema()
                self._owner._connection.execute("BEGIN IMMEDIATE")
            except Exception:
                self._owner._lock.release()
                raise

        def __exit__(self, exc_type: object, _exc: object, _tb: object) -> None:
            try:
                self._owner._connection.execute("COMMIT" if exc_type is None else "ROLLBACK")
            finally:
                self._owner._lock.release()

    def _transaction(self, *, verify_schema: bool = True) -> _Transaction:
        return self._Transaction(self, verify_schema=verify_schema)


def dataclass_replace(record: OperationRecord, **changes: object) -> OperationRecord:
    values: dict[str, object] = {
        "unit_identity_sha256": record.unit_identity_sha256,
        "request_sha256": record.request_sha256,
        "state": record.state,
        "runtime_receipt_sha256": record.runtime_receipt_sha256,
        "storage_commitment_sha256": record.storage_commitment_sha256,
        "tombstone_commitment_sha256": record.tombstone_commitment_sha256,
        "abort_origin_state": record.abort_origin_state,
        "abort_result_sha256": record.abort_result_sha256,
        "outcome_unknown": record.outcome_unknown,
    }
    values.update(changes)
    return OperationRecord(**values)  # type: ignore[arg-type]


def _prepare_private_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("operation state path must be absolute")
    if path.is_symlink():
        raise StateError("operation state path cannot be a symlink")
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise StateError("operation state directory is unsafe")
    mode = stat.S_IMODE(parent.stat().st_mode)
    if mode & 0o077:
        raise StateError("operation state directory must not be accessible by group or others")
    if path.exists():
        file_stat = path.stat()
        if not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) & 0o077:
            raise StateError("operation state file must be a private regular file")
    return path


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _optional_digest(value: object, name: str) -> str | None:
    return None if value is None else _digest(value, name)


def _zero_or_one(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1}:
        raise ValueError("outcome_unknown must be zero or one")
    return value


def _validate_record_semantics(record: OperationRecord) -> None:
    receipt_states = {
        OperationState.RECEIPT_DURABLE,
        OperationState.STORAGE_VERIFIED,
        OperationState.COMMITTED,
        OperationState.CLEANED,
    }
    storage_states = {
        OperationState.STORAGE_VERIFIED,
        OperationState.COMMITTED,
        OperationState.CLEANED,
    }
    if record.state is OperationState.ABORT_CLEANED:
        origin = record.abort_origin_state
        if origin not in {
            OperationState.ADMITTED,
            OperationState.RESERVED,
            OperationState.DISPATCHED,
            OperationState.RECEIPT_DURABLE,
            OperationState.STORAGE_VERIFIED,
        }:
            raise ValueError("abort cleanup origin is invalid")
        if record.abort_result_sha256 is None or record.tombstone_commitment_sha256 is None:
            raise ValueError("abort cleanup evidence is incomplete")
        requires_receipt = origin in {
            OperationState.RECEIPT_DURABLE,
            OperationState.STORAGE_VERIFIED,
        }
        requires_storage = origin is OperationState.STORAGE_VERIFIED
        if (record.runtime_receipt_sha256 is not None) != requires_receipt:
            raise ValueError("abort cleanup receipt evidence differs from origin")
        if (record.storage_commitment_sha256 is not None) != requires_storage:
            raise ValueError("abort cleanup storage evidence differs from origin")
        if record.outcome_unknown != (origin is OperationState.DISPATCHED):
            raise ValueError("abort cleanup dispatch outcome differs from origin")
        return
    if record.abort_origin_state is not None or record.abort_result_sha256 is not None:
        raise ValueError("non-abort operation retained abort evidence")
    if (record.runtime_receipt_sha256 is not None) != (record.state in receipt_states):
        raise ValueError("operation receipt evidence differs from state")
    if (record.storage_commitment_sha256 is not None) != (record.state in storage_states):
        raise ValueError("operation storage evidence differs from state")
    if (record.tombstone_commitment_sha256 is not None) != (record.state is OperationState.CLEANED):
        raise ValueError("operation tombstone evidence differs from state")
    if record.outcome_unknown and record.state is not OperationState.DISPATCHED:
        raise ValueError("outcome-unknown marker differs from state")


def _hmac(key: bytes, value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _identities(records: tuple[OperationRecord, ...], state: OperationState) -> tuple[str, ...]:
    return tuple(record.unit_identity_sha256 for record in records if record.state is state)


__all__ = (
    "STRUCTURAL_FINGERPRINT",
    "OperationRecord",
    "OperationState",
    "RecoveryReport",
    "SqliteOperationState",
    "StateError",
    "StateTamperedError",
)
