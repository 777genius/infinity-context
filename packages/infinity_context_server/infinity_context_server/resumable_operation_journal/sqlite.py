"""Strict schema-v4 SQLite adapter for the resumable operation journal."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import final

from infinity_context_server.resumable_operation_journal.commitments import (
    RECEIPT_TREE,
    STATE_TREE,
    CommitmentNode,
    facts_from_roots,
    receipt_leaf,
    state_leaf,
    unsettled_from_state,
)
from infinity_context_server.resumable_operation_journal.domain import (
    OPERATION_JOURNAL_SCHEMA_VERSION,
    LogicalOperationIdentity,
    OperationEvent,
    OperationJournalCheckpoint,
    OperationJournalError,
    OperationJournalFacts,
    OperationManifest,
    OperationPhase,
    OperationReceipt,
    OperationRunIdentity,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    OperationUnsettledState,
    RetryDisposition,
    VerifiedOperationReceipt,
    canonical_json,
    sha256_commitment,
)
from infinity_context_server.resumable_operation_journal.sqlite_accumulator import (
    SQLiteCommitmentTree,
)
from infinity_context_server.resumable_operation_journal.sqlite_schema import (
    JOURNAL_SCHEMA as _SCHEMA,
)
from infinity_context_server.resumable_operation_journal.sqlite_schema import (
    JOURNAL_TABLES as _TABLES,
)
from infinity_context_server.resumable_operation_journal.sqlite_schema import (
    expected_schema_fingerprint as _expected_fingerprint,
)
from infinity_context_server.resumable_operation_journal.sqlite_schema import (
    schema_fingerprint as _schema_fingerprint,
)


def _state_root(facts: OperationJournalFacts) -> CommitmentNode:
    return CommitmentNode(
        commitment_sha256=facts.state_commitment_sha256,
        valid_count=facts.expected_operation_count,
        pending_count=facts.pending_count,
        dispatched_count=facts.dispatched_count,
        committed_count=facts.committed_count,
        outcome_unknown_count=facts.outcome_unknown_count,
    )


def _receipt_root(facts: OperationJournalFacts) -> CommitmentNode:
    return CommitmentNode(
        commitment_sha256=facts.receipts_commitment_sha256,
        valid_count=facts.expected_operation_count,
        receipt_count=facts.receipt_count,
    )


@final
class SQLiteOperationJournalTransaction:
    def __init__(self, connection: sqlite3.Connection, observe: object = None) -> None:
        self._connection = connection
        self._observe_callback = observe

    def _observe(self, name: str, amount: int = 1, *, maximum: bool = False) -> None:
        if callable(self._observe_callback):
            self._observe_callback(name, amount, maximum=maximum)

    def get_run(self, run_id: str) -> OperationRunState | None:
        row = self._connection.execute(
            "SELECT * FROM operation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _run_from_row(row) if row is not None else None

    def put_run(self, state: OperationRunState) -> None:
        identity = state.identity
        self._connection.execute(
            """
            INSERT INTO operation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                phase=excluded.phase,
                event_count=excluded.event_count,
                head_event_sha256=excluded.head_event_sha256
            """,
            (
                identity.run_id,
                identity.operation_namespace,
                identity.manifest_commitment_sha256,
                identity.policy_commitment_sha256,
                identity.signer_key_id,
                identity.expected_operation_count,
                identity.journal_schema_version,
                state.phase.value,
                state.event_count,
                state.head_event_sha256,
            ),
        )

    def put_manifest(self, manifest: OperationManifest) -> None:
        self._connection.executemany(
            """
            INSERT INTO operation_manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    operation.run_id,
                    operation.ordinal,
                    operation.logical_operation_id,
                    operation.replay_key,
                    operation.operation_key,
                    operation.operation_kind,
                    operation.authority_commitment_sha256,
                    operation.retry_disposition.value,
                )
                for operation in manifest.operations
            ),
        )

    def get_manifest_operation(
        self, *, run_id: str, ordinal: int
    ) -> LogicalOperationIdentity | None:
        row = self._connection.execute(
            "SELECT * FROM operation_manifest WHERE run_id = ? AND ordinal = ?",
            (run_id, ordinal),
        ).fetchone()
        return _identity_from_row(row) if row is not None else None

    def iter_manifest(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[LogicalOperationIdentity]:
        _validate_batch_size(batch_size)
        cursor = self._connection.execute(
            "SELECT * FROM operation_manifest WHERE run_id = ? ORDER BY ordinal", (run_id,)
        )
        yield from _batched(
            cursor,
            _identity_from_row,
            batch_size,
            observe=self._observe,
            counter="manifest_rows_scanned",
        )

    def get_operation(self, *, run_id: str, logical_operation_id: str) -> OperationState | None:
        row = self._connection.execute(
            """
            SELECT m.*, s.ordinal AS state_ordinal, s.phase,
                   s.request_commitment_sha256, s.receipt_id,
                   s.result_commitment_sha256, s.verifier_key_id,
                   s.verification_commitment_sha256
            FROM operation_states s
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE s.run_id = ? AND s.logical_operation_id = ?
            """,
            (run_id, logical_operation_id),
        ).fetchone()
        return _state_from_row(row) if row is not None else None

    def get_authenticated_operation(
        self,
        *,
        run_id: str,
        ordinal: int,
        facts: OperationJournalFacts,
    ) -> OperationState | None:
        if facts.expected_operation_count <= ordinal or ordinal < 0:
            raise OperationJournalError("operation_journal_ordinal_invalid")
        identity = self.get_manifest_operation(run_id=run_id, ordinal=ordinal)
        if identity is None:
            raise OperationJournalError("operation_journal_manifest_identity_missing")
        state = self.get_operation(
            run_id=run_id,
            logical_operation_id=identity.logical_operation_id,
        )
        tree = self._tree(run_id=run_id, tree_kind=STATE_TREE, facts=facts)
        tree.authenticate_leaf(
            ordinal=ordinal,
            leaf=state_leaf(state),
            expected_root=_state_root(facts),
        )
        self._observe("authenticated_state_reads")
        return state

    def put_operation(self, state: OperationState) -> None:
        receipt = state.receipt
        self._connection.execute(
            """
            INSERT INTO operation_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, logical_operation_id) DO UPDATE SET
                phase=excluded.phase,
                request_commitment_sha256=excluded.request_commitment_sha256,
                receipt_id=excluded.receipt_id,
                result_commitment_sha256=excluded.result_commitment_sha256,
                verifier_key_id=excluded.verifier_key_id,
                verification_commitment_sha256=excluded.verification_commitment_sha256
            """,
            (
                state.identity.run_id,
                state.identity.logical_operation_id,
                state.identity.ordinal,
                state.phase.value,
                state.request_commitment_sha256,
                receipt.receipt_id if receipt else None,
                receipt.result_commitment_sha256 if receipt else None,
                state.verifier_key_id,
                state.verification_commitment_sha256,
            ),
        )

    def put_receipt(self, *, state: OperationState, verified: VerifiedOperationReceipt) -> None:
        self._connection.execute(
            "INSERT INTO operation_receipts VALUES (?, ?, ?, ?, ?, ?)",
            (
                state.identity.run_id,
                state.identity.logical_operation_id,
                canonical_json(verified.receipt.identity_payload()),
                sha256_commitment(verified.receipt.identity_payload()),
                verified.verifier_key_id,
                verified.verification_commitment_sha256,
            ),
        )

    def apply_operation_transition(
        self,
        *,
        state: OperationState,
        verified: VerifiedOperationReceipt | None,
        expected_facts: OperationJournalFacts,
    ) -> OperationJournalFacts:
        run_id = state.identity.run_id
        ordinal = state.identity.ordinal
        current = self.get_authenticated_operation(
            run_id=run_id,
            ordinal=ordinal,
            facts=expected_facts,
        )
        state_tree = self._tree(
            run_id=run_id,
            tree_kind=STATE_TREE,
            facts=expected_facts,
        )
        next_state_root = state_tree.update_leaf(
            ordinal=ordinal,
            previous_leaf=state_leaf(current),
            next_leaf=state_leaf(state),
            expected_root=_state_root(expected_facts),
        )
        receipt_tree = self._tree(
            run_id=run_id,
            tree_kind=RECEIPT_TREE,
            facts=expected_facts,
        )
        next_receipt_root = _receipt_root(expected_facts)
        if verified is not None:
            if state.phase is not OperationPhase.COMMITTED or verified.receipt != state.receipt:
                raise OperationJournalError("operation_journal_receipt_transition_invalid")
            existing = self._receipt_for_ordinal(run_id=run_id, ordinal=ordinal)
            if existing is not None:
                raise OperationJournalError("operation_journal_receipt_replay_divergent")
            next_receipt_root = receipt_tree.update_leaf(
                ordinal=ordinal,
                previous_leaf=receipt_leaf(ordinal, None),
                next_leaf=receipt_leaf(ordinal, verified),
                expected_root=_receipt_root(expected_facts),
            )
        self.put_operation(state)
        if verified is not None:
            self.put_receipt(state=state, verified=verified)
        committed_prefix = self._committed_prefix(
            state_tree=state_tree,
            root=next_state_root,
        )
        first_unsettled = self._first_unsettled(
            run_id=run_id,
            state_tree=state_tree,
            root=next_state_root,
        )
        self._observe("operation_transitions")
        return facts_from_roots(
            state=next_state_root,
            receipts=next_receipt_root,
            committed_prefix_count=committed_prefix,
            first_unsettled=first_unsettled,
        )

    def get_checkpoint(self, *, run_id: str) -> OperationJournalCheckpoint | None:
        row = self._connection.execute(
            "SELECT * FROM operation_checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        self._observe("checkpoint_reads")
        return _checkpoint_from_row(row) if row is not None else None

    def put_checkpoint(self, checkpoint: OperationJournalCheckpoint) -> None:
        payload_json = canonical_json(checkpoint.commitment_payload())
        self._connection.execute(
            """
            INSERT INTO operation_checkpoints VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                checkpoint_json=excluded.checkpoint_json,
                checkpoint_sha256=excluded.checkpoint_sha256,
                signer_key_id=excluded.signer_key_id,
                signature=excluded.signature
            """,
            (
                checkpoint.run.identity.run_id,
                payload_json,
                checkpoint.checkpoint_sha256,
                checkpoint.signer_key_id,
                checkpoint.signature,
            ),
        )
        self._observe("checkpoint_writes")

    def append_event(self, event: OperationEvent) -> None:
        self._connection.execute(
            "INSERT INTO operation_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.run_id,
                event.sequence,
                event.event_type,
                event.logical_operation_id,
                event.payload_json,
                event.predecessor_event_sha256,
                event.event_sha256,
                event.signer_key_id,
                event.signature,
            ),
        )

    def enqueue_notification(self, event: OperationEvent) -> None:
        self._connection.execute(
            "INSERT INTO notification_outbox(run_id, event_sha256) VALUES (?, ?)",
            (event.run_id, event.event_sha256),
        )

    def mark_notification_delivered(self, *, run_id: str, event_sha256: str) -> None:
        cursor = self._connection.execute(
            """UPDATE notification_outbox SET delivered = 1
               WHERE run_id = ? AND event_sha256 = ?""",
            (run_id, event_sha256),
        )
        if cursor.rowcount != 1:
            raise OperationJournalError("operation_journal_notification_missing")

    def iter_operations(self, *, run_id: str, batch_size: int = 256) -> Iterator[OperationState]:
        _validate_batch_size(batch_size)
        cursor = self._connection.execute(
            """
            SELECT m.*, s.ordinal AS state_ordinal, s.phase,
                   s.request_commitment_sha256, s.receipt_id,
                   s.result_commitment_sha256, s.verifier_key_id,
                   s.verification_commitment_sha256
            FROM operation_states s
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE s.run_id = ? ORDER BY m.ordinal
            """,
            (run_id,),
        )
        yield from _batched(
            cursor,
            _state_from_row,
            batch_size,
            observe=self._observe,
            counter="state_rows_scanned",
        )

    def operation_phase_page(
        self,
        *,
        run_id: str,
        phases: tuple[str, ...],
        after_ordinal: int = -1,
        batch_size: int = 512,
    ) -> tuple[OperationState, ...]:
        _validate_batch_size(batch_size)
        if (
            not phases
            or any(phase not in {item.value for item in OperationPhase} for phase in phases)
            or not isinstance(after_ordinal, int)
            or isinstance(after_ordinal, bool)
            or after_ordinal < -1
        ):
            raise ValueError("operation phase page is invalid")
        placeholders = ",".join("?" for _ in phases)
        cursor = self._connection.execute(
            f"""
            SELECT m.*, s.ordinal AS state_ordinal, s.phase,
                   s.request_commitment_sha256, s.receipt_id,
                   s.result_commitment_sha256, s.verifier_key_id,
                   s.verification_commitment_sha256
            FROM operation_states s
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE s.run_id = ? AND s.phase IN ({placeholders}) AND s.ordinal > ?
            ORDER BY s.ordinal LIMIT ?
            """,
            (run_id, *phases, after_ordinal, batch_size),
        )
        rows = cursor.fetchmany(batch_size)
        cursor.close()
        self._observe("phase_page_queries")
        self._observe("phase_page_rows", len(rows))
        self._observe("max_scan_page_size", len(rows), maximum=True)
        return tuple(_state_from_row(row) for row in rows)

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[OperationEvent]:
        _validate_batch_size(batch_size)
        cursor = self._connection.execute(
            "SELECT * FROM operation_events WHERE run_id = ? ORDER BY sequence", (run_id,)
        )
        yield from _batched(
            cursor,
            _event_from_row,
            batch_size,
            observe=self._observe,
            counter="event_rows_scanned",
        )

    def iter_verified_receipts(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[VerifiedOperationReceipt]:
        _validate_batch_size(batch_size)
        cursor = self._connection.execute(
            """
            SELECT m.*, r.receipt_identity_json, r.receipt_commitment_sha256,
                   r.verifier_key_id, r.verification_commitment_sha256
            FROM operation_receipts r
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE r.run_id = ? ORDER BY m.ordinal
            """,
            (run_id,),
        )
        yield from _batched(
            cursor,
            _verified_receipt_from_row,
            batch_size,
            observe=self._observe,
            counter="receipt_rows_scanned",
        )

    def phase_counts(self, *, run_id: str) -> dict[str, int]:
        facts = self._require_checkpoint_facts(run_id)
        return {
            OperationPhase.PENDING.value: facts.pending_count,
            OperationPhase.DISPATCHED.value: facts.dispatched_count,
            OperationPhase.COMMITTED.value: facts.committed_count,
            OperationPhase.OUTCOME_UNKNOWN.value: facts.outcome_unknown_count,
        }

    def state_commitment(self, *, run_id: str) -> str:
        return self._require_checkpoint_facts(run_id).state_commitment_sha256

    def receipt_count(self, *, run_id: str) -> int:
        return self._require_checkpoint_facts(run_id).receipt_count

    def receipts_commitment(self, *, run_id: str) -> str:
        return self._require_checkpoint_facts(run_id).receipts_commitment_sha256

    def _require_checkpoint_facts(self, run_id: str) -> OperationJournalFacts:
        checkpoint = self.get_checkpoint(run_id=run_id)
        if checkpoint is None:
            raise OperationJournalError("operation_journal_checkpoint_missing")
        return checkpoint.facts

    def _tree(
        self,
        *,
        run_id: str,
        tree_kind: str,
        facts: OperationJournalFacts,
    ) -> SQLiteCommitmentTree:
        return SQLiteCommitmentTree(
            self._connection,
            run_id=run_id,
            tree_kind=tree_kind,
            expected_operation_count=facts.expected_operation_count,
            observe=self._observe,
        )

    def _receipt_for_ordinal(
        self,
        *,
        run_id: str,
        ordinal: int,
    ) -> VerifiedOperationReceipt | None:
        row = self._connection.execute(
            """
            SELECT m.*, r.receipt_identity_json, r.receipt_commitment_sha256,
                   r.verifier_key_id, r.verification_commitment_sha256
            FROM operation_receipts r
            JOIN operation_manifest m USING (run_id, logical_operation_id)
            WHERE r.run_id = ? AND m.ordinal = ?
            """,
            (run_id, ordinal),
        ).fetchone()
        return _verified_receipt_from_row(row) if row is not None else None

    @staticmethod
    def _committed_prefix(
        *,
        state_tree: SQLiteCommitmentTree,
        root: CommitmentNode,
    ) -> int:
        ordinal = state_tree.find_first(
            expected_root=root,
            count=lambda node: (
                node.pending_count + node.dispatched_count + node.outcome_unknown_count
            ),
        )
        return root.valid_count if ordinal is None else ordinal

    def _first_unsettled(
        self,
        *,
        run_id: str,
        state_tree: SQLiteCommitmentTree,
        root: CommitmentNode,
    ) -> OperationUnsettledState | None:
        ordinal = state_tree.find_first(
            expected_root=root,
            count=lambda node: node.dispatched_count + node.outcome_unknown_count,
        )
        if ordinal is None:
            return None
        identity = self.get_manifest_operation(run_id=run_id, ordinal=ordinal)
        if identity is None:
            raise OperationJournalError("operation_journal_manifest_identity_missing")
        state = self.get_operation(
            run_id=run_id,
            logical_operation_id=identity.logical_operation_id,
        )
        if state is None:
            raise OperationJournalError("operation_journal_projection_authentication_invalid")
        state_tree.authenticate_leaf(
            ordinal=ordinal,
            leaf=state_leaf(state),
            expected_root=root,
        )
        return unsettled_from_state(state)


@final
class SQLiteOperationJournal:
    """Local-only adapter which never migrates or accepts a v3 database."""

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if database_path.parent != private_directory:
            raise ValueError("database_path must be directly inside private_directory")
        if not 1 <= busy_timeout_ms <= 120_000 or isinstance(busy_timeout_ms, bool):
            raise ValueError("busy_timeout_ms must be from 1 to 120000")
        self.database_path = database_path
        self.private_directory = private_directory
        self._busy_timeout_ms = busy_timeout_ms
        self._work_counters: dict[str, int] = {}
        self._prepare_directory()
        self._assert_safe_file(database_path)
        self._initialize_schema()

    @property
    def schema_version(self) -> str:
        return OPERATION_JOURNAL_SCHEMA_VERSION

    @property
    def work_counters(self) -> dict[str, int]:
        """Return structural work evidence without exposing the live counter map."""

        return dict(self._work_counters)

    def reset_work_counters(self) -> None:
        self._work_counters.clear()

    def _observe(self, name: str, amount: int = 1, *, maximum: bool = False) -> None:
        if maximum:
            self._work_counters[name] = max(self._work_counters.get(name, 0), amount)
        else:
            self._work_counters[name] = self._work_counters.get(name, 0) + amount

    @contextmanager
    def write_transaction(self) -> Iterator[SQLiteOperationJournalTransaction]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._observe("write_transactions")
            yield SQLiteOperationJournalTransaction(connection, self._observe)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            try:
                connection.close()
            finally:
                self._secure_files()

    def iter_pending_notifications(
        self, *, run_id: str, batch_size: int = 64
    ) -> Iterator[OperationEvent]:
        _validate_batch_size(batch_size)
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                SELECT e.* FROM notification_outbox o
                JOIN operation_events e USING (run_id, event_sha256)
                WHERE o.run_id = ? AND o.delivered = 0 ORDER BY e.sequence
                """,
                (run_id,),
            )
            try:
                events = tuple(_event_from_row(row) for row in cursor.fetchmany(batch_size))
            finally:
                cursor.close()
        finally:
            try:
                connection.close()
            finally:
                self._secure_files()
        return iter(events)

    def _initialize_schema(self) -> None:
        connection = self._open_connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                str(row[0])
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            } - {"sqlite_sequence"}
            if not tables:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_meta VALUES (?, ?)",
                    ("schema_version", OPERATION_JOURNAL_SCHEMA_VERSION),
                )
            else:
                self._validate_schema(connection, tables)
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            try:
                connection.close()
            finally:
                self._secure_files()

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection, tables: set[str]) -> None:
        if tables != _TABLES:
            raise OperationJournalError("operation_journal_schema_layout_invalid")
        rows = tuple(
            tuple(row)
            for row in connection.execute("SELECT key, value FROM schema_meta ORDER BY key")
        )
        if rows != (("schema_version", OPERATION_JOURNAL_SCHEMA_VERSION),):
            raise OperationJournalError("operation_journal_schema_version_mismatch")
        if _schema_fingerprint(connection) != _expected_fingerprint():
            raise OperationJournalError("operation_journal_schema_layout_invalid")

    def _connect(self) -> sqlite3.Connection:
        connection = self._open_connection()
        try:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
            self._secure_files()
        except BaseException:
            connection.close()
            raise
        return connection

    def _open_connection(self) -> sqlite3.Connection:
        self._assert_safe_directory()
        self._assert_safe_file(self.database_path)
        connection = sqlite3.connect(
            self.database_path,
            isolation_level=None,
            check_same_thread=False,
            timeout=self._busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _prepare_directory(self) -> None:
        if not os.path.lexists(self.private_directory):
            self.private_directory.mkdir(mode=0o700)
            os.chmod(self.private_directory, 0o700)
        self._assert_safe_directory()

    def _assert_safe_directory(self) -> None:
        info = os.lstat(self.private_directory)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise OperationJournalError("operation_journal_private_directory_unsafe")

    @staticmethod
    def _assert_safe_file(path: Path) -> None:
        if not os.path.lexists(path):
            return
        info = os.lstat(path)
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise OperationJournalError("operation_journal_private_file_unsafe")

    def _secure_files(self) -> None:
        self._assert_safe_directory()
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if os.path.lexists(path):
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise OperationJournalError("operation_journal_private_file_unsafe")
                if stat.S_IMODE(info.st_mode) != 0o600:
                    os.chmod(path, 0o600)


def _batched(
    cursor: sqlite3.Cursor,
    factory: object,
    batch_size: int,
    *,
    observe: object = None,
    counter: str = "rows_scanned",
) -> Iterator[object]:
    _validate_batch_size(batch_size)
    while rows := cursor.fetchmany(batch_size):
        if callable(observe):
            observe(counter, len(rows))
            observe("scan_pages", 1)
            observe("max_scan_page_size", len(rows), maximum=True)
        for row in rows:
            yield factory(row)  # type: ignore[operator]


def _validate_batch_size(batch_size: int) -> None:
    if not 1 <= batch_size <= 512 or isinstance(batch_size, bool):
        raise ValueError("batch_size must be from 1 to 512")


def _identity_from_row(row: sqlite3.Row) -> LogicalOperationIdentity:
    identity = LogicalOperationIdentity(
        run_id=str(row["run_id"]),
        operation_key=str(row["operation_key"]),
        operation_kind=str(row["operation_kind"]),
        ordinal=int(row["ordinal"]),
        authority_commitment_sha256=str(row["authority_commitment_sha256"]),
        retry_disposition=RetryDisposition(str(row["retry_disposition"])),
    )
    if identity.logical_operation_id != str(
        row["logical_operation_id"]
    ) or identity.replay_key != str(row["replay_key"]):
        raise OperationJournalError("operation_journal_manifest_row_tampered")
    return identity


def _state_from_row(row: sqlite3.Row) -> OperationState:
    identity = _identity_from_row(row)
    state_ordinal = row["state_ordinal"]
    if type(state_ordinal) is not int or state_ordinal != identity.ordinal:
        raise OperationJournalError("operation_journal_state_row_tampered")
    phase = OperationPhase(str(row["phase"]))
    receipt = None
    if phase is OperationPhase.COMMITTED:
        if any(
            row[column] is None
            for column in (
                "request_commitment_sha256",
                "receipt_id",
                "result_commitment_sha256",
                "verifier_key_id",
                "verification_commitment_sha256",
            )
        ):
            raise OperationJournalError("operation_journal_state_row_tampered")
        receipt = OperationReceipt(
            run_id=identity.run_id,
            logical_operation_id=identity.logical_operation_id,
            request_commitment_sha256=str(row["request_commitment_sha256"]),
            receipt_id=str(row["receipt_id"]),
            result_commitment_sha256=str(row["result_commitment_sha256"]),
        )
    return OperationState(
        identity=identity,
        phase=phase,
        request_commitment_sha256=_optional(row["request_commitment_sha256"]),
        receipt=receipt,
        verifier_key_id=_optional(row["verifier_key_id"]),
        verification_commitment_sha256=_optional(row["verification_commitment_sha256"]),
    )


def _run_from_row(row: sqlite3.Row) -> OperationRunState:
    return OperationRunState(
        identity=OperationRunIdentity(
            run_id=str(row["run_id"]),
            operation_namespace=str(row["operation_namespace"]),
            manifest_commitment_sha256=str(row["manifest_commitment_sha256"]),
            policy_commitment_sha256=str(row["policy_commitment_sha256"]),
            signer_key_id=str(row["signer_key_id"]),
            expected_operation_count=int(row["expected_operation_count"]),
            journal_schema_version=str(row["journal_schema_version"]),
        ),
        phase=OperationRunPhase(str(row["phase"])),
        event_count=int(row["event_count"]),
        head_event_sha256=_optional(row["head_event_sha256"]),
    )


def _event_from_row(row: sqlite3.Row) -> OperationEvent:
    return OperationEvent(
        run_id=str(row["run_id"]),
        sequence=int(row["sequence"]),
        event_type=str(row["event_type"]),
        logical_operation_id=_optional(row["logical_operation_id"]),
        payload_json=str(row["payload_json"]),
        predecessor_event_sha256=_optional(row["predecessor_event_sha256"]),
        event_sha256=str(row["event_sha256"]),
        signer_key_id=str(row["signer_key_id"]),
        signature=str(row["signature"]),
    )


def _verified_receipt_from_row(row: sqlite3.Row) -> VerifiedOperationReceipt:
    identity = _identity_from_row(row)
    try:
        payload = json.loads(str(row["receipt_identity_json"]))
    except (TypeError, ValueError) as error:
        raise OperationJournalError("operation_journal_receipt_row_tampered") from error
    if not isinstance(payload, dict) or canonical_json(payload) != str(
        row["receipt_identity_json"]
    ):
        raise OperationJournalError("operation_journal_receipt_row_tampered")
    receipt = OperationReceipt(
        run_id=str(payload.get("run_id", "")),
        logical_operation_id=str(payload.get("logical_operation_id", "")),
        request_commitment_sha256=str(payload.get("request_commitment_sha256", "")),
        receipt_id=str(payload.get("receipt_id", "")),
        result_commitment_sha256=str(payload.get("result_commitment_sha256", "")),
    )
    if (
        receipt.run_id != identity.run_id
        or receipt.logical_operation_id != identity.logical_operation_id
        or receipt.identity_payload() != payload
        or sha256_commitment(payload) != str(row["receipt_commitment_sha256"])
    ):
        raise OperationJournalError("operation_journal_receipt_row_tampered")
    return VerifiedOperationReceipt(
        receipt=receipt,
        verifier_key_id=str(row["verifier_key_id"]),
        verification_commitment_sha256=str(row["verification_commitment_sha256"]),
    )


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


def _checkpoint_from_row(row: sqlite3.Row) -> OperationJournalCheckpoint:
    source = str(row["checkpoint_json"])
    try:
        payload = json.loads(source)
        if not isinstance(payload, dict) or canonical_json(payload) != source:
            raise ValueError("checkpoint payload is not canonical")
        if payload.get("schema_version") != "operation-journal-checkpoint.v1":
            raise ValueError("checkpoint schema is invalid")
        run_payload = payload["run"]
        facts_payload = payload["facts"]
        if not isinstance(run_payload, dict) or not isinstance(facts_payload, dict):
            raise ValueError("checkpoint payload is invalid")
        identity_payload = run_payload["identity"]
        if not isinstance(identity_payload, dict):
            raise ValueError("checkpoint identity is invalid")
        identity = OperationRunIdentity(**identity_payload)
        run = OperationRunState(
            identity=identity,
            phase=OperationRunPhase(str(run_payload["phase"])),
            event_count=int(run_payload["event_count"]),
            head_event_sha256=_optional(run_payload["head_event_sha256"]),
        )
        unsettled_payload = facts_payload.get("first_unsettled")
        unsettled = None
        if unsettled_payload is not None:
            if not isinstance(unsettled_payload, dict):
                raise ValueError("checkpoint unsettled state is invalid")
            unsettled = OperationUnsettledState(
                ordinal=int(unsettled_payload["ordinal"]),
                logical_operation_id=str(unsettled_payload["logical_operation_id"]),
                phase=OperationPhase(str(unsettled_payload["phase"])),
                request_commitment_sha256=str(unsettled_payload["request_commitment_sha256"]),
            )
        facts = OperationJournalFacts(
            expected_operation_count=int(facts_payload["expected_operation_count"]),
            pending_count=int(facts_payload["pending_count"]),
            dispatched_count=int(facts_payload["dispatched_count"]),
            committed_count=int(facts_payload["committed_count"]),
            outcome_unknown_count=int(facts_payload["outcome_unknown_count"]),
            receipt_count=int(facts_payload["receipt_count"]),
            committed_prefix_count=int(facts_payload["committed_prefix_count"]),
            state_commitment_sha256=str(facts_payload["state_commitment_sha256"]),
            receipts_commitment_sha256=str(facts_payload["receipts_commitment_sha256"]),
            first_unsettled=unsettled,
        )
        checkpoint = OperationJournalCheckpoint(
            run=run,
            facts=facts,
            signer_key_id=str(row["signer_key_id"]),
            checkpoint_sha256=str(row["checkpoint_sha256"]),
            signature=str(row["signature"]),
        )
    except (KeyError, TypeError, ValueError, OperationJournalError) as error:
        raise OperationJournalError("operation_journal_checkpoint_row_tampered") from error
    if (
        payload != checkpoint.commitment_payload()
        or str(payload.get("signer_key_id")) != checkpoint.signer_key_id
    ):
        raise OperationJournalError("operation_journal_checkpoint_row_tampered")
    return checkpoint


__all__ = ("SQLiteOperationJournal",)
