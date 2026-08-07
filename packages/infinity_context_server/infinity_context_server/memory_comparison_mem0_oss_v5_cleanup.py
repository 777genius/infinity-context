"""Provider-neutral verification policy for Mem0-v5 cleanup receipts."""

from __future__ import annotations

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationPort,
    CleanupVerificationResult,
    Mem0OssFullRunError,
)


def verify_cleanup_result(
    *,
    port: CleanupVerificationPort,
    payload: object,
    context: CleanupVerificationContext,
) -> CleanupVerificationResult:
    try:
        result = port.verify(payload=payload, context=context)
    except Exception:
        raise Mem0OssFullRunError("mem0_v5_cleanup_verification_failed") from None
    if type(result) is not CleanupVerificationResult:
        raise Mem0OssFullRunError("mem0_v5_cleanup_result_invalid")
    for field in (
        "admission_commitment_sha256",
        "seal_commitment_sha256",
        "operation_root_sha256",
        "operation_inventory_root_sha256",
    ):
        if getattr(result, field) != getattr(context, field):
            raise Mem0OssFullRunError("mem0_v5_cleanup_binding_mismatch")
    if (
        result.residual_record_count != 0
        or result.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
    ):
        raise Mem0OssFullRunError("mem0_v5_cleanup_residue_detected")
    return result


__all__ = ("verify_cleanup_result",)
