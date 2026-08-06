"""Ports owned by the publishable evaluation-journal application boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol

from infinity_context_server.publishable_checkpoint_journal.domain import (
    CallPhase,
    EvaluationCoverage,
    JournalEvent,
    JournalRunState,
    LogicalCallIdentity,
    ProviderCallState,
    PublishableEvaluationManifest,
    RuntimeReceipt,
    VerifiedRuntimeReceipt,
)


class JournalHmacSignerPort(Protocol):
    """Sign and authenticate local chain records with one configured key."""

    @property
    def key_id(self) -> str:
        """Return the stable identifier for the injected signing key."""

    def sign(self, message: bytes) -> str:
        """Return an authenticated signature for an immutable byte sequence."""

    def verify(self, message: bytes, signature: str) -> bool:
        """Return whether a signature was created with this exact key."""


class RuntimeReceiptVerifierPort(Protocol):
    """Verify a provider-neutral receipt before it enters the local journal."""

    def verify(
        self,
        *,
        identity: LogicalCallIdentity,
        receipt: RuntimeReceipt,
    ) -> VerifiedRuntimeReceipt:
        """Return a verifier-bound receipt or raise before any journal write."""


class ExternalLifecyclePort(Protocol):
    """Idempotently consume a durable authority event outside a journal transaction."""

    def deliver(self, event: JournalEvent) -> None:
        """Deliver one event using event_sha256 as the idempotency key."""


class CheckpointJournalTransactionPort(Protocol):
    """Persistence operations valid only inside one immediate write transaction."""

    def get_run(self, run_id: str) -> JournalRunState | None:
        """Load a run state under the transaction lock."""

    def put_run(self, state: JournalRunState) -> None:
        """Create or update one run state."""

    def put_evaluation_manifest(self, manifest: PublishableEvaluationManifest) -> None:
        """Persist the immutable exact provider-call manifest once."""

    def get_evaluation_manifest_call(
        self,
        *,
        run_id: str,
        ordinal: int,
    ) -> LogicalCallIdentity | None:
        """Load the one exact manifest slot assigned to a global ordinal."""

    def get_call(self, *, run_id: str, logical_call_id: str) -> ProviderCallState | None:
        """Load a runtime call by its immutable full identity."""

    def get_call_by_replay_key(
        self,
        *,
        run_id: str,
        replay_key: str,
    ) -> ProviderCallState | None:
        """Load a call slot without accepting request-commitment drift."""

    def put_call(self, state: ProviderCallState) -> None:
        """Create or update one manifest-bound provider call state."""

    def put_private_provider_result(
        self,
        *,
        state: ProviderCallState,
        verified_receipt: VerifiedRuntimeReceipt,
    ) -> None:
        """Persist only receipt identity/commitments, never a provider body."""

    def append_event(self, event: JournalEvent) -> None:
        """Append one pre-authenticated event."""

    def enqueue_lifecycle_event(self, event: JournalEvent) -> None:
        """Durably enqueue one external authority event in the same transaction."""

    def has_calls_in_phase(self, *, run_id: str, phase: CallPhase) -> bool:
        """Return whether one phase exists without materializing call rows."""

    def count_calls_in_phase(self, *, run_id: str, phase: CallPhase) -> int:
        """Count one phase in SQL without materializing call rows."""

    def evaluation_coverage(self, *, run_id: str) -> EvaluationCoverage:
        """Return aggregate manifest/receipt coverage without materializing calls."""

    def runtime_state_commitment(self, *, run_id: str) -> str:
        """Return the ordered durable call-state commitment."""

    def iter_calls(
        self,
        *,
        run_id: str,
        phases: tuple[CallPhase, ...] | None = None,
        batch_size: int = 256,
    ) -> Iterator[ProviderCallState]:
        """Yield calls in batches; callers must exhaust or explicitly close."""

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[JournalEvent]:
        """Yield events in batches; callers must exhaust or explicitly close."""

    def mark_lifecycle_event_delivered(self, *, run_id: str, event_sha256: str) -> None:
        """Mark an event delivered after an idempotent external acknowledgement."""


class CheckpointJournalPort(Protocol):
    """Durable checkpoint journal abstraction used by application policy."""

    @property
    def schema_version(self) -> str:
        """Return the validated on-disk journal schema version."""

    def write_transaction(
        self,
    ) -> AbstractContextManager[CheckpointJournalTransactionPort]:
        """Start an immediate write transaction."""

    def load_run(self, run_id: str) -> JournalRunState | None:
        """Load one durable run without opening a write transaction."""

    def iter_calls(
        self,
        *,
        run_id: str,
        phases: tuple[CallPhase, ...] | None = None,
        batch_size: int = 256,
    ) -> Iterator[ProviderCallState]:
        """Yield durable calls in batches; callers must exhaust or explicitly close."""

    def iter_events(self, *, run_id: str, batch_size: int = 256) -> Iterator[JournalEvent]:
        """Yield chain entries in batches; callers must exhaust or explicitly close."""

    def iter_pending_lifecycle_events(
        self,
        *,
        run_id: str,
        batch_size: int = 64,
    ) -> Iterator[JournalEvent]:
        """Yield pending events in batches; callers must exhaust or explicitly close."""


__all__ = (
    "CheckpointJournalPort",
    "CheckpointJournalTransactionPort",
    "ExternalLifecyclePort",
    "JournalHmacSignerPort",
    "RuntimeReceiptVerifierPort",
)
