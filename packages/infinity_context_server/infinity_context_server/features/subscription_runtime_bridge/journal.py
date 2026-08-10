"""HMAC-chained private SQLite intent/result journal for one-shot bridge calls."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from heapq import merge
from pathlib import Path
from types import TracebackType
from typing import Self

from .contracts import (
    AuthenticatedBridgeResult,
    BridgeCallBinding,
    BridgeDivergenceError,
    BridgeIntent,
    BridgeJournalError,
    BridgeOutcome,
    BridgeReceiptError,
    NotFound,
    OutcomeUnknown,
    TerminalOutcome,
    TokenUsage,
)
from .journal_schema import (
    SCHEMA_VERSION,
    configure_connection,
    create_schema,
    expected_schema_fingerprint,
    validate_schema,
)
from .json_boundary import canonical_json_bytes
from .secure_sqlite import (
    close_private_sqlite,
    create_private_sqlite,
    fsync_private_sqlite,
    open_private_sqlite,
    unlink_bound_private_sqlite,
    verify_private_sqlite,
)


class HmacJournalIntegrity:
    """Non-serializable HMAC capability for journal rows and the event head."""

    __slots__ = ("__key",)

    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise BridgeJournalError("bridge_journal_integrity_key_invalid")
        self.__key = bytes(key)

    def digest(self, value: bytes) -> str:
        return hmac.new(self.__key, value, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class IntentClaim:
    dispatch_granted: bool
    outcome: OutcomeUnknown | TerminalOutcome


@dataclass(frozen=True, slots=True)
class BridgeJournalStatistics:
    """Bounded aggregate used to bind a scheduler store set to one journal."""

    intent_count: int
    result_count: int
    event_count: int

    def __post_init__(self) -> None:
        if (
            type(self.intent_count) is not int
            or type(self.result_count) is not int
            or type(self.event_count) is not int
            or min(self.intent_count, self.result_count, self.event_count) < 0
            or self.result_count > self.intent_count
            or self.event_count != self.intent_count + self.result_count
        ):
            raise BridgeJournalError("bridge_journal_statistics_invalid")


class BridgeJournal:
    """Durable no-redispatch authority with exact replay and authenticated rows."""

    __slots__ = (
        "_checkpoint",
        "_closed",
        "_connection",
        "_descriptor",
        "_integrity",
        "_lock",
        "_path",
        "_pending_checkpoint",
    )

    def __init__(
        self,
        *,
        path: Path,
        connection: sqlite3.Connection,
        descriptor: int,
        integrity: HmacJournalIntegrity,
    ) -> None:
        self._path = path
        self._connection = connection
        self._descriptor = descriptor
        self._integrity = integrity
        self._lock = threading.RLock()
        self._closed = False
        self._checkpoint: tuple[int, str] | None = None
        self._pending_checkpoint: tuple[int, str] | None = None

    @classmethod
    def create(cls, path: Path, *, integrity: HmacJournalIntegrity) -> Self:
        connection, descriptor = create_private_sqlite(path)
        try:
            configure_connection(connection)
            create_schema(connection)
            fingerprint = expected_schema_fingerprint()
            root = integrity.digest(b"bridge-journal-root-v1\0" + fingerprint.encode("ascii"))
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO bridge_journal_metadata (
                       singleton, schema_version, schema_fingerprint_sha256,
                       event_count, head_hmac_sha256
                   ) VALUES (1, ?, ?, 0, ?)""",
                (SCHEMA_VERSION, fingerprint, root),
            )
            written = connection.execute(
                "SELECT * FROM bridge_journal_metadata WHERE singleton = 1"
            ).fetchone()
            if (
                written is None
                or written["schema_version"] != SCHEMA_VERSION
                or written["schema_fingerprint_sha256"] != fingerprint
                or written["event_count"] != 0
                or written["head_hmac_sha256"] != root
            ):
                raise BridgeJournalError("bridge_journal_metadata_readback_invalid")
            connection.commit()
            fsync_private_sqlite(path, descriptor)
            journal = cls(
                path=path,
                connection=connection,
                descriptor=descriptor,
                integrity=integrity,
            )
            journal._validate_current()
            return journal
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            with suppress(BridgeJournalError, OSError):
                unlink_bound_private_sqlite(path, descriptor)
            close_private_sqlite(connection, descriptor)
            raise

    @classmethod
    def open(cls, path: Path, *, integrity: HmacJournalIntegrity) -> Self:
        connection, descriptor = open_private_sqlite(path)
        try:
            configure_connection(connection)
            journal = cls(
                path=path,
                connection=connection,
                descriptor=descriptor,
                integrity=integrity,
            )
            journal._validate_current()
            return journal
        except BaseException:
            close_private_sqlite(connection, descriptor)
            raise

    def record_intent(self, intent: BridgeIntent) -> IntentClaim:
        with self._lock, self._transaction(immediate=True):
            existing_row = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE intent_id = ?",
                (intent.binding.intent_id,),
            ).fetchone()
            if existing_row is not None:
                existing = self._authenticated_intent(existing_row)
                if existing != intent:
                    raise BridgeDivergenceError("bridge_journal_intent_divergence")
                return IntentClaim(False, self._outcome_for(existing))
            logical_row = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE logical_call_id = ?",
                (intent.binding.logical_call_id,),
            ).fetchone()
            if logical_row is not None:
                self._authenticated_intent(logical_row)
                raise BridgeDivergenceError("bridge_journal_logical_call_divergence")
            sequence, previous_head = self._next_event()
            row_hmac = self._intent_hmac(intent, sequence)
            self._connection.execute(
                """INSERT INTO bridge_intents (
                       intent_id, event_sequence, logical_operation, logical_call_id,
                       pool_id, pool_authority_sha256, bridge_id, bridge_authority_sha256,
                       request_body_sha256, prompt_input_sha256, response_format_type,
                       response_format_sha256, response_schema_sha256, output_token_limit,
                       row_hmac_sha256
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _intent_values(intent, sequence, row_hmac),
            )
            self._advance_head(sequence, previous_head, row_hmac)
            readback = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE intent_id = ?",
                (intent.binding.intent_id,),
            ).fetchone()
            if readback is None or self._authenticated_intent(readback) != intent:
                raise BridgeJournalError("bridge_journal_intent_readback_invalid")
        fsync_private_sqlite(self._path, self._descriptor)
        return IntentClaim(True, OutcomeUnknown(intent))

    def record_result(
        self,
        intent: BridgeIntent,
        result: AuthenticatedBridgeResult,
    ) -> TerminalOutcome:
        with self._lock, self._transaction(immediate=True):
            intent_row = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE intent_id = ?",
                (intent.binding.intent_id,),
            ).fetchone()
            if intent_row is None:
                raise BridgeJournalError("bridge_journal_result_without_intent")
            persisted_intent = self._authenticated_intent(intent_row)
            if persisted_intent != intent:
                raise BridgeDivergenceError("bridge_journal_intent_divergence")
            existing_row = self._connection.execute(
                "SELECT * FROM bridge_results WHERE intent_id = ?",
                (intent.binding.intent_id,),
            ).fetchone()
            if existing_row is not None:
                existing = self._authenticated_result(existing_row)
                if existing != result:
                    raise BridgeDivergenceError("bridge_journal_result_divergence")
                return TerminalOutcome(intent, existing)
            sequence, previous_head = self._next_event()
            row_hmac = self._result_hmac(intent.binding.intent_id, result, sequence)
            self._connection.execute(
                """INSERT INTO bridge_results (
                       intent_id, event_sequence, response_body_sha256, output_text_sha256,
                       attestation_sha256, receipt_hmac_sha256, thread_id, turn_id,
                       prompt_tokens, cached_tokens, cache_write_tokens, completion_tokens,
                       reasoning_tokens, total_tokens, encrypted_output, row_hmac_sha256
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                _result_values(intent.binding.intent_id, result, sequence, row_hmac),
            )
            self._advance_head(sequence, previous_head, row_hmac)
            readback = self._connection.execute(
                "SELECT * FROM bridge_results WHERE intent_id = ?",
                (intent.binding.intent_id,),
            ).fetchone()
            if readback is None or self._authenticated_result(readback) != result:
                raise BridgeJournalError("bridge_journal_result_readback_invalid")
        fsync_private_sqlite(self._path, self._descriptor)
        return TerminalOutcome(intent, result)

    def lookup_outcome(self, intent_id: str) -> BridgeOutcome:
        if not isinstance(intent_id, str) or not intent_id:
            raise BridgeJournalError("bridge_journal_lookup_intent_id_invalid")
        with self._lock, self._transaction(immediate=False):
            row = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if row is None:
                return NotFound(intent_id)
            return self._outcome_for(self._authenticated_intent(row))

    def lookup_logical_call(self, logical_call_id: str) -> BridgeOutcome | None:
        """Read one uniquely bound logical call without scanning journal history."""

        if not isinstance(logical_call_id, str) or not logical_call_id:
            raise BridgeJournalError("bridge_journal_lookup_logical_call_id_invalid")
        with self._lock, self._transaction(immediate=False):
            rows = self._connection.execute(
                "SELECT * FROM bridge_intents WHERE logical_call_id = ? LIMIT 2",
                (logical_call_id,),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise BridgeDivergenceError("bridge_journal_logical_call_divergence")
            return self._outcome_for(self._authenticated_intent(rows[0]))

    def audit(self) -> None:
        """Perform an explicit bounded-memory audit of the complete HMAC chain."""

        self._validate_current(full=True)

    def statistics(self) -> BridgeJournalStatistics:
        """Return authenticated constant-memory counts without exposing private rows."""

        with self._lock, self._transaction(immediate=False):
            metadata = self._connection.execute(
                "SELECT event_count FROM bridge_journal_metadata WHERE singleton = 1"
            ).fetchone()
            intents = self._connection.execute("SELECT COUNT(*) FROM bridge_intents").fetchone()
            results = self._connection.execute("SELECT COUNT(*) FROM bridge_results").fetchone()
            if metadata is None or intents is None or results is None:
                raise BridgeJournalError("bridge_journal_statistics_invalid")
            return BridgeJournalStatistics(
                intent_count=intents[0],
                result_count=results[0],
                event_count=metadata["event_count"],
            )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._validate_current(full=True)
                verify_private_sqlite(self._path, self._descriptor)
            finally:
                close_private_sqlite(self._connection, self._descriptor)
                self._closed = True

    def destroy(self) -> None:
        """Authenticate and unlink only the exact still-bound private journal inode."""

        with self._lock:
            self._assert_open()
            try:
                self._validate_current(full=True)
                unlink_bound_private_sqlite(self._path, self._descriptor)
            finally:
                close_private_sqlite(self._connection, self._descriptor)
                self._closed = True

    def __enter__(self) -> Self:
        self._assert_open()
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def _transaction(self, *, immediate: bool) -> Iterator[None]:
        self._assert_open()
        verify_private_sqlite(self._path, self._descriptor)
        try:
            self._connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            if self._checkpoint is None:
                self._validate_integrity()
            else:
                self._validate_cached_checkpoint()
            self._pending_checkpoint = None
            yield
            self._validate_pending_checkpoint()
            self._connection.commit()
            if self._pending_checkpoint is not None:
                self._checkpoint = self._pending_checkpoint
            self._pending_checkpoint = None
        except (BridgeDivergenceError, BridgeJournalError):
            if self._connection.in_transaction:
                self._connection.rollback()
            self._pending_checkpoint = None
            raise
        except (sqlite3.Error, BridgeReceiptError, ValueError, TypeError, OverflowError) as exc:
            if self._connection.in_transaction:
                self._connection.rollback()
            self._pending_checkpoint = None
            raise BridgeJournalError("bridge_journal_operation_invalid") from exc
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            self._pending_checkpoint = None
            raise
        verify_private_sqlite(self._path, self._descriptor)

    def _validate_current(self, *, full: bool = True) -> None:
        with self._lock, self._transaction(immediate=False):
            if full:
                self._validate_integrity()

    def _validate_integrity(self) -> None:
        validate_schema(self._connection)
        metadata_rows = self._connection.execute("SELECT * FROM bridge_journal_metadata").fetchall()
        fingerprint = expected_schema_fingerprint()
        if len(metadata_rows) != 1:
            raise BridgeJournalError("bridge_journal_metadata_invalid")
        metadata = metadata_rows[0]
        if (
            metadata["singleton"] != 1
            or metadata["schema_version"] != SCHEMA_VERSION
            or metadata["schema_fingerprint_sha256"] != fingerprint
            or type(metadata["event_count"]) is not int
            or metadata["event_count"] < 0
        ):
            raise BridgeJournalError("bridge_journal_metadata_invalid")
        head = self._integrity.digest(b"bridge-journal-root-v1\0" + fingerprint.encode("ascii"))
        observed_count = 0
        events = merge(self._authenticated_intent_events(), self._authenticated_result_events())
        for expected_sequence, (sequence, row_hmac) in enumerate(events, start=1):
            if sequence != expected_sequence:
                raise BridgeJournalError("bridge_journal_event_sequence_invalid")
            head = self._head_hmac(sequence, head, row_hmac)
            observed_count = expected_sequence
        if observed_count != metadata["event_count"]:
            raise BridgeJournalError("bridge_journal_event_count_invalid")
        if not _safe_hmac_equal(metadata["head_hmac_sha256"], head):
            raise BridgeJournalError("bridge_journal_head_hmac_invalid")
        self._checkpoint = (observed_count, head)

    def _validate_cached_checkpoint(self) -> None:
        checkpoint = self._checkpoint
        if checkpoint is None:
            raise BridgeJournalError("bridge_journal_checkpoint_missing")
        metadata = self._connection.execute(
            "SELECT event_count, head_hmac_sha256 FROM bridge_journal_metadata WHERE singleton = 1"
        ).fetchone()
        if metadata is None:
            raise BridgeJournalError("bridge_journal_checkpoint_changed")
        if metadata["event_count"] != checkpoint[0] or not _safe_hmac_equal(
            metadata["head_hmac_sha256"], checkpoint[1]
        ):
            # A second authenticated process may have appended events.  Accept
            # the new head only after a complete chain audit; forged or rolled
            # back metadata therefore remains fail-closed.
            self._validate_integrity()

    def _validate_pending_checkpoint(self) -> None:
        expected = self._pending_checkpoint or self._checkpoint
        if expected is None:
            raise BridgeJournalError("bridge_journal_checkpoint_missing")
        metadata = self._connection.execute(
            "SELECT event_count, head_hmac_sha256 FROM bridge_journal_metadata WHERE singleton = 1"
        ).fetchone()
        if (
            metadata is None
            or metadata["event_count"] != expected[0]
            or not _safe_hmac_equal(metadata["head_hmac_sha256"], expected[1])
        ):
            raise BridgeJournalError("bridge_journal_checkpoint_update_invalid")

    def _authenticated_intent_events(self) -> Iterator[tuple[int, str]]:
        for row in self._connection.execute("SELECT * FROM bridge_intents ORDER BY event_sequence"):
            intent = _intent_from_row(row)
            sequence = _event_sequence(row)
            expected = self._intent_hmac(intent, sequence)
            if not _safe_hmac_equal(row["row_hmac_sha256"], expected):
                raise BridgeJournalError("bridge_journal_intent_hmac_invalid")
            yield sequence, expected

    def _authenticated_result_events(self) -> Iterator[tuple[int, str]]:
        for row in self._connection.execute("SELECT * FROM bridge_results ORDER BY event_sequence"):
            intent_id = row["intent_id"]
            if not isinstance(intent_id, str):
                raise BridgeJournalError("bridge_journal_result_intent_invalid")
            result = _result_from_row(row)
            sequence = _event_sequence(row)
            expected = self._result_hmac(intent_id, result, sequence)
            if not _safe_hmac_equal(row["row_hmac_sha256"], expected):
                raise BridgeJournalError("bridge_journal_result_hmac_invalid")
            yield sequence, expected

    def _outcome_for(self, intent: BridgeIntent) -> OutcomeUnknown | TerminalOutcome:
        row = self._connection.execute(
            "SELECT * FROM bridge_results WHERE intent_id = ?",
            (intent.binding.intent_id,),
        ).fetchone()
        if row is None:
            return OutcomeUnknown(intent)
        return TerminalOutcome(intent, self._authenticated_result(row))

    def _next_event(self) -> tuple[int, str]:
        metadata = self._connection.execute(
            "SELECT event_count, head_hmac_sha256 FROM bridge_journal_metadata WHERE singleton = 1"
        ).fetchone()
        if metadata is None:
            raise BridgeJournalError("bridge_journal_metadata_invalid")
        return metadata["event_count"] + 1, metadata["head_hmac_sha256"]

    def _advance_head(self, sequence: int, previous_head: str, row_hmac: str) -> None:
        checkpoint = self._checkpoint
        if (
            checkpoint is None
            or self._pending_checkpoint is not None
            or sequence != checkpoint[0] + 1
            or not hmac.compare_digest(previous_head, checkpoint[1])
        ):
            raise BridgeJournalError("bridge_journal_head_checkpoint_invalid")
        head = self._head_hmac(sequence, previous_head, row_hmac)
        changed = self._connection.execute(
            """UPDATE bridge_journal_metadata
               SET event_count = ?, head_hmac_sha256 = ?
               WHERE singleton = 1 AND event_count = ? AND head_hmac_sha256 = ?""",
            (sequence, head, sequence - 1, previous_head),
        ).rowcount
        if changed != 1:
            raise BridgeJournalError("bridge_journal_head_update_invalid")
        self._pending_checkpoint = (sequence, head)

    def _authenticated_intent(self, row: sqlite3.Row) -> BridgeIntent:
        intent = _intent_from_row(row)
        sequence = _event_sequence(row)
        expected = self._intent_hmac(intent, sequence)
        if not _safe_hmac_equal(row["row_hmac_sha256"], expected):
            raise BridgeJournalError("bridge_journal_intent_hmac_invalid")
        return intent

    def _authenticated_result(self, row: sqlite3.Row) -> AuthenticatedBridgeResult:
        intent_id = row["intent_id"]
        if not isinstance(intent_id, str):
            raise BridgeJournalError("bridge_journal_result_intent_invalid")
        result = _result_from_row(row)
        sequence = _event_sequence(row)
        expected = self._result_hmac(intent_id, result, sequence)
        if not _safe_hmac_equal(row["row_hmac_sha256"], expected):
            raise BridgeJournalError("bridge_journal_result_hmac_invalid")
        return result

    def _intent_hmac(self, intent: BridgeIntent, sequence: int) -> str:
        payload = {**intent.public_payload(), "event_sequence": sequence}
        return self._integrity.digest(b"bridge-intent-row-v1\0" + canonical_json_bytes(payload))

    def _result_hmac(
        self,
        intent_id: str,
        result: AuthenticatedBridgeResult,
        sequence: int,
    ) -> str:
        payload = {
            **result.public_payload(),
            "event_sequence": sequence,
            "intent_id": intent_id,
        }
        return self._integrity.digest(b"bridge-result-row-v1\0" + canonical_json_bytes(payload))

    def _head_hmac(self, sequence: int, previous_head: str, row_hmac: str) -> str:
        try:
            material = (
                b"bridge-journal-head-v1\0"
                + sequence.to_bytes(8, "big")
                + bytes.fromhex(previous_head)
                + bytes.fromhex(row_hmac)
            )
        except (ValueError, OverflowError) as exc:
            raise BridgeJournalError("bridge_journal_head_material_invalid") from exc
        return self._integrity.digest(material)

    def _assert_open(self) -> None:
        if self._closed:
            raise BridgeJournalError("bridge_journal_closed")


def _intent_values(intent: BridgeIntent, sequence: int, row_hmac: str) -> tuple[object, ...]:
    return (
        intent.binding.intent_id,
        sequence,
        intent.binding.logical_operation,
        intent.binding.logical_call_id,
        intent.pool_id,
        intent.pool_authority_sha256,
        intent.bridge_id,
        intent.bridge_authority_sha256,
        intent.request_body_sha256,
        intent.prompt_input_sha256,
        intent.response_format_type,
        intent.response_format_sha256,
        intent.response_schema_sha256,
        intent.output_token_limit,
        row_hmac,
    )


def _intent_from_row(row: sqlite3.Row) -> BridgeIntent:
    return BridgeIntent(
        binding=BridgeCallBinding(
            intent_id=row["intent_id"],
            logical_operation=row["logical_operation"],
            logical_call_id=row["logical_call_id"],
        ),
        pool_id=row["pool_id"],
        pool_authority_sha256=row["pool_authority_sha256"],
        bridge_id=row["bridge_id"],
        bridge_authority_sha256=row["bridge_authority_sha256"],
        request_body_sha256=row["request_body_sha256"],
        prompt_input_sha256=row["prompt_input_sha256"],
        response_format_type=row["response_format_type"],
        response_format_sha256=row["response_format_sha256"],
        response_schema_sha256=row["response_schema_sha256"],
        output_token_limit=row["output_token_limit"],
    )


def _result_values(
    intent_id: str,
    result: AuthenticatedBridgeResult,
    sequence: int,
    row_hmac: str,
) -> tuple[object, ...]:
    usage = result.usage
    return (
        intent_id,
        sequence,
        result.response_body_sha256,
        result.output_text_sha256,
        result.attestation_sha256,
        result.receipt_hmac_sha256,
        result.thread_id,
        result.turn_id,
        usage.prompt_tokens,
        usage.cached_tokens,
        usage.cache_write_tokens,
        usage.completion_tokens,
        usage.reasoning_tokens,
        usage.total_tokens,
        sqlite3.Binary(result.encrypted_output),
        row_hmac,
    )


def _result_from_row(row: sqlite3.Row) -> AuthenticatedBridgeResult:
    encrypted = row["encrypted_output"]
    if type(encrypted) is not bytes:
        raise BridgeJournalError("bridge_journal_ciphertext_invalid")
    return AuthenticatedBridgeResult(
        response_body_sha256=row["response_body_sha256"],
        output_text_sha256=row["output_text_sha256"],
        attestation_sha256=row["attestation_sha256"],
        receipt_hmac_sha256=row["receipt_hmac_sha256"],
        thread_id=row["thread_id"],
        turn_id=row["turn_id"],
        usage=TokenUsage(
            prompt_tokens=row["prompt_tokens"],
            cached_tokens=row["cached_tokens"],
            cache_write_tokens=row["cache_write_tokens"],
            completion_tokens=row["completion_tokens"],
            reasoning_tokens=row["reasoning_tokens"],
            total_tokens=row["total_tokens"],
        ),
        encrypted_output=encrypted,
    )


def _event_sequence(row: sqlite3.Row) -> int:
    sequence = row["event_sequence"]
    if type(sequence) is not int or sequence < 1:
        raise BridgeJournalError("bridge_journal_event_sequence_invalid")
    return sequence


def _safe_hmac_equal(value: object, expected: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and hmac.compare_digest(value, expected)


__all__ = (
    "BridgeJournal",
    "BridgeJournalStatistics",
    "HmacJournalIntegrity",
    "IntentClaim",
)
