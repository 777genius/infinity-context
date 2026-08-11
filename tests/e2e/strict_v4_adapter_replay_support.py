"""Provider-free PostgreSQL adapter proof for exact strict-v4 seal replay."""

from __future__ import annotations

import hashlib

import pytest
from infinity_context_adapters.postgres.managed_cleanup_v4_context_registration import (
    AsyncPostgresCleanupV4ContextAuthorityRegistry,
)
from infinity_context_adapters.postgres.strict_v4_writer_authority import (
    AsyncPostgresStrictV4WriterAuthority,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
)
from infinity_context_core.features.projection_receipts.strict_v4_writer_authority import (
    build_strict_v4_writer_authority,
)
from strict_v4_provider_free_material import build_provider_free_strict_v4_material

_AUTHENTICATOR = ProjectionReceiptAuthenticator(b"strict-v4-0036-provider-free" * 2)


def _digest(field: str) -> str:
    return hashlib.sha256(f"0036:adapter:{field}".encode()).hexdigest()


async def assert_adapter_seal_replay(
    *,
    asyncpg,
    owner,
    canonical,
    registrar_connect,
    sealer_connect,
) -> None:
    """Seal through the adapter, insert the sentinel, then replay exactly/divergently."""

    run_id = _digest("run")
    space_id = f"benchmark-space-{run_id[:48]}"
    registered_at = await owner.fetchval("SELECT pg_catalog.clock_timestamp()")
    sealed_at = await owner.fetchval("SELECT pg_catalog.clock_timestamp()")
    material = build_provider_free_strict_v4_material(
        run_id_sha256=run_id,
        space_id=space_id,
        space_slug=space_id,
        authenticator=_AUTHENTICATOR,
        registered_at=registered_at,
        prepared_at=registered_at,
        sealed_at=sealed_at,
    )
    receipt = material.receipt
    await owner.execute(
        """
        INSERT INTO public.memory_spaces(id,slug,name,status,created_at,updated_at)
        VALUES($1,$1,$1,'active',pg_catalog.clock_timestamp(),
               pg_catalog.clock_timestamp())
        """,
        space_id,
    )
    await owner.execute(
        """
        INSERT INTO public.memory_comparison_benchmark_runs(
          run_id_sha256,binding_commitment_sha256,infinity_target_identity_sha256,
          space_id,space_slug,idempotency_key_sha256,registration_fingerprint_sha256,
          state,cleanup_plan_state,projection_cleanup_state,created_at,updated_at)
        VALUES($1,$2,$3,$4,$4,$5,$6,'active','recovery_blocked','unsealed',
               pg_catalog.clock_timestamp(),pg_catalog.clock_timestamp())
        """,
        receipt.run_id_sha256,
        receipt.binding_commitment_sha256,
        receipt.a2_context.infinity_target_identity_sha256,
        space_id,
        _digest("idempotency"),
        _digest("registration"),
    )
    registry = AsyncPostgresCleanupV4ContextAuthorityRegistry(
        connect=registrar_connect,
        authenticator=_AUTHENTICATOR,
    )
    await _insert_target_identity(owner, run_id=run_id)
    with pytest.raises(asyncpg.CheckViolationError) as registration_rejected:
        await registry.register_and_readback(
            context=receipt.a2_context,
            authority=receipt.a2_authority,
            registration_sha256=receipt.registration_sha256,
            registration_mac_sha256=receipt.registration_mac_sha256,
            registered_at=receipt.registered_at,
        )
    assert (
        registration_rejected.value.constraint_name
        == "ck_memory_comparison_strict_v4_registration_pristine"
    )
    await _delete_target_identity(owner, run_id=run_id)
    registration = await registry.register_and_readback(
        context=receipt.a2_context,
        authority=receipt.a2_authority,
        registration_sha256=receipt.registration_sha256,
        registration_mac_sha256=receipt.registration_mac_sha256,
        registered_at=receipt.registered_at,
    )
    assert registration.created is True
    writer = AsyncPostgresStrictV4WriterAuthority(
        connect=sealer_connect,
        authenticator=_AUTHENTICATOR,
    )
    await _insert_target_identity(owner, run_id=run_id)
    with pytest.raises(asyncpg.CheckViolationError) as seal_rejected:
        await writer.seal_and_readback(
            receipt=receipt,
            authority=material.authority,
        )
    assert seal_rejected.value.constraint_name == "ck_memory_comparison_strict_v4_seal_pristine"
    await _delete_target_identity(owner, run_id=run_id)
    assert (
        await writer.seal_and_readback(
            receipt=receipt,
            authority=material.authority,
        )
        == material.authority
    )
    await canonical.execute(
        """
        INSERT INTO public.memory_idempotency_records(
          space_id,key,fingerprint,result_type,result_id,created_at)
        VALUES($1,'adapter-replay','adapter-replay','strict-v4','adapter-replay',
               pg_catalog.clock_timestamp())
        """,
        space_id,
    )
    assert (
        await writer.seal_and_readback(
            receipt=receipt,
            authority=material.authority,
        )
        == material.authority
    )
    divergent_at = await owner.fetchval(
        "SELECT CASE WHEN pg_catalog.clock_timestamp() <= $1 "
        "THEN $1 + '1 microsecond'::pg_catalog.interval "
        "ELSE pg_catalog.clock_timestamp() END",
        material.authority.sealed_at,
    )
    divergent = build_strict_v4_writer_authority(
        receipt=receipt,
        authenticator=_AUTHENTICATOR,
        sealed_at=divergent_at,
    )
    with pytest.raises(ProjectionReceiptError, match="writer_authority_divergent"):
        await writer.seal_and_readback(receipt=receipt, authority=divergent)


async def _insert_target_identity(owner, *, run_id: str) -> None:
    await owner.execute(
        """
        INSERT INTO public.memory_projection_target_identities(
          run_id_sha256,kind,identity_sha256,identity_commitment_sha256,
          canonical_source_id,physical_identity,lineage_root_sha256,
          target_authority_sha256,identity_mac_sha256,created_at)
        VALUES($1,'qdrant_point_id',$2,$3,'authority-pristine-probe',
               'authority-pristine-probe',$4,$5,$6,pg_catalog.clock_timestamp())
        """,
        run_id,
        _digest("target-identity"),
        _digest("target-commitment"),
        _digest("target-lineage"),
        _digest("target-authority"),
        _digest("target-mac"),
    )


async def _delete_target_identity(owner, *, run_id: str) -> None:
    await owner.execute(
        "DELETE FROM public.memory_projection_target_identities WHERE run_id_sha256=$1",
        run_id,
    )


__all__ = ("assert_adapter_seal_replay",)
