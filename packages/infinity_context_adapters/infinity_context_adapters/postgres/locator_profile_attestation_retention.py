"""Bounded retention for resumable locator-profile attestation evidence."""

from sqlalchemy import delete, select

from infinity_context_adapters.postgres.models import (
    MemoryLocatorProfileAttestationCheckpointRow,
    MemoryLocatorProfileAttestationPageRow,
    MemoryLocatorProfileReconciliationOperationRow,
    MemoryLocatorProfileTransitionAuditRow,
)


async def compact_completed_attestations_before_scan(session, *, profile_id: str) -> None:
    completed = await _completed_checkpoints(session, profile_id)
    if not completed:
        return
    keep = completed[0]
    await _delete_pages(session, profile_id, keep.operation_id)
    for stale in completed[1:]:
        await session.delete(stale)


async def compact_reconciliation_evidence(session, *, profile_id: str, operation_id: str) -> None:
    """Keep one completed receipt, all in-progress proof, and two CAS receipts.

    With 256-point pages, a 16,385-point renewal is bounded at 67 checkpoint/page
    rows while active (one retained receipt + one checkpoint + 65 pages), and one
    checkpoint receipt after completion, independent of renewal count.
    """

    completed = await _completed_checkpoints(session, profile_id)
    if completed:
        keep = next(
            (item for item in completed if item.owner_operation_id == operation_id),
            completed[0],
        )
        await _delete_pages(session, profile_id, keep.operation_id)
        for stale in completed:
            if stale is not keep:
                await session.delete(stale)

    operations = tuple(
        (
            await session.execute(
                select(MemoryLocatorProfileReconciliationOperationRow)
                .where(MemoryLocatorProfileReconciliationOperationRow.profile_id == profile_id)
                .order_by(
                    MemoryLocatorProfileReconciliationOperationRow.created_at.desc(),
                    MemoryLocatorProfileReconciliationOperationRow.operation_id.desc(),
                )
                .with_for_update()
            )
        ).scalars()
    )
    retained_ids = {operation_id}
    audited_ids = set(
        (
            await session.execute(
                select(MemoryLocatorProfileTransitionAuditRow.lease_id).where(
                    MemoryLocatorProfileTransitionAuditRow.profile_id == profile_id,
                    MemoryLocatorProfileTransitionAuditRow.lease_id.in_(
                        tuple(item.operation_id for item in operations)
                    ),
                )
            )
        ).scalars()
    )
    predecessor_receipt = next(
        (
            item
            for item in operations
            if item.operation_id != operation_id and item.operation_id in audited_ids
        ),
        None,
    )
    if predecessor_receipt is None:
        predecessor_receipt = next(
            (item for item in operations if item.operation_id != operation_id), None
        )
    if predecessor_receipt is not None:
        retained_ids.add(predecessor_receipt.operation_id)
    for stale in operations:
        if stale.operation_id not in retained_ids:
            await session.delete(stale)


async def _completed_checkpoints(session, profile_id: str):
    return tuple(
        (
            await session.execute(
                select(MemoryLocatorProfileAttestationCheckpointRow)
                .where(
                    MemoryLocatorProfileAttestationCheckpointRow.profile_id == profile_id,
                    MemoryLocatorProfileAttestationCheckpointRow.complete.is_(True),
                )
                .order_by(
                    MemoryLocatorProfileAttestationCheckpointRow.updated_at.desc(),
                    MemoryLocatorProfileAttestationCheckpointRow.operation_id.desc(),
                )
                .with_for_update()
            )
        ).scalars()
    )


async def _delete_pages(session, profile_id: str, operation_id: str) -> None:
    await session.execute(
        delete(MemoryLocatorProfileAttestationPageRow).where(
            MemoryLocatorProfileAttestationPageRow.profile_id == profile_id,
            MemoryLocatorProfileAttestationPageRow.operation_id == operation_id,
        )
    )


__all__ = (
    "compact_completed_attestations_before_scan",
    "compact_reconciliation_evidence",
)
