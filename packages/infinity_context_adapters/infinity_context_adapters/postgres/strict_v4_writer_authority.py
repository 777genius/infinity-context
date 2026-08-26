"""Postgres seal/readback adapter for strict-v4 canonical write authority."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

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
    StrictV4WriterAuthorityPort,
    authenticate_strict_v4_writer_authority,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import canonical_bytes

from infinity_context_adapters.postgres.strict_v4_authority_lock_topology import (
    assert_strict_v4_authority_lock_topology,
)
from infinity_context_adapters.postgres.strict_v4_database_roles import (
    STRICT_V4_SEALER_ROLE,
    assert_strict_v4_runtime_capability,
)
from infinity_context_adapters.postgres.strict_v4_writer_fence_topology import (
    assert_strict_v4_writer_fence_topology,
)

_LOCK_TARGETS_SQL = """
SELECT public.memory_comparison_lock_strict_v4_seal_targets($1, $2)
"""
_READ_RUN_SQL = """
SELECT run_id_sha256, binding_commitment_sha256, infinity_target_identity_sha256,
       space_id, space_slug, state, cleanup_plan_json, cleanup_plan_sha256,
       cleanup_plan_state, projection_cleanup_state, projection_manifest_json,
       projection_manifest_sha256, cleanup_fingerprint_sha256,
       cleanup_receipt_json, finalization_fingerprint_sha256,
       completion_receipt_json, completed_at
FROM public.memory_comparison_benchmark_runs
WHERE run_id_sha256=$1
"""
_READ_CONTEXT_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       context_json::pg_catalog.text AS context_json,
       authority_json::pg_catalog.text AS authority_json,
       registration_sha256, registration_mac_sha256, registered_at
FROM public.memory_cleanup_v3_context_authorities
WHERE run_id_sha256=$1 OR context_sha256=$2
ORDER BY run_id_sha256, context_sha256
"""
_READ_AUTHORITY_SQL = """
SELECT run_id_sha256, context_sha256, authority_terminal_sha256,
       preparation_receipt_json::pg_catalog.text AS preparation_receipt_json,
       preparation_receipt_sha256, preparation_receipt_mac_sha256,
       writer_authority_json::pg_catalog.text AS writer_authority_json,
       writer_authority_sha256, writer_authority_mac_sha256,
       registration_sha256, registration_mac_sha256,
       provider_calls, paid_go_ready, state, sealed_at, closed_at
FROM public.memory_comparison_strict_v4_preparations
WHERE run_id_sha256=$1 OR context_sha256=$2
ORDER BY run_id_sha256, context_sha256
"""
_DATABASE_NOW_SQL = "SELECT pg_catalog.clock_timestamp()"
_CANONICAL_ABSENCE_SQL = """
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
_INSERT_SQL = """
INSERT INTO public.memory_comparison_strict_v4_preparations (
  run_id_sha256, context_sha256, authority_terminal_sha256,
  preparation_receipt_json, preparation_receipt_sha256,
  preparation_receipt_mac_sha256, writer_authority_json,
  writer_authority_sha256, writer_authority_mac_sha256,
  registration_sha256, registration_mac_sha256,
  provider_calls, paid_go_ready, state, sealed_at, closed_at
) VALUES ($1,$2,$3,$4::pg_catalog.jsonb,$5,$6,$7::pg_catalog.jsonb,
         $8,$9,$10,$11,0,FALSE,'sealed',$12,NULL)
