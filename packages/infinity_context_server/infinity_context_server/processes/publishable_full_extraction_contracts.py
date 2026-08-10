"""Provider-neutral contracts for the publishable full-extraction worker."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, final

from infinity_context_core.ports.managed_full_run_extraction_ledger import (
    ManagedFullRunExpectedOperationPagePort,
    ManagedFullRunExtractionContext,
    ManagedFullRunExtractionLedgerPort,
    ManagedFullRunExtractionTerminal,
    canonical_sha256,
)

from infinity_context_server.memory_comparison_mem0_oss_v5_observed_receipt import (
    Mem0V5ObservedExtractionOperationAuthority,
    Mem0V5ObservedExtractionReceiptAuthority,
)
from infinity_context_server.resumable_operation_journal.domain import (
    LogicalOperationIdentity,
    OperationJournalSnapshot,
    OperationManifest,
    OperationReceipt,
    OperationRunIdentity,
    RetryDisposition,
)
from infinity_context_server.resumable_operation_journal.ports import OperationJournalPort
from infinity_context_server.resumable_operation_journal.service import (
    ResumableOperationJournalService,
)

PUBLISHABLE_EXTRACTION_WORKER_SCHEMA = "publishable-full-extraction-worker.v1"
PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA = "publishable-full-extraction-terminal.v1"
MANAGED_MEM0_EXTRACTION_NAMESPACE = "managed_mem0_v5_production"
MANAGED_MEM0_EXTRACTION_OPERATION_KIND = "managed_mem0_v5_extraction"


class PublishableExtractionWorkerError(RuntimeError):
    """Stable provider-free failure for the extraction composition."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PublishableExtractionAdvancePhase(StrEnum):
    OPERATION_COMMITTED = "operation_committed"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    SEALED = "sealed"


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionRunAuthority:
    """Exact journal, runtime-receipt, and strict-v4 extraction authority."""

    journal_identity: OperationRunIdentity
    operation_manifest: OperationManifest
    runtime_receipt_authority: Mem0V5ObservedExtractionReceiptAuthority
    ledger_context: ManagedFullRunExtractionContext
    preparation_receipt_sha256: str
    dataset_sha256: str
    a2_terminal_commitment_sha256: str

    def __post_init__(self) -> None:
        identity = self.journal_identity
        manifest = self.operation_manifest
        runtime = self.runtime_receipt_authority
        context = self.ledger_context
        if (
            type(identity) is not OperationRunIdentity
            or type(manifest) is not OperationManifest
            or type(runtime) is not Mem0V5ObservedExtractionReceiptAuthority
            or type(context) is not ManagedFullRunExtractionContext
            or any(
                not _sha(value)
                for value in (
                    self.preparation_receipt_sha256,
                    self.dataset_sha256,
                    self.a2_terminal_commitment_sha256,
                )
            )
            or identity.operation_namespace != MANAGED_MEM0_EXTRACTION_NAMESPACE
            or manifest.run_id != identity.run_id
            or manifest.commitment_sha256 != identity.manifest_commitment_sha256
            or identity.expected_operation_count != len(manifest.operations)
            or len(runtime.operations) != len(manifest.operations)
            or context.expected_receipt_count != len(manifest.operations)
            or context.admission_commitment_sha256 != runtime.admission_commitment_sha256
            or hashlib.sha256(identity.run_id.encode()).hexdigest() != context.run_id_sha256
        ):
            _fail("extraction_run_authority_invalid")
        for ordinal, (operation, observed) in enumerate(
            zip(manifest.operations, runtime.operations, strict=True)
        ):
            if (
                type(operation) is not LogicalOperationIdentity
                or type(observed) is not Mem0V5ObservedExtractionOperationAuthority
                or operation.ordinal != ordinal
                or observed.sequence != ordinal
                or operation.run_id != identity.run_id
                or operation.operation_kind != MANAGED_MEM0_EXTRACTION_OPERATION_KIND
                or operation.operation_key != observed.operation_id_sha256
                or operation.retry_disposition is not RetryDisposition.QUARANTINE_UNKNOWN
            ):
                _fail("extraction_operation_authority_invalid")


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionCommand:
    """Commitment-only command passed to one dispatch or status lookup."""

    run_id: str
    run_identity_commitment_sha256: str
    logical_operation_id: str
    ordinal: int
    admission_commitment_sha256: str
    operation_id_sha256: str
    unit_identity_sha256: str
    unit_sha256: str
    route_sha256: str
    scope_sha256: str
    request_body_sha256: str
    command_commitment_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.run_id) is not str
            or not self.run_id
            or type(self.ordinal) is not int
            or self.ordinal < 0
            or any(
                not _sha(value)
                for value in (
                    self.run_identity_commitment_sha256,
                    self.logical_operation_id,
                    self.admission_commitment_sha256,
                    self.operation_id_sha256,
                    self.unit_identity_sha256,
                    self.unit_sha256,
                    self.route_sha256,
                    self.scope_sha256,
                    self.request_body_sha256,
                )
            )
        ):
            _fail("extraction_command_invalid")
        object.__setattr__(
            self,
            "command_commitment_sha256",
            canonical_sha256(self.payload()),
        )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": PUBLISHABLE_EXTRACTION_WORKER_SCHEMA,
            "run_id": self.run_id,
            "run_identity_commitment_sha256": self.run_identity_commitment_sha256,
            "logical_operation_id": self.logical_operation_id,
            "ordinal": self.ordinal,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "route_sha256": self.route_sha256,
            "scope_sha256": self.scope_sha256,
            "request_body_sha256": self.request_body_sha256,
        }


