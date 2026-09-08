"""Generic relation policy over canonical facts; temporal decisions stay separate."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from infinity_context_core.features.memory_facts.domain.fact import MemoryFactSnapshot


class FactRelationType(StrEnum):
    SUPPORTS = "supports"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DUPLICATES = "duplicates"
    REFERENCES = "references"
    DEPENDS_ON = "depends_on"
    RELATED_TO = "related_to"


class FactRelationStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class FactRelationConflict(ValueError):
    """A valid request conflicts with canonical relation or fact state."""


@dataclass(frozen=True, slots=True)
class FactRelationSnapshot:
    relation_id: str
    space_id: str
    memory_scope_id: str
    source_fact_id: str
    target_fact_id: str
    relation_type: FactRelationType
    reason: str
    status: FactRelationStatus
    observed_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        relation_id: str,
        source: MemoryFactSnapshot,
        target: MemoryFactSnapshot,
        relation_type: FactRelationType,
        reason: str,
        now: datetime,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> FactRelationSnapshot:
        require_generic_relation_type(relation_type)
        require_linkable_facts(source, target)
        if source.identity.fact_id == target.identity.fact_id:
            raise ValueError("Fact relation requires two distinct facts")
        if not reason.strip():
            raise ValueError("Fact relation reason is required")
        if valid_from is not None and valid_to is not None:
            start, end = comparable_datetimes(valid_from, valid_to)
            if end <= start:
                raise ValueError("Temporal valid_to must be after valid_from")
        return cls(
            relation_id=relation_id,
            space_id=source.identity.scope.space_id,
            memory_scope_id=source.identity.scope.memory_scope_id,
            source_fact_id=source.identity.fact_id,
            target_fact_id=target.identity.fact_id,
            relation_type=FactRelationType(relation_type),
            reason=reason.strip(),
            status=FactRelationStatus.ACTIVE,
            observed_at=observed_at or now,
            valid_from=valid_from,
            valid_to=valid_to,
            created_at=now,
            updated_at=now,
        )

    def delete(self, *, now: datetime) -> FactRelationSnapshot:
        if self.relation_type == FactRelationType.SUPERSEDES:
            raise ValueError("Supersession relations are immutable; use a compensating decision")
        if self.status == FactRelationStatus.DELETED:
            return self
        return replace(self, status=FactRelationStatus.DELETED, updated_at=now)

    def require_temporal_replay(
        self,
        *,
        observed_at: datetime | None,
        valid_from: datetime | None,
        valid_to: datetime | None,
    ) -> None:
        mismatches = [
            name
            for name, existing, requested in (
                ("observed_at", self.observed_at, observed_at),
                ("valid_from", self.valid_from, valid_from),
                ("valid_to", self.valid_to, valid_to),
            )
            if requested is not None
            and (existing is None or not _datetime_equal(existing, requested))
        ]
        if mismatches:
            raise FactRelationConflict(
                "Active fact relation already exists with different temporal fields: "
                + ", ".join(mismatches)
            )


def require_generic_relation_type(value: FactRelationType | str) -> FactRelationType:
    try:
        relation_type = FactRelationType(value)
    except ValueError as exc:
        raise ValueError("Unknown fact relation type") from exc
    if relation_type in {FactRelationType.SUPERSEDES, FactRelationType.CONTRADICTS}:
        raise ValueError("Temporal relations require the audited supersede or dispute use case")
    return relation_type


def require_linkable_facts(source: MemoryFactSnapshot, target: MemoryFactSnapshot) -> None:
    source_scope, target_scope = source.identity.scope, target.identity.scope
    # Threads may differ: legacy generic relations belong to a memory scope.
    if (source_scope.space_id, source_scope.memory_scope_id) != (
        target_scope.space_id,
        target_scope.memory_scope_id,
    ):
        raise FactRelationConflict("Fact relations cannot cross memory_scope boundaries")
    if any(fact.visibility.status == "deleted" for fact in (source, target)):
        raise FactRelationConflict("Deleted facts cannot be linked")
    if any(fact.visibility.classification == "restricted" for fact in (source, target)):
        raise FactRelationConflict("Restricted facts cannot be linked")


def comparable_datetimes(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    """Preserve legacy naive timestamp compatibility at the relation boundary."""
    if left.tzinfo is None and right.tzinfo is not None:
        left = left.replace(tzinfo=right.tzinfo)
    elif left.tzinfo is not None and right.tzinfo is None:
        right = right.replace(tzinfo=left.tzinfo)
    return left, right


def _datetime_equal(left: datetime, right: datetime) -> bool:
    left, right = comparable_datetimes(left, right)
    return left == right
