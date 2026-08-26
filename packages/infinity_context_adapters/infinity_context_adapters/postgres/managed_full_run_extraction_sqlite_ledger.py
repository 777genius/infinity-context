"""Crash-safe authenticated SQLite ledger for a full extraction run."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import suppress
from pathlib import Path

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
    FULL_RUN_EXTRACTION_PAGE_SIZE,
    ManagedFullRunExtractionCheckpoint,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerError,
    ManagedFullRunExtractionReceipt,
    ManagedFullRunExtractionTerminal,
    canonical_bytes,
    canonical_sha256,
)

from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    StrictV4SQLiteFileError,
    close_strict_sqlite,
    create_strict_sqlite,
    exclusive_parent_lock,
    open_strict_sqlite,
    unlink_strict_sqlite_binding,
    verify_strict_sqlite_binding,
    wipe,
)

_CONTEXT_MAC_DOMAIN = b"infinity-context/full-run-extraction/context/v1\x00"
_RECEIPT_MAC_DOMAIN = b"infinity-context/full-run-extraction/receipt/v1\x00"
_STATE_MAC_DOMAIN = b"infinity-context/full-run-extraction/state/v1\x00"

_RUN_SQL = (
    "CREATE TABLE run("
    "singleton INTEGER PRIMARY KEY CHECK(singleton=1),"
    "context_json TEXT NOT NULL,"
    "context_commitment_sha256 TEXT NOT NULL,"
    "context_mac_sha256 TEXT NOT NULL,"
    "receipt_count INTEGER NOT NULL CHECK(receipt_count>=0),"
    "state TEXT NOT NULL CHECK(state IN ('active','committed')),"
    "terminal_json TEXT,"
    "state_mac_sha256 TEXT NOT NULL,"
    "CHECK((state='active' AND terminal_json IS NULL) OR "
    "(state='committed' AND terminal_json IS NOT NULL))"
    ") STRICT"
)
_RECEIPTS_SQL = (
    "CREATE TABLE receipts("
    "sequence INTEGER PRIMARY KEY CHECK(sequence>=0),"
    "payload_json TEXT NOT NULL,"
    "commitment_sha256 TEXT NOT NULL,"
    "row_mac_sha256 TEXT NOT NULL"
    ") STRICT"
)
_SCHEMA_SQL = (_RUN_SQL, _RECEIPTS_SQL)


class SQLiteManagedFullRunExtractionLedger:
    """One authenticated, page-bounded extraction run per private file."""

    def __init__(
        self,
        path: Path,
        db: sqlite3.Connection,
        fd: int,
        authentication_key: bytes,
    ) -> None:
        if type(authentication_key) is not bytes or len(authentication_key) < 32:
            raise ManagedFullRunExtractionLedgerError("authentication_key_invalid")
        self._path = path
        self._db = db
        self._fd = fd
        self._key = bytearray(authentication_key)
        self._data_version = _data_version(db)
        self._closed = False
        self._checkpoint: ManagedFullRunExtractionCheckpoint | None = None
        self._full_scan_pass_count = 0
        self._full_scan_receipt_count = 0
        self._max_scan_batch_size = 0

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        authentication_key: bytes,
    ) -> SQLiteManagedFullRunExtractionLedger:
        target = Path(path)
        db, fd = create_strict_sqlite(target)
        try:
            _initialize_schema(db)
            verify_strict_sqlite_binding(target, fd)
            return cls(target, db, fd, authentication_key)
        except BaseException:
            try:
                with suppress(StrictV4SQLiteFileError, FileNotFoundError):
                    unlink_strict_sqlite_binding(target, fd)
            finally:
                close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        authentication_key: bytes,
    ) -> SQLiteManagedFullRunExtractionLedger:
        target = Path(path)
        db, fd = open_strict_sqlite(target, readonly=False)
        try:
            _validate_schema(db)
            verify_strict_sqlite_binding(target, fd)
            ledger = cls(target, db, fd, authentication_key)
            ledger._verify_persisted_state()
            return ledger
        except BaseException:
            close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open_or_create(
        cls,
        path: str | os.PathLike[str],
        *,
        authentication_key: bytes,
    ) -> SQLiteManagedFullRunExtractionLedger:
        target = Path(path)
        with exclusive_parent_lock(target.parent):
            if not target.exists():
                return cls.create(target, authentication_key=authentication_key)
            db, fd = open_strict_sqlite(target, readonly=False)
            try:
                _initialize_schema(db)
                verify_strict_sqlite_binding(target, fd)
                ledger = cls(target, db, fd, authentication_key)
                ledger._verify_persisted_state()
                return ledger
            except BaseException:
                close_strict_sqlite(db, fd)
                raise

    @property
    def max_scan_batch_size(self) -> int:
        return self._max_scan_batch_size

    @property
    def full_scan_pass_count(self) -> int:
        return self._full_scan_pass_count

    @property
    def full_scan_receipt_count(self) -> int:
        return self._full_scan_receipt_count

    def begin(self, context: ManagedFullRunExtractionContext) -> None:
        self._require_open()
        self._verify_binding()
        context_json = canonical_bytes(context.payload()).decode("ascii")
        context_mac = self._mac(_CONTEXT_MAC_DOMAIN, context_json.encode("ascii"))
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT context_json,context_commitment_sha256,context_mac_sha256 "
                "FROM run WHERE singleton=1"
            ).fetchone()
            if row is not None:
                if (
                    str(row[0]) != context_json
                    or str(row[1]) != context.commitment_sha256
                    or not hmac.compare_digest(str(row[2]), context_mac)
                ):
                    raise ManagedFullRunExtractionLedgerError("context_conflict")
                checkpoint = self._checkpoint_from_row(self._verify_state_row())
                self._require_checkpoint_match(checkpoint)
                self._verify_binding()
                self._db.commit()
                self._checkpoint = checkpoint
                self._verify_binding()
                return
            state_mac = self._state_mac(
                context_commitment_sha256=context.commitment_sha256,
                receipt_count=0,
                state="active",
                terminal_json=None,
            )
            self._db.execute(
                "INSERT INTO run VALUES(1,?,?,?,?,?,?,?)",
                (
                    context_json,
                    context.commitment_sha256,
                    context_mac,
                    0,
                    "active",
                    None,
                    state_mac,
                ),
            )
            checkpoint = self._checkpoint_from_row(self._verify_state_row())
            self._verify_binding()
            self._db.commit()
            self._checkpoint = checkpoint
            self._verify_binding()
        except BaseException:
            self._db.rollback()
            raise

    def read_checkpoint(self) -> ManagedFullRunExtractionCheckpoint:
        """Return MAC-authenticated progress from this exhaustively verified session."""

        self._require_open()
        self._verify_binding()
        checkpoint = self._checkpoint_from_row(self._verify_state_row())
        self._require_checkpoint_match(checkpoint)
        self._verify_binding()
        return checkpoint

    def append_page(
        self,
        receipts: tuple[ManagedFullRunExtractionReceipt, ...],
    ) -> None:
        self._require_open()
        if (
            type(receipts) is not tuple
            or not receipts
            or len(receipts) > FULL_RUN_EXTRACTION_PAGE_SIZE
        ):
            raise ManagedFullRunExtractionLedgerError("receipt_page_invalid")
        self._verify_binding()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            context, count, state, terminal_json = self._load_context_and_state()
            current_checkpoint = self._checkpoint_from_state(
                context=context,
                receipt_count=count,
                state=state,
                terminal_json=terminal_json,
            )
            self._require_checkpoint_match(current_checkpoint)
            if state != "active" or terminal_json is not None:
                raise ManagedFullRunExtractionLedgerError("ledger_not_active")
            start = receipts[0].sequence
            for offset, receipt in enumerate(receipts):
                if (
                    type(receipt) is not ManagedFullRunExtractionReceipt
                    or receipt.sequence != start + offset
                    or receipt.runtime_binding_commitment_sha256
                    != context.runtime_binding_commitment_sha256
                ):
                    raise ManagedFullRunExtractionLedgerError("receipt_page_invalid")
            end = start + len(receipts)
            if start < count:
                if end > count:
                    raise ManagedFullRunExtractionLedgerError("receipt_page_overlap")
                self._verify_exact_replay(context, receipts)
                self._verify_binding()
                self._db.commit()
                self._checkpoint = current_checkpoint
                self._verify_binding()
                return
            if start != count or end > context.expected_receipt_count:
                raise ManagedFullRunExtractionLedgerError("receipt_sequence_gap")
            for receipt in receipts:
                payload_json = canonical_bytes(receipt.payload()).decode("ascii")
                inserted = self._db.execute(
                    "INSERT INTO receipts VALUES(?,?,?,?)",
                    (
                        receipt.sequence,
                        payload_json,
                        receipt.commitment_sha256,
                        self._receipt_mac(
                            context.commitment_sha256,
                            receipt.sequence,
                            payload_json,
                        ),
                    ),
                )
                if inserted.rowcount != 1:
                    raise ManagedFullRunExtractionLedgerError("receipt_write_invalid")
            state_mac = self._state_mac(
                context_commitment_sha256=context.commitment_sha256,
                receipt_count=end,
                state="active",
                terminal_json=None,
            )
            updated = self._db.execute(
                "UPDATE run SET receipt_count=?,state_mac_sha256=? WHERE singleton=1",
                (end, state_mac),
            )
            if updated.rowcount != 1:
                raise ManagedFullRunExtractionLedgerError("receipt_write_invalid")
            self._verify_exact_replay(context, receipts)
            checkpoint = self._checkpoint_from_row(self._verify_state_row())
            if (
                checkpoint.context_commitment_sha256 != context.commitment_sha256
                or checkpoint.receipt_count != end
                or checkpoint.state != "active"
            ):
                raise ManagedFullRunExtractionLedgerError("receipt_write_invalid")
            self._verify_binding()
            self._db.commit()
            self._checkpoint = checkpoint
            self._verify_binding()
        except BaseException:
            self._db.rollback()
            raise

    def finalize(self) -> ManagedFullRunExtractionTerminal:
        self._require_open()
        self._verify_binding()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            context, count, state, terminal_json = self._load_context_and_state()
            current_checkpoint = self._checkpoint_from_state(
                context=context,
                receipt_count=count,
                state=state,
                terminal_json=terminal_json,
            )
            self._require_checkpoint_match(current_checkpoint)
            if count != context.expected_receipt_count:
                raise ManagedFullRunExtractionLedgerError("receipt_count_incomplete")
            if state == "committed":
                terminal = current_checkpoint.terminal
                if terminal is None:
                    raise ManagedFullRunExtractionLedgerError("terminal_invalid")
                encoded = canonical_bytes(_terminal_payload(terminal)).decode("ascii")
                if terminal_json != encoded:
                    raise ManagedFullRunExtractionLedgerError("terminal_invalid")
                self._verify_binding()
                self._db.commit()
                self._checkpoint = current_checkpoint
                self._verify_binding()
                return terminal
            if state != "active" or terminal_json is not None:
                raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
            terminal = self._recompute_terminal(context, count)
            encoded = canonical_bytes(_terminal_payload(terminal)).decode("ascii")
            state_mac = self._state_mac(
                context_commitment_sha256=context.commitment_sha256,
                receipt_count=count,
                state="committed",
                terminal_json=encoded,
            )
            updated = self._db.execute(
                "UPDATE run SET state='committed',terminal_json=?,state_mac_sha256=? "
                "WHERE singleton=1",
                (encoded, state_mac),
            )
            if updated.rowcount != 1:
                raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
            checkpoint = self._checkpoint_from_row(self._verify_state_row())
            if checkpoint.terminal != terminal:
                raise ManagedFullRunExtractionLedgerError("terminal_invalid")
            self._verify_binding()
            self._db.commit()
            self._checkpoint = checkpoint
            self._verify_binding()
            return terminal
        except BaseException:
            self._db.rollback()
            raise

    def readback(self) -> ManagedFullRunExtractionTerminal | None:
        return self.read_checkpoint().terminal

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        error: BaseException | None = None
        try:
            self._verify_binding()
        except BaseException as exc:
            error = exc
        try:
            close_strict_sqlite(self._db, self._fd)
        finally:
            wipe(self._key)
        if error is not None:
            raise error

    def _load_context_and_state(
        self,
    ) -> tuple[ManagedFullRunExtractionContext, int, str, str | None]:
        row = self._verify_state_row()
        context = _context_from_json(str(row[0]))
        if context.commitment_sha256 != str(row[1]):
            raise ManagedFullRunExtractionLedgerError("context_commitment_invalid")
        return context, int(row[3]), str(row[4]), None if row[5] is None else str(row[5])

    def _checkpoint_from_row(
        self,
        row: tuple[object, ...],
    ) -> ManagedFullRunExtractionCheckpoint:
        context = _context_from_json(str(row[0]))
        if context.commitment_sha256 != str(row[1]):
            raise ManagedFullRunExtractionLedgerError("context_commitment_invalid")
        return self._checkpoint_from_state(
            context=context,
            receipt_count=int(row[3]),
            state=str(row[4]),
            terminal_json=None if row[5] is None else str(row[5]),
        )

    @staticmethod
    def _checkpoint_from_state(
        *,
        context: ManagedFullRunExtractionContext,
        receipt_count: int,
        state: str,
        terminal_json: str | None,
    ) -> ManagedFullRunExtractionCheckpoint:
        terminal: ManagedFullRunExtractionTerminal | None = None
        if state == "active":
            if terminal_json is not None:
                raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
        elif state == "committed":
            if terminal_json is None or receipt_count != context.expected_receipt_count:
                raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
            terminal = _terminal_from_json(terminal_json)
            if (
                terminal.context_commitment_sha256 != context.commitment_sha256
                or terminal.receipt_count != receipt_count
            ):
                raise ManagedFullRunExtractionLedgerError("terminal_invalid")
        else:
            raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
        return ManagedFullRunExtractionCheckpoint(
            context_commitment_sha256=context.commitment_sha256,
            receipt_count=receipt_count,
            expected_receipt_count=context.expected_receipt_count,
            state=state,
            terminal=terminal,
        )

    def _require_checkpoint_match(
        self,
        checkpoint: ManagedFullRunExtractionCheckpoint,
    ) -> None:
        if self._checkpoint is not None and self._checkpoint != checkpoint:
            raise ManagedFullRunExtractionLedgerError("ledger_checkpoint_changed")

    def _verify_state_row(self) -> tuple[object, ...]:
        row = self._db.execute(
            "SELECT context_json,context_commitment_sha256,context_mac_sha256,"
            "receipt_count,state,terminal_json,state_mac_sha256 FROM run WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise ManagedFullRunExtractionLedgerError("ledger_not_started")
        context_json = str(row[0])
        context_commitment = str(row[1])
        if not hmac.compare_digest(
            str(row[2]),
            self._mac(_CONTEXT_MAC_DOMAIN, context_json.encode("ascii")),
        ):
            raise ManagedFullRunExtractionLedgerError("context_authentication_invalid")
        expected_state_mac = self._state_mac(
            context_commitment_sha256=context_commitment,
            receipt_count=int(row[3]),
            state=str(row[4]),
            terminal_json=None if row[5] is None else str(row[5]),
        )
        if not hmac.compare_digest(str(row[6]), expected_state_mac):
            raise ManagedFullRunExtractionLedgerError("state_authentication_invalid")
        return tuple(row)

    def _verify_persisted_state(self) -> None:
        self._verify_binding()
        row = self._db.execute("SELECT singleton FROM run WHERE singleton=1").fetchone()
        if row is None:
            self._checkpoint = None
            self._verify_binding()
            return
        context, count, state, terminal_json = self._load_context_and_state()
        checkpoint = self._checkpoint_from_state(
            context=context,
            receipt_count=count,
            state=state,
            terminal_json=terminal_json,
        )
        if state == "committed":
            if terminal_json is None or count != context.expected_receipt_count:
                raise ManagedFullRunExtractionLedgerError("ledger_state_invalid")
            terminal = self._recompute_terminal(context, count)
            if (
                checkpoint.terminal != terminal
                or canonical_bytes(_terminal_payload(terminal)).decode("ascii") != terminal_json
            ):
                raise ManagedFullRunExtractionLedgerError("terminal_invalid")
        else:
            self._verify_receipt_rows(context, count)
        self._checkpoint = checkpoint
        self._verify_binding()

    def _verify_receipt_rows(
        self,
        context: ManagedFullRunExtractionContext,
        expected_count: int,
    ) -> None:
        self._full_scan_pass_count += 1
        cursor = self._db.execute(
            "SELECT sequence,payload_json,commitment_sha256,row_mac_sha256 "
            "FROM receipts ORDER BY sequence"
        )
        sequence = 0
        while rows := cursor.fetchmany(FULL_RUN_EXTRACTION_PAGE_SIZE):
            self._max_scan_batch_size = max(self._max_scan_batch_size, len(rows))
            self._full_scan_receipt_count += len(rows)
            for row in rows:
                observed_sequence = int(row[0])
                payload_json = str(row[1])
                if observed_sequence != sequence:
                    raise ManagedFullRunExtractionLedgerError("receipt_sequence_gap")
                receipt = _receipt_from_json(payload_json)
                if (
                    receipt.sequence != observed_sequence
                    or receipt.runtime_binding_commitment_sha256
                    != context.runtime_binding_commitment_sha256
                    or receipt.commitment_sha256 != str(row[2])
                    or not hmac.compare_digest(
                        str(row[3]),
                        self._receipt_mac(
                            context.commitment_sha256,
                            observed_sequence,
                            payload_json,
                        ),
                    )
                ):
                    raise ManagedFullRunExtractionLedgerError("receipt_authentication_invalid")
                sequence += 1
        if sequence != expected_count:
            raise ManagedFullRunExtractionLedgerError("receipt_count_invalid")

    def _verify_exact_replay(
        self,
        context: ManagedFullRunExtractionContext,
        receipts: tuple[ManagedFullRunExtractionReceipt, ...],
    ) -> None:
        first = receipts[0].sequence
        cursor = self._db.execute(
            "SELECT sequence,payload_json,commitment_sha256,row_mac_sha256 "
            "FROM receipts WHERE sequence>=? AND sequence<? ORDER BY sequence",
            (first, first + len(receipts)),
        )
        rows = cursor.fetchmany(FULL_RUN_EXTRACTION_PAGE_SIZE)
        self._max_scan_batch_size = max(self._max_scan_batch_size, len(rows))
        if len(rows) != len(receipts) or cursor.fetchone() is not None:
            raise ManagedFullRunExtractionLedgerError("receipt_replay_conflict")
        for receipt, row in zip(receipts, rows, strict=True):
            payload_json = canonical_bytes(receipt.payload()).decode("ascii")
            if (
                int(row[0]) != receipt.sequence
                or str(row[1]) != payload_json
                or str(row[2]) != receipt.commitment_sha256
                or not hmac.compare_digest(
                    str(row[3]),
                    self._receipt_mac(
                        context.commitment_sha256,
                        receipt.sequence,
                        payload_json,
                    ),
                )
            ):
                raise ManagedFullRunExtractionLedgerError("receipt_replay_conflict")

    def _recompute_terminal(
        self,
        context: ManagedFullRunExtractionContext,
        count: int,
    ) -> ManagedFullRunExtractionTerminal:
        self._full_scan_pass_count += 1
        page_roots: list[str] = []
        prompt_tokens = completion_tokens = total_tokens = 0
        cursor = self._db.execute(
            "SELECT sequence,payload_json,commitment_sha256,row_mac_sha256 "
            "FROM receipts ORDER BY sequence"
        )
        expected_sequence = 0
        page_index = 0
        while rows := cursor.fetchmany(FULL_RUN_EXTRACTION_PAGE_SIZE):
            self._max_scan_batch_size = max(self._max_scan_batch_size, len(rows))
            self._full_scan_receipt_count += len(rows)
            commitments: list[str] = []
            for row in rows:
                sequence = int(row[0])
                payload_json = str(row[1])
                receipt = _receipt_from_json(payload_json)
                if (
                    sequence != expected_sequence
                    or receipt.sequence != sequence
                    or receipt.commitment_sha256 != str(row[2])
                    or not hmac.compare_digest(
                        str(row[3]),
                        self._receipt_mac(
                            context.commitment_sha256,
                            sequence,
                            payload_json,
                        ),
                    )
                    or receipt.runtime_binding_commitment_sha256
                    != context.runtime_binding_commitment_sha256
                ):
                    raise ManagedFullRunExtractionLedgerError("receipt_authentication_invalid")
                commitments.append(receipt.commitment_sha256)
                prompt_tokens += receipt.prompt_tokens
                completion_tokens += receipt.completion_tokens
                total_tokens += receipt.total_tokens
                expected_sequence += 1
            page_roots.append(
                canonical_sha256(
                    {
                        "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
                        "page_index": page_index,
                        "first_sequence": int(rows[0][0]),
                        "last_sequence": int(rows[-1][0]),
                        "receipt_commitment_sha256": commitments,
                    }
                )
            )
            page_index += 1
        if expected_sequence != count:
            raise ManagedFullRunExtractionLedgerError("receipt_count_invalid")
        pages_root = canonical_sha256(
            {
                "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
                "page_commitment_sha256": page_roots,
            }
        )
        body = {
            "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
            "context_commitment_sha256": context.commitment_sha256,
            "receipt_count": count,
            "page_count": len(page_roots),
            "receipt_pages_root_sha256": pages_root,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }
        return ManagedFullRunExtractionTerminal(
            context_commitment_sha256=context.commitment_sha256,
            receipt_count=count,
            page_count=len(page_roots),
            receipt_pages_root_sha256=pages_root,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            terminal_commitment_sha256=canonical_sha256(body),
        )

    def _receipt_mac(
        self,
        context_commitment_sha256: str,
        sequence: int,
        payload_json: str,
    ) -> str:
        return self._mac(
            _RECEIPT_MAC_DOMAIN,
            canonical_bytes(
                {
                    "context_commitment_sha256": context_commitment_sha256,
                    "sequence": sequence,
                    "payload_json": payload_json,
                }
            ),
        )

    def _state_mac(
        self,
        *,
        context_commitment_sha256: str,
        receipt_count: int,
        state: str,
        terminal_json: str | None,
    ) -> str:
        return self._mac(
            _STATE_MAC_DOMAIN,
            canonical_bytes(
                {
                    "context_commitment_sha256": context_commitment_sha256,
                    "receipt_count": receipt_count,
                    "state": state,
                    "terminal_json": terminal_json,
                }
            ),
        )

    def _mac(self, domain: bytes, payload: bytes) -> str:
        return hmac.new(self._key, domain + payload, hashlib.sha256).hexdigest()

    def _verify_binding(self) -> None:
        verify_strict_sqlite_binding(self._path, self._fd)
        if _data_version(self._db) != self._data_version:
            raise ManagedFullRunExtractionLedgerError("ledger_session_changed")

    def _require_open(self) -> None:
        if self._closed:
            raise ManagedFullRunExtractionLedgerError("ledger_closed")


def _initialize_schema(db: sqlite3.Connection) -> None:
    db.execute("BEGIN IMMEDIATE")
    try:
        objects = _schema_objects(db)
        if not objects:
            for statement in _SCHEMA_SQL:
                db.execute(statement)
        _validate_schema(db)
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _data_version(db: sqlite3.Connection) -> int:
    row = db.execute("PRAGMA data_version").fetchone()
    if row is None or type(row[0]) is not int:
        raise ManagedFullRunExtractionLedgerError("ledger_session_invalid")
    return int(row[0])


def _schema_objects(db: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    )


def _validate_schema(db: sqlite3.Connection) -> None:
    expected = tuple(
        sorted(
            (
                ("table", "receipts", "receipts", _RECEIPTS_SQL),
                ("table", "run", "run", _RUN_SQL),
            )
        )
    )
    if (
        _schema_objects(db) != expected
        or db.execute("PRAGMA foreign_keys").fetchone() != (1,)
        or db.execute("PRAGMA trusted_schema").fetchone() != (0,)
    ):
        raise ManagedFullRunExtractionLedgerError("ledger_schema_invalid")


def _strict_json(source: str) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(token: str) -> object:
        raise ValueError(f"invalid constant {token}")

    value = json.loads(
        source,
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )
    if type(value) is not dict or canonical_bytes(value).decode("ascii") != source:
        raise ValueError("non-canonical payload")
    return value


def _context_from_json(source: str) -> ManagedFullRunExtractionContext:
    try:
        value = _strict_json(source)
        if value.pop("schema_version", None) != FULL_RUN_EXTRACTION_LEDGER_SCHEMA:
            raise ValueError("context schema invalid")
        return ManagedFullRunExtractionContext(**value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ManagedFullRunExtractionLedgerError("context_invalid") from exc


def _receipt_from_json(source: str) -> ManagedFullRunExtractionReceipt:
    try:
        value = _strict_json(source)
        usage = value.pop("usage")
        if type(usage) is not dict:
            raise ValueError("usage invalid")
        return ManagedFullRunExtractionReceipt(**value, **usage)
    except (TypeError, ValueError, KeyError) as exc:
        raise ManagedFullRunExtractionLedgerError("receipt_invalid") from exc


def _terminal_from_json(source: str) -> ManagedFullRunExtractionTerminal:
    try:
        value = _strict_json(source)
        if value.pop("schema_version", None) != FULL_RUN_EXTRACTION_LEDGER_SCHEMA:
            raise ValueError("terminal schema invalid")
        usage = value.pop("usage")
        if type(usage) is not dict:
            raise ValueError("usage invalid")
        return ManagedFullRunExtractionTerminal(**value, **usage)
    except (TypeError, ValueError, KeyError, ManagedFullRunExtractionLedgerError) as exc:
        raise ManagedFullRunExtractionLedgerError("terminal_invalid") from exc


def _terminal_payload(terminal: ManagedFullRunExtractionTerminal) -> dict[str, object]:
    return {
        **terminal.body(),
        "terminal_commitment_sha256": terminal.terminal_commitment_sha256,
    }


__all__ = ("SQLiteManagedFullRunExtractionLedger",)
