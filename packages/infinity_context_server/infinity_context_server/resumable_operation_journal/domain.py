"""Provider-neutral contracts for the signed resumable operation journal."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import final

OPERATION_JOURNAL_SCHEMA_VERSION = "4"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OperationJournalError(RuntimeError):
    """Raised when a durable operation-journal invariant cannot be proven."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RetryDisposition(StrEnum):
    """The only restart policies permitted for a dispatched operation."""

    IDEMPOTENT_REPLAY = "idempotent_replay"
    QUARANTINE_UNKNOWN = "quarantine_unknown"


class OperationPhase(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    COMMITTED = "committed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class OperationRunPhase(StrEnum):
    ACTIVE = "active"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SEALED = "sealed"


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise OperationJournalError("operation_journal_payload_not_canonical") from error


def sha256_commitment(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _identifier(value: object, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise OperationJournalError(f"operation_journal_{name}_invalid")


def _digest(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise OperationJournalError(f"operation_journal_{name}_invalid")


@final
@dataclass(frozen=True, slots=True)
class LogicalOperationIdentity:
    """One immutable operation slot in an exact run manifest."""

    run_id: str
    operation_key: str
    operation_kind: str
    ordinal: int
    authority_commitment_sha256: str
    retry_disposition: RetryDisposition = RetryDisposition.QUARANTINE_UNKNOWN
    logical_operation_id: str = field(init=False)
    replay_key: str = field(init=False)

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.operation_key, "operation_key")
        _identifier(self.operation_kind, "operation_kind")
        _digest(self.authority_commitment_sha256, "authority_commitment_sha256")
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise OperationJournalError("operation_journal_ordinal_invalid")
        if not isinstance(self.retry_disposition, RetryDisposition):
            raise OperationJournalError("operation_journal_retry_disposition_invalid")
        payload = self.identity_payload()
        object.__setattr__(self, "logical_operation_id", sha256_commitment(payload))
        object.__setattr__(
            self,
            "replay_key",
            sha256_commitment(
                {
                    "operation_key": self.operation_key,
                    "operation_kind": self.operation_kind,
                    "run_id": self.run_id,
                }
            ),
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "authority_commitment_sha256": self.authority_commitment_sha256,
            "operation_key": self.operation_key,
            "operation_kind": self.operation_kind,
            "ordinal": self.ordinal,
            "retry_disposition": self.retry_disposition.value,
            "run_id": self.run_id,
        }


@final
@dataclass(frozen=True, slots=True)
class OperationManifest:
    """The exact ordered operation authority materialized before any dispatch."""

    operations: tuple[LogicalOperationIdentity, ...]
    run_id: str = field(init=False)
    commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.operations, tuple) or not self.operations:
            raise OperationJournalError("operation_journal_manifest_empty")
        run_id = self.operations[0].run_id
        if any(
            not isinstance(operation, LogicalOperationIdentity)
            or operation.run_id != run_id
            or operation.ordinal != ordinal
            for ordinal, operation in enumerate(self.operations)
        ):
            raise OperationJournalError("operation_journal_manifest_ordinal_drift")
        if len({item.logical_operation_id for item in self.operations}) != len(
            self.operations
        ) or len({item.replay_key for item in self.operations}) != len(self.operations):
            raise OperationJournalError("operation_journal_manifest_identity_duplicate")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(
            self,
            "commitment_sha256",
            sha256_commitment(
                {
                    "operations": tuple(item.identity_payload() for item in self.operations),
                    "schema_version": OPERATION_JOURNAL_SCHEMA_VERSION,
                }
            ),
        )


@final
@dataclass(frozen=True, slots=True)
class OperationRunIdentity:
    """Immutable authority for one generic operation run."""

    run_id: str
    operation_namespace: str
    manifest_commitment_sha256: str
    policy_commitment_sha256: str
    signer_key_id: str
    expected_operation_count: int
    journal_schema_version: str = OPERATION_JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.operation_namespace, "operation_namespace")
        _identifier(self.signer_key_id, "signer_key_id")
        _digest(self.manifest_commitment_sha256, "manifest_commitment_sha256")
        _digest(self.policy_commitment_sha256, "policy_commitment_sha256")
        if self.journal_schema_version != OPERATION_JOURNAL_SCHEMA_VERSION:
            raise OperationJournalError("operation_journal_schema_version_drift")
        if (
            not isinstance(self.expected_operation_count, int)
            or isinstance(self.expected_operation_count, bool)
            or self.expected_operation_count <= 0
        ):
            raise OperationJournalError("operation_journal_expected_count_invalid")

    def commitment_payload(self) -> dict[str, object]:
        return {
            "expected_operation_count": self.expected_operation_count,
            "journal_schema_version": self.journal_schema_version,
            "manifest_commitment_sha256": self.manifest_commitment_sha256,
            "operation_namespace": self.operation_namespace,
            "policy_commitment_sha256": self.policy_commitment_sha256,
            "run_id": self.run_id,
            "signer_key_id": self.signer_key_id,
        }


@final
@dataclass(frozen=True, slots=True)
class OperationReceipt:
    """Compact provider-neutral evidence for a completed operation."""

    run_id: str
    logical_operation_id: str
    request_commitment_sha256: str
    receipt_id: str
    result_commitment_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _digest(self.logical_operation_id, "logical_operation_id")
        _digest(self.request_commitment_sha256, "request_commitment_sha256")
        _identifier(self.receipt_id, "receipt_id")
        _digest(self.result_commitment_sha256, "result_commitment_sha256")

    def identity_payload(self) -> dict[str, str]:
        return {
            "logical_operation_id": self.logical_operation_id,
            "receipt_id": self.receipt_id,
            "request_commitment_sha256": self.request_commitment_sha256,
            "result_commitment_sha256": self.result_commitment_sha256,
            "run_id": self.run_id,
        }


@final
@dataclass(frozen=True, slots=True)
class VerifiedOperationReceipt:
    receipt: OperationReceipt
    verifier_key_id: str
    verification_commitment_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, OperationReceipt):
            raise OperationJournalError("operation_journal_receipt_type_invalid")
        _identifier(self.verifier_key_id, "verifier_key_id")
        _digest(self.verification_commitment_sha256, "verification_commitment_sha256")


