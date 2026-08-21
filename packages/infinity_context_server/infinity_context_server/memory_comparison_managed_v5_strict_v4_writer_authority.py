"""Provider-free production seam from verified preparation to DB write authority."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.features.projection_receipts import (
    ContextAuthorityRegistrationPort,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationKeyIdentityPort,
    StrictV4PreparationReceipt,
    StrictV4PreparationReceiptPort,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    StrictV4WriterAuthority,
    StrictV4WriterAuthorityPort,
    seal_strict_v4_writer_authority,
)

from infinity_context_server.memory_comparison_managed_v5_strict_v4_preparation import (
    recover_strict_v4_full_run,
)


class _VerifiedPreparationCoverage:
    """Capability minted only from the full artifact recovery use case."""

    def __init__(self, receipt: StrictV4PreparationReceipt) -> None:
        self._receipt = receipt

    async def reauthenticate_full_coverage(
        self, receipt: StrictV4PreparationReceipt
    ) -> StrictV4PreparationReceipt:
        if receipt != self._receipt:
            raise ProjectionReceiptError("projection_receipt.preparation_coverage_divergent")
        return self._receipt


async def recover_and_seal_strict_v4_writer_authority(
    *,
    receipt_store: StrictV4PreparationReceiptPort,
    registration_port: ContextAuthorityRegistrationPort,
    writer_authority_port: StrictV4WriterAuthorityPort,
    authenticator: ProjectionReceiptAuthenticator,
    key_identity_authority: StrictV4PreparationKeyIdentityPort,
    sealed_at: datetime,
) -> StrictV4WriterAuthority:
    """Verify receipt, every local artifact, registration, then seal DB authority."""

    receipt = await recover_strict_v4_full_run(
        receipt_store=receipt_store,
        registration_port=registration_port,
        authenticator=authenticator,
        key_identity_authority=key_identity_authority,
    )
    return await seal_strict_v4_writer_authority(
        receipt=receipt,
        coverage=_VerifiedPreparationCoverage(receipt),
        authority_port=writer_authority_port,
        authenticator=authenticator,
        sealed_at=sealed_at,
    )


__all__ = ("recover_and_seal_strict_v4_writer_authority",)
