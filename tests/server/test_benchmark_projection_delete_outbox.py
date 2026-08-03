import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, create_schema
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server.benchmark_projection_delete_outbox import (
    SealedBenchmarkDeleteScope,
    load_exact_projection_delete_events,
)
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RUN = "a" * 64
SPACE_ID = "benchmark-space"


def test_exact_delete_outbox_query_is_bounded_by_receipt_ids() -> None:
    source = inspect.getsource(load_exact_projection_delete_events)

    assert "MemoryOutboxRow.id.in_(exact_outbox_ids)" in source
    assert ".limit(" not in source
    assert "MemoryOutboxRow.event_type ==" not in source


@pytest.mark.parametrize(
    ("outbox_id", "event_type", "message"),
    [
        (999, None, "incomplete"),
        (1, "graph.delete_fact", "conflicted"),
    ],
)
def test_exact_delete_outbox_rejects_forged_or_wrong_event(
    tmp_path: Path,
    outbox_id: int,
    event_type: str | None,
    message: str,
) -> None:
    asyncio.run(
        _forged_or_wrong_event_contract(
            tmp_path,
            outbox_id=outbox_id,
            event_type=event_type,
            message=message,
        )
    )


async def _forged_or_wrong_event_contract(
    tmp_path: Path,
    *,
    outbox_id: int,
    event_type: str | None,
    message: str,
) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'exact-outbox.db'}")
    await create_schema(engine)
    sealed = _sealed_scope()
    try:
        async with AsyncSession(engine) as session:
            if event_type is not None:
                session.add(_outbox(event_type))
                await session.commit()
            with pytest.raises(MemoryConflictError, match=message):
                await load_exact_projection_delete_events(
                    session,
                    event_type="vector.delete_chunks",
                    expected_ids=("chunk-1",),
                    exact_outbox_ids=(outbox_id,),
                    space_id=SPACE_ID,
                    sealed_scope=sealed,
                )
    finally:
        await engine.dispose()


def test_empty_exact_graph_lane_is_valid_without_query() -> None:
    result = asyncio.run(
        load_exact_projection_delete_events(
            _NeverExecuteSession(),
            event_type="graph.delete_fact",
            expected_ids=("fact-1",),
            exact_outbox_ids=(),
            space_id=SPACE_ID,
            sealed_scope=SealedBenchmarkDeleteScope(
                manifest_scope={},
                run_id_sha256=RUN,
                all_chunk_ids=("chunk-1",),
                all_fact_ids=("fact-1",),
            ),
        )
    )

    assert result == []


class _NeverExecuteSession:
    async def execute(self, _statement: object) -> object:
        raise AssertionError("empty exact graph lane must not query the global outbox")


def _sealed_scope() -> SealedBenchmarkDeleteScope:
    return SealedBenchmarkDeleteScope(
        manifest_scope={},
        run_id_sha256=RUN,
        all_chunk_ids=("chunk-1",),
        all_fact_ids=(),
    )


def _outbox(event_type: str) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        id=1,
        event_type=event_type,
        aggregate_type="benchmark_run",
        aggregate_id=RUN,
        aggregate_version=None,
        workload_class="projection",
        fairness_key=f"benchmark_cleanup:{SPACE_ID}",
        payload_json={
            "chunk_ids": ["chunk-1"],
            "space_id": SPACE_ID,
            "cleanup_run_id_sha256": RUN,
        },
        status="done",
        attempt_count=1,
        next_attempt_at=NOW,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=NOW,
        updated_at=NOW,
    )
