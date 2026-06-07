import asyncio
import json
from typing import Any

from mcp.shared.version import LATEST_PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS
from mcp_adapter_fakes import RecordingGateway
from memo_stack_mcp.application.service import MemoryToolService
from memo_stack_mcp.config import (
    MemoryMcpDeleteMode,
    MemoryMcpIngestMode,
    MemoryMcpSettings,
    MemoryMcpWriteMode,
    load_settings,
)
from memo_stack_mcp.domain.models import (
    MemoryGatewayError,
    MemoryReadScope,
    MemoryScope,
)
from memo_stack_mcp.server import create_mcp_server


def test_load_settings_uses_memory_service_token_fallback() -> None:
    settings = load_settings(
        {
            "MEMORY_SERVICE_TOKEN": "server-token",
            "MEMORY_MCP_API_URL": "http://memory.test/",
        }
    )

    assert settings.auth_token == "server-token"
    assert settings.api_url == "http://memory.test"
    assert settings.allow_deletes is True
    assert settings.delete_mode == MemoryMcpDeleteMode.OFF


def test_load_settings_parses_new_policy_modes() -> None:
    settings = load_settings(
        {
            "MEMORY_MCP_WRITE_MODE": "suggest",
            "MEMORY_MCP_DELETE_MODE": "explicit",
            "MEMORY_MCP_INGEST_MODE": "small_docs",
            "MEMORY_MCP_SMALL_DOC_MAX_CHARS": "1234",
        }
    )

    assert settings.write_mode == MemoryMcpWriteMode.SUGGEST
    assert settings.delete_mode == MemoryMcpDeleteMode.EXPLICIT
    assert settings.ingest_mode == MemoryMcpIngestMode.SMALL_DOCS
    assert settings.small_doc_max_chars == 1234
    assert settings.writes_enabled is True
    assert settings.deletes_enabled is True


def test_load_settings_uses_safe_policy_defaults() -> None:
    settings = load_settings({})

    assert settings.write_mode == MemoryMcpWriteMode.SUGGEST
    assert settings.delete_mode == MemoryMcpDeleteMode.OFF
    assert settings.ingest_mode == MemoryMcpIngestMode.SMALL_DOCS
    assert settings.small_doc_max_chars == 50_000


def test_mcp_sdk_protocol_version_is_explicitly_guarded() -> None:
    assert LATEST_PROTOCOL_VERSION == "2025-11-25"
    assert "2025-11-25" in SUPPORTED_PROTOCOL_VERSIONS


def test_service_profile_snapshot_export_and_import_are_policy_gated() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_profile_external_ref="backend",
            ),
        )
        snapshot = {
            "schema_version": 1,
            "facts": [{"id": "fact_1", "text": "Portable profile snapshot fact."}],
            "documents": [],
            "chunks": [],
            "source_refs": [],
        }

        exported = await service.export_profile_snapshot(redacted=True)
        dry_run = await service.import_profile_snapshot(snapshot=snapshot)
        refused = await service.import_profile_snapshot(
            snapshot=snapshot,
            dry_run=False,
            confirmed=False,
        )
        imported = await service.import_profile_snapshot(
            snapshot=snapshot,
            dry_run=False,
            confirmed=True,
            merge_strategy="create_new_profile",
            source_name="unit-snapshot",
        )

        assert exported["ok"] is True
        assert exported["data"]["status"] == "ok"
        assert exported["data"]["redacted"] is True
        assert exported["data"]["manifest"] == {}
        assert dry_run["data"]["dry_run"] is True
        assert refused["ok"] is False
        assert refused["error"]["code"] == "memo_stack_mcp.policy.explicit_confirmation_required"
        assert imported["ok"] is True
        assert imported["diagnostics"]["side_effects"] == ["imported_profile_snapshot"]
        assert (
            "export_profile_snapshot",
            {"scope": MemoryScope("project-a", "backend", None), "redacted": True},
        ) in gateway.calls
        assert gateway.calls[-1][0] == "import_profile_snapshot"
        assert gateway.calls[-1][1]["manifest"] is None
        assert gateway.calls[-1][1]["merge_strategy"] == "create_new_profile"
        assert gateway.calls[-1][1]["source_name"] == "unit-snapshot"

    asyncio.run(run())


