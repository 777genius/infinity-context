from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import infinity_context_core.features.memory_facts.public as memory_facts
import pytest
from infinity_context_contracts.features.memory_facts import (
    MemoryFactSourceRefDto,
    RememberFactRequestDto,
)
from infinity_context_server.features.memory_facts import public as server_public

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "memory_facts"
)
API_FACTS_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "facts.py"
)


class RecordingRememberFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.RememberFactCommand] = []

    async def execute(
        self,
        command: memory_facts.RememberFactCommand,
    ) -> memory_facts.RememberFactResult:
        self.commands.append(command)
        return memory_facts.RememberFactResult(
            fact=_snapshot(
                fact_id="fact_1",
                scope=command.scope,
                text=command.text,
                source_refs=command.source_refs,
                category=command.category,
                tags=command.tags,
            ),
            outbox_message_ids=("outbox_1",),
        )


class RecordingUpdateFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.UpdateFactCommand] = []

    async def execute(
        self,
        command: memory_facts.UpdateFactCommand,
    ) -> memory_facts.UpdateFactResult:
        self.commands.append(command)
        return memory_facts.UpdateFactResult(
            fact=_snapshot(
                fact_id=command.identity.fact_id,
                scope=command.identity.scope,
                text=command.text,
                source_refs=command.source_refs,
                version=command.expected_version + 1,
                category=command.category,
                tags=command.tags,
            ),
            outbox_message_ids=("outbox_2",),
        )


class RecordingForgetFact:
    def __init__(self) -> None:
        self.commands: list[memory_facts.ForgetFactCommand] = []

    async def execute(
        self,
        command: memory_facts.ForgetFactCommand,
    ) -> memory_facts.ForgetFactResult:
        self.commands.append(command)
        return memory_facts.ForgetFactResult(
            fact=_snapshot(
                fact_id=command.identity.fact_id,
                scope=command.identity.scope,
                text="Postgres owns canonical lifecycle.",
                source_refs=(_source_ref(),),
                status="deleted",
                version=(command.expected_version or 1) + 1,
            ),
            tombstone_id="tombstone_1",
            outbox_message_ids=("outbox_3",),
        )


def test_memory_facts_server_feature_public_surface_composes_router() -> None:
    use_cases = _use_cases()
    feature = server_public.build_memory_facts_server_feature(
        use_cases,
        route_prefix="/memory-facts-feature",
    )

    assert feature.feature_id == "memory_facts"
    assert server_public.FEATURE_ID == "memory_facts"
    assert server_public.__all__ == (
        "ForgetFactHttpRequest",
        "MemoryFactSourceRefHttpRequest",
        "MemoryFactsServerComposition",
        "MemoryFactsServerFeature",
        "RememberFactHttpRequest",
        "UpdateFactHttpRequest",
        "FEATURE_ID",
        "build_memory_facts_server_composition",
        "build_memory_facts_server_feature",
        "create_memory_facts_router",
        "evidence_ref_request_to_public",
        "evidence_ref_to_response",
        "fact_relation_item_to_response",
        "fact_relation_to_response",
        "fact_result_to_response",
        "fact_to_response",
        "forget_fact_command_from_http",
        "forget_fact_request_to_command",
        "forget_fact_result_to_contract",
        "legacy_memory_fact_to_response",
        "memory_fact_result_to_response",
        "memory_fact_scope_from_contract",
        "memory_fact_scope_from_ids",
        "memory_fact_snapshot_to_contract",
        "memory_fact_snapshot_to_response",
        "related_fact_to_response",
        "remember_fact_command_from_contract",
        "remember_fact_request_to_command",
        "remember_fact_result_to_contract",
        "source_ref_request_to_public",
        "source_ref_to_contract",
        "source_ref_to_response",
        "update_fact_command_from_http",
        "update_fact_request_to_command",
        "update_fact_result_to_contract",
        "validate_fact_relation_status_filter",
    )
    assert {route.path for route in feature.create_router().routes} == {
        "/memory-facts-feature/facts",
        "/memory-facts-feature/facts/{fact_id}",
    }


