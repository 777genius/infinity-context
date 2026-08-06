"""Authenticated replay for the generic v4 operation journal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import final

from infinity_context_server.resumable_operation_journal.domain import (
    OperationEvent,
    OperationJournalError,
    OperationPhase,
    OperationReceipt,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    RetryDisposition,
    VerifiedOperationReceipt,
    operation_states_commitment,
    sha256_commitment,
    verified_receipts_commitment,
)
from infinity_context_server.resumable_operation_journal.ports import (
    OperationJournalSignerPort,
)


@final
@dataclass(frozen=True, slots=True)
class OperationReplayVerification:
    event_count: int
    head_event_sha256: str | None
    phase: OperationRunPhase
    state_commitment_sha256: str
    receipt_count: int
    receipts_commitment_sha256: str


def replay_operation_events(
    events: object,
    *,
    run: OperationRunState,
    manifest_by_id: dict[str, object],
    signer: OperationJournalSignerPort,
) -> OperationReplayVerification:
    """Authenticate and replay the complete chain into a canonical projection."""

    predecessor: str | None = None
    sequence = 0
    phase = OperationRunPhase.ACTIVE
    initialized = False
    states: dict[str, OperationState] = {}
    last_committed_from_unknown: str | None = None
    for event in events:  # type: ignore[union-attr]
        if not isinstance(event, OperationEvent):
            raise OperationJournalError("operation_journal_replay_event_invalid")
        sequence += 1
        if (
            event.run_id != run.identity.run_id
            or event.sequence != sequence
            or event.predecessor_event_sha256 != predecessor
            or event.signer_key_id != signer.key_id
            or sha256_commitment(event.hash_payload()) != event.event_sha256
            or not signer.verify(event.event_sha256.encode("ascii"), event.signature)
        ):
            raise OperationJournalError("operation_journal_event_chain_invalid")
        payload = json.loads(event.payload_json)
        if not isinstance(payload, dict):
            raise OperationJournalError("operation_journal_replay_payload_invalid")
        logical_id = event.logical_operation_id
        if phase is OperationRunPhase.SEALED:
            raise OperationJournalError("operation_journal_post_seal_event")
        if event.event_type == "run_initialized":
            if (
                sequence != 1
                or initialized
                or logical_id is not None
                or payload != run.identity.commitment_payload()
            ):
                raise OperationJournalError("operation_journal_initialize_replay_invalid")
            initialized = True
        elif event.event_type == "operation_dispatched":
            _require_initialized(initialized)
            identity = manifest_by_id.get(logical_id or "")
            if identity is None:
                raise OperationJournalError("operation_journal_dispatch_replay_invalid")
            request_hash = _string(payload, "request_commitment_sha256")
            expected = {
                "ordinal": identity.ordinal,  # type: ignore[union-attr]
                "request_commitment_sha256": request_hash,
                "retry_disposition": identity.retry_disposition.value,  # type: ignore[union-attr]
            }
            current = states.get(logical_id or "")
            if payload != expected or (
                current is not None
                and (
                    current.phase is not OperationPhase.PENDING
                    or current.request_commitment_sha256 != request_hash
                )
            ):
                raise OperationJournalError("operation_journal_dispatch_replay_invalid")
            states[logical_id or ""] = OperationState(  # type: ignore[arg-type]
                identity=identity,
                phase=OperationPhase.DISPATCHED,
                request_commitment_sha256=request_hash,
            )
        elif event.event_type == "operation_replay_scheduled":
            _require_initialized(initialized)
            current = _require_state(states, logical_id)
            if (
                current.phase is not OperationPhase.DISPATCHED
                or current.identity.retry_disposition is not RetryDisposition.IDEMPOTENT_REPLAY
                or payload
                != {
                    "ordinal": current.identity.ordinal,
                    "reason": "restart_without_verified_receipt",
                }
            ):
                raise OperationJournalError("operation_journal_replay_schedule_invalid")
            states[logical_id or ""] = OperationState(
                identity=current.identity,
                request_commitment_sha256=current.request_commitment_sha256,
            )
        elif event.event_type == "operation_outcome_unknown":
            _require_initialized(initialized)
            current = _require_state(states, logical_id)
            if (
                current.phase is not OperationPhase.DISPATCHED
                or current.identity.retry_disposition is not RetryDisposition.QUARANTINE_UNKNOWN
                or payload
                != {
                    "ordinal": current.identity.ordinal,
                    "reason": "restart_without_verified_receipt",
                }
            ):
                raise OperationJournalError("operation_journal_unknown_replay_invalid")
            states[logical_id or ""] = OperationState(
                identity=current.identity,
                phase=OperationPhase.OUTCOME_UNKNOWN,
                request_commitment_sha256=current.request_commitment_sha256,
            )
        elif event.event_type == "operation_committed":
            _require_initialized(initialized)
            current = _require_state(states, logical_id)
            late_idempotent = (
                current.phase is OperationPhase.PENDING
                and current.identity.retry_disposition is RetryDisposition.IDEMPOTENT_REPLAY
                and current.request_commitment_sha256 is not None
                and phase is OperationRunPhase.ACTIVE
            )
            if (
                current.phase is OperationPhase.OUTCOME_UNKNOWN
                and phase is not OperationRunPhase.RECONCILIATION_REQUIRED
            ):
                raise OperationJournalError("operation_journal_commit_replay_invalid")
            if (
                current.phase
                not in (
                    OperationPhase.DISPATCHED,
                    OperationPhase.OUTCOME_UNKNOWN,
                )
                and not late_idempotent
            ):
                raise OperationJournalError("operation_journal_commit_replay_invalid")
            request_hash = _string(payload, "request_commitment_sha256")
            if request_hash != current.request_commitment_sha256:
                raise OperationJournalError("operation_journal_commit_replay_invalid")
            receipt = OperationReceipt(
                run_id=run.identity.run_id,
                logical_operation_id=logical_id or "",
                request_commitment_sha256=request_hash,
                receipt_id=_string(payload, "receipt_id"),
                result_commitment_sha256=_string(payload, "result_commitment_sha256"),
            )
            expected = {
                "ordinal": current.identity.ordinal,
                "receipt_id": receipt.receipt_id,
                "request_commitment_sha256": request_hash,
                "result_commitment_sha256": receipt.result_commitment_sha256,
                "verification_commitment_sha256": _string(
                    payload, "verification_commitment_sha256"
                ),
                "verifier_key_id": _string(payload, "verifier_key_id"),
            }
            if payload != expected or any(
                state.receipt is not None and state.receipt.receipt_id == receipt.receipt_id
                for state in states.values()
            ):
                raise OperationJournalError("operation_journal_commit_replay_invalid")
            states[logical_id or ""] = OperationState(
                identity=current.identity,
                phase=OperationPhase.COMMITTED,
                request_commitment_sha256=current.request_commitment_sha256,
                receipt=receipt,
                verifier_key_id=_string(payload, "verifier_key_id"),
                verification_commitment_sha256=_string(payload, "verification_commitment_sha256"),
            )
            last_committed_from_unknown = (
                logical_id if current.phase is OperationPhase.OUTCOME_UNKNOWN else None
            )
        elif event.event_type == "reconciliation_required":
            _require_initialized(initialized)
            unknown_count = sum(
                state.phase is OperationPhase.OUTCOME_UNKNOWN for state in states.values()
            )
            if (
                logical_id is not None
                or phase is not OperationRunPhase.ACTIVE
                or unknown_count == 0
                or any(state.phase is OperationPhase.DISPATCHED for state in states.values())
                or payload != {"outcome_unknown_count": unknown_count}
            ):
                raise OperationJournalError("operation_journal_reconciliation_replay_invalid")
            phase = OperationRunPhase.RECONCILIATION_REQUIRED
        elif event.event_type == "reconciliation_cleared":
            _require_initialized(initialized)
            resolved_id = payload.get("resolved_logical_operation_id")
            if (
                logical_id is not None
                or phase is not OperationRunPhase.RECONCILIATION_REQUIRED
                or not isinstance(resolved_id, str)
                or payload != {"resolved_logical_operation_id": resolved_id}
                or resolved_id != last_committed_from_unknown
                or _require_state(states, resolved_id).phase is not OperationPhase.COMMITTED
                or any(state.phase is OperationPhase.OUTCOME_UNKNOWN for state in states.values())
            ):
                raise OperationJournalError("operation_journal_reconciliation_replay_invalid")
            phase = OperationRunPhase.ACTIVE
            last_committed_from_unknown = None
        elif event.event_type == "run_sealed":
            _require_initialized(initialized)
            ordered_for_seal = sorted(states.values(), key=lambda item: item.identity.ordinal)
            state_commitment = operation_states_commitment(iter(ordered_for_seal))
            if (
                logical_id is not None
                or phase is not OperationRunPhase.ACTIVE
                or len(states) != run.identity.expected_operation_count
                or any(state.phase is not OperationPhase.COMMITTED for state in states.values())
                or payload
                != {
                    "committed_count": run.identity.expected_operation_count,
                    "state_commitment_sha256": state_commitment,
                }
            ):
                raise OperationJournalError("operation_journal_seal_replay_invalid")
            phase = OperationRunPhase.SEALED
        else:
            raise OperationJournalError("operation_journal_event_type_unknown")
        predecessor = event.event_sha256
    _require_initialized(initialized)
    ordered_states = sorted(states.values(), key=lambda item: item.identity.ordinal)
    ordered_receipts = tuple(
        VerifiedOperationReceipt(
            receipt=state.receipt,
            verifier_key_id=state.verifier_key_id or "",
            verification_commitment_sha256=state.verification_commitment_sha256 or "",
        )
        for state in ordered_states
        if state.phase is OperationPhase.COMMITTED and state.receipt is not None
    )
    return OperationReplayVerification(
        event_count=sequence,
        head_event_sha256=predecessor,
        phase=phase,
        state_commitment_sha256=operation_states_commitment(iter(ordered_states)),
        receipt_count=len(ordered_receipts),
        receipts_commitment_sha256=verified_receipts_commitment(iter(ordered_receipts)),
    )


def _require_initialized(initialized: bool) -> None:
    if not initialized:
        raise OperationJournalError("operation_journal_initialize_replay_invalid")


def _require_state(
    states: dict[str, OperationState], logical_operation_id: str | None
) -> OperationState:
    state = states.get(logical_operation_id or "")
    if state is None:
        raise OperationJournalError("operation_journal_replay_state_missing")
    return state


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise OperationJournalError("operation_journal_replay_payload_invalid")
    return value


__all__ = ("OperationReplayVerification", "replay_operation_events")
