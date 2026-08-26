"""Crash-safe worker seam for exact provider projection receipts."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from infinity_context_adapters.postgres.projection_receipt_repository import (
    PostgresProjectionReceiptRepository,
)
from infinity_context_core.features.projection_receipts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReadbackPort,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    ProjectionResultReceipt,
    ProjectionTargetIdentity,
    build_projection_result_receipt,
    ensure_projection_and_readback,
    ensure_projection_deleted_and_readback,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Authority,
    ManagedCleanupV3Context,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ProjectionReceiptWorker:
    """Sequence provider I/O before one canonical Postgres commit."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: ProjectionReadbackPort,
        authenticator: ProjectionReceiptAuthenticator,
        now: Callable[[], datetime],
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._authenticator = authenticator
        self._now = now

    async def register_context_authority(
        self,
        *,
        context: ManagedCleanupV3Context,
        authority: ManagedCleanupV3Authority,
    ) -> bool:
        """Persist/read back the exact A2 authority before any provider call."""

        async with self._session_factory() as session, session.begin():
            return await PostgresProjectionReceiptRepository(
                session, self._authenticator
            ).register_context_authority(
                context=context,
                authority=authority,
                registered_at=self._now(),
            )

    async def _claim_job_preflight(
        self,
        binding: ProjectionJobBinding,
        *,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> tuple[bytes, int]:
        async with self._session_factory() as session, session.begin():
            return await PostgresProjectionReceiptRepository(
                session, self._authenticator
            ).claim_job_preflight(
                binding=binding,
                operation=operation,
                expected_identities=expected_identities,
            )

    async def _mark_dispatch_started(
        self,
        binding: ProjectionJobBinding,
        *,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
        claim_token: bytes,
        generation: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await PostgresProjectionReceiptRepository(
                session, self._authenticator
            ).mark_dispatch_started(
                binding=binding,
                operation=operation,
                expected_identities=expected_identities,
                claim_token=claim_token,
                generation=generation,
            )

    async def _wait_for_authenticated_receipt(
        self,
        binding: ProjectionJobBinding,
        *,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt:
        for _ in range(500):
            await asyncio.sleep(0.01)
            existing = await self._load_authenticated_receipt(
                binding,
                operation=operation,
                expected_identities=expected_identities,
            )
            if existing is not None:
                return existing
        raise ProjectionReceiptError("projection_receipt.claim_busy")

    async def _load_authenticated_receipt(
        self,
        binding: ProjectionJobBinding,
        *,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt | None:
        async with self._session_factory() as session, session.begin():
            return await PostgresProjectionReceiptRepository(
                session, self._authenticator
            ).load_authenticated_receipt(
                binding=binding,
                operation=operation,
                expected_identities=expected_identities,
            )

    async def _reconcile_dispatch_started(
        self,
        binding: ProjectionJobBinding,
        *,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt:
        ordered_expected = tuple(
            sorted(expected_identities, key=lambda item: (item.kind, item.identity_sha256))
        )
        for _ in range(500):
            existing = await self._load_authenticated_receipt(
                binding,
                operation=operation,
                expected_identities=expected_identities,
            )
            if existing is not None:
                return existing
            matches = await self._provider.read_exact(binding)
            materialization: ProjectionMaterialization | None = None
            if operation == "upsert" and len(matches) == 1:
                observed = matches[0]
                ordered_observed = tuple(
                    sorted(
                        observed.identities,
                        key=lambda item: (item.kind, item.identity_sha256),
                    )
                )
                if (
                    observed.projection_key_sha256 != binding.projection_key_sha256
                    or ordered_observed != ordered_expected
                    or observed.completed_at.tzinfo is None
                ):
                    raise ProjectionReceiptError("projection_receipt.readback_divergent")
                materialization = observed
            elif operation == "delete" and not matches:
                materialization = ProjectionMaterialization(
                    projection_key_sha256=binding.projection_key_sha256,
                    identities=ordered_expected,
                    completed_at=self._now(),
                )
            elif len(matches) > 1:
                raise ProjectionReceiptError("projection_receipt.readback_multiple")
            if materialization is not None:
                receipt = build_projection_result_receipt(
                    binding=binding,
                    materialization=materialization,
                    authenticator=self._authenticator,
                    persisted_at=self._now(),
                    operation=operation,
                    result_state="present" if operation == "upsert" else "absent",
                )
                async with self._session_factory() as session, session.begin():
                    await PostgresProjectionReceiptRepository(
                        session, self._authenticator
                    ).persist_and_mark_done(receipt, reconciliation=True)
                return receipt
            await asyncio.sleep(0.01)
        raise ProjectionReceiptError("projection_receipt.outcome_unknown")

    async def _persist_owner_or_replay(
        self,
        receipt: ProjectionResultReceipt,
        *,
        claim_token: bytes,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt:
        try:
            async with self._session_factory() as session, session.begin():
                await PostgresProjectionReceiptRepository(
                    session, self._authenticator
                ).persist_and_mark_done(receipt, claim_token=claim_token)
            return receipt
        except ProjectionReceiptError as exc:
            if exc.diagnostic_code not in {
                "projection_receipt.claim_lost",
                "projection_receipt.replay_divergent",
            }:
                raise
        existing = await self._load_authenticated_receipt(
            receipt.binding,
            operation=receipt.operation,
            expected_identities=expected_identities,
        )
        if existing is None:
            raise ProjectionReceiptError("projection_receipt.outcome_unknown")
        return existing

    async def ensure_projection_and_readback(
        self,
        *,
        binding: ProjectionJobBinding,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt:
        existing = await self._load_authenticated_receipt(
            binding,
            operation="upsert",
            expected_identities=expected_identities,
        )
        if existing is not None:
            return existing
        try:
            claim_token, generation = await self._claim_job_preflight(
                binding,
                operation="upsert",
                expected_identities=expected_identities,
            )
        except ProjectionReceiptError as exc:
            if exc.diagnostic_code == "projection_receipt.claim_busy":
                return await self._wait_for_authenticated_receipt(
                    binding,
                    operation="upsert",
                    expected_identities=expected_identities,
                )
            if exc.diagnostic_code != "projection_receipt.dispatch_started":
                raise
            return await self._reconcile_dispatch_started(
                binding,
                operation="upsert",
                expected_identities=expected_identities,
            )
        await self._mark_dispatch_started(
            binding,
            operation="upsert",
            expected_identities=expected_identities,
            claim_token=claim_token,
            generation=generation,
        )
        materialization = await ensure_projection_and_readback(
            self._provider,
            binding=binding,
            expected_identities=expected_identities,
        )
        receipt = build_projection_result_receipt(
            binding=binding,
            materialization=materialization,
            authenticator=self._authenticator,
            persisted_at=self._now(),
        )
        return await self._persist_owner_or_replay(
            receipt,
            claim_token=claim_token,
            expected_identities=expected_identities,
        )

    async def ensure_deletion_and_readback(
        self,
        *,
        binding: ProjectionJobBinding,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> ProjectionResultReceipt:
        existing = await self._load_authenticated_receipt(
            binding,
            operation="delete",
            expected_identities=expected_identities,
        )
        if existing is not None:
            return existing
        try:
            claim_token, generation = await self._claim_job_preflight(
                binding,
                operation="delete",
                expected_identities=expected_identities,
            )
        except ProjectionReceiptError as exc:
            if exc.diagnostic_code == "projection_receipt.claim_busy":
                return await self._wait_for_authenticated_receipt(
                    binding,
                    operation="delete",
                    expected_identities=expected_identities,
                )
            if exc.diagnostic_code != "projection_receipt.dispatch_started":
                raise
            return await self._reconcile_dispatch_started(
                binding,
                operation="delete",
                expected_identities=expected_identities,
            )
        await self._mark_dispatch_started(
            binding,
            operation="delete",
            expected_identities=expected_identities,
            claim_token=claim_token,
            generation=generation,
        )
        materialization = await ensure_projection_deleted_and_readback(
            self._provider,
            binding=binding,
            expected_identities=expected_identities,
            observed_at=self._now(),
        )
        receipt = build_projection_result_receipt(
            binding=binding,
            materialization=materialization,
            authenticator=self._authenticator,
            persisted_at=self._now(),
            operation="delete",
            result_state="absent",
        )
        return await self._persist_owner_or_replay(
            receipt,
            claim_token=claim_token,
            expected_identities=expected_identities,
        )


__all__ = ("ProjectionReceiptWorker",)
