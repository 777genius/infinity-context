"""Canonical evidence DTOs and verification for Mem0 OSS v5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE,
    Mem0OssFullRunError,
    Mem0OssFullRunState,
    Mem0OssManifestUnit,
    Mem0OssOperationState,
    Mem0OssReceiptDisposition,
    canonical_sha256,
    is_sha256,
    manifest_root_sha256,
)


@final
@dataclass(frozen=True, slots=True)
class Mem0OssOperationEvidence:
    operation_id_sha256: str
    unit_index: int
    unit_identity_sha256: str
    unit_sha256: str
    scope_sha256: str
    state: str
    provider_receipt_sha256: str
    disposition: str
    extraction_calls: int
    retry_count: int
    request_tokens: int
    response_tokens: int
    stored_identity_sha256: str
    stored_record_count: int
    commitment_sha256: str

    def __post_init__(self) -> None:
        digests = (
            self.operation_id_sha256,
            self.unit_identity_sha256,
            self.unit_sha256,
            self.scope_sha256,
            self.provider_receipt_sha256,
            self.stored_identity_sha256,
            self.commitment_sha256,
        )
        if (
            any(not is_sha256(value) for value in digests)
            or type(self.unit_index) is not int
            or self.unit_index < 0
            or self.state != Mem0OssOperationState.COMMITTED.value
            or self.disposition != Mem0OssReceiptDisposition.COMPLETED.value
            or type(self.extraction_calls) is not int
            or self.extraction_calls != 1
            or type(self.retry_count) is not int
            or self.retry_count != 0
            or type(self.request_tokens) is not int
            or self.request_tokens < 0
            or type(self.response_tokens) is not int
            or self.response_tokens < 0
            or type(self.stored_record_count) is not int
            or self.stored_record_count < 0
        ):
            raise Mem0OssFullRunError("mem0_v5_operation_evidence_invalid")

    def commitment_payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in self.payload().items()
            if key not in {"state", "commitment_sha256"}
        }

    def payload(self) -> dict[str, object]:
        return {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_index": self.unit_index,
            "unit_identity_sha256": self.unit_identity_sha256,
            "unit_sha256": self.unit_sha256,
            "scope_sha256": self.scope_sha256,
            "state": self.state,
            "provider_receipt_sha256": self.provider_receipt_sha256,
            "disposition": self.disposition,
            "extraction_calls": self.extraction_calls,
            "retry_count": self.retry_count,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
            "stored_identity_sha256": self.stored_identity_sha256,
            "stored_record_count": self.stored_record_count,
            "commitment_sha256": self.commitment_sha256,
        }


@final
@dataclass(frozen=True, slots=True)
class Mem0OssRunSeal:
    admission_commitment_sha256: str
    operation_count: int
    ingestion_root_sha256: str
    operation_root_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.admission_commitment_sha256,
                    self.ingestion_root_sha256,
                    self.operation_root_sha256,
                )
            )
            or type(self.operation_count) is not int
            or self.operation_count < 1
            or type(self.provider_observed_extraction_calls) is not int
            or self.provider_observed_extraction_calls != self.operation_count
            or type(self.provider_observed_request_tokens) is not int
            or self.provider_observed_request_tokens < 0
            or type(self.provider_observed_response_tokens) is not int
            or self.provider_observed_response_tokens < 0
        ):
            raise Mem0OssFullRunError("mem0_v5_seal_invalid")

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "operation_count": self.operation_count,
            "ingestion_root_sha256": self.ingestion_root_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "provider_observed_extraction_calls": self.provider_observed_extraction_calls,
            "provider_observed_request_tokens": self.provider_observed_request_tokens,
            "provider_observed_response_tokens": self.provider_observed_response_tokens,
        }


@final
@dataclass(frozen=True, slots=True)
class Mem0OssFailedReceiptEvidence:
    operation_id_sha256: str
    unit_index: int
    disposition: str
    provider_receipt_sha256: str
    extraction_calls: int
    request_tokens: int
    response_tokens: int

    def __post_init__(self) -> None:
        if (
            not is_sha256(self.operation_id_sha256)
            or type(self.unit_index) is not int
            or self.unit_index < 0
            or self.disposition
            not in {
                Mem0OssReceiptDisposition.PROVIDER_FAILED.value,
                Mem0OssReceiptDisposition.REJECTED.value,
            }
            or not is_sha256(self.provider_receipt_sha256)
            or type(self.extraction_calls) is not int
            or self.extraction_calls != 1
            or type(self.request_tokens) is not int
            or self.request_tokens < 0
            or type(self.response_tokens) is not int
            or self.response_tokens < 0
        ):
            raise Mem0OssFullRunError("mem0_v5_failed_receipt_evidence_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "operation_id_sha256": self.operation_id_sha256,
            "unit_index": self.unit_index,
            "disposition": self.disposition,
            "provider_receipt_sha256": self.provider_receipt_sha256,
            "extraction_calls": self.extraction_calls,
            "request_tokens": self.request_tokens,
            "response_tokens": self.response_tokens,
        }


@final
@dataclass(frozen=True, slots=True)
class Mem0OssTerminalCleanupEvidence:
    terminal_state: str
    admission_commitment_sha256: str
    seal_commitment_sha256: str | None
    operation_root_sha256: str | None
    operation_inventory_root_sha256: str
    deleted_operation_count: int
    residual_record_count: int
    residual_root_sha256: str
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int
    failed_receipts: tuple[Mem0OssFailedReceiptEvidence, ...]

    def __post_init__(self) -> None:
        if (
            self.terminal_state
            not in {Mem0OssFullRunState.DELETED.value, Mem0OssFullRunState.ABORTED.value}
            or not is_sha256(self.admission_commitment_sha256)
            or (
                self.seal_commitment_sha256 is not None
                and not is_sha256(self.seal_commitment_sha256)
            )
            or (
                self.operation_root_sha256 is not None and not is_sha256(self.operation_root_sha256)
            )
            or not is_sha256(self.operation_inventory_root_sha256)
            or type(self.deleted_operation_count) is not int
            or self.deleted_operation_count < 0
            or type(self.residual_record_count) is not int
            or self.residual_record_count != 0
            or self.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
            or type(self.provider_observed_extraction_calls) is not int
            or self.provider_observed_extraction_calls < 0
            or type(self.provider_observed_request_tokens) is not int
            or self.provider_observed_request_tokens < 0
            or type(self.provider_observed_response_tokens) is not int
            or self.provider_observed_response_tokens < 0
            or type(self.failed_receipts) is not tuple
            or any(type(item) is not Mem0OssFailedReceiptEvidence for item in self.failed_receipts)
        ):
            raise Mem0OssFullRunError("mem0_v5_terminal_cleanup_evidence_invalid")

    @property
    def commitment_sha256(self) -> str:
        return canonical_sha256(self.public_payload())

    def public_payload(self) -> dict[str, object]:
        return {
            "terminal_state": self.terminal_state,
            "admission_commitment_sha256": self.admission_commitment_sha256,
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "operation_inventory_root_sha256": self.operation_inventory_root_sha256,
            "deleted_operation_count": self.deleted_operation_count,
            "residual_record_count": self.residual_record_count,
            "residual_root_sha256": self.residual_root_sha256,
            "provider_observed_extraction_calls": self.provider_observed_extraction_calls,
            "provider_observed_request_tokens": self.provider_observed_request_tokens,
            "provider_observed_response_tokens": self.provider_observed_response_tokens,
            "failed_receipts": [item.public_payload() for item in self.failed_receipts],
        }


@final
@dataclass(frozen=True, slots=True)
class Mem0OssEvidencePage:
    seal_commitment_sha256: str
    operation_root_sha256: str
    page_index: int
    total_pages: int
    start_unit_index: int
    end_unit_index_exclusive: int
    previous_page_commitment_sha256: str
    items: tuple[Mem0OssOperationEvidence, ...]
    page_commitment_sha256: str

    def __post_init__(self) -> None:
        if (
            any(
                not is_sha256(value)
                for value in (
                    self.seal_commitment_sha256,
                    self.operation_root_sha256,
                    self.previous_page_commitment_sha256,
                    self.page_commitment_sha256,
                )
            )
            or type(self.page_index) is not int
            or self.page_index < 0
            or type(self.total_pages) is not int
            or self.total_pages < 1
            or type(self.start_unit_index) is not int
            or self.start_unit_index < 0
            or type(self.end_unit_index_exclusive) is not int
            or self.end_unit_index_exclusive <= self.start_unit_index
            or type(self.items) is not tuple
            or not 1 <= len(self.items) <= MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE
            or any(type(item) is not Mem0OssOperationEvidence for item in self.items)
        ):
            raise Mem0OssFullRunError("mem0_v5_evidence_page_invalid")

    def payload_without_commitment(self) -> dict[str, object]:
        return {
            "seal_commitment_sha256": self.seal_commitment_sha256,
            "operation_root_sha256": self.operation_root_sha256,
            "page_index": self.page_index,
            "total_pages": self.total_pages,
            "start_unit_index": self.start_unit_index,
            "end_unit_index_exclusive": self.end_unit_index_exclusive,
            "previous_page_commitment_sha256": self.previous_page_commitment_sha256,
            "items": [item.payload() for item in self.items],
        }

    def public_payload(self) -> dict[str, object]:
        return {
            **self.payload_without_commitment(),
            "page_commitment_sha256": self.page_commitment_sha256,
        }


def verify_mem0_oss_sealed_evidence_pages(
    pages: tuple[Mem0OssEvidencePage, ...], *, seal: Mem0OssRunSeal
) -> None:
    """Verify page commitments, chain order and exact whole-run coverage."""

    if type(pages) is not tuple or not pages or type(seal) is not Mem0OssRunSeal:
        raise Mem0OssFullRunError("mem0_v5_evidence_sequence_invalid")
    items: list[Mem0OssOperationEvidence] = []
    previous = MEM0_OSS_EMPTY_ROOT_SHA256
    for page_index, page in enumerate(pages):
        if type(page) is not Mem0OssEvidencePage:
            raise Mem0OssFullRunError("mem0_v5_evidence_page_invalid")
        if (
            page.page_index != page_index
            or page.total_pages != len(pages)
            or page.previous_page_commitment_sha256 != previous
            or page.seal_commitment_sha256 != seal.commitment_sha256
            or page.operation_root_sha256 != seal.operation_root_sha256
            or not 1 <= len(page.items) <= MEM0_OSS_FULL_RUN_MAX_EVIDENCE_PAGE
            or page.start_unit_index != len(items)
            or page.end_unit_index_exclusive != len(items) + len(page.items)
            or canonical_sha256(page.payload_without_commitment()) != page.page_commitment_sha256
        ):
            raise Mem0OssFullRunError("mem0_v5_evidence_page_chain_invalid")
        items.extend(page.items)
        previous = page.page_commitment_sha256
    if (
        len(items) != seal.operation_count
        or [item.unit_index for item in items] != list(range(seal.operation_count))
        or len({item.unit_identity_sha256 for item in items}) != len(items)
        or manifest_root_sha256(
            tuple(
                Mem0OssManifestUnit(
                    unit_identity_sha256=item.unit_identity_sha256,
                    unit_sha256=item.unit_sha256,
                    scope_sha256=item.scope_sha256,
                )
                for item in items
            )
        )
        != seal.ingestion_root_sha256
        or sum(item.extraction_calls for item in items) != seal.provider_observed_extraction_calls
        or sum(item.request_tokens for item in items) != seal.provider_observed_request_tokens
        or sum(item.response_tokens for item in items) != seal.provider_observed_response_tokens
        or any(
            item.state != Mem0OssOperationState.COMMITTED.value
            or canonical_sha256(item.commitment_payload()) != item.commitment_sha256
            for item in items
        )
        or operation_root(tuple(items)) != seal.operation_root_sha256
    ):
        raise Mem0OssFullRunError("mem0_v5_evidence_coverage_invalid")


def operation_root(items: tuple[Mem0OssOperationEvidence, ...]) -> str:
    return canonical_sha256({"operation_commitments": [item.commitment_sha256 for item in items]})


__all__ = [
    "Mem0OssEvidencePage",
    "Mem0OssFailedReceiptEvidence",
    "Mem0OssOperationEvidence",
    "Mem0OssRunSeal",
    "Mem0OssTerminalCleanupEvidence",
    "operation_root",
    "verify_mem0_oss_sealed_evidence_pages",
]
