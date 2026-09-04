"""Outbox assertions shared by asset extraction API tests."""

import asyncio

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _get_asset_extract_outbox_row(
    client: TestClient,
    extraction_id: str,
) -> MemoryOutboxRow:
    async with AsyncSession(client.app.state.container.engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow)
                .where(MemoryOutboxRow.event_type == "asset.extract")
                .where(MemoryOutboxRow.aggregate_id == extraction_id)
                .order_by(MemoryOutboxRow.id.desc())
                .limit(1)
            )
        ).scalar_one()
        return row


def assert_manual_retry_reschedules_outbox_row(
    client: TestClient,
    extraction_id: str,
    *,
    headers: dict[str, str],
) -> None:
    failed_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
    assert failed_row.status == "retry_pending"

    retry = client.post(
        f"/v1/asset-extractions/{extraction_id}/retry",
        headers=headers,
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["data"]["status"] == "pending"

    rescheduled_row = asyncio.run(_get_asset_extract_outbox_row(client, extraction_id))
    assert rescheduled_row.id == failed_row.id
    assert rescheduled_row.status == "pending"
    assert rescheduled_row.attempt_count == 0
