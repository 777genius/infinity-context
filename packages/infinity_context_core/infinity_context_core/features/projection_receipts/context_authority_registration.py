"""Provider-free use case for exact cleanup-v4 authority registration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.projection_receipts.application import (
    ProjectionReceiptAuthenticator,
)
from infinity_context_core.features.projection_receipts.contracts import ProjectionReceiptError
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    commitment,
)


@dataclass(frozen=True, slots=True)
class ContextAuthorityRegistration:
    """One fully authenticated canonical context-authority row."""

    context: ManagedCleanupV3Context
    authority: ManagedCleanupV3Authority
    registration_sha256: str
    registration_mac_sha256: str
    registered_at: datetime
    created: bool


class ContextAuthorityRegistrationPort(Protocol):
    """Narrow mutation port: exact idempotent registration plus locked readback."""

    async def register_and_readback(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        registration_sha256: str,
        registration_mac_sha256: str,
        registered_at: datetime,
    ) -> ContextAuthorityRegistration: ...


async def register_context_authority_and_readback(
    port: ContextAuthorityRegistrationPort,
    *,
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
    authenticator: ProjectionReceiptAuthenticator,
    registered_at: datetime,
) -> ContextAuthorityRegistration:
    """Register and authenticate the exact durable row before provider construction."""

    _validate_pair(context, authority)
    if registered_at.tzinfo is None:
        raise ProjectionReceiptError("projection_receipt.context_registered_time_invalid")
    registration_sha256 = context_authority_registration_sha256(context, authority)
    registration_mac_sha256 = authenticator.sign(
        "projection-context-authority", registration_sha256
    )
    result = await port.register_and_readback(
        context=context,
        authority=authority,
        registration_sha256=registration_sha256,
        registration_mac_sha256=registration_mac_sha256,
        registered_at=registered_at,
    )
    authenticate_context_authority_registration(
        result,
        expected_context=context,
        expected_authority=authority,
        authenticator=authenticator,
    )
    return result


def context_authority_registration_sha256(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
) -> str:
    """Bind the run, context, terminal and both complete canonical payloads."""

    _validate_pair(context, authority)
    return commitment(
        "projection-receipt-context-registration/v1",
        {
            "run_id_sha256": context.run_id_sha256,
            "context_sha256": context.context_sha256,
            "authority_terminal_sha256": authority.terminal_commitment_sha256,
            "context": context.payload(),
            "authority": authority.payload(),
        },
    )


def authenticate_context_authority_registration(
    registration: ContextAuthorityRegistration,
    *,
    expected_context: ManagedCleanupV3Context,
    expected_authority: ManagedCleanupV3Authority,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    """Reject missing, divergent or tampered readback material."""

    if type(registration) is not ContextAuthorityRegistration:
        raise ProjectionReceiptError("projection_receipt.context_authority_missing")
    try:
        _validate_pair(registration.context, registration.authority)
        expected_sha256 = context_authority_registration_sha256(
            registration.context, registration.authority
        )
    except (ManagedCleanupV3Error, ProjectionReceiptError, TypeError) as exc:
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid") from exc
    if (
        registration.context != expected_context
        or registration.authority != expected_authority
        or registration.registration_sha256 != expected_sha256
        or not authenticator.verify(
            "projection-context-authority",
            expected_sha256,
            registration.registration_mac_sha256,
        )
        or registration.registered_at.tzinfo is None
        or type(registration.created) is not bool
    ):
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid")


def _validate_pair(
    context: ManagedCleanupV3Context,
    authority: ManagedCleanupV3Authority,
) -> None:
    try:
        if (
            type(context) is not ManagedCleanupV3Context
            or type(authority) is not ManagedCleanupV3Authority
        ):
            raise TypeError("cleanup authority types must be exact")
        context.__post_init__()
        authority.__post_init__()
    except (ManagedCleanupV3Error, TypeError) as exc:
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid") from exc
    if (
        authority.profile_id != context.profile_id
        or authority.context_sha256 != context.context_sha256
        or authority.a1_terminal_commitment_sha256 != context.a1_terminal_commitment_sha256
        or authority.cleanup_operation_stream_root_sha256
        != context.cleanup_operation_stream_root_sha256
        or authority.omitted_source_identity_root_sha256
        != context.omitted_source_identity_root_sha256
    ):
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid")


__all__ = (
    "ContextAuthorityRegistration",
    "ContextAuthorityRegistrationPort",
    "authenticate_context_authority_registration",
    "context_authority_registration_sha256",
    "register_context_authority_and_readback",
)
