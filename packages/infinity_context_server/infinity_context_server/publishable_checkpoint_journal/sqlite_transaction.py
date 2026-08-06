"""Transaction-scoped SQLite persistence for the evaluation journal."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import final

from infinity_context_server.publishable_checkpoint_journal.domain import (
    PUBLISHABLE_ANSWER_CALL_COUNT,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    EvaluationCoverage,
    JournalEvent,
    JournalRunState,
    LogicalCallIdentity,
    ProviderCallState,
    PublishableEvaluationManifest,
    VerifiedRuntimeReceipt,
    canonical_json,
    verify_evaluation_manifest_stream,
)
from infinity_context_server.publishable_checkpoint_journal.manifest_persistence import (
    verify_manifest_authority_stream,
)
from infinity_context_server.publishable_checkpoint_journal.replay import (
    compute_call_state_commitment,
)
from infinity_context_server.publishable_checkpoint_journal.sqlite_rows import (
    call_from_row,
    identity_from_manifest_row,
    iter_calls,
    iter_events,
    iter_manifest_backend_targets,
    iter_manifest_cases,
    iter_manifest_identities,
    iter_runtime_state_projections,
)


@final
class SQLiteCheckpointJournalTransaction:
    """Transaction-scoped implementation of the application persistence port."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_run(self, run_id: str) -> JournalRunState | None:
        from infinity_context_server.publishable_checkpoint_journal.sqlite_rows import (
            run_from_row,
        )

        row = self._connection.execute(
            "SELECT * FROM run_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return run_from_row(row) if row is not None else None

    def put_run(self, state: JournalRunState) -> None:
        if type(state) is not JournalRunState:
            raise CheckpointJournalError("checkpoint_journal_run_state_invalid")
        identity = state.identity
        self._connection.execute(
            """
            INSERT INTO run_state(
                run_id, profile_id, profile_commitment_sha256, dataset_commitment_sha256,
                methodology_commitment_sha256, source_commit_sha256, runtime_pin_sha256,
                case_manifest_sha256, manifest_authority_commitment_sha256,
                evaluation_manifest_commitment_sha256,
                signer_key_id, journal_schema_version, expected_case_count,
                expected_message_count, expected_extraction_call_count,
                expected_answer_judge_call_count, phase, event_count, head_event_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                phase = excluded.phase,
                event_count = excluded.event_count,
                head_event_sha256 = excluded.head_event_sha256
            """,
            (
                identity.run_id,
                identity.profile_id,
                identity.profile_commitment_sha256,
                identity.dataset_commitment_sha256,
                identity.methodology_commitment_sha256,
                identity.source_commit_sha256,
                identity.runtime_pin_sha256,
                identity.case_manifest_sha256,
                identity.manifest_authority_commitment_sha256,
                identity.evaluation_manifest_commitment_sha256,
                identity.signer_key_id,
                identity.journal_schema_version,
                identity.expected_case_count,
                identity.expected_message_count,
                identity.expected_extraction_call_count,
                identity.expected_answer_judge_call_count,
                state.phase.value,
                state.event_count,
                state.head_event_sha256,
            ),
        )

    def put_evaluation_manifest(self, manifest: PublishableEvaluationManifest) -> None:
        if type(manifest) is not PublishableEvaluationManifest:
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_invalid")
        existing = self._connection.execute(
            "SELECT COUNT(*) FROM evaluation_manifest WHERE run_id = ?",
            (manifest.run_id,),
        ).fetchone()
        if existing is not None and int(existing[0]) != 0:
            raise CheckpointJournalError("checkpoint_journal_evaluation_manifest_exists")
        for ordinal, case in enumerate(manifest.authority.ordered_cases):
            self._connection.execute(
                """
                INSERT INTO manifest_cases(
                    run_id, case_ordinal, case_id, case_alias
                ) VALUES (?, ?, ?, ?)
                """,
                (manifest.run_id, ordinal, case.case_id, case.case_alias),
            )
        for ordinal, target in enumerate(manifest.authority.backend_targets):
            self._connection.execute(
                """
                INSERT INTO manifest_backend_targets(
                    run_id, backend_ordinal, backend_role, backend_target_id,
                    backend_target_commitment_sha256
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    ordinal,
                    target.backend_role,
                    target.backend_target_id,
                    target.backend_target_commitment_sha256,
                ),
            )
        for identity in manifest.calls:
            self._connection.execute(
                """
                INSERT INTO evaluation_manifest(
                    run_id, ordinal, logical_call_id, replay_key, case_lane_id,
                    case_id, case_alias, backend_role, backend_target_id,
                    backend_target_commitment_sha256, stage,
                    depends_on_logical_call_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.run_id,
                    identity.ordinal,
                    identity.logical_call_id,
                    identity.replay_key,
                    identity.case_lane_id,
                    identity.case_id,
                    identity.case_alias,
                    identity.backend_role,
                    identity.backend_target_id,
                    identity.backend_target_commitment_sha256,
                    identity.stage.value,
                    identity.depends_on_logical_call_id,
                ),
            )
            self._put_case_lane(identity)

    def get_evaluation_manifest_call(
        self,
        *,
        run_id: str,
        ordinal: int,
    ) -> LogicalCallIdentity | None:
        row = self._connection.execute(
            """
            SELECT * FROM evaluation_manifest
            WHERE run_id = ? AND ordinal = ?
            """,
            (run_id, ordinal),
        ).fetchone()
        return identity_from_manifest_row(row) if row is not None else None

    def get_call(self, *, run_id: str, logical_call_id: str) -> ProviderCallState | None:
        row = self._connection.execute(
            """
            SELECT manifest.*, calls.phase, calls.request_commitment_sha256,
                   calls.provider_receipt_id,
                   calls.result_commitment_sha256, calls.verifier_key_id,
                   calls.verification_commitment_sha256
            FROM provider_calls AS calls
            JOIN evaluation_manifest AS manifest
              ON manifest.run_id = calls.run_id
             AND manifest.logical_call_id = calls.logical_call_id
            WHERE calls.run_id = ? AND calls.logical_call_id = ?
            """,
            (run_id, logical_call_id),
        ).fetchone()
        return call_from_row(row) if row is not None else None

    def get_call_by_replay_key(
        self,
        *,
        run_id: str,
        replay_key: str,
    ) -> ProviderCallState | None:
        row = self._connection.execute(
            """
            SELECT manifest.*, calls.phase, calls.request_commitment_sha256,
                   calls.provider_receipt_id,
                   calls.result_commitment_sha256, calls.verifier_key_id,
                   calls.verification_commitment_sha256
            FROM provider_calls AS calls
            JOIN evaluation_manifest AS manifest
              ON manifest.run_id = calls.run_id
             AND manifest.logical_call_id = calls.logical_call_id
            WHERE calls.run_id = ? AND manifest.replay_key = ?
            """,
            (run_id, replay_key),
        ).fetchone()
        return call_from_row(row) if row is not None else None

    def put_call(self, state: ProviderCallState) -> None:
        if type(state) is not ProviderCallState:
            raise CheckpointJournalError("checkpoint_journal_call_state_invalid")
        expected = self.get_evaluation_manifest_call(
            run_id=state.identity.run_id,
            ordinal=state.identity.ordinal,
        )
        if expected is None:
            raise CheckpointJournalError("checkpoint_journal_call_outside_manifest")
        if expected != state.identity:
            raise CheckpointJournalError("checkpoint_journal_manifest_identity_divergent")
        receipt = state.receipt
        if receipt is not None:
            reused = self._connection.execute(
                """
                SELECT logical_call_id FROM provider_calls
                WHERE run_id = ? AND provider_receipt_id = ?
                """,
                (state.identity.run_id, receipt.provider_receipt_id),
            ).fetchone()
            if (
                reused is not None
                and str(reused["logical_call_id"]) != state.identity.logical_call_id
            ):
                raise CheckpointJournalError("checkpoint_journal_provider_receipt_reused")
        self._connection.execute(
            """
            INSERT INTO provider_calls(
                run_id, logical_call_id, phase, request_commitment_sha256,
                provider_receipt_id,
                result_commitment_sha256, verifier_key_id,
                verification_commitment_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, logical_call_id) DO UPDATE SET
                phase = excluded.phase,
                request_commitment_sha256 = excluded.request_commitment_sha256,
                provider_receipt_id = excluded.provider_receipt_id,
                result_commitment_sha256 = excluded.result_commitment_sha256,
                verifier_key_id = excluded.verifier_key_id,
                verification_commitment_sha256 = excluded.verification_commitment_sha256
            """,
            (
                state.identity.run_id,
                state.identity.logical_call_id,
                state.phase.value,
                state.request_commitment_sha256,
                receipt.provider_receipt_id if receipt is not None else None,
                receipt.result_commitment_sha256 if receipt is not None else None,
                state.verifier_key_id,
                state.verification_commitment_sha256,
            ),
        )

    def put_private_provider_result(
        self,
        *,
        state: ProviderCallState,
        verified_receipt: VerifiedRuntimeReceipt,
    ) -> None:
        if (
            type(state) is not ProviderCallState
            or type(verified_receipt) is not VerifiedRuntimeReceipt
            or state.phase is not CallPhase.COMMITTED
            or state.receipt != verified_receipt.receipt
        ):
            raise CheckpointJournalError("checkpoint_journal_private_result_invalid")
        receipt = verified_receipt.receipt
        payload = canonical_json(receipt.identity_payload())
        existing = self._connection.execute(
            """
            SELECT receipt_identity_json, request_commitment_sha256,
                   receipt_commitment_sha256, verifier_key_id,
                   verification_commitment_sha256
            FROM private_provider_results
            WHERE run_id = ? AND logical_call_id = ?
            """,
            (receipt.run_id, receipt.logical_call_id),
        ).fetchone()
        expected = (
            payload,
            receipt.request_commitment_sha256,
            receipt.result_commitment_sha256,
            verified_receipt.verifier_key_id,
            verified_receipt.verification_commitment_sha256,
        )
        if existing is not None:
            actual = (
                str(existing["receipt_identity_json"]),
                str(existing["request_commitment_sha256"]),
                str(existing["receipt_commitment_sha256"]),
                str(existing["verifier_key_id"]),
                str(existing["verification_commitment_sha256"]),
            )
            if actual != expected:
                raise CheckpointJournalError("checkpoint_journal_private_result_divergent")
            return
        self._connection.execute(
            """
            INSERT INTO private_provider_results(
                run_id, logical_call_id, receipt_identity_json,
                request_commitment_sha256, receipt_commitment_sha256,
                verifier_key_id, verification_commitment_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt.run_id,
                receipt.logical_call_id,
                payload,
                receipt.request_commitment_sha256,
                receipt.result_commitment_sha256,
                verified_receipt.verifier_key_id,
                verified_receipt.verification_commitment_sha256,
            ),
        )

    def append_event(self, event: JournalEvent) -> None:
        if type(event) is not JournalEvent:
            raise CheckpointJournalError("checkpoint_journal_event_type_invalid")
        self._connection.execute(
            """
            INSERT INTO receipt_events(
                run_id, sequence, event_type, logical_call_id, payload_json,
                predecessor_event_sha256, event_sha256, signer_key_id, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.sequence,
                event.event_type,
                event.logical_call_id,
                event.payload_json,
                event.predecessor_event_sha256,
                event.event_sha256,
                event.signer_key_id,
                event.signature,
            ),
        )

    def enqueue_lifecycle_event(self, event: JournalEvent) -> None:
        if type(event) is not JournalEvent:
            raise CheckpointJournalError("checkpoint_journal_event_type_invalid")
        self._connection.execute(
            """
            INSERT OR IGNORE INTO lifecycle_outbox(run_id, event_sha256, delivered)
            VALUES (?, ?, 0)
            """,
            (event.run_id, event.event_sha256),
        )

    def has_calls_in_phase(self, *, run_id: str, phase: CallPhase) -> bool:
        return self.count_calls_in_phase(run_id=run_id, phase=phase) != 0

    def count_calls_in_phase(self, *, run_id: str, phase: CallPhase) -> int:
        if type(phase) is not CallPhase:
            raise CheckpointJournalError("checkpoint_journal_call_phase_filter_invalid")
        row = self._connection.execute(
            """
            SELECT COUNT(*) FROM provider_calls
            WHERE run_id = ? AND phase = ?
            """,
            (run_id, phase.value),
        ).fetchone()
        return int(row[0])

    def evaluation_coverage(self, *, run_id: str) -> EvaluationCoverage:
        run_row = self._connection.execute(
            "SELECT run_id FROM run_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            return EvaluationCoverage(
                case_manifest_sha256=None,
                manifest_authority_commitment_sha256=None,
                evaluation_manifest_commitment_sha256=None,
                authority_case_count=0,
                authority_backend_target_count=0,
                authority_mismatch_count=0,
                manifest_total=0,
                manifest_answer_count=0,
                manifest_judge_count=0,
                committed_total=0,
                committed_answer_count=0,
                committed_judge_count=0,
                unresolved_count=0,
                private_result_count=0,
                signed_commit_event_count=0,
                signed_commit_binding_count=0,
            )
        authority = verify_manifest_authority_stream(
            iter_manifest_cases(
                self._connection,
                run_id=run_id,
                batch_size=256,
            ),
            iter_manifest_backend_targets(
                self._connection,
                run_id=run_id,
                batch_size=16,
            ),
        )
        manifest = verify_evaluation_manifest_stream(
            iter_manifest_identities(
                self._connection,
                run_id=run_id,
                batch_size=256,
            ),
            case_manifest_sha256=authority.case_manifest_sha256,
            manifest_authority_commitment_sha256=(authority.manifest_authority_commitment_sha256),
        )
        if manifest.run_id != run_id:
            raise CheckpointJournalError(
                "checkpoint_journal_evaluation_manifest_run_binding_invalid"
            )
        authority_binding = self._connection.execute(
            """
            WITH slots AS (
                SELECT manifest.*,
                       CASE
                           WHEN manifest.ordinal >= :answer_call_count
                           THEN manifest.ordinal - :answer_call_count
                           ELSE manifest.ordinal
                       END AS base_ordinal
                FROM evaluation_manifest AS manifest
                WHERE manifest.run_id = :run_id
            )
            SELECT COALESCE(SUM(
                cases.case_id IS NULL
                OR targets.backend_target_id IS NULL
                OR slots.case_id != cases.case_id
                OR slots.case_alias != cases.case_alias
                OR slots.backend_role != targets.backend_role
                OR slots.backend_target_id != targets.backend_target_id
                OR slots.backend_target_commitment_sha256
                   != targets.backend_target_commitment_sha256
            ), 0) AS mismatch_count
            FROM slots
            LEFT JOIN manifest_cases AS cases
              ON cases.run_id = slots.run_id
             AND cases.case_ordinal = CAST(slots.base_ordinal / 2 AS INTEGER)
            LEFT JOIN manifest_backend_targets AS targets
              ON targets.run_id = slots.run_id
             AND targets.backend_ordinal = slots.base_ordinal % 2
            """,
            {
                "answer_call_count": PUBLISHABLE_ANSWER_CALL_COUNT,
                "run_id": run_id,
            },
        ).fetchone()
        calls = self._connection.execute(
            """
            SELECT
                COALESCE(SUM(calls.phase = 'committed'), 0) AS committed_total,
                COALESCE(SUM(
                    calls.phase = 'committed' AND manifest.stage = 'answer'
                ), 0) AS committed_answers,
                COALESCE(SUM(
                    calls.phase = 'committed' AND manifest.stage = 'judge'
                ), 0) AS committed_judges,
                COALESCE(SUM(
                    calls.phase IS NULL OR calls.phase != 'committed'
                ), 0) AS unresolved
            FROM evaluation_manifest AS manifest
            LEFT JOIN provider_calls AS calls
              ON calls.run_id = manifest.run_id
             AND calls.logical_call_id = manifest.logical_call_id
            WHERE manifest.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        private_results = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM private_provider_results
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        signed_events = self._connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM receipt_events
            WHERE run_id = ? AND event_type = 'call_committed'
            """,
            (run_id,),
        ).fetchone()
        signed_binding = self._connection.execute(
            """
            SELECT COUNT(*) AS matching_count
            FROM receipt_events AS events
            JOIN evaluation_manifest AS manifest
              ON manifest.run_id = events.run_id
             AND manifest.logical_call_id = events.logical_call_id
            JOIN provider_calls AS calls
              ON calls.run_id = manifest.run_id
             AND calls.logical_call_id = manifest.logical_call_id
            JOIN private_provider_results AS private
              ON private.run_id = calls.run_id
             AND private.logical_call_id = calls.logical_call_id
            WHERE events.run_id = ?
              AND events.event_type = 'call_committed'
              AND calls.phase = 'committed'
              AND json_extract(events.payload_json, '$.ordinal') = manifest.ordinal
              AND json_extract(
                    events.payload_json, '$.request_commitment_sha256'
                  ) = calls.request_commitment_sha256
              AND json_extract(
                    events.payload_json, '$.provider_receipt_id'
                  ) = calls.provider_receipt_id
              AND json_extract(
                    events.payload_json, '$.result_commitment_sha256'
                  ) = calls.result_commitment_sha256
              AND json_extract(
                    events.payload_json, '$.verifier_key_id'
                  ) = calls.verifier_key_id
              AND json_extract(
                    events.payload_json, '$.verification_commitment_sha256'
                  ) = calls.verification_commitment_sha256
              AND private.request_commitment_sha256
                  = calls.request_commitment_sha256
              AND private.receipt_commitment_sha256
                  = calls.result_commitment_sha256
              AND private.verifier_key_id = calls.verifier_key_id
              AND private.verification_commitment_sha256
                  = calls.verification_commitment_sha256
              AND json_extract(
                    private.receipt_identity_json, '$.run_id'
                  ) = calls.run_id
              AND json_extract(
                    private.receipt_identity_json, '$.logical_call_id'
                  ) = calls.logical_call_id
              AND json_extract(
                    private.receipt_identity_json, '$.request_commitment_sha256'
                  ) = calls.request_commitment_sha256
              AND json_extract(
                    private.receipt_identity_json, '$.provider_receipt_id'
                  ) = calls.provider_receipt_id
              AND json_extract(
                    private.receipt_identity_json, '$.result_commitment_sha256'
                  ) = calls.result_commitment_sha256
            """,
            (run_id,),
        ).fetchone()
        return EvaluationCoverage(
            case_manifest_sha256=manifest.case_manifest_sha256,
            manifest_authority_commitment_sha256=(manifest.manifest_authority_commitment_sha256),
            evaluation_manifest_commitment_sha256=manifest.commitment_sha256,
            authority_case_count=authority.case_count,
            authority_backend_target_count=authority.backend_target_count,
            authority_mismatch_count=int(authority_binding["mismatch_count"]),
            manifest_total=manifest.total_count,
            manifest_answer_count=manifest.answer_count,
            manifest_judge_count=manifest.judge_count,
            committed_total=int(calls["committed_total"]),
            committed_answer_count=int(calls["committed_answers"]),
            committed_judge_count=int(calls["committed_judges"]),
            unresolved_count=int(calls["unresolved"]),
            private_result_count=int(private_results["total"]),
            signed_commit_event_count=int(signed_events["total"]),
            signed_commit_binding_count=int(signed_binding["matching_count"]),
        )

    def runtime_state_commitment(self, *, run_id: str) -> str:
        return compute_call_state_commitment(
            iter_runtime_state_projections(
                self._connection,
                run_id=run_id,
                batch_size=256,
            )
        )

    def iter_calls(
        self,
        *,
        run_id: str,
        phases: tuple[CallPhase, ...] | None = None,
        batch_size: int = 256,
    ) -> Iterator[ProviderCallState]:
        return iter_calls(
            self._connection,
            run_id=run_id,
            phases=phases,
            batch_size=batch_size,
        )

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[JournalEvent]:
        return iter_events(self._connection, run_id=run_id, batch_size=batch_size)

    def mark_lifecycle_event_delivered(self, *, run_id: str, event_sha256: str) -> None:
        cursor = self._connection.execute(
            """
            UPDATE lifecycle_outbox
            SET delivered = 1
            WHERE run_id = ? AND event_sha256 = ?
            """,
            (run_id, event_sha256),
        )
        if cursor.rowcount != 1:
            raise CheckpointJournalError("checkpoint_journal_lifecycle_outbox_missing")

    def _put_case_lane(self, identity: LogicalCallIdentity) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO case_lanes(
                run_id, case_lane_id, case_id, case_alias, backend_role,
                backend_target_id, backend_target_commitment_sha256,
                answer_logical_call_id, judge_logical_call_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '')
            """,
            (
                identity.run_id,
                identity.case_lane_id,
                identity.case_id,
                identity.case_alias,
                identity.backend_role,
                identity.backend_target_id,
                identity.backend_target_commitment_sha256,
            ),
        )
        column = (
            "answer_logical_call_id"
            if identity.stage is CallStage.ANSWER
            else "judge_logical_call_id"
        )
        row = self._connection.execute(
            f"SELECT {column} FROM case_lanes WHERE run_id = ? AND case_lane_id = ?",
            (identity.run_id, identity.case_lane_id),
        ).fetchone()
        if row is None:
            raise CheckpointJournalError("checkpoint_journal_case_lane_missing")
        existing = str(row[column])
        if existing and existing != identity.logical_call_id:
            raise CheckpointJournalError("checkpoint_journal_case_lane_slot_divergent")
        self._connection.execute(
            f"UPDATE case_lanes SET {column} = ? WHERE run_id = ? AND case_lane_id = ?",
            (identity.logical_call_id, identity.run_id, identity.case_lane_id),
        )

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("SQLiteCheckpointJournalTransaction is final")


__all__ = ("SQLiteCheckpointJournalTransaction",)
