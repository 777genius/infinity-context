"""Authenticated provider-free SQLite store for strict cleanup-v4 preparation."""

# ruff: noqa: E501 - SQL statements remain auditable as complete clauses.

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Final, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Error,
    ManagedCleanupV3Operation,
    ManagedCleanupV3Page,
    ManagedCleanupV3StoreReceipt,
    canonical_bytes,
    commitment,
    digest,
)

from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
    close_strict_sqlite,
    create_strict_sqlite,
    exclusive_parent_lock,
    open_strict_sqlite,
    unlink_strict_sqlite_binding,
    verify_exact_schema,
    verify_strict_sqlite_binding,
    wipe,
)

_ROW_DOMAIN: Final = b"managed-cleanup-v4/sqlite-preparation-row/v1\0"
_STATE_DOMAIN: Final = b"managed-cleanup-v4/sqlite-preparation-state/v1\0"
_CLAIM_BATCH_SIZE: Final = 512
_TABLE_SQL: Final = {
    "sessions": """CREATE TABLE sessions(
      context_sha TEXT PRIMARY KEY, expected_operations INTEGER NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('active','prepared','committed')),
      terminal_sha TEXT, page_count INTEGER, receipt_json TEXT,
      state_mac TEXT NOT NULL
    ) STRICT""",
    "claims": """CREATE TABLE claims(
      context_sha TEXT NOT NULL REFERENCES sessions(context_sha) ON DELETE CASCADE,
      sequence INTEGER NOT NULL, operation_sha TEXT NOT NULL, row_mac TEXT NOT NULL,
      PRIMARY KEY(context_sha,sequence), UNIQUE(context_sha,operation_sha)
    ) STRICT""",
    "pages": """CREATE TABLE pages(
      context_sha TEXT NOT NULL REFERENCES sessions(context_sha) ON DELETE CASCADE,
      page_index INTEGER NOT NULL, payload_json TEXT NOT NULL, row_mac TEXT NOT NULL,
      PRIMARY KEY(context_sha,page_index)
    ) STRICT""",
}


