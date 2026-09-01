from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import get_args, get_origin, get_type_hints

import infinity_context_core.features.document_ingestion.public as ingestion
import pytest
from fastapi import FastAPI
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
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "unavailable"
    assert handler.calls == 0


def test_oversized_body_is_rejected_before_handler_execution() -> None:
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


def test_cancellation_waits_for_handler_and_disconnect_cleanup() -> None:
    async def scenario() -> None:
        operation_cancelled = asyncio.Event()

        async def operation() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                operation_cancelled.set()

        async def receive():
            await asyncio.Event().wait()

        task = asyncio.create_task(
            body_boundary.execute_with_disconnect(
                SimpleNamespace(receive=receive), operation()
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert operation_cancelled.is_set()

    asyncio.run(scenario())
