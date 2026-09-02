"""Focused transaction gates for live document/fact source-reference races."""

from __future__ import annotations

import asyncio
from datetime import datetime

from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactUnitOfWork,
)
from infinity_context_adapters.postgres.unit_of_work import PostgresUnitOfWork
from sqlalchemy import text


async def active_facts_solely_backed_by_document(session, *, document_id: str) -> int:
    return int(
        await session.scalar(
            text(
                """
                SELECT count(*)
                FROM memory_facts fact
                WHERE fact.status = 'active'
                  AND EXISTS (
                    SELECT 1
                    FROM memory_source_refs ref
                    WHERE ref.fact_id = fact.id
                      AND ref.fact_version = fact.version
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM memory_source_refs ref
                    WHERE ref.fact_id = fact.id
                      AND ref.fact_version = fact.version
                      AND NOT (
                        (ref.source_type = 'document' AND ref.source_id = :document_id)
                        OR ref.chunk_id IN (
                          SELECT chunk.id
                          FROM memory_chunks chunk
                          WHERE chunk.document_id = :document_id
                        )
                      )
                  )
                """
            ),
            {"document_id": document_id},
        )
        or 0
    )


class AdmissionGateDocumentRepository:
    def __init__(self, inner, *, admitted: asyncio.Event, release: asyncio.Event) -> None:
        self._inner = inner
        self._admitted = admitted
        self._release = release

    async def soft_delete_with_chunks(self, **kwargs):
        result = await self._inner.soft_delete_with_chunks(**kwargs)
        self._admitted.set()
        await self._release.wait()
        return result


class AdmissionGateUnitOfWork(PostgresUnitOfWork):
    def __init__(self, *, admitted: asyncio.Event, release: asyncio.Event, **kwargs) -> None:
        super().__init__(**kwargs)
        self._admitted = admitted
        self._release = release

    async def __aenter__(self):
        entered = await super().__aenter__()
        self.documents = AdmissionGateDocumentRepository(
            self.documents,
            admitted=self._admitted,
            release=self._release,
        )
        return entered


class AdmissionGateUnitOfWorkFactory:
    def __init__(self, *, session_factory, clock, admitted, release) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._admitted = admitted
        self._release = release

    def __call__(self) -> AdmissionGateUnitOfWork:
        return AdmissionGateUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            admitted=self._admitted,
            release=self._release,
        )


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class CanonicalIds:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._next = 0

    def _id(self, kind: str) -> str:
        self._next += 1
        return f"{self._prefix}-{kind}-{self._next}"

    def new_fact_id(self) -> str:
        return self._id("fact")

    def new_outbox_message_id(self) -> str:
        return self._id("outbox")

    def new_tombstone_id(self) -> str:
        return self._id("tombstone")

    def new_temporal_decision_id(self) -> str:
        return self._id("decision")

    def new_fact_relation_id(self) -> str:
        return self._id("relation")


class TrackingCanonicalUnitOfWork(PostgresMemoryFactUnitOfWork):
    def __init__(self, *, pid_ready: asyncio.Event, pid: list[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self._pid_ready = pid_ready
        self._pid = pid

    async def __aenter__(self):
        entered = await super().__aenter__()
        assert self._session is not None
        backend_pid = await self._session.scalar(text("SELECT pg_backend_pid()"))
        assert backend_pid is not None
        self._pid.append(backend_pid)
        self._pid_ready.set()
        return entered


class TrackingCanonicalUnitOfWorkFactory:
    def __init__(self, *, session_factory, clock, pid_ready, pid) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._pid_ready = pid_ready
        self._pid = pid

    def __call__(self) -> TrackingCanonicalUnitOfWork:
        return TrackingCanonicalUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            pid_ready=self._pid_ready,
            pid=self._pid,
        )


__all__ = (
    "AdmissionGateUnitOfWorkFactory",
    "CanonicalIds",
    "FixedClock",
    "TrackingCanonicalUnitOfWorkFactory",
    "active_facts_solely_backed_by_document",
)
