"""Authenticated provider-free SQLite journal for strict-v4 cleanup."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
from contextlib import suppress
from pathlib import Path
from typing import Protocol

from infinity_context_core.application.use_cases.managed_cleanup_v4_lifecycle import (
    ManagedCleanupV4InitiationReceipt,
    ManagedCleanupV4TerminalBindings,
    ManagedCleanupV4TerminalReceipt,
)
from infinity_context_core.features.projection_receipts import ProjectionReceiptAuthenticator
from infinity_context_core.ports.managed_cleanup_v3_contracts import canonical_bytes
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    ManagedCleanupV4Authority,
    StrictV4CleanupAuthorityReadback,
    authenticate_strict_v4_cleanup_authority_readback,
    build_strict_v4_cleanup_authority,
)

from infinity_context_adapters.postgres.managed_strict_v4_sqlite_files import (
    close_strict_sqlite,
    create_strict_sqlite,
    open_strict_sqlite,
    wipe,
)

JOURNAL_SCHEMA = "memory-comparison-strict-v4-cleanup-journal.v1"
JOURNAL_KEY_PURPOSE = "strict-v4-cleanup-journal"
_ZERO = "0" * 64
_SCHEMA_SQL = (
    "CREATE TABLE journal_metadata(singleton INTEGER PRIMARY KEY CHECK(singleton=1),schema_version TEXT NOT NULL,schema_fingerprint_sha256 TEXT NOT NULL,authentication_key_id TEXT NOT NULL,metadata_mac_sha256 TEXT NOT NULL) STRICT",
    "CREATE TABLE cleanup_authority(singleton INTEGER PRIMARY KEY CHECK(singleton=1),run_id_sha256 TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,authority_mac_sha256 TEXT NOT NULL) STRICT",
    "CREATE TABLE lifecycle_events(sequence INTEGER PRIMARY KEY,event_kind TEXT NOT NULL CHECK(event_kind IN ('initiation','terminal')),run_id_sha256 TEXT NOT NULL,payload_json TEXT NOT NULL,previous_event_sha256 TEXT NOT NULL,event_sha256 TEXT NOT NULL UNIQUE,event_mac_sha256 TEXT NOT NULL,UNIQUE(run_id_sha256,event_kind)) STRICT",
    "CREATE TABLE journal_head(singleton INTEGER PRIMARY KEY CHECK(singleton=1),event_count INTEGER NOT NULL CHECK(event_count>=0),event_head_sha256 TEXT NOT NULL,terminal_head_sha256 TEXT,head_mac_sha256 TEXT NOT NULL) STRICT",
)
_EXPECTED_SCHEMA = tuple(
    sorted(
        (
            ("table", "journal_metadata", "journal_metadata", _SCHEMA_SQL[0]),
            ("table", "cleanup_authority", "cleanup_authority", _SCHEMA_SQL[1]),
            ("table", "lifecycle_events", "lifecycle_events", _SCHEMA_SQL[2]),
            ("table", "journal_head", "journal_head", _SCHEMA_SQL[3]),
        )
    )
)
SCHEMA_FINGERPRINT_SHA256 = hashlib.sha256(
    canonical_bytes([list(row) for row in _EXPECTED_SCHEMA])
).hexdigest()


class ManagedCleanupV4JournalError(RuntimeError):
    """Stable fail-closed journal error."""


class CleanupJournalKeyIdentityPort(Protocol):
    def resolve(self, *, purpose: str, key_id: str) -> bytes: ...


class SQLiteManagedCleanupV4Journal:
    """One immutable strict authority and an authenticated two-event chain."""

    def __init__(
        self, path: Path, db: sqlite3.Connection, fd: int, *, key_id: str, secret: bytearray
    ) -> None:
        self._path, self._db, self._fd = path, db, fd
        self._key_id, self._secret, self._closed = key_id, secret, False

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        readback: StrictV4CleanupAuthorityReadback,
        authentication_key_id: str,
        key_identity_authority: CleanupJournalKeyIdentityPort,
    ) -> SQLiteManagedCleanupV4Journal:
        target = Path(path)
        secret = _resolve_key(key_identity_authority, authentication_key_id)
        authenticate_strict_v4_cleanup_authority_readback(
            readback,
            authenticator=ProjectionReceiptAuthenticator(bytes(secret)),
            authentication_key_id=authentication_key_id,
        )
        db = None
        fd = None
        try:
            db, fd = create_strict_sqlite(target)
            for statement in _SCHEMA_SQL:
                db.execute(statement)
            journal = cls(target, db, fd, key_id=authentication_key_id, secret=secret)
            journal._initialize(readback)
            journal._verify_all()
            return journal
        except BaseException:
            wipe(secret)
            if db is not None and fd is not None:
                try:
                    _unlink_if_bound(target, fd)
                finally:
                    close_strict_sqlite(db, fd)
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        key_identity_authority: CleanupJournalKeyIdentityPort,
    ) -> SQLiteManagedCleanupV4Journal:
        target = Path(path)
        db, fd = open_strict_sqlite(target, readonly=False)
        secret = None
        try:
            row = db.execute(
                "SELECT authentication_key_id FROM journal_metadata WHERE singleton=1"
            ).fetchone()
            if row is None or type(row[0]) is not str:
                _fail("metadata_invalid")
            secret = _resolve_key(key_identity_authority, row[0])
            journal = cls(target, db, fd, key_id=row[0], secret=secret)
            journal._verify_all()
            return journal
        except BaseException:
            if secret is not None:
                wipe(secret)
            close_strict_sqlite(db, fd)
            raise

    @property
    def authentication_key_id(self) -> str:
        return self._key_id

    @property
    def run_id_sha256(self) -> str:
        self._verify_all()
        row = self._db.execute(
            "SELECT run_id_sha256 FROM cleanup_authority WHERE singleton=1"
        ).fetchone()
        assert row is not None
        value = str(row[0])
        _verify_stable_file(self._path, self._fd)
        return value

    async def read_registered_strict_v4(
        self, run_id_sha256: str
    ) -> StrictV4CleanupAuthorityReadback | None:
        self._verify_all()
        row = self._db.execute(
            "SELECT run_id_sha256,payload_json FROM cleanup_authority WHERE singleton=1"
        ).fetchone()
        value = (
            None if row is None or str(row[0]) != run_id_sha256 else _stored_readback(str(row[1]))
        )
        _verify_stable_file(self._path, self._fd)
        return value

    async def read_initiation(self, run_id_sha256: str) -> ManagedCleanupV4InitiationReceipt | None:
        value = self._read_event(run_id_sha256, "initiation")
        return None if value is None else _initiation(value)

    async def put_initiation(
        self, receipt: ManagedCleanupV4InitiationReceipt
    ) -> ManagedCleanupV4InitiationReceipt:
        if type(receipt) is not ManagedCleanupV4InitiationReceipt:
            _fail("initiation_invalid")
        receipt.__post_init__()
        stored = _initiation(
            self._put_event(receipt.run_id_sha256, "initiation", receipt.payload())
        )
        if stored != receipt:
            _fail("initiation_conflict")
        return stored

    async def read_terminal(self, run_id_sha256: str) -> ManagedCleanupV4TerminalReceipt | None:
        value = self._read_event(run_id_sha256, "terminal")
        return None if value is None else _terminal(value)

    async def put_terminal(
        self, receipt: ManagedCleanupV4TerminalReceipt
    ) -> ManagedCleanupV4TerminalReceipt:
        if type(receipt) is not ManagedCleanupV4TerminalReceipt:
            _fail("terminal_invalid")
        receipt.__post_init__()
        stored = _terminal(self._put_event(receipt.run_id_sha256, "terminal", receipt.payload()))
        if stored != receipt:
            _fail("terminal_conflict")
        return stored

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            failure: BaseException | None = None
            try:
                _verify_stable_file(self._path, self._fd)
            except BaseException as exc:
                failure = exc
            finally:
                try:
                    close_strict_sqlite(self._db, self._fd)
                finally:
                    wipe(self._secret)
            if failure is not None:
                raise failure

    def _initialize(self, readback: StrictV4CleanupAuthorityReadback) -> None:
        metadata = {
            "schema_version": JOURNAL_SCHEMA,
            "schema_fingerprint_sha256": SCHEMA_FINGERPRINT_SHA256,
            "authentication_key_id": self._key_id,
        }
        strict_authority = build_strict_v4_cleanup_authority(
            run_id_sha256=readback.run_id_sha256,
            context_sha256=readback.context_sha256,
            a2_terminal_sha256=readback.a2_terminal_sha256,
            expected_index_terminal_sha256=readback.expected_index_terminal_sha256,
        )
        authority = {
            "authority_kind": strict_authority.kind,
            "authority_sha256": strict_authority.authority_sha256,
            "readback": readback.payload(),
        }
        head = {"event_count": 0, "event_head_sha256": _ZERO, "terminal_head_sha256": None}
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                "INSERT INTO journal_metadata VALUES(1,?,?,?,?)",
                (*metadata.values(), self._mac("metadata", metadata)),
            )
            self._db.execute(
                "INSERT INTO cleanup_authority VALUES(1,?,?,?)",
                (readback.run_id_sha256, _json(authority), self._mac("authority", authority)),
            )
            self._db.execute(
                "INSERT INTO journal_head VALUES(1,?,?,?,?)",
                (*head.values(), self._mac("head", head)),
            )
            _verify_stable_file(self._path, self._fd)
            self._db.commit()
            _verify_stable_file(self._path, self._fd)
        except BaseException:
            self._db.rollback()
            raise

    def _read_event(self, run_id: str, kind: str) -> dict[str, object] | None:
        self._verify_all()
        row = self._db.execute(
            "SELECT payload_json FROM lifecycle_events WHERE run_id_sha256=? AND event_kind=?",
            (run_id, kind),
        ).fetchone()
        value = None if row is None else _object(str(row[0]))
        _verify_stable_file(self._path, self._fd)
        return value

    def _put_event(self, run_id: str, kind: str, payload: dict[str, object]) -> dict[str, object]:
        self._ensure_open()
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._verify_all()
            authority = self._db.execute(
                "SELECT run_id_sha256 FROM cleanup_authority WHERE singleton=1"
            ).fetchone()
            if authority is None or str(authority[0]) != run_id:
                _fail("run_conflict")
            existing = self._db.execute(
                "SELECT payload_json FROM lifecycle_events WHERE run_id_sha256=? AND event_kind=?",
                (run_id, kind),
            ).fetchone()
            if existing is not None:
                value = _object(str(existing[0]))
                if value != payload:
                    _fail(f"{kind}_conflict")
                _verify_stable_file(self._path, self._fd)
                self._db.commit()
                _verify_stable_file(self._path, self._fd)
                return value
            head_row = self._db.execute(
                "SELECT event_count,event_head_sha256,terminal_head_sha256 FROM journal_head WHERE singleton=1"
            ).fetchone()
            assert head_row is not None
            count, previous, terminal = int(head_row[0]), str(head_row[1]), head_row[2]
            if (kind == "initiation" and count != 0) or (kind == "terminal" and count != 1):
                _fail("order_invalid")
            sequence = count + 1
            material = {
                "sequence": sequence,
                "event_kind": kind,
                "run_id_sha256": run_id,
                "payload": payload,
                "previous_event_sha256": previous,
            }
            event_sha = _event_sha(material)
            self._db.execute(
                "INSERT INTO lifecycle_events VALUES(?,?,?,?,?,?,?)",
                (
                    sequence,
                    kind,
                    run_id,
                    _json(payload),
                    previous,
                    event_sha,
                    self._mac("event", {**material, "event_sha256": event_sha}),
                ),
            )
            head = {
                "event_count": sequence,
                "event_head_sha256": event_sha,
                "terminal_head_sha256": event_sha if kind == "terminal" else terminal,
            }
            self._db.execute(
                "UPDATE journal_head SET event_count=?,event_head_sha256=?,terminal_head_sha256=?,head_mac_sha256=? WHERE singleton=1",
                (*head.values(), self._mac("head", head)),
            )
            _verify_stable_file(self._path, self._fd)
            self._db.commit()
            _verify_stable_file(self._path, self._fd)
            return payload
        except BaseException:
            self._db.rollback()
            raise

    def _verify_all(self) -> None:
        self._ensure_open()
        _verify_stable_file(self._path, self._fd)
        if self._db.execute("PRAGMA quick_check").fetchone() != ("ok",):
            _fail("integrity_invalid")
        schema = tuple(
            tuple(str(value) for value in row)
            for row in self._db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        )
        if schema != _EXPECTED_SCHEMA:
            _fail("schema_invalid")
        meta_row = self._db.execute(
            "SELECT schema_version,schema_fingerprint_sha256,authentication_key_id,metadata_mac_sha256 FROM journal_metadata WHERE singleton=1"
        ).fetchone()
        if meta_row is None:
            _fail("metadata_invalid")
        metadata = {
            "schema_version": str(meta_row[0]),
            "schema_fingerprint_sha256": str(meta_row[1]),
            "authentication_key_id": str(meta_row[2]),
        }
        if metadata != {
            "schema_version": JOURNAL_SCHEMA,
            "schema_fingerprint_sha256": SCHEMA_FINGERPRINT_SHA256,
            "authentication_key_id": self._key_id,
        }:
            _fail("metadata_invalid")
        self._require_mac("metadata", metadata, str(meta_row[3]))
        authority_row = self._db.execute(
            "SELECT run_id_sha256,payload_json,authority_mac_sha256 FROM cleanup_authority WHERE singleton=1"
        ).fetchone()
        if authority_row is None:
            _fail("authority_invalid")
        authority = _object(str(authority_row[1]))
        self._require_mac("authority", authority, str(authority_row[2]))
        readback = _stored_readback(str(authority_row[1]))
        if str(authority_row[0]) != readback.run_id_sha256:
            _fail("authority_invalid")
        previous, terminal, count = _ZERO, None, 0
        rows = self._db.execute(
            "SELECT sequence,event_kind,run_id_sha256,payload_json,previous_event_sha256,event_sha256,event_mac_sha256 FROM lifecycle_events ORDER BY sequence"
        )
        for row in rows:
            sequence, kind, run_id, payload_json, prior, event_sha, event_mac = row
            count += 1
            payload = _object(str(payload_json))
            material = {
                "sequence": int(sequence),
                "event_kind": str(kind),
                "run_id_sha256": str(run_id),
                "payload": payload,
                "previous_event_sha256": str(prior),
            }
            expected = _event_sha(material)
            if (
                int(sequence) != count
                or str(prior) != previous
                or str(event_sha) != expected
                or str(run_id) != readback.run_id_sha256
            ):
                _fail("chain_invalid")
            self._require_mac("event", {**material, "event_sha256": expected}, str(event_mac))
            if kind == "initiation" and count == 1:
                _initiation(payload)
            elif kind == "terminal" and count == 2:
                _terminal(payload)
                terminal = expected
            else:
                _fail("order_invalid")
            previous = expected
        head_row = self._db.execute(
            "SELECT event_count,event_head_sha256,terminal_head_sha256,head_mac_sha256 FROM journal_head WHERE singleton=1"
        ).fetchone()
        if head_row is None:
            _fail("head_invalid")
        head = {
            "event_count": int(head_row[0]),
            "event_head_sha256": str(head_row[1]),
            "terminal_head_sha256": head_row[2],
        }
        if head != {
            "event_count": count,
            "event_head_sha256": previous,
            "terminal_head_sha256": terminal,
        }:
            _fail("head_invalid")
        self._require_mac("head", head, str(head_row[3]))
        _verify_stable_file(self._path, self._fd)

    def _mac(self, label: str, value: object) -> str:
        message = (
            b"infinity-context:strict-v4-cleanup-journal:v1:"
            + label.encode("ascii")
            + b"\0"
            + canonical_bytes(value)
        )
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def _require_mac(self, label: str, value: object, observed: str) -> None:
        if not hmac.compare_digest(self._mac(label, value), observed):
            _fail("authentication_invalid")

    def _ensure_open(self) -> None:
        if self._closed:
            _fail("closed")


def _resolve_key(authority: CleanupJournalKeyIdentityPort, key_id: str) -> bytearray:
    if not callable(getattr(authority, "resolve", None)):
        _fail("key_resolver_invalid")
    try:
        value = authority.resolve(purpose=JOURNAL_KEY_PURPOSE, key_id=key_id)
    except Exception as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_key_unavailable") from exc
    if type(value) is not bytes or len(value) < 32:
        _fail("key_invalid")
    return bytearray(value)


def _stored_readback(payload_json: str) -> StrictV4CleanupAuthorityReadback:
    try:
        record = _object(payload_json)
        if set(record) != {"authority_kind", "authority_sha256", "readback"}:
            _fail("authority_invalid")
        readback = StrictV4CleanupAuthorityReadback(**dict(record["readback"]))
        authority: ManagedCleanupV4Authority = build_strict_v4_cleanup_authority(
            run_id_sha256=readback.run_id_sha256,
            context_sha256=readback.context_sha256,
            a2_terminal_sha256=readback.a2_terminal_sha256,
            expected_index_terminal_sha256=readback.expected_index_terminal_sha256,
        )
        if (
            record["authority_kind"] != authority.kind
            or record["authority_sha256"] != authority.authority_sha256
        ):
            _fail("authority_invalid")
        return readback
    except (TypeError, ValueError, KeyError) as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_authority_invalid") from exc


def _initiation(value: dict[str, object]) -> ManagedCleanupV4InitiationReceipt:
    try:
        return ManagedCleanupV4InitiationReceipt(**value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_initiation_invalid") from exc


def _terminal(value: dict[str, object]) -> ManagedCleanupV4TerminalReceipt:
    try:
        raw = value.copy()
        bindings = dict(raw["terminal_bindings"])  # type: ignore[arg-type]
        bindings["qdrant_absence_pass_sha256"] = tuple(bindings["qdrant_absence_pass_sha256"])
        bindings["graphiti_absence_pass_sha256"] = tuple(bindings["graphiti_absence_pass_sha256"])
        raw["terminal_bindings"] = ManagedCleanupV4TerminalBindings(**bindings)
        return ManagedCleanupV4TerminalReceipt(**raw)
    except (TypeError, ValueError, KeyError) as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_terminal_invalid") from exc


def _object(payload_json: str) -> dict[str, object]:
    try:
        value = json.loads(payload_json)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_json_invalid") from exc
    if type(value) is not dict:
        _fail("json_invalid")
    return value


def _json(value: object) -> str:
    return canonical_bytes(value).decode("ascii")


def _event_sha(material: object) -> str:
    return hashlib.sha256(
        b"infinity-context:strict-v4-cleanup-event:v1\0" + canonical_bytes(material)
    ).hexdigest()


def _verify_stable_file(path: Path, fd: int) -> None:
    try:
        actual, descriptor = path.lstat(), os.fstat(fd)
    except OSError as exc:
        raise ManagedCleanupV4JournalError("managed_cleanup_v4_journal_file_invalid") from exc
    if (
        stat.S_ISLNK(actual.st_mode)
        or not stat.S_ISREG(descriptor.st_mode)
        or descriptor.st_uid != os.getuid()
        or descriptor.st_nlink != 1
        or stat.S_IMODE(descriptor.st_mode) != 0o600
        or (actual.st_dev, actual.st_ino) != (descriptor.st_dev, descriptor.st_ino)
    ):
        _fail("file_invalid")


def _unlink_if_bound(path: Path, fd: int) -> None:
    """Remove only the exact file created by this descriptor, never a replacement."""

    with suppress(FileNotFoundError):
        actual, descriptor = path.lstat(), os.fstat(fd)
        if (
            not stat.S_ISLNK(actual.st_mode)
            and stat.S_ISREG(descriptor.st_mode)
            and (actual.st_dev, actual.st_ino) == (descriptor.st_dev, descriptor.st_ino)
        ):
            path.unlink()


def _fail(suffix: str) -> None:
    raise ManagedCleanupV4JournalError(f"managed_cleanup_v4_journal_{suffix}")


__all__ = (
    "CleanupJournalKeyIdentityPort",
    "JOURNAL_KEY_PURPOSE",
    "ManagedCleanupV4JournalError",
    "SCHEMA_FINGERPRINT_SHA256",
    "SQLiteManagedCleanupV4Journal",
)
