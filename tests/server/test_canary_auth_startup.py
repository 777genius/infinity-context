import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_core.domain.errors import MemoryUnauthorizedError
from infinity_context_server.api.auth import require_service_token
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from starlette.requests import Request

_POSTGRES_URL = "postgresql+asyncpg://test:test@127.0.0.1/test"
_BIND_HOSTS = (
    "127.0.0.1",
    "::1",
    "localhost",
    "0.0.0.0",
    "::",
    "10.0.0.8",
    "203.0.113.8",
    "infinity-context-api",
    "api.example.test",
    "http://127.0.0.1:7788",
)


@pytest.mark.parametrize("deploy_profile", (DeployProfile.CANARY, DeployProfile.SERVER))
@pytest.mark.parametrize("host", _BIND_HOSTS)
@pytest.mark.parametrize("service_token", (None, "configured-token"))
def test_serving_profile_auth_is_independent_of_bind_host(
    deploy_profile: DeployProfile,
    host: str,
    service_token: str | None,
) -> None:
    settings = Settings(
        deploy_profile=deploy_profile,
        database_url=_POSTGRES_URL,
        host=host,
        service_token=service_token,
    )

    if service_token is None:
        with pytest.raises(
            RuntimeError,
            match="MEMORY_SERVICE_TOKEN is required for canary/server deploy profiles",
        ):
            settings.validate_for_startup()
    else:
        settings.validate_for_startup()


@pytest.mark.parametrize("service_token", (None, "", "   "))
def test_canary_missing_or_blank_token_fails_while_app_is_being_built(
    service_token: str | None,
) -> None:
    with pytest.raises(
        RuntimeError,
        match="MEMORY_SERVICE_TOKEN is required for canary/server deploy profiles",
    ):
        create_app(
            Settings(
                deploy_profile=DeployProfile.CANARY,
                database_url=_POSTGRES_URL,
                host="0.0.0.0",
                service_token=service_token,
            )
        )


def test_authenticated_canary_request_sets_root_actor_without_exposing_token() -> None:
    request = _request()
    container = SimpleNamespace(
        settings=Settings(
            deploy_profile=DeployProfile.CANARY,
            database_url=_POSTGRES_URL,
            host="0.0.0.0",
            service_token="private-canary-token",
        )
    )
    container.settings.validate_for_startup()

    asyncio.run(
        require_service_token(
            container,
            request,
            authorization="Bearer private-canary-token",
        )
    )

    assert request.state.authenticated_actor_id == "root-service-token"
    assert "private-canary-token" not in repr(request.state.__dict__)


def test_authenticated_canary_rejects_missing_header_with_generic_error() -> None:
    container = SimpleNamespace(
        settings=Settings(
            deploy_profile=DeployProfile.CANARY,
            database_url=_POSTGRES_URL,
            service_token="private-canary-token",
        )
    )

    with pytest.raises(MemoryUnauthorizedError) as error:
        asyncio.run(require_service_token(container, _request(), authorization=None))

    assert str(error.value) == "Missing or invalid service token"
    assert "private-canary-token" not in str(error.value)


def _request() -> Request:
    path = "/v1/documents"
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("198.51.100.9", 40000),
            "server": ("0.0.0.0", 7788),
            "path_params": {},
        }
    )