"""


class AsyncPostgresStrictV4WriterAuthority(StrictV4WriterAuthorityPort):
    """Grant one authority using a dedicated seal credential, never the execution writer."""

    def __init__(
        self,
        *,
        connect: Callable[[], Awaitable[Any]],
        authenticator: ProjectionReceiptAuthenticator,
    ) -> None:
        if type(authenticator) is not ProjectionReceiptAuthenticator:
            raise ProjectionReceiptError("projection_receipt.hmac_capability_invalid")
        self._connect = connect
        self._authenticator = authenticator

    async def seal_and_readback(
        self,
        *,
        receipt: StrictV4PreparationReceipt,
        authority: StrictV4WriterAuthority,
    ) -> StrictV4WriterAuthority:
        authenticate_strict_v4_preparation_receipt(receipt, authenticator=self._authenticator)
        authenticate_strict_v4_writer_authority(
            authority,
            expected_receipt=receipt,
            authenticator=self._authenticator,
        )
        connection = await self._connect()
        transaction = connection.transaction(isolation="serializable")
        try:
            await transaction.start()
            await assert_strict_v4_runtime_capability(
                connection,
                capability_role=STRICT_V4_SEALER_ROLE,
                error_code="projection_receipt.writer_authority_role_invalid",
            )
            await assert_strict_v4_authority_lock_topology(
                connection,
                capability_role=STRICT_V4_SEALER_ROLE,
            )
            await assert_strict_v4_writer_fence_topology(connection)
            await connection.execute(
                _LOCK_TARGETS_SQL,
                receipt.run_id_sha256,
                receipt.a2_context.context_sha256,
            )
            database_now = await connection.fetchval(_DATABASE_NOW_SQL)
            if authority.sealed_at > database_now:
                raise ProjectionReceiptError("projection_receipt.writer_authority_time_invalid")
            run = await connection.fetchrow(_READ_RUN_SQL, receipt.run_id_sha256)
            if run is None or not _strict_unsealed_run(run, receipt):
                raise ProjectionReceiptError("projection_receipt.writer_authority_run_invalid")
            contexts = await connection.fetch(
                _READ_CONTEXT_SQL,
                receipt.run_id_sha256,
                receipt.a2_context.context_sha256,
            )
            if len(contexts) != 1 or not _exact_context(contexts[0], receipt):
                raise ProjectionReceiptError("projection_receipt.writer_authority_context_invalid")
            rows = await connection.fetch(
                _READ_AUTHORITY_SQL,
                receipt.run_id_sha256,
                receipt.a2_context.context_sha256,
            )
            if rows:
                if len(rows) != 1:
                    raise ProjectionReceiptError("projection_receipt.writer_authority_collision")
                durable = _read_exact(rows[0], receipt, authority)
                await transaction.commit()
                return durable
            if (
                await connection.fetchval(
                    _CANONICAL_ABSENCE_SQL,
                    receipt.a2_context.space_id,
                    receipt.run_id_sha256,
                )
                is not True
            ):
                raise ProjectionReceiptError("projection_receipt.writer_authority_not_pristine")
            await connection.execute(
                _INSERT_SQL,
                receipt.run_id_sha256,
                receipt.a2_context.context_sha256,
                receipt.a2_authority.terminal_commitment_sha256,
                canonical_bytes(receipt.payload()).decode("ascii"),
                receipt.receipt_sha256,
                receipt.receipt_mac_sha256,
                canonical_bytes(authority.payload()).decode("ascii"),
                authority.writer_authority_sha256,
                authority.writer_authority_mac_sha256,
                receipt.registration_sha256,
                receipt.registration_mac_sha256,
                authority.sealed_at,
            )
            row = await connection.fetchrow(
                _READ_AUTHORITY_SQL,
                receipt.run_id_sha256,
                receipt.a2_context.context_sha256,
            )
            if row is None:
                raise ProjectionReceiptError("projection_receipt.writer_authority_missing")
            durable = _read_exact(row, receipt, authority)
            await transaction.commit()
            return durable
        except BaseException:
            await transaction.rollback()
            raise
        finally:
            await connection.close()


def _strict_unsealed_run(row: Any, receipt: StrictV4PreparationReceipt) -> bool:
    context = receipt.a2_context
    return bool(
        row["run_id_sha256"] == receipt.run_id_sha256
        and row["binding_commitment_sha256"] == receipt.binding_commitment_sha256
        and row["infinity_target_identity_sha256"] == context.infinity_target_identity_sha256
        and row["space_id"] == context.space_id
        and row["space_slug"] == context.space_slug
        and row["state"] == "active"
        and row["cleanup_plan_json"] is None
        and row["cleanup_plan_sha256"] is None
        and row["cleanup_plan_state"] == "recovery_blocked"
        and row["projection_cleanup_state"] == "unsealed"
        and row["projection_manifest_json"] is None
        and row["projection_manifest_sha256"] is None
        and row["cleanup_fingerprint_sha256"] is None
        and row["cleanup_receipt_json"] is None
        and row["finalization_fingerprint_sha256"] is None
        and row["completion_receipt_json"] is None
        and row["completed_at"] is None
    )


def _exact_context(row: Any, receipt: StrictV4PreparationReceipt) -> bool:
    return bool(
        row["run_id_sha256"] == receipt.run_id_sha256
        and row["context_sha256"] == receipt.a2_context.context_sha256
        and row["authority_terminal_sha256"] == receipt.a2_authority.terminal_commitment_sha256
        and row["registration_sha256"] == receipt.registration_sha256
        and row["registration_mac_sha256"] == receipt.registration_mac_sha256
        and row["registered_at"] == receipt.registered_at
        and canonical_bytes(json.loads(str(row["context_json"])))
        == canonical_bytes(receipt.a2_context.payload())
        and canonical_bytes(json.loads(str(row["authority_json"])))
        == canonical_bytes(receipt.a2_authority.payload())
    )


def _read_exact(
    row: Any,
    receipt: StrictV4PreparationReceipt,
    expected: StrictV4WriterAuthority,
) -> StrictV4WriterAuthority:
    try:
        receipt_payload = json.loads(str(row["preparation_receipt_json"]))
        authority_payload = json.loads(str(row["writer_authority_json"]))
        authority_payload["sealed_at"] = datetime.fromisoformat(authority_payload["sealed_at"])
        durable = StrictV4WriterAuthority(**authority_payload)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ProjectionReceiptError("projection_receipt.writer_authority_invalid") from exc
    if (
        row["run_id_sha256"] != receipt.run_id_sha256
        or row["context_sha256"] != receipt.a2_context.context_sha256
        or row["authority_terminal_sha256"] != receipt.a2_authority.terminal_commitment_sha256
        or canonical_bytes(receipt_payload) != canonical_bytes(receipt.payload())
        or row["preparation_receipt_sha256"] != receipt.receipt_sha256
        or row["preparation_receipt_mac_sha256"] != receipt.receipt_mac_sha256
        or durable != expected
        or row["writer_authority_sha256"] != expected.writer_authority_sha256
        or row["writer_authority_mac_sha256"] != expected.writer_authority_mac_sha256
        or row["registration_sha256"] != receipt.registration_sha256
        or row["registration_mac_sha256"] != receipt.registration_mac_sha256
        or type(row["provider_calls"]) is not int
        or row["provider_calls"] != 0
        or row["paid_go_ready"] is not False
        or row["state"] != "sealed"
        or row["sealed_at"] != expected.sealed_at
        or row["closed_at"] is not None
    ):
        raise ProjectionReceiptError("projection_receipt.writer_authority_divergent")
    return durable


__all__ = ("AsyncPostgresStrictV4WriterAuthority", "STRICT_V4_SEALER_ROLE")
