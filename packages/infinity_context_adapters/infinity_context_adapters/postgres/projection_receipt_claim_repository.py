"""Durable pre-dispatch claim state machine for projection receipts."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from infinity_context_core.features.projection_receipts import (
    ProjectionJobBinding,
    ProjectionMaterialization,
    ProjectionReceiptAuthenticator,
    ProjectionReceiptError,
    ProjectionTargetIdentity,
    build_projection_result_receipt,
)
from infinity_context_core.ports.managed_cleanup_v3_contracts import commitment
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.projection_receipt_models import (
    MemoryProjectionReceiptClaimRow,
)


class ProjectionReceiptClaimRepositoryMixin:
    """Claim behavior mixed into the authoritative receipt repository."""

    _session: AsyncSession
    _authenticator: ProjectionReceiptAuthenticator

    async def claim_job_preflight(
        self,
        *,
        binding: ProjectionJobBinding,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
    ) -> tuple[bytes, int]:
        """Validate and durably fence one provider owner without a long transaction."""

        outbox = await self._locked_outbox(binding.outbox_id)
        registry = await self._locked_registry(binding.run_id_sha256)
        context_authority = await self._locked_context_authority(binding.context_sha256)
        if context_authority is None:
            raise ProjectionReceiptError("projection_receipt.context_authority_missing")
        observed_at = _aware_datetime(outbox.updated_at)
        receipt = build_projection_result_receipt(
            binding=binding,
            materialization=ProjectionMaterialization(
                projection_key_sha256=binding.projection_key_sha256,
                identities=expected_identities,
                completed_at=observed_at,
            ),
            authenticator=self._authenticator,
            persisted_at=observed_at,
            operation=operation,
            result_state="present" if operation == "upsert" else "absent",
        )
        canonical = await self._locked_canonical_aggregate(receipt)
        self._validate_canonical_lineage(outbox, registry, context_authority, canonical, receipt)
        if outbox.status == "done":
            raise ProjectionReceiptError("projection_receipt.done_without_receipt")
        token = secrets.token_bytes(32)
        token_sha256 = hashlib.sha256(token).hexdigest()
        claimed_at = _aware_datetime(await self._session.scalar(select(func.now())))
        fingerprint = expected_identities_sha256(expected_identities)
        claim = await self._locked_claim(binding.outbox_id)
        if claim is not None:
            if (
                claim.run_id_sha256 != binding.run_id_sha256
                or claim.context_sha256 != binding.context_sha256
                or claim.worker_authority_sha256 != binding.worker_authority_sha256
                or claim.projection_key_sha256 != binding.projection_key_sha256
                or claim.operation != operation
                or claim.expected_identities_sha256 != fingerprint
            ):
                raise ProjectionReceiptError("projection_receipt.claim_divergent")
            if claim.state != "prepared":
                raise ProjectionReceiptError("projection_receipt.dispatch_started")
            if claimed_at < _aware_datetime(claim.lease_expires_at):
                raise ProjectionReceiptError("projection_receipt.claim_busy")
            claim.claim_token_sha256 = token_sha256
            claim.generation += 1
            claim.lease_expires_at = claimed_at + timedelta(seconds=60)
            claim.updated_at = claimed_at
            await self._session.flush()
            return token, claim.generation
        self._session.add(
            MemoryProjectionReceiptClaimRow(
                outbox_id=binding.outbox_id,
                run_id_sha256=binding.run_id_sha256,
                context_sha256=binding.context_sha256,
                worker_authority_sha256=binding.worker_authority_sha256,
                expected_identities_sha256=fingerprint,
                projection_key_sha256=binding.projection_key_sha256,
                operation=operation,
                claim_token_sha256=token_sha256,
                generation=1,
                state="prepared",
                lease_expires_at=claimed_at + timedelta(seconds=60),
                created_at=claimed_at,
                updated_at=claimed_at,
            )
        )
        await self._session.flush()
        return token, 1

    async def mark_dispatch_started(
        self,
        *,
        binding: ProjectionJobBinding,
        operation: str,
        expected_identities: tuple[ProjectionTargetIdentity, ...],
        claim_token: bytes,
        generation: int,
    ) -> None:
        """Revalidate authority and fence a live owner immediately before provider I/O."""

        outbox = await self._locked_outbox(binding.outbox_id)
        registry = await self._locked_registry(binding.run_id_sha256)
        context_authority = await self._locked_context_authority(binding.context_sha256)
        if context_authority is None:
            raise ProjectionReceiptError("projection_receipt.context_authority_missing")
        observed_at = _aware_datetime(outbox.updated_at)
        receipt = build_projection_result_receipt(
            binding=binding,
            materialization=ProjectionMaterialization(
                projection_key_sha256=binding.projection_key_sha256,
                identities=expected_identities,
                completed_at=observed_at,
            ),
            authenticator=self._authenticator,
            persisted_at=observed_at,
            operation=operation,
            result_state="present" if operation == "upsert" else "absent",
        )
        canonical = await self._locked_canonical_aggregate(receipt)
        self._validate_canonical_lineage(outbox, registry, context_authority, canonical, receipt)
        claim = await self._locked_claim(binding.outbox_id)
        db_now = _aware_datetime(await self._session.scalar(select(func.now())))
        if (
            claim is None
            or claim.state != "prepared"
            or not hmac.compare_digest(
                claim.claim_token_sha256, hashlib.sha256(claim_token).hexdigest()
            )
            or claim.generation != generation
            or claim.projection_key_sha256 != binding.projection_key_sha256
            or claim.operation != operation
            or claim.expected_identities_sha256 != expected_identities_sha256(expected_identities)
            or db_now >= _aware_datetime(claim.lease_expires_at)
        ):
            raise ProjectionReceiptError("projection_receipt.claim_fenced")
        claim.state = "dispatch_started"
        claim.updated_at = db_now
        await self._session.flush()


def expected_identities_sha256(identities: tuple[ProjectionTargetIdentity, ...]) -> str:
    ordered = sorted(identities, key=lambda item: (item.kind, item.identity_sha256))
    return commitment(
        "projection-receipt-claim-identities/v1",
        {"identities": [item.canonical_payload() for item in ordered]},
    )


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
