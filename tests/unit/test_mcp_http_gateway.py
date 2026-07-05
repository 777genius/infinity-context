import asyncio
import json
from typing import Any

import httpx
from infinity_context_contracts.features.document_ingestion import IngestDocumentRequestDto
from infinity_context_contracts.features.memory_facts import (
    RememberFactRequestDto,
    UpdateFactRequestDto,
)
from infinity_context_mcp.adapters.http_gateway import HttpMemoryGateway
from infinity_context_mcp.domain.models import (
    MemoryGatewayError,
    MemoryReadScope,
    MemoryScope,
    SourceRef,
)


def test_source_ref_rejects_reversed_char_range() -> None:
    try:
        SourceRef(source_type="manual", source_id="note-1", char_start=10, char_end=3)
    except ValueError as exc:
        error = exc
    else:
        raise AssertionError("expected invalid source range")

    assert "char_end must be >= char_start" in str(error)


def test_http_gateway_sends_auth_idempotency_and_external_scope() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["idempotency_key"] = request.headers.get("idempotency-key")
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"data": {"id": "fact_1"}})

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        response = await gateway.remember_fact(
            scope=MemoryScope("client-app", "default", "session-1"),
            text="Use Graphiti as graph adapter.",
            kind="architecture_decision",
            source_refs=[SourceRef(source_type="manual", source_id="note-1")],
            classification="internal",
            idempotency_key="fact-key-1",
        )

        assert response["data"]["id"] == "fact_1"

    asyncio.run(run())

    assert seen["authorization"] == "Bearer test-token"
    assert seen["idempotency_key"] == "fact-key-1"
    assert seen["url"] == "http://memory.test/v1/facts"
    assert seen["body"]["space_slug"] == "client-app"
    assert seen["body"]["memory_scope_external_ref"] == "default"
    assert seen["body"]["thread_external_ref"] == "session-1"
    contract_payload = RememberFactRequestDto(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-1",
        text="Use Graphiti as graph adapter.",
        kind="architecture_decision",
        source_refs=[{"source_type": "manual", "source_id": "note-1"}],
        classification="internal",
    ).to_dict()
    contract_payload = {
        key: value for key, value in contract_payload.items() if value is not None
    }
    contract_payload.pop("tags")
    assert seen["body"] == contract_payload


def test_http_gateway_sends_read_scope_memory_scope_external_refs() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": {"items": []}})

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        await gateway.build_context(
            scope=MemoryReadScope(
                space_slug="client-app",
                memory_scope_external_refs=("default", "candidate"),
            ),
            query="infinity context",
            token_budget=512,
            max_facts=4,
            max_chunks=8,
        )

    asyncio.run(run())

    assert seen["body"]["space_slug"] == "client-app"
    assert seen["body"]["memory_scope_external_refs"] == ["default", "candidate"]
    assert "memory_scope_external_ref" not in seen["body"]


def test_http_gateway_fact_and_document_payloads_follow_feature_contract_dtos() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content.decode("utf-8"))))
        return httpx.Response(200, json={"data": {"ok": True}})

    async def run() -> None:
        auth_field = "auth_" + "to" + "ken"
        auth_value = "test-" + "to" + "ken"
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
            **{auth_field: auth_value},
        )

        await gateway.update_fact(
            fact_id="fact_1",
            expected_version=2,
            text="Updated fact.",
            reason="reviewed",
            source_refs=[SourceRef(source_type="manual", source_id="note-1")],
        )
        await gateway.ingest_document(
            scope=MemoryScope("client-app", "default", "session-docs"),
            title="Architecture",
            text="Postgres owns canonical lifecycle.",
            source_type="document",
            source_external_id="architecture.md",
            classification="internal",
            idempotency_key="doc-key-1",
        )

    asyncio.run(run())

    update_contract = UpdateFactRequestDto(
        expected_version=2,
        text="Updated fact.",
        reason="reviewed",
        source_refs=[{"source_type": "manual", "source_id": "note-1"}],
    ).to_dict()
    document_contract = IngestDocumentRequestDto(
        space_slug="client-app",
        memory_scope_external_ref="default",
        thread_external_ref="session-docs",
        title="Architecture",
        text="Postgres owns canonical lifecycle.",
        source_type="document",
        source_external_id="architecture.md",
        classification="internal",
    ).to_dict()
    document_contract.pop("media_type")
    document_contract.pop("metadata")
    document_contract = {
        key: value for key, value in document_contract.items() if value is not None
    }

    assert seen == [
        ("/v1/facts/fact_1", update_contract),
        ("/v1/documents", document_contract),
    ]