class PublishableExtractionOneShotPort(Protocol):
    """Outer adapter performs no implicit retry and status never dispatches."""

    def dispatch_once(self, *, command: PublishableExtractionCommand) -> object: ...

    def lookup_outcome(self, *, command: PublishableExtractionCommand) -> object: ...


class PublishableExtractionOperationReceiptIssuerPort(Protocol):
    def issue(
        self,
        *,
        identity: LogicalOperationIdentity,
        request_commitment_sha256: str,
        result_commitment_sha256: str,
    ) -> OperationReceipt: ...


@final
@dataclass(slots=True)
class OpenedPublishableExtractionStores:
    """Opened durable stores and authenticated A1 authority owned by one worker."""

    journal_service: ResumableOperationJournalService
    journal_store: OperationJournalPort
    extraction_ledger: ManagedFullRunExtractionLedgerPort
    expected_operations: ManagedFullRunExpectedOperationPagePort
    operation_receipt_issuer: PublishableExtractionOperationReceiptIssuerPort
    close_callbacks: tuple[Callable[[], None], ...]
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        required = (
            (self.journal_store, ("write_transaction",)),
            (
                self.extraction_ledger,
                ("begin", "read_checkpoint", "append_page", "finalize", "readback"),
            ),
            (self.expected_operations, ("read_operation_page",)),
            (self.operation_receipt_issuer, ("issue",)),
        )
        if (
            type(self.journal_service) is not ResumableOperationJournalService
            or any(
                not callable(getattr(value, name, None))
                for value, names in required
                for name in names
            )
            or type(self.close_callbacks) is not tuple
            or any(not callable(callback) for callback in self.close_callbacks)
        ):
            _fail("extraction_stores_invalid")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first: BaseException | None = None
        for callback in self.close_callbacks:
            try:
                callback()
            except BaseException as error:
                if first is None:
                    first = error
        if first is not None:
            raise first


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionRunTerminal:
    """Commitment-only handoff reconstructed from two independently durable seals."""

    profile_id: str
    run_id_sha256: str
    binding_commitment_sha256: str
    methodology_commitment_sha256: str
    admission_commitment_sha256: str
    ingestion_root_sha256: str
    a1_terminal_commitment_sha256: str
    a1_manifest_context_sha256: str
    runtime_binding_commitment_sha256: str
    preparation_receipt_sha256: str
    dataset_sha256: str
    a2_terminal_commitment_sha256: str
    expected_receipt_count: int
    journal_manifest_commitment_sha256: str
    journal_state_commitment_sha256: str
    journal_head_event_sha256: str
    ledger_terminal: ManagedFullRunExtractionTerminal
    terminal_commitment_sha256: str = field(init=False)
    paid_go_ready: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        digests = (
            self.run_id_sha256,
            self.binding_commitment_sha256,
            self.methodology_commitment_sha256,
            self.admission_commitment_sha256,
            self.ingestion_root_sha256,
            self.a1_terminal_commitment_sha256,
            self.a1_manifest_context_sha256,
            self.runtime_binding_commitment_sha256,
            self.preparation_receipt_sha256,
            self.dataset_sha256,
            self.a2_terminal_commitment_sha256,
            self.journal_manifest_commitment_sha256,
            self.journal_state_commitment_sha256,
            self.journal_head_event_sha256,
        )
        if (
            type(self.profile_id) is not str
            or not self.profile_id
            or any(not _sha(value) for value in digests)
            or type(self.expected_receipt_count) is not int
            or type(self.ledger_terminal) is not ManagedFullRunExtractionTerminal
            or self.ledger_terminal.receipt_count != self.expected_receipt_count
            or self.ledger_terminal.context_commitment_sha256
            != self.ledger_context_commitment_sha256
            or self.paid_go_ready is not False
        ):
            _fail("extraction_terminal_invalid")
        object.__setattr__(self, "terminal_commitment_sha256", canonical_sha256(self.body()))

    @property
    def ledger_context_commitment_sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": "managed-full-run-extraction-ledger.v1",
                "profile_id": self.profile_id,
                "run_id_sha256": self.run_id_sha256,
                "binding_commitment_sha256": self.binding_commitment_sha256,
                "methodology_commitment_sha256": self.methodology_commitment_sha256,
                "admission_commitment_sha256": self.admission_commitment_sha256,
                "ingestion_root_sha256": self.ingestion_root_sha256,
                "a1_terminal_commitment_sha256": self.a1_terminal_commitment_sha256,
                "a1_manifest_context_sha256": self.a1_manifest_context_sha256,
                "runtime_binding_commitment_sha256": self.runtime_binding_commitment_sha256,
                "expected_receipt_count": self.expected_receipt_count,
            }
        )

    def body(self) -> dict[str, object]:
        return {
            "schema_version": PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA,
            "profile_id": self.profile_id,
            "run_id_sha256": self.run_id_sha256,
            "binding_commitment_sha256": self.binding_commitment_sha256,
            "methodology_commitment_sha256": self.methodology_commitment_sha256,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "a1_terminal_commitment_sha256": self.a1_terminal_commitment_sha256,
            "a1_manifest_context_sha256": self.a1_manifest_context_sha256,
            "runtime_binding_commitment_sha256": self.runtime_binding_commitment_sha256,
            "expected_receipt_count": self.expected_receipt_count,
            "preparation_receipt_sha256": self.preparation_receipt_sha256,
            "dataset_sha256": self.dataset_sha256,
            "a2_terminal_commitment_sha256": self.a2_terminal_commitment_sha256,
            "journal_manifest_commitment_sha256": self.journal_manifest_commitment_sha256,
            "journal_state_commitment_sha256": self.journal_state_commitment_sha256,
            "journal_head_event_sha256": self.journal_head_event_sha256,
            "ledger_terminal": {
                **self.ledger_terminal.body(),
                "terminal_commitment_sha256": self.ledger_terminal.terminal_commitment_sha256,
            },
            "paid_go_ready": False,
        }


