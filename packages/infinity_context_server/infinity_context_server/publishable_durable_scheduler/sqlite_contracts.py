"""Authenticated SQLite-only contracts for the standalone scheduler v4."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Final, final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerContractError,
    canonical_json,
)

SQLITE_SCHEDULER_SCHEMA_VERSION: Final = "publishable-durable-scheduler-sqlite.v1"
SQLITE_SCHEDULER_PAID_GO_READY: Final = False
SQLITE_QUERY_LIMIT: Final = 257
ANSWER_CIPHERTEXT_BYTES_CAP: Final = 1024 * 1024
_GENESIS = "0" * 64


class SchedulerSQLiteError(SchedulerContractError):
    """Stable fail-closed SQLite scheduler rejection."""


@final
@dataclass(frozen=True, slots=True)
class SchedulerSQLiteAuthenticator:
    secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.secret) is not bytes or not 32 <= len(self.secret) <= 1024:
            _fail("scheduler_sqlite_authenticator_invalid")

    def sign(self, domain: str, material: object) -> str:
        if type(domain) is not str or not domain or not domain.isascii():
            _fail("scheduler_sqlite_authenticator_domain_invalid")
        message = (
            b"memory-comparison/scheduler/sqlite/v1/"
            + domain.encode("ascii")
            + b"\0"
            + canonical_json(material)
        )
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def verify(self, domain: str, material: object, signature: object) -> bool:
        if type(signature) is not str:
            return False
        try:
            return hmac.compare_digest(self.sign(domain, material), signature)
        except (UnicodeError, ValueError):
            return False


@final
@dataclass(frozen=True, slots=True)
class SchedulerSQLiteEvent:
    event_id: int
    run_id: str
    logical_call_id: str | None
    event_kind: str
    run_version: int
    call_version: int | None
    state_sha256: str
    previous_event_sha256: str
    event_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.event_id) is not int
            or self.event_id < 1
            or type(self.run_id) is not str
            or not self.run_id
            or self.logical_call_id is not None
            and not is_sha256(self.logical_call_id)
            or type(self.event_kind) is not str
            or not self.event_kind
            or type(self.run_version) is not int
            or self.run_version < 0
            or self.call_version is not None
            and (type(self.call_version) is not int or self.call_version < 0)
            or not is_sha256(self.state_sha256)
            or not is_sha256(self.previous_event_sha256)
            or not is_sha256(self.event_sha256)
        ):
            _fail("scheduler_sqlite_event_invalid")

    def material(self) -> dict[str, object]:
        return {
            "call_version": self.call_version,
            "event_id": self.event_id,
            "event_kind": self.event_kind,
            "logical_call_id": self.logical_call_id,
            "previous_event_sha256": self.previous_event_sha256,
            "run_id": self.run_id,
            "run_version": self.run_version,
            "state_sha256": self.state_sha256,
        }


def ciphertext_material(value: bytes | None) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if type(value) is not bytes or not 1 <= len(value) <= ANSWER_CIPHERTEXT_BYTES_CAP:
        _fail("scheduler_sqlite_ciphertext_invalid")
    return hashlib.sha256(value).hexdigest(), len(value)


def require_query(limit: object, *, after: object) -> tuple[int, int]:
    if (
        type(limit) is not int
        or not 1 <= limit <= SQLITE_QUERY_LIMIT
        or type(after) is not int
        or after < -1
    ):
        _fail("scheduler_sqlite_query_invalid")
    return after, limit


def is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def genesis_event_sha256() -> str:
    return _GENESIS


def _fail(code: str) -> None:
    raise SchedulerSQLiteError(code)


__all__ = (
    "ANSWER_CIPHERTEXT_BYTES_CAP",
    "SQLITE_QUERY_LIMIT",
    "SQLITE_SCHEDULER_PAID_GO_READY",
    "SQLITE_SCHEDULER_SCHEMA_VERSION",
    "SchedulerSQLiteAuthenticator",
    "SchedulerSQLiteError",
    "SchedulerSQLiteEvent",
    "ciphertext_material",
    "genesis_event_sha256",
    "is_sha256",
    "require_query",
)
