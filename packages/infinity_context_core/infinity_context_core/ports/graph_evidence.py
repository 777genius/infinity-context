"""Provider-neutral exact identity evidence for derived graph projections.

The port deliberately carries identities only. Provider text, entity names,
facts, embeddings, and credentials must never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.domain.errors import MemoryValidationError

_IDENTITY_FIELDS = (
    "episode_ids",
    "entity_ids",
    "mentions_edge_ids",
    "relates_to_edge_ids",
)


@dataclass(frozen=True, slots=True)
class GraphProjectionIdentitySnapshot:
    """Exact sorted identity inventory observed from one graph operation."""

    group_ids: tuple[str, ...] = ()
    episode_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    mentions_edge_ids: tuple[str, ...] = ()
    relates_to_edge_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("group_ids", *_IDENTITY_FIELDS):
            _validate_identity_tuple(getattr(self, field_name), field_name=field_name)
        identities = tuple(
            item for field_name in _IDENTITY_FIELDS for item in getattr(self, field_name)
        )
        if len(set(identities)) != len(identities):
            raise MemoryValidationError("Graph projection identities must be globally unique")
        if bool(self.group_ids) != bool(identities):
            raise MemoryValidationError(
                "Graph projection group presence must match identity presence"
            )

    @property
    def identity_count(self) -> int:
        """Return physical node and relationship identity cardinality."""

        return sum(len(getattr(self, field_name)) for field_name in _IDENTITY_FIELDS)

    @property
    def node_ids(self) -> tuple[str, ...]:
        return (*self.episode_ids, *self.entity_ids)

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return (*self.mentions_edge_ids, *self.relates_to_edge_ids)

    @property
    def empty(self) -> bool:
        return self.identity_count == 0


@dataclass(frozen=True, slots=True)
class GraphProjectionDeletePass:
    """Identity-only evidence from one transactional delete and both readbacks."""

    pass_index: int
    before: GraphProjectionIdentitySnapshot
    deleted: GraphProjectionIdentitySnapshot
    group_readback: GraphProjectionIdentitySnapshot
    global_readback: GraphProjectionIdentitySnapshot

    def __post_init__(self) -> None:
        if type(self.pass_index) is not int or self.pass_index not in (1, 2):
            raise MemoryValidationError("Graph projection delete pass index is invalid")
        for field_name in ("before", "deleted", "group_readback", "global_readback"):
            if type(getattr(self, field_name)) is not GraphProjectionIdentitySnapshot:
                raise MemoryValidationError(
                    f"Graph projection delete {field_name} snapshot is invalid"
                )


@dataclass(frozen=True, slots=True)
class GraphProjectionDeleteEvidence:
    """Successful two-pass group deletion with exact global and scoped absence."""

    group_id: str
    expected: GraphProjectionIdentitySnapshot
    first_pass: GraphProjectionDeletePass
    second_pass: GraphProjectionDeletePass

    def __post_init__(self) -> None:
        _validate_identifier(self.group_id, field_name="group_id")
        if type(self.expected) is not GraphProjectionIdentitySnapshot:
            raise MemoryValidationError("Graph projection delete expected snapshot is invalid")
        if (
            type(self.first_pass) is not GraphProjectionDeletePass
            or type(self.second_pass) is not GraphProjectionDeletePass
            or self.first_pass.pass_index != 1
            or self.second_pass.pass_index != 2
        ):
            raise MemoryValidationError("Graph projection delete pass coverage is invalid")
        empty = GraphProjectionIdentitySnapshot()
        if self.first_pass.before != self.expected or self.first_pass.deleted != self.expected:
            raise MemoryValidationError("First graph projection delete pass differs from expected")
        if self.first_pass.group_readback != empty or self.first_pass.global_readback != empty:
            raise MemoryValidationError("First graph projection delete pass is not absent")
        if (
            self.second_pass.before != empty
            or self.second_pass.deleted != empty
            or self.second_pass.group_readback != empty
            or self.second_pass.global_readback != empty
        ):
            raise MemoryValidationError("Second graph projection delete pass is not idempotent")

    @property
    def verified_absent(self) -> bool:
        return True


class GraphProjectionEvidencePort(Protocol):
    """Narrow exact-inventory and terminal-delete graph boundary."""

    async def inventory_group(
        self,
        group_id: str,
        *,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionIdentitySnapshot:
        """Enumerate one group and prove exact binding to the expected facts."""

    async def readback_identities(
        self,
        expected: GraphProjectionIdentitySnapshot,
    ) -> GraphProjectionIdentitySnapshot:
        """Read expected UUIDs globally, independent of their current group."""

    async def delete_group_two_pass(
        self,
        *,
        group_id: str,
        expected: GraphProjectionIdentitySnapshot,
        expected_fact_ids: tuple[str, ...],
    ) -> GraphProjectionDeleteEvidence:
        """Delete one manifest-bound group and prove scoped/global absence twice."""


def _validate_identity_tuple(value: object, *, field_name: str) -> None:
    if type(value) is not tuple:
        raise MemoryValidationError(f"Graph projection {field_name} must be a tuple")
    for item in value:
        _validate_identifier(item, field_name=field_name)
    if len(set(value)) != len(value):
        raise MemoryValidationError(f"Graph projection {field_name} cannot contain duplicates")
    if value != tuple(sorted(value)):
        raise MemoryValidationError(f"Graph projection {field_name} must be sorted")


def _validate_identifier(value: object, *, field_name: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise MemoryValidationError(f"Graph projection {field_name} contains an invalid identity")


__all__ = (
    "GraphProjectionDeleteEvidence",
    "GraphProjectionDeletePass",
    "GraphProjectionEvidencePort",
    "GraphProjectionIdentitySnapshot",
)
