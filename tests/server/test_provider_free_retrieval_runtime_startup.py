import asyncio
from pathlib import Path

import pytest
from infinity_context_server.composition import build_container
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.retrieval_runtime_lifecycle import (
    ProviderFreeRetrievalRuntimeLifecycle,
    RetrievalRuntimeLifecycle,
)


@pytest.mark.parametrize("deploy_profile", [DeployProfile.TEST, DeployProfile.LOCAL])
def test_local_provider_free_runtime_starts_without_postgres_runtime_fence(
    tmp_path: Path,
    deploy_profile: DeployProfile,
) -> None:
    container = build_container(
        Settings(
            deploy_profile=deploy_profile,
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


@pytest.mark.parametrize("deploy_profile", [DeployProfile.CANARY, DeployProfile.SERVER])
def test_production_profile_never_selects_provider_free_runtime(
    deploy_profile: DeployProfile,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="MEMORY_DATABASE_URL must use PostgreSQL for canary/server deploy profiles",
    ):
        build_container(
            Settings(
                deploy_profile=deploy_profile,
                database_url="sqlite+aiosqlite:///:memory:",
                service_token="test-token",
                qdrant_enabled=False,
                graphiti_enabled=False,
                embeddings_enabled=False,
            )
        )


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
