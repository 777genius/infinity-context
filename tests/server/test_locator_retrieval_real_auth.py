"""Exercise the router's real auth dependency with synthetic token/storage ports."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import infinity_context_core.features.context_building.public as core
import infinity_context_server.api.auth as auth
import infinity_context_server.api.v1.context_retrieval as route
import infinity_context_server.api.v1.scope_resolution as scopes
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from infinity_context_contracts.features.context_building import RetrievalCapabilityDto
from infinity_context_core.domain.errors import MemoryForbiddenError, MemoryUnauthorizedError
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_READ, ActiveServiceToken

FIXTURES = Path(__file__).resolve().parents[2] / (
    "packages/infinity_context_contracts/infinity_context_contracts/fixtures/context_retrieval_v2"
)
V2 = "/v1/context/retrieve"
V3 = "/v1/context/retrieve-v3"
CAPABILITY = V3 + "/capability"


def _payload(version=3):
    payload = json.loads((FIXTURES / "request.json").read_text())
    payload["scope"] = {"space_id": "space-a", "memory_scope_id": "scope-a", "thread_id": None}
    if version == 3:
        payload["contract_version"] = "context-retrieval.v3"
        payload["scope"] = {
            "spaceId": "space-a",
            "memoryScopeId": "scope-a",
            "thread": {"mode": "any"},
        }
    return payload


class _Service:
    def __init__(self):
        self.calls = []
        self.descriptor_calls = 0

    async def descriptor(self):
        self.descriptor_calls += 1
        payload = json.loads((FIXTURES / "capability.json").read_text())
        return RetrievalCapabilityDto.from_dict(payload)

    async def execute(
        self, request, *, deadline_monotonic, contract_version="context-retrieval.v2"
    ):
        self.calls.append((request, contract_version))
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


@pytest.fixture
def harness(monkeypatch):
    token = ActiveServiceToken(
        token_id="synthetic-token",
        space_id="space-a",
        memory_scope_ids=frozenset({"scope-a"}),
        permissions=frozenset({MEMORY_PERMISSION_READ}),
    )
    service = _Service()
    container = SimpleNamespace(
        settings=SimpleNamespace(service_token="synthetic-root"), locator_retrieval=service
    )
    state = SimpleNamespace(token=token, service=service)

    async def lookup(actual_container, presented):
        assert actual_container is container
        return state.token if presented == "synthetic-scoped" else None

    # Fake canonical storage, leaving route resolution and both authorizers intact.
    state.storage = AsyncMock(return_value=True)
    monkeypatch.setattr(scopes, "canonical_scope_matches", state.storage)
    monkeypatch.setattr(auth, "get_active_db_token", lookup)
    state.generic_json = AsyncMock(side_effect=AssertionError("generic request.json consumed body"))
    monkeypatch.setattr(Request, "json", state.generic_json)
    app = FastAPI()
    app.include_router(route.router, prefix="/v1")
    app.dependency_overrides[get_container] = lambda: container

    async def forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    async def unauthorized(_request, exc):
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    app.add_exception_handler(MemoryForbiddenError, forbidden)
    app.add_exception_handler(MemoryUnauthorizedError, unauthorized)
    assert auth.require_service_token not in app.dependency_overrides
    state.app = app
    yield state
    state.generic_json.assert_not_awaited()


def _send(harness, path=V3, *, raw=None, authorization="Bearer synthetic-scoped"):
    async def run():
        headers = {"Content-Type": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        async with AsyncClient(
            transport=ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client:
            if path == CAPABILITY:
                return await client.get(path, headers=headers)
            return await client.post(path, content=raw or json.dumps(_payload()), headers=headers)

    return asyncio.run(run())


@pytest.mark.parametrize("restriction", ("space", "scope", "both"))
@pytest.mark.parametrize(
    "selector",
    (
        {"mode": "any"},
        {"mode": "exact", "id": None},
        {"mode": "exact", "id": "thread-a"},
    ),
)
def test_real_auth_v3_scoped_post_and_capability(harness, restriction, selector):
    if restriction == "space":
        harness.token = replace(harness.token, memory_scope_ids=None)
    elif restriction == "scope":
        harness.token = replace(harness.token, space_id=None)
    payload = _payload()
    payload["scope"]["thread"] = selector
    response = _send(harness, raw=json.dumps(payload))
    assert response.status_code == 200
    assert response.json()["contract_version"] == "context-retrieval.v3"
    assert harness.storage.await_count == 1
    request, version = harness.service.calls[0]
    assert version == "context-retrieval.v3"
    assert request.scope.thread_mode == selector["mode"]
    assert request.scope.thread_id == selector.get("id")
    capability = _send(harness, CAPABILITY)
    assert capability.status_code == 200
    assert capability.json()["contract_version"] == "context-retrieval.v3"
    assert capability.json()["endpoint"] == V3
    assert harness.service.descriptor_calls == 1
    assert harness.storage.await_count == 1


@pytest.mark.parametrize("version", (2, 3))
@pytest.mark.parametrize("field", ("space", "scope"))
def test_real_auth_cross_scope_fails_before_storage(harness, version, field):
    payload = _payload(version)
    key = (
        {"space": "spaceId", "scope": "memoryScopeId"}
        if version == 3
        else {"space": "space_id", "scope": "memory_scope_id"}
    )[field]
    payload["scope"][key] = "other"
    response = _send(harness, V3 if version == 3 else V2, raw=json.dumps(payload))
    assert response.status_code == 403
    harness.storage.assert_not_awaited()
    assert harness.service.calls == []


@pytest.mark.parametrize("path", (V2, V3, CAPABILITY))
@pytest.mark.parametrize("failure", ("missing", "invalid", "permission", "inactive", "repository"))
def test_real_auth_still_requires_active_eligible_read_token(harness, path, failure):
    authorization = "Bearer synthetic-scoped"
    if failure == "missing":
        authorization = None
    elif failure == "invalid":
        authorization = "Bearer unknown-synthetic"
    elif failure == "permission":
        harness.token = replace(harness.token, permissions=frozenset({"memory:write"}))
    elif failure == "inactive":
        harness.token = replace(harness.token, binding_active=False)
    else:
        harness.token = replace(harness.token, repository_id="repository-a")
    response = _send(
        harness, path, raw=json.dumps(_payload(2 if path == V2 else 3)), authorization=authorization
    )
    assert response.status_code == (401 if failure in {"missing", "invalid"} else 403)
    harness.storage.assert_not_awaited()
    assert harness.service.calls == []
    assert harness.service.descriptor_calls == 0


@pytest.mark.parametrize(
    "selector",
    (
        '{"mode":"any","mode":"exact","id":null}',
        '{"mode":"any","id":null}',
        '{"mode":"exact"}',
        '{"mode":"all"}',
        "null",
    ),
)
def test_real_auth_invalid_selector_reaches_strict_bounded_decoder(harness, monkeypatch, selector):
    raw = json.dumps(_payload()).replace('{"mode": "any"}', selector).encode()
    decoded = []
    original = route.decode_retrieve_context_v3_request

    def decode(value):
        decoded.append(value)
        return original(value)

    monkeypatch.setattr(route, "decode_retrieve_context_v3_request", decode)
    response = _send(harness, raw=raw)
    unsupported = selector in ('{"mode":"any","id":null}', '{"mode":"all"}')
    assert response.status_code == (422 if unsupported else 400)
    code = "unsupported" if unsupported else "contract_invalid"
    assert response.json()["error"]["code"] == "memory.context_retrieval_" + code
    assert decoded == [raw]
    harness.storage.assert_not_awaited()
    assert harness.service.calls == []


def test_real_auth_raw_limit_precedes_decoder(harness, monkeypatch):
    from unittest.mock import Mock

    decode = Mock(side_effect=AssertionError("oversized body reached decoder"))
    monkeypatch.setattr(route, "decode_retrieve_context_v3_request", decode)
    response = _send(harness, raw=b" " * (route.MAX_RAW_REQUEST_BYTES + 1))
    assert response.status_code == 400
    decode.assert_not_called()
    harness.storage.assert_not_awaited()


def test_real_auth_v2_exact_null_unchanged(harness):
    response = _send(harness, V2, raw=json.dumps(_payload(2)))
    assert response.status_code == 200
    assert response.json()["contract_version"] == "context-retrieval.v2"
    request, version = harness.service.calls[0]
    assert version == "context-retrieval.v2"
    assert request.scope.thread_mode == "exact"
    assert request.scope.thread_id is None
    assert harness.storage.await_count == 1


@pytest.mark.parametrize("field", ("space_id", "memory_scope_id"))
def test_real_auth_rechecks_resolved_scope(harness, monkeypatch, field):
    async def changed(dto, _container):
        return replace(dto, scope=replace(dto.scope, **{field: "other"}))

    monkeypatch.setattr(route, "_resolve_scope", changed)
    assert _send(harness).status_code == 403
    assert harness.service.calls == []


@pytest.mark.parametrize(
    "method,path,trusted,safe",
    (
        ("POST", V2, True, False),
        ("POST", V3, True, False),
        ("GET", CAPABILITY, False, True),
        ("GET", "/v1/capabilities", False, True),
        ("GET", V3, False, False),
        ("POST", CAPABILITY, False, False),
        ("POST", V3 + "/other", False, False),
        ("GET", CAPABILITY + "/other", False, False),
    ),
)
def test_auth_exceptions_match_only_exact_method_and_path(method, path, trusted, safe):
    request = Request({"type": "http", "method": method, "path": path, "headers": []})
    assert auth._uses_trusted_post_resolution_scope(request) is trusted
    assert auth._is_safe_unscoped_endpoint(request) is safe
