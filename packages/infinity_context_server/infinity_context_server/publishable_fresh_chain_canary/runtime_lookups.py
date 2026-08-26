"""Lookup constructors and bridge binding for the fresh-chain runtime."""

from __future__ import annotations

from infinity_context_runtime_bridge import BridgeCallBinding

from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    RuntimeReceiptVerificationContext,
)
from infinity_context_server.processes.publishable_full_extraction_contracts import (
    PublishableExtractionCommand,
)

from .contracts import (
    FreshChainCallFailure,
    FreshChainCallIntent,
    FreshChainCallResult,
    FreshChainLookup,
    FreshChainLookupDisposition,
    canonical_sha256,
)


def bridge_binding(intent: FreshChainCallIntent) -> BridgeCallBinding:
    return BridgeCallBinding(
        intent_id=intent.intent_sha256,
        logical_operation=f"fresh_chain_canary_{intent.stage}",
        logical_call_id=f"fresh-chain:{intent.ordinal}:{intent.intent_sha256[:32]}",
    )


def extraction_context(
    command: PublishableExtractionCommand,
    *,
    readback: bool,
) -> RuntimeReceiptVerificationContext:
    return RuntimeReceiptVerificationContext(
        admission_commitment_sha256=command.admission_commitment_sha256,
        operation_id_sha256=command.operation_id_sha256,
        unit_identity_sha256=command.unit_identity_sha256,
        unit_sha256=command.unit_sha256,
        route_sha256=command.route_sha256,
        scope_sha256=command.scope_sha256,
        readback_only=readback,
    )


def terminal_lookup(result: FreshChainCallResult) -> FreshChainLookup:
    return FreshChainLookup(
        disposition=FreshChainLookupDisposition.TERMINAL,
        intent_sha256=result.intent_sha256,
        result=result,
    )


def failed_lookup(failure: FreshChainCallFailure) -> FreshChainLookup:
    return FreshChainLookup(
        disposition=FreshChainLookupDisposition.FAILED,
        intent_sha256=failure.intent_sha256,
        failure=failure,
    )


def ambiguous_lookup(
    intent: FreshChainCallIntent,
    material: dict[str, object],
) -> FreshChainLookup:
    return FreshChainLookup(
        disposition=FreshChainLookupDisposition.AMBIGUOUS,
        intent_sha256=intent.intent_sha256,
        ambiguity_sha256=canonical_sha256(
            {
                "intent_sha256": intent.intent_sha256,
                "material": material,
                "schema_version": "fresh-chain-runtime-ambiguity.v1",
            }
        ),
    )


__all__ = (
    "ambiguous_lookup",
    "bridge_binding",
    "extraction_context",
    "failed_lookup",
    "terminal_lookup",
)
