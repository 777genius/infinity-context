from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import get_args, get_origin, get_type_hints

import infinity_context_core.features.document_ingestion.public as ingestion
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncByteStream, AsyncClient
from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1 import exact_reconciliation_body as body_boundary
from infinity_context_server.api.v1.documents import reconcile_exact_document, router


def _client(handler) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[require_service_token] = lambda: None
    app.dependency_overrides[get_container] = lambda: SimpleNamespace(
        reconcile_exact_document=handler
    )
    return TestClient(app)


def _body(**changes):
    value = {
        "contract_version": "document-reconciliation.v1",
        "space_id": "space",
        "memory_scope_id": "scope",
        "thread_id": "thread",
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "projection_generation": "projection-1",
        "profile_generation": "profile-1",
        "deadline_ms": 500,
    }
    value.update(changes)
    return value


def test_route_returns_exact_visibility_without_a_mutation() -> None:
    class Handler:
        calls = 0

        async def execute(self, query):
            self.calls += 1
            assert query.identity.origin.source_external_id == "opaque-id"
            return ingestion.ExactDocumentReconciliation(
                "indexed",
                query.identity,
                document_id="doc-1",
                canonical_status="active",
                projection_generation="projection-1",
                profile_generation="profile-1",
                visibility="indexed",
                idempotency_key_matches=True,
            )

    handler = Handler()
    response = _client(handler).post("/v1/documents/reconcile-exact", json=_body())
    assert response.status_code == 200
    assert response.json()["data"] == {
        "contract_version": "document-reconciliation.v1",
        "state": "indexed",
        "scope": {"space_id": "space", "memory_scope_id": "scope", "thread_id": "thread"},
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "document_id": "doc-1",
        "canonical_status": "active",
        "projection_generation": "projection-1",
        "profile_generation": "profile-1",
        "visibility": "indexed",
        "idempotency_key_matches": True,
    }
    assert handler.calls == 1


def test_route_converts_deadline_to_bounded_unavailable_state() -> None:
    class Handler:
        async def execute(self, _query):
            await asyncio.sleep(0.2)

    response = _client(Handler()).post("/v1/documents/reconcile-exact", json=_body(deadline_ms=50))
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "unavailable"
    assert response.json()["data"]["visibility"] == "unavailable"


def test_route_rejects_malformed_and_unsupported_contracts() -> None:
    class Handler:
        async def execute(self, _query):
            raise AssertionError("must not execute")

    client = _client(Handler())
    assert (
        client.post("/v1/documents/reconcile-exact", json=_body(deadline_ms=49)).status_code == 422
    )
    response = client.post("/v1/documents/reconcile-exact", json=_body(contract_version="wrong"))
    assert response.status_code == 409


def test_route_return_annotation_includes_typed_payload_and_json_response() -> None:
    annotation = get_type_hints(reconcile_exact_document)["return"]
    members = get_args(annotation)
    assert JSONResponse in members
    assert any(get_origin(member) is dict for member in members)


def test_slow_body_consumes_the_advertised_deadline_before_handler_execution() -> None:
    class Handler:
        calls = 0

        async def execute(self, _query):
            self.calls += 1
            raise AssertionError("must not execute after request deadline")

    class SlowBody(AsyncByteStream):
        async def __aiter__(self):
            encoded = json.dumps(_body(deadline_ms=50)).encode()
            yield encoded[:-1]
            await asyncio.sleep(0.08)
            yield encoded[-1:]

    handler = Handler()
    app = _client(handler).app

    async def post():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            return await client.post(
                "/v1/documents/reconcile-exact",
                content=SlowBody(),
                headers={"content-type": "application/json"},
            )

    response = asyncio.run(post())
    assert response.status_code == 408
    assert handler.calls == 0


def test_single_oversized_chunk_is_rejected_before_handler_execution() -> None:
    class Handler:
        calls = 0

        async def execute(self, _query):
            self.calls += 1

    handler = Handler()
    response = _client(handler).post(
        "/v1/documents/reconcile-exact",
        content=b"{" + b" " * body_boundary.MAX_EXACT_RECONCILIATION_BODY_BYTES,
        headers={"content-type": "application/json", "content-length": "1"},
    )
    assert response.status_code == 413
    assert handler.calls == 0


def test_malformed_json_is_rejected_before_handler_execution() -> None:
    class Handler:
        calls = 0

        async def execute(self, _query):
            self.calls += 1

    handler = Handler()
    response = _client(handler).post(
        "/v1/documents/reconcile-exact",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert handler.calls == 0


def test_auth_runs_before_typed_contract_validation() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def reject_request() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    app.dependency_overrides[require_service_token] = reject_request
    response = TestClient(app).post(
        "/v1/documents/reconcile-exact",
        json={"deadline_ms": 500},
    )

    assert response.status_code == 401


def test_openapi_preserves_typed_request_component_reference() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    schema = app.openapi()

    assert schema["paths"]["/v1/documents/reconcile-exact"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ReconcileExactDocumentHttpRequest"
    }
    assert "ReconcileExactDocumentHttpRequest" in schema["components"]["schemas"]


def test_disconnect_during_authorization_cancels_the_whole_route() -> None:
    async def scenario() -> None:
        authorization_started = asyncio.Event()
        authorization_cancelled = asyncio.Event()
        disconnect_receiver_started = asyncio.Event()
        disconnect_receiver_finished = asyncio.Event()
        disconnect = asyncio.Queue()
        body_delivered = False

        async def blocked_authorization() -> None:
            authorization_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                authorization_cancelled.set()

        async def receive():
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {
                    "type": "http.request",
                    "body": json.dumps(_body()).encode(),
                    "more_body": False,
                }
            disconnect_receiver_started.set()
            try:
                return await disconnect.get()
            finally:
                disconnect_receiver_finished.set()

        async def send(_message) -> None:
            return None

        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.dependency_overrides[require_service_token] = blocked_authorization
        task = asyncio.create_task(
            app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": "/v1/documents/reconcile-exact",
                    "raw_path": b"/v1/documents/reconcile-exact",
                    "query_string": b"",
                    "headers": [(b"content-type", b"application/json")],
                    "client": ("test", 123),
                    "server": ("test", 80),
                },
                receive,
                send,
            )
        )
        await asyncio.wait_for(authorization_started.wait(), timeout=1)
        await asyncio.wait_for(disconnect_receiver_started.wait(), timeout=1)
        await disconnect.put({"type": "http.disconnect"})

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert authorization_cancelled.is_set()
        assert disconnect_receiver_finished.is_set()

    asyncio.run(scenario())
