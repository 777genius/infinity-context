"""Relation helpers for profile snapshot transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memo_stack_adapters.postgres.models import MemoryFactRelationRow


def relation_to_json(row: MemoryFactRelationRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_fact_id": row.source_fact_id,
        "target_fact_id": row.target_fact_id,
        "relation_type": row.relation_type,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def relation_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    profile_id: str,
    now: datetime,
) -> MemoryFactRelationRow:
    return MemoryFactRelationRow(
        id=str(item["id"]),
        space_id=space_id,
        profile_id=profile_id,
        source_fact_id=str(item["source_fact_id"]),
        target_fact_id=str(item["target_fact_id"]),
        relation_type=str(item.get("relation_type", "related_to")),
        reason=str(item.get("reason") or "imported profile snapshot relation")[:320],
        status=str(item.get("status", "active")),
        created_at=_parse_dt(item.get("created_at"), now),
        updated_at=_parse_dt(item.get("updated_at"), now),
    )


def remap_relation(
    item: dict[str, Any],
    *,
    fact_id_map: dict[str, str],
    relation_id_map: dict[str, str],
) -> dict[str, Any]:
    relation_id = str(item["id"])
    source_fact_id = str(item["source_fact_id"])
    target_fact_id = str(item["target_fact_id"])
    return {
        **item,
        "id": relation_id_map.get(relation_id, relation_id),
        "source_fact_id": fact_id_map.get(source_fact_id, source_fact_id),
        "target_fact_id": fact_id_map.get(target_fact_id, target_fact_id),
    }


def _parse_dt(value: object, fallback: datetime) -> datetime:
    if not value:
        return fallback
    return datetime.fromisoformat(str(value))