def test_memory_facts_mapper_builds_feature_public_application_commands() -> None:
    remember_request = RememberFactRequestDto(
        text="  Postgres owns canonical lifecycle.  ",
        source_refs=(
            MemoryFactSourceRefDto(
                source_type="document",
                source_id="doc_1",
                chunk_id="chunk_1",
                char_start=0,
                char_end=37,
                quote_preview="Postgres owns canonical lifecycle.",
            ),
        ),
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        kind="note",
        category="architecture",
        tags=("postgres", " "),
    )

    remember_command = server_public.remember_fact_command_from_contract(
        remember_request,
        idempotency_key="remember_1",
    )

    assert isinstance(remember_command, memory_facts.RememberFactCommand)
    assert remember_command.scope == memory_facts.MemoryFactScope(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
    )
    assert remember_command.text == "  Postgres owns canonical lifecycle.  "
    assert remember_command.source_refs[0].source_id == "doc_1"
    assert remember_command.tags == ("postgres",)
    assert remember_command.idempotency_key == "remember_1"

    update_request = server_public.UpdateFactHttpRequest(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        expected_version=1,
        text="Postgres remains the canonical lifecycle store.",
        reason="clarify owner",
        source_refs=[server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())],
    )

    update_command = server_public.update_fact_command_from_http(
        "fact_1",
        update_request,
        idempotency_key="update_1",
    )

    assert isinstance(update_command, memory_facts.UpdateFactCommand)
    assert update_command.identity == memory_facts.MemoryFactIdentity(
        fact_id="fact_1",
        scope=remember_command.scope,
    )
    assert update_command.expected_version == 1
    assert update_command.reason == "clarify owner"
    assert update_command.idempotency_key == "update_1"

    forget_request = server_public.ForgetFactHttpRequest(
        space_id="space_1",
        memory_scope_id="scope_1",
        thread_id="thread_1",
        expected_version=2,
        reason="obsolete",
    )

    forget_command = server_public.forget_fact_command_from_http(
        "fact_1",
        forget_request,
        idempotency_key="forget_1",
    )

    assert isinstance(forget_command, memory_facts.ForgetFactCommand)
    assert forget_command.identity == update_command.identity
    assert forget_command.expected_version == 2
    assert forget_command.reason == "obsolete"
    assert forget_command.idempotency_key == "forget_1"


def test_memory_facts_mapper_requires_resolved_scope_ids() -> None:
    request = RememberFactRequestDto(
        text="Postgres owns canonical lifecycle.",
        source_refs=(MemoryFactSourceRefDto(source_type="document", source_id="doc_1"),),
        space_slug="client-app",
        memory_scope_external_ref="default",
    )

    with pytest.raises(ValueError, match="space_id is required"):
        server_public.remember_fact_command_from_contract(request)


def test_memory_facts_public_seam_maps_relation_responses() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5)
    valid_to = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    relation = SimpleNamespace(
        id="relation_1",
        space_id="space_1",
        memory_scope_id="scope_1",
        source_fact_id="fact_1",
        target_fact_id="fact_2",
        relation_type=SimpleNamespace(value="supports"),
        reason="relation checked with Bearer " + "sk-" + "proj-secretvalue1234567890",
        status=SimpleNamespace(value="active"),
        valid_from=None,
        valid_to=valid_to,
        created_at=created_at,
        updated_at=created_at,
    )
    related_fact = _snapshot(
        fact_id="fact_2",
        scope=memory_facts.MemoryFactScope(
            space_id="space_1",
            memory_scope_id="scope_1",
        ),
        text="Graphiti remains a derived index.",
        source_refs=(_source_ref(),),
    )

    relation_body = server_public.fact_relation_to_response(relation)
    item_body = server_public.fact_relation_item_to_response(
        SimpleNamespace(
            relation=relation,
            related_fact=related_fact,
            direction="outgoing",
        )
    )
    related_body = server_public.related_fact_to_response(
        SimpleNamespace(
            fact=related_fact,
            score=0.75,
            relation_reasons=("ADR support",),
        )
    )

    assert relation_body == {
        "id": "relation_1",
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "source_fact_id": "fact_1",
        "target_fact_id": "fact_2",
        "relation_type": "supports",
        "reason": "relation checked with [redacted]",
        "status": "active",
        "observed_at": "2026-01-02T03:04:05+00:00",
        "valid_from": None,
        "valid_to": "2026-02-01T00:00:00+00:00",
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:04:05+00:00",
    }
    assert item_body["relation"] == relation_body
    assert item_body["related_fact"]["id"] == "fact_2"
    assert item_body["direction"] == "outgoing"
    assert related_body["id"] == "fact_2"
    assert related_body["score"] == 0.75
    assert related_body["relation_reasons"] == ["ADR support"]


