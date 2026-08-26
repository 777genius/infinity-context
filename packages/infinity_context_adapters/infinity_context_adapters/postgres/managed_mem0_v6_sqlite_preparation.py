"""Authenticated provider-free SQLite staging for strict managed-Mem0 v6."""

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

from infinity_context_core.ports.managed_mem0_v6_manifest_contracts import (
    MANAGED_MEM0_V6_MAX_PAGE_COUNT,
    TERMINAL_COMMITMENT_DOMAIN,
    ManagedMem0V6ManifestError,
    ManagedMem0V6ManifestPage,
    ManagedMem0V6PagedManifestAuthority,
    ManagedMem0V6PageStoreCommitReceipt,
    ManagedMem0V6UniquenessReceipt,
    authority_body,
    canonical_bytes,
    domain_sha256,
    merkle_root,
    require_sha256,
    store_receipt_sha256,
    uniqueness_receipt_sha256,
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

_ROW_DOMAIN: Final = b"managed-mem0-v6/sqlite-preparation-row/v1\0"
_STATE_DOMAIN: Final = b"managed-mem0-v6/sqlite-preparation-state/v1\0"
_CLAIM_BATCH_SIZE: Final = 512
_TABLE_SQL: Final = {
    "sessions": """CREATE TABLE sessions(
      context_sha TEXT PRIMARY KEY, expected_operations INTEGER NOT NULL,
      expected_pages INTEGER,
      state TEXT NOT NULL CHECK(state IN ('active','prepared','committed')),
      uniqueness_receipt_json TEXT, terminal_sha TEXT, store_receipt_json TEXT,
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
    raise ManagedMem0V6ManifestError(f"managed_mem0_v6_sqlite_preparation_{code}")


def _key(value: bytes) -> bytearray:
    if type(value) is not bytes or len(value) < 32:
        _fail("authentication_key_invalid")
    return bytearray(value)


def _json(value: object) -> str:
    return canonical_bytes(value).decode("ascii")


@final
class SQLiteManagedMem0V6PreparationStore:
    """One narrow adapter implementing page-store and uniqueness-factory ports."""

    def __init__(self, path: Path, db: sqlite3.Connection, fd: int, key: bytes) -> None:
        self._path = path
        self._db = db
        self._fd = fd
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
    ) -> SQLiteManagedMem0V6PreparationStore:
        target = Path(path)
        db, fd = create_strict_sqlite(target)
        try:
            db.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE sessions(
                  context_sha TEXT PRIMARY KEY, expected_operations INTEGER NOT NULL,
                  expected_pages INTEGER,
                  state TEXT NOT NULL CHECK(state IN ('active','prepared','committed')),
                  uniqueness_receipt_json TEXT, terminal_sha TEXT, store_receipt_json TEXT,
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
    ) -> SQLiteManagedMem0V6PreparationStore:
        target = Path(path)
        db, fd = open_strict_sqlite(target, readonly=False)
        try:
            store = cls(target, db, fd, authentication_key)
            store._verify_schema()
            store._authenticate_all()
            return store
        except BaseException:
            close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open_or_create(
        cls, path: str | os.PathLike[str], *, authentication_key: bytes
    ) -> SQLiteManagedMem0V6PreparationStore:
        """Open durable state or safely recover an empty crash-partial bootstrap."""
        target = Path(path)
        with exclusive_parent_lock(target.parent):
            return cls._open_or_create_locked(target, authentication_key)

    @classmethod
    def _open_or_create_locked(
        cls, target: Path, authentication_key: bytes
    ) -> SQLiteManagedMem0V6PreparationStore:
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

    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]:
        """Read one HMAC-authenticated ordered operation page from a committed A1."""

        self._ensure_open()
        context = require_sha256(manifest_context_sha256)
        if (
            type(start_sequence) is not int
            or start_sequence < 0
            or start_sequence % _CLAIM_BATCH_SIZE != 0
        ):
            _fail("claim_page_invalid")
        row = self._session(context)
        if row is None or self._authenticate_state(context, row) != "committed":
            _fail("committed_session_missing")
        operation_count = int(row[0])
        if start_sequence >= operation_count:
            _fail("claim_page_invalid")
        end = min(start_sequence + _CLAIM_BATCH_SIZE, operation_count)
        claims = self._claims_for_range(context, start_sequence, end)
        self._ensure_open()
        return tuple(value for _sequence, value in claims)

    def begin(
        self,
        *,
        manifest_context_sha256: str,
        expected_operation_count: int | None = None,
        expected_page_count: int | None = None,
    ) -> _A1Session:
        """Begin either port; repeated begins must agree with already-bound counts."""
        self._ensure_open()
        context = require_sha256(manifest_context_sha256)
        if (expected_operation_count is None) == (expected_page_count is None):
            _fail("begin_invalid")
        if expected_operation_count is not None and (
            type(expected_operation_count) is not int or expected_operation_count < 1
        ):
            _fail("operation_count_invalid")
        if expected_page_count is not None and (
            type(expected_page_count) is not int
            or not 1 <= expected_page_count <= MANAGED_MEM0_V6_MAX_PAGE_COUNT
        ):
            _fail("page_count_invalid")
        with self._write():
            row = self._session(context)
            if row is None:
                operations = expected_operation_count or 0
                pages = expected_page_count
                self._insert_state(context, operations, pages, "active", None, None, None)
            else:
                state = self._authenticate_state(context, row)
                operations, pages = int(row[0]), row[1]
                if expected_operation_count is not None:
                    if operations not in (0, expected_operation_count):
                        _fail("begin_conflict")
                    operations = expected_operation_count
                if expected_page_count is not None:
                    if pages is not None and int(pages) != expected_page_count:
                        _fail("begin_conflict")
                    pages = expected_page_count
                self._update_state(
                    context,
                    operations,
                    None if pages is None else int(pages),
                    state,
                    row[3],
                    row[4],
                    row[5],
                )
        return _A1Session(self, context)

    def _session(self, context: str) -> tuple[object, ...] | None:
        return self._db.execute(
            "SELECT expected_operations,expected_pages,state,uniqueness_receipt_json,"
            "terminal_sha,store_receipt_json,state_mac FROM sessions WHERE context_sha=?",
            (context,),
        ).fetchone()

    def _state_payload(
        self,
        context: str,
        operations: int,
        pages: int | None,
        state: str,
        unique: object,
        terminal: object,
        receipt: object,
    ) -> dict[str, object]:
        return {
            "context_sha": context,
            "expected_operations": operations,
            "expected_pages": pages,
            "state": state,
            "uniqueness_receipt_json": unique,
            "terminal_sha": terminal,
            "store_receipt_json": receipt,
        }

    def _mac(self, domain: bytes, value: object) -> str:
        return hmac.new(self._key, domain + canonical_bytes(value), hashlib.sha256).hexdigest()

    def _insert_state(
        self,
        context: str,
        operations: int,
        pages: int | None,
        state: str,
        unique: object,
        terminal: object,
        receipt: object,
    ) -> None:
        payload = self._state_payload(context, operations, pages, state, unique, terminal, receipt)
        self._db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
            (
                context,
                operations,
                pages,
                state,
                unique,
                terminal,
                receipt,
                self._mac(_STATE_DOMAIN, payload),
            ),
        )

    def _update_state(
        self,
        context: str,
        operations: int,
        pages: int | None,
        state: str,
        unique: object,
        terminal: object,
        receipt: object,
    ) -> None:
        payload = self._state_payload(context, operations, pages, state, unique, terminal, receipt)
        self._db.execute(
            "UPDATE sessions SET expected_operations=?,expected_pages=?,state=?,"
            "uniqueness_receipt_json=?,terminal_sha=?,store_receipt_json=?,state_mac=? "
            "WHERE context_sha=?",
            (
                operations,
                pages,
                state,
                unique,
                terminal,
                receipt,
                self._mac(_STATE_DOMAIN, payload),
                context,
            ),
        )

    def _authenticate_state(self, context: str, row: tuple[object, ...]) -> str:
        payload = self._state_payload(
            context,
            int(row[0]),
            None if row[1] is None else int(row[1]),
            str(row[2]),
            row[3],
            row[4],
            row[5],
        )
        if not hmac.compare_digest(str(row[6]), self._mac(_STATE_DOMAIN, payload)):
            _fail("authentication_invalid")
        return str(row[2])

    def _authenticate_all(self) -> None:
        self._ensure_open()
        for row in self._db.execute(
            "SELECT context_sha,expected_operations,expected_pages,state,uniqueness_receipt_json,"
            "terminal_sha,store_receipt_json,state_mac FROM sessions ORDER BY context_sha"
        ):
            context = str(row[0])
            state = self._authenticate_state(context, tuple(row[1:]))
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
                self._validate_committed(context, tuple(row[1:]))

    def _verify_schema(self) -> None:
        verify_exact_schema(self._db, _TABLE_SQL)

    def _validate_committed(self, context: str, row: tuple[object, ...]) -> None:
        self._verify_schema()
        expected_operations = int(row[0])
        expected_pages = row[1]
        if expected_pages is None or row[3] is None or row[4] is None or row[5] is None:
            _fail("committed_coverage_invalid")
        try:
            unique = ManagedMem0V6UniquenessReceipt(**json.loads(str(row[3])))
            receipt = ManagedMem0V6PageStoreCommitReceipt(**json.loads(str(row[5])))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ManagedMem0V6ManifestError(
                "managed_mem0_v6_sqlite_preparation_authentication_invalid"
            ) from exc
        unique.__post_init__()
        receipt.__post_init__()
        commitments: list[str] = []
        seen = 0
        profile_id: str | None = None
        for index, payload, mac in self._db.execute(
            "SELECT page_index,payload_json,row_mac FROM pages "
            "WHERE context_sha=? ORDER BY page_index",
            (context,),
        ):
            page_index = int(index)
            if page_index != len(commitments):
                _fail("committed_coverage_invalid")
            encoded = str(payload)
            self._check_row("page", context, page_index, encoded, str(mac))
            value = json.loads(encoded)
            value["ordered_operation_sha256"] = tuple(value["ordered_operation_sha256"])
            page = ManagedMem0V6ManifestPage(**value)
            if page.start_sequence != seen or page.manifest_context_sha256 != context:
                _fail("committed_coverage_invalid")
            if profile_id is None:
                profile_id = page.profile_id
            elif profile_id != page.profile_id:
                _fail("committed_coverage_invalid")
            claims = self._claims_for_range(context, seen, page.end_sequence_exclusive)
            if tuple(value for _sequence, value in claims) != page.ordered_operation_sha256:
                _fail("claim_page_mismatch")
            commitments.append(page.page_commitment_sha256)
            seen = page.end_sequence_exclusive
        claim_count = self._db.execute(
            "SELECT COUNT(*) FROM claims WHERE context_sha=?", (context,)
        ).fetchone()
        if (
            profile_id is None
            or seen != expected_operations
            or claim_count != (expected_operations,)
            or len(commitments) != int(expected_pages)
        ):
            _fail("committed_coverage_invalid")
        root = merkle_root(tuple(commitments))
        if (
            unique.manifest_context_sha256 != context
            or unique.operation_count != expected_operations
            or unique.ordered_operations_root_sha256 != root
            or receipt.manifest_context_sha256 != context
            or receipt.page_count != int(expected_pages)
            or receipt.authority_terminal_commitment_sha256 != row[4]
        ):
            _fail("committed_coverage_invalid")
        body = authority_body(
            profile_id=profile_id,
            manifest_context_sha256=context,
            operation_count=expected_operations,
            ordered_page_commitment_sha256=tuple(commitments),
            pages_merkle_root_sha256=root,
            uniqueness_receipt_sha256_value=unique.receipt_sha256,
        )
        if domain_sha256(TERMINAL_COMMITMENT_DOMAIN, body) != row[4]:
            _fail("committed_terminal_invalid")

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
class _A1Session:
    def __init__(self, store: SQLiteManagedMem0V6PreparationStore, context: str) -> None:
        self._store, self._context = store, context

    def claim(self, *, sequence: int, operation_sha256: str) -> None:
        operation = require_sha256(operation_sha256)
        if type(sequence) is not int or sequence < 0:
            _fail("claim_invalid")
        self._store._begin_claim_batch(self._context)
        try:
            row = self._require_active_or_committed()
            expected = int(row[0])
            if expected < 1 or sequence >= expected:
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
            if str(row[2]) != "active":
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
                raise ManagedMem0V6ManifestError(
                    "managed_mem0_v6_sqlite_preparation_duplicate_operation"
                ) from exc
            self._store._claim_batch_inserted += 1
            self._store._advance_claim_batch()
        except BaseException:
            self._store._rollback_claim_batch()
            raise

    def append(self, page: ManagedMem0V6ManifestPage) -> None:
        if type(page) is not ManagedMem0V6ManifestPage:
            _fail("page_invalid")
        page.__post_init__()
        if page.manifest_context_sha256 != self._context:
            _fail("page_invalid")
        payload = _json(
            page.__dict__
            if hasattr(page, "__dict__")
            else {
                name: (list(value) if isinstance(value, tuple) else value)
                for name in page.__dataclass_fields__
                for value in (getattr(page, name),)
            }
        )
        with self._store._write():
            row = self._require_active_or_committed()
            expected_pages = row[1]
            if expected_pages is None or page.page_index >= int(expected_pages):
                _fail("page_invalid")
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
            if str(row[2]) != "active":
                _fail("committed")
            page_count = self._store._db.execute(
                "SELECT COUNT(*) FROM pages WHERE context_sha=?", (self._context,)
            ).fetchone()
            if page_count != (page.page_index,):
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

    def finalize(
        self, *, operation_count: int, ordered_operations_root_sha256: str
    ) -> ManagedMem0V6UniquenessReceipt:
        root = require_sha256(ordered_operations_root_sha256)
        with self._store._write():
            row = self._require_active_or_committed()
            if operation_count != int(row[0]):
                _fail("claim_coverage_invalid")
            if row[1] is None:
                _fail("page_coverage_invalid")
            commitments: list[str] = []
            seen = 0
            for page_index, payload, mac in self._store._db.execute(
                "SELECT page_index,payload_json,row_mac FROM pages "
                "WHERE context_sha=? ORDER BY page_index",
                (self._context,),
            ):
                index = int(page_index)
                if index != len(commitments):
                    _fail("page_coverage_invalid")
                encoded = str(payload)
                self._store._check_row("page", self._context, index, encoded, str(mac))
                page = json.loads(encoded)
                operations = tuple(str(value) for value in page["ordered_operation_sha256"])
                end = seen + len(operations)
                if (
                    page["start_sequence"] != seen
                    or page["end_sequence_exclusive"] != end
                    or not operations
                    or len(operations) > _CLAIM_BATCH_SIZE
                ):
                    _fail("page_coverage_invalid")
                claims = self._store._claims_for_range(self._context, seen, end)
                if tuple(value for _sequence, value in claims) != operations:
                    _fail("claim_page_mismatch")
                commitments.append(str(page["page_commitment_sha256"]))
                seen = end
            if (
                seen != operation_count
                or len(commitments) != int(row[1])
                or merkle_root(tuple(commitments)) != root
            ):
                _fail("claim_coverage_invalid")
            receipt = ManagedMem0V6UniquenessReceipt(
                manifest_context_sha256=self._context,
                operation_count=operation_count,
                ordered_operations_root_sha256=root,
                receipt_sha256=uniqueness_receipt_sha256(self._context, operation_count, root),
            )
            encoded = _json({name: getattr(receipt, name) for name in receipt.__dataclass_fields__})
            if row[3] is not None and str(row[3]) != encoded:
                _fail("uniqueness_conflict")
            self._store._update_state(
                self._context,
                int(row[0]),
                None if row[1] is None else int(row[1]),
                str(row[2]),
                encoded,
                row[4],
                row[5],
            )
            return receipt

    def prepare(self, authority: ManagedMem0V6PagedManifestAuthority) -> None:
        if type(authority) is not ManagedMem0V6PagedManifestAuthority:
            _fail("authority_invalid")
        authority.__post_init__()
        if authority.manifest_context_sha256 != self._context:
            _fail("authority_invalid")
        with self._store._write():
            row = self._require_active_or_committed()
            if str(row[2]) in {"prepared", "committed"}:
                if row[4] != authority.terminal_commitment_sha256:
                    _fail("prepare_conflict")
                return
            if (
                int(row[0]) != authority.operation_count
                or row[1] != authority.page_count
                or row[3] is None
            ):
                _fail("coverage_invalid")
            page_count = 0
            for index, payload, mac in self._store._db.execute(
                "SELECT page_index,payload_json,row_mac FROM pages "
                "WHERE context_sha=? ORDER BY page_index",
                (self._context,),
            ):
                if int(index) != page_count or page_count >= authority.page_count:
                    _fail("coverage_invalid")
                encoded = str(payload)
                self._store._check_row("page", self._context, page_count, encoded, str(mac))
                if (
                    str(json.loads(encoded)["page_commitment_sha256"])
                    != authority.ordered_page_commitment_sha256[page_count]
                ):
                    _fail("authority_invalid")
                page_count += 1
            if page_count != authority.page_count:
                _fail("coverage_invalid")
            unique = json.loads(str(row[3]))
            if unique.get("receipt_sha256") != authority.uniqueness_receipt_sha256:
                _fail("authority_invalid")
            self._store._update_state(
                self._context,
                int(row[0]),
                int(row[1]),
                "prepared",
                row[3],
                authority.terminal_commitment_sha256,
                None,
            )

    def commit(
        self, authority: ManagedMem0V6PagedManifestAuthority
    ) -> ManagedMem0V6PageStoreCommitReceipt:
        self.prepare(authority)
        receipt = ManagedMem0V6PageStoreCommitReceipt(
            manifest_context_sha256=self._context,
            authority_terminal_commitment_sha256=authority.terminal_commitment_sha256,
            page_count=authority.page_count,
            receipt_sha256=store_receipt_sha256(
                self._context, authority.terminal_commitment_sha256, authority.page_count
            ),
        )
        encoded_receipt = _json(
            {name: getattr(receipt, name) for name in receipt.__dataclass_fields__}
        )
        with self._store._write():
            row = self._require_active_or_committed()
            if str(row[2]) == "committed":
                if row[4] != authority.terminal_commitment_sha256 or row[5] != encoded_receipt:
                    _fail("commit_conflict")
                self._store._validate_committed(self._context, row)
                return receipt
            if str(row[2]) != "prepared":
                _fail("prepare_missing")
            self._store._update_state(
                self._context,
                int(row[0]),
                int(row[1]),
                "committed",
                row[3],
                authority.terminal_commitment_sha256,
                encoded_receipt,
            )
            observed = self._require_active_or_committed()
            if str(observed[2]) != "committed" or observed[5] != encoded_receipt:
                _fail("commit_readback_invalid")
            self._store._validate_committed(self._context, observed)
        return receipt

    def readback(self) -> ManagedMem0V6PageStoreCommitReceipt | None:
        self._store._ensure_open()
        row = self._store._session(self._context)
        if row is None:
            return None
        state = self._store._authenticate_state(self._context, row)
        if state != "committed":
            return None
        self._store._validate_committed(self._context, row)
        try:
            receipt = ManagedMem0V6PageStoreCommitReceipt(**json.loads(str(row[5])))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ManagedMem0V6ManifestError(
                "managed_mem0_v6_sqlite_preparation_authentication_invalid"
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
            state = self._store._authenticate_state(self._context, row)
            if state != "committed":
                self._store._db.execute(
                    "DELETE FROM sessions WHERE context_sha=?", (self._context,)
                )

    def _require_active_or_committed(self) -> tuple[object, ...]:
        row = self._store._session(self._context)
        if row is None:
            _fail("session_missing")
        self._store._authenticate_state(self._context, row)
        return row


__all__ = ("SQLiteManagedMem0V6PreparationStore",)
