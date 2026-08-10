"""Durable SQLite scheduler adapter with atomic C1a state transitions.

This adapter remains not paid-go-ready.  The resumable composition injects a
reviewed one-shot boundary and permanently freezes ambiguous durable intents.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from sqlite3 import Connection
from typing import final

from infinity_context_server.publishable_durable_scheduler.contracts import (
    SchedulerCallStage,
    SchedulerContractError,
    SchedulerRunAuthority,
    SchedulerSuiteAuthority,
)
from infinity_context_server.publishable_durable_scheduler.manifest import (
    BuiltSchedulerManifest,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_contracts import (
    SQLITE_SCHEDULER_PAID_GO_READY,
    SchedulerSQLiteAuthenticator,
    SchedulerSQLiteError,
    SchedulerSQLiteEvent,
    ciphertext_material,
    is_sha256,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_repository import (
    SQLiteSchedulerRepository,
)
from infinity_context_server.publishable_durable_scheduler.sqlite_rows import state_sha256
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallState,
    SchedulerRunPhase,
    SchedulerRunState,
)

_Transition = Callable[
    [Connection, SchedulerRunState, SchedulerCallState],
    tuple[SchedulerRunState, SchedulerCallState],
]


@final
class SQLiteDurableSchedulerStore:
    """One exact suite run per private authenticated SQLite database."""

    __slots__ = ("_repository",)

    def __init__(
        self,
        database_path: Path,
        *,
        private_directory: Path,
        authentication_secret: bytes,
        suite: SchedulerSuiteAuthority,
        run: SchedulerRunAuthority,
        manifest: BuiltSchedulerManifest,
    ) -> None:
        self._repository = SQLiteSchedulerRepository(
            database_path,
            private_directory=private_directory,
            authenticator=SchedulerSQLiteAuthenticator(authentication_secret),
            suite=suite,
            run=run,
            manifest=manifest,
        )

    @property
    def paid_go_ready(self) -> bool:
        return SQLITE_SCHEDULER_PAID_GO_READY

    def read_run(self) -> SchedulerRunState:
        with self._repository.immediate() as connection:
            return self._repository.load_run(connection)[0]

    def read_call(self, logical_call_id: str) -> SchedulerCallState:
        with self._repository.immediate() as connection:
            return self._repository.load_call(connection, logical_call_id)[0]

    def read_calls(self, *, after_ordinal: int, limit: int) -> tuple[SchedulerCallState, ...]:
        return self._repository.read_calls(after_ordinal=after_ordinal, limit=limit)

    def read_events(self, *, after_event_id: int, limit: int) -> tuple[SchedulerSQLiteEvent, ...]:
        return self._repository.read_events(after_event_id=after_event_id, limit=limit)

    def read_private_answer_ciphertext(self, logical_call_id: str) -> bytes:
        return self._repository.read_private_answer_ciphertext(logical_call_id)

    def verify(self) -> None:
        self._repository.verify_all()

    def acquire_lease(
        self,
        logical_call_id: str,
        *,
        now_unix_ms: int,
        lease_id: str,
        lease_expires_unix_ms: int,
    ) -> SchedulerCallState:
        def transition(
            connection: Connection,
            run: SchedulerRunState,
            call: SchedulerCallState,
        ) -> tuple[SchedulerRunState, SchedulerCallState]:
            dependency = None
            if call.depends_on_logical_call_id is not None:
                dependency = self._repository.load_call(
                    connection, call.depends_on_logical_call_id
                )[0]
            return self._repository.validator.acquire_lease(
                run,
                call,
                now_unix_ms=now_unix_ms,
                lease_id=lease_id,
                lease_expires_unix_ms=lease_expires_unix_ms,
                dependency=dependency,
            )

        return self._apply(logical_call_id, "lease_acquired", transition)

    def bind_request(
        self,
        logical_call_id: str,
        *,
        lease_id: str,
        request_sha256: str,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "request_bound",
            lambda _connection, run, call: self._repository.validator.bind_request(
                run,
                call,
                lease_id=lease_id,
                request_sha256=request_sha256,
            ),
        )

    def record_dispatch_intent(
        self,
        logical_call_id: str,
        *,
        lease_id: str,
        now_unix_ms: int,
        bridge_boot_authority_sha256: str,
        intent_sha256: str,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "dispatch_intent_recorded",
            lambda _connection, run, call: self._repository.validator.record_dispatch_intent(
                run,
                call,
                lease_id=lease_id,
                now_unix_ms=now_unix_ms,
                bridge_boot_authority_sha256=bridge_boot_authority_sha256,
                intent_sha256=intent_sha256,
            ),
        )

    def commit_outcome(
        self,
        logical_call_id: str,
        *,
        intent_sha256: str,
        receipt_sha256: str,
        completion_tokens: int,
        charged_tokens: int,
        answer_ciphertext: bytes | None,
    ) -> SchedulerCallState:
        call = self.read_call(logical_call_id)
        if call.stage is SchedulerCallStage.ANSWER:
            ciphertext_material(answer_ciphertext)
            if answer_ciphertext is None:
                raise SchedulerSQLiteError("scheduler_sqlite_answer_ciphertext_missing")
        elif answer_ciphertext is not None:
            raise SchedulerSQLiteError("scheduler_sqlite_judge_ciphertext_forbidden")
        return self._apply(
            logical_call_id,
            "outcome_committed",
            lambda _connection, run, current: self._repository.validator.commit_outcome(
                run,
                current,
                intent_sha256=intent_sha256,
                receipt_sha256=receipt_sha256,
                completion_tokens=completion_tokens,
                charged_tokens=charged_tokens,
            ),
            answer_ciphertext=answer_ciphertext,
        )

    def record_known_failure(
        self,
        logical_call_id: str,
        *,
        intent_sha256: str,
        failure_sha256: str,
        charged_tokens: int,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "known_failure_recorded",
            lambda _connection, run, call: self._repository.validator.record_known_failure(
                run,
                call,
                intent_sha256=intent_sha256,
                failure_sha256=failure_sha256,
                charged_tokens=charged_tokens,
            ),
        )

    def record_ambiguous_outcome(
        self,
        logical_call_id: str,
        *,
        intent_sha256: str,
        ambiguity_sha256: str,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "outcome_unknown_recorded",
            lambda _connection, run, call: self._repository.validator.record_ambiguous_outcome(
                run,
                call,
                intent_sha256=intent_sha256,
                ambiguity_sha256=ambiguity_sha256,
            ),
        )

    def reclaim_expired_no_intent_lease(
        self,
        logical_call_id: str,
        *,
        now_unix_ms: int,
        lease_id: str,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "lease_reclaimed",
            lambda _connection, run, call: (
                self._repository.validator.reclaim_expired_no_intent_lease(
                    run,
                    call,
                    now_unix_ms=now_unix_ms,
                    lease_id=lease_id,
                )
            ),
        )

    def reconcile_authenticated_terminal_absence(
        self,
        logical_call_id: str,
        *,
        now_unix_ms: int,
        lease_id: str,
        intent_sha256: str,
        absence_sha256: str,
    ) -> SchedulerCallState:
        return self._apply(
            logical_call_id,
            "authenticated_terminal_absence_reconciled",
            lambda _connection, run, call: (
                self._repository.validator.reconcile_authenticated_terminal_absence(
                    run,
                    call,
                    now_unix_ms=now_unix_ms,
                    lease_id=lease_id,
                    intent_sha256=intent_sha256,
                    absence_sha256=absence_sha256,
                )
            ),
        )

    def seal_run(self, *, suite_seal_sha256: str) -> SchedulerRunState:
        """Durably seal exact committed coverage; repeated reopen sealing is safe."""

        if not is_sha256(suite_seal_sha256):
            raise SchedulerSQLiteError("scheduler_sqlite_suite_seal_invalid")

        with self._repository.immediate() as connection:
            before_run, event_head = self._repository.load_run(connection)
            if before_run.phase is SchedulerRunPhase.SEALED:
                self._verify_sealed_run_binding(
                    connection,
                    run=before_run,
                    event_head=event_head,
                    suite_seal_sha256=suite_seal_sha256,
                )
                return before_run
            try:
                run = self._repository.validator.seal_run(
                    before_run,
                    self._repository.iter_calls_bounded(connection),
                )
            except SchedulerSQLiteError:
                raise
            except SchedulerContractError as error:
                raise SchedulerSQLiteError(error.code) from error
            self._repository.persist_run_transition(
                connection,
                before_run=before_run,
                run=run,
                event_kind="run_sealed",
                transition_evidence_sha256=suite_seal_sha256,
            )
            return run

    def verify_suite_seal_binding(self, *, suite_seal_sha256: str) -> SchedulerRunState:
        """Authenticate a sealed run head against one exact durable suite seal."""

        if not is_sha256(suite_seal_sha256):
            raise SchedulerSQLiteError("scheduler_sqlite_suite_seal_invalid")
        with self._repository.immediate() as connection:
            run, event_head = self._repository.load_run(connection)
            if run.phase is not SchedulerRunPhase.SEALED:
                raise SchedulerSQLiteError("scheduler_sqlite_suite_seal_evidence_invalid")
            self._verify_sealed_run_binding(
                connection,
                run=run,
                event_head=event_head,
                suite_seal_sha256=suite_seal_sha256,
            )
            return run

    def exhaust_deadline(self, *, now_unix_ms: int) -> SchedulerRunState:
        """Durably terminalize an idle active run after its immutable deadline."""

        with self._repository.immediate() as connection:
            before_run, _ = self._repository.load_run(connection)
            if before_run.phase is SchedulerRunPhase.DEADLINE_EXHAUSTED:
                if (
                    before_run.reserved_tokens != 0
                    or before_run.inflight_logical_call_id is not None
                ):
                    raise SchedulerSQLiteError("scheduler_sqlite_deadline_exhaustion_invalid")
                return before_run
            calls = self._repository.load_calls_bounded(connection)
            try:
                run = self._repository.validator.exhaust_deadline(
                    before_run,
                    calls,
                    now_unix_ms=now_unix_ms,
                )
            except SchedulerSQLiteError:
                raise
            except SchedulerContractError as error:
                raise SchedulerSQLiteError(error.code) from error
            self._repository.persist_run_transition(
                connection,
                before_run=before_run,
                run=run,
                event_kind="deadline_exhausted",
            )
            return run

    def _apply(
        self,
        logical_call_id: str,
        event_kind: str,
        transition: _Transition,
        *,
        answer_ciphertext: bytes | None = None,
    ) -> SchedulerCallState:
        with self._repository.immediate() as connection:
            before_run, _ = self._repository.load_run(connection)
            before_call, existing_ciphertext = self._repository.load_call(
                connection, logical_call_id
            )
            if existing_ciphertext is not None:
                raise SchedulerSQLiteError("scheduler_sqlite_terminal_call_immutable")
            try:
                run, call = transition(connection, before_run, before_call)
            except SchedulerSQLiteError:
                raise
            except SchedulerContractError as error:
                raise SchedulerSQLiteError(error.code) from error
            self._repository.persist_transition(
                connection,
                before_run=before_run,
                before_call=before_call,
                run=run,
                call=call,
                event_kind=event_kind,
                answer_ciphertext=answer_ciphertext,
            )
            return call

    def _verify_sealed_run_binding(
        self,
        connection: Connection,
        *,
        run: SchedulerRunState,
        event_head: str,
        suite_seal_sha256: str,
    ) -> None:
        if run.reserved_tokens != 0 or run.inflight_logical_call_id is not None:
            raise SchedulerSQLiteError("scheduler_sqlite_sealed_coverage_invalid")
        try:
            self._repository.validator.seal_run(
                replace(
                    run,
                    phase=SchedulerRunPhase.ACTIVE,
                    version=run.version - 1,
                ),
                self._repository.iter_calls_bounded(connection),
            )
        except SchedulerContractError as error:
            raise SchedulerSQLiteError(error.code) from error
        head = self._repository.load_event_head(connection, event_head)
        if head.event_kind != "run_sealed" or head.state_sha256 != state_sha256(
            run,
            call=None,
            ciphertext_sha256=None,
            ciphertext_bytes=0,
            transition_evidence_sha256=suite_seal_sha256,
        ):
            raise SchedulerSQLiteError("scheduler_sqlite_suite_seal_evidence_invalid")


__all__ = ("SQLiteDurableSchedulerStore",)
