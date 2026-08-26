from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import infinity_context_core.features.context_building.public as core
import infinity_context_server.api.v1.context_retrieval as route
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient, Response
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1 import router as v1_router
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_READ, ActiveServiceToken


class _Service:
    async def execute(self, request):
        return core.LocatorRetrievalResponse(
            status="unqualified",
            capability_fingerprint=request.capability_fingerprint,
            profile_id=request.profile_id,
            applied_bounds=core.LocatorAppliedBounds(
                request.bounds.candidate_limit,
                request.bounds.result_limit,
                request.bounds.neighbor_radius,
                request.bounds.response_byte_limit,
                request.bounds.deadline_ms,
                0,
                0,
            ),
            candidates=(),
            provider_outcomes=(),
        )


def _app(monkeypatch, token: ActiveServiceToken | None) -> FastAPI:
    app = FastAPI()
    app.include_router(route.router, prefix="/v1")
    resolve_calls: list[object] = []

    async def authenticate(request: Request) -> None:
        if token is not None:
            request.state.active_service_token = token

    async def container():
        return SimpleNamespace(locator_retrieval=_Service())

    async def resolved(payload, _container):
        resolve_calls.append(payload)
        return payload

    async def forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    app.dependency_overrides[require_service_token] = authenticate
    app.dependency_overrides[get_container] = container
    app.add_exception_handler(MemoryForbiddenError, forbidden)
    monkeypatch.setattr(route, "_resolve_scope", resolved)
    app.state.resolve_calls = resolve_calls
    return app


def _post(app: FastAPI, payload: dict[str, object]) -> Response:
    async def execute() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post("/v1/context/retrieve", json=payload)

    return asyncio.run(execute())


def _payload(*, space_id="space-a", memory_scope_id="scope-a"):
    path = (
        Path(__file__).resolve().parents[2]
        / "packages/infinity_context_contracts/infinity_context_contracts/fixtures"
        / "context_retrieval_v2/request.json"
    )
    payload = deepcopy(json.loads(path.read_text()))
    payload["scope"]["space_id"] = space_id
    payload["scope"]["memory_scope_id"] = memory_scope_id
    return payload


def _token() -> ActiveServiceToken:
    return ActiveServiceToken(
        token_id="token-a",
        space_id="space-a",
        memory_scope_ids=frozenset({"scope-a"}),
        permissions=frozenset({MEMORY_PERMISSION_READ}),
    )


def test_scoped_token_http_route_allows_exact_scope(monkeypatch) -> None:
    response = _post(_app(monkeypatch, _token()), _payload())
    assert response.status_code == 200


@pytest.mark.parametrize(
    "payload",
    (_payload(space_id="space-b"), _payload(memory_scope_id="scope-b")),
)
def test_scoped_token_http_route_denies_cross_scope(monkeypatch, payload) -> None:
    app = _app(monkeypatch, _token())
    response = _post(app, payload)
    assert response.status_code == 403
    assert app.state.resolve_calls == []


def test_root_token_http_route_preserves_unscoped_behavior(monkeypatch) -> None:
    response = _post(
        _app(monkeypatch, None),
        _payload(space_id="space-b", memory_scope_id="scope-b"),
    )
    assert response.status_code == 200


def test_retrieval_route_is_additive_to_legacy_context_and_search() -> None:
    paths = {item.path for item in v1_router.routes}
    retrieval_paths = {item.path for item in route.router.routes}
    assert {"/v1/context", "/v1/search"} <= paths
    assert "/context/retrieve" in retrieval_paths


def test_timeout_cancels_retrieval_and_disconnect_tasks() -> None:
    async def scenario() -> None:
        operation_cancelled = asyncio.Event()
        receive_cancelled = asyncio.Event()

        async def operation() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                operation_cancelled.set()

        async def receive() -> dict[str, str]:
            try:
                await asyncio.Event().wait()
            finally:
                receive_cancelled.set()
            return {"type": "http.disconnect"}

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await route._execute_with_disconnect(
                    SimpleNamespace(receive=receive),
                    operation(),
                )
        assert operation_cancelled.is_set()
        assert receive_cancelled.is_set()

    asyncio.run(scenario())
