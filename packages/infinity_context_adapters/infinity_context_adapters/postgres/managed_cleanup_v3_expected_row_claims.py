"""Durable authenticated claims for cleanup-v3 expected-row verification."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
    commitment,
    digest,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authentication import (
    expected_index_row_tag,
)

_CLAIM_DOMAIN: Final = b"managed-cleanup-v4/expected-row-claim/v1\0"
CLAIM_PAGE_SIZE: Final = 512
_FINALIZATION_DOMAIN: Final = b"managed-cleanup-v4/expected-row-finalization/v1\0"
_SESSION_DOMAIN: Final = b"managed-cleanup-v4/expected-row-session/v1\0"
_CLAIM_KINDS: Final = (
    "memory_scopes",
    "memory_threads",
    "facts",
    "fact_source_refs",
    "documents",
    "chunks",
)
_LOCATOR_FIELDS: Final = {
    "memory_scopes": ("id",),
    "memory_threads": ("id",),
    "facts": ("id",),
    "fact_source_refs": ("id", "fact_id", "fact_version"),
    "documents": ("id",),
    "chunks": ("id",),
}
_CLAIM_ORDER: Final = {
    "memory_scopes": "authority_item",
    "memory_threads": "authority_item",
    "facts": "CAST(authority_item AS INTEGER),authority_item",
    "fact_source_refs": "CAST(authority_item AS INTEGER),authority_item",
    "documents": "CAST(authority_item AS INTEGER),authority_item",
    "chunks": (
        "CAST(substr(authority_item,1,instr(authority_item,':')-1) AS INTEGER),"
        "CAST(substr(authority_item,instr(authority_item,':')+1) AS INTEGER),"
        "authority_item"
    ),
}


@dataclass(slots=True)
class ExpectedRowClaimMetrics:
    """Bounded instrumentation for durable claim page checkpoints."""

    claim_checkpoints: int = 0
    max_pending_claims: int = 0


def create_claim_schema(state_db: sqlite3.Connection) -> None:
    """Create mutable claim state separately from the sealed authority index."""
    if not isinstance(state_db, sqlite3.Connection):
        _fail("claims_connection_invalid")
    state_db.executescript(
        """
        CREATE TABLE verification_claims(
            kind TEXT NOT NULL,
            authority_item TEXT NOT NULL,
            locator_sha TEXT NOT NULL,
            claim_mac TEXT NOT NULL,
            PRIMARY KEY(kind, authority_item),
            UNIQUE(kind, locator_sha)
        ) STRICT;
        CREATE TABLE verification_session(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            state TEXT NOT NULL CHECK(state IN ('active','finalized')),
            session_sha TEXT NOT NULL,
            terminal_sha TEXT NOT NULL,
            session_mac TEXT NOT NULL
        ) STRICT;
        """
    )


@final
class DurableExpectedRowClaims:
    """Record order-independent, exact-once evidence claims in the index."""

    def __init__(
        self,
        authority_db: sqlite3.Connection,
        state_db: sqlite3.Connection,
        key: bytes,
        terminal: str,
        *,
        metrics: ExpectedRowClaimMetrics | None = None,
    ) -> None:
        if (
            not isinstance(authority_db, sqlite3.Connection)
            or not isinstance(state_db, sqlite3.Connection)
            or authority_db is state_db
        ):
            _fail("claims_connection_invalid")
        if type(key) is not bytes or len(key) < 32:
            _fail("claims_authentication_key_invalid")
        try:
            self._terminal = digest(terminal)
        except ManagedCleanupV3Error as exc:
            raise ManagedCleanupV3Error(
                "managed_cleanup_v3_expected_index_claims_terminal_invalid"
            ) from exc
        self._authority_db = authority_db
        self._state_db = state_db
        self._key = bytearray(key)
        self.metrics = metrics or ExpectedRowClaimMetrics()
        self._pending_claims = 0
        self._page_session: str | None = None
        self._closed = False

    def close(self) -> None:
        """Erase the held authentication key and reject further operations."""
        if not self._closed:
            self._rollback_page()
            for index in range(len(self._key)):
                self._key[index] = 0
            self._closed = True

    def verify_index_row(
        self,
        context_sha256: str,
        table: str,
        values: Sequence[object],
        authentication_tag: str,
    ) -> None:
        self._ensure_open()
        expected = expected_index_row_tag(
            self._key,
            context_sha256=context_sha256,
            authority_terminal_sha256=self._terminal,
            table=table,
            values=values,
        )
        if not hmac.compare_digest(authentication_tag, expected):
            _fail("authority_row_authentication_invalid")

    def begin(self, session_sha: str, *, reset_authorized: bool = False) -> None:
        """Start a session, discarding partial claims from a different session."""
        self._ensure_open()
        if type(reset_authorized) is not bool:
            _fail("session_reset_invalid")
        session = _session_sha(session_sha)
        if self._page_session is not None:
            if self._page_session == session and not reset_authorized:
                _fail("claims_page_unflushed")
            self._rollback_page()
        with self._state_db:
            row = self._session_row()
            if row is not None:
                state, current = self._authenticate_session(row)
                if current == session:
                    return
                if state == "finalized" and not reset_authorized:
                    _fail("session_finalized")
                self._state_db.execute("DELETE FROM verification_claims")
                self._state_db.execute("DELETE FROM verification_session WHERE singleton=1")
            elif (
                self._state_db.execute("SELECT 1 FROM verification_claims LIMIT 1").fetchone()
                is not None
            ):
                _fail("session_authentication_invalid")
            self._state_db.execute(
                "INSERT INTO verification_session"
                "(singleton,state,session_sha,terminal_sha,session_mac) "
                "VALUES(1,'active',?,?,?)",
                (session, self._terminal, self._session_mac("active", session)),
            )

    def claim(
        self,
        session_sha: str,
        kind: str,
        authority_item: str | int,
        locator_json: Mapping[str, object],
    ) -> None:
        """Persist a claim, accepting only an exact replay of an existing claim."""
        self._ensure_open()
        session = _session_sha(session_sha)
        item = _authority_item(authority_item)
        locator_sha = _locator_sha(kind, locator_json)
        claim_mac = self._claim_mac(session, kind, item, locator_sha)
        self._begin_page(session)
        try:
            state, _current = self._require_session(session)
            existing = self._state_db.execute(
                "SELECT locator_sha, claim_mac FROM verification_claims "
                "WHERE kind=? AND authority_item=?",
                (kind, item),
            ).fetchone()
            if existing is not None:
                self._authenticate_claim(session, kind, item, str(existing[0]), str(existing[1]))
                if str(existing[0]) != locator_sha:
                    _fail("claim_conflict")
                return
            if state == "finalized":
                _fail("claims_finalized")
            try:
                self._state_db.execute(
                    "INSERT INTO verification_claims"
                    "(kind,authority_item,locator_sha,claim_mac) VALUES(?,?,?,?)",
                    (kind, item, locator_sha, claim_mac),
                )
                self._pending_claims += 1
                self.metrics.max_pending_claims = max(
                    self.metrics.max_pending_claims, self._pending_claims
                )
                if self._pending_claims == CLAIM_PAGE_SIZE:
                    self._checkpoint_page()
            except sqlite3.IntegrityError as exc:
                raise ManagedCleanupV3Error(
                    "managed_cleanup_v3_expected_index_claim_conflict"
                ) from exc
        except BaseException:
            self._rollback_page()
            raise

    def flush_verification_page(self, session_sha: str) -> None:
        """Durably checkpoint the current bounded claim page."""
        self._ensure_open()
        session = _session_sha(session_sha)
        if self._page_session is None:
            self._require_session(session)
            return
        if self._page_session != session:
            _fail("session_conflict")
        self._require_session(session)
        self._checkpoint_page()

    def finalize(self, session_sha: str) -> None:
        """Authenticate all claims, require exact coverage, and seal the set."""
        self._ensure_open()
        session = _session_sha(session_sha)
        if self._page_session is not None or self._state_db.in_transaction:
            _fail("claims_page_unflushed")
        with self._state_db:
            state, _current = self._require_session(session)
            claims_sha, claim_count = self._authenticated_claims_sha(session)
            if self._verify_coverage() != claim_count:
                _fail("claims_coverage_incomplete")
            finalization_mac = self._session_mac("finalized", session, claims_sha)
            if state == "finalized":
                row = self._session_row()
                if row is None or not hmac.compare_digest(str(row[3]), finalization_mac):
                    _fail("finalization_authentication_invalid")
                return
            updated = self._state_db.execute(
                "UPDATE verification_session SET state='finalized',session_mac=? "
                "WHERE singleton=1 AND state='active' AND session_sha=?",
                (finalization_mac, session),
            )
            if updated.rowcount != 1:
                _fail("finalization_conflict")

    def abort(self, session_sha: str) -> None:
        """Atomically discard partial claims for the matching active session."""
        self._ensure_open()
        session = _session_sha(session_sha)
        if self._page_session is not None:
            if self._page_session != session:
                _fail("session_conflict")
            self._rollback_page()
        with self._state_db:
            row = self._session_row()
            if row is None:
                return
            _state, current = self._authenticate_session(row)
            if current != session:
                _fail("session_conflict")
            self._state_db.execute("DELETE FROM verification_claims")
            self._state_db.execute("DELETE FROM verification_session WHERE singleton=1")

    def _begin_page(self, session: str) -> None:
        if self._page_session is not None:
            if self._page_session != session:
                _fail("session_conflict")
            return
        if self._state_db.in_transaction:
            _fail("claims_transaction_invalid")
        self._state_db.execute("BEGIN IMMEDIATE")
        self._page_session = session

    def _checkpoint_page(self) -> None:
        pending = self._pending_claims
        if self._page_session is None:
            return
        try:
            self._state_db.commit()
        except BaseException:
            self._rollback_page()
            raise
        self._page_session = None
        self._pending_claims = 0
        if pending:
            self.metrics.claim_checkpoints += 1

    def _rollback_page(self) -> None:
        if self._page_session is not None or self._state_db.in_transaction:
            self._state_db.rollback()
        self._page_session = None
        self._pending_claims = 0

    def _claim_mac(self, session: str, kind: str, item: str, locator_sha: str) -> str:
        payload = canonical_bytes(
            {
                "terminal_sha": self._terminal,
                "session_sha": session,
                "kind": kind,
                "authority_item": item,
                "locator_sha": locator_sha,
            }
        )
        return hmac.new(self._key, _CLAIM_DOMAIN + payload, hashlib.sha256).hexdigest()

    def _authenticate_claim(
        self, session: str, kind: str, item: str, locator_sha: str, claim_mac: str
    ) -> None:
        if kind not in _CLAIM_KINDS or not hmac.compare_digest(
            claim_mac, self._claim_mac(session, kind, item, locator_sha)
        ):
            _fail("claim_authentication_invalid")

    def _authenticated_claims_sha(self, session: str) -> tuple[str, int]:
        state = hashlib.sha256(b"managed-cleanup-v4/expected-row-claims/v1\0")
        state.update(bytes.fromhex(session))
        count = 0
        for kind in _CLAIM_KINDS:
            rows = self._state_db.execute(
                "SELECT kind,authority_item,locator_sha,claim_mac "
                "FROM verification_claims "
                f"WHERE kind=? ORDER BY {_CLAIM_ORDER[kind]}",
                (kind,),
            )
            for row_kind, item, locator_sha, claim_mac in rows:
                values = (str(row_kind), str(item), str(locator_sha), str(claim_mac))
                self._authenticate_claim(session, *values)
                material = canonical_bytes(values[:3])
                state.update(len(material).to_bytes(8, "big"))
                state.update(material)
                count += 1
        unknown = self._state_db.execute(
            "SELECT kind,authority_item,locator_sha,claim_mac "
            "FROM verification_claims WHERE kind NOT IN (?,?,?,?,?,?) "
            "ORDER BY kind,authority_item",
            _CLAIM_KINDS,
        )
        for kind, item, locator_sha, claim_mac in unknown:
            self._authenticate_claim(
                session, str(kind), str(item), str(locator_sha), str(claim_mac)
            )
        return state.hexdigest(), count

    def _session_mac(self, state: str, session: str, claims_sha: str | None = None) -> str:
        payload = {
            "state": state,
            "session_sha": session,
            "terminal_sha": self._terminal,
            "ordered_claims_sha256": claims_sha,
        }
        domain = _FINALIZATION_DOMAIN if state == "finalized" else _SESSION_DOMAIN
        return hmac.new(self._key, domain + canonical_bytes(payload), hashlib.sha256).hexdigest()

    def _session_row(self) -> tuple[object, ...] | None:
        return self._state_db.execute(
            "SELECT state,session_sha,terminal_sha,session_mac "
            "FROM verification_session WHERE singleton=1"
        ).fetchone()

    def _authenticate_session(self, row: tuple[object, ...]) -> tuple[str, str]:
        state, session, terminal, session_mac = (str(value) for value in row)
        claims_sha = None
        if state == "finalized":
            claims_sha, _count = self._authenticated_claims_sha(session)
        if (
            state not in ("active", "finalized")
            or terminal != self._terminal
            or not hmac.compare_digest(session_mac, self._session_mac(state, session, claims_sha))
        ):
            _fail("session_authentication_invalid")
        return state, session

    def _require_session(self, session: str) -> tuple[str, str]:
        row = self._session_row()
        if row is None:
            _fail("session_missing")
        state, current = self._authenticate_session(row)
        if current != session:
            _fail("session_conflict")
        return state, current

    def _verify_coverage(self) -> int:
        matched = 0
        for kind in ("memory_scopes", "memory_threads"):
            matched += self._merge_kind(
                kind,
                _CLAIM_ORDER[kind],
                "SELECT corpus_sha FROM corpora ORDER BY corpus_sha",
            )
        for kind in ("facts", "fact_source_refs"):
            matched += self._merge_kind(
                kind,
                _CLAIM_ORDER[kind],
                "SELECT CAST(sequence AS TEXT) FROM operations WHERE lane='fact' ORDER BY sequence",
            )
        matched += self._merge_kind(
            "documents",
            _CLAIM_ORDER["documents"],
            "SELECT CAST(sequence AS TEXT) FROM operations WHERE lane='document' ORDER BY sequence",
        )
        matched += self._merge_kind(
            "chunks",
            _CLAIM_ORDER["chunks"],
            "SELECT CAST(sequence AS TEXT)||':'||CAST(ordinal AS TEXT) "
            "FROM fragments ORDER BY sequence,ordinal",
        )
        return matched

    def _merge_kind(self, kind: str, claim_order: str, authority_sql: str) -> int:
        claims = iter(
            self._state_db.execute(
                "SELECT authority_item FROM verification_claims "
                f"WHERE kind=? ORDER BY {claim_order}",
                (kind,),
            )
        )
        expected = iter(self._authority_db.execute(authority_sql))
        count = 0
        while True:
            claim_row = next(claims, None)
            expected_row = next(expected, None)
            if claim_row is None or expected_row is None:
                if claim_row is not None or expected_row is not None:
                    _fail("claims_coverage_incomplete")
                return count
            if str(claim_row[0]) != str(expected_row[0]):
                _fail("claims_coverage_incomplete")
            count += 1

    def _ensure_open(self) -> None:
        if self._closed:
            _fail("claims_closed")


def _authority_item(value: str | int) -> str:
    if type(value) is int and value >= 0:
        return str(value)
    if type(value) is str and value and value.strip() == value:
        return value
    _fail("claim_authority_item_invalid")


def _session_sha(value: str) -> str:
    try:
        return digest(value)
    except ManagedCleanupV3Error as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_expected_index_session_invalid") from exc


def _locator_sha(kind: str, locator_json: Mapping[str, object]) -> str:
    if kind not in _CLAIM_KINDS or not isinstance(locator_json, Mapping):
        _fail("claim_locator_invalid")
    supplied = dict(locator_json)
    try:
        locator = {field: supplied[field] for field in _LOCATOR_FIELDS[kind]}
        if supplied != locator:
            _fail("claim_locator_invalid")
        if any(value is None for value in locator.values()):
            _fail("claim_locator_invalid")
        return commitment("inventory-locator/v4", {"kind": kind, "locator": locator})
    except (KeyError, ManagedCleanupV3Error) as exc:
        raise ManagedCleanupV3Error(
            "managed_cleanup_v3_expected_index_claim_locator_invalid"
        ) from exc


def _fail(suffix: str) -> None:
    raise ManagedCleanupV3Error(f"managed_cleanup_v3_expected_index_{suffix}")


__all__ = (
    "CLAIM_PAGE_SIZE",
    "DurableExpectedRowClaims",
    "ExpectedRowClaimMetrics",
    "create_claim_schema",
)
