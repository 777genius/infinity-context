"""Concurrency policy tests for document-sourced fact deletion."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from infinity_context_adapters.postgres.fact_repositories import PostgresFactRepository
from infinity_context_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def test_document_fact_delete_reloads_locked_current_versions_before_deciding() -> None:
    asyncio.run(_assert_locked_current_versions_drive_document_fact_delete())


async def _assert_locked_current_versions_drive_document_fact_delete() -> None:
    moved = _fact("fact-a", SourceRef(source_type="manual", source_id="survives"))
    still_sourced = _fact(
        "fact-b",
        SourceRef(source_type="document", source_id="document-a", chunk_id="chunk-a"),
    )
    superseded = replace(
        _fact(
            "fact-c",
            SourceRef(source_type="document", source_id="document-a", chunk_id="chunk-a"),
        ),
        status=FactStatus.SUPERSEDED,
    )
    session = _CandidateSession(("fact-a", "fact-b", "fact-c"))
    repository = _RaceRepository(
        cast(AsyncSession, session),
        locked={"fact-a": moved, "fact-b": still_sourced, "fact-c": superseded},
    )

    deleted = await repository.delete_facts_sourced_only_by_chunks(
        space_id="space-a",
        memory_scope_id="scope-a",
        document_id="document-a",
        chunk_ids=("chunk-a",),
        now=NOW,
    )

    assert repository.locked_ids == ["fact-a", "fact-b", "fact-c"]
    assert deleted == (("fact-b", 3),)
    assert [(str(fact.id), fact.version, fact.status) for fact in repository.saved] == [
        ("fact-b", 3, FactStatus.DELETED)
    ]
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "SELECT DISTINCT memory_facts.id" in sql
    assert "ORDER BY memory_facts.id" in sql
    assert "FOR UPDATE" not in sql


class _CandidateScalars:
    def __init__(self, fact_ids: tuple[str, ...]) -> None:
        self._fact_ids = fact_ids

    def scalars(self) -> tuple[str, ...]:
        return self._fact_ids


class _CandidateSession:
    def __init__(self, fact_ids: tuple[str, ...]) -> None:
        self._fact_ids = fact_ids
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _CandidateScalars(self._fact_ids)


class _RaceRepository(PostgresFactRepository):
    def __init__(self, session: AsyncSession, *, locked: dict[str, MemoryFact]) -> None:
        super().__init__(session, now=NOW)
        self._locked = locked
        self.locked_ids: list[str] = []
        self.saved: list[MemoryFact] = []

    async def get_for_update(self, fact_id: str) -> MemoryFact | None:
        self.locked_ids.append(fact_id)
        return self._locked.get(fact_id)

    async def save(self, fact: MemoryFact) -> MemoryFact:
        self.saved.append(fact)
        return fact


def _fact(fact_id: str, ref: SourceRef) -> MemoryFact:
    created = MemoryFact.create(
        fact_id=MemoryFactId(fact_id),
        space_id=SpaceId("space-a"),
        memory_scope_id=MemoryScopeId("scope-a"),
        text=f"Fact {fact_id}",
        kind=MemoryKind.NOTE,
        source_refs=(ref,),
        now=NOW,
    )
    return replace(created, version=2)