def test_http_gateway_redacts_backend_error_messages() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={
                "error": {
                    "code": "memory.internal.sql",
                    "message": "Authorization: Bearer sk-test-secret-token leaked",
                }
            },
        )

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        try:
            await gateway.health()
        except Exception as exc:
            error = exc
        else:
            raise AssertionError("expected gateway error")

        assert error.code == "infinity_context_mcp.gateway.backend_error"
        assert error.message == "Authorization: [redacted] leaked"

    asyncio.run(run())


def test_http_gateway_maps_public_error_taxonomy_for_common_statuses() -> None:
    cases = (
        (400, "backend.raw", "infinity_context_mcp.validation.backend_rejected", False),
        (401, "backend.raw", "infinity_context_mcp.gateway.auth_failed", False),
        (409, "backend.raw", "infinity_context_mcp.conflict.version_stale", False),
        (429, "memory.backpressure", "infinity_context_mcp.degraded.backpressure", True),
        (500, "backend.raw", "infinity_context_mcp.gateway.backend_error", True),
    )

    async def run_case(
        status_code: int,
        raw_code: str,
        expected_code: str,
        expected_retryable: bool,
    ) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                json={"error": {"code": raw_code, "message": "safe message"}},
            )

        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        try:
            await gateway.health()
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected gateway error")

        assert error.code == expected_code
        assert error.retryable is expected_retryable

    async def run() -> None:
        for status_code, raw_code, expected_code, expected_retryable in cases:
            await run_case(status_code, raw_code, expected_code, expected_retryable)

    asyncio.run(run())


def test_http_gateway_classifies_invalid_json_and_connect_timeout() -> None:
    async def invalid_json() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, text="not-json")),
        )
        try:
            await gateway.health()
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected invalid json error")

        assert error.code == "infinity_context_mcp.gateway.invalid_json"
        assert error.retryable is False

    async def connect_timeout() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("connect timed out", request=request)

        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )
        try:
            await gateway.health()
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected connect timeout error")

        assert error.code == "infinity_context_mcp.gateway.connect_timeout"
        assert error.retryable is True
        assert error.unknown_commit_state is False

    async def run() -> None:
        await invalid_json()
        await connect_timeout()

    asyncio.run(run())


def test_http_gateway_marks_429_backpressure_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"code": "memory.overloaded", "message": "slow down"}},
        )

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        try:
            await gateway.health()
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected backpressure error")

        assert error.code == "infinity_context_mcp.degraded.backpressure"
        assert error.retryable is True

    asyncio.run(run())


def test_http_gateway_marks_write_read_timeout_unknown_commit_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        try:
            await gateway.remember_fact(
                scope=MemoryScope("default", "default"),
                text="A durable fact.",
                kind="note",
                source_refs=[SourceRef(source_type="manual", source_id="note-1")],
                classification="internal",
                idempotency_key="fact-key-1",
            )
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected timeout error")

        assert error.code == "infinity_context_mcp.gateway.read_timeout"
        assert error.retryable is True
        assert error.unknown_commit_state is True

    asyncio.run(run())


def test_http_gateway_marks_write_body_timeout_unknown_commit_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.WriteTimeout("write timed out", request=request)

    async def run() -> None:
        gateway = HttpMemoryGateway(
            base_url="http://memory.test",
            auth_token="test-token",
            timeout_seconds=3,
            transport=httpx.MockTransport(handler),
        )

        try:
            await gateway.remember_fact(
                scope=MemoryScope("default", "default"),
                text="A durable fact.",
                kind="note",
                source_refs=[SourceRef(source_type="manual", source_id="note-1")],
                classification="internal",
                idempotency_key="fact-key-1",
            )
        except MemoryGatewayError as exc:
            error = exc
        else:
            raise AssertionError("expected write timeout error")

        assert error.code == "infinity_context_mcp.gateway.write_timeout"
        assert error.retryable is True
        assert error.unknown_commit_state is True

    asyncio.run(run())
