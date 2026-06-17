"""Relation helpers for memory_scope snapshot transfer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memo_stack_adapters.postgres.models import MemoryFactRelationRow


def relation_to_json(row: MemoryFactRelationRow) -> dict[str, Any]:
    observed_at = row.observed_at or row.created_at
    return {
        "id": row.id,
        "source_fact_id": row.source_fact_id,
        "target_fact_id": row.target_fact_id,
        "relation_type": row.relation_type,
        "reason": row.reason,
        "status": row.status,
        "observed_at": observed_at.isoformat(),
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def relation_from_json(
    item: dict[str, Any],
    *,
    space_id: str,
    memory_scope_id: str,
    now: datetime,
) -> MemoryFactRelationRow:
    created_at = _parse_dt(item.get("created_at"), now)
    return MemoryFactRelationRow(
        id=str(item["id"]),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        source_fact_id=str(item["source_fact_id"]),
        target_fact_id=str(item["target_fact_id"]),
        relation_type=str(item.get("relation_type", "related_to")),
        reason=str(item.get("reason") or "imported memory_scope snapshot relation")[:320],
        status=str(item.get("status", "active")),
        observed_at=_parse_dt(item.get("observed_at"), created_at),
        valid_from=_parse_optional_dt(item.get("valid_from")),
        valid_to=_parse_optional_dt(item.get("valid_to")),
        created_at=created_at,
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


def _parse_optional_dt(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))
