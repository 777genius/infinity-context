"""Provider-neutral terminal basis and evidence factory for Mem0 OSS v5."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    CleanupVerificationContext,
    CleanupVerificationResult,
    Mem0OssFullRunError,
    Mem0OssFullRunState,
    canonical_sha256,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_evidence import (
    Mem0OssFailedReceiptEvidence,
    Mem0OssTerminalCleanupEvidence,
)


@final
@dataclass(frozen=True, slots=True)
class Mem0OssTerminalBasis:
    terminal_state: str
    cleanup_context: CleanupVerificationContext
    provider_observed_extraction_calls: int
    provider_observed_request_tokens: int
    provider_observed_response_tokens: int
    failed_receipts: tuple[Mem0OssFailedReceiptEvidence, ...]

    def __post_init__(self) -> None:
        if (
            self.terminal_state
            not in {Mem0OssFullRunState.DELETED.value, Mem0OssFullRunState.ABORTED.value}
            or type(self.cleanup_context) is not CleanupVerificationContext
            or (self.terminal_state == Mem0OssFullRunState.ABORTED.value)
            != self.cleanup_context.aborting
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.provider_observed_extraction_calls,
                    self.provider_observed_request_tokens,
                    self.provider_observed_response_tokens,
                )
            )
            or type(self.failed_receipts) is not tuple
            or any(type(item) is not Mem0OssFailedReceiptEvidence for item in self.failed_receipts)
        ):
            raise Mem0OssFullRunError("mem0_v5_terminal_basis_invalid")

    def public_payload(self) -> dict[str, object]:
        return {
            "terminal_state": self.terminal_state,
            "cleanup_context": {
                "admission_commitment_sha256": self.cleanup_context.admission_commitment_sha256,
                "seal_commitment_sha256": self.cleanup_context.seal_commitment_sha256,
                "operation_root_sha256": self.cleanup_context.operation_root_sha256,
                "operation_inventory_root_sha256": (
                    self.cleanup_context.operation_inventory_root_sha256
                ),
                "expected_operation_count": self.cleanup_context.expected_operation_count,
                "aborting": self.cleanup_context.aborting,
            },
            "provider_observed_extraction_calls": self.provider_observed_extraction_calls,
            "provider_observed_request_tokens": self.provider_observed_request_tokens,
            "provider_observed_response_tokens": self.provider_observed_response_tokens,
            "failed_receipts": [item.public_payload() for item in self.failed_receipts],
        }


def cleanup_request_payload(context: CleanupVerificationContext) -> dict[str, object]:
    if type(context) is not CleanupVerificationContext:
        raise Mem0OssFullRunError("mem0_v5_cleanup_context_invalid")
    return {
        "admission_commitment_sha256": context.admission_commitment_sha256,
        "seal_commitment_sha256": context.seal_commitment_sha256,
        "operation_root_sha256": context.operation_root_sha256,
        "operation_inventory_root_sha256": context.operation_inventory_root_sha256,
        "expected_operation_count": context.expected_operation_count,
        "aborting": context.aborting,
    }


def cleanup_request_commitment(context: CleanupVerificationContext) -> str:
    return canonical_sha256(cleanup_request_payload(context))


def build_terminal_evidence(
    *, basis: Mem0OssTerminalBasis, result: CleanupVerificationResult
) -> Mem0OssTerminalCleanupEvidence:
    if type(basis) is not Mem0OssTerminalBasis or type(result) is not CleanupVerificationResult:
        raise Mem0OssFullRunError("mem0_v5_terminal_factory_input_invalid")
    context = basis.cleanup_context
    for field in (
        "admission_commitment_sha256",
        "seal_commitment_sha256",
        "operation_root_sha256",
        "operation_inventory_root_sha256",
    ):
        if getattr(result, field) != getattr(context, field):
            raise Mem0OssFullRunError("mem0_v5_terminal_factory_binding_mismatch")
    if not is_sha256(result.residual_root_sha256):
        raise Mem0OssFullRunError("mem0_v5_terminal_factory_result_invalid")
    if context.aborting:
        if result.deleted_operation_count > context.expected_operation_count:
            raise Mem0OssFullRunError("mem0_v5_cleanup_count_mismatch")
    elif result.deleted_operation_count != context.expected_operation_count:
        raise Mem0OssFullRunError("mem0_v5_cleanup_count_mismatch")
    return Mem0OssTerminalCleanupEvidence(
        terminal_state=basis.terminal_state,
        admission_commitment_sha256=result.admission_commitment_sha256,
        seal_commitment_sha256=result.seal_commitment_sha256,
        operation_root_sha256=result.operation_root_sha256,
        operation_inventory_root_sha256=result.operation_inventory_root_sha256,
        deleted_operation_count=result.deleted_operation_count,
        residual_record_count=result.residual_record_count,
        residual_root_sha256=result.residual_root_sha256,
        provider_observed_extraction_calls=basis.provider_observed_extraction_calls,
        provider_observed_request_tokens=basis.provider_observed_request_tokens,
        provider_observed_response_tokens=basis.provider_observed_response_tokens,
        failed_receipts=basis.failed_receipts,
    )


__all__ = (
    "Mem0OssTerminalBasis",
    "build_terminal_evidence",
    "cleanup_request_commitment",
    "cleanup_request_payload",
)
