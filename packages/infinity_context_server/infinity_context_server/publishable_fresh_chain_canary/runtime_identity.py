"""Small provider-neutral identity helpers for the fresh-chain runtime."""

from __future__ import annotations

from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)

from .contracts import (
    FreshChainCallFailure,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainCanaryError,
)


def same_result(left: FreshChainCallResult, right: FreshChainCallResult) -> bool:
    """Compare durable result identity, excluding the local dispatch bit."""

    return _result_identity(left) == _result_identity(right)


def same_failure(left: FreshChainCallFailure, right: FreshChainCallFailure) -> bool:
    """Compare durable failure identity, excluding the local dispatch bit."""

    return _failure_identity(left) == _failure_identity(right)


def require_result(intent: FreshChainCallIntent, result: object) -> None:
    if (
        type(result) is not FreshChainCallResult
        or result.stage != intent.stage
        or result.ordinal != intent.ordinal
        or result.intent_sha256 != intent.intent_sha256
    ):
        _fail("fresh_chain_result_crosswire")


def require_failure(intent: FreshChainCallIntent, failure: object) -> None:
    if (
        type(failure) is not FreshChainCallFailure
        or failure.stage != intent.stage
        or failure.ordinal != intent.ordinal
        or failure.intent_sha256 != intent.intent_sha256
    ):
        _fail("fresh_chain_failure_crosswire")


def require_projection_bound_command(
    command: PublishableExtractionCommand,
    *,
    namespace_id: str,
    namespace_commitment_sha256: str,
    source_projection_commitment_sha256: str,
) -> None:
    """Authenticate the provider-composed extraction command's source projection."""

    from .contracts import canonical_sha256

    expected_run_identity = canonical_sha256(
        {
            "admission_commitment_sha256": command.admission_commitment_sha256,
            "namespace_commitment_sha256": namespace_commitment_sha256,
            "namespace_id": namespace_id,
            "source_projection_commitment_sha256": source_projection_commitment_sha256,
        }
    )
    expected_operation = canonical_sha256(
        {
            "namespace_commitment_sha256": namespace_commitment_sha256,
            "source_projection_commitment_sha256": source_projection_commitment_sha256,
            "stage": "mem0_extraction",
        }
    )
    if (
        command.run_id != namespace_id
        or command.run_identity_commitment_sha256 != expected_run_identity
        or command.logical_operation_id != expected_operation
    ):
        _fail("fresh_chain_extraction_source_projection_crosswire")


def _result_identity(value: FreshChainCallResult) -> tuple[object, ...]:
    return (
        value.stage,
        value.ordinal,
        value.intent_sha256,
        value.result_sha256,
        value.physical_receipt_sha256,
        value.receipt_id,
        value.usage,
        value.output_text,
        value.commitments,
    )


def _failure_identity(value: FreshChainCallFailure) -> tuple[object, ...]:
    return (
        value.stage,
        value.ordinal,
        value.intent_sha256,
        value.failure_sha256,
        value.physical_receipt_sha256,
        value.receipt_id,
        value.usage,
        value.provider_disposition,
        value.commitments,
    )


def _fail(code: str) -> None:
    raise FreshChainCanaryError(code) from None


__all__ = (
    "require_failure",
    "require_projection_bound_command",
    "require_result",
    "same_failure",
    "same_result",
)
