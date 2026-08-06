"""Administrative canonical fact reads, distinct from prompt eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from infinity_context_core.features.memory_facts.domain import MemoryFactSnapshot


@dataclass(frozen=True, slots=True)
class MemoryFactListSpec:
    space_id: str
    memory_scope_id: str
    thread_id: str | None
    status: str | None
    limit: int
    cursor_updated_at: datetime | None = None
    cursor_id: str | None = None
    category: str | None = None
    tag: str | None = None
    repository_id: str | None = None
    code_scope_id: str | None = None
    restrict_to_repository_visibility: bool = False

    def __post_init__(self) -> None:
        if not self.space_id.strip() or not self.memory_scope_id.strip():
            raise ValueError("Fact list scope cannot be blank")
        if self.limit < 1:
            raise ValueError("Fact list limit must be positive")
        if (self.cursor_updated_at is None) != (self.cursor_id is None):
            raise ValueError("Fact list cursor fields must be provided together")
        if self.code_scope_id is not None and self.repository_id is None:
            raise ValueError("Fact list code scope requires repository")


class MemoryFactReadModelPort(Protocol):
    async def get_by_id(self, fact_id: str) -> MemoryFactSnapshot | None: ...

    async def get_many_by_ids(
        self,
        fact_ids: tuple[str, ...],
    ) -> tuple[MemoryFactSnapshot, ...]: ...

    async def list_for_scope(
        self,
        spec: MemoryFactListSpec,
    ) -> tuple[MemoryFactSnapshot, ...]: ...

    async def list_versions_by_id(
        self,
        fact_id: str,
    ) -> tuple[MemoryFactSnapshot, ...]: ...


__all__ = ("MemoryFactListSpec", "MemoryFactReadModelPort")
