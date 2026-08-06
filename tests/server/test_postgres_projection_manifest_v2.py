from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    _require_projection_manifest_inventory,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryEpisodeRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import build_async_engine, create_schema
from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_v2_inventory_accepts_exact_episode_and_owned_chunk(tmp_path: Path) -> None:
    asyncio.run(_inventory_contract(tmp_path, mode="exact"))


def test_v2_inventory_accepts_threadless_scope_with_empty_episodes(tmp_path: Path) -> None:
    asyncio.run(_threadless_empty_inventory_contract(tmp_path))


def test_v2_inventory_rejects_threadless_scope_with_episode(tmp_path: Path) -> None:
    asyncio.run(_threadless_empty_inventory_contract(tmp_path, episode_ids=["episode-1"]))


@pytest.mark.parametrize("mode", ["missing", "extra", "cross_scope", "unbound_chunk"])
def test_v2_inventory_rejects_episode_or_chunk_ownership_mismatch(
    tmp_path: Path,
    mode: str,
) -> None:
    asyncio.run(_inventory_contract(tmp_path, mode=mode))


async def _inventory_contract(tmp_path: Path, *, mode: str) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'{mode}.db'}")
    await create_schema(engine)
    try:
        async with AsyncSession(engine) as session:
            await _seed(session, mode=mode)
            manifest = _manifest()
            if mode == "missing":
                manifest["scopes"][0]["episode_ids"] = []
            elif mode == "extra":
                manifest["scopes"][0]["episode_ids"] = ["episode-1", "episode-extra"]
            if mode == "exact":
                await _require_projection_manifest_inventory(
                    session,
                    space_id="space-1",
                    manifest=manifest,
                )
            else:
                with pytest.raises(MemoryConflictError):
                    await _require_projection_manifest_inventory(
                        session,
                        space_id="space-1",
                        manifest=manifest,
                    )
    finally:
        await engine.dispose()


async def _threadless_empty_inventory_contract(
    tmp_path: Path,
    *,
    episode_ids: list[str] | None = None,
) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'threadless.db'}")
    await create_schema(engine)
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                [
                    MemorySpaceRow(
                        id="space-1",
                        slug="memory-comparison-v2-threadless",
                        name="v2 threadless",
                        status="active",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MemoryScopeRow(
                        id="scope-1",
                        space_id="space-1",
                        external_ref="scope-1",
                        name="scope-1",
                        status="active",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            await session.flush()
            manifest = _manifest()
            manifest["scopes"][0].update(
                {
                    "thread_id": None,
                    "episode_ids": episode_ids or [],
                    "chunk_ids": [],
                }
            )

            if episode_ids:
                with pytest.raises(MemoryConflictError):
                    await _require_projection_manifest_inventory(
                        session,
                        space_id="space-1",
                        manifest=manifest,
                    )
            else:
                await _require_projection_manifest_inventory(
                    session,
                    space_id="space-1",
                    manifest=manifest,
                )
    finally:
        await engine.dispose()


async def _seed(session: AsyncSession, *, mode: str) -> None:
    episode_scope = "scope-other" if mode == "cross_scope" else "scope-1"
    episode_thread = "thread-other" if mode == "cross_scope" else "thread-1"
    session.add_all(
        [
            MemorySpaceRow(
                id="space-1",
                slug="memory-comparison-v2",
                name="v2",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            ),
            MemoryScopeRow(
                id="scope-1",
                space_id="space-1",
                external_ref="scope-1",
                name="scope-1",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            ),
            MemoryThreadRow(
                id="thread-1",
                space_id="space-1",
                memory_scope_id="scope-1",
                external_ref="thread-1",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            ),
            MemoryEpisodeRow(
                id="episode-1",
                space_id="space-1",
                memory_scope_id=episode_scope,
                thread_id=episode_thread,
                source_type="benchmark",
                source_external_id="episode-source",
                text="episode",
                speaker="user",
                trust_level="trusted",
                status="active",
                occurred_at=NOW,
                created_at=NOW,
                metadata_json={},
            ),
            MemoryChunkRow(
                id="chunk-1",
                space_id="space-1",
                memory_scope_id="scope-1",
                thread_id="thread-1",
                document_id=None,
                episode_id=None if mode == "unbound_chunk" else "episode-1",
                source_type="benchmark",
                source_external_id="episode-source",
                source_hash="1" * 64,
                kind="episode",
                text="chunk",
                normalized_text="chunk",
                status="active",
                sequence=0,
                char_start=0,
                char_end=5,
                token_estimate=1,
                classification="internal",
                created_at=NOW,
                updated_at=NOW,
                metadata_json={},
            ),
        ]
    )
    await session.flush()


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v2",
        "scopes": [
            {
                "memory_scope_id": "scope-1",
                "thread_id": "thread-1",
                "episode_ids": ["episode-1"],
                "chunk_ids": ["chunk-1"],
                "fact_ids": [],
                "document_ids": [],
            }
        ],
    }
