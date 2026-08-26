from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from infinity_context_adapters.postgres import create_schema
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_server.composition import build_container
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.worker import OutboxWorker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def test_outbox_claim_serializes_each_fairness_key_across_batches(tmp_path: Path) -> None:
    async def run() -> tuple[list[str], list[str]]:
        container = build_container(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{tmp_path / 'worker-fairness.db'}",
                service_token="test-token",
            )
        )
        try:
            await create_schema(container.engine)
            now = container.clock.now()
            async with AsyncSession(container.engine) as session:
                for index, (aggregate_id, fairness_key) in enumerate(
                    (
                        ("same-key-1", "chunk:same"),
                        ("same-key-2", "chunk:same"),
                        ("other-key", "chunk:other"),
                    )
                ):
                    session.add(
                        MemoryOutboxRow(
                            event_type="test.concurrent",
                            aggregate_type="test",
                            aggregate_id=aggregate_id,
                            aggregate_version=index + 1,
                            payload_json={},
                            status="pending",
                            workload_class="projection",
                            fairness_key=fairness_key,
                            attempt_count=0,
                            next_attempt_at=now,
                            created_at=now + timedelta(microseconds=index),
                            updated_at=now,
                        )
                    )
                await session.commit()
            worker = OutboxWorker(container)
            first = await worker._claim_pending(limit=3)  # noqa: SLF001
            async with AsyncSession(container.engine) as session:
                first_same = (
                    await session.execute(
                        select(MemoryOutboxRow).where(MemoryOutboxRow.aggregate_id == "same-key-1")
                    )
                ).scalar_one()
                first_same.status = "done"
                await session.commit()
            second = await worker._claim_pending(limit=3)  # noqa: SLF001
            return (
                [job.aggregate_id for job in first],
                [job.aggregate_id for job in second],
            )
        finally:
            await container.aclose()

    first, second = asyncio.run(run())

    assert first == ["same-key-1", "other-key"]
    assert second == ["same-key-2"]