@final
@dataclass(frozen=True, slots=True)
class PublishableExtractionAdvance:
    phase: PublishableExtractionAdvancePhase
    journal_snapshot: OperationJournalSnapshot
    operation_ordinal: int | None = None
    terminal: PublishableExtractionRunTerminal | None = None

    def __post_init__(self) -> None:
        if (
            type(self.phase) is not PublishableExtractionAdvancePhase
            or type(self.journal_snapshot) is not OperationJournalSnapshot
            or (self.operation_ordinal is not None and self.operation_ordinal < 0)
            or (self.phase is PublishableExtractionAdvancePhase.SEALED)
            is not (self.terminal is not None)
        ):
            _fail("extraction_advance_invalid")


def _sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _fail(code: str) -> None:
    raise PublishableExtractionWorkerError(code) from None


__all__ = (
    "MANAGED_MEM0_EXTRACTION_NAMESPACE",
    "MANAGED_MEM0_EXTRACTION_OPERATION_KIND",
    "OpenedPublishableExtractionStores",
    "PUBLISHABLE_EXTRACTION_TERMINAL_SCHEMA",
    "PUBLISHABLE_EXTRACTION_WORKER_SCHEMA",
    "PublishableExtractionAdvance",
    "PublishableExtractionAdvancePhase",
    "PublishableExtractionCommand",
    "PublishableExtractionOneShotPort",
    "PublishableExtractionOperationReceiptIssuerPort",
    "PublishableExtractionRunAuthority",
    "PublishableExtractionRunTerminal",
    "PublishableExtractionWorkerError",
)
