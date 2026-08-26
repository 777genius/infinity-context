from __future__ import annotations

import pytest
from infinity_context_server import composition
from infinity_context_server.config import DeployProfile, Settings

_POSTGRES_REQUIRED = (
    "MEMORY_DATABASE_URL must use PostgreSQL for canary/server deploy profiles"
)


@pytest.mark.parametrize("deploy_profile", (DeployProfile.CANARY, DeployProfile.SERVER))
def test_production_retrieval_profiles_reject_sqlite(deploy_profile: DeployProfile) -> None:
    settings = Settings(
        deploy_profile=deploy_profile,
        database_url="sqlite+aiosqlite:///:memory:",
        service_token="unit-token",
    )

    with pytest.raises(RuntimeError) as error:
        settings.validate_for_startup()

    assert str(error.value) == _POSTGRES_REQUIRED


@pytest.mark.parametrize("deploy_profile", (DeployProfile.LOCAL, DeployProfile.TEST))
def test_local_and_test_retrieval_profiles_retain_sqlite(
    deploy_profile: DeployProfile,
) -> None:
    Settings(
        deploy_profile=deploy_profile,
        database_url="sqlite+aiosqlite:///:memory:",
    ).validate_for_startup()


@pytest.mark.parametrize("deploy_profile", (DeployProfile.CANARY, DeployProfile.SERVER))
def test_production_retrieval_profiles_retain_postgresql(
    deploy_profile: DeployProfile,
) -> None:
    Settings(
        deploy_profile=deploy_profile,
        database_url="postgresql+asyncpg://runtime:secret@db/context",
        service_token="unit-token",
    ).validate_for_startup()


@pytest.mark.parametrize("deploy_profile", (DeployProfile.CANARY, DeployProfile.SERVER))
def test_composition_rejects_sqlite_before_engine_construction(
    monkeypatch: pytest.MonkeyPatch,
    deploy_profile: DeployProfile,
) -> None:
    engine_construction_attempted = False

    def unexpected_engine_construction(_database_url: str) -> object:
        nonlocal engine_construction_attempted
        engine_construction_attempted = True
        raise AssertionError("engine construction must not run")

    monkeypatch.setattr(composition, "build_async_engine", unexpected_engine_construction)

    with pytest.raises(RuntimeError) as error:
        composition.build_container(
            Settings(
                deploy_profile=deploy_profile,
                database_url="sqlite+aiosqlite:///:memory:",
                service_token="unit-token",
            )
        )

    assert str(error.value) == _POSTGRES_REQUIRED
    assert engine_construction_attempted is False
