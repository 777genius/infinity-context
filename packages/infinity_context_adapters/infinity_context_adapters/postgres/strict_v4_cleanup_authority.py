"""Derive strict-v4 cleanup authority from authenticated durable evidence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_preparation import (
    StrictV4PreparationReceipt,
    authenticate_strict_v4_preparation_receipt,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    StrictV4WriterAuthority,
    authenticate_strict_v4_writer_authority,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import canonical_bytes
from infinity_context_core.ports.managed_cleanup_v4_authority import (
    ManagedCleanupV4ReceiptAuthenticatorPort,
    StrictV4CleanupAuthorityReadback,
    StrictV4CleanupAuthorityReadPort,
    build_strict_v4_cleanup_authority_readback,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_json import strict_json_object
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_SEALER_ROLE,
    assert_strict_v4_runtime_capability,
)

CLEANUP_READBACK_CAPABILITY_ERROR = "projection_receipt.cleanup_readback_role_invalid"

_REGISTRATION_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       context_json::text AS context_json, authority_json::text AS authority_json,
       registration_sha256, registration_mac_sha256, registered_at
FROM public.memory_cleanup_v3_context_authorities
WHERE run_id_sha256=$1 OR context_sha256=$2
ORDER BY run_id_sha256, context_sha256
"""
_WRITER_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       preparation_receipt_json::text AS preparation_receipt_json,
       preparation_receipt_sha256, preparation_receipt_mac_sha256,
       writer_authority_json::text AS writer_authority_json,
       writer_authority_sha256, writer_authority_mac_sha256,
       registration_sha256, registration_mac_sha256,
       provider_calls, paid_go_ready, state, sealed_at, closed_at
