"""Shared SQL predicates for canonical MemoryFact visibility and isolation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_

from infinity_context_adapters.postgres.models import MemoryFactRow


def memory_fact_code_scope_conditions(
    row_type: type[MemoryFactRow],
    *,
    repository_id: str | None,
    code_scope_id: str | None,
) -> tuple[object, ...]:
    """Return canonical global-plus-project visibility predicates."""

    if repository_id is None:
        return (row_type.repository_id.is_(None), row_type.code_scope_id.is_(None))
    conditions: list[object] = [
        or_(row_type.repository_id.is_(None), row_type.repository_id == repository_id)
    ]
    if code_scope_id is None:
        conditions.append(row_type.code_scope_id.is_(None))
    else:
        conditions.append(
            or_(row_type.code_scope_id.is_(None), row_type.code_scope_id == code_scope_id)
        )
    return tuple(conditions)


def memory_fact_selection_conditions(
    *,
    space_id: str,
    memory_scope_ids: tuple[str, ...],
    thread_id: str | None,
    repository_id: str | None,
    code_scope_id: str | None,
    temporal_mode: str,
    reference_time: datetime,
    fact_ids: tuple[str, ...] = (),
) -> tuple[object, ...]:
    """Build the one canonical SQL eligibility predicate used before ranking."""

    conditions: list[object] = [
        MemoryFactRow.space_id == space_id,
        MemoryFactRow.memory_scope_id.in_(memory_scope_ids),
        MemoryFactRow.classification.in_(("public", "internal")),
    ]
    if fact_ids:
        conditions.append(MemoryFactRow.id.in_(fact_ids))
    if thread_id is None:
        conditions.append(MemoryFactRow.thread_id.is_(None))
    else:
        conditions.append(
            or_(MemoryFactRow.thread_id.is_(None), MemoryFactRow.thread_id == thread_id)
        )
    conditions.extend(
        memory_fact_code_scope_conditions(
            MemoryFactRow,
            repository_id=repository_id,
            code_scope_id=code_scope_id,
        )
    )
    if temporal_mode == "history":
        return tuple(conditions)

    allowed_statuses = ("active", "superseded") if temporal_mode == "as_of" else ("active",)
    conditions.extend(
        (
            MemoryFactRow.status.in_(allowed_statuses),
            or_(
                MemoryFactRow.expires_at.is_(None),
                MemoryFactRow.expires_at > reference_time,
            ),
            or_(
                and_(
                    MemoryFactRow.temporal_kind == "state",
                    MemoryFactRow.valid_from.is_not(None),
                    MemoryFactRow.valid_from <= reference_time,
                    or_(
                        MemoryFactRow.valid_to.is_(None),
                        MemoryFactRow.valid_to > reference_time,
                    ),
                ),
                and_(
                    MemoryFactRow.temporal_kind.is_(None),
                    MemoryFactRow.created_at <= reference_time,
                ),
                MemoryFactRow.temporal_kind == "timeless",
                and_(
                    MemoryFactRow.temporal_kind == "event",
                    MemoryFactRow.occurred_from.is_not(None),
                    MemoryFactRow.occurred_from <= reference_time,
                ),
            ),
        )
    )
    return tuple(conditions)


__all__ = ("memory_fact_code_scope_conditions", "memory_fact_selection_conditions")
