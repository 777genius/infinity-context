"""Live PostgreSQL proof for reinstatement observation revalidation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest
from document_fact_source_ref_race_support import CanonicalIds, FixedClock
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactUnitOfWork,
    PostgresMemoryFactUnitOfWorkFactory,
)
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryFactRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWork,
    build_session_factory,
)
from infinity_context_core.application.dto import UpdateFactCommand
from infinity_context_core.application.use_cases.update_fact import UpdateFactUseCase
from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.features.memory_facts.public import (
    FactTemporalExtent,
    MemoryFact,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSourceRef,
    ReinstateSupersededFactCommand,
    ReinstateSupersededFactHandler,
    SupersedeFactCommand,
    SupersedeFactHandler,
)
from postgres_test_database import PostgresTestDatabase
from sqlalchemy import select, text

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def test_reinstatement_serializes_legacy_version_and_ref_change() -> None:
    database_url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_reinstatement_revalidates(database_url))


async def _assert_reinstatement_revalidates(database_url: str) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(
        database_url,
        prefix="reinstate_legacy_update",
        asyncpg=asyncpg,
    )
    await database.recreate()
    engine = build_async_engine(database.app_url)
    release = asyncio.Event()
    reinstatement = update_task = None
    try:
        await upgrade_schema(engine)
        sessions = build_session_factory(engine)
        async with sessions.begin() as session:
            session.add(_document())
            await session.flush()
            session.add(_chunk())

        scope = MemoryFactScope("space-reinstate", "scope-reinstate", None)
        source_ref = MemoryFactSourceRef(
            source_type="document",
            source_id="document-reinstate",
            chunk_id="chunk-reinstate",
        )
        predecessor = _fact("fact-old", "Version one", scope, source_ref, NOW)
        successor = _fact(
            "fact-new",
            "Version two",
            scope,
            source_ref,
            NOW + timedelta(seconds=1),
        )
        canonical_clock = FixedClock(NOW + timedelta(seconds=1))
        canonical_factory = PostgresMemoryFactUnitOfWorkFactory(
            session_factory=sessions,
            clock=canonical_clock,
        )
        async with canonical_factory() as uow:
            await uow.coordinate_source_refs(scope=scope, source_refs=(source_ref,))
            await uow.facts.create(predecessor)
            await uow.facts.create(successor)
            await uow.commit()
        superseded = await SupersedeFactHandler(
            uow_factory=canonical_factory,
            clock=canonical_clock,
            ids=CanonicalIds("supersede"),
        ).execute(
            SupersedeFactCommand(
                successor_identity=successor.identity,
                predecessor_identity=predecessor.identity,
                expected_successor_version=1,
                expected_predecessor_version=1,
                effective_at=NOW + timedelta(seconds=1),
                evidence_refs=(MemoryFactEvidenceRef(source_ref=source_ref, evidence_id="accept"),),
                actor_id="reviewer",
                reason_code="accepted_replacement",
                idempotency_key="supersede-live",
            )
        )

        coordinated = asyncio.Event()
        reinstatement = asyncio.create_task(
            ReinstateSupersededFactHandler(
                uow_factory=_BarrierFactory(
                    session_factory=sessions,
                    clock=FixedClock(NOW + timedelta(seconds=3)),
                    coordinated=coordinated,
                    release=release,
                ),
                clock=FixedClock(NOW + timedelta(seconds=3)),
                ids=CanonicalIds("reinstate"),
            ).execute(
                ReinstateSupersededFactCommand(
                    scope=scope,
                    supersession_decision_id=superseded.decision.decision_id,
                    expected_rejected_successor_version=2,
                    expected_original_predecessor_version=2,
                    evidence_refs=(
                        MemoryFactEvidenceRef(source_ref=source_ref, evidence_id="reject"),
                    ),
                    actor_id="reviewer",
                    reason_code="replacement_rejected",
                    idempotency_key="reinstate-live",
                )
            )
        )
        await asyncio.wait_for(coordinated.wait(), timeout=3)
        update_pid_ready = asyncio.Event()
        update_pid: list[int] = []
        update_task = asyncio.create_task(
            UpdateFactUseCase(
                uow_factory=_TrackingUnitOfWorkFactory(
                    session_factory=sessions,
                    clock=FixedClock(NOW + timedelta(seconds=2)),
                    pid_ready=update_pid_ready,
                    pid=update_pid,
                ),
                clock=FixedClock(NOW + timedelta(seconds=2)),
            ).execute(
                UpdateFactCommand(
                    fact_id="fact-new",
                    expected_version=2,
                    text="Legacy update must lose after coordinated reinstatement.",
                    source_refs=(SourceRef("manual", "legacy-update"),),
                    reason="exercise reinstatement serialization",
                )
            )
        )
        await asyncio.wait_for(update_pid_ready.wait(), timeout=3)
        await _wait_for_advisory_lock(engine, update_pid[0])
        release.set()
        result = await asyncio.wait_for(reinstatement, timeout=5)
        reinstatement = None
        with pytest.raises(MemoryConflictError):
            await asyncio.wait_for(update_task, timeout=5)
        update_task = None

        async with sessions() as session:
            rows = tuple(
                (await session.execute(select(MemoryFactRow).order_by(MemoryFactRow.id))).scalars()
            )
        by_id = {row.id: row for row in rows}
        assert (by_id["fact-new"].status, by_id["fact-new"].version) == (
            "superseded",
            3,
        )
        assert (by_id["fact-old"].status, by_id["fact-old"].version) == (
            "superseded",
            2,
        )
        reinstated_id = result.reinstated_fact.identity.fact_id
        assert (by_id[reinstated_id].status, by_id[reinstated_id].version) == (
            "active",
            1,
        )
    finally:
        release.set()
        for task in (reinstatement, update_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (reinstatement, update_task) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()
        await database.drop()


class _BarrierUnitOfWork(PostgresMemoryFactUnitOfWork):
    def __init__(self, *, coordinated, release, **kwargs) -> None:
        super().__init__(**kwargs)
        self._coordinated = coordinated
        self._release = release

    async def coordinate_source_refs(self, *, scope, source_refs) -> None:
        await super().coordinate_source_refs(scope=scope, source_refs=source_refs)
        self._coordinated.set()
        await self._release.wait()


class _BarrierFactory:
    def __init__(self, *, session_factory, clock, coordinated, release) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._coordinated = coordinated
        self._release = release

    def __call__(self) -> _BarrierUnitOfWork:
        return _BarrierUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            coordinated=self._coordinated,
            release=self._release,
        )


class _TrackingUnitOfWork(PostgresUnitOfWork):
    def __init__(self, *, pid_ready, pid, **kwargs) -> None:
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


class _TrackingUnitOfWorkFactory:
    def __init__(self, *, session_factory, clock, pid_ready, pid) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._pid_ready = pid_ready
        self._pid = pid

    def __call__(self) -> _TrackingUnitOfWork:
        return _TrackingUnitOfWork(
            session_factory=self._session_factory,
            clock=self._clock,
            pid_ready=self._pid_ready,
            pid=self._pid,
        )


async def _wait_for_advisory_lock(engine, backend_pid: int) -> None:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        async with engine.connect() as connection:
            wait_event = await connection.scalar(
                text("SELECT wait_event FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": backend_pid},
            )
        if wait_event == "advisory":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("legacy update did not wait on the global fact lifecycle fence")


def _fact(fact_id, text, scope, source_ref, now):
    return MemoryFact.remember(
        identity=MemoryFactIdentity(fact_id, scope),
        text=text,
        source_refs=(source_ref,),
        now=now,
        temporal_extent=FactTemporalExtent.ongoing_state(
            observed_at=now,
            valid_from=now,
            basis="primary_evidence",
        ),
    ).to_snapshot()


def _document() -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id="document-reinstate",
        space_id="space-reinstate",
        memory_scope_id="scope-reinstate",
        thread_id=None,
        title="Reinstatement evidence",
        source_type="document",
        source_external_id="document-reinstate",
        content_hash="document-reinstate-hash",
        classification="internal",
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )


def _chunk() -> MemoryChunkRow:
    return MemoryChunkRow(
        id="chunk-reinstate",
        space_id="space-reinstate",
        memory_scope_id="scope-reinstate",
        thread_id=None,
        document_id="document-reinstate",
        episode_id=None,
        source_type="document",
        source_external_id="document-reinstate",
        source_hash="chunk-reinstate-hash",
        kind="document_section",
        text="Canonical reinstatement evidence.",
        normalized_text="canonical reinstatement evidence.",
        status="active",
        sequence=0,
        char_start=0,
        char_end=33,
        token_estimate=4,
        classification="internal",
        created_at=NOW,
        updated_at=NOW,
        metadata_json={},
    )
