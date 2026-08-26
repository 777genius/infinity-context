from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_server.api import auth
from infinity_context_server.auth_tokens import ActiveServiceToken
from starlette.requests import Request


def _request(**changes) -> Request:
    body = {
        "contract_version": "document-reconciliation.v1",
        "space_id": "space-a",
        "memory_scope_id": "scope-a",
        "source_type": "opaque-kind",
        "source_external_id": "opaque-id",
    }
    body.update(changes)
    encoded = json.dumps(body).encode()
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": encoded, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/documents/reconcile-exact",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "scheme": "http",
        },
        receive,
    )


def _token(*permissions: str) -> ActiveServiceToken:
    return ActiveServiceToken(
        token_id="token-a",
        space_id="space-a",
        memory_scope_ids=frozenset({"scope-a"}),
        permissions=frozenset(permissions),
    )


def test_exact_reconciliation_authorizes_memory_read_and_forbids_write_only_token() -> None:
    auth._ensure_permission(_request(), _token("memory:read"))
    with pytest.raises(MemoryForbiddenError, match="required permission"):
        auth._ensure_permission(_request(), _token("memory:write"))


def test_exact_reconciliation_enforces_space_and_memory_scope_token_bounds(monkeypatch) -> None:
    async def space_matches(_container, token_scope, requested_scope):
        return token_scope == requested_scope

    async def memory_scope_matches(_container, token_scope, requested_scope, *, space_scope=None):
        return (
            space_scope == "space-a"
            and token_scope == requested_scope
            and requested_scope == "scope-a"
        )

    monkeypatch.setattr(auth, "space_matches", space_matches)
    monkeypatch.setattr(auth, "memory_scope_matches", memory_scope_matches)

    async def requested_spaces(_container, request):
        return {str((await request.json())["space_id"])}

    async def requested_memory_scopes(_container, request):
        return {str((await request.json())["memory_scope_id"])}

    monkeypatch.setattr(auth, "_requested_space_refs", requested_spaces)
    monkeypatch.setattr(auth, "_requested_memory_scope_refs", requested_memory_scopes)
    container = SimpleNamespace(
        settings=SimpleNamespace(
            default_space_slug="default",
            default_memory_scope_external_ref="default",
        )
    )

    async def allowed() -> None:
        request = _request()
        await auth._ensure_scoped_token_can_access_request(
            container, request, _token("memory:read")
        )
        await auth._ensure_memory_scope_scoped_token_can_access_request(
            container, request, _token("memory:read")
        )

    asyncio.run(allowed())

    async def crossed() -> None:
        request = _request(memory_scope_id="scope-b")
        await auth._ensure_memory_scope_scoped_token_can_access_request(
            container, request, _token("memory:read")
        )

    with pytest.raises(MemoryForbiddenError, match="requested memory_scope"):
        asyncio.run(crossed())
