"""Strict typed bridges from managed Mem0 v5 HTTP evidence into core ports."""

from __future__ import annotations

from typing import final

from infinity_context_server.memory_comparison_managed_mem0_v5_projector import (
    ManagedMem0V5ManifestAuthority,
    ManagedMem0V5SourceUnit,
)
from infinity_context_server.memory_comparison_managed_mem0_v5_storage_witness import (
    ManagedMem0V5AuthenticatedStorageWitness,
    ManagedMem0V5StorageWitnessVerifierPort,
    require_managed_mem0_v5_storage_witness_verifier,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_contracts import (
    MEM0_OSS_EMPTY_ROOT_SHA256,
    CleanupVerificationContext,
    CleanupVerificationPort,
    CleanupVerificationResult,
    Mem0OssFullRunError,
    StorageVerificationContext,
    StorageVerificationPort,
    StorageVerificationResult,
    is_sha256,
)
from infinity_context_server.memory_comparison_mem0_oss_v5_http import (
    Mem0V5CleanupReceipt,
)


@final
class ManagedMem0V5StorageBridgeVerifier(StorageVerificationPort):
    """Bind authenticated managed observations to sealed manifest authority."""

    __slots__ = ("_authority", "_authority_commitment", "_units", "_witness_verifier")

    def __init__(
        self,
        *,
        authority: ManagedMem0V5ManifestAuthority,
        storage_witness_verifier: ManagedMem0V5StorageWitnessVerifierPort,
    ) -> None:
        if type(authority) is not ManagedMem0V5ManifestAuthority:
            _fail("mem0_v5_managed_storage_authority_invalid")
        try:
            authority.__post_init__()
        except Exception:
            _fail("mem0_v5_managed_storage_authority_invalid")
        self._authority_commitment = authority.authority_commitment_sha256
        self._authority = authority
        self._units = {unit.unit_identity_sha256: unit for unit in authority.units}
        try:
            self._witness_verifier = require_managed_mem0_v5_storage_witness_verifier(
                storage_witness_verifier
            )
        except Exception:
            _fail("mem0_v5_managed_storage_witness_authority_invalid")
        if len(self._units) != authority.operation_count:
            _fail("mem0_v5_managed_storage_authority_invalid")

    def verify(
        self,
        *,
        payload: object,
        context: StorageVerificationContext,
    ) -> StorageVerificationResult:
        if type(context) is not StorageVerificationContext:
            _fail("mem0_v5_managed_storage_context_invalid")
        try:
            witness = self._witness_verifier.authenticate_storage(payload)
        except Exception:
            _fail("mem0_v5_managed_storage_witness_invalid")
        try:
            self._authority.__post_init__()
            context.__post_init__()
            witness.__post_init__()
        except Exception:
            _fail("mem0_v5_managed_storage_observation_invalid")
        if self._authority.authority_commitment_sha256 != self._authority_commitment:
            _fail("mem0_v5_managed_storage_authority_invalid")
        unit = self._units.get(context.unit_identity_sha256)
        if unit is None:
            _fail("mem0_v5_managed_storage_binding_mismatch")
        _require_unit_binding(unit=unit, payload=witness, context=context)
        return StorageVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            operation_id_sha256=context.operation_id_sha256,
            unit_identity_sha256=context.unit_identity_sha256,
            unit_sha256=context.unit_sha256,
            route_sha256=context.route_sha256,
            scope_sha256=context.scope_sha256,
            provider_receipt_sha256=context.provider_receipt_sha256,
            stored_identity_sha256=witness.storage_commitment_sha256,
            stored_record_count=len(witness.created_record_ids),
        )


@final
class ManagedMem0V5CleanupBridgeVerifier(CleanupVerificationPort):
    """Bind the parsed HTTP cleanup receipt to the server-owned cleanup tuple."""

    __slots__ = ()

    def verify(
        self,
        *,
        payload: object,
        context: CleanupVerificationContext,
    ) -> CleanupVerificationResult:
        if type(context) is not CleanupVerificationContext:
            _fail("mem0_v5_managed_cleanup_context_invalid")
        if type(payload) is not Mem0V5CleanupReceipt:
            _fail("mem0_v5_managed_cleanup_receipt_invalid")
        try:
            context.__post_init__()
        except Exception:
            _fail("mem0_v5_managed_cleanup_context_invalid")
        if (
            payload.admission_commitment_sha256 != context.admission_commitment_sha256
            or payload.seal_commitment_sha256 != context.seal_commitment_sha256
            or payload.operation_root_sha256 != context.operation_root_sha256
            or payload.operation_inventory_root_sha256 != context.operation_inventory_root_sha256
            or type(payload.deleted_operation_count) is not int
            or payload.deleted_operation_count < 0
            or payload.deleted_operation_count > context.expected_operation_count
            or (
                not context.aborting
                and payload.deleted_operation_count != context.expected_operation_count
            )
            or type(payload.residual_record_count) is not int
            or payload.residual_record_count != 0
            or payload.residual_root_sha256 != MEM0_OSS_EMPTY_ROOT_SHA256
            or not is_sha256(payload.residual_root_sha256)
        ):
            _fail("mem0_v5_managed_cleanup_binding_mismatch")
        return CleanupVerificationResult(
            admission_commitment_sha256=context.admission_commitment_sha256,
            seal_commitment_sha256=context.seal_commitment_sha256,
            operation_root_sha256=context.operation_root_sha256,
            operation_inventory_root_sha256=context.operation_inventory_root_sha256,
            deleted_operation_count=payload.deleted_operation_count,
            residual_record_count=payload.residual_record_count,
            residual_root_sha256=payload.residual_root_sha256,
        )


def _require_unit_binding(
    *,
    unit: ManagedMem0V5SourceUnit,
    payload: ManagedMem0V5AuthenticatedStorageWitness,
    context: StorageVerificationContext,
) -> None:
    try:
        unit.__post_init__()
    except Exception:
        _fail("mem0_v5_managed_storage_authority_invalid")
    expected_sources = ((unit.source_id, unit.source_sha256),)
    if (
        payload.operation_id_sha256 != context.operation_id_sha256
        or payload.unit_identity_sha256 != context.unit_identity_sha256
        or unit.unit_sha256 != context.unit_sha256
        or unit.scope_sha256 != context.scope_sha256
        or payload.source_pairs != expected_sources
    ):
        _fail("mem0_v5_managed_storage_binding_mismatch")


def _fail(code: str) -> None:
    raise Mem0OssFullRunError(code)


__all__ = [
    "ManagedMem0V5CleanupBridgeVerifier",
    "ManagedMem0V5StorageBridgeVerifier",
]
