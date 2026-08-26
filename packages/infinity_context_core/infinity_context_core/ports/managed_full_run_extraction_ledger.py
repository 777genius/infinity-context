"""Paged authenticated evidence contracts for one full extraction run."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol, final

FULL_RUN_EXTRACTION_LEDGER_SCHEMA = "managed-full-run-extraction-ledger.v1"
FULL_RUN_EXTRACTION_PAGE_SIZE = 512
FULL_RUN_EXTRACTION_MAX_RECEIPTS = 124_344

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ManagedFullRunExtractionLedgerError(RuntimeError):
    """Stable fail-closed error with no provider or benchmark material."""


def require_sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedFullRunExtractionLedgerError(f"{name}_invalid")
    return value


def canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ManagedFullRunExtractionLedgerError("canonical_payload_invalid") from None


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class ManagedFullRunExtractionContext:
    profile_id: str
    run_id_sha256: str
    binding_commitment_sha256: str
    methodology_commitment_sha256: str
    admission_commitment_sha256: str
    ingestion_root_sha256: str
    a1_terminal_commitment_sha256: str
    a1_manifest_context_sha256: str
    runtime_binding_commitment_sha256: str
    expected_receipt_count: int

    def __post_init__(self) -> None:
        if (
            type(self.profile_id) is not str
            or not self.profile_id
            or self.profile_id != self.profile_id.strip()
            or type(self.expected_receipt_count) is not int
            or not 1 <= self.expected_receipt_count <= FULL_RUN_EXTRACTION_MAX_RECEIPTS
        ):
            raise ManagedFullRunExtractionLedgerError("context_invalid")
        for name in (
            "run_id_sha256",
            "binding_commitment_sha256",
            "methodology_commitment_sha256",
            "admission_commitment_sha256",
            "ingestion_root_sha256",
            "a1_terminal_commitment_sha256",
            "a1_manifest_context_sha256",
            "runtime_binding_commitment_sha256",
        ):
            require_sha256(getattr(self, name), name)

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
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


@final
@dataclass(frozen=True, slots=True)
class ManagedFullRunExtractionReceipt:
    sequence: int
    operation_id_sha256: str
    unit_identity_sha256: str
    request_body_sha256: str
    output_text_sha256: str
    provider_receipt_sha256: str
    runtime_binding_commitment_sha256: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if (
            type(self.sequence) is not int
            or not 0 <= self.sequence < FULL_RUN_EXTRACTION_MAX_RECEIPTS
        ):
            raise ManagedFullRunExtractionLedgerError("receipt_sequence_invalid")
        for name in (
            "operation_id_sha256",
            "unit_identity_sha256",
            "request_body_sha256",
            "output_text_sha256",
            "provider_receipt_sha256",
            "runtime_binding_commitment_sha256",
        ):
            require_sha256(getattr(self, name), name)
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 100_000_000:
                raise ManagedFullRunExtractionLedgerError("receipt_usage_invalid")
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ManagedFullRunExtractionLedgerError("receipt_usage_invalid")

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "operation_id_sha256": self.operation_id_sha256,
            "unit_identity_sha256": self.unit_identity_sha256,
            "request_body_sha256": self.request_body_sha256,
            "output_text_sha256": self.output_text_sha256,
            "provider_receipt_sha256": self.provider_receipt_sha256,
            "runtime_binding_commitment_sha256": self.runtime_binding_commitment_sha256,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedFullRunExtractionTerminal:
    context_commitment_sha256: str
    receipt_count: int
    page_count: int
    receipt_pages_root_sha256: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    terminal_commitment_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "context_commitment_sha256",
            "receipt_pages_root_sha256",
            "terminal_commitment_sha256",
        ):
            require_sha256(getattr(self, name), name)
        expected_pages = (
            self.receipt_count + FULL_RUN_EXTRACTION_PAGE_SIZE - 1
        ) // FULL_RUN_EXTRACTION_PAGE_SIZE
        if (
            type(self.receipt_count) is not int
            or not 1 <= self.receipt_count <= FULL_RUN_EXTRACTION_MAX_RECEIPTS
            or type(self.page_count) is not int
            or self.page_count != expected_pages
        ):
            raise ManagedFullRunExtractionLedgerError("terminal_count_invalid")
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ManagedFullRunExtractionLedgerError("terminal_usage_invalid")
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ManagedFullRunExtractionLedgerError("terminal_usage_invalid")
        if self.terminal_commitment_sha256 != canonical_sha256(self.body()):
            raise ManagedFullRunExtractionLedgerError("terminal_commitment_invalid")

    def body(self) -> dict[str, object]:
        return {
            "schema_version": FULL_RUN_EXTRACTION_LEDGER_SCHEMA,
            "context_commitment_sha256": self.context_commitment_sha256,
            "receipt_count": self.receipt_count,
            "page_count": self.page_count,
            "receipt_pages_root_sha256": self.receipt_pages_root_sha256,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }


@final
@dataclass(frozen=True, slots=True)
class ManagedFullRunExtractionCheckpoint:
    """Authenticated run progress returned without rescanning receipt evidence."""

    context_commitment_sha256: str
    receipt_count: int
    expected_receipt_count: int
    state: str
    terminal: ManagedFullRunExtractionTerminal | None = None

    def __post_init__(self) -> None:
        require_sha256(self.context_commitment_sha256, "context_commitment_sha256")
        if (
            type(self.receipt_count) is not int
            or type(self.expected_receipt_count) is not int
            or not 0 <= self.receipt_count <= self.expected_receipt_count
            or not 1 <= self.expected_receipt_count <= FULL_RUN_EXTRACTION_MAX_RECEIPTS
            or type(self.state) is not str
            or self.state not in ("active", "committed")
        ):
            raise ManagedFullRunExtractionLedgerError("checkpoint_invalid")
        if self.state == "active":
            if self.terminal is not None:
                raise ManagedFullRunExtractionLedgerError("checkpoint_invalid")
            return
        terminal = self.terminal
        if (
            type(terminal) is not ManagedFullRunExtractionTerminal
            or self.receipt_count != self.expected_receipt_count
            or terminal.context_commitment_sha256 != self.context_commitment_sha256
            or terminal.receipt_count != self.receipt_count
        ):
            raise ManagedFullRunExtractionLedgerError("checkpoint_invalid")

    @property
    def next_sequence(self) -> int:
        return self.receipt_count


class ManagedFullRunExpectedOperationPagePort(Protocol):
    def read_operation_page(
        self,
        *,
        manifest_context_sha256: str,
        start_sequence: int,
    ) -> tuple[str, ...]: ...


class ManagedFullRunExtractionLedgerPort(Protocol):
    def begin(self, context: ManagedFullRunExtractionContext) -> None: ...

    def read_checkpoint(self) -> ManagedFullRunExtractionCheckpoint: ...

    def append_page(self, receipts: tuple[ManagedFullRunExtractionReceipt, ...]) -> None: ...

    def finalize(self) -> ManagedFullRunExtractionTerminal: ...

    def readback(self) -> ManagedFullRunExtractionTerminal | None: ...

    def close(self) -> None: ...


__all__ = (
    "FULL_RUN_EXTRACTION_LEDGER_SCHEMA",
    "FULL_RUN_EXTRACTION_MAX_RECEIPTS",
    "FULL_RUN_EXTRACTION_PAGE_SIZE",
    "ManagedFullRunExtractionCheckpoint",
    "ManagedFullRunExtractionContext",
    "ManagedFullRunExtractionLedgerError",
    "ManagedFullRunExpectedOperationPagePort",
    "ManagedFullRunExtractionLedgerPort",
    "ManagedFullRunExtractionReceipt",
    "ManagedFullRunExtractionTerminal",
    "canonical_bytes",
    "canonical_sha256",
    "require_sha256",
)
