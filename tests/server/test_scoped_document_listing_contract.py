"""Black-box contract tests for scoped canonical document enumeration."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_server.api.auth import _ensure_repository_token_endpoint_isolated
from infinity_context_server.auth_tokens import ActiveServiceToken
from infinity_context_server.config import DeployProfile, Settings
from infinity_context_server.main import create_app
from starlette.requests import Request

ROOT_HEADERS = {"Authorization": "Bearer root-token"}


def _make_client(database_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                deploy_profile=DeployProfile.TEST,
                database_url=f"sqlite+aiosqlite:///{database_path}",
                auto_create_schema=True,
                service_token="root-token",
                qdrant_enabled=False,
                graphiti_enabled=False,
                embeddings_enabled=False,
            )
        )
    )


def _ingest(
    client: TestClient,
    marker: str,
    *,
    space: str = "list-contract",
    memory_scope: str = "meeting",
    thread: str | None = "thread-a",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "space_slug": space,
        "memory_scope_external_ref": memory_scope,
        "title": marker,
        "text": f"body {marker}",
        "source_type": "meeting_transcript",
        "source_external_id": marker,
    }
    if thread is not None:
        payload["thread_external_ref"] = thread
    response = client.post("/v1/documents", json=payload, headers=ROOT_HEADERS)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _list(
    client: TestClient,
    *,
    space: str = "list-contract",
    memory_scope: str = "meeting",
    thread: str | None = "thread-a",
    **filters: object,
) -> Any:
    params: dict[str, object] = {
        "space_slug": space,
        "memory_scope_external_ref": memory_scope,
        **filters,
    }
    if thread is not None:
        params["thread_external_ref"] = thread
    return client.get("/v1/documents", params=params, headers=ROOT_HEADERS)


def _external_ids(response: Any) -> list[str]:
    return [str(item["source_external_id"]) for item in response.json()["data"]]


def test_list_documents_is_exactly_scoped_and_defaults_to_active(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.db"
    with _make_client(database_path) as client:
        target = _ingest(client, "TARGET_THREAD_A")
        global_sentinel = _ingest(client, "GLOBAL_SENTINEL", thread=None)
        _ingest(client, "OTHER_THREAD_SENTINEL", thread="thread-b")
        _ingest(client, "OTHER_SCOPE_SENTINEL", memory_scope="other")
        _ingest(client, "OTHER_SPACE_SENTINEL", space="other-space")
        deleted = _ingest(client, "DELETED_TARGET")
        deleted_response = client.delete(f"/v1/documents/{deleted['id']}", headers=ROOT_HEADERS)
        assert deleted_response.status_code == 200, deleted_response.text

        thread_page = _list(client)
        global_page = _list(client, thread=None)
        deleted_page = _list(client, status="deleted")
        source_page = _list(client, source_external_id="TARGET_THREAD_A")
        missing_source_page = _list(client, source_external_id="TARGET_THREAD")

    assert thread_page.status_code == 200, thread_page.text
    assert thread_page.json()["next_cursor"] is None
    assert _external_ids(thread_page) == ["TARGET_THREAD_A"]
    assert thread_page.json()["data"][0]["id"] == target["id"]
    assert _external_ids(global_page) == ["GLOBAL_SENTINEL"]
    assert global_page.json()["data"][0]["id"] == global_sentinel["id"]
    assert _external_ids(deleted_page) == ["DELETED_TARGET"]
    assert _external_ids(source_page) == ["TARGET_THREAD_A"]
    assert missing_source_page.json() == {"data": [], "next_cursor": None}


def test_list_documents_keyset_pagination_has_no_duplicates_or_skips_on_ties(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    with _make_client(database_path) as client:
        documents = [_ingest(client, f"PAGE_{index}") for index in range(5)]
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE memory_documents SET updated_at = ? WHERE id IN (?, ?, ?, ?, ?)",
                (
                    "2026-08-19 12:00:00.000000",
                    *(document["id"] for document in documents),
                ),
            )

        seen: list[str] = []
        cursor: str | None = None
        while True:
            page = _list(client, limit=2, **({"cursor": cursor} if cursor else {}))
            assert page.status_code == 200, page.text
            seen.extend(item["id"] for item in page.json()["data"])
            cursor = page.json()["next_cursor"]
            if cursor is None:
                break

    expected = sorted((str(document["id"]) for document in documents), reverse=True)
    assert seen == expected
    assert len(seen) == len(set(seen)) == 5


def test_list_documents_cursor_is_opaque_bound_to_kind_scope_and_filters(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    with _make_client(database_path) as client:
        _ingest(client, "CURSOR_A")
        _ingest(client, "CURSOR_B")
        _ingest(client, "CURSOR_OTHER_SCOPE", memory_scope="other")
        page = _list(client, limit=1)
        assert page.status_code == 200, page.text
        cursor = page.json()["next_cursor"]
        assert cursor

        from infinity_context_server.pagination import encode_cursor

        wrong_kind_cursor = encode_cursor("document_chunks", sequence=0, id="chunk")
        responses = (
            _list(client, cursor="not-a-valid-cursor"),
            _list(client, cursor=wrong_kind_cursor),
            _list(client, memory_scope="other", cursor=cursor),
            _list(client, cursor=cursor, source_external_id="CURSOR_A"),
            _list(client, cursor=cursor, status="deleted"),
        )

    for response in responses:
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "memory.validation"
    assert "CURSOR_A" not in cursor
    assert "CURSOR_B" not in cursor


def test_list_documents_missing_scope_and_auth_do_not_leak_or_create(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "memory.db"
    marker = "PRIVATE_DOCUMENT_MARKER"
    with _make_client(database_path) as client:
        target = _ingest(client, marker)
        spaces_before = client.get("/v1/spaces", headers=ROOT_HEADERS).json()["data"]
        missing_scope = _list(
            client,
            space="does-not-exist",
            memory_scope="does-not-exist",
            thread="does-not-exist",
        )
        spaces_after = client.get("/v1/spaces", headers=ROOT_HEADERS).json()["data"]
        unscoped = client.get("/v1/documents", headers=ROOT_HEADERS)
        partial_canonical_scope = client.get(
            "/v1/documents",
            params={"space_id": target["space_id"]},
            headers=ROOT_HEADERS,
        )
        partial_external_scope = client.get(
            "/v1/documents",
            params={"space_slug": "list-contract"},
            headers=ROOT_HEADERS,
        )
        missing_auth = client.get(
            "/v1/documents",
            params={
                "space_id": target["space_id"],
                "memory_scope_id": target["memory_scope_id"],
                "thread_id": target["thread_id"],
            },
        )
        wrong_scope = client.get(
            "/v1/documents",
            params={
                "space_id": target["space_id"],
                "memory_scope_id": "memory_scope_wrong",
                "thread_id": target["thread_id"],
            },
            headers=ROOT_HEADERS,
        )

    assert missing_scope.status_code == 200, missing_scope.text
    assert missing_scope.json() == {"data": [], "next_cursor": None}
    assert spaces_after == spaces_before
    assert missing_auth.status_code in {401, 403}
    assert wrong_scope.status_code == 400
    for response in (unscoped, partial_canonical_scope, partial_external_scope):
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "memory.validation"
    for response in (
        missing_scope,
        missing_auth,
        wrong_scope,
        unscoped,
        partial_canonical_scope,
        partial_external_scope,
    ):
        assert marker not in response.text


def test_repository_scoped_token_is_denied_by_the_document_collection_route() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/v1/documents", "headers": []})
    repository_token = ActiveServiceToken(
        token_id="repository-token",
        space_id="space",
        memory_scope_ids=frozenset({"scope"}),
        permissions=frozenset({"memory:read"}),
        repository_id="repository",
        code_scope_id="code-scope",
    )

    with pytest.raises(MemoryForbiddenError, match="without repository isolation"):
        _ensure_repository_token_endpoint_isolated(request, repository_token)


def test_openapi_describes_scoped_document_listing_contract(tmp_path: Path) -> None:
    body = _make_client(tmp_path / "memory.db").app.openapi()
    operation = body["paths"]["/v1/documents"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert {
        "space_id",
        "memory_scope_id",
        "thread_id",
        "space_slug",
        "memory_scope_external_ref",
        "thread_external_ref",
        "status",
        "source_external_id",
        "limit",
        "cursor",
    }.issubset(parameters)
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 500,
        "minimum": 1,
        "default": 100,
        "title": "Limit",
    }
    assert parameters["status"]["schema"]["default"] == "active"

    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    if "$ref" in response_schema:
        response_schema = body["components"]["schemas"][response_schema["$ref"].rsplit("/", 1)[-1]]
    assert {"data", "next_cursor"}.issubset(response_schema["properties"])