@final
@dataclass(frozen=True, slots=True)
class OperationState:
    identity: LogicalOperationIdentity
    phase: OperationPhase = OperationPhase.PENDING
    request_commitment_sha256: str | None = None
    receipt: OperationReceipt | None = None
    verifier_key_id: str | None = None
    verification_commitment_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LogicalOperationIdentity) or not isinstance(
            self.phase, OperationPhase
        ):
            raise OperationJournalError("operation_journal_operation_state_invalid")
        if self.request_commitment_sha256 is not None:
            _digest(self.request_commitment_sha256, "request_commitment_sha256")
        if self.phase is not OperationPhase.PENDING and self.request_commitment_sha256 is None:
            raise OperationJournalError("operation_journal_request_commitment_missing")
        evidence = (self.receipt, self.verifier_key_id, self.verification_commitment_sha256)
        if self.phase is OperationPhase.COMMITTED:
            if not isinstance(self.receipt, OperationReceipt):
                raise OperationJournalError("operation_journal_committed_receipt_missing")
            if (
                self.receipt.run_id != self.identity.run_id
                or self.receipt.logical_operation_id != self.identity.logical_operation_id
                or self.receipt.request_commitment_sha256 != self.request_commitment_sha256
            ):
                raise OperationJournalError("operation_journal_receipt_binding_invalid")
            _identifier(self.verifier_key_id, "verifier_key_id")
            _digest(self.verification_commitment_sha256, "verification_commitment_sha256")
        elif any(item is not None for item in evidence):
            raise OperationJournalError("operation_journal_uncommitted_receipt_present")


@final
@dataclass(frozen=True, slots=True)
class OperationRunState:
    identity: OperationRunIdentity
    phase: OperationRunPhase = OperationRunPhase.ACTIVE
    event_count: int = 0
    head_event_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, OperationRunIdentity) or not isinstance(
            self.phase, OperationRunPhase
        ):
            raise OperationJournalError("operation_journal_run_state_invalid")
        if self.event_count < 0 or isinstance(self.event_count, bool):
            raise OperationJournalError("operation_journal_event_count_invalid")
        if (self.event_count == 0) != (self.head_event_sha256 is None):
            raise OperationJournalError("operation_journal_chain_head_invalid")
        if self.head_event_sha256 is not None:
            _digest(self.head_event_sha256, "head_event_sha256")


