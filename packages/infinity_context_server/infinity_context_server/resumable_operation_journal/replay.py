"""Authenticated replay for the generic v4 operation journal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import final

from infinity_context_server.resumable_operation_journal.commitments import (
    RECEIPT_TREE,
    STATE_TREE,
    StreamingCommitmentTree,
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
    OperationPhase,
    OperationReceipt,
    OperationRunPhase,
    OperationRunState,
    OperationState,
    RetryDisposition,
    VerifiedOperationReceipt,
    canonical_json,
    sha256_commitment,
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


@final
@dataclass(frozen=True, slots=True)
class OperationEventChainVerification:
    """Authenticated terminal chain position and optional checkpoint boundary."""

    event_count: int
    head_event_sha256: str | None
    checkpoint_event_count: int | None = None
    checkpoint_head_event_sha256: str | None = None
    first_extra_event: OperationEvent | None = None
    last_extra_event: OperationEvent | None = None


def stream_operation_manifest_commitment(
    operations: object,
    *,
    expected_run_id: str | None = None,
    expected_operation_count: int | None = None,
) -> str:
    """Hash an ordered manifest with the exact ``OperationManifest`` wire format.

    The stream must be in ordinal order. Global identity uniqueness remains a
    canonical-storage constraint because proving it here would retain O(N)
    identity material.
    """

    if expected_operation_count is not None and (
        not isinstance(expected_operation_count, int)
        or isinstance(expected_operation_count, bool)
        or expected_operation_count <= 0
    ):
        raise OperationJournalError("operation_journal_expected_count_invalid")
    digest = hashlib.sha256()
    digest.update(b'{"operations":[')
    count = 0
    run_id = expected_run_id
    for operation in _iterator(operations, "operation_journal_manifest_stream_invalid"):
        if not isinstance(operation, LogicalOperationIdentity):
            raise OperationJournalError("operation_journal_manifest_ordinal_drift")
        if run_id is None:
            run_id = operation.run_id
        if operation.run_id != run_id or operation.ordinal != count:
            raise OperationJournalError("operation_journal_manifest_ordinal_drift")
        if count:
            digest.update(b",")
        digest.update(canonical_json(operation.identity_payload()).encode())
        count += 1
    if count == 0:
        raise OperationJournalError("operation_journal_manifest_empty")
    if expected_operation_count is not None and count != expected_operation_count:
        raise OperationJournalError("operation_journal_manifest_count_mismatch")
    digest.update(b'],"schema_version":')
    digest.update(canonical_json(OPERATION_JOURNAL_SCHEMA_VERSION).encode())
    digest.update(b"}")
    return digest.hexdigest()


def rebuild_operation_journal_facts(
    states: object,
    receipts: object,
    *,
    expected_run_id: str,
    expected_operation_count: int,
) -> OperationJournalFacts:
    """Rebuild exact Merkle facts from two ordered, caller-batched streams.

    ``states`` is the sparse ordinal-ordered state projection. ``receipts`` is
    ordered by the ordinals of committed states. Only one item of lookahead and
    the two O(log N) Merkle frontiers are retained.
    """

    state_tree = StreamingCommitmentTree(STATE_TREE, expected_operation_count)
    receipt_tree = StreamingCommitmentTree(RECEIPT_TREE, expected_operation_count)
    state_iterator = _iterator(states, "operation_journal_state_stream_invalid")
    receipt_iterator = _iterator(receipts, "operation_journal_receipt_stream_invalid")
    next_state = _next_state(state_iterator)
    previous_state_ordinal = -1
    committed_prefix_count = 0
    prefix_open = True
    first_unsettled = None

    for ordinal in range(expected_operation_count):
        state: OperationState | None = None
        if next_state is not None:
            state_ordinal = next_state.identity.ordinal
            if (
                next_state.identity.run_id != expected_run_id
                or state_ordinal <= previous_state_ordinal
                or state_ordinal < ordinal
                or state_ordinal >= expected_operation_count
            ):
                raise OperationJournalError("operation_journal_state_stream_invalid")
            if state_ordinal == ordinal:
                state = next_state
                previous_state_ordinal = state_ordinal
                next_state = _next_state(state_iterator)

        verified: VerifiedOperationReceipt | None = None
        if state is not None and state.phase is OperationPhase.COMMITTED:
            verified = _next_receipt(receipt_iterator)
            if verified is None or not _verified_receipt_matches_state(verified, state):
                raise OperationJournalError("operation_journal_receipt_stream_invalid")
        if prefix_open:
            if state is not None and state.phase is OperationPhase.COMMITTED:
                committed_prefix_count += 1
            else:
                prefix_open = False
        if (
            first_unsettled is None
            and state is not None
            and state.phase in (OperationPhase.DISPATCHED, OperationPhase.OUTCOME_UNKNOWN)
        ):
            first_unsettled = unsettled_from_state(state)
        state_tree.append(state_leaf(state))
        receipt_tree.append(receipt_leaf(ordinal, verified))

    if next_state is not None or _next_receipt(receipt_iterator) is not None:
        raise OperationJournalError("operation_journal_projection_stream_trailing")
    return facts_from_roots(
        state=state_tree.finish(),
        receipts=receipt_tree.finish(),
        committed_prefix_count=committed_prefix_count,
        first_unsettled=first_unsettled,
    )


def verify_operation_event_stream(
    events: object,
    *,
    run: OperationRunState,
    signer: OperationJournalSignerPort,
    checkpoint: OperationJournalCheckpoint | None = None,
) -> OperationEventChainVerification:
    """Authenticate a full event stream and an optional signed boundary.

    A checkpoint may trail the run. In that case the returned first extra event
    lets recovery distinguish a contiguous signed tail from an exact checkpoint.
    """

    if signer.key_id != run.identity.signer_key_id:
        raise OperationJournalError("operation_journal_signer_key_mismatch")
    checkpoint_count: int | None = None
    checkpoint_head: str | None = None
    if checkpoint is not None:
        if (
            checkpoint.run.identity != run.identity
            or checkpoint.signer_key_id != signer.key_id
            or checkpoint.run.event_count > run.event_count
            or not signer.verify(checkpoint.checkpoint_sha256.encode("ascii"), checkpoint.signature)
        ):
            raise OperationJournalError("operation_journal_checkpoint_invalid")
        checkpoint_count = checkpoint.run.event_count
        checkpoint_head = checkpoint.run.head_event_sha256

    predecessor: str | None = None
    sequence = 0
    first_extra_event: OperationEvent | None = None
    last_extra_event: OperationEvent | None = None
    boundary_observed = checkpoint_count in (None, 0)
    for item in _iterator(events, "operation_journal_event_chain_invalid"):
        if not isinstance(item, OperationEvent):
            raise OperationJournalError("operation_journal_replay_event_invalid")
        sequence += 1
        _authenticate_event(
            item,
            run=run,
            signer=signer,
            expected_sequence=sequence,
            expected_predecessor=predecessor,
        )
        predecessor = item.event_sha256
        if checkpoint_count is not None:
            if sequence == checkpoint_count:
                if predecessor != checkpoint_head:
                    raise OperationJournalError("operation_journal_checkpoint_chain_invalid")
                boundary_observed = True
            elif sequence == checkpoint_count + 1:
                first_extra_event = item
                last_extra_event = item
            elif sequence > checkpoint_count:
                last_extra_event = item

    if sequence != run.event_count or predecessor != run.head_event_sha256 or not boundary_observed:
        raise OperationJournalError("operation_journal_event_chain_invalid")
    return OperationEventChainVerification(
        event_count=sequence,
        head_event_sha256=predecessor,
        checkpoint_event_count=checkpoint_count,
        checkpoint_head_event_sha256=checkpoint_head,
        first_extra_event=first_extra_event,
        last_extra_event=last_extra_event,
    )


def replay_operation_events(
    events: object,
    *,
    run: OperationRunState,
    manifest_by_id: dict[str, object],
    signer: OperationJournalSignerPort,
) -> OperationReplayVerification:
    """Legacy semantic replay using O(N) compatibility state, never recovery.

    Recovery uses the bounded manifest, fact, and event-stream primitives above.
    This compatibility API retains one state per touched operation, but all
    transitions are constant-time and final projections stream in ordinal order.
    """

    predecessor: str | None = None
    sequence = 0
    phase = OperationRunPhase.ACTIVE
    initialized = False
    pending_count = run.identity.expected_operation_count
    dispatched_count = 0
    committed_count = 0
    unknown_count = 0
    last_committed_from_unknown: str | None = None
    sealed_facts: OperationJournalFacts | None = None
    with _ReplayProjection(
        manifest_by_id,
        expected_operation_count=run.identity.expected_operation_count,
    ) as projection:
        for item in _iterator(events, "operation_journal_replay_event_invalid"):
            if not isinstance(item, OperationEvent):
                raise OperationJournalError("operation_journal_replay_event_invalid")
            sequence += 1
            _authenticate_event(
                item,
                run=run,
                signer=signer,
                expected_sequence=sequence,
                expected_predecessor=predecessor,
            )
            payload = json.loads(item.payload_json)
            if not isinstance(payload, dict):
                raise OperationJournalError("operation_journal_replay_payload_invalid")
            logical_id = item.logical_operation_id
            if phase is OperationRunPhase.SEALED:
                raise OperationJournalError("operation_journal_post_seal_event")
            if item.event_type == "run_initialized":
                if (
                    sequence != 1
                    or initialized
                    or logical_id is not None
                    or payload != run.identity.commitment_payload()
                ):
                    raise OperationJournalError("operation_journal_initialize_replay_invalid")
                initialized = True
            elif item.event_type == "operation_dispatched":
                _require_initialized(initialized)
                identity = manifest_by_id.get(logical_id or "")
                if not isinstance(identity, LogicalOperationIdentity):
                    raise OperationJournalError("operation_journal_dispatch_replay_invalid")
                request_hash = _string(payload, "request_commitment_sha256")
                expected = {
                    "ordinal": identity.ordinal,
                    "request_commitment_sha256": request_hash,
                    "retry_disposition": identity.retry_disposition.value,
                }
                current = projection.get(logical_id)
                if payload != expected or (
                    current is not None
                    and (
                        current.phase is not OperationPhase.PENDING
                        or current.request_commitment_sha256 != request_hash
                    )
                ):
                    raise OperationJournalError("operation_journal_dispatch_replay_invalid")
                projection.put(
                    OperationState(
                        identity=identity,
                        phase=OperationPhase.DISPATCHED,
                        request_commitment_sha256=request_hash,
                    )
                )
                pending_count -= 1
                dispatched_count += 1
            elif item.event_type == "operation_replay_scheduled":
                _require_initialized(initialized)
                current = _require_replay_state(projection, logical_id)
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
                projection.put(
                    OperationState(
                        identity=current.identity,
                        request_commitment_sha256=current.request_commitment_sha256,
                    )
                )
                dispatched_count -= 1
                pending_count += 1
            elif item.event_type == "operation_outcome_unknown":
                _require_initialized(initialized)
                current = _require_replay_state(projection, logical_id)
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
                projection.put(
                    OperationState(
                        identity=current.identity,
                        phase=OperationPhase.OUTCOME_UNKNOWN,
                        request_commitment_sha256=current.request_commitment_sha256,
                    )
                )
                dispatched_count -= 1
                unknown_count += 1
            elif item.event_type == "operation_committed":
                _require_initialized(initialized)
                current = _require_replay_state(projection, logical_id)
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
                if payload != expected:
                    raise OperationJournalError("operation_journal_commit_replay_invalid")
                committed = OperationState(
                    identity=current.identity,
                    phase=OperationPhase.COMMITTED,
                    request_commitment_sha256=current.request_commitment_sha256,
                    receipt=receipt,
                    verifier_key_id=_string(payload, "verifier_key_id"),
                    verification_commitment_sha256=_string(
                        payload, "verification_commitment_sha256"
                    ),
                )
                projection.put(committed)
                if current.phase is OperationPhase.DISPATCHED:
                    dispatched_count -= 1
                elif current.phase is OperationPhase.OUTCOME_UNKNOWN:
                    unknown_count -= 1
                else:
                    pending_count -= 1
                committed_count += 1
                last_committed_from_unknown = (
                    logical_id if current.phase is OperationPhase.OUTCOME_UNKNOWN else None
                )
            elif item.event_type == "reconciliation_required":
                _require_initialized(initialized)
                if (
                    logical_id is not None
                    or phase is not OperationRunPhase.ACTIVE
                    or unknown_count == 0
                    or dispatched_count != 0
                    or payload != {"outcome_unknown_count": unknown_count}
                ):
                    raise OperationJournalError("operation_journal_reconciliation_replay_invalid")
                phase = OperationRunPhase.RECONCILIATION_REQUIRED
            elif item.event_type == "reconciliation_cleared":
                _require_initialized(initialized)
                resolved_id = payload.get("resolved_logical_operation_id")
                if (
                    logical_id is not None
                    or phase is not OperationRunPhase.RECONCILIATION_REQUIRED
                    or not isinstance(resolved_id, str)
                    or payload != {"resolved_logical_operation_id": resolved_id}
                    or resolved_id != last_committed_from_unknown
                    or _require_replay_state(projection, resolved_id).phase
                    is not OperationPhase.COMMITTED
                    or unknown_count != 0
                ):
                    raise OperationJournalError("operation_journal_reconciliation_replay_invalid")
                phase = OperationRunPhase.ACTIVE
                last_committed_from_unknown = None
            elif item.event_type == "run_sealed":
                _require_initialized(initialized)
                sealed_facts = rebuild_operation_journal_facts(
                    projection.iter_states(),
                    projection.iter_receipts(),
                    expected_run_id=run.identity.run_id,
                    expected_operation_count=run.identity.expected_operation_count,
                )
                if (
                    logical_id is not None
                    or phase is not OperationRunPhase.ACTIVE
                    or pending_count != 0
                    or dispatched_count != 0
                    or committed_count != run.identity.expected_operation_count
                    or unknown_count != 0
                    or payload
                    != {
                        "committed_count": run.identity.expected_operation_count,
                        "state_commitment_sha256": (sealed_facts.state_commitment_sha256),
                    }
                ):
                    raise OperationJournalError("operation_journal_seal_replay_invalid")
                phase = OperationRunPhase.SEALED
            else:
                raise OperationJournalError("operation_journal_event_type_unknown")
            predecessor = item.event_sha256
        _require_initialized(initialized)
        facts = sealed_facts or rebuild_operation_journal_facts(
            projection.iter_states(),
            projection.iter_receipts(),
            expected_run_id=run.identity.run_id,
            expected_operation_count=run.identity.expected_operation_count,
        )
        return OperationReplayVerification(
            event_count=sequence,
            head_event_sha256=predecessor,
            phase=phase,
            state_commitment_sha256=facts.state_commitment_sha256,
            receipt_count=facts.receipt_count,
            receipts_commitment_sha256=facts.receipts_commitment_sha256,
        )


def _require_initialized(initialized: bool) -> None:
    if not initialized:
        raise OperationJournalError("operation_journal_initialize_replay_invalid")


@final
class _ReplayProjection:
    """O(N) legacy replay state; not used by bounded journal recovery."""

    __slots__ = (
        "_expected_operation_count",
        "_manifest_by_id",
        "_receipt_ids",
        "_states_by_ordinal",
    )

    def __init__(
        self,
        manifest_by_id: dict[str, object],
        *,
        expected_operation_count: int,
    ) -> None:
        self._manifest_by_id = manifest_by_id
        self._expected_operation_count = expected_operation_count
        self._states_by_ordinal: dict[int, OperationState] = {}
        self._receipt_ids: set[str] = set()

    def __enter__(self) -> _ReplayProjection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, logical_operation_id: str | None) -> OperationState | None:
        if logical_operation_id is None:
            return None
        identity = self._manifest_by_id.get(logical_operation_id)
        if not isinstance(identity, LogicalOperationIdentity):
            return None
        state = self._states_by_ordinal.get(identity.ordinal)
        if state is not None and state.identity != identity:
            raise OperationJournalError("operation_journal_replay_state_missing")
        return state

    def put(self, state: OperationState) -> None:
        receipt = state.receipt
        if receipt is not None:
            if receipt.receipt_id in self._receipt_ids:
                raise OperationJournalError("operation_journal_commit_replay_invalid")
            self._receipt_ids.add(receipt.receipt_id)
        current = self._states_by_ordinal.get(state.identity.ordinal)
        if current is not None and current.identity != state.identity:
            raise OperationJournalError("operation_journal_replay_state_missing")
        self._states_by_ordinal[state.identity.ordinal] = state

    def iter_states(self) -> Iterator[OperationState]:
        for ordinal in range(self._expected_operation_count):
            state = self._states_by_ordinal.get(ordinal)
            if state is not None:
                yield state

    def iter_receipts(self) -> Iterator[VerifiedOperationReceipt]:
        for state in self.iter_states():
            if state.phase is OperationPhase.COMMITTED:
                if state.receipt is None:
                    raise OperationJournalError("operation_journal_receipt_stream_invalid")
                yield VerifiedOperationReceipt(
                    receipt=state.receipt,
                    verifier_key_id=state.verifier_key_id or "",
                    verification_commitment_sha256=(state.verification_commitment_sha256 or ""),
                )


def _require_replay_state(
    projection: _ReplayProjection,
    logical_operation_id: str | None,
) -> OperationState:
    state = projection.get(logical_operation_id)
    if state is None:
        raise OperationJournalError("operation_journal_replay_state_missing")
    return state


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise OperationJournalError("operation_journal_replay_payload_invalid")
    return value


def _iterator(value: object, error_code: str) -> Iterator[object]:
    try:
        return iter(value)  # type: ignore[arg-type,return-value]
    except TypeError as error:
        raise OperationJournalError(error_code) from error


def _next_state(iterator: Iterator[object]) -> OperationState | None:
    try:
        state = next(iterator)
    except StopIteration:
        return None
    if not isinstance(state, OperationState):
        raise OperationJournalError("operation_journal_state_stream_invalid")
    return state


def _next_receipt(iterator: Iterator[object]) -> VerifiedOperationReceipt | None:
    try:
        verified = next(iterator)
    except StopIteration:
        return None
    if not isinstance(verified, VerifiedOperationReceipt):
        raise OperationJournalError("operation_journal_receipt_stream_invalid")
    return verified


def _verified_receipt_matches_state(
    verified: VerifiedOperationReceipt,
    state: OperationState,
) -> bool:
    return (
        verified.receipt == state.receipt
        and verified.verifier_key_id == state.verifier_key_id
        and verified.verification_commitment_sha256 == state.verification_commitment_sha256
    )


def _authenticate_event(
    event: OperationEvent,
    *,
    run: OperationRunState,
    signer: OperationJournalSignerPort,
    expected_sequence: int,
    expected_predecessor: str | None,
) -> None:
    if (
        event.run_id != run.identity.run_id
        or event.sequence != expected_sequence
        or event.predecessor_event_sha256 != expected_predecessor
        or event.signer_key_id != run.identity.signer_key_id
        or event.signer_key_id != signer.key_id
        or sha256_commitment(event.hash_payload()) != event.event_sha256
        or not signer.verify(event.event_sha256.encode("ascii"), event.signature)
    ):
        raise OperationJournalError("operation_journal_event_chain_invalid")


__all__ = (
    "OperationEventChainVerification",
    "OperationReplayVerification",
    "rebuild_operation_journal_facts",
    "replay_operation_events",
    "stream_operation_manifest_commitment",
    "verify_operation_event_stream",
)
