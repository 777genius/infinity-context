"""Authentication of registered cleanup authority rows from raw PostgreSQL."""

from __future__ import annotations

from typing import Any

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    context_authority_registration_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    digest,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_json import strict_json_object

CONTEXT_AUTHORITY_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       context_json, authority_json, registration_sha256, registration_mac_sha256
FROM memory_cleanup_v3_context_authorities
WHERE run_id_sha256=$1 AND context_sha256=$2
FOR SHARE
"""


async def authenticate_registered_authority(
    connection: Any,
    context: ManagedCleanupV3Context,
    authority_terminal_sha256: str,
    authenticator: ProjectionReceiptAuthenticator,
) -> None:
    terminal = digest(authority_terminal_sha256)
    row = await connection.fetchrow(
        CONTEXT_AUTHORITY_SQL, context.run_id_sha256, context.context_sha256
    )
    if row is None:
        raise ManagedCleanupV3Error("managed_cleanup_v3_context_authority_missing")
    try:
        registered_context = ManagedCleanupV3Context(
            **strict_json_object(
                row["context_json"], "managed_cleanup_v3_context_authority_invalid"
            )
        )
        authority_values = strict_json_object(
            row["authority_json"], "managed_cleanup_v3_context_authority_invalid"
        )
        authority_values["ordered_page_sha256"] = tuple(authority_values["ordered_page_sha256"])
        authority = ManagedCleanupV3Authority(**authority_values)
        registered_context.__post_init__()
        authority.__post_init__()
    except (ManagedCleanupV3Error, TypeError, KeyError) as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_context_authority_invalid") from exc
    try:
        registration = context_authority_registration_sha256(registered_context, authority)
    except ProjectionReceiptError as exc:
        raise ManagedCleanupV3Error("managed_cleanup_v3_context_authority_invalid") from exc
    if (
        row["run_id_sha256"] != context.run_id_sha256
        or row["context_sha256"] != context.context_sha256
        or row["authority_terminal_sha256"] != terminal
        or authority.terminal_commitment_sha256 != terminal
        or registered_context.payload() != context.payload()
        or authority.profile_id != context.profile_id
        or authority.context_sha256 != context.context_sha256
        or authority.a1_terminal_commitment_sha256 != context.a1_terminal_commitment_sha256
        or authority.cleanup_operation_stream_root_sha256
        != context.cleanup_operation_stream_root_sha256
        or authority.omitted_source_identity_root_sha256
        != context.omitted_source_identity_root_sha256
        or row["registration_sha256"] != registration
        or not authenticator.verify(
            "projection-context-authority",
            registration,
            str(row["registration_mac_sha256"]),
        )
    ):
        raise ManagedCleanupV3Error("managed_cleanup_v3_context_authority_invalid")


__all__ = ("CONTEXT_AUTHORITY_SQL", "authenticate_registered_authority")