@final
@dataclass(frozen=True, slots=True)
class OperationEvent:
    run_id: str
    sequence: int
    event_type: str
    logical_operation_id: str | None
    payload_json: str
    predecessor_event_sha256: str | None
    event_sha256: str
    signer_key_id: str
    signature: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(self.event_type, "event_type")
        if self.sequence <= 0 or isinstance(self.sequence, bool):
            raise OperationJournalError("operation_journal_event_sequence_invalid")
        if self.logical_operation_id is not None:
            _digest(self.logical_operation_id, "logical_operation_id")
        try:
            parsed = json.loads(self.payload_json)
        except (TypeError, ValueError) as error:
            raise OperationJournalError("operation_journal_event_payload_invalid") from error
        if canonical_json(parsed) != self.payload_json:
            raise OperationJournalError("operation_journal_event_payload_noncanonical")
        if self.predecessor_event_sha256 is not None:
            _digest(self.predecessor_event_sha256, "predecessor_event_sha256")
        _digest(self.event_sha256, "event_sha256")
        _identifier(self.signer_key_id, "signer_key_id")
        if not isinstance(self.signature, str) or not self.signature:
            raise OperationJournalError("operation_journal_signature_invalid")

    def hash_payload(self) -> dict[str, object]:
        return {
            "event_type": self.event_type,
            "logical_operation_id": self.logical_operation_id,
            "payload_json": self.payload_json,
            "predecessor_event_sha256": self.predecessor_event_sha256,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "signer_key_id": self.signer_key_id,
        }


@final
@dataclass(frozen=True, slots=True)
class DispatchPreparation:
    state: OperationState
    should_dispatch: bool


@final
@dataclass(frozen=True, slots=True)
class OperationResumeResult:
    run: OperationRunState
    replayable_count: int
    outcome_unknown_count: int


@final
@dataclass(frozen=True, slots=True)
class OperationJournalSnapshot:
    run: OperationRunState
    pending_count: int
    dispatched_count: int
    committed_count: int
    outcome_unknown_count: int
    state_commitment_sha256: str


def operation_state_projection(state: OperationState) -> dict[str, object]:
    """Return the canonical durable projection used by replay and SQLite."""

    receipt = state.receipt
    return {
        "logical_operation_id": state.identity.logical_operation_id,
        "ordinal": state.identity.ordinal,
        "phase": state.phase.value,
        "receipt_id": receipt.receipt_id if receipt is not None else None,
        "request_commitment_sha256": state.request_commitment_sha256,
        "result_commitment_sha256": (
            receipt.result_commitment_sha256 if receipt is not None else None
        ),
        "verification_commitment_sha256": state.verification_commitment_sha256,
        "verifier_key_id": state.verifier_key_id,
    }


def operation_states_commitment(states: object) -> str:
    """Hash ordered operation projections without unbounded materialization."""

    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for state in states:  # type: ignore[union-attr]
        if not isinstance(state, OperationState):
            raise OperationJournalError("operation_journal_state_stream_invalid")
        if not first:
            digest.update(b",")
        digest.update(canonical_json(operation_state_projection(state)).encode())
        first = False
    digest.update(b"]")
    return digest.hexdigest()


def verified_receipt_projection(verified: VerifiedOperationReceipt) -> dict[str, object]:
    """Return the complete evidence projection committed by replay and storage."""

    return {
        "receipt": verified.receipt.identity_payload(),
        "verification_commitment_sha256": verified.verification_commitment_sha256,
        "verifier_key_id": verified.verifier_key_id,
    }


def verified_receipts_commitment(receipts: object) -> str:
    """Hash ordered verified receipts so missing evidence fails closed."""

    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for verified in receipts:  # type: ignore[union-attr]
        if not isinstance(verified, VerifiedOperationReceipt):
            raise OperationJournalError("operation_journal_receipt_stream_invalid")
        if not first:
            digest.update(b",")
        digest.update(canonical_json(verified_receipt_projection(verified)).encode())
        first = False
    digest.update(b"]")
    return digest.hexdigest()


def create_operation_event(
    *,
    run: OperationRunState,
    event_type: str,
    logical_operation_id: str | None,
    payload: Mapping[str, object],
    signer_key_id: str,
    sign: Callable[[bytes], str],
) -> OperationEvent:
    payload_json = canonical_json(payload)
    provisional = OperationEvent(
        run_id=run.identity.run_id,
        sequence=run.event_count + 1,
        event_type=event_type,
        logical_operation_id=logical_operation_id,
        payload_json=payload_json,
        predecessor_event_sha256=run.head_event_sha256,
        event_sha256="0" * 64,
        signer_key_id=signer_key_id,
        signature="provisional",
    )
    event_sha256 = sha256_commitment(provisional.hash_payload())
    return OperationEvent(
        run_id=provisional.run_id,
        sequence=provisional.sequence,
        event_type=event_type,
        logical_operation_id=logical_operation_id,
        payload_json=payload_json,
        predecessor_event_sha256=provisional.predecessor_event_sha256,
        event_sha256=event_sha256,
        signer_key_id=signer_key_id,
        signature=sign(event_sha256.encode("ascii")),
    )
