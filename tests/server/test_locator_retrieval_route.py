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
    async def execute(
        self, request, *, deadline_monotonic, contract_version="context-retrieval.v2"
    ):
        assert contract_version == "context-retrieval.v3" or request.scope.thread_mode == "exact"
        assert asyncio.get_running_loop().time() < deadline_monotonic
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


def _post(app: FastAPI, payload: dict[str, object], path="/v1/context/retrieve") -> Response:
    async def execute() -> Response:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(path, json=payload)

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
                    deadline_monotonic=asyncio.get_running_loop().time() + 0.01,
                )
        assert operation_cancelled.is_set()
        assert receive_cancelled.is_set()

    asyncio.run(scenario())


def test_repeated_cancellation_waits_for_retrieval_cleanup() -> None:
    async def scenario() -> None:
        cleanup_started = asyncio.Event()
        cleanup_finished = asyncio.Event()

        async def operation() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await asyncio.sleep(0.02)
                cleanup_finished.set()

        async def receive() -> dict[str, str]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        current = asyncio.current_task()
        assert current is not None
        loop = asyncio.get_running_loop()
        loop.call_later(0.01, current.cancel)
        loop.call_later(0.015, current.cancel)
        with pytest.raises(asyncio.CancelledError):
            await route._execute_with_disconnect(
                SimpleNamespace(receive=receive),
                operation(),
                deadline_monotonic=asyncio.get_running_loop().time() + 1,
            )
        assert cleanup_started.is_set()
        assert cleanup_finished.is_set()
        while current.cancelling():
            current.uncancel()

    asyncio.run(scenario())


def test_disconnect_cleanup_cannot_outlive_absolute_deadline() -> None:
    async def scenario() -> None:
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()

        async def operation() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cleanup_started.set()
                await release_cleanup.wait()

        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        started = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            await route._execute_with_disconnect(
                SimpleNamespace(receive=receive),
                operation(),
                deadline_monotonic=started + 0.02,
            )
        assert cleanup_started.is_set()
        assert asyncio.get_running_loop().time() - started < 0.2
        release_cleanup.set()
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_repeated_deadlines_release_handler_capacity() -> None:
    async def scenario() -> None:
        cancelled = 0

        async def operation() -> None:
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            finally:
                cancelled += 1

        async def receive() -> dict[str, str]:
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        started = asyncio.get_running_loop().time()
        for _ in range(10):
            with pytest.raises(TimeoutError):
                await route._execute_with_disconnect(
                    SimpleNamespace(receive=receive),
                    operation(),
                    deadline_monotonic=asyncio.get_running_loop().time() + 0.005,
                )
        assert cancelled == 10
        assert asyncio.get_running_loop().time() - started < 0.5

    asyncio.run(scenario())


def _v3_payload():
    payload = _payload()
    payload["contract_version"] = "context-retrieval.v3"
    payload["scope"] = {"spaceId": "space-a", "memoryScopeId": "scope-a", "thread": {"mode": "any"}}
    return payload


@pytest.mark.parametrize(
    "selector",
    ({"mode": "any"}, {"mode": "exact", "id": None}, {"mode": "exact", "id": "meeting-a"}),
)
def test_v3_http_selectors_use_same_authorized_boundary(monkeypatch, selector):
    app = _app(monkeypatch, _token())
    payload = _v3_payload()
    payload["scope"]["thread"] = selector
    response = _post(app, payload, "/v1/context/retrieve-v3")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "context-retrieval.v3"
    assert len(app.state.resolve_calls) == 1
    assert app.state.resolve_calls[0].scope.thread.to_dict() == selector


@pytest.mark.parametrize(
    ("selector", "status", "code"),
    (
        ({"mode": "any", "id": None}, 422, "memory.context_retrieval_unsupported"),
        ({"mode": "exact"}, 400, "memory.context_retrieval_contract_invalid"),
        ({"mode": "all"}, 422, "memory.context_retrieval_unsupported"),
        (None, 400, "memory.context_retrieval_contract_invalid"),
    ),
)
def test_v3_invalid_selector_rejected_before_resolution(monkeypatch, selector, status, code):
    app = _app(monkeypatch, _token())
    payload = _v3_payload()
    payload["scope"]["thread"] = selector
    response = _post(app, payload, "/v1/context/retrieve-v3")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is False
    assert app.state.resolve_calls == []


