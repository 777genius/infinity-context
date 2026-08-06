"""Database backstops for irreversible canonical fact shape corruption."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from infinity_context_adapters.features.memory_facts.postgres_temporal_decision_store import (
    PostgresFactSupersessionRepository,
)
from infinity_context_adapters.postgres import (
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_adapters.postgres.context_candidates import (
    create_postgres_memory_fact_selection,
)
from infinity_context_adapters.postgres.feature_models import CodeRepositoryRow
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryFactVersionRow,
    MemoryServiceTokenRow,
    MemorySpaceRow,
)
from infinity_context_adapters.postgres.temporal_models import MemoryFactTemporalDecisionRow
from infinity_context_core.features.memory_facts.public import (
    FactTemporalQueryMode,
    MemoryFactSelectionQuery,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 8, 5, tzinfo=UTC)
EFFECTIVE_AT = NOW + timedelta(days=1)


def test_metadata_declares_temporal_relation_and_chunk_backstops() -> None:
    relation_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in MemoryFactRelationRow.__table__.constraints
    }
    decision_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in MemoryFactTemporalDecisionRow.__table__.constraints
    }
    chunk_constraints = {constraint.name for constraint in MemoryChunkRow.__table__.constraints}

    assert "ck_memory_fact_relation_decision_versions" in relation_constraints
    assert relation_constraints["fk_memory_fact_relation_temporal_decision_identity"] == (
        "temporal_decision_id",
        "space_id",
        "memory_scope_id",
        "source_fact_id",
        "source_fact_version",
        "target_fact_id",
        "target_fact_version",
        "valid_from",
    )
    assert decision_constraints["uq_memory_fact_temporal_decision_relation_identity"] == (
        "id",
        "space_id",
        "memory_scope_id",
        "source_fact_id",
        "source_fact_version",
        "target_fact_id",
        "target_fact_version",
        "effective_at",
    )
    assert decision_constraints["fk_memory_fact_temporal_decision_compensation_scope"] == (
        "compensates_decision_id",
        "space_id",
        "memory_scope_id",
    )
    assert "ck_chunk_owner" in chunk_constraints


@pytest.mark.parametrize(
    ("overrides", "constraint_fragment"),
    (
        ({"temporal_kind": "event", "occurred_from": None}, "temporal_shape"),
        ({"repository_id": None, "code_scope_id": "code-scope-1"}, "code_scope_pair"),
        ({"last_confirmed_at": NOW, "confirmation_basis": None}, "confirmation_pair"),
    ),
)
def test_database_rejects_invalid_canonical_fact_shapes(
    tmp_path: Path,
    overrides: dict[str, object],
    constraint_fragment: str,
) -> None:
    async def run() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'facts.db'}")
        try:
            await create_schema(engine)
            values: dict[str, object] = {
                "id": f"fact-{constraint_fragment}",
                "space_id": "space-1",
                "memory_scope_id": "scope-1",
                "thread_id": None,
                "kind": "note",
                "text": "Invalid storage shape",
                "status": "active",
                "confidence": "medium",
                "trust_level": "medium",
                "classification": "internal",
                "temporal_kind": "state",
                "observed_at": NOW,
                "valid_from": NOW,
                "temporal_basis": "asserted",
                "temporal_precision": "exact",
                "epistemic_mode": "world_claim",
                "version": 1,
                "created_at": NOW,
                "updated_at": NOW,
            }
            values.update(overrides)
            async with AsyncSession(engine) as session:
                session.add(MemoryFactRow(**values))
                with pytest.raises(IntegrityError) as error:
                    await session.commit()
                assert constraint_fragment in str(error.value)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("row_kind", ("fact", "service_token"))
def test_repository_references_cannot_cross_space(
    tmp_path: Path,
    row_kind: str,
) -> None:
    async def run() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{row_kind}.db'}")
        try:
            await create_schema(engine)
            async with AsyncSession(engine) as session:
                await session.execute(text("PRAGMA foreign_keys=ON"))
                session.add_all(
                    (
                        MemorySpaceRow(
                            id="space-a",
                            slug="space-a",
                            name="Space A",
                            status="active",
                            created_at=NOW,
                            updated_at=NOW,
                        ),
                        MemorySpaceRow(
                            id="space-b",
                            slug="space-b",
                            name="Space B",
                            status="active",
                            created_at=NOW,
                            updated_at=NOW,
                        ),
                    )
                )
                await session.commit()
                session.add(
                    CodeRepositoryRow(
                        id="repository-a",
                        space_id="space-a",
                        provider="local",
                        repo_key="repository-v1-repository-a",
                        safe_label="repository-a",
                        remote_url_hash=None,
                        default_branch="main",
                        monorepo_root=None,
                        status="active",
                        version=1,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await session.commit()
                if row_kind == "fact":
                    session.add(
                        MemoryFactRow(
                            id="fact-cross-space",
                            space_id="space-b",
                            memory_scope_id="scope-b",
                            thread_id=None,
                            kind="note",
                            text="Cross-space repository reference",
                            status="active",
                            confidence="medium",
                            trust_level="medium",
                            classification="internal",
                            temporal_kind="state",
                            observed_at=NOW,
                            valid_from=NOW,
                            temporal_basis="asserted",
                            temporal_precision="exact",
                            epistemic_mode="world_claim",
                            repository_id="repository-a",
                            version=1,
                            created_at=NOW,
                            updated_at=NOW,
                        )
                    )
                else:
                    session.add(
                        MemoryServiceTokenRow(
                            id="token-cross-space",
                            space_id="space-b",
                            memory_scope_ids_json=["scope-b"],
                            repository_id="repository-a",
                            code_scope_id=None,
                            description="cross-space token",
                            token_hash="cross-space-token-hash",
                            permissions_json=["memory:read"],
                            status="active",
                            created_at=NOW,
                        )
                    )
                with pytest.raises(IntegrityError):
                    await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_database_rejects_relation_effective_time_that_differs_from_decision(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relation-fk.db'}")
        try:
            await create_schema(engine)
            async with AsyncSession(engine) as session:
                await session.execute(text("PRAGMA foreign_keys=ON"))
                await _seed_consistent_supersession(session)
                with pytest.raises(IntegrityError):
                    await session.execute(
                        text(
                            "UPDATE memory_fact_relations "
                            "SET valid_from = :invalid_effective_at WHERE id = 'relation-1'"
                        ),
                        {"invalid_effective_at": EFFECTIVE_AT + timedelta(days=1)},
                    )
                    await session.commit()
                await session.rollback()
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_supersession_store_fails_closed_on_thread_mismatch(tmp_path: Path) -> None:
    async def run() -> None:
        engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'relation-thread.db'}")
        try:
            await create_schema(engine)
            async with AsyncSession(engine) as session:
                await session.execute(text("PRAGMA foreign_keys=ON"))
                await _seed_consistent_supersession(session)
                await session.execute(
                    text(
                        "UPDATE memory_fact_relations "
                        "SET thread_id = 'thread-other' WHERE id = 'relation-1'"
                    )
                )
                await session.commit()

                repository = PostgresFactSupersessionRepository(session)
                with pytest.raises(
                    ValueError,
                    match="does not match its temporal decision",
                ):
                    await repository.find_by_decision("decision-1")
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "temporal_mode",
    (FactTemporalQueryMode.CURRENT, FactTemporalQueryMode.AS_OF),
)
def test_selection_fails_closed_on_inconsistent_audited_relation(
    tmp_path: Path,
    temporal_mode: FactTemporalQueryMode,
) -> None:
    async def run() -> None:
        engine = build_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / f'relation-{temporal_mode.value}.db'}"
        )
        try:
            await create_schema(engine)
            async with AsyncSession(engine) as session:
                await session.execute(text("PRAGMA foreign_keys=ON"))
                await _seed_consistent_supersession(session)
                await session.execute(text("PRAGMA foreign_keys=OFF"))
                assert (await session.execute(text("PRAGMA foreign_keys"))).scalar_one() == 0
                await session.execute(
                    text(
                        "UPDATE memory_fact_relations "
                        "SET valid_from = :invalid_effective_at WHERE id = 'relation-1'"
                    ),
                    {"invalid_effective_at": EFFECTIVE_AT + timedelta(hours=1)},
                )
                await session.commit()
                await session.execute(text("PRAGMA foreign_keys=ON"))

            selection = create_postgres_memory_fact_selection(build_session_factory(engine))
            relations = await selection.find_current_supersessions(
                MemoryFactSelectionQuery(
                    space_id="space-1",
                    memory_scope_ids=("scope-1",),
                    thread_id=None,
                    temporal_mode=temporal_mode,
                    reference_time=EFFECTIVE_AT + timedelta(days=2),
                    fact_ids=("predecessor",),
                    limit=1,
                )
            )
            assert relations == ()
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _seed_consistent_supersession(session: AsyncSession) -> None:
    predecessor = _fact_row(
        "predecessor",
        status="superseded",
        valid_from=NOW - timedelta(days=10),
        valid_to=EFFECTIVE_AT,
    )
    successor = _fact_row(
        "successor",
        status="active",
        valid_from=EFFECTIVE_AT,
    )
    session.add_all((predecessor, successor))
    await session.flush()
    session.add_all(
        (
            _fact_version_row(predecessor),
            _fact_version_row(successor),
        )
    )
    await session.commit()
    session.add(
        MemoryFactTemporalDecisionRow(
            id="decision-1",
            decision_type="supersede",
            space_id="space-1",
            memory_scope_id="scope-1",
            thread_id=None,
            thread_scope_key="global",
            source_fact_id="successor",
            source_fact_version=1,
            target_fact_id="predecessor",
            target_fact_version=1,
            effective_at=EFFECTIVE_AT,
            evidence_refs_json=[],
            actor_id="reviewer",
            policy_version="test-v1",
            reason_code="accepted_replacement",
            applied_at=EFFECTIVE_AT,
            idempotency_key="decision-1",
            compensates_decision_id=None,
            outbox_message_ids_json=[],
        )
    )
    await session.commit()
    session.add(
        MemoryFactRelationRow(
            id="relation-1",
            space_id="space-1",
            memory_scope_id="scope-1",
            thread_id=None,
            source_fact_id="successor",
            source_fact_version=1,
            target_fact_id="predecessor",
            target_fact_version=1,
            relation_type="supersedes",
            reason="temporal_decision:decision-1",
            status="active",
            observed_at=EFFECTIVE_AT,
            valid_from=EFFECTIVE_AT,
            valid_to=None,
            temporal_decision_id="decision-1",
            created_at=EFFECTIVE_AT,
            updated_at=EFFECTIVE_AT,
        )
    )
    await session.commit()


def _fact_row(
    fact_id: str,
    *,
    status: str,
    valid_from: datetime,
    valid_to: datetime | None = None,
) -> MemoryFactRow:
    return MemoryFactRow(
        id=fact_id,
        space_id="space-1",
        memory_scope_id="scope-1",
        thread_id=None,
        kind="architecture_decision",
        text=f"Canonical {fact_id}",
        status=status,
        confidence="high",
        trust_level="verified",
        classification="internal",
        temporal_kind="state",
        observed_at=NOW,
        valid_from=valid_from,
        valid_to=valid_to,
        temporal_basis="asserted",
        temporal_precision="exact",
        epistemic_mode="world_claim",
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _fact_version_row(fact: MemoryFactRow) -> MemoryFactVersionRow:
    return MemoryFactVersionRow(
        fact_id=fact.id,
        version=fact.version,
        text=fact.text,
        status=fact.status,
        source_refs_json=[],
        snapshot_json={},
        reason=None,
        created_at=NOW,
    )
