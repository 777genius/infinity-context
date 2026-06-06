"""Server-layer backpressure guards."""

from __future__ import annotations

from fastapi import status
from fastapi.responses import JSONResponse
from memo_stack_adapters.postgres.models import MemoryOutboxRow
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_server.composition import Container


async def document_ingest_backpressure_response(container: Container) -> JSONResponse | None:
    threshold = container.settings.outbox_backpressure_pending_threshold
    if threshold <= 0:
        return None
    pending_active = await _active_outbox_count(container)
    if pending_active < threshold:
        return None
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": "memory.backpressure",
                "message": "Backpressure",
                "retryable": True,
                "safe_details": {
                    "reason": "outbox_pending_high",
                    "pending_active": pending_active,
                    "threshold": threshold,
                },
            }
        },
    )


async def _active_outbox_count(container: Container) -> int:
    async with AsyncSession(container.engine) as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(MemoryOutboxRow)
                .where(MemoryOutboxRow.status.in_(("pending", "retry_pending", "running")))
            )
            or 0
        )