def _fail(code: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_sqlite_preparation_{code}")


def _key(value: bytes) -> bytearray:
    if type(value) is not bytes or len(value) < 32:
        _fail("authentication_key_invalid")
    return bytearray(value)


def _json(value: object) -> str:
    return canonical_bytes(value).decode("ascii")


def _receipt(context: str, terminal: str, page_count: int) -> ManagedCleanupV3StoreReceipt:
    body = {
        "schema_version": "memory-comparison-paged-cleanup-store-receipt.v4",
        "context_sha256": context,
        "terminal_commitment_sha256": terminal,
        "page_count": page_count,
        "committed": True,
    }
    return ManagedCleanupV3StoreReceipt(
        context_sha256=context,
        terminal_commitment_sha256=terminal,
        page_count=page_count,
        committed=True,
        receipt_sha256=commitment("store-receipt/v4", body),
    )


def _decode_page(payload: str) -> ManagedCleanupV3Page:
    try:
        value = json.loads(payload)
        operations = []
        for raw in value["operations"]:
            item = dict(raw)
            item["ordered_source_ref_descriptor_sha256"] = tuple(
                item["ordered_source_ref_descriptor_sha256"]
            )
            item["ordered_fragment_descriptor_sha256"] = tuple(
                item["ordered_fragment_descriptor_sha256"]
            )
            operations.append(ManagedCleanupV3Operation(**item))
        value["operations"] = tuple(operations)
        page = ManagedCleanupV3Page(**value)
        page.__post_init__()
        return page
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ManagedCleanupV3Error(
            "managed_cleanup_v3_sqlite_preparation_authentication_invalid"
        ) from exc


@final
class SQLiteManagedCleanupV3PreparationStore:
    """Exact-idempotent implementation of ManagedCleanupV3StorePort."""

    def __init__(self, path: Path, db: sqlite3.Connection, fd: int, key: bytes) -> None:
        self._path, self._db, self._fd = path, db, fd
        self._key = _key(key)
        self._closed = False
        self._max_claim_batch_observed = 0
        self._claim_checkpoint_count = 0
        self._claim_batch_context: str | None = None
        self._claim_batch_processed = 0
        self._claim_batch_initial_count = 0
        self._claim_batch_inserted = 0

    @classmethod
    def create(
        cls, path: str | os.PathLike[str], *, authentication_key: bytes
    ) -> SQLiteManagedCleanupV3PreparationStore:
        target = Path(path)
        db, fd = create_strict_sqlite(target)
        try:
            db.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE sessions(
                  context_sha TEXT PRIMARY KEY, expected_operations INTEGER NOT NULL,
                  state TEXT NOT NULL CHECK(state IN ('active','prepared','committed')),
                  terminal_sha TEXT, page_count INTEGER, receipt_json TEXT,
                  state_mac TEXT NOT NULL
                ) STRICT;
                CREATE TABLE claims(
                  context_sha TEXT NOT NULL REFERENCES sessions(context_sha) ON DELETE CASCADE,
                  sequence INTEGER NOT NULL, operation_sha TEXT NOT NULL, row_mac TEXT NOT NULL,
                  PRIMARY KEY(context_sha,sequence), UNIQUE(context_sha,operation_sha)
                ) STRICT;
                CREATE TABLE pages(
                  context_sha TEXT NOT NULL REFERENCES sessions(context_sha) ON DELETE CASCADE,
                  page_index INTEGER NOT NULL, payload_json TEXT NOT NULL, row_mac TEXT NOT NULL,
                  PRIMARY KEY(context_sha,page_index)
                ) STRICT;
                COMMIT;
                """
            )
            result = cls(target, db, fd, authentication_key)
            result._verify_schema()
            return result
        except BaseException:
            try:
                with suppress(FileNotFoundError, StrictV4SQLiteFileError):
                    unlink_strict_sqlite_binding(target, fd)
            finally:
                close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open(
        cls, path: str | os.PathLike[str], *, authentication_key: bytes
    ) -> SQLiteManagedCleanupV3PreparationStore:
        target = Path(path)
        db, fd = open_strict_sqlite(target, readonly=False)
        try:
            result = cls(target, db, fd, authentication_key)
            result._verify_schema()
            result._authenticate_all()
            return result
        except BaseException:
            close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open_or_create(
        cls, path: str | os.PathLike[str], *, authentication_key: bytes
    ) -> SQLiteManagedCleanupV3PreparationStore:
        """Open durable state or safely recover an empty crash-partial bootstrap."""
        target = Path(path)
        with exclusive_parent_lock(target.parent):
            return cls._open_or_create_locked(target, authentication_key)

    @classmethod
    def _open_or_create_locked(
        cls, target: Path, authentication_key: bytes
    ) -> SQLiteManagedCleanupV3PreparationStore:
        if not target.exists() and not target.is_symlink():
            try:
                return cls.create(target, authentication_key=authentication_key)
            except StrictV4SQLiteFileError:
                pass
        try:
            return cls.open(target, authentication_key=authentication_key)
        except (sqlite3.OperationalError, StrictV4SQLiteFileError) as original:
            db, fd = open_strict_sqlite(target, readonly=False)
            try:
                tables = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
                ).fetchone()
                if tables is not None:
                    raise original
                unlink_strict_sqlite_binding(target, fd)
            finally:
                close_strict_sqlite(db, fd)
            return cls.create(target, authentication_key=authentication_key)

    def close(self) -> None:
        if not self._closed:
            self._rollback_claim_batch()
            self._closed = True
            wipe(self._key)
            close_strict_sqlite(self._db, self._fd)

    @property
    def max_claim_batch_observed(self) -> int:
        """Largest bounded claim batch retained by this adapter instance."""
        return self._max_claim_batch_observed

    @property
    def claim_checkpoint_count(self) -> int:
        """Number of durable bounded claim checkpoints written by this instance."""
        return self._claim_checkpoint_count

    def begin(self, *, context_sha256: str, expected_operation_count: int) -> _CleanupSession:
        self._ensure_open()
        context = digest(context_sha256)
        if type(expected_operation_count) is not int or expected_operation_count < 1:
            _fail("operation_count_invalid")
        with self._write():
            row = self._session(context)
            if row is None:
                self._insert_state(context, expected_operation_count, "active", None, None, None)
            else:
                self._authenticate_state(context, row)
                if int(row[0]) != expected_operation_count:
                    _fail("begin_conflict")
        return _CleanupSession(self, context)

    def _state_payload(
        self,
        context: str,
        expected: int,
        state: str,
        terminal: object,
        pages: object,
        receipt: object,
    ) -> dict[str, object]:
        return {
            "context_sha": context,
            "expected_operations": expected,
            "state": state,
            "terminal_sha": terminal,
            "page_count": pages,
            "receipt_json": receipt,
        }

    def _mac(self, domain: bytes, value: object) -> str:
        return hmac.new(self._key, domain + canonical_bytes(value), hashlib.sha256).hexdigest()

    def _insert_state(
        self,
        context: str,
        expected: int,
        state: str,
        terminal: object,
        pages: object,
        receipt: object,
    ) -> None:
        payload = self._state_payload(context, expected, state, terminal, pages, receipt)
        self._db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?)",
            (context, expected, state, terminal, pages, receipt, self._mac(_STATE_DOMAIN, payload)),
        )

    def _update_state(
        self,
        context: str,
        expected: int,
        state: str,
        terminal: object,
        pages: object,
        receipt: object,
    ) -> None:
        payload = self._state_payload(context, expected, state, terminal, pages, receipt)
        self._db.execute(
            "UPDATE sessions SET expected_operations=?,state=?,terminal_sha=?,page_count=?,"
            "receipt_json=?,state_mac=? WHERE context_sha=?",
            (expected, state, terminal, pages, receipt, self._mac(_STATE_DOMAIN, payload), context),
        )

    def _session(self, context: str) -> tuple[object, ...] | None:
        return self._db.execute(
            "SELECT expected_operations,state,terminal_sha,page_count,receipt_json,state_mac "
            "FROM sessions WHERE context_sha=?",
            (context,),
        ).fetchone()

    def _authenticate_state(self, context: str, row: tuple[object, ...]) -> str:
        payload = self._state_payload(context, int(row[0]), str(row[1]), row[2], row[3], row[4])
        if not hmac.compare_digest(str(row[5]), self._mac(_STATE_DOMAIN, payload)):
            _fail("authentication_invalid")
        return str(row[1])

    def _row_mac(self, kind: str, context: str, index: int, value: str) -> str:
        return self._mac(
            _ROW_DOMAIN, {"kind": kind, "context_sha": context, "index": index, "value": value}
        )

    def _check_row(self, kind: str, context: str, index: int, value: str, mac: str) -> None:
        if not hmac.compare_digest(mac, self._row_mac(kind, context, index, value)):
            _fail("authentication_invalid")

    def _claims_for_range(
        self, context: str, start_sequence: int, end_sequence_exclusive: int
    ) -> tuple[tuple[int, str], ...]:
        size = end_sequence_exclusive - start_sequence
        if not 1 <= size <= _CLAIM_BATCH_SIZE:
            _fail("claim_batch_invalid")
        rows = self._db.execute(
            "SELECT sequence,operation_sha,row_mac FROM claims "
            "WHERE context_sha=? AND sequence>=? AND sequence<? ORDER BY sequence LIMIT ?",
            (context, start_sequence, end_sequence_exclusive, _CLAIM_BATCH_SIZE),
        ).fetchall()
        self._max_claim_batch_observed = max(self._max_claim_batch_observed, len(rows))
        if len(rows) != size:
            _fail("claim_coverage_invalid")
        result: list[tuple[int, str]] = []
        for offset, (sequence, operation, mac) in enumerate(rows):
            expected = start_sequence + offset
            if int(sequence) != expected:
                _fail("claim_coverage_invalid")
            value = str(operation)
            self._check_row("claim", context, expected, value, str(mac))
            result.append((expected, value))
        return tuple(result)

    def _authenticate_all(self) -> None:
        self._ensure_open()
        for item in self._db.execute(
            "SELECT context_sha,expected_operations,state,terminal_sha,page_count,receipt_json,state_mac "
            "FROM sessions ORDER BY context_sha"
        ):
            context = str(item[0])
            state = self._authenticate_state(context, tuple(item[1:]))
            for sequence, operation, mac in self._db.execute(
                "SELECT sequence,operation_sha,row_mac FROM claims WHERE context_sha=? ORDER BY sequence",
                (context,),
            ):
                self._check_row("claim", context, int(sequence), str(operation), str(mac))
            for index, payload, mac in self._db.execute(
                "SELECT page_index,payload_json,row_mac FROM pages WHERE context_sha=? ORDER BY page_index",
                (context,),
            ):
                self._check_row("page", context, int(index), str(payload), str(mac))
            if state == "committed":
                self._validate_committed(context, tuple(item[1:]))

    def _verify_schema(self) -> None:
        verify_exact_schema(self._db, _TABLE_SQL)

    def _validate_committed(self, context: str, row: tuple[object, ...]) -> None:
        self._verify_schema()
        expected_operations = int(row[0])
        if row[2] is None or row[3] is None or row[4] is None:
            _fail("committed_coverage_invalid")
        try:
            receipt = ManagedCleanupV3StoreReceipt(**json.loads(str(row[4])))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ManagedCleanupV3Error(
                "managed_cleanup_v3_sqlite_preparation_authentication_invalid"
            ) from exc
        receipt.__post_init__()
        page_count = 0
        seen = 0
        for index, payload, mac in self._db.execute(
            "SELECT page_index,payload_json,row_mac FROM pages "
            "WHERE context_sha=? ORDER BY page_index",
            (context,),
        ):
            if int(index) != page_count:
                _fail("committed_coverage_invalid")
            encoded = str(payload)
            self._check_row("page", context, page_count, encoded, str(mac))
            page = _decode_page(encoded)
            if page.context_sha256 != context or page.start_sequence != seen:
                _fail("committed_coverage_invalid")
            claims = self._claims_for_range(context, seen, page.end_sequence_exclusive)
            if tuple(value for _sequence, value in claims) != tuple(
                operation.operation_sha256 for operation in page.operations
            ):
                _fail("claim_page_mismatch")
            seen = page.end_sequence_exclusive
            page_count += 1
        claim_count = self._db.execute(
            "SELECT COUNT(*) FROM claims WHERE context_sha=?", (context,)
        ).fetchone()
        if (
            seen != expected_operations
            or claim_count != (expected_operations,)
            or page_count != int(row[3])
            or receipt.context_sha256 != context
            or receipt.terminal_commitment_sha256 != row[2]
            or receipt.page_count != page_count
        ):
            _fail("committed_coverage_invalid")

    @contextmanager
    def _write(self) -> Iterator[None]:
        self._commit_claim_batch()
        self._ensure_open()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._verify_schema()
            yield
        except BaseException:
            self._db.rollback()
            raise
        else:
            try:
                self._ensure_open()
                self._db.commit()
                self._ensure_open()
            except BaseException:
                self._db.rollback()
                raise

    def _begin_claim_batch(self, context: str) -> None:
        if self._claim_batch_context is not None:
            if self._claim_batch_context != context:
                _fail("claim_batch_context_invalid")
            return
        self._ensure_open()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._verify_schema()
            row = self._db.execute(
                "SELECT COUNT(*) FROM claims WHERE context_sha=?", (context,)
            ).fetchone()
            if row is None:
                _fail("claim_coverage_invalid")
            self._claim_batch_context = context
            self._claim_batch_processed = 0
            self._claim_batch_initial_count = int(row[0])
            self._claim_batch_inserted = 0
        except BaseException:
            self._db.rollback()
            self._reset_claim_batch()
            raise

    def _advance_claim_batch(self) -> None:
        self._claim_batch_processed += 1
        self._max_claim_batch_observed = max(
            self._max_claim_batch_observed, self._claim_batch_processed
        )
        if self._claim_batch_processed >= _CLAIM_BATCH_SIZE:
            self._commit_claim_batch()

    def _commit_claim_batch(self) -> None:
        if self._claim_batch_context is None:
            return
        try:
            self._ensure_open()
            self._db.commit()
            self._claim_checkpoint_count += 1
            self._ensure_open()
        except BaseException:
            self._db.rollback()
            raise
        finally:
            self._reset_claim_batch()

    def _rollback_claim_batch(self) -> None:
        if self._claim_batch_context is None:
            return
        try:
            self._db.rollback()
        finally:
            self._reset_claim_batch()

    def _reset_claim_batch(self) -> None:
        self._claim_batch_context = None
        self._claim_batch_processed = 0
        self._claim_batch_initial_count = 0
        self._claim_batch_inserted = 0

    def _ensure_open(self) -> None:
        if self._closed:
            _fail("closed")
        verify_strict_sqlite_binding(self._path, self._fd)


@final
class _CleanupSession:
    def __init__(self, store: SQLiteManagedCleanupV3PreparationStore, context: str) -> None:
        self._store, self._context = store, context

    def claim(self, *, sequence: int, operation_sha256: str) -> None:
        operation = digest(operation_sha256)
        if type(sequence) is not int or sequence < 0:
            _fail("claim_invalid")
        self._store._begin_claim_batch(self._context)
        try:
            row = self._require_session()
            if sequence >= int(row[0]):
                _fail("claim_invalid")
            existing = self._store._db.execute(
                "SELECT operation_sha,row_mac FROM claims WHERE context_sha=? AND sequence=?",
                (self._context, sequence),
            ).fetchone()
            if existing:
                self._store._check_row(
                    "claim", self._context, sequence, str(existing[0]), str(existing[1])
                )
                if str(existing[0]) != operation:
                    _fail("claim_conflict")
                self._store._advance_claim_batch()
                return
            if str(row[1]) != "active":
                _fail("committed")
            next_sequence = (
                self._store._claim_batch_initial_count + self._store._claim_batch_inserted
            )
            if sequence != next_sequence:
                _fail("claim_gap")
            try:
                self._store._db.execute(
                    "INSERT INTO claims VALUES(?,?,?,?)",
                    (
                        self._context,
                        sequence,
                        operation,
                        self._store._row_mac("claim", self._context, sequence, operation),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ManagedCleanupV3Error(
                    "managed_cleanup_v3_sqlite_preparation_duplicate_operation"
                ) from exc
            self._store._claim_batch_inserted += 1
            self._store._advance_claim_batch()
        except BaseException:
            self._store._rollback_claim_batch()
            raise

    def append(self, page: ManagedCleanupV3Page) -> None:
        if type(page) is not ManagedCleanupV3Page:
            _fail("page_invalid")
        page.__post_init__()
        if page.context_sha256 != self._context:
            _fail("page_invalid")
        payload = _json(page.payload())
        with self._store._write():
            row = self._require_session()
            existing = self._store._db.execute(
                "SELECT payload_json,row_mac FROM pages WHERE context_sha=? AND page_index=?",
                (self._context, page.page_index),
            ).fetchone()
            if existing:
                self._store._check_row(
                    "page", self._context, page.page_index, str(existing[0]), str(existing[1])
                )
                if str(existing[0]) != payload:
                    _fail("page_conflict")
                return
            if str(row[1]) != "active":
                _fail("committed")
            previous = self._store._db.execute(
                "SELECT page_index,payload_json FROM pages WHERE context_sha=? "
                "ORDER BY page_index DESC LIMIT 1",
                (self._context,),
            ).fetchone()
            expected_index = 0 if previous is None else int(previous[0]) + 1
            expected_start = (
                0
                if previous is None
                else int(json.loads(str(previous[1]))["end_sequence_exclusive"])
            )
            if page.page_index != expected_index or page.start_sequence != expected_start:
                _fail("page_gap")
            self._store._db.execute(
                "INSERT INTO pages VALUES(?,?,?,?)",
                (
                    self._context,
                    page.page_index,
                    payload,
                    self._store._row_mac("page", self._context, page.page_index, payload),
                ),
            )

    def prepare(self, authority: ManagedCleanupV3Authority) -> None:
        if type(authority) is not ManagedCleanupV3Authority:
            _fail("authority_invalid")
        authority.__post_init__()
        if authority.context_sha256 != self._context:
            _fail("authority_invalid")
        with self._store._write():
            row = self._require_session()
            if str(row[1]) in {"prepared", "committed"}:
                if row[2] != authority.terminal_commitment_sha256:
                    _fail("prepare_conflict")
                return
            page_count = 0
            expected_start = 0
            for index, payload, mac in self._store._db.execute(
                "SELECT page_index,payload_json,row_mac FROM pages "
                "WHERE context_sha=? ORDER BY page_index",
                (self._context,),
            ):
                if int(index) != page_count or page_count >= authority.page_count:
                    _fail("page_coverage_invalid")
                encoded = str(payload)
                self._store._check_row("page", self._context, page_count, encoded, str(mac))
                body = json.loads(encoded)
                operations = body["operations"]
                end = int(body["end_sequence_exclusive"])
                if (
                    body["start_sequence"] != expected_start
                    or not isinstance(operations, list)
                    or not operations
                    or len(operations) > _CLAIM_BATCH_SIZE
                    or end - expected_start != len(operations)
                ):
                    _fail("page_gap")
                claims = self._store._claims_for_range(self._context, expected_start, end)
                if tuple(value for _sequence, value in claims) != tuple(
                    str(operation["operation_sha256"]) for operation in operations
                ):
                    _fail("claim_page_mismatch")
                if str(body["page_sha256"]) != authority.ordered_page_sha256[page_count]:
                    _fail("authority_invalid")
                expected_start = end
                page_count += 1
            if page_count != authority.page_count or expected_start != authority.operation_count:
                _fail("authority_invalid")
            self._store._update_state(
                self._context,
                int(row[0]),
                "prepared",
                authority.terminal_commitment_sha256,
                authority.page_count,
                None,
            )

    def commit(self, authority: ManagedCleanupV3Authority) -> ManagedCleanupV3StoreReceipt:
        self.prepare(authority)
        receipt = _receipt(
            self._context, authority.terminal_commitment_sha256, authority.page_count
        )
        encoded = _json(
            receipt.__dict__
            if hasattr(receipt, "__dict__")
            else {name: getattr(receipt, name) for name in receipt.__dataclass_fields__}
        )
        with self._store._write():
            row = self._require_session()
            if str(row[1]) == "committed":
                if row[2] != authority.terminal_commitment_sha256 or row[4] != encoded:
                    _fail("commit_conflict")
                self._store._validate_committed(self._context, row)
                return receipt
            if str(row[1]) != "prepared":
                _fail("prepare_missing")
            self._store._update_state(
                self._context,
                int(row[0]),
                "committed",
                authority.terminal_commitment_sha256,
                authority.page_count,
                encoded,
            )
            observed = self._require_session()
            if str(observed[1]) != "committed" or observed[4] != encoded:
                _fail("commit_readback_invalid")
            self._store._validate_committed(self._context, observed)
        return receipt

    def readback(self) -> ManagedCleanupV3StoreReceipt | None:
        self._store._ensure_open()
        row = self._store._session(self._context)
        if row is None:
            return None
        state = self._store._authenticate_state(self._context, row)
        if state != "committed":
            return None
        self._store._validate_committed(self._context, row)
        try:
            value = json.loads(str(row[4]))
            receipt = ManagedCleanupV3StoreReceipt(**value)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ManagedCleanupV3Error(
                "managed_cleanup_v3_sqlite_preparation_authentication_invalid"
            ) from exc
        receipt.__post_init__()
        self._store._ensure_open()
        return receipt

    def abort(self) -> None:
        self._store._rollback_claim_batch()
        with self._store._write():
            row = self._store._session(self._context)
            if row is None:
                return
            if self._store._authenticate_state(self._context, row) != "committed":
                self._store._db.execute(
                    "DELETE FROM sessions WHERE context_sha=?", (self._context,)
                )

    def _require_session(self) -> tuple[object, ...]:
        row = self._store._session(self._context)
        if row is None:
            _fail("session_missing")
        self._store._authenticate_state(self._context, row)
        return row


def iter_committed_pages(
    path: str | os.PathLike[str],
    *,
    context_sha256: str,
    terminal_commitment_sha256: str,
    authentication_key: bytes,
) -> Iterator[ManagedCleanupV3Page]:
    """Yield authenticated committed pages one bounded page at a time from a true RO fd."""
    context, terminal = digest(context_sha256), digest(terminal_commitment_sha256)
    key = _key(authentication_key)
    target = Path(path)
    db, fd = open_strict_sqlite(target, readonly=True)
    try:
        verify_exact_schema(db, _TABLE_SQL)
        row = db.execute(
            "SELECT expected_operations,state,terminal_sha,page_count,receipt_json,state_mac "
            "FROM sessions WHERE context_sha=?",
            (context,),
        ).fetchone()
        if row is None:
            _fail("commit_missing")
        state_payload = {
            "context_sha": context,
            "expected_operations": int(row[0]),
            "state": str(row[1]),
            "terminal_sha": row[2],
            "page_count": row[3],
            "receipt_json": row[4],
        }
        expected_mac = hmac.new(
            key, _STATE_DOMAIN + canonical_bytes(state_payload), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(str(row[5]), expected_mac):
            _fail("authentication_invalid")
        if str(row[1]) != "committed":
            _fail("commit_missing")
        if row[2] != terminal or type(row[3]) is not int:
            _fail("authentication_invalid")
        receipt = ManagedCleanupV3StoreReceipt(**json.loads(str(row[4])))
        receipt.__post_init__()
        if receipt.context_sha256 != context or receipt.terminal_commitment_sha256 != terminal:
            _fail("authentication_invalid")
        seen = 0
        cursor = db.execute(
            "SELECT page_index,payload_json,row_mac FROM pages WHERE context_sha=? ORDER BY page_index",
            (context,),
        )
        for expected_index, (index, payload, mac) in enumerate(cursor):
            row_value = {
                "kind": "page",
                "context_sha": context,
                "index": int(index),
                "value": str(payload),
            }
            expected_row_mac = hmac.new(
                key, _ROW_DOMAIN + canonical_bytes(row_value), hashlib.sha256
            ).hexdigest()
            if int(index) != expected_index or not hmac.compare_digest(str(mac), expected_row_mac):
                _fail("authentication_invalid")
            page = _decode_page(str(payload))
            if page.context_sha256 != context or page.start_sequence != seen:
                _fail("page_gap")
            verify_strict_sqlite_binding(target, fd)
            claim_rows = db.execute(
                "SELECT sequence,operation_sha,row_mac FROM claims "
                "WHERE context_sha=? AND sequence>=? AND sequence<? "
                "ORDER BY sequence LIMIT ?",
                (context, seen, page.end_sequence_exclusive, _CLAIM_BATCH_SIZE),
            ).fetchall()
            if len(claim_rows) != len(page.operations):
                _fail("claim_coverage_invalid")
            for offset, (sequence, operation, claim_mac) in enumerate(claim_rows):
                expected_sequence = seen + offset
                claim_value = str(operation)
                expected_claim_mac = hmac.new(
                    key,
                    _ROW_DOMAIN
                    + canonical_bytes(
                        {
                            "kind": "claim",
                            "context_sha": context,
                            "index": expected_sequence,
                            "value": claim_value,
                        }
                    ),
                    hashlib.sha256,
                ).hexdigest()
                if (
                    int(sequence) != expected_sequence
                    or not hmac.compare_digest(str(claim_mac), expected_claim_mac)
                    or claim_value != page.operations[offset].operation_sha256
                ):
                    _fail("claim_page_mismatch")
            seen = page.end_sequence_exclusive
            verify_strict_sqlite_binding(target, fd)
            yield page
        if seen != int(row[0]) or receipt.page_count == 0:
            _fail("page_coverage_invalid")
        actual_count = db.execute(
            "SELECT COUNT(*) FROM pages WHERE context_sha=?", (context,)
        ).fetchone()
        if actual_count != (receipt.page_count,):
            _fail("page_coverage_invalid")
        claim_count = db.execute(
            "SELECT COUNT(*) FROM claims WHERE context_sha=?", (context,)
        ).fetchone()
        if claim_count != (int(row[0]),):
            _fail("claim_coverage_invalid")
        verify_strict_sqlite_binding(target, fd)
    finally:
        wipe(key)
        close_strict_sqlite(db, fd)


__all__ = ("SQLiteManagedCleanupV3PreparationStore", "iter_committed_pages")
