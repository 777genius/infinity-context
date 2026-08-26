"""Raw-Postgres adapter for strict cleanup-v4 context registration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Protocol

from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.context_authority_registration import (
    ContextAuthorityRegistration,
    ContextAuthorityRegistrationPort,
    authenticate_context_authority_registration,
    context_authority_registration_sha256,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
    ManagedCleanupV3Error,
    canonical_bytes,
)

from infinity_context_adapters.postgres.managed_cleanup_v3_json import strict_json_object
from infinity_context_adapters.postgres.strict_v4_authority_lock_topology import (
    assert_strict_v4_authority_lock_topology,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_REGISTRAR_ROLE,
    assert_strict_v4_runtime_capability,
)
from infinity_context_adapters.postgres.strict_v4_writer_fence_topology import (
    assert_strict_v4_writer_fence_topology,
)

LOCK_TARGETS_SQL = """
SELECT public.memory_comparison_lock_strict_v4_registration_targets($1, $2)
"""
READ_RUN_SQL = """
SELECT run_id_sha256, binding_commitment_sha256, infinity_target_identity_sha256,
       space_id, space_slug, state, cleanup_plan_json, cleanup_plan_sha256,
       cleanup_plan_state, projection_cleanup_state,
       projection_manifest_json, projection_manifest_sha256,
       cleanup_fingerprint_sha256, cleanup_receipt_json,
       finalization_fingerprint_sha256, completion_receipt_json, completed_at
FROM public.memory_comparison_benchmark_runs
WHERE run_id_sha256=$1
"""
READ_REGISTRATION_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       context_json::pg_catalog.text AS context_json,
       authority_json::pg_catalog.text AS authority_json,
       registration_sha256, registration_mac_sha256, registered_at
FROM public.memory_cleanup_v3_context_authorities
WHERE run_id_sha256=$1 OR context_sha256=$2
ORDER BY run_id_sha256, context_sha256
"""
INSERT_REGISTRATION_SQL = """
INSERT INTO public.memory_cleanup_v3_context_authorities (
  run_id_sha256, context_sha256, authority_terminal_sha256,
  context_json, authority_json, registration_sha256,
  registration_mac_sha256, registered_at
) VALUES ($1,$2,$3,$4::pg_catalog.jsonb,$5::pg_catalog.jsonb,$6,$7,$8)
"""
CANONICAL_ABSENCE_SQL = """
SELECT NOT EXISTS (
  SELECT 1 FROM public.memory_scopes WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_threads WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_facts WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_documents WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_chunks WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_fact_operation_receipts WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_idempotency_records WHERE space_id=$1
  UNION ALL SELECT 1 FROM public.memory_projection_result_receipts WHERE run_id_sha256=$2
) AS canonical_absent
"""


class ContextRegistrationPhasePolicy(Protocol):
    """Schema-aware precondition checked while the exact run row is locked."""

    async def assert_registration_binding(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        locked_run: Any,
    ) -> None: ...

    async def assert_first_registration_allowed(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        locked_run: Any,
    ) -> None: ...


class StrictV4PreExecutionRegistrationPolicy:
    """Require pristine canonical state and the complete DB writer fence."""

    async def assert_registration_binding(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        locked_run: Any,
    ) -> None:
        if not _exact_registry_identity(locked_run, context):
            raise ProjectionReceiptError("projection_receipt.context_registry_divergent")

    async def assert_first_registration_allowed(
        self,
        connection: Any,
        *,
        context: ManagedCleanupV3Context,
        locked_run: Any,
    ) -> None:
        if not _exact_pre_execution_run(locked_run, context):
            raise ProjectionReceiptError("projection_receipt.context_pre_execution_invalid")
        canonical_absent = await connection.fetchval(
            CANONICAL_ABSENCE_SQL,
            context.space_id,
            context.run_id_sha256,
        )
        if canonical_absent is not True:
            raise ProjectionReceiptError("projection_receipt.context_not_pristine")


