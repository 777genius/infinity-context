"""Persistence checks for exact source-version cognitive dependencies."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from infinity_context_adapters.features.cognitive_memory import (
    PostgresCognitiveProjectionStore,
)
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_adapters.postgres.feature_models import (
    MemoryCognitiveDependencyRow,
    MemoryCognitiveProjectionRow,
)
from infinity_context_adapters.postgres.models import MemoryFactRow
from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceChangedCommand,
    InvalidateCognitiveDependenciesHandler,
)
from sqlalchemy import select

from tests.cognitive_candidate_test_support import create_cognitive_candidate

NOW = datetime(2026, 8, 5, tzinfo=UTC)


def test_postgres_projection_persists_version_dependency_and_invalidates_once(
    tmp_path: Path,
) -> None:
    candidate = _candidate(version=3)

    async def exercise() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cognition.db'}")
        try:
            await create_schema(engine)
            sessions = build_session_factory(engine)
            async with sessions() as session:
                store = PostgresCognitiveProjectionStore(session)
                session.add(_fact_row(version=3))
                persisted = await store.upsert_if_evidence_current(
                    candidate,
                    current_visible_evidence=candidate.evidence_identities,
                    created_at=NOW,
                )
                assert persisted is True
                await session.commit()

            command = CanonicalEvidenceChangedCommand(
                scope=candidate.scope,
                evidence_type="fact",
                evidence_id="fact-1",
                current_version=4,
                currently_visible=True,
                source_event_id="fact.updated:fact-1:4",
                occurred_at=NOW,
            )
            async with sessions() as session:
                handler = InvalidateCognitiveDependenciesHandler(
                    PostgresCognitiveProjectionStore(session)
                )
                first = await handler.execute(command)
                await session.commit()
            async with sessions() as session:
                handler = InvalidateCognitiveDependenciesHandler(
                    PostgresCognitiveProjectionStore(session)
                )
                second = await handler.execute(command)
                projections = tuple(
                    (await session.execute(select(MemoryCognitiveProjectionRow))).scalars()
                )
                dependencies = tuple(
                    (await session.execute(select(MemoryCognitiveDependencyRow))).scalars()
                )

            assert first.invalidated_candidate_ids == (candidate.identity,)
            assert second.invalidated_candidate_ids == ()
            assert len(projections) == len(dependencies) == 1
            assert projections[0].state == "invalidated"
            assert projections[0].invalidation_reason == "canonical_source_version_changed"
            assert dependencies[0].evidence_id == "fact-1"
            assert dependencies[0].evidence_version == 3
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def _candidate(*, version: int):
    return create_cognitive_candidate(
        version=version,
        content="Postgres is canonical",
    )


def _fact_row(*, version: int) -> MemoryFactRow:
    return MemoryFactRow(
        id="fact-1",
        space_id="space-1",
        memory_scope_id="scope-1",
        thread_id=None,
        kind="note",
        text="Postgres is canonical",
        status="active",
        confidence="high",
        trust_level="high",
        classification="internal",
        category=None,
        tags_json=[],
        ttl_policy=None,
        expires_at=None,
        temporal_kind="state",
        observed_at=NOW,
        valid_from=NOW,
        valid_to=None,
        occurred_from=None,
        occurred_to=None,
        temporal_basis="asserted",
        temporal_precision="exact",
        last_confirmed_at=NOW,
        confirmation_basis="test",
        purge_after=None,
        epistemic_mode="world_claim",
        asserted_by=None,
        perspective_subject=None,
        repository_id=None,
        code_scope_id=None,
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )
