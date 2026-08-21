"""Provider-free authority for strict-v4 canonical benchmark writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
    authenticate_strict_v4_preparation_receipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment

STRICT_V4_WRITER_AUTHORITY_SCHEMA = "memory-comparison-strict-v4-writer-authority.v1"
_COMMITMENT_DOMAIN = "strict-v4-canonical-write-authority/v1"
_MAC_DOMAIN = "strict-v4-canonical-write-authority"


@dataclass(frozen=True, slots=True)
class StrictV4WriterAuthority:
    run_id_sha256: str
    context_sha256: str
    authority_terminal_sha256: str
    preparation_receipt_sha256: str
    preparation_receipt_mac_sha256: str
    registration_sha256: str
    registration_mac_sha256: str
    a1_terminal_commitment_sha256: str
    a2_terminal_commitment_sha256: str
    expected_index_terminal_sha256: str
    provider_calls: int
    paid_go_ready: bool
    sealed_at: datetime
    writer_authority_sha256: str
    writer_authority_mac_sha256: str
    schema_version: str = STRICT_V4_WRITER_AUTHORITY_SCHEMA

    def payload(self, *, authenticated: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_id_sha256": self.run_id_sha256,
            "context_sha256": self.context_sha256,
            "authority_terminal_sha256": self.authority_terminal_sha256,
            "preparation_receipt_sha256": self.preparation_receipt_sha256,
            "preparation_receipt_mac_sha256": self.preparation_receipt_mac_sha256,
            "registration_sha256": self.registration_sha256,
            "registration_mac_sha256": self.registration_mac_sha256,
            "a1_terminal_commitment_sha256": self.a1_terminal_commitment_sha256,
            "a2_terminal_commitment_sha256": self.a2_terminal_commitment_sha256,
            "expected_index_terminal_sha256": self.expected_index_terminal_sha256,
            "provider_calls": self.provider_calls,
            "paid_go_ready": self.paid_go_ready,
            "sealed_at": self.sealed_at.isoformat(),
        }
        if authenticated:
            value.update(
                writer_authority_sha256=self.writer_authority_sha256,
                writer_authority_mac_sha256=self.writer_authority_mac_sha256,
            )
        return value


class StrictV4PreparationCoveragePort(Protocol):
    """Reopen and authenticate every artifact named by a preparation receipt."""

    async def reauthenticate_full_coverage(
        self, receipt: StrictV4PreparationReceipt
    ) -> StrictV4PreparationReceipt: ...


class StrictV4WriterAuthorityPort(Protocol):
    """Immutable exact-idempotent seal plus locked durable readback."""

    async def seal_and_readback(
        self,
        *,
        receipt: StrictV4PreparationReceipt,
        authority: StrictV4WriterAuthority,
    ) -> StrictV4WriterAuthority: ...


async def seal_strict_v4_writer_authority(
    *,
    receipt: StrictV4PreparationReceipt,
    coverage: StrictV4PreparationCoveragePort,
    authority_port: StrictV4WriterAuthorityPort,
    authenticator: ProjectionReceiptAuthenticator,
    sealed_at: datetime,
) -> StrictV4WriterAuthority:
    """Reauthenticate all preparation evidence before granting DB write authority."""

    authenticate_strict_v4_preparation_receipt(receipt, authenticator=authenticator)
    observed = await coverage.reauthenticate_full_coverage(receipt)
    authenticate_strict_v4_preparation_receipt(observed, authenticator=authenticator)
    if observed != receipt:
        raise ProjectionReceiptError("projection_receipt.preparation_coverage_divergent")
    authority = build_strict_v4_writer_authority(
        receipt=receipt,
        authenticator=authenticator,
        sealed_at=sealed_at,
    )
    durable = await authority_port.seal_and_readback(receipt=receipt, authority=authority)
    authenticate_strict_v4_writer_authority(
        durable,
        expected_receipt=receipt,
        authenticator=authenticator,
    )
    if durable != authority:
        raise ProjectionReceiptError("projection_receipt.writer_authority_divergent")
    return durable


def build_strict_v4_writer_authority(
    *,
    receipt: StrictV4PreparationReceipt,
    authenticator: ProjectionReceiptAuthenticator,
    sealed_at: datetime,
) -> StrictV4WriterAuthority:
    if (
        sealed_at.tzinfo is None
        or sealed_at < receipt.prepared_at
        or sealed_at < receipt.registered_at
        or receipt.prepared_at < receipt.registered_at
    ):
        raise ProjectionReceiptError("projection_receipt.writer_authority_time_invalid")
    base = StrictV4WriterAuthority(
        run_id_sha256=receipt.run_id_sha256,
        context_sha256=receipt.a2_context.context_sha256,
        authority_terminal_sha256=receipt.a2_authority.terminal_commitment_sha256,
        preparation_receipt_sha256=receipt.receipt_sha256,
        preparation_receipt_mac_sha256=receipt.receipt_mac_sha256,
        registration_sha256=receipt.registration_sha256,
        registration_mac_sha256=receipt.registration_mac_sha256,
        a1_terminal_commitment_sha256=receipt.a1_authority.terminal_commitment_sha256,
        a2_terminal_commitment_sha256=receipt.a2_authority.terminal_commitment_sha256,
        expected_index_terminal_sha256=receipt.expected_index_terminal_sha256,
        provider_calls=0,
        paid_go_ready=False,
        sealed_at=sealed_at,
        writer_authority_sha256="0" * 64,
        writer_authority_mac_sha256="0" * 64,
    )
    digest = commitment(_COMMITMENT_DOMAIN, base.payload(authenticated=False))
    return StrictV4WriterAuthority(
        **{
            name: getattr(base, name)
            for name in base.__dataclass_fields__
            if name not in {"writer_authority_sha256", "writer_authority_mac_sha256"}
        },
        writer_authority_sha256=digest,
        writer_authority_mac_sha256=authenticator.sign(_MAC_DOMAIN, digest),
    )


def authenticate_strict_v4_writer_authority(
    authority: StrictV4WriterAuthority,
    *,
    expected_receipt: StrictV4PreparationReceipt,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    if type(authority) is not StrictV4WriterAuthority:
        raise ProjectionReceiptError("projection_receipt.writer_authority_missing")
    expected = commitment(_COMMITMENT_DOMAIN, authority.payload(authenticated=False))
    if (
        authority.schema_version != STRICT_V4_WRITER_AUTHORITY_SCHEMA
        or authority.run_id_sha256 != expected_receipt.run_id_sha256
        or authority.context_sha256 != expected_receipt.a2_context.context_sha256
        or authority.authority_terminal_sha256
        != expected_receipt.a2_authority.terminal_commitment_sha256
        or authority.preparation_receipt_sha256 != expected_receipt.receipt_sha256
        or authority.preparation_receipt_mac_sha256 != expected_receipt.receipt_mac_sha256
        or authority.registration_sha256 != expected_receipt.registration_sha256
        or authority.registration_mac_sha256 != expected_receipt.registration_mac_sha256
        or authority.a1_terminal_commitment_sha256
        != expected_receipt.a1_authority.terminal_commitment_sha256
        or authority.a2_terminal_commitment_sha256
        != expected_receipt.a2_authority.terminal_commitment_sha256
        or authority.expected_index_terminal_sha256
        != expected_receipt.expected_index_terminal_sha256
        or type(authority.provider_calls) is not int
        or authority.provider_calls != 0
        or authority.paid_go_ready is not False
        or authority.sealed_at.tzinfo is None
        or authority.sealed_at < expected_receipt.prepared_at
        or authority.sealed_at < expected_receipt.registered_at
        or expected_receipt.prepared_at < expected_receipt.registered_at
        or authority.writer_authority_sha256 != expected
        or not authenticator.verify(_MAC_DOMAIN, expected, authority.writer_authority_mac_sha256)
    ):
        raise ProjectionReceiptError("projection_receipt.writer_authority_invalid")


__all__ = (
    "STRICT_V4_WRITER_AUTHORITY_SCHEMA",
    "StrictV4PreparationCoveragePort",
    "StrictV4WriterAuthority",
    "StrictV4WriterAuthorityPort",
    "authenticate_strict_v4_writer_authority",
    "build_strict_v4_writer_authority",
    "seal_strict_v4_writer_authority",
)