def test_service_remember_fact_uses_default_scope_and_stable_idempotency() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_profile_external_ref="backend",
                write_mode=MemoryMcpWriteMode.DIRECT,
            ),
        )

        first = await service.remember_fact(
            text="Postgres is canonical truth.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )
        second = await service.remember_fact(
            text="Postgres is canonical truth.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert first["ok"] is True
        assert second["ok"] is True
        remember_calls = [call for name, call in gateway.calls if name == "remember_fact"]
        assert len(remember_calls) == 2
        first_call = remember_calls[0]
        second_call = remember_calls[1]
        assert first_call["scope"] == MemoryScope("project-a", "backend", None)
        assert first_call["idempotency_key"] == second_call["idempotency_key"]
        assert first_call["source_refs"][0].source_type == "manual"

    asyncio.run(run())


def test_service_remember_fact_dedupes_existing_active_fact() -> None:
    class DuplicateGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_existing",
                        "text": "Postgres is canonical truth.",
                    }
                ]
            }

    async def run() -> None:
        gateway = DuplicateGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(
            text="Postgres is canonical truth.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "fact_existing"
        assert result["data"]["status"] == "duplicate"
        assert result["data"]["safe_reason"] == "memo_stack_mcp.duplicate.existing_memory"
        assert result["diagnostics"]["side_effects"] == []
        assert "remember_fact" not in [name for name, _ in gateway.calls]

    asyncio.run(run())


def test_service_remember_fact_dedupes_semantic_equivalent_active_fact() -> None:
    class DuplicateGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_qdrant_documents",
                        "text": "Qdrant owns document vector retrieval.",
                    }
                ]
            }

    async def run() -> None:
        gateway = DuplicateGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(
            text="Docs retrieval should use Qdrant vectors.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "fact_qdrant_documents"
        assert result["data"]["status"] == "duplicate"
        assert result["data"]["safe_reason"] == "memo_stack_mcp.duplicate.existing_memory"
        assert [name for name, _ in gateway.calls] == ["list_facts"]

    asyncio.run(run())


def test_service_remember_fact_routes_negated_semantic_neighbor_to_review() -> None:
    class NegatedNeighborGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_qdrant_negated",
                        "text": "Qdrant should not use document vectors.",
                    }
                ]
            }

    async def run() -> None:
        gateway = NegatedNeighborGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(
            text="Docs retrieval should use Qdrant vectors.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "sug_1"
        assert result["data"]["status"] == "pending"
        assert result["diagnostics"]["side_effects"] == ["created_suggestion"]
        assert result["diagnostics"]["warnings"] == ["memo_stack_mcp.conflict.requires_review"]
        assert [name for name, _ in gateway.calls] == [
            "list_facts",
            "list_suggestions",
            "create_suggestion",
        ]
        assert gateway.calls[-1][1]["review_payload"] == {
            "conflicting_fact_id": "fact_qdrant_negated",
            "conflict_source": "mcp_preflight",
        }

    asyncio.run(run())


def test_service_remember_fact_does_not_dedupe_different_engine_neighbor() -> None:
    class DifferentEngineGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_qdrant_documents",
                        "text": "Qdrant owns document vector retrieval.",
                    }
                ]
            }

    async def run() -> None:
        gateway = DifferentEngineGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(
            text="Postgres owns document vector retrieval.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "sug_1"
        assert result["data"]["status"] == "pending"
        assert result["diagnostics"]["side_effects"] == ["created_suggestion"]
        assert [name for name, _ in gateway.calls] == [
            "list_facts",
            "list_suggestions",
            "create_suggestion",
        ]
        assert gateway.calls[-1][1]["review_payload"] == {
            "conflicting_fact_id": "fact_qdrant_documents",
            "conflict_source": "mcp_preflight",
        }

    asyncio.run(run())


def test_service_remember_fact_routes_conflicting_existing_fact_to_review() -> None:
    class ConflictGateway(RecordingGateway):
        async def list_facts(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("list_facts", kwargs))
            return {
                "data": [
                    {
                        "id": "fact_mysql",
                        "text": "Use MySQL as canonical truth.",
                    }
                ]
            }

    async def run() -> None:
        gateway = ConflictGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(
            text="Use Postgres as canonical truth.",
            kind="architecture_decision",
            source_type="manual",
            source_id="manual-note-1",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "sug_1"
        assert result["diagnostics"]["side_effects"] == ["created_suggestion"]
        assert result["diagnostics"]["warnings"] == ["memo_stack_mcp.conflict.requires_review"]
        assert "remember_fact" not in [name for name, _ in gateway.calls]
        assert [name for name, _ in gateway.calls] == [
            "list_facts",
            "list_suggestions",
            "create_suggestion",
        ]

    asyncio.run(run())


def test_service_remember_fact_routes_low_trust_source_to_suggestion() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_profile_external_ref="backend",
                write_mode=MemoryMcpWriteMode.DIRECT,
            ),
        )

        result = await service.remember_fact(
            text="Agent inferred this fact from task output.",
            kind="note",
        )

        assert result["ok"] is True
        assert result["data"]["status"] == "pending"
        assert result["diagnostics"]["policy"]["decision"] == "allow_suggestion"
        assert gateway.calls[0][0] == "create_suggestion"
        assert gateway.calls[0][1]["safe_reason"] == "memo_stack_mcp.policy.source_requires_review"

    asyncio.run(run())