FROM public.memory_comparison_strict_v4_preparations
WHERE run_id_sha256=$1 OR context_sha256=$2
ORDER BY run_id_sha256, context_sha256
"""


class AsyncPostgresStrictV4CleanupAuthorityReader(StrictV4CleanupAuthorityReadPort):
    """Read one cleanup authority only after receipt, registration, and seal agree."""

    def __init__(
        self,
        *,
        connect: Callable[[], Awaitable[Any]],
        recover_preparation: Callable[[], Awaitable[StrictV4PreparationReceipt]],
        preparation_authenticator: ProjectionReceiptAuthenticator,
        readback_authenticator: ManagedCleanupV4ReceiptAuthenticatorPort,
        authentication_key_id: str,
    ) -> None:
        if (
            not callable(connect)
            or not callable(recover_preparation)
            or type(preparation_authenticator) is not ProjectionReceiptAuthenticator
            or not _is_cleanup_receipt_authenticator(readback_authenticator)
            or type(authentication_key_id) is not str
            or not authentication_key_id
        ):
            raise ProjectionReceiptError("projection_receipt.cleanup_readback_capability_invalid")
        self._connect = connect
        self._recover_preparation = recover_preparation
        self._preparation_authenticator = preparation_authenticator
        self._readback_authenticator = readback_authenticator
        self._authentication_key_id = authentication_key_id

    async def read_registered_strict_v4(
        self, run_id_sha256: str
    ) -> StrictV4CleanupAuthorityReadback | None:
        receipt = await self._recover_preparation()
        authenticate_strict_v4_preparation_receipt(
            receipt, authenticator=self._preparation_authenticator
        )
        if receipt.run_id_sha256 != run_id_sha256:
            raise ProjectionReceiptError("projection_receipt.cleanup_readback_run_invalid")
        context_sha256 = receipt.a2_context.context_sha256
        connection = await self._connect()
        try:
            await assert_strict_v4_runtime_capability(
                connection,
                capability_role=STRICT_V4_SEALER_ROLE,
                error_code=CLEANUP_READBACK_CAPABILITY_ERROR,
            )
            transaction = connection.transaction(isolation="repeatable_read", readonly=True)
            try:
                await transaction.start()
                registrations = await connection.fetch(
                    _REGISTRATION_SQL, run_id_sha256, context_sha256
                )
                writers = await connection.fetch(_WRITER_SQL, run_id_sha256, context_sha256)
                if not registrations and not writers:
                    await transaction.commit()
                    return None
                if len(registrations) != 1 or len(writers) != 1:
                    raise ProjectionReceiptError("projection_receipt.cleanup_readback_collision")
                _assert_registration(registrations[0], receipt)
                writer = _writer_authority(writers[0])
                authenticate_strict_v4_writer_authority(
                    writer,
                    expected_receipt=receipt,
                    authenticator=self._preparation_authenticator,
                )
                _assert_writer_row(writers[0], receipt, writer)
                result = build_strict_v4_cleanup_authority_readback(
                    run_id_sha256=receipt.run_id_sha256,
                    context_sha256=context_sha256,
                    a2_terminal_sha256=receipt.a2_authority.terminal_commitment_sha256,
                    expected_index_terminal_sha256=receipt.expected_index_terminal_sha256,
                    preparation_receipt_sha256=receipt.receipt_sha256,
                    preparation_receipt_mac_sha256=receipt.receipt_mac_sha256,
                    registration_sha256=receipt.registration_sha256,
                    registration_mac_sha256=receipt.registration_mac_sha256,
                    writer_authority_sha256=writer.writer_authority_sha256,
                    writer_authority_mac_sha256=writer.writer_authority_mac_sha256,
                    authenticator=self._readback_authenticator,
                    authentication_key_id=self._authentication_key_id,
                )
                await transaction.commit()
                return result
            except BaseException:
                await transaction.rollback()
                raise
        finally:
            await connection.close()


def _assert_registration(row: Any, receipt: Any) -> None:
    context = strict_json_object(
        row["context_json"], "projection_receipt.cleanup_readback_registration_invalid"
    )
    authority = strict_json_object(
        row["authority_json"], "projection_receipt.cleanup_readback_registration_invalid"
    )
    if (
        row["run_id_sha256"] != receipt.run_id_sha256
        or row["context_sha256"] != receipt.a2_context.context_sha256
        or row["authority_terminal_sha256"] != receipt.a2_authority.terminal_commitment_sha256
        or row["registration_sha256"] != receipt.registration_sha256
        or row["registration_mac_sha256"] != receipt.registration_mac_sha256
        or row["registered_at"] != receipt.registered_at
        or canonical_bytes(context) != canonical_bytes(receipt.a2_context.payload())
        or canonical_bytes(authority) != canonical_bytes(receipt.a2_authority.payload())
    ):
        raise ProjectionReceiptError("projection_receipt.cleanup_readback_registration_invalid")


def _writer_authority(row: Any) -> StrictV4WriterAuthority:
    try:
        value = strict_json_object(
            row["writer_authority_json"],
            "projection_receipt.cleanup_readback_writer_invalid",
        )
        value["sealed_at"] = datetime.fromisoformat(value["sealed_at"])
        return StrictV4WriterAuthority(**value)
    except (TypeError, ValueError, KeyError) as exc:
        raise ProjectionReceiptError("projection_receipt.cleanup_readback_writer_invalid") from exc


def _assert_writer_row(row: Any, receipt: Any, writer: StrictV4WriterAuthority) -> None:
    preparation = strict_json_object(
        row["preparation_receipt_json"],
        "projection_receipt.cleanup_readback_writer_invalid",
    )
    if (
        row["run_id_sha256"] != receipt.run_id_sha256
        or row["context_sha256"] != receipt.a2_context.context_sha256
        or row["authority_terminal_sha256"] != receipt.a2_authority.terminal_commitment_sha256
        or row["preparation_receipt_sha256"] != receipt.receipt_sha256
        or row["preparation_receipt_mac_sha256"] != receipt.receipt_mac_sha256
        or row["registration_sha256"] != receipt.registration_sha256
        or row["registration_mac_sha256"] != receipt.registration_mac_sha256
        or row["writer_authority_sha256"] != writer.writer_authority_sha256
        or row["writer_authority_mac_sha256"] != writer.writer_authority_mac_sha256
        or row["provider_calls"] != 0
        or row["paid_go_ready"] is not False
        or row["state"] != "sealed"
        or row["sealed_at"] != writer.sealed_at
        or row["closed_at"] is not None
        or canonical_bytes(preparation) != canonical_bytes(receipt.payload())
    ):
        raise ProjectionReceiptError("projection_receipt.cleanup_readback_writer_invalid")


def _is_cleanup_receipt_authenticator(value: object) -> bool:
    capability = cast(ManagedCleanupV4ReceiptAuthenticatorPort, value)
    try:
        authority_sha256 = capability.authority_sha256
        signer = capability.sign
    except Exception:
        return False
    return (
        callable(signer)
        and type(authority_sha256) is str
        and len(authority_sha256) == 64
        and all(character in "0123456789abcdef" for character in authority_sha256)
    )


__all__ = (
    "AsyncPostgresStrictV4CleanupAuthorityReader",
    "CLEANUP_READBACK_CAPABILITY_ERROR",
)
