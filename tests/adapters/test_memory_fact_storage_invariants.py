"""Database backstops for irreversible canonical fact shape corruption."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.postgres import build_async_engine, create_schema
from infinity_context_adapters.postgres.feature_models import CodeRepositoryRow
from infinity_context_adapters.postgres.models import (
    MemoryFactRow,
    MemoryServiceTokenRow,
    MemorySpaceRow,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 8, 5, tzinfo=UTC)


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
