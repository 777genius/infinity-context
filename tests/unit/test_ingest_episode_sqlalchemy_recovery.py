import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryEpisodeRow,
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def test_episode_precommit_unique_conflict_recovers_with_fresh_uow(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )
    episode = {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "thread_external_ref": "precommit-race",
        "source_type": "system_audio",
        "source_external_id": "precommit-race-event",
        "text": "PRECOMMIT_RACE_MARKER must replay the canonical episode.",
        "idempotency_key": "precommit-race-event",
    }
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post("/v1/episodes", json=episode, headers=headers)
        container = app.state.container
        racing_factory = _HideFirstIdempotencyReadFactory(container.uow_factory)
        container.ingest_episode._uow_factory = racing_factory

        replay = client.post("/v1/episodes", json=episode, headers=headers)

    assert created.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["episode_id"] == created.json()["data"]["episode_id"]
    assert replay.json()["data"]["stored_chunks"] == 0
    assert replay.json()["data"]["duplicate_chunks"] == 1
    assert racing_factory.raw_integrity_errors == 1
    assert racing_factory.adapter_translations == 1
    assert racing_factory.open_count == 2
    assert asyncio.run(_canonical_write_counts(app.state.container.engine)) == (1, 1, 1, 1)


def test_episode_replay_fails_closed_for_corrupt_idempotency(tmp_path: Path) -> None:
    app = _create_test_app(tmp_path)
    episode = _episode_payload("corrupt-idempotency")
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        created = client.post("/v1/episodes", json=episode, headers=headers)
        episode_id = created.json()["data"]["episode_id"]

        asyncio.run(
            _rewrite_episode_idempotency(
                app.state.container.engine,
                episode_id=episode_id,
                result_type="fact",
                result_id=episode_id,
            )
        )
        wrong_type = client.post("/v1/episodes", json=episode, headers=headers)

        asyncio.run(
            _rewrite_episode_idempotency(
                app.state.container.engine,
                episode_id=episode_id,
                result_type="episode",
                result_id="episode_missing",
            )
        )
        missing_episode = client.post("/v1/episodes", json=episode, headers=headers)

    assert created.status_code == 200
    assert wrong_type.status_code == 500
    assert wrong_type.json()["error"]["code"] == "memory.internal"
    assert missing_episode.status_code == 500
    assert missing_episode.json()["error"]["code"] == "memory.internal"


class _HideFirstIdempotencyReadFactory:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.open_count = 0
        self.raw_integrity_errors = 0
        self.adapter_translations = 0

    def __call__(self):
        self.open_count += 1
        inner = self._delegate()
        if self.open_count == 1:
            return _HideIdempotencyReadUow(inner, self)
        return inner


class _HideIdempotencyReadUow:
    def __init__(self, inner, factory: _HideFirstIdempotencyReadFactory) -> None:
        self._inner = inner
        self._factory = factory

    async def __aenter__(self):
        await self._inner.__aenter__()
        self.idempotency = _HiddenIdempotencyRepository(self._inner.idempotency)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if isinstance(exc, IntegrityError):
            self._factory.raw_integrity_errors += 1
        try:
            await self._inner.__aexit__(exc_type, exc, tb)
        except MemoryConflictError as translated:
            if translated.__cause__ is exc:
                self._factory.adapter_translations += 1
            raise

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _HiddenIdempotencyRepository:
    def __init__(self, delegate) -> None:
        self._delegate = delegate

    async def find(self, **_kwargs):
        return None

    async def save(self, record) -> None:
        await self._delegate.save(record)


def _create_test_app(tmp_path: Path):
    return create_app(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}",
            auto_create_schema=True,
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
            legacy_client_enabled=True,
        )
    )


def _episode_payload(marker: str) -> dict[str, str]:
    return {
        "space_slug": "client-app",
        "memory_scope_external_ref": "default",
        "thread_external_ref": marker,
        "source_type": "system_audio",
        "source_external_id": f"{marker}-event",
        "text": f"{marker.upper()} must replay the canonical episode.",
        "idempotency_key": f"{marker}-event",
    }


async def _canonical_write_counts(engine) -> tuple[int, int, int, int]:
    async with AsyncSession(engine) as session:
        counts = []
        for row_type in (
            MemoryEpisodeRow,
            MemoryChunkRow,
            MemoryOutboxRow,
            MemoryIdempotencyRecordRow,
        ):
            counts.append(int(await session.scalar(select(func.count()).select_from(row_type))))
    return tuple(counts)  # type: ignore[return-value]


async def _rewrite_episode_idempotency(
    engine,
    *,
    episode_id: str,
    result_type: str,
    result_id: str,
) -> None:
    async with AsyncSession(engine) as session:
        row = await session.scalar(
            select(MemoryIdempotencyRecordRow).where(
                MemoryIdempotencyRecordRow.result_id == episode_id
            )
        )
        assert row is not None
        row.result_type = result_type
        row.result_id = result_id
        await session.commit()
