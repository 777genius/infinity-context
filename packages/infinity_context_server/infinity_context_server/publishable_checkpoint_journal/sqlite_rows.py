"""Bounded SQLite row mapping and streaming helpers for the evaluation journal."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from infinity_context_server.publishable_checkpoint_journal.domain import (
    BackendTargetAuthority,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    JournalEvent,
    JournalRunState,
    LogicalCallIdentity,
    ManifestCaseAuthority,
    ProviderCallState,
    PublishableRunIdentity,
    RunPhase,
    RuntimeReceipt,
)

MAX_BATCH_SIZE = 1000


def iter_calls(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    phases: tuple[CallPhase, ...] | None,
    batch_size: int,
) -> Iterator[ProviderCallState]:
    validate_batch_size(batch_size)
    where = "WHERE calls.run_id = ?"
    parameters: list[object] = [run_id]
    if phases is not None:
        if (
            not isinstance(phases, tuple)
            or not phases
            or any(not isinstance(phase, CallPhase) for phase in phases)
        ):
            raise CheckpointJournalError("checkpoint_journal_call_phase_filter_invalid")
        placeholders = ", ".join("?" for _ in phases)
        where += f" AND calls.phase IN ({placeholders})"
        parameters.extend(phase.value for phase in phases)
    cursor = connection.execute(
        f"""
        SELECT manifest.*, calls.phase, calls.request_commitment_sha256,
               calls.provider_receipt_id,
               calls.result_commitment_sha256, calls.verifier_key_id,
               calls.verification_commitment_sha256
        FROM provider_calls AS calls
        JOIN evaluation_manifest AS manifest
          ON manifest.run_id = calls.run_id
         AND manifest.logical_call_id = calls.logical_call_id
        {where}
        ORDER BY manifest.ordinal
        """,
        tuple(parameters),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield call_from_row(row)
    finally:
        cursor.close()


def iter_runtime_state_projections(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[dict[str, object]]:
    """Stream provider and private receipt state in the signed replay shape."""

    validate_batch_size(batch_size)
    cursor = connection.execute(
        """
        SELECT manifest.*, calls.phase, calls.request_commitment_sha256,
               calls.provider_receipt_id, calls.result_commitment_sha256,
               calls.verifier_key_id, calls.verification_commitment_sha256,
               private.receipt_identity_json AS private_receipt_identity_json,
               private.request_commitment_sha256
                   AS private_request_commitment_sha256,
               private.receipt_commitment_sha256
                   AS private_receipt_commitment_sha256,
               private.verifier_key_id AS private_verifier_key_id,
               private.verification_commitment_sha256
                   AS private_verification_commitment_sha256
        FROM provider_calls AS calls
        JOIN evaluation_manifest AS manifest
          ON manifest.run_id = calls.run_id
         AND manifest.logical_call_id = calls.logical_call_id
        LEFT JOIN private_provider_results AS private
          ON private.run_id = calls.run_id
         AND private.logical_call_id = calls.logical_call_id
        WHERE calls.run_id = ?
        ORDER BY manifest.ordinal
        """,
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                state = call_from_row(row)
                receipt = state.receipt
                yield {
                    "logical_call_id": state.identity.logical_call_id,
                    "ordinal": state.identity.ordinal,
                    "phase": state.phase.value,
                    "private_receipt_commitment_sha256": optional_string(
                        row["private_receipt_commitment_sha256"]
                    ),
                    "private_receipt_identity_json": optional_string(
                        row["private_receipt_identity_json"]
                    ),
                    "private_request_commitment_sha256": optional_string(
                        row["private_request_commitment_sha256"]
                    ),
                    "private_verification_commitment_sha256": optional_string(
                        row["private_verification_commitment_sha256"]
                    ),
                    "private_verifier_key_id": optional_string(row["private_verifier_key_id"]),
                    "provider_receipt_id": (
                        receipt.provider_receipt_id if receipt is not None else None
                    ),
                    "replay_key": state.identity.replay_key,
                    "request_commitment_sha256": (state.request_commitment_sha256),
                    "result_commitment_sha256": (
                        receipt.result_commitment_sha256 if receipt is not None else None
                    ),
                    "stage": state.identity.stage.value,
                    "verification_commitment_sha256": (state.verification_commitment_sha256),
                    "verifier_key_id": state.verifier_key_id,
                }
    finally:
        cursor.close()


def iter_manifest_identities(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[LogicalCallIdentity]:
    """Yield immutable manifest slots in ordinal order using bounded cursor batches."""

    validate_batch_size(batch_size)
    cursor = connection.execute(
        "SELECT * FROM evaluation_manifest WHERE run_id = ? ORDER BY ordinal",
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield identity_from_manifest_row(row)
    finally:
        cursor.close()


def iter_manifest_cases(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[tuple[int, ManifestCaseAuthority]]:
    validate_batch_size(batch_size)
    cursor = connection.execute(
        "SELECT * FROM manifest_cases WHERE run_id = ? ORDER BY case_ordinal",
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield (
                    int(row["case_ordinal"]),
                    ManifestCaseAuthority(
                        case_id=str(row["case_id"]),
                        case_alias=str(row["case_alias"]),
                    ),
                )
    finally:
        cursor.close()


def iter_manifest_backend_targets(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[tuple[int, BackendTargetAuthority]]:
    validate_batch_size(batch_size)
    cursor = connection.execute(
        """
        SELECT * FROM manifest_backend_targets
        WHERE run_id = ? ORDER BY backend_ordinal
        """,
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield (
                    int(row["backend_ordinal"]),
                    BackendTargetAuthority(
                        backend_role=str(row["backend_role"]),
                        backend_target_id=str(row["backend_target_id"]),
                        backend_target_commitment_sha256=str(
                            row["backend_target_commitment_sha256"]
                        ),
                    ),
                )
    finally:
        cursor.close()


def iter_events(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[JournalEvent]:
    validate_batch_size(batch_size)
    cursor = connection.execute(
        "SELECT * FROM receipt_events WHERE run_id = ? ORDER BY sequence",
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield event_from_row(row)
    finally:
        cursor.close()


def iter_pending_lifecycle_events(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    batch_size: int,
) -> Iterator[JournalEvent]:
    validate_batch_size(batch_size)
    cursor = connection.execute(
        """
        SELECT events.*
        FROM lifecycle_outbox AS outbox
        JOIN receipt_events AS events
          ON events.run_id = outbox.run_id
         AND events.event_sha256 = outbox.event_sha256
        WHERE outbox.run_id = ? AND outbox.delivered = 0
        ORDER BY events.sequence
        """,
        (run_id,),
    )
    try:
        while rows := cursor.fetchmany(batch_size):
            for row in rows:
                yield event_from_row(row)
    finally:
        cursor.close()


def run_from_row(row: sqlite3.Row) -> JournalRunState:
    try:
        return JournalRunState(
            identity=PublishableRunIdentity(
                run_id=str(row["run_id"]),
                profile_id=str(row["profile_id"]),
                profile_commitment_sha256=str(row["profile_commitment_sha256"]),
                dataset_commitment_sha256=str(row["dataset_commitment_sha256"]),
                methodology_commitment_sha256=str(row["methodology_commitment_sha256"]),
                source_commit_sha256=str(row["source_commit_sha256"]),
                runtime_pin_sha256=str(row["runtime_pin_sha256"]),
                case_manifest_sha256=str(row["case_manifest_sha256"]),
                manifest_authority_commitment_sha256=str(
                    row["manifest_authority_commitment_sha256"]
                ),
                evaluation_manifest_commitment_sha256=str(
                    row["evaluation_manifest_commitment_sha256"]
                ),
                signer_key_id=str(row["signer_key_id"]),
                journal_schema_version=str(row["journal_schema_version"]),
                expected_case_count=int(row["expected_case_count"]),
                expected_message_count=int(row["expected_message_count"]),
                expected_extraction_call_count=int(row["expected_extraction_call_count"]),
                expected_answer_judge_call_count=int(row["expected_answer_judge_call_count"]),
            ),
            phase=RunPhase(str(row["phase"])),
            event_count=int(row["event_count"]),
            head_event_sha256=optional_string(row["head_event_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointJournalError("checkpoint_journal_run_row_invalid") from error


def identity_from_manifest_row(row: sqlite3.Row) -> LogicalCallIdentity:
    try:
        identity = LogicalCallIdentity(
            run_id=str(row["run_id"]),
            case_id=str(row["case_id"]),
            case_alias=str(row["case_alias"]),
            backend_role=str(row["backend_role"]),
            backend_target_id=str(row["backend_target_id"]),
            backend_target_commitment_sha256=str(row["backend_target_commitment_sha256"]),
            stage=CallStage(str(row["stage"])),
            ordinal=int(row["ordinal"]),
            depends_on_logical_call_id=optional_string(row["depends_on_logical_call_id"]),
        )
        if identity.logical_call_id != str(row["logical_call_id"]):
            raise CheckpointJournalError("checkpoint_journal_call_row_identity_drift")
        if identity.replay_key != str(row["replay_key"]):
            raise CheckpointJournalError("checkpoint_journal_call_row_replay_drift")
        if identity.case_lane_id != str(row["case_lane_id"]):
            raise CheckpointJournalError("checkpoint_journal_call_row_lane_drift")
        return identity
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointJournalError("checkpoint_journal_call_row_invalid") from error


def call_from_row(row: sqlite3.Row) -> ProviderCallState:
    try:
        identity = identity_from_manifest_row(row)
        phase = CallPhase(str(row["phase"]))
        request_commitment_sha256 = optional_string(row["request_commitment_sha256"])
        receipt = (
            RuntimeReceipt(
                run_id=identity.run_id,
                logical_call_id=identity.logical_call_id,
                request_commitment_sha256=str(request_commitment_sha256),
                provider_receipt_id=str(row["provider_receipt_id"]),
                result_commitment_sha256=str(row["result_commitment_sha256"]),
            )
            if phase is CallPhase.COMMITTED
            else None
        )
        return ProviderCallState(
            identity=identity,
            phase=phase,
            request_commitment_sha256=request_commitment_sha256,
            receipt=receipt,
            verifier_key_id=optional_string(row["verifier_key_id"]),
            verification_commitment_sha256=optional_string(row["verification_commitment_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CheckpointJournalError("checkpoint_journal_call_row_invalid") from error


def event_from_row(row: sqlite3.Row) -> JournalEvent:
    return JournalEvent(
        run_id=str(row["run_id"]),
        sequence=int(row["sequence"]),
        event_type=str(row["event_type"]),
        logical_call_id=optional_string(row["logical_call_id"]),
        payload_json=str(row["payload_json"]),
        predecessor_event_sha256=optional_string(row["predecessor_event_sha256"]),
        event_sha256=str(row["event_sha256"]),
        signer_key_id=str(row["signer_key_id"]),
        signature=str(row["signature"]),
    )


def optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def validate_batch_size(batch_size: int) -> None:
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= MAX_BATCH_SIZE
    ):
        raise CheckpointJournalError("checkpoint_journal_batch_size_invalid")


__all__ = (
    "call_from_row",
    "event_from_row",
    "identity_from_manifest_row",
    "iter_calls",
    "iter_events",
    "iter_manifest_backend_targets",
    "iter_manifest_cases",
    "iter_manifest_identities",
    "iter_pending_lifecycle_events",
    "iter_runtime_state_projections",
    "optional_string",
    "run_from_row",
)