def test_service_blocks_destructive_tools_when_disabled() -> None:
    async def run() -> None:
        service = MemoryToolService(
            gateway=RecordingGateway(),
            settings=MemoryMcpSettings(allow_deletes=False),
        )

        result = await service.forget_fact(fact_id="fact_1")

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.policy.delete_mode_off"
        assert (
            result["error"]["safe_message"]
            == "Memo Stack MCP deletes are disabled by local policy"
        )
        assert result["diagnostics"]["schema_version"] == "mcp.memo_stack.v1"

    asyncio.run(run())


def test_service_status_surfaces_capability_diagnostics() -> None:
    async def run() -> None:
        service = MemoryToolService(
            gateway=RecordingGateway(),
            settings=MemoryMcpSettings(),
        )

        result = await service.status()

        assert result["ok"] is True
        assert result["diagnostics"]["schema_version"] == "mcp.memo_stack.v1"
        assert result["data"]["readiness"]["read_ready"] is True
        assert result["data"]["readiness"]["write_ready"] is True
        assert result["data"]["readiness"]["projection_ready"] is True
        assert result["data"]["auth_configured"] is False
        assert result["data"]["capability_diagnostics"] == [
            {
                "adapter_name": "graphiti",
                "capability": "temporal_fact_graph",
                "enabled": True,
                "healthy": True,
                "status": "ok",
            }
        ]

    asyncio.run(run())


def test_mcp_search_structured_output_preserves_backend_diagnostics() -> None:
    class DiagnosticsGateway(RecordingGateway):
        async def build_context(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("build_context", kwargs))
            return {
                "data": {
                    "rendered_text": "Graphiti and Qdrant evidence.",
                    "items": [],
                    "diagnostics": {
                        "graph_status": "ok",
                        "graph_hydrated_count": 1,
                        "vector_status": "ok",
                        "vector_hydrated_count": 1,
                    },
                }
            }

    async def run() -> None:
        server = create_mcp_server(
            service=MemoryToolService(gateway=DiagnosticsGateway(), settings=MemoryMcpSettings())
        )

        result = await server.call_tool("memory_search", {"query": "Graphiti Qdrant"})

        assert result.structuredContent["ok"] is True
        assert result.structuredContent["data"]["diagnostics"] == {
            "graph_status": "ok",
            "graph_hydrated_count": 1,
            "vector_status": "ok",
            "vector_hydrated_count": 1,
        }

    asyncio.run(run())


