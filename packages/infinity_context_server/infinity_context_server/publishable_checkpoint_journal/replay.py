"""Semantic replay of the authenticated journal event chain."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import final

from infinity_context_server.publishable_checkpoint_journal.domain import (
    CHECKPOINT_JOURNAL_SCHEMA_VERSION,
    PUBLISHABLE_ANSWER_CALL_COUNT,
    PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT,
    PUBLISHABLE_JUDGE_CALL_COUNT,
    CallPhase,
    CallStage,
    CheckpointJournalError,
    JournalEvent,
    PublishableRunIdentity,
    RunPhase,
    canonical_json,
    sha256_commitment,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@final
@dataclass(frozen=True, slots=True)
class EventChainVerification:
    event_count: int
    head_event_sha256: str | None

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("EventChainVerification is final")


@dataclass(slots=True)
class _ReplayedCall:
    ordinal: int
    stage: CallStage
    replay_key: str
    phase: CallPhase
    request_commitment_sha256: str | None = None
    provider_receipt_id: str | None = None
    result_commitment_sha256: str | None = None
    verifier_key_id: str | None = None
    verification_commitment_sha256: str | None = None


@final
@dataclass(frozen=True, slots=True)
class JournalReplayVerification:
    event_count: int
    head_event_sha256: str
    phase: RunPhase
    call_state_commitment_sha256: str
    call_count: int
    committed_call_count: int
    outcome_unknown_count: int

    def __init_subclass__(cls, **kwargs: object) -> None:
        del cls, kwargs
        raise TypeError("JournalReplayVerification is final")


def verify_journal_event_chain(
    events: Iterable[JournalEvent],
    *,
    run_id: str,
    signer_key_id: str,
    verify: Callable[[bytes, str], bool],
) -> EventChainVerification:
    """Stream-verify an event envelope chain without semantic run context."""

    predecessor: str | None = None
    expected_sequence = 1
    for event in events:
        if not isinstance(event, JournalEvent):
            raise CheckpointJournalError("checkpoint_journal_chain_event_type_invalid")
        if event.run_id != run_id:
            raise CheckpointJournalError("checkpoint_journal_chain_cross_run")
        if event.sequence != expected_sequence:
            raise CheckpointJournalError("checkpoint_journal_chain_sequence_gap")
        if event.predecessor_event_sha256 != predecessor:
            raise CheckpointJournalError("checkpoint_journal_chain_predecessor_mismatch")
        if event.event_sha256 != sha256_commitment(event.hash_payload()):
            raise CheckpointJournalError("checkpoint_journal_chain_hash_mismatch")
        if event.signer_key_id != signer_key_id:
            raise CheckpointJournalError("checkpoint_journal_chain_signer_key_mismatch")
        if not verify(event.event_sha256.encode("ascii"), event.signature):
            raise CheckpointJournalError("checkpoint_journal_chain_signature_invalid")
        predecessor = event.event_sha256
        expected_sequence += 1
    return EventChainVerification(
        event_count=expected_sequence - 1,
        head_event_sha256=predecessor,
    )


def replay_journal_events(
    events: Iterable[JournalEvent],
    *,
    identity: PublishableRunIdentity,
    signer_key_id: str,
    verify: Callable[[bytes, str], bool],
) -> JournalReplayVerification:
    """Authenticate and semantically reduce every event in one streaming pass."""

    predecessor: str | None = None
    expected_sequence = 1
    phase = RunPhase.ACTIVE
    calls: dict[str, _ReplayedCall] = {}
    ordinals: set[int] = set()
    last_resolved_logical_call_id: str | None = None
    for event in events:
        _verify_envelope(
            event,
            identity=identity,
            signer_key_id=signer_key_id,
            expected_sequence=expected_sequence,
            predecessor=predecessor,
            verify=verify,
        )
        payload = _payload(event)
        if expected_sequence == 1:
            if (
                event.event_type != "run_initialized"
                or event.logical_call_id is not None
                or payload != identity.commitment_payload()
            ):
                raise CheckpointJournalError("checkpoint_journal_chain_run_identity_mismatch")
        else:
            if phase is RunPhase.EVALUATION_SEALED:
                raise CheckpointJournalError("checkpoint_journal_chain_event_after_evaluation_seal")
            last_resolved_logical_call_id = _apply_event(
                event,
                payload=payload,
                calls=calls,
                ordinals=ordinals,
                phase=phase,
                identity=identity,
                last_resolved_logical_call_id=last_resolved_logical_call_id,
            )
            if event.event_type == "reconciliation_required":
                phase = RunPhase.RECONCILIATION_REQUIRED
            elif event.event_type == "reconciliation_cleared":
                phase = RunPhase.ACTIVE
            elif event.event_type == "evaluation_sealed":
                phase = RunPhase.EVALUATION_SEALED
        predecessor = event.event_sha256
        expected_sequence += 1
    if expected_sequence == 1 or predecessor is None:
        raise CheckpointJournalError("checkpoint_journal_chain_initialize_missing")
    unknown_count = sum(call.phase is CallPhase.OUTCOME_UNKNOWN for call in calls.values())
    if (phase is RunPhase.RECONCILIATION_REQUIRED) != (unknown_count > 0):
        raise CheckpointJournalError("checkpoint_journal_chain_reconciliation_state_mismatch")
    return JournalReplayVerification(
        event_count=expected_sequence - 1,
        head_event_sha256=predecessor,
        phase=phase,
        call_state_commitment_sha256=compute_call_state_commitment(
            _call_projection(
                logical_call_id,
                call,
                run_id=identity.run_id,
            )
            for logical_call_id, call in sorted(
                calls.items(),
                key=lambda item: item[1].ordinal,
            )
        ),
        call_count=len(calls),
        committed_call_count=sum(call.phase is CallPhase.COMMITTED for call in calls.values()),
        outcome_unknown_count=unknown_count,
    )


def compute_call_state_commitment(
    calls: Iterable[Mapping[str, object]],
) -> str:
    """Hash ordered runtime call projections in one pass."""

    digest = hashlib.sha256()
    digest.update(b'{"calls":[')
    for index, call in enumerate(calls):
        if index:
            digest.update(b",")
        digest.update(
            json.dumps(
                call,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
    digest.update(b'],"schema_version":')
    digest.update(json.dumps(CHECKPOINT_JOURNAL_SCHEMA_VERSION).encode("utf-8"))
    digest.update(b"}")
    return digest.hexdigest()


def _call_projection(
    logical_call_id: str,
    call: _ReplayedCall,
    *,
    run_id: str,
) -> dict[str, object]:
    private_receipt_identity_json = None
    if call.phase is CallPhase.COMMITTED:
        private_receipt_identity_json = canonical_json(
            {
                "logical_call_id": logical_call_id,
                "provider_receipt_id": call.provider_receipt_id,
                "request_commitment_sha256": call.request_commitment_sha256,
                "result_commitment_sha256": call.result_commitment_sha256,
                "run_id": run_id,
            }
        )
    return {
        "logical_call_id": logical_call_id,
        "ordinal": call.ordinal,
        "phase": call.phase.value,
        "private_receipt_commitment_sha256": call.result_commitment_sha256,
        "private_receipt_identity_json": private_receipt_identity_json,
        "private_request_commitment_sha256": call.request_commitment_sha256
        if call.phase is CallPhase.COMMITTED
        else None,
        "private_verification_commitment_sha256": (call.verification_commitment_sha256),
        "private_verifier_key_id": call.verifier_key_id,
        "provider_receipt_id": call.provider_receipt_id,
        "replay_key": call.replay_key,
        "request_commitment_sha256": call.request_commitment_sha256,
        "result_commitment_sha256": call.result_commitment_sha256,
        "stage": call.stage.value,
        "verification_commitment_sha256": call.verification_commitment_sha256,
        "verifier_key_id": call.verifier_key_id,
    }


def _apply_event(
    event: JournalEvent,
    *,
    payload: dict[str, object],
    calls: dict[str, _ReplayedCall],
    ordinals: set[int],
    phase: RunPhase,
    identity: PublishableRunIdentity,
    last_resolved_logical_call_id: str | None,
) -> str | None:
    event_type = event.event_type
    logical_call_id = event.logical_call_id
    if event_type == "call_reserved":
        if phase is not RunPhase.ACTIVE or logical_call_id is None:
            raise CheckpointJournalError("checkpoint_journal_chain_reserve_invalid")
        _exact_keys(payload, {"ordinal", "replay_key", "stage"})
        ordinal = _ordinal(payload)
        stage = _stage(payload)
        replay_key = _digest(payload.get("replay_key"), "replay_key")
        if logical_call_id in calls or ordinal in ordinals:
            raise CheckpointJournalError("checkpoint_journal_chain_reserve_duplicate")
        calls[logical_call_id] = _ReplayedCall(
            ordinal=ordinal,
            stage=stage,
            replay_key=replay_key,
            phase=CallPhase.RESERVED,
        )
        ordinals.add(ordinal)
        return last_resolved_logical_call_id
    if event_type == "request_bound":
        call = _require_call(calls, logical_call_id, CallPhase.RESERVED)
        _exact_keys(payload, {"ordinal", "request_commitment_sha256"})
        _same_ordinal(payload, call)
        if call.request_commitment_sha256 is not None:
            raise CheckpointJournalError("checkpoint_journal_chain_request_binding_duplicate")
        call.request_commitment_sha256 = _digest(
            payload.get("request_commitment_sha256"),
            "request_commitment_sha256",
        )
        return last_resolved_logical_call_id
    if event_type == "call_dispatched":
        call = _require_call(calls, logical_call_id, CallPhase.RESERVED)
        _exact_keys(
            payload,
            {"ordinal", "request_commitment_sha256", "stage"},
        )
        _same_ordinal(payload, call)
        if _stage(payload) is not call.stage:
            raise CheckpointJournalError("checkpoint_journal_chain_call_stage_mismatch")
        request_sha256 = _digest(
            payload.get("request_commitment_sha256"),
            "request_commitment_sha256",
        )
        if call.request_commitment_sha256 != request_sha256:
            raise CheckpointJournalError("checkpoint_journal_chain_request_binding_mismatch")
        call.phase = CallPhase.DISPATCHED
        return last_resolved_logical_call_id
    if event_type == "call_outcome_unknown":
        call = _require_call(calls, logical_call_id, CallPhase.DISPATCHED)
        _exact_keys(payload, {"ordinal", "reason"})
        _same_ordinal(payload, call)
        if payload["reason"] != "restart_without_verified_receipt":
            raise CheckpointJournalError("checkpoint_journal_chain_unknown_reason_invalid")
        call.phase = CallPhase.OUTCOME_UNKNOWN
        return last_resolved_logical_call_id
    if event_type == "call_committed":
        call = _require_call(
            calls,
            logical_call_id,
            (CallPhase.DISPATCHED, CallPhase.OUTCOME_UNKNOWN),
        )
        _exact_keys(
            payload,
            {
                "ordinal",
                "provider_receipt_id",
                "request_commitment_sha256",
                "result_commitment_sha256",
                "verifier_key_id",
                "verification_commitment_sha256",
            },
        )
        _same_ordinal(payload, call)
        request_sha256 = _digest(
            payload.get("request_commitment_sha256"),
            "request_commitment_sha256",
        )
        if call.request_commitment_sha256 != request_sha256:
            raise CheckpointJournalError("checkpoint_journal_chain_request_binding_mismatch")
        provider_receipt_id = _identifier(
            payload.get("provider_receipt_id"),
            "provider_receipt_id",
        )
        result_commitment_sha256 = _digest(
            payload.get("result_commitment_sha256"),
            "result_commitment_sha256",
        )
        verifier_key_id = _identifier(
            payload.get("verifier_key_id"),
            "verifier_key_id",
        )
        verification_commitment_sha256 = _digest(
            payload.get("verification_commitment_sha256"),
            "verification_commitment_sha256",
        )
        call.provider_receipt_id = provider_receipt_id
        call.result_commitment_sha256 = result_commitment_sha256
        call.verifier_key_id = verifier_key_id
        call.verification_commitment_sha256 = verification_commitment_sha256
        call.phase = CallPhase.COMMITTED
        return logical_call_id
    if event_type == "reconciliation_required":
        if phase is not RunPhase.ACTIVE or logical_call_id is not None:
            raise CheckpointJournalError(
                "checkpoint_journal_chain_reconciliation_transition_invalid"
            )
        _exact_keys(payload, {"outcome_unknown_count"})
        unknown_count = sum(call.phase is CallPhase.OUTCOME_UNKNOWN for call in calls.values())
        if payload["outcome_unknown_count"] != unknown_count or unknown_count == 0:
            raise CheckpointJournalError("checkpoint_journal_chain_reconciliation_count_mismatch")
        return last_resolved_logical_call_id
    if event_type == "reconciliation_cleared":
        if phase is not RunPhase.RECONCILIATION_REQUIRED or logical_call_id is not None:
            raise CheckpointJournalError(
                "checkpoint_journal_chain_reconciliation_transition_invalid"
            )
        _exact_keys(payload, {"resolved_logical_call_id"})
        if payload["resolved_logical_call_id"] != last_resolved_logical_call_id or any(
            call.phase is CallPhase.OUTCOME_UNKNOWN for call in calls.values()
        ):
            raise CheckpointJournalError("checkpoint_journal_chain_reconciliation_clear_invalid")
        return last_resolved_logical_call_id
    if event_type == "evaluation_sealed":
        if phase is not RunPhase.ACTIVE or logical_call_id is not None:
            raise CheckpointJournalError("checkpoint_journal_chain_evaluation_seal_invalid")
        _exact_keys(
            payload,
            {
                "committed_answer_count",
                "committed_judge_count",
                "evaluation_manifest_commitment_sha256",
            },
        )
        answer_count = sum(
            call.phase is CallPhase.COMMITTED and call.stage is CallStage.ANSWER
            for call in calls.values()
        )
        judge_count = sum(
            call.phase is CallPhase.COMMITTED and call.stage is CallStage.JUDGE
            for call in calls.values()
        )
        if (
            len(calls) != PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
            or answer_count != PUBLISHABLE_ANSWER_CALL_COUNT
            or judge_count != PUBLISHABLE_JUDGE_CALL_COUNT
            or payload["committed_answer_count"] != answer_count
            or payload["committed_judge_count"] != judge_count
            or payload["evaluation_manifest_commitment_sha256"]
            != identity.evaluation_manifest_commitment_sha256
        ):
            raise CheckpointJournalError("checkpoint_journal_chain_evaluation_seal_invalid")
        return last_resolved_logical_call_id
    raise CheckpointJournalError("checkpoint_journal_chain_event_type_unknown")


def _verify_envelope(
    event: JournalEvent,
    *,
    identity: PublishableRunIdentity,
    signer_key_id: str,
    expected_sequence: int,
    predecessor: str | None,
    verify: Callable[[bytes, str], bool],
) -> None:
    if not isinstance(event, JournalEvent):
        raise CheckpointJournalError("checkpoint_journal_chain_event_type_invalid")
    if event.run_id != identity.run_id:
        raise CheckpointJournalError("checkpoint_journal_chain_cross_run")
    if event.sequence != expected_sequence:
        raise CheckpointJournalError("checkpoint_journal_chain_sequence_gap")
    if event.predecessor_event_sha256 != predecessor:
        raise CheckpointJournalError("checkpoint_journal_chain_predecessor_mismatch")
    if event.event_sha256 != sha256_commitment(event.hash_payload()):
        raise CheckpointJournalError("checkpoint_journal_chain_hash_mismatch")
    if event.signer_key_id != signer_key_id:
        raise CheckpointJournalError("checkpoint_journal_chain_signer_key_mismatch")
    if not verify(event.event_sha256.encode("ascii"), event.signature):
        raise CheckpointJournalError("checkpoint_journal_chain_signature_invalid")


def _payload(event: JournalEvent) -> dict[str, object]:
    value = json.loads(event.payload_json)
    if not isinstance(value, dict):
        raise CheckpointJournalError("checkpoint_journal_chain_payload_shape_invalid")
    return value


def _exact_keys(payload: dict[str, object], keys: set[str]) -> None:
    if set(payload) != keys:
        raise CheckpointJournalError("checkpoint_journal_chain_payload_shape_invalid")


def _ordinal(payload: dict[str, object]) -> int:
    value = payload.get("ordinal")
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < PUBLISHABLE_ANSWER_JUDGE_CALL_COUNT
    ):
        raise CheckpointJournalError("checkpoint_journal_chain_call_ordinal_invalid")
    return value


def _stage(payload: dict[str, object]) -> CallStage:
    try:
        return CallStage(str(payload.get("stage")))
    except ValueError as error:
        raise CheckpointJournalError("checkpoint_journal_chain_call_stage_invalid") from error


def _same_ordinal(payload: dict[str, object], call: _ReplayedCall) -> None:
    if _ordinal(payload) != call.ordinal:
        raise CheckpointJournalError("checkpoint_journal_chain_call_ordinal_mismatch")


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CheckpointJournalError(f"checkpoint_journal_chain_{name}_invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CheckpointJournalError(f"checkpoint_journal_chain_{name}_invalid")
    return value


def _require_call(
    calls: dict[str, _ReplayedCall],
    logical_call_id: str | None,
    phase: CallPhase | tuple[CallPhase, ...],
) -> _ReplayedCall:
    if logical_call_id is None or logical_call_id not in calls:
        raise CheckpointJournalError("checkpoint_journal_chain_call_missing")
    call = calls[logical_call_id]
    allowed = phase if isinstance(phase, tuple) else (phase,)
    if call.phase not in allowed:
        raise CheckpointJournalError("checkpoint_journal_chain_call_transition_invalid")
    return call


__all__ = (
    "EventChainVerification",
    "JournalReplayVerification",
    "compute_call_state_commitment",
    "replay_journal_events",
    "verify_journal_event_chain",
)
