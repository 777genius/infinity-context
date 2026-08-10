"""Canonical projection-result receipt feature."""

from infinity_context_core.features.projection_receipts.application import (
    AuthenticatedProjectionIdentity,
    ProjectionReceiptAuthenticator,
    ProjectionResultReceipt,
    build_projection_result_receipt,
    ensure_projection_and_readback,
    ensure_projection_deleted_and_readback,
    verify_projection_result_receipt,
)
from infinity_context_core.features.projection_receipts.context_authority_registration import (
    ContextAuthorityRegistration,
    ContextAuthorityRegistrationPort,
    authenticate_context_authority_registration,
    context_authority_registration_sha256,
    register_context_authority_and_readback,
)
from infinity_context_core.features.projection_receipts.contracts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReadbackPort,
    ProjectionReceiptError,
    ProjectionTargetIdentity,
    projection_outbox_event_commitment,
)

__all__ = (
    "AuthenticatedProjectionIdentity",
    "ContextAuthorityRegistration",
    "ContextAuthorityRegistrationPort",
    "ProjectionJobBinding",
    "ProjectionMaterialization",
    "ProjectionReadbackPort",
    "ProjectionReceiptAuthenticator",
    "ProjectionReceiptError",
    "ProjectionResultReceipt",
    "ProjectionTargetIdentity",
    "authenticate_context_authority_registration",
    "context_authority_registration_sha256",
    "projection_outbox_event_commitment",
    "register_context_authority_and_readback",
    "build_projection_result_receipt",
    "ensure_projection_and_readback",
    "ensure_projection_deleted_and_readback",
    "verify_projection_result_receipt",
)
