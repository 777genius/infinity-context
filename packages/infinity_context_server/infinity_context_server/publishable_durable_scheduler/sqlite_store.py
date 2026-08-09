"""Durable SQLite scheduler adapter with atomic C1a state transitions.

This adapter is still not paid-run capable: no provider-attempt lookup or
deduplication bridge exists in this standalone slice.
"""

from __future__ import annotations

from collections.abc import Callable
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
)
from infinity_context_server.publishable_durable_scheduler.sqlite_repository import (
    SQLiteSchedulerRepository,
)
from infinity_context_server.publishable_durable_scheduler.state_models import (
    SchedulerCallState,
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


__all__ = ("SQLiteDurableSchedulerStore",)
