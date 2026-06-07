"""Conflict detection for profile snapshot imports."""

from __future__ import annotations

from typing import Any

from memo_stack_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRelationRow,
    MemoryFactRow,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def profile_snapshot_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    facts: list[dict[str, Any]],
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> list[str]:
    conflicts: list[str] = []
    fact_ids = [str(item["id"]) for item in facts]
    document_ids = [str(item["id"]) for item in documents]
    chunk_ids = [str(item["id"]) for item in chunks]
    relation_ids = [str(item["id"]) for item in relations]
    for model, ids in (
        (MemoryFactRow, fact_ids),
        (MemoryDocumentRow, document_ids),
        (MemoryChunkRow, chunk_ids),
        (MemoryFactRelationRow, relation_ids),
    ):
        if not ids:
            continue
        result = await session.execute(select(model.id).where(model.id.in_(ids)))
        conflicts.extend(str(row_id) for row_id in result.scalars())
    conflicts.extend(
        await _document_hash_conflicts(
            session,
            space_id=space_id,
            profile_id=profile_id,
            documents=documents,
        )
    )
    conflicts.extend(
        await _chunk_hash_conflicts(
            session,
            space_id=space_id,
            profile_id=profile_id,
            chunks=chunks,
        )
    )
    conflicts.extend(
        await _relation_signature_conflicts(
            session,
            space_id=space_id,
            profile_id=profile_id,
            relations=relations,
        )
    )
    return sorted(set(conflicts))


async def _document_hash_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    documents: list[dict[str, Any]],
) -> list[str]:
    by_hash = {
        str(item.get("content_hash")): str(item["id"])
        for item in documents
        if item.get("content_hash")
    }
    if not by_hash:
        return []
    rows = (
        await session.execute(
            select(MemoryDocumentRow.id, MemoryDocumentRow.content_hash).where(
                MemoryDocumentRow.space_id == space_id,
                MemoryDocumentRow.profile_id == profile_id,
                MemoryDocumentRow.status != "deleted",
                MemoryDocumentRow.content_hash.in_(by_hash),
            )
        )
    ).all()
    return [
        by_hash[str(content_hash)]
        for row_id, content_hash in rows
        if str(row_id) != by_hash[str(content_hash)]
    ]


async def _chunk_hash_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    chunks: list[dict[str, Any]],
) -> list[str]:
    by_hash = {
        str(item.get("source_hash")): str(item["id"]) for item in chunks if item.get("source_hash")
    }
    if not by_hash:
        return []
    rows = (
        await session.execute(
            select(MemoryChunkRow.id, MemoryChunkRow.source_hash).where(
                MemoryChunkRow.space_id == space_id,
                MemoryChunkRow.profile_id == profile_id,
                MemoryChunkRow.status != "deleted",
                MemoryChunkRow.source_hash.in_(by_hash),
            )
        )
    ).all()
    return [
        by_hash[str(source_hash)]
        for row_id, source_hash in rows
        if str(row_id) != by_hash[str(source_hash)]
    ]


async def _relation_signature_conflicts(
    session: AsyncSession,
    *,
    space_id: str,
    profile_id: str,
    relations: list[dict[str, Any]],
) -> list[str]:
    by_signature = {
        (
            str(item.get("source_fact_id")),
            str(item.get("target_fact_id")),
            str(item.get("relation_type", "related_to")),
        ): str(item["id"])
        for item in relations
        if item.get("source_fact_id") and item.get("target_fact_id")
    }
    if not by_signature:
        return []
    rows = (
        await session.execute(
            select(
                MemoryFactRelationRow.id,
                MemoryFactRelationRow.source_fact_id,
                MemoryFactRelationRow.target_fact_id,
                MemoryFactRelationRow.relation_type,
            ).where(
                MemoryFactRelationRow.space_id == space_id,
                MemoryFactRelationRow.profile_id == profile_id,
                MemoryFactRelationRow.status == "active",
                MemoryFactRelationRow.relation_type.in_(
                    {signature[2] for signature in by_signature}
                ),
            )
        )
    ).all()
    conflicts: list[str] = []
    for row_id, source_fact_id, target_fact_id, relation_type in rows:
        snapshot_id = by_signature.get((source_fact_id, target_fact_id, relation_type))
        if snapshot_id is not None and str(row_id) != snapshot_id:
            conflicts.append(snapshot_id)
    return conflicts
