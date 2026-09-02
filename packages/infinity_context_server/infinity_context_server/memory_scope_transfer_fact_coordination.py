"""Coordinate canonical fact mutations during snapshot import."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from infinity_context_adapters.postgres.document_source_ref_coordination import (
    coordinate_document_source_ref_batches,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRow,
    MemorySourceRefRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server import memory_scope_transfer_facts as _facts
from infinity_context_server import memory_scope_transfer_records as _records
from infinity_context_server import memory_scope_transfer_remap as _remap
from infinity_context_server import memory_scope_transfer_support as _support


async def coordinate_and_stage_imported_facts(
    session: AsyncSession,
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
    mapped_facts: list[dict[str, Any]],
    imported_fact_versions: dict[str, int],
    source_refs: list[dict[str, Any]],
    skipped_fact_ids: set[str],
    fact_id_map: dict[str, str],
    chunk_id_map: dict[str, str],
    document_id_map: dict[str, str],
    extraction_job_id_map: dict[str, str],
    superseded_fact_ids: set[str],
) -> list[MemorySourceRefRow]:
    """Validate a complete remapped batch before staging any fact mutation."""

    mapped_source_ref_rows: list[MemorySourceRefRow] = []
    refs_by_fact_id: dict[str, list[MemorySourceRefRow]] = {}
    for ref in source_refs:
        if str(ref["fact_id"]) in skipped_fact_ids:
            continue
        mapped_ref = _remap.remap_source_ref(
            ref,
            fact_id_map=fact_id_map,
            chunk_id_map=chunk_id_map,
            document_id_map=document_id_map,
            extraction_job_id_map=extraction_job_id_map,
        )
        mapped_fact_id = str(mapped_ref["fact_id"])
        if mapped_fact_id not in imported_fact_versions:
            continue
        row = _records.source_ref_from_json(mapped_ref)
        mapped_source_ref_rows.append(row)
        refs_by_fact_id.setdefault(mapped_fact_id, []).append(row)

    batches: list[tuple[str | None, tuple[MemorySourceRefRow, ...]]] = [
        (
            str(fact["thread_id"]) if fact.get("thread_id") is not None else None,
            tuple(refs_by_fact_id.get(str(fact["id"]), ())),
        )
        for fact in mapped_facts
    ]
    expected_versions: dict[str, int] = {}
    if superseded_fact_ids:
        existing_rows = tuple(
            (
                await session.execute(
                    select(MemoryFactRow).where(
                        MemoryFactRow.id.in_(superseded_fact_ids),
                        MemoryFactRow.status == "active",
                    )
                )
            ).scalars()
        )
        expected_versions = {row.id: row.version for row in existing_rows}
        existing_refs = tuple(
            (
                await session.execute(
                    select(MemorySourceRefRow).where(
                        MemorySourceRefRow.fact_id.in_(superseded_fact_ids),
                        MemorySourceRefRow.fact_version.in_(
                            tuple(row.version for row in existing_rows)
                        ),
                    )
                )
            ).scalars()
        )
        for row in existing_rows:
            batches.append(
                (
                    row.thread_id,
                    tuple(
                        ref
                        for ref in existing_refs
                        if ref.fact_id == row.id and ref.fact_version == row.version
                    ),
                )
            )
    await coordinate_document_source_ref_batches(
        session,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        batches=batches,
    )
    for fact in mapped_facts:
        session.add(
            _records.fact_from_json(
                fact,
                space_id=space_id,
                memory_scope_id=memory_scope_id,
                now=now,
            )
        )
    if superseded_fact_ids:
        await _facts.supersede_facts(
            session,
            fact_ids=superseded_fact_ids,
            now=now,
            expected_versions=expected_versions,
        )
        for fact_id in superseded_fact_ids:
            session.add(
                _support.outbox(
                    event_type="graph.delete_fact",
                    aggregate_type="fact",
                    aggregate_id=fact_id,
                    now=now,
                    payload={"fact_id": fact_id},
                )
            )
    return mapped_source_ref_rows


__all__ = ("coordinate_and_stage_imported_facts",)
