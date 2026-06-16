from __future__ import annotations

import asyncio
from typing import Any

import httpx
from memo_stack_mcp.adapters.http_gateway import HttpMemoryGateway
from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import MemoryMcpSettings
from memo_stack_mcp.domain.models import MemoryScope


class MemoryBrowserGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_memory_browser(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_memory_browser", kwargs))
        return {
            "data": {
                "generated_at": "2026-06-17T00:00:00+00:00",
                "memory_scope": {
                    "id": "memory_scope_1",
                    "external_ref": kwargs["scope"].memory_scope_external_ref,
                },
                "facts": [{"id": "fact_1", "text": "Alex confirmed Project Atlas."}],
                "episodes": [{"id": "episode_1", "source_type": "transcript"}],
                "documents": [{"id": "doc_1", "title": "Project Atlas notes"}],
                "chunks": [{"id": "chunk_1", "document_id": "doc_1"}],
                "extraction_jobs": [{"id": "extract_1", "status": "pending"}],
                "threads": [{"id": "thread_1", "external_ref": "alex-call"}],
                "captures": [{"id": "cap_1", "evidence_refs": [{"source_id": "asset_1"}]}],
                "assets": [{"id": "asset_1", "filename": "atlas.png"}],
                "anchors": [{"id": "anchor_1", "label": "Alex"}],
                "context_links": [{"id": "ctx_1", "status": "active"}],
                "context_link_suggestions": [{"id": "ctxsug_1", "status": "approved"}],
                "stats": {"active_context_links": 1},
                "diagnostics": {"browser_version": "memory-browser-v1"},
            }
        }


def test_service_browses_memory_scope_with_bounded_filters() -> None:
    async def run() -> None:
        gateway = MemoryBrowserGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.browse_scope(
            space_slug="team",
            memory_scope_external_ref="project-atlas",
            limit=500,
            link_status="active",
            suggestion_status="approved",
        )

        assert result["ok"] is True
        assert result["data"]["memory_scope"]["external_ref"] == "project-atlas"
        assert result["data"]["facts"][0]["id"] == "fact_1"
        assert result["data"]["episodes"][0]["id"] == "episode_1"
        assert result["data"]["documents"][0]["id"] == "doc_1"
        assert result["data"]["chunks"][0]["id"] == "chunk_1"
        assert result["data"]["extraction_jobs"][0]["id"] == "extract_1"
        assert result["data"]["stats"]["active_context_links"] == 1
        assert result["diagnostics"]["warnings"] == ["limit_clamped_to_max"]
        call_name, payload = gateway.calls[0]
        assert call_name == "get_memory_browser"
        assert payload["scope"].space_slug == "team"
        assert payload["scope"].memory_scope_external_ref == "project-atlas"
        assert payload["limit"] == 200
        assert payload["fact_status"] == "active"
        assert payload["episode_status"] == "active"
        assert payload["document_status"] == "active"
        assert payload["chunk_status"] == "active"
        assert payload["extraction_status"] is None
        assert payload["thread_status"] == "active"
        assert payload["asset_status"] == "stored"
        assert payload["anchor_status"] == "active"
        assert payload["link_status"] == "active"
        assert payload["suggestion_status"] == "approved"

    asyncio.run(run())


def test_http_gateway_requests_memory_browser_read_model() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"data": {"stats": {"threads": 1}}})

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=5,
            transport=httpx.MockTransport(handler),
        )

        response = await gateway.get_memory_browser(
            scope=MemoryScope(
                space_slug="team",
                memory_scope_external_ref="project-atlas",
                thread_external_ref="ignored-by-browser",
            ),
            limit=25,
            fact_status="active",
            episode_status="active",
            document_status="active",
            chunk_status="active",
            extraction_status="pending",
            thread_status="active",
            capture_status=None,
            asset_status="stored",
            anchor_status="active",
            link_status="active",
            suggestion_status="approved",
        )

        assert response["data"]["stats"]["threads"] == 1

    asyncio.run(run())

    assert seen == [
        (
            "GET",
            "/v1/memory-browser",
            {
                "space_slug": "team",
                "memory_scope_external_ref": "project-atlas",
                "limit": "25",
                "fact_status": "active",
                "episode_status": "active",
                "document_status": "active",
                "chunk_status": "active",
                "extraction_status": "pending",
                "thread_status": "active",
                "asset_status": "stored",
                "anchor_status": "active",
                "link_status": "active",
                "suggestion_status": "approved",
            },
        )
    ]