def test_mcp_digest_structured_output_and_scope() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        server = create_mcp_server(
            service=MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())
        )

        result = await server.call_tool(
            "memory_digest",
            {
                "topic": "Graphiti decisions",
                "profile_external_refs": ["engineering", "product"],
                "include_related": False,
            },
        )

        assert result.structuredContent["ok"] is True
        assert result.structuredContent["data"]["digest_id"] == "dig_1"
        assert result.structuredContent["data"]["diagnostics"] == {"evidence_only": True}
        assert result.structuredContent["data"]["rendered_markdown_truncated"] is False
        assert gateway.calls[0][0] == "build_digest"
        assert gateway.calls[0][1]["topic"] == "Graphiti decisions"
        assert gateway.calls[0][1]["include_related"] is False
        assert gateway.calls[0][1]["scope"].profile_external_refs == (
            "engineering",
            "product",
        )

    asyncio.run(run())


def test_service_status_never_echoes_auth_token() -> None:
    async def run() -> None:
        service = MemoryToolService(
            gateway=RecordingGateway(),
            settings=MemoryMcpSettings(auth_token="sk-test-secret-token"),
        )

        result = await service.status()
        serialized = json.dumps(result, ensure_ascii=False)

        assert result["ok"] is True
        assert result["data"]["auth_configured"] is True
        assert "sk-test" not in serialized
        assert "secret-token" not in serialized

    asyncio.run(run())


def test_service_search_uses_read_scope_for_multiple_profiles() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                default_space_slug="project-a",
                default_profile_external_ref="backend",
            ),
        )

        result = await service.search(
            query="memory architecture",
            profile_external_refs=["backend", "frontend"],
        )

        assert result["ok"] is True
        assert result["data"]["requested_profile_external_refs"] == ["backend", "frontend"]
        assert gateway.calls[0] == (
            "build_context",
            {
                "scope": MemoryReadScope(
                    space_slug="project-a",
                    profile_external_refs=("backend", "frontend"),
                    thread_external_ref=None,
                ),
                "query": "memory architecture",
                "token_budget": 1800,
                "max_facts": 12,
                "max_chunks": 12,
            },
        )

    asyncio.run(run())


def test_service_search_clamps_budget_and_limits() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                min_token_budget=256,
                max_token_budget=6000,
                max_search_items=50,
            ),
        )

        result = await service.search(
            query="memory architecture",
            token_budget=100_000,
            max_facts=500,
            max_chunks=500,
        )

        assert result["ok"] is True
        assert result["data"]["effective_token_budget"] == 6000
        assert result["data"]["budget_clamped"] is True
        assert result["data"]["effective_max_facts"] == 50
        assert result["data"]["effective_max_chunks"] == 50
        assert result["diagnostics"]["warnings"] == [
            "token_budget_clamped_to_max",
            "max_facts_clamped_to_max",
            "max_chunks_clamped_to_max",
        ]
        call = gateway.calls[0][1]
        assert call["token_budget"] == 6000
        assert call["max_facts"] == 50
        assert call["max_chunks"] == 50

    asyncio.run(run())


def test_service_search_passes_taxonomy_filters_when_set() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.search(
            query="Graphiti memory",
            category="Architecture",
            tags_any=["Graphiti"],
            tags_all=["Memory"],
            tags_none=["Redis"],
        )

        assert result["ok"] is True
        call = gateway.calls[0][1]
        assert call["category"] == "architecture"
        assert call["tags_any"] == ["graphiti"]
        assert call["tags_all"] == ["memory"]
        assert call["tags_none"] == ["redis"]

    asyncio.run(run())