@pytest.mark.parametrize("field", ("spaceId", "memoryScopeId"))
def test_v3_any_cannot_escape_authorized_scope(monkeypatch, field):
    app = _app(monkeypatch, _token())
    payload = _v3_payload()
    payload["scope"][field] = "other"
    assert _post(app, payload, "/v1/context/retrieve-v3").status_code == 403
    assert app.state.resolve_calls == []


def test_v3_response_byte_fallback_preserves_version():
    from infinity_context_contracts.features.context_retrieval_v3 import (
        RetrieveContextV3ResponseDto,
    )

    path = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_contracts/infinity_context_contracts/fixtures/context_retrieval_v2/success.json"
    )
    body = json.loads(path.read_text())
    body["contract_version"] = "context-retrieval.v3"
    result = json.loads(route._oversized_fallback(body))
    assert RetrieveContextV3ResponseDto.from_dict(result).status == "unavailable"
    assert result["applied_bounds"]["returned_seeds"] == 0


def test_v3_reauthorizes_after_scope_resolution(monkeypatch):
    from dataclasses import replace

    app = _app(monkeypatch, _token())

    async def changed_scope(dto, _container):
        return replace(dto, scope=replace(dto.scope, memory_scope_id="other-room"))

    monkeypatch.setattr(route, "_resolve_scope", changed_scope)
    assert _post(app, _v3_payload(), "/v1/context/retrieve-v3").status_code == 403


def _capability_app(monkeypatch, service):
    app = _app(monkeypatch, _token())
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(locator_retrieval=service)
    return app


async def _get_capability(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get("/v1/context/retrieve-v3/capability")


def _assert_capability_unavailable(response):
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "memory.context_retrieval_unavailable",
            "message": "Retrieval is unavailable",
            "retryable": True,
        }
    }


def test_v3_capability_stalled_lane_health_is_bounded(monkeypatch):
    from infinity_context_server.features.context_building.retrieval_service import (
        LocatorRetrievalService,
        RetrievalLaneRuntime,
    )

    async def scenario():
        cancelled = asyncio.Event()

        async def health():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        service = LocatorRetrievalService(
            lanes=(RetrievalLaneRuntime("postgres_keyword", None, health),),
            canonical_reader=None,
            service_revision="1" * 40,
            index_profile_digest="a" * 64,
            profile_kind="lexical",
        )
        monkeypatch.setattr(route, "MAX_DEADLINE_SECONDS", 0.02)
        started = asyncio.get_running_loop().time()
        response = await asyncio.wait_for(
            _get_capability(_capability_app(monkeypatch, service)), timeout=0.5
        )
        assert asyncio.get_running_loop().time() - started < 0.5
        _assert_capability_unavailable(response)
        assert cancelled.is_set()

    asyncio.run(scenario())


def test_v3_capability_missing_profile(monkeypatch):
    from infinity_context_server.retrieval_profile_composition import (
        ProfileAwareLocatorRetrievalService,
    )

    async def active():
        return None

    service = ProfileAwareLocatorRetrievalService(
        registry=SimpleNamespace(active=active),
        projection=None,
        sessions=None,
        query_embeddings=None,
        service_revision="1" * 40,
    )
    app = _capability_app(monkeypatch, service)
    _assert_capability_unavailable(asyncio.run(_get_capability(app)))


def test_v3_capability_success(monkeypatch):
    from infinity_context_contracts.features.context_building import RetrievalCapabilityDto
    from infinity_context_contracts.features.context_retrieval_v3 import retrieval_v3_capability

    fixture = Path(__file__).resolve().parents[2] / (
        "packages/infinity_context_contracts/infinity_context_contracts/fixtures/"
        "context_retrieval_v2/capability.json"
    )
    capability = RetrievalCapabilityDto.from_dict(json.loads(fixture.read_text()))

    async def descriptor():
        return capability

    response = asyncio.run(
        _get_capability(_capability_app(monkeypatch, SimpleNamespace(descriptor=descriptor)))
    )
    assert response.status_code == 200
    assert response.json() == retrieval_v3_capability(capability)


@pytest.mark.parametrize(
    "error", [RuntimeError("unexpected bug"), ValueError("invalid descriptor")]
)
def test_v3_capability_unexpected_errors_remain_visible(monkeypatch, error):
    async def descriptor():
        raise error

    app = _capability_app(monkeypatch, SimpleNamespace(descriptor=descriptor))
    with pytest.raises(type(error), match=str(error)):
        asyncio.run(_get_capability(app))


def test_v3_capability_preserves_cancellation(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def descriptor():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        app = _capability_app(monkeypatch, SimpleNamespace(descriptor=descriptor))
        task = asyncio.create_task(_get_capability(app))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(scenario())
