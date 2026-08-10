"""Canonical hashing, HMAC separation, and exact SQLite schema checks."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from typing import Final, final

from infinity_context_server.publishable_durable_scheduler.contracts import canonical_json
from infinity_context_server.publishable_durable_scheduler.official_authority_contracts import (
    SchedulerOfficialAuthorityError,
)

_HASH_DOMAIN: Final = b"memory-comparison/scheduler/official-authority/hash/v1/"
_HMAC_DOMAIN: Final = b"memory-comparison/scheduler/official-authority/hmac/v1/"
_MAX_KEY_BYTES: Final = 1024


@final
class SchedulerOfficialAuthorityAuthenticator:
    """Purpose-separated HMAC-SHA256 authority authenticator."""

    __slots__ = ("_kind", "_secret")

    def __init__(self, secret: bytes, *, kind: str) -> None:
        if (
            type(secret) is not bytes
            or not 32 <= len(secret) <= _MAX_KEY_BYTES
            or type(kind) is not str
            or not kind
            or not kind.isascii()
        ):
            _fail("scheduler_official_authority_authenticator_invalid")
        self._secret = secret
        self._kind = kind.encode("ascii")

    def sign(self, purpose: str, material: object) -> str:
        if type(purpose) is not str or not purpose or not purpose.isascii():
            _fail("scheduler_official_authority_hmac_domain_invalid")
        message = (
            _HMAC_DOMAIN
            + self._kind
            + b"/"
            + purpose.encode("ascii")
            + b"\0"
            + canonical_json(material)
        )
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def verify(self, purpose: str, material: object, signature: object) -> bool:
        if type(signature) is not str:
            return False
        try:
            return hmac.compare_digest(self.sign(purpose, material), signature)
        except (TypeError, UnicodeError, ValueError):
            return False


@final
class OrderedAuthorityRoot:
    """Incremental canonical root with explicit item framing and final count."""

    __slots__ = ("_count", "_state")

    def __init__(self, purpose: str) -> None:
        if type(purpose) is not str or not purpose or not purpose.isascii():
            _fail("scheduler_official_authority_hash_domain_invalid")
        self._state = hashlib.sha256(_HASH_DOMAIN + purpose.encode("ascii") + b"\0")
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def add(self, value: object) -> None:
        encoded = canonical_json(value)
        self._state.update(len(encoded).to_bytes(8, "big"))
        self._state.update(encoded)
        self._count += 1

    def finish(self) -> str:
        state = self._state.copy()
        state.update(self._count.to_bytes(8, "big"))
        return state.hexdigest()


def authority_digest(purpose: str, material: object) -> str:
    if type(purpose) is not str or not purpose or not purpose.isascii():
        _fail("scheduler_official_authority_hash_domain_invalid")
    return hashlib.sha256(
        _HASH_DOMAIN + purpose.encode("ascii") + b"\0" + canonical_json(material)
    ).hexdigest()


def ordered_root(purpose: str, values: Iterable[object]) -> tuple[str, int]:
    """Hash a stream with length framing; no row collection is retained."""

    root = OrderedAuthorityRoot(purpose)
    for value in values:
        root.add(value)
    return root.finish(), root.count


def canonical_text(value: object) -> str:
    return canonical_json(value).decode("ascii")


def canonical_mapping(value: object, *, code: str) -> dict[str, object]:
    if type(value) is not str:
        _fail(code)
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise SchedulerOfficialAuthorityError(code) from error
    if type(decoded) is not dict or canonical_text(decoded) != value:
        _fail(code)
    return decoded


def schema_fingerprint(statements: tuple[str, ...]) -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in statements:
            connection.execute(statement)
        return _schema_fingerprint(connection)
    finally:
        connection.close()


def validate_schema(connection: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    try:
        if _schema_fingerprint(connection) != schema_fingerprint(statements):
            _fail("scheduler_official_authority_schema_invalid")
        quick = connection.execute("PRAGMA quick_check").fetchone()
        foreign = connection.execute("PRAGMA foreign_key_check").fetchone()
    except sqlite3.DatabaseError as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_database_integrity_invalid"
        ) from error
    if quick is None or quick[0] != "ok" or foreign is not None:
        _fail("scheduler_official_authority_database_integrity_invalid")


def create_schema(connection: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    try:
        existing = _user_schema(connection)
        if existing:
            _fail("scheduler_official_authority_schema_invalid")
        for statement in statements:
            connection.execute(statement)
    except sqlite3.DatabaseError as error:
        raise SchedulerOfficialAuthorityError(
            "scheduler_official_authority_schema_invalid"
        ) from error
    if _schema_fingerprint(connection) != schema_fingerprint(statements):
        _fail("scheduler_official_authority_schema_invalid")


@contextmanager
def immediate_transaction(connection: sqlite3.Connection):
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def require_exact_keys(value: Mapping[str, object], expected: frozenset[str], *, code: str) -> None:
    if type(value) is not dict or frozenset(value) != expected:
        _fail(code)


def require_digest(value: object, *, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(code)
    return value


def require_int(value: object, *, minimum: int = 0, code: str) -> int:
    if type(value) is not int or value < minimum:
        _fail(code)
    return value


def _schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT type,name,tbl_name,sql FROM sqlite_master
           WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"""
    ).fetchall()
    material = [list(row) for row in rows]
    return hashlib.sha256(canonical_json(material)).hexdigest()


def _user_schema(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            """SELECT type,name FROM sqlite_master
               WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"""
        )
    )


def _fail(code: str) -> None:
    raise SchedulerOfficialAuthorityError(code)


__all__ = (
    "OrderedAuthorityRoot",
    "SchedulerOfficialAuthorityAuthenticator",
    "authority_digest",
    "canonical_mapping",
    "canonical_text",
    "create_schema",
    "immediate_transaction",
    "ordered_root",
    "require_digest",
    "require_exact_keys",
    "require_int",
    "schema_fingerprint",
    "validate_schema",
)
