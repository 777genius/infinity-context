"""Application-owned ports for the resumable operation journal."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationEvent,
    OperationJournalCheckpoint,
    OperationJournalFacts,
    OperationManifest,
    OperationReceipt,
    OperationRunIdentity,
    OperationRunState,
    OperationState,
    VerifiedOperationReceipt,
)


class OperationJournalSignerPort(Protocol):
    @property
    def key_id(self) -> str: ...

    def sign(self, message: bytes) -> str: ...

    def verify(self, message: bytes, signature: str) -> bool: ...


class OperationManifestPolicyPort(Protocol):
    """Validate composition-owned manifest policy before persistence."""

    def validate(
        self,
        *,
        identity: OperationRunIdentity,
        manifest: OperationManifest,
    ) -> None: ...


class OperationReceiptVerifierPort(Protocol):
    """Verify external evidence before opening a journal transaction."""

    def verify(
        self,
        *,
        identity: LogicalOperationIdentity,
        receipt: OperationReceipt,
    ) -> VerifiedOperationReceipt: ...


class OperationNotificationPort(Protocol):
    """Idempotently deliver an event using its hash as delivery key."""

    def deliver(self, event: OperationEvent) -> None: ...


class OperationJournalTransactionPort(Protocol):
    def get_run(self, run_id: str) -> OperationRunState | None: ...

    def put_run(self, state: OperationRunState) -> None: ...

    def put_manifest(self, manifest: OperationManifest) -> None: ...

    def get_manifest_operation(
        self, *, run_id: str, ordinal: int
    ) -> LogicalOperationIdentity | None: ...

    def get_operation(self, *, run_id: str, logical_operation_id: str) -> OperationState | None: ...

    def get_authenticated_operation(
        self,
        *,
        run_id: str,
        ordinal: int,
        facts: OperationJournalFacts,
    ) -> OperationState | None: ...

    def put_operation(self, state: OperationState) -> None: ...

    def put_receipt(self, *, state: OperationState, verified: VerifiedOperationReceipt) -> None: ...

    def apply_operation_transition(
        self,
        *,
        state: OperationState,
        verified: VerifiedOperationReceipt | None,
        expected_facts: OperationJournalFacts,
    ) -> OperationJournalFacts: ...

    def get_checkpoint(self, *, run_id: str) -> OperationJournalCheckpoint | None: ...

    def put_checkpoint(self, checkpoint: OperationJournalCheckpoint) -> None: ...

    def append_event(self, event: OperationEvent) -> None: ...

    def enqueue_notification(self, event: OperationEvent) -> None: ...

    def mark_notification_delivered(self, *, run_id: str, event_sha256: str) -> None: ...

    def iter_operations(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[OperationState]: ...

    def operation_phase_page(
        self,
        *,
        run_id: str,
        phases: tuple[str, ...],
        after_ordinal: int = -1,
        batch_size: int = 512,
    ) -> tuple[OperationState, ...]: ...

    def iter_manifest(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[LogicalOperationIdentity]: ...

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[OperationEvent]: ...

    def iter_verified_receipts(
        self, *, run_id: str, batch_size: int = 256
    ) -> Iterator[VerifiedOperationReceipt]: ...

    def phase_counts(self, *, run_id: str) -> dict[str, int]: ...

    def state_commitment(self, *, run_id: str) -> str: ...

    def receipt_count(self, *, run_id: str) -> int: ...

    def receipts_commitment(self, *, run_id: str) -> str: ...


class OperationJournalPort(Protocol):
    @property
    def schema_version(self) -> str: ...

    def write_transaction(
        self,
    ) -> AbstractContextManager[OperationJournalTransactionPort]: ...

    def iter_pending_notifications(
        self, *, run_id: str, batch_size: int = 64
    ) -> Iterator[OperationEvent]: ...


__all__ = (
    "OperationJournalPort",
    "OperationJournalSignerPort",
    "OperationJournalTransactionPort",
    "OperationManifestPolicyPort",
    "OperationNotificationPort",
    "OperationReceiptVerifierPort",
)
