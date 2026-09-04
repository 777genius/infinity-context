"""Fact lifecycle helpers for MemoryScope snapshot transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_adapters.postgres.models import MemoryFactRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.memory_scope_transfer_support import outbox


def fact_conflict_ids(
    *,
    facts: list[dict[str, Any]],
    conflict_ids: set[str],
) -> set[str]:
    return {str(item["id"]) for item in facts if str(item["id"]) in conflict_ids}


async def supersede_facts(
    session: AsyncSession,
    *,
    fact_ids: set[str],
    now: datetime,
    expected_versions: dict[str, int] | None = None,
) -> None:
    if not fact_ids:
        return
    rows = (
        await session.execute(
            select(MemoryFactRow)
            .where(MemoryFactRow.id.in_(fact_ids), MemoryFactRow.status == "active")
            .order_by(MemoryFactRow.thread_id.asc().nulls_first(), MemoryFactRow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars()
    rows = tuple(rows)
    if expected_versions is not None and (
        {row.id for row in rows} != set(expected_versions)
        or any(row.version != expected_versions[row.id] for row in rows)
    ):
        raise ValueError("Snapshot import fact changed during source coordination")
    for row in rows:
        row.status = "superseded"
        row.version += 1
        row.updated_at = now


def enqueue_fact_graph_upserts(
    session: AsyncSession,
    *,
    facts: list[dict[str, Any]],
    skipped_fact_ids: set[str],
    fact_id_map: dict[str, str],
    now: datetime,
) -> None:
    for fact in facts:
        if str(fact["id"]) in skipped_fact_ids or str(fact.get("status", "active")) != "active":
            continue
        mapped_fact_id = fact_id_map.get(str(fact["id"]), str(fact["id"]))
        session.add(
            outbox(
                event_type="graph.upsert_fact",
                aggregate_type="fact",
                aggregate_id=mapped_fact_id,
                aggregate_version=int(fact.get("version", 1)),
                now=now,
                payload={"fact_id": mapped_fact_id},
            )
        )