def test_memory_facts_public_seam_validates_relation_status_filter() -> None:
    server_public.validate_fact_relation_status_filter(None)
    server_public.validate_fact_relation_status_filter("active")
    server_public.validate_fact_relation_status_filter("deleted")

    with pytest.raises(ValueError, match="Unknown fact relation status"):
        server_public.validate_fact_relation_status_filter("archived")


def test_memory_facts_routes_map_http_contracts_to_feature_use_cases() -> None:
    remember_recorder = RecordingRememberFact()
    update_recorder = RecordingUpdateFact()
    forget_recorder = RecordingForgetFact()
    use_cases = memory_facts.MemoryFactLifecycleUseCases(
        remember_fact=remember_recorder,
        update_fact=update_recorder,
        forget_fact=forget_recorder,
    )
    router = server_public.create_memory_facts_router(use_cases)
    create_route = next(
        route for route in router.routes if route.path == "/facts" and "POST" in route.methods
    )
    update_route = next(
        route
        for route in router.routes
        if route.path == "/facts/{fact_id}" and "PATCH" in route.methods
    )
    forget_route = next(
        route
        for route in router.routes
        if route.path == "/facts/{fact_id}" and "DELETE" in route.methods
    )

    create_body = asyncio.run(
        create_route.endpoint(
            server_public.RememberFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                text="Postgres owns canonical lifecycle.",
                kind="note",
                category="architecture",
                tags=["postgres"],
                source_refs=[
                    server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())
                ],
            ),
            idempotency_key="remember_1",
        )
    )

    assert create_route.status_code == 201
    assert len(remember_recorder.commands) == 1
    assert remember_recorder.commands[0].scope.memory_scope_id == "scope_1"
    assert remember_recorder.commands[0].idempotency_key == "remember_1"
    assert create_body["data"]["id"] == "fact_1"
    assert create_body["data"]["space_id"] == "space_1"
    assert create_body["data"]["memory_scope_id"] == "scope_1"
    assert create_body["data"]["thread_id"] == "thread_1"
    assert create_body["data"]["text"] == "Postgres owns canonical lifecycle."
    assert create_body["data"]["status"] == "active"
    assert create_body["data"]["version"] == 1
    assert create_body["data"]["category"] == "architecture"
    assert create_body["data"]["tags"] == ["postgres"]
    assert create_body["data"]["source_refs"][0]["source_id"] == "doc_1"
    assert create_body["data"]["created_at"] == "2026-01-02T03:04:05"

    update_body = asyncio.run(
        update_route.endpoint(
            "fact_1",
            server_public.UpdateFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                expected_version=1,
                text="Postgres remains the canonical lifecycle store.",
                reason="clarify owner",
                source_refs=[
                    server_public.MemoryFactSourceRefHttpRequest(**_source_ref_json())
                ],
            ),
            idempotency_key="update_1",
        )
    )

    assert len(update_recorder.commands) == 1
    update_command = update_recorder.commands[0]
    assert update_command.identity.fact_id == "fact_1"
    assert update_command.identity.scope.memory_scope_id == "scope_1"
    assert update_command.expected_version == 1
    assert update_command.idempotency_key == "update_1"
    assert update_body["data"]["version"] == 2

    forget_body = asyncio.run(
        forget_route.endpoint(
            "fact_1",
            server_public.ForgetFactHttpRequest(
                space_id="space_1",
                memory_scope_id="scope_1",
                thread_id="thread_1",
                expected_version=2,
                reason="obsolete",
            ),
            idempotency_key="forget_1",
        )
    )

    assert len(forget_recorder.commands) == 1
    forget_command = forget_recorder.commands[0]
    assert forget_command.identity.fact_id == "fact_1"
    assert forget_command.expected_version == 2
    assert forget_command.reason == "obsolete"
    assert forget_command.idempotency_key == "forget_1"
    assert forget_body["data"]["status"] == "deleted"
    assert forget_body["data"]["version"] == 3


