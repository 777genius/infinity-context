"""Low-level authenticated repository for the scheduler SQLite adapter."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
    SchedulerLogicalCall,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SQLITE_SCHEDULER_SCHEMA_VERSION,
    SchedulerSQLiteAuthenticator,
    SchedulerSQLiteError,
    SchedulerSQLiteEvent,
    ciphertext_material,
    genesis_event_sha256,
    require_query,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_replay import (
    verify_calls,
    verify_events,
    verify_headers,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_rows import (
    call_from_row,
    call_values,
    event,
    event_from_row,
    run_from_row,
    run_values,
    shard_values,
    signed_material,
    state_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_schema import (
    open_scheduler_connection,
    schema_fingerprint_sha256,
)
from infinity_context_server.publishable_durable_scheduler.state import (
    SchedulerStateTransitionValidator,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallState,
    SchedulerRunState,
)


@final
class SQLiteSchedulerRepository:
    __slots__ = (
        "_auth",
        "_calls",
        "_database_path",
        "_manifest",
        "_private_directory",
        "_run",
        "_suite",
        "validator",
    )

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        authenticator: SchedulerSQLiteAuthenticator,
        suite: SchedulerSuiteAuthority,
        run: SchedulerRunAuthority,
        manifest: BuiltSchedulerManifest,
    ) -> None:
        if (
            type(authenticator) is not SchedulerSQLiteAuthenticator
            or type(suite) is not SchedulerSuiteAuthority
            or type(run) is not SchedulerRunAuthority
            or type(manifest) is not BuiltSchedulerManifest
        ):
            raise SchedulerSQLiteError("scheduler_sqlite_composition_invalid")
        self.validator = SchedulerStateTransitionValidator(suite, run, manifest.authority)
        self._database_path = database_path
        self._private_directory = private_directory
        self._auth = authenticator
        self._suite = suite
        self._run = run
        self._manifest = manifest
        self._calls = {
            call.logical_call_id: call for shard in manifest.shards for call in shard.calls
        }
        with self.immediate() as connection:
            self._initialize_or_verify(connection)
        self.verify_all()

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        connection = open_scheduler_connection(
            self._database_path, private_directory=self._private_directory
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load_run(self, connection: sqlite3.Connection) -> tuple[SchedulerRunState, str]:
        row = connection.execute(
            "SELECT * FROM scheduler_runs WHERE run_id = ?", (self._run.binding.run_id,)
        ).fetchone()
        if row is None:
            raise SchedulerSQLiteError("scheduler_sqlite_run_missing")
        state, head = run_from_row(row, self._auth)
        expected = self.validator.initial_run()
        if (
            state.run_id != expected.run_id
            or state.run_authority_sha256 != expected.run_authority_sha256
            or state.bridge_boot_authority_sha256 != expected.bridge_boot_authority_sha256
            or state.dispatch_not_before_unix_ms != expected.dispatch_not_before_unix_ms
            or state.dispatch_deadline_unix_ms != expected.dispatch_deadline_unix_ms
            or state.token_ceiling != expected.token_ceiling
            or state.expected_call_count != expected.expected_call_count
        ):
            raise SchedulerSQLiteError("scheduler_sqlite_run_authority_drift")
        return state, head

    def load_call(
        self, connection: sqlite3.Connection, logical_call_id: str
    ) -> tuple[SchedulerCallState, bytes | None]:
        expected = self._calls.get(logical_call_id)
        if expected is None:
            raise SchedulerSQLiteError("scheduler_sqlite_call_unknown")
        row = connection.execute(
            "SELECT * FROM scheduler_calls WHERE logical_call_id = ?",
            (logical_call_id,),
        ).fetchone()
        if row is None:
            raise SchedulerSQLiteError("scheduler_sqlite_call_missing")
        return call_from_row(row, self._auth, expected=expected)

    def persist_transition(
        self,
        connection: sqlite3.Connection,
        *,
        before_run: SchedulerRunState,
        before_call: SchedulerCallState,
        run: SchedulerRunState,
        call: SchedulerCallState,
        event_kind: str,
        answer_ciphertext: bytes | None,
    ) -> SchedulerSQLiteEvent:
        current_run, previous_head = self.load_run(connection)
        current_call, _ = self.load_call(connection, call.logical_call_id)
        if current_run != before_run or current_call != before_call:
            raise SchedulerSQLiteError("scheduler_sqlite_concurrent_transition")
        expected_call = self._calls[call.logical_call_id]
        call_material = call_values(
            call,
            shard_index=expected_call.shard_index,
            answer_ciphertext=answer_ciphertext,
        )
        ciphertext_sha256, ciphertext_bytes = ciphertext_material(answer_ciphertext)
        event_id = self._next_event_id(connection)
        observed = event(
            self._auth,
            event_id=event_id,
            run_id=run.run_id,
            logical_call_id=call.logical_call_id,
            event_kind=event_kind,
            run_version=run.version,
            call_version=call.version,
            state_sha256=state_sha256(
                run,
                call=call,
                ciphertext_sha256=ciphertext_sha256,
                ciphertext_bytes=ciphertext_bytes,
            ),
            previous_event_sha256=previous_head,
        )
        run_material = run_values(run, event_head_sha256=observed.event_sha256)
        self._update_call(
            connection,
            call_material,
            answer_ciphertext=answer_ciphertext,
            before_version=before_call.version,
        )
        self._update_run(connection, run_material, before_version=before_run.version)
        connection.execute(
            """INSERT INTO scheduler_events
               (event_id, run_id, logical_call_id, event_kind, run_version,
                call_version, state_sha256, previous_event_sha256, event_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _event_parameters(observed),
        )
        return observed

    def persist_run_transition(
        self,
        connection: sqlite3.Connection,
        *,
        before_run: SchedulerRunState,
        run: SchedulerRunState,
        event_kind: str,
        transition_evidence_sha256: str | None = None,
    ) -> SchedulerSQLiteEvent:
        """Persist one run-only terminal transition and its authenticated event."""

        current_run, previous_head = self.load_run(connection)
        if current_run != before_run:
            raise SchedulerSQLiteError("scheduler_sqlite_concurrent_transition")
        event_id = self._next_event_id(connection)
        observed = event(
            self._auth,
            event_id=event_id,
            run_id=run.run_id,
            logical_call_id=None,
            event_kind=event_kind,
            run_version=run.version,
            call_version=None,
            state_sha256=state_sha256(
                run,
                call=None,
                ciphertext_sha256=None,
                ciphertext_bytes=0,
                transition_evidence_sha256=transition_evidence_sha256,
            ),
            previous_event_sha256=previous_head,
        )
        self._update_run(
            connection,
            run_values(run, event_head_sha256=observed.event_sha256),
            before_version=before_run.version,
        )
        connection.execute(
            """INSERT INTO scheduler_events
               (event_id, run_id, logical_call_id, event_kind, run_version,
                call_version, state_sha256, previous_event_sha256, event_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _event_parameters(observed),
        )
        return observed

    def load_calls_bounded(
        self,
        connection: sqlite3.Connection,
    ) -> tuple[SchedulerCallState, ...]:
        """Authenticate every exact call while fetching in bounded batches."""

        calls = list(self.iter_calls_bounded(connection))
        if len(calls) != self._manifest.authority.call_count:
            raise SchedulerSQLiteError("scheduler_sqlite_call_count_invalid")
        return tuple(calls)

    def iter_calls_bounded(
        self,
        connection: sqlite3.Connection,
    ) -> Iterator[SchedulerCallState]:
        """Yield authenticated calls from bounded SQLite fetches without accumulation."""

        cursor = connection.execute(
            """SELECT * FROM scheduler_calls
               WHERE run_id = ? ORDER BY ordinal""",
            (self._run.binding.run_id,),
        )
        while rows := cursor.fetchmany(257):
            for row in rows:
                yield call_from_row(
                    row,
                    self._auth,
                    expected=self._expected_by_ordinal(row["ordinal"]),
                )[0]

    def load_event_head(
        self,
        connection: sqlite3.Connection,
        event_head_sha256: str,
    ) -> SchedulerSQLiteEvent:
        row = connection.execute(
            "SELECT * FROM scheduler_events WHERE event_sha256 = ?",
            (event_head_sha256,),
        ).fetchone()
        if row is None:
            raise SchedulerSQLiteError("scheduler_sqlite_event_head_missing")
        return event_from_row(row, self._auth)

    def read_calls(self, *, after_ordinal: int, limit: int) -> tuple[SchedulerCallState, ...]:
        after, cap = require_query(limit, after=after_ordinal)
        connection = self._connection()
        try:
            rows = connection.execute(
                """SELECT * FROM scheduler_calls
                   WHERE run_id = ? AND ordinal > ? ORDER BY ordinal LIMIT ?""",
                (self._run.binding.run_id, after, cap),
            ).fetchall()
            return tuple(
                call_from_row(
                    row,
                    self._auth,
                    expected=self._expected_by_ordinal(row["ordinal"]),
                )[0]
                for row in rows
            )
        finally:
            connection.close()

    def read_events(self, *, after_event_id: int, limit: int) -> tuple[SchedulerSQLiteEvent, ...]:
        after, cap = require_query(limit, after=after_event_id)
        connection = self._connection()
        try:
            rows = connection.execute(
                """SELECT * FROM scheduler_events
                   WHERE run_id = ? AND event_id > ? ORDER BY event_id LIMIT ?""",
                (self._run.binding.run_id, after, cap),
            ).fetchall()
            return tuple(event_from_row(row, self._auth) for row in rows)
        finally:
            connection.close()

    def read_private_answer_ciphertext(self, logical_call_id: str) -> bytes:
        connection = self._connection()
        try:
            state, ciphertext = self.load_call(connection, logical_call_id)
            if state.phase.value != "committed" or state.stage.value != "answer":
                raise SchedulerSQLiteError("scheduler_sqlite_ciphertext_unavailable")
            if ciphertext is None:
                raise SchedulerSQLiteError("scheduler_sqlite_ciphertext_unavailable")
            return ciphertext
        finally:
            connection.close()

    def verify_all(self) -> None:
        connection = self._connection()
        try:
            verify_headers(connection, self._auth, self._manifest)
            run, event_head = self.load_run(connection)
            verify_calls(
                connection,
                self._auth,
                self._manifest,
                self._expected_by_ordinal,
            )
            verify_events(connection, self._auth, event_head=event_head, run=run)
        finally:
            connection.close()

    def _initialize_or_verify(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT COUNT(*) FROM scheduler_manifests").fetchone()
        if row is None:
            raise SchedulerSQLiteError("scheduler_sqlite_manifest_count_invalid")
        if row[0] == 0:
            self._initialize(connection)
        elif row[0] == 1:
            verify_headers(connection, self._auth, self._manifest)
        else:
            raise SchedulerSQLiteError("scheduler_sqlite_manifest_count_invalid")

    def _initialize(self, connection: sqlite3.Connection) -> None:
        fingerprint = schema_fingerprint_sha256()
        meta = {
            "singleton": 1,
            "schema_version": SQLITE_SCHEDULER_SCHEMA_VERSION,
            "schema_fingerprint_sha256": fingerprint,
        }
        connection.execute(
            "INSERT INTO scheduler_meta VALUES (?, ?, ?, ?)",
            signed_material(self._auth, "meta-row", meta),
        )
        authority = self._manifest.authority
        manifest = {
            "run_id": authority.run_id,
            "suite_authority_sha256": authority.suite_authority_sha256,
            "run_authority_sha256": authority.run_authority_sha256,
            "manifest_authority_sha256": authority.commitment_sha256,
            "case_manifest_sha256": authority.case_manifest_sha256,
            "call_count": authority.call_count,
            "shard_count": len(authority.ordered_shard_commitments),
        }
        connection.execute(
            "INSERT INTO scheduler_manifests VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            signed_material(self._auth, "manifest-row", manifest),
        )
        for shard in self._manifest.shards:
            values = shard_values(authority.run_id, shard)
            connection.execute(
                "INSERT INTO scheduler_shards VALUES (?, ?, ?, ?, ?, ?)",
                signed_material(self._auth, "shard-row", values),
            )
            for call in shard.calls:
                state = self.validator.initial_call(call, shard=shard)
                self._insert_call(connection, state, call.shard_index)
        run = self.validator.initial_run()
        initial = event(
            self._auth,
            event_id=1,
            run_id=run.run_id,
            logical_call_id=None,
            event_kind="manifest_initialized",
            run_version=run.version,
            call_version=None,
            state_sha256=state_sha256(run, call=None, ciphertext_sha256=None, ciphertext_bytes=0),
            previous_event_sha256=genesis_event_sha256(),
        )
        self._insert_run(connection, run, event_head_sha256=initial.event_sha256)
        connection.execute(
            "INSERT INTO scheduler_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _event_parameters(initial),
        )

    def _insert_call(
        self, connection: sqlite3.Connection, state: SchedulerCallState, shard_index: int
    ) -> None:
        values = call_values(state, shard_index=shard_index, answer_ciphertext=None)
        connection.execute(
            """INSERT INTO scheduler_calls
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                values["run_id"],
                values["ordinal"],
                values["shard_index"],
                values["logical_call_id"],
                values["stage"],
                values["token_ceiling"],
                values["depends_on_logical_call_id"],
                values["phase"],
                values["attempt_count"],
                values["lease_id"],
                values["lease_expires_unix_ms"],
                values["request_sha256"],
                values["intent_sha256"],
                values["terminal_evidence_sha256"],
                values["charged_tokens"],
                None,
                values["answer_ciphertext_sha256"],
                values["answer_ciphertext_bytes"],
                values["version"],
                self._auth.sign("call-row", values),
            ),
        )

    def _insert_run(
        self,
        connection: sqlite3.Connection,
        state: SchedulerRunState,
        *,
        event_head_sha256: str,
    ) -> None:
        values = run_values(state, event_head_sha256=event_head_sha256)
        connection.execute(
            "INSERT INTO scheduler_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            signed_material(self._auth, "run-row", values),
        )

    def _update_call(
        self,
        connection: sqlite3.Connection,
        values: dict[str, object],
        *,
        answer_ciphertext: bytes | None,
        before_version: int,
    ) -> None:
        assignments = ", ".join(f"{name} = ?" for name in values if name != "run_id")
        parameters = [values[name] for name in values if name != "run_id"]
        parameters.extend(
            (
                answer_ciphertext,
                self._auth.sign("call-row", values),
                values["run_id"],
                values["ordinal"],
                before_version,
            )
        )
        cursor = connection.execute(
            f"""UPDATE scheduler_calls SET {assignments}, answer_ciphertext = ?, row_mac = ?
                WHERE run_id = ? AND ordinal = ? AND version = ?""",  # noqa: S608
            parameters,
        )
        if cursor.rowcount != 1:
            raise SchedulerSQLiteError("scheduler_sqlite_concurrent_transition")

    def _update_run(
        self,
        connection: sqlite3.Connection,
        values: dict[str, object],
        *,
        before_version: int,
    ) -> None:
        assignments = ", ".join(f"{name} = ?" for name in values if name != "run_id")
        parameters = [values[name] for name in values if name != "run_id"]
        parameters.extend(
            (
                self._auth.sign("run-row", values),
                values["run_id"],
                before_version,
            )
        )
        cursor = connection.execute(
            f"""UPDATE scheduler_runs SET {assignments}, row_mac = ?
                WHERE run_id = ? AND version = ?""",  # noqa: S608
            parameters,
        )
        if cursor.rowcount != 1:
            raise SchedulerSQLiteError("scheduler_sqlite_concurrent_transition")

    def _next_event_id(self, connection: sqlite3.Connection) -> int:
        row = connection.execute("SELECT MAX(event_id) FROM scheduler_events").fetchone()
        return 1 if row is None or row[0] is None else row[0] + 1

    def _expected_by_ordinal(self, ordinal: object) -> SchedulerLogicalCall:
        if type(ordinal) is not int or not 0 <= ordinal < self._manifest.authority.call_count:
            raise SchedulerSQLiteError("scheduler_sqlite_call_ordinal_invalid")
        shard = self._manifest.shards[ordinal // 256]
        return shard.calls[ordinal - shard.start_ordinal]

    def _connection(self) -> sqlite3.Connection:
        return open_scheduler_connection(
            self._database_path, private_directory=self._private_directory
        )


__all__ = ("SQLiteSchedulerRepository",)


def _event_parameters(value: SchedulerSQLiteEvent) -> tuple[object, ...]:
    return (
        value.event_id,
        value.run_id,
        value.logical_call_id,
        value.event_kind,
        value.run_version,
        value.call_version,
        value.state_sha256,
        value.previous_event_sha256,
        value.event_sha256,
    )