def test_service_search_reports_rendered_text_truncation() -> None:
    class LongContextGateway(RecordingGateway):
        async def build_context(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("build_context", kwargs))
            return {"data": {"rendered_text": "x" * 50, "items": []}}

    async def run() -> None:
        service = MemoryToolService(
            gateway=LongContextGateway(),
            settings=MemoryMcpSettings(max_tool_text_chars=10),
        )

        result = await service.search(query="long context")

        assert result["ok"] is True
        assert result["data"]["rendered_text"] == "x" * 10 + "\n[truncated]"
        assert result["data"]["rendered_text_truncated"] is True
        assert result["data"]["rendered_text_original_chars"] == 50

    asyncio.run(run())


def test_service_search_adds_fact_resource_links() -> None:
    class SearchGateway(RecordingGateway):
        async def build_context(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("build_context", kwargs))
            return {
                "data": {
                    "rendered_text": "Postgres is canonical.",
                    "items": [{"id": "fact_1", "text": "Postgres is canonical."}],
                }
            }

    async def run() -> None:
        service = MemoryToolService(gateway=SearchGateway(), settings=MemoryMcpSettings())

        result = await service.search(query="Postgres")

        assert result["data"]["items"][0]["resource_uri"] == "memory://fact/fact_1"
        assert result["data"]["resource_uris"] == ["memory://fact/fact_1"]

    asyncio.run(run())


def test_service_search_redacts_sensitive_retrieved_text() -> None:
    class SensitiveContextGateway(RecordingGateway):
        async def build_context(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("build_context", kwargs))
            secret = "password=bench-secret-search-output-alpha"
            return {
                "data": {
                    "rendered_text": f"Relevant memory says {secret}. Keep review-gated.",
                    "items": [
                        {
                            "item_id": "chunk_1",
                            "item_type": "chunk",
                            "text": f"Tail chunk includes {secret}. Keep review-gated.",
                            "source_refs": [{"quote_preview": f"quote {secret}"}],
                        }
                    ],
                }
            }

    async def run() -> None:
        service = MemoryToolService(
            gateway=SensitiveContextGateway(),
            settings=MemoryMcpSettings(),
        )

        result = await service.search(query="review-gated hooks")
        serialized = json.dumps(result, ensure_ascii=False)

        assert result["ok"] is True
        assert "bench-secret-search-output-alpha" not in serialized
        assert "[redacted]" in result["data"]["rendered_text"]
        assert "[redacted]" in result["data"]["items"][0]["text"]
        assert "[redacted]" in result["data"]["items"][0]["source_refs"][0]["quote_preview"]
        assert result["data"]["rendered_text_original_chars"] == len(
            result["data"]["rendered_text"]
        )

    asyncio.run(run())


def test_service_search_rejects_thread_scope_with_multiple_profiles() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.search(
            query="memory architecture",
            profile_external_refs=["backend", "frontend"],
            thread_external_ref="session-1",
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.validation.invalid_scope"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_status_degrades_when_capabilities_unavailable() -> None:
    class SafeCapabilitiesDownGateway(RecordingGateway):
        async def capabilities(self) -> dict[str, Any]:

            raise MemoryGatewayError(
                status_code=503,
                code="memory.internal.database_error",
                message="database unavailable",
                retryable=True,
            )

    async def run() -> None:
        service = MemoryToolService(
            gateway=SafeCapabilitiesDownGateway(),
            settings=MemoryMcpSettings(),
        )

        result = await service.status()

        assert result["ok"] is True
        assert result["data"]["readiness"]["degraded"] is True
        assert result["data"]["readiness"]["write_ready"] is False
        assert "capabilities.unavailable" in result["data"]["readiness"]["degraded_reasons"]
        assert result["diagnostics"]["degraded"] is True
        assert result["diagnostics"]["backend"]["capabilities_error"]["code"] == (
            "memo_stack_mcp.gateway.backend_error"
        )

    asyncio.run(run())


def test_service_rejects_invalid_kind_before_gateway() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        result = await service.remember_fact(text="A durable fact.", kind="runbook")

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.validation.invalid_input"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_sanitizes_absolute_source_path() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.remember_fact(
            text="A durable fact.",
            source_type="manual",
            source_id="/Users/belief/private/project/note.md",
        )

        assert result["ok"] is True
        source_ref = gateway.calls[0][1]["source_refs"][0]
        assert source_ref.source_id.startswith("mcp-source-path:")
        assert "Users" not in source_ref.source_id

    asyncio.run(run())