def test_v1_facts_route_delegates_relation_response_mapping_to_feature_public_seam() -> None:
    source = API_FACTS_PATH.read_text(encoding="utf-8")

    assert "def related_fact_to_response" not in source
    assert "def fact_relation_to_response" not in source
    assert "def fact_relation_item_to_response" not in source
    assert "infinity_context_server.api.public_payload" not in _imports(API_FACTS_PATH)
    assert "memory_facts_feature.fact_relation_to_response" in source
    assert "memory_facts_feature.related_fact_to_response" in source


def test_memory_facts_server_slice_uses_only_public_feature_boundaries() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "infinity_context_adapters",
        "infinity_context_core.application",
        "infinity_context_core.domain",
        "infinity_context_core.ports",
        "infinity_context_server.api",
        "infinity_context_server.composition",
        "graphiti",
        "openai",
        "qdrant_client",
        "sqlalchemy",
    )

    for path in sorted(FEATURE_ROOT.rglob("*.py")):
        for imported in _imports(path):
            rel = path.relative_to(REPO_ROOT)
            if imported.startswith(
                "infinity_context_core.features."
            ) and not imported.endswith(".public"):
                violations.append(f"{rel}: imports {imported}")
            if imported == "infinity_context_core" or any(
                imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes
            ) or imported in forbidden_prefixes:
                violations.append(f"{rel}: imports {imported}")

    assert violations == []


def _use_cases() -> memory_facts.MemoryFactLifecycleUseCases:
    return memory_facts.MemoryFactLifecycleUseCases(
        remember_fact=RecordingRememberFact(),
        update_fact=RecordingUpdateFact(),
        forget_fact=RecordingForgetFact(),
    )


def _snapshot(
    *,
    fact_id: str,
    scope: memory_facts.MemoryFactScope,
    text: str,
    source_refs: tuple[memory_facts.MemoryFactSourceRef, ...],
    status: str = "active",
    version: int = 1,
    category: str | None = None,
    tags: tuple[str, ...] = (),
) -> memory_facts.MemoryFactSnapshot:
    now = datetime(2026, 1, 2, 3, 4, 5)
    return memory_facts.MemoryFactSnapshot(
        identity=memory_facts.MemoryFactIdentity(fact_id=fact_id, scope=scope),
        text=text,
        source_refs=source_refs,
        visibility=memory_facts.MemoryFactVisibility(
            status=status,
            version=version,
            confidence="medium",
            trust_level="medium",
            classification="internal",
        ),
        kind="note",
        category=category,
        tags=tags,
        created_at=now,
        updated_at=now,
    )


def _source_ref() -> memory_facts.MemoryFactSourceRef:
    return memory_facts.MemoryFactSourceRef(
        source_type="document",
        source_id="doc_1",
        chunk_id="chunk_1",
        char_start=0,
        char_end=37,
        quote_preview="Postgres owns canonical lifecycle.",
    )


def _source_ref_json() -> dict[str, object]:
    return {
        "source_type": "document",
        "source_id": "doc_1",
        "chunk_id": "chunk_1",
        "char_start": 0,
        "char_end": 37,
        "quote_preview": "Postgres owns canonical lifecycle.",
    }


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
