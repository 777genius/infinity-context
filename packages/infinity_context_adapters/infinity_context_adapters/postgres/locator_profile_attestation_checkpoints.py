"""Durable, CAS-updated checkpoints for bounded profile attestation."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.features.context_building.public import (
    ProfileAttestationCheckpoint,
    ProfileAttestationPageReceipt,
)
from sqlalchemy import text

from infinity_context_adapters.postgres.locator_profile_attestation_retention import (
    compact_completed_attestations_before_scan,
)
from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileAttestationCheckpointRow,
    MemoryLocatorProfileAttestationPageRow,
    MemoryLocatorProfileMaintenanceFenceRow,
    MemoryLocatorProfileRow,
)


class PostgresRetrievalProfileAttestationCheckpointMixin:
    async def attestation_checkpoint(
        self, profile_id: str, operation_id: str
    ) -> ProfileAttestationCheckpoint | None:
        async with self.sessions() as session:
            row = await session.get(
                MemoryLocatorProfileAttestationCheckpointRow,
                (profile_id, operation_id),
            )
            if row is None:
                return None
            return ProfileAttestationCheckpoint(
                row.cursor,
                int(row.item_count),
                row.digest_accumulator,
                bool(row.complete),
                bool(row.scan_complete),
                int(row.scan_page_count),
                row.validation_cursor,
                int(row.validation_page_number),
                int(row.validation_item_count),
                row.validation_accumulator,
                int(row.provider_epoch),
            )

    async def attestation_page_receipt(
        self, profile_id: str, operation_id: str, page_number: int
    ) -> ProfileAttestationPageReceipt | None:
        async with self.sessions() as session:
            row = await session.get(
                MemoryLocatorProfileAttestationPageRow,
                (profile_id, operation_id, page_number),
            )
            if row is None:
                return None
            return ProfileAttestationPageReceipt(
                row.page_number,
                row.start_cursor,
                row.end_cursor,
                row.item_count,
                row.byte_count,
                row.page_digest,
            )

    async def checkpoint_attestation(
        self,
        profile_id: str,
        operation_id: str,
        *,
        previous_cursor: str | None,
        cursor: str | None,
        item_count: int,
        digest_accumulator: str,
        started_at: datetime,
        deadline_at: datetime,
        now: datetime,
        complete: bool,
        scan_complete: bool = False,
        page_receipt: ProfileAttestationPageReceipt | None = None,
        validation_cursor: str | None = None,
        validation_page_number: int = 0,
        validation_item_count: int = 0,
        validation_accumulator: str = "0" * 64,
        provider_epoch: int = 0,
        owner_operation_id: str | None = None,
    ) -> None:
        async with self.sessions() as session, session.begin():
            maintenance = await session.get(
                MemoryLocatorProfileMaintenanceFenceRow, True, with_for_update=True
            )
            if maintenance is None or maintenance.active:
                raise RuntimeError("retrieval_profile_maintenance_active")
            await session.execute(
                text(
                    "SELECT aggregate_version FROM memory_locator_profile_evidence_versions "
                    "WHERE singleton=TRUE FOR UPDATE"
                )
            )
            profile = await session.get(MemoryLocatorProfileRow, profile_id, with_for_update=True)
            if profile is None:
                raise RuntimeError("retrieval_profile_missing")
            row = await session.get(
                MemoryLocatorProfileAttestationCheckpointRow,
                (profile_id, operation_id),
                with_for_update=True,
            )
            if row is None:
                if previous_cursor is not None:
                    raise RuntimeError("retrieval_profile_attestation_cursor_raced")
                await compact_completed_attestations_before_scan(session, profile_id=profile_id)
                session.add(
                    MemoryLocatorProfileAttestationCheckpointRow(
                        profile_id=profile_id,
                        operation_id=operation_id,
                        stage="complete" if complete else "qdrant",
                        cursor=cursor,
                        item_count=item_count,
                        digest_accumulator=digest_accumulator,
                        started_at=started_at,
                        updated_at=now,
                        deadline_at=deadline_at,
                        complete=complete,
                        scan_complete=scan_complete,
                        scan_page_count=1 if page_receipt is not None else 0,
                        validation_cursor=validation_cursor,
                        validation_page_number=validation_page_number,
                        validation_item_count=validation_item_count,
                        validation_accumulator=validation_accumulator,
                        provider_epoch=provider_epoch,
                        owner_operation_id=owner_operation_id,
                    )
                )
                if page_receipt is not None:
                    session.add(_page_row(profile_id, operation_id, page_receipt))
                return
            if row.cursor != previous_cursor or row.complete:
                raise RuntimeError("retrieval_profile_attestation_cursor_raced")
            if page_receipt is not None:
                if page_receipt.page_number != row.scan_page_count:
                    raise RuntimeError("retrieval_profile_attestation_page_raced")
                session.add(_page_row(profile_id, operation_id, page_receipt))
                row.scan_page_count += 1
            row.cursor = cursor
            row.item_count = item_count
            row.digest_accumulator = digest_accumulator
            row.updated_at = now
            row.deadline_at = deadline_at
            row.stage = "complete" if complete else "qdrant"
            row.complete = complete
            row.scan_complete = scan_complete
            row.validation_cursor = validation_cursor
            row.validation_page_number = validation_page_number
            row.validation_item_count = validation_item_count
            row.validation_accumulator = validation_accumulator
            if row.provider_epoch != provider_epoch:
                raise RuntimeError("retrieval_profile_attestation_provider_epoch_drift")
            if row.owner_operation_id != owner_operation_id:
                raise RuntimeError("retrieval_profile_attestation_owner_drift")


def _page_row(
    profile_id: str,
    operation_id: str,
    receipt: ProfileAttestationPageReceipt,
) -> MemoryLocatorProfileAttestationPageRow:
    return MemoryLocatorProfileAttestationPageRow(
        profile_id=profile_id,
        operation_id=operation_id,
        page_number=receipt.page_number,
        start_cursor=receipt.start_cursor,
        end_cursor=receipt.end_cursor,
        item_count=receipt.item_count,
        byte_count=receipt.byte_count,
        page_digest=receipt.page_digest,
    )


__all__ = ("PostgresRetrievalProfileAttestationCheckpointMixin",)