def test_service_rejects_token_source_id_and_quote_preview() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        source_result = await service.remember_fact(
            text="A durable fact.",
            source_type="manual",
            source_id="Bearer sk-test-secret-token",
        )
        quote_result = await service.remember_fact(
            text="A durable fact.",
            source_type="manual",
            source_id="safe-source",
            quote_preview="Authorization: Bearer sk-test-secret-token",
        )

        assert source_result["ok"] is False
        assert source_result["error"]["code"] == "memo_stack_mcp.validation.invalid_source_ref"
        assert quote_result["ok"] is False
        assert quote_result["error"]["code"] == "memo_stack_mcp.policy.secret_detected"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_rejects_invalid_source_type() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.remember_fact(
            text="A durable fact.",
            source_type="../tool",
            source_id="source-1",
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.validation.invalid_source_ref"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_write_mode_off_blocks_write_paths() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.OFF),
        )

        remembered = await service.remember_fact(
            text="A durable fact.",
            source_type="manual",
            source_id="note-1",
        )
        suggested = await service.suggest_fact(
            candidate_text="A candidate fact.",
            source_type="manual",
            source_id="note-2",
        )

        assert remembered["ok"] is False
        assert remembered["error"]["code"] == "memo_stack_mcp.policy.write_mode_off"
        assert suggested["ok"] is False
        assert suggested["error"]["code"] == "memo_stack_mcp.policy.write_mode_off"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_secret_text_is_rejected_before_gateway() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.remember_fact(
            text="Remember token sk-test-secret-token",
            source_type="manual",
            source_id="note-1",
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.policy.secret_detected"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_secret_search_query_is_rejected_before_gateway() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(gateway=gateway, settings=MemoryMcpSettings())

        result = await service.search(query="Find password=bench-secret-project-alpha")

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.policy.secret_detected"
        assert result["error"]["safe_message"] == "Search query contains a credential-like value"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_rejects_private_key_generic_secret_and_invisible_text() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(write_mode=MemoryMcpWriteMode.DIRECT),
        )

        private_key = await service.remember_fact(
            text="-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
            source_type="manual",
            source_id="note-1",
        )
        generic_secret = await service.remember_fact(
            text="password=abcdefghijklmnopqrstuvwxyz123456",
            source_type="manual",
            source_id="note-2",
        )
        invisible = await service.remember_fact(
            text="Use Graphiti\u200b for temporal facts.",
            source_type="manual",
            source_id="note-3",
        )
        bidi = await service.remember_fact(
            text="Use Graphiti\u202e for temporal facts.",
            source_type="manual",
            source_id="note-4",
        )

        assert private_key["error"]["code"] == "memo_stack_mcp.policy.secret_detected"
        assert generic_secret["error"]["code"] == "memo_stack_mcp.policy.secret_detected"
        assert invisible["error"]["code"] == "memo_stack_mcp.policy.invisible_characters"
        assert bidi["error"]["code"] == "memo_stack_mcp.policy.control_characters"
        assert gateway.calls == []

    asyncio.run(run())


def test_service_small_doc_ingest_mode_blocks_large_docs() -> None:
    async def run() -> None:
        gateway = RecordingGateway()
        service = MemoryToolService(
            gateway=gateway,
            settings=MemoryMcpSettings(
                ingest_mode=MemoryMcpIngestMode.SMALL_DOCS,
                small_doc_max_chars=10,
            ),
        )

        result = await service.ingest_document(title="doc", text="x" * 11)

        assert result["ok"] is False
        assert result["error"]["code"] == "memo_stack_mcp.policy.ingest_too_large"
        assert gateway.calls == []

    asyncio.run(run())
