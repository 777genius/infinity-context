import asyncio
from pathlib import Path

from infinity_context_server.composition import build_container
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.retrieval_runtime_lifecycle import (
    ProviderFreeRetrievalRuntimeLifecycle,
    RetrievalRuntimeLifecycle,
)


def test_provider_free_runtime_starts_without_postgres_runtime_fence(
    tmp_path: Path,
) -> None:
    container = build_container(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'provider-free.db'}",
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    assert isinstance(
        container.retrieval_runtime_lifecycle, ProviderFreeRetrievalRuntimeLifecycle
    )
    asyncio.run(container.start_retrieval_runtime())
    asyncio.run(container.aclose())


def test_postgres_runtime_keeps_fail_closed_lifecycle() -> None:
    container = build_container(
        Settings(
            deploy_profile=DeployProfile.TEST,
            database_url="postgresql+asyncpg://test:test@127.0.0.1/test",
            service_token="test-token",
            qdrant_enabled=False,
            graphiti_enabled=False,
            embeddings_enabled=False,
        )
    )

    assert isinstance(container.retrieval_runtime_lifecycle, RetrievalRuntimeLifecycle)
    asyncio.run(container.aclose())
