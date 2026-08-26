"""Recovered strict-v4 fact authority for the production composition root."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import final

from infinity_context_adapters.postgres.managed_benchmark_strict_v4_fact_authority import (
    ExpectedIndexStrictV4FactAuthority,
)
from infinity_context_adapters.postgres.managed_cleanup_v3_expected_row_authority import (
    SQLiteManagedCleanupV3ExpectedRowAuthority,
)
from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
    StrictV4PreparationReceiptPort,
    strict_v4_preparation_key_commitment,
)
from infinity_context_core.ports.managed_benchmark_strict_v4_write import (
    ManagedBenchmarkStrictV4CorpusAdmission,
    ManagedBenchmarkStrictV4CorpusClaim,
    ManagedBenchmarkStrictV4FactAdmission,
    ManagedBenchmarkStrictV4FactClaim,
)

from infinity_context_server.memory_comparison_managed_v5_cleanup_v4_projector import (
    ManagedV5CleanupV4OperationProjector,
)
from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)


@final
class RecoveredStrictV4FactAuthority:
    """Own the authenticated SQLite snapshot used by strict fact admission."""

    def __init__(
        self,
        index: SQLiteManagedCleanupV3ExpectedRowAuthority,
        delegate: ExpectedIndexStrictV4FactAuthority,
        receipt: StrictV4PreparationReceipt,
    ) -> None:
        self._index = index
        self._delegate = delegate
        self._receipt = receipt
        self._closed = False

    @property
    def receipt(self) -> StrictV4PreparationReceipt:
        if self._closed:
            raise ProjectionReceiptError("projection_receipt.fact_authority_closed")
        return self._receipt

    def admit_fact(
        self, claim: ManagedBenchmarkStrictV4FactClaim
    ) -> ManagedBenchmarkStrictV4FactAdmission:
        if self._closed:
            raise ProjectionReceiptError("projection_receipt.fact_authority_closed")
        return self._delegate.admit_fact(claim)

    def admit_corpus(
        self, claim: ManagedBenchmarkStrictV4CorpusClaim
    ) -> ManagedBenchmarkStrictV4CorpusAdmission:
        if self._closed:
            raise ProjectionReceiptError("projection_receipt.fact_authority_closed")
        return self._delegate.admit_corpus(claim)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._index.close()

    def __enter__(self) -> RecoveredStrictV4FactAuthority:
        if self._closed:
            raise ProjectionReceiptError("projection_receipt.fact_authority_closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


async def recover_strict_v4_fact_authority(
    *,
    receipt_store: StrictV4PreparationReceiptPort,
    registration_port: ContextAuthorityRegistrationPort,
    authenticator: ProjectionReceiptAuthenticator,
    key_identity_authority: StrictV4PreparationKeyIdentityPort,
    expected_projector: ManagedV5CleanupV4OperationProjector | None = None,
) -> RecoveredStrictV4FactAuthority:
    """Reauthenticate all artifacts, then pin the exact expected-row snapshot."""

    receipt = await recover_strict_v4_full_run(
        receipt_store=receipt_store,
        registration_port=registration_port,
        authenticator=authenticator,
        key_identity_authority=key_identity_authority,
    )
    if expected_projector is not None:
        _validate_execution_projector(receipt, expected_projector)
    key = key_identity_authority.resolve(
        purpose="expected-index", key_id=receipt.expected_index_key_id
    )
    if type(key) is not bytes or len(key) < 32:
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    observed = strict_v4_preparation_key_commitment(
        key,
        purpose="expected-index",
        key_id=receipt.expected_index_key_id,
        artifact_context=f"{receipt.run_id_sha256}:{Path(receipt.expected_index_path)}",
    )
    if not hmac.compare_digest(observed, receipt.expected_index_key_commitment_sha256):
        raise ProjectionReceiptError("projection_receipt.preparation_key_binding_invalid")
    index = SQLiteManagedCleanupV3ExpectedRowAuthority.open(
        receipt.expected_index_path,
        context=receipt.a2_context,
        authority=receipt.a2_authority,
        authentication_key=key,
    )
    try:
        delegate = ExpectedIndexStrictV4FactAuthority(
            context=receipt.a2_context,
            authority_terminal_sha256=receipt.expected_index_terminal_sha256,
            lookup=index,
        )
        return RecoveredStrictV4FactAuthority(index, delegate, receipt)
    except BaseException:
        index.close()
        raise


def _validate_execution_projector(
    receipt: StrictV4PreparationReceipt,
    projector: ManagedV5CleanupV4OperationProjector,
) -> None:
    """Reject dataset/request drift before opening the write authority."""

    if type(projector) is not ManagedV5CleanupV4OperationProjector:
        raise ProjectionReceiptError("projection_receipt.fact_projection_invalid")
    bindings = projector.projection.bindings
    context = receipt.a2_context
    infinity_targets = tuple(
        item.target_identity_sha256
        for item in bindings.backend_targets
        if item.backend_role == "infinity-context"
    )
    if (
        receipt.profile_id != projector.profile_id
        or receipt.profile_id != bindings.profile_id
        or receipt.dataset_sha256 != bindings.dataset_sha256
        or receipt.run_id_sha256 != hashlib.sha256(bindings.run_id.encode()).hexdigest()
        or receipt.binding_commitment_sha256 != bindings.binding_commitment_sha256
        or receipt.methodology_commitment_sha256 != bindings.methodology_commitment_sha256
        or receipt.admission_commitment_sha256 != projector.admission_commitment_sha256
        or receipt.ingestion_root_sha256 != projector.manifest_authority.ingestion_root_sha256
        or receipt.a2_context.case_manifest_sha256 != projector.projection.case_manifest_sha256
        or receipt.a2_context.publishable_profile_commitment_sha256
        != projector.projection.publishable_profile_commitment_sha256
        or len(infinity_targets) != 1
        or context.infinity_target_identity_sha256 != infinity_targets[0]
    ):
        raise ProjectionReceiptError("projection_receipt.fact_projection_invalid")


__all__ = ("RecoveredStrictV4FactAuthority", "recover_strict_v4_fact_authority")