class AsyncPostgresCleanupV4ContextAuthorityRegistry(ContextAuthorityRegistrationPort):
    """Perform the sole allowed mutation, then decode the locked row strictly."""

    def __init__(
        self,
        *,
        connect: Callable[[], Awaitable[Any]],
        authenticator: ProjectionReceiptAuthenticator,
        phase_policy: ContextRegistrationPhasePolicy | None = None,
    ) -> None:
        if type(authenticator) is not ProjectionReceiptAuthenticator:
            raise ProjectionReceiptError("projection_receipt.hmac_capability_invalid")
        self._connect = connect
        self._authenticator = authenticator
        self._strict_phase_policy = StrictV4PreExecutionRegistrationPolicy()
        self._additional_phase_policy = phase_policy

    async def register_and_readback(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
        registration_sha256: str,
        registration_mac_sha256: str,
        registered_at: datetime,
    ) -> ContextAuthorityRegistration:
        expected_registration = context_authority_registration_sha256(context, authority)
        if registration_sha256 != expected_registration or not self._authenticator.verify(
            "projection-context-authority",
            registration_sha256,
            registration_mac_sha256,
        ):
            raise ProjectionReceiptError("projection_receipt.context_authority_invalid")
        connection = await self._connect()
        transaction = connection.transaction(isolation="serializable")
        try:
            await transaction.start()
            await assert_strict_v4_runtime_capability(
                connection,
                capability_role=STRICT_V4_REGISTRAR_ROLE,
                error_code="projection_receipt.context_authority_role_invalid",
            )
            await assert_strict_v4_authority_lock_topology(
                connection,
                capability_role=STRICT_V4_REGISTRAR_ROLE,
            )
            await assert_strict_v4_writer_fence_topology(connection)
            await connection.execute(
                LOCK_TARGETS_SQL,
                context.run_id_sha256,
                context.context_sha256,
            )
            locked_run = await connection.fetchrow(READ_RUN_SQL, context.run_id_sha256)
            if locked_run is None:
                raise ProjectionReceiptError("projection_receipt.run_missing")
            await self._strict_phase_policy.assert_registration_binding(
                connection,
                context=context,
                locked_run=locked_run,
            )
            if self._additional_phase_policy is not None:
                await self._additional_phase_policy.assert_registration_binding(
                    connection,
                    context=context,
                    locked_run=locked_run,
                )
            rows = await connection.fetch(
                READ_REGISTRATION_SQL,
                context.run_id_sha256,
                context.context_sha256,
            )
            if rows:
                if len(rows) != 1:
                    raise ProjectionReceiptError("projection_receipt.context_authority_collision")
                result = _registration_from_row(rows[0], created=False)
                if (
                    result.context != context
                    or result.authority != authority
                    or result.registration_sha256 != registration_sha256
                    or result.registration_mac_sha256 != registration_mac_sha256
                    or result.registered_at != registered_at
                ):
                    raise ProjectionReceiptError("projection_receipt.context_authority_collision")
                authenticate_context_authority_registration(
                    result,
                    expected_context=context,
                    expected_authority=authority,
                    authenticator=self._authenticator,
                )
                await transaction.commit()
                return result
            await self._strict_phase_policy.assert_first_registration_allowed(
                connection,
                context=context,
                locked_run=locked_run,
            )
            if self._additional_phase_policy is not None:
                await self._additional_phase_policy.assert_first_registration_allowed(
                    connection,
                    context=context,
                    locked_run=locked_run,
                )
            await connection.execute(
                INSERT_REGISTRATION_SQL,
                context.run_id_sha256,
                context.context_sha256,
                authority.terminal_commitment_sha256,
                canonical_bytes(context.payload()).decode("ascii"),
                canonical_bytes(authority.payload()).decode("ascii"),
                registration_sha256,
                registration_mac_sha256,
                registered_at,
            )
            row = await connection.fetchrow(
                READ_REGISTRATION_SQL,
                context.run_id_sha256,
                context.context_sha256,
            )
            if row is None:
                raise ProjectionReceiptError("projection_receipt.context_authority_missing")
            result = _registration_from_row(row, created=True)
            if (
                result.context != context
                or result.authority != authority
                or result.registration_sha256 != registration_sha256
                or result.registration_mac_sha256 != registration_mac_sha256
                or result.registered_at != registered_at
            ):
                raise ProjectionReceiptError("projection_receipt.context_authority_divergent")
            authenticate_context_authority_registration(
                result,
                expected_context=context,
                expected_authority=authority,
                authenticator=self._authenticator,
            )
            await transaction.commit()
            return result
        except BaseException:
            await transaction.rollback()
            raise
        finally:
            await connection.close()


def _registration_from_row(row: Any, *, created: bool) -> ContextAuthorityRegistration:
    try:
        context = ManagedCleanupV3Context(
            **strict_json_object(
                row["context_json"], "managed_cleanup_v3_context_authority_invalid"
            )
        )
        authority_values = strict_json_object(
            row["authority_json"], "managed_cleanup_v3_context_authority_invalid"
        )
        pages = authority_values.get("ordered_page_sha256")
        if type(pages) is not list:
            raise ManagedCleanupV3Error("managed_cleanup_v3_context_authority_invalid")
        authority_values["ordered_page_sha256"] = tuple(pages)
        authority = ManagedCleanupV3Authority(**authority_values)
    except (ManagedCleanupV3Error, TypeError, KeyError) as exc:
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid") from exc
    if (
        row["run_id_sha256"] != context.run_id_sha256
        or row["context_sha256"] != context.context_sha256
        or row["authority_terminal_sha256"] != authority.terminal_commitment_sha256
    ):
        raise ProjectionReceiptError("projection_receipt.context_authority_invalid")
    return ContextAuthorityRegistration(
        context=context,
        authority=authority,
        registration_sha256=str(row["registration_sha256"]),
        registration_mac_sha256=str(row["registration_mac_sha256"]),
        registered_at=row["registered_at"],
        created=created,
    )


def _exact_pre_execution_run(row: Any, context: ManagedCleanupV3Context) -> bool:
    return bool(
        _exact_registry_identity(row, context)
        and row["state"] == "active"
        and row["projection_cleanup_state"] == "unsealed"
        and row["projection_manifest_json"] is None
        and row["projection_manifest_sha256"] is None
        and row["cleanup_fingerprint_sha256"] is None
        and row["cleanup_receipt_json"] is None
        and row["finalization_fingerprint_sha256"] is None
        and row["completion_receipt_json"] is None
        and row["completed_at"] is None
        and row["cleanup_plan_json"] is None
        and row["cleanup_plan_sha256"] is None
        and row["cleanup_plan_state"] == "recovery_blocked"
    )


def _exact_registry_identity(row: Any, context: ManagedCleanupV3Context) -> bool:
    return bool(
        row["run_id_sha256"] == context.run_id_sha256
        and row["binding_commitment_sha256"] == context.binding_commitment_sha256
        and row["infinity_target_identity_sha256"] == context.infinity_target_identity_sha256
        and row["space_id"] == context.space_id
        and row["space_slug"] == context.space_slug
    )


__all__ = (
    "AsyncPostgresCleanupV4ContextAuthorityRegistry",
    "ContextRegistrationPhasePolicy",
    "StrictV4PreExecutionRegistrationPolicy",
)
