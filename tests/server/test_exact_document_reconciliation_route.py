from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import get_args, get_origin, get_type_hints

import infinity_context_core.features.document_ingestion.public as ingestion
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncByteStream, AsyncClient
from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1 import exact_reconciliation_body as body_boundary
from infinity_context_server.api.v1.documents import reconcile_exact_document, router
from infinity_context_server.features.document_ingestion.public import (
    ReconcileExactDocumentHttpRequest,
)


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


def _assert_sdk_compatible_unavailable(payload) -> None:
    """Assert the generation bindings required by the official TypeScript decoder."""

    data = payload["data"]
    assert data == {
        "contract_version": "document-reconciliation.v1",
        "state": "unavailable",
        "scope": {
            "space_id": "space",
            "memory_scope_id": "scope",
            "thread_id": "thread",
        },
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
        "document_id": None,
        "canonical_status": None,
        "projection_generation": "projection-1",
        "profile_generation": "profile-1",
        "visibility": "unavailable",
        "idempotency_key_matches": None,
    }


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
    _assert_sdk_compatible_unavailable(response.json())


def test_endpoint_timeout_preserves_sdk_generation_bindings() -> None:
    class Handler:
        async def execute(self, _query):
            raise TimeoutError("canonical reconciliation timed out")

    response = _client(Handler()).post("/v1/documents/reconcile-exact", json=_body())

    assert response.status_code == 200
    _assert_sdk_compatible_unavailable(response.json())


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
    app = _client(handler).app

    @app.post("/native-body-parsing")
    async def native_body_parsing(_body: dict) -> None:
        raise AssertionError("must not execute")

    parsing_errors: list[RequestValidationError] = []

    async def capture_parsing_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        parsing_errors.append(exc)
        return await request_validation_exception_handler(request, exc)

    app.add_exception_handler(RequestValidationError, capture_parsing_error)
    client = TestClient(app)
    expected = client.post(
        "/native-body-parsing",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    response = client.post(
        "/v1/documents/reconcile-exact",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == expected.status_code == 422
    assert response.json() == expected.json() == {
        "detail": [
            {
                "type": "json_invalid",
                "loc": ["body", 1],
                "msg": "JSON decode error",
                "input": {},
                "ctx": {"error": "Expecting property name enclosed in double quotes"},
            }
        ]
    }
    assert len(parsing_errors) == 2
    assert parsing_errors[1].errors() == parsing_errors[0].errors()
    assert parsing_errors[1].body == parsing_errors[0].body == "{"
    assert handler.calls == 0


def test_invalid_utf8_preserves_fastapi_body_parsing_response() -> None:
    class Handler:
        calls = 0

        async def execute(self, _query):
            self.calls += 1

    handler = Handler()
    app = _client(handler).app

    @app.post("/native-body-parsing")
    async def native_body_parsing(_body: dict) -> None:
        raise AssertionError("must not execute")

    client = TestClient(app)
    expected = client.post(
        "/native-body-parsing",
        content=b'"\xff"',
        headers={"content-type": "application/json"},
    )
    response = client.post(
        "/v1/documents/reconcile-exact",
        content=b'"\xff"',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == expected.status_code == 400
    assert response.json() == expected.json() == {
        "detail": "There was an error parsing the body"
    }
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


@pytest.mark.parametrize("body", [[], None, "not-an-object", 7])
def test_auth_runs_before_non_object_contract_validation(body) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def reject_request() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    app.dependency_overrides[require_service_token] = reject_request
    response = TestClient(app).post(
        "/v1/documents/reconcile-exact",
        content=json.dumps(body),
    )

    assert response.status_code == 401


@pytest.mark.parametrize("deadline_ms", [50.0, "50"])
def test_deadline_uses_the_typed_field_coercion(deadline_ms) -> None:
    class Handler:
        async def execute(self, _query):
            await asyncio.sleep(0.2)

    response = _client(Handler()).post(
        "/v1/documents/reconcile-exact",
        json=_body(deadline_ms=deadline_ms),
    )

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "unavailable"


@pytest.mark.parametrize(
    "content_type", ["application/json", "application/vnd.infinity+json"]
)
def test_fastapi_compatible_json_media_types_remain_accepted(content_type) -> None:
    class Handler:
        async def execute(self, query):
            return ingestion.ExactDocumentReconciliation("absent", query.identity)

    response = _client(Handler()).post(
        "/v1/documents/reconcile-exact",
        content=json.dumps(_body()).encode(),
        headers={"content-type": content_type},
    )

    assert response.status_code == 200
    assert response.json()["data"]["state"] == "absent"


def test_absent_content_type_matches_native_typed_fastapi_validation() -> None:
    class Handler:
        calls = 0

        async def execute(self, _query):
            self.calls += 1

    handler = Handler()
    app = _client(handler).app
    native_calls = 0

    @app.post("/native-body-parsing")
    async def native_body_parsing(
        _body: ReconcileExactDocumentHttpRequest,
    ) -> None:
        nonlocal native_calls
        native_calls += 1

    client = TestClient(app)
    content = json.dumps(_body()).encode()
    expected = client.post("/native-body-parsing", content=content)
    response = client.post("/v1/documents/reconcile-exact", content=content)

    assert response.status_code == expected.status_code == 422
    assert response.json() == expected.json()
    assert any(
        error["type"] == "model_attributes_type" and error["loc"] == ["body"]
        for error in response.json()["detail"]
    )
    assert native_calls == handler.calls == 0


def test_unsupported_media_type_still_authenticates_before_typed_validation() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def reject_request() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    app.dependency_overrides[require_service_token] = reject_request
    response = TestClient(app).post(
        "/v1/documents/reconcile-exact",
        content=json.dumps(_body()),
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("content", "content_type"),
    [(b"", "application/json"), (b"{", "text/plain")],
    ids=["empty-body", "malformed-non-json"],
)
def test_auth_runs_before_empty_or_non_json_body_validation(
    content: bytes, content_type: str
) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def reject_request() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    app.dependency_overrides[require_service_token] = reject_request
    response = TestClient(app).post(
        "/v1/documents/reconcile-exact",
        content=content,
        headers={"content-type": content_type},
    )

    assert response.status_code == 401


def test_unrelated_authorization_timeout_is_not_translated() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    async def fail_authorization() -> None:
        raise TimeoutError("authorization backend timed out")

    app.dependency_overrides[require_service_token] = fail_authorization
    with pytest.raises(TimeoutError, match="authorization backend"):
        TestClient(app).post("/v1/documents/reconcile-exact", json=_body())


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


@pytest.mark.parametrize("cancellations", [1, 2])
def test_external_cancellation_drains_route_and_receiver_tasks(cancellations) -> None:
    async def scenario() -> None:
        authorization_started = asyncio.Event()
        authorization_finished = asyncio.Event()
        receiver_started = asyncio.Event()
        receiver_finished = asyncio.Event()
        body_delivered = False

        async def blocked_authorization() -> None:
            authorization_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.02)
                authorization_finished.set()

        async def receive():
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {
                    "type": "http.request",
                    "body": json.dumps(_body()).encode(),
                    "more_body": False,
                }
            receiver_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.02)
                receiver_finished.set()

        async def send(_message) -> None:
            return None

        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.dependency_overrides[require_service_token] = blocked_authorization
        current = asyncio.current_task()
        assert current is not None
        baseline = asyncio.all_tasks() - {current}
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
        await asyncio.wait_for(receiver_started.wait(), timeout=1)
        task.cancel()
        if cancellations == 2:
            asyncio.get_running_loop().call_later(0.005, task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert authorization_finished.is_set()
        assert receiver_finished.is_set()
        assert asyncio.all_tasks() - {current} == baseline

    asyncio.run(scenario())


def test_route_timeout_does_not_consume_repeated_external_cancellation() -> None:
    async def scenario() -> None:
        authorization_started = asyncio.Event()
        authorization_cleanup_started = asyncio.Event()
        authorization_finished = asyncio.Event()
        receiver_finished = asyncio.Event()
        body_delivered = False

        async def blocked_authorization() -> None:
            authorization_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                authorization_cleanup_started.set()
                await asyncio.sleep(0.04)
                authorization_finished.set()

        async def receive():
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {
                    "type": "http.request",
                    "body": json.dumps(_body(deadline_ms=50)).encode(),
                    "more_body": False,
                }
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.04)
                receiver_finished.set()

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
        await asyncio.wait_for(authorization_cleanup_started.wait(), timeout=1)
        task.cancel()
        asyncio.get_running_loop().call_later(0.005, task.cancel)

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert authorization_finished.is_set()
        assert receiver_finished.is_set()

    asyncio.run(scenario())
