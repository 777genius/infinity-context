from __future__ import annotations

import asyncio
from types import SimpleNamespace

import infinity_context_core.features.document_ingestion.public as ingestion
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1.documents import router


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
