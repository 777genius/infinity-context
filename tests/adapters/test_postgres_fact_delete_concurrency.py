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
    session = _CandidateSession(
        (
            _Candidate("fact-a", "space-a", "scope-a", "thread-z"),
            _Candidate("fact-b", "space-a", "scope-a", "thread-a"),
            _Candidate("fact-c", "space-a", "scope-a", None),
        )
    )
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

    assert repository.locked_ids == ["fact-c", "fact-b", "fact-a"]
    assert deleted == (("fact-b", 3),)
    assert [(str(fact.id), fact.version, fact.status) for fact in repository.saved] == [
        ("fact-b", 3, FactStatus.DELETED)
    ]
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "SELECT DISTINCT memory_facts.id" in sql
    assert "memory_facts.thread_id" in sql
    assert "ORDER BY" not in sql
    assert "FOR UPDATE" not in sql


class _Candidate:
    def __init__(
        self,
        fact_id: str,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
    ) -> None:
        self.id = fact_id
        self.space_id = space_id
        self.memory_scope_id = memory_scope_id
        self.thread_id = thread_id


class _CandidateRows:
    def __init__(self, rows: tuple[_Candidate, ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[_Candidate, ...]:
        return self._rows


class _CandidateSession:
    def __init__(self, rows: tuple[_Candidate, ...]) -> None:
        self._rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _CandidateRows(self._rows)


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
