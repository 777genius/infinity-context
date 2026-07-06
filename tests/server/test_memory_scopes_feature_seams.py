from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import infinity_context_core.features.memory_scopes.public as memory_scopes
import pytest
from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
)
from infinity_context_server.features.memory_scopes import public as server_public

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_ROOT = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "features"
    / "memory_scopes"
)
EXPORT_API_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "export.py"
)
MEMORY_BROWSER_API_PATH = (
    REPO_ROOT
    / "packages"
    / "infinity_context_server"
    / "infinity_context_server"
    / "api"
    / "v1"
    / "memory_browser.py"
)


class RecordingCreateMemoryScope:
    def __init__(self) -> None:
        self.commands: list[memory_scopes.CreateMemoryScopeCommand] = []

    async def execute(
        self,
        command: memory_scopes.CreateMemoryScopeCommand,
    ) -> memory_scopes.CreateMemoryScopeResult:
        self.commands.append(command)
        scope = memory_scopes.MemoryScopeSnapshot(
            identity=memory_scopes.MemoryScopeIdentity(
                space_id=command.space_id,
                memory_scope_id="scope_1",
            ),
            name=command.name,
            owner=command.owner,
            external_ref=command.external_ref,
            description=command.description,
        )
        return memory_scopes.CreateMemoryScopeResult(scope=scope)


class RecordingTransferMemoryScopeOwnership:
    def __init__(self) -> None:
        self.commands: list[memory_scopes.TransferMemoryScopeOwnershipCommand] = []

    async def execute(
        self,
        command: memory_scopes.TransferMemoryScopeOwnershipCommand,
    ) -> memory_scopes.TransferMemoryScopeOwnershipResult:
        self.commands.append(command)
        previous_owner = command.expected_current_owner or memory_scopes.MemoryScopeOwner(
            principal_id="owner_1"
        )
        scope = memory_scopes.MemoryScopeSnapshot(
            identity=command.identity,
            name="Default",
            owner=command.new_owner,
            external_ref="default",
        )
        return memory_scopes.TransferMemoryScopeOwnershipResult(
            scope=scope,
            previous_owner=previous_owner,
        )


class RecordingArchiveMemoryScope:
    def __init__(self) -> None:
        self.commands: list[memory_scopes.ArchiveMemoryScopeCommand] = []

    async def execute(
        self,
        command: memory_scopes.ArchiveMemoryScopeCommand,
    ) -> memory_scopes.ArchiveMemoryScopeResult:
        self.commands.append(command)
        scope = memory_scopes.MemoryScopeSnapshot(
            identity=command.identity,
            name="Default",
            owner=memory_scopes.MemoryScopeOwner(principal_id="owner_1"),
            external_ref="default",
            status=memory_scopes.MEMORY_SCOPE_STATUS_ARCHIVED,
        )
        return memory_scopes.ArchiveMemoryScopeResult(
            scope=scope,
            previous_status=memory_scopes.MEMORY_SCOPE_STATUS_ACTIVE,
        )


class RecordingRestoreMemoryScope:
    def __init__(self) -> None:
        self.commands: list[memory_scopes.RestoreMemoryScopeCommand] = []

    async def execute(
        self,
        command: memory_scopes.RestoreMemoryScopeCommand,
    ) -> memory_scopes.RestoreMemoryScopeResult:
        self.commands.append(command)
        scope = memory_scopes.MemoryScopeSnapshot(
            identity=command.identity,
            name="Default",
            owner=memory_scopes.MemoryScopeOwner(principal_id="owner_1"),
            external_ref="default",
            status=memory_scopes.MEMORY_SCOPE_STATUS_ACTIVE,
        )
        return memory_scopes.RestoreMemoryScopeResult(
            scope=scope,
            previous_status=memory_scopes.MEMORY_SCOPE_STATUS_ARCHIVED,
        )


def test_memory_scopes_server_feature_public_surface_composes_router() -> None:
    use_cases = _use_cases()
    feature = server_public.build_memory_scopes_server_feature(
        use_cases,
        route_prefix="/memory-scopes-feature",
    )

    assert feature.feature_id == "memory_scopes"
    assert server_public.FEATURE_ID == "memory_scopes"
    assert server_public.__all__ == (
        "ArchiveMemoryScopeHttpRequest",
        "CreateMemoryScopeCompatibilityCommand",
        "CreateMemoryScopeHttpRequest",
        "CreateMemoryScopeRequest",
        "CreateSpaceRequest",
        "DeleteMemoryScopeCompatibilityCommand",
        "ImportMemoryScopeSnapshotRequest",
        "MemoryScopeActorHttpRequest",
        "MemoryScopeLifecycleHttpRequest",
        "MemoryScopeOwnerHttpRequest",
        "MemoryScopesServerFeature",
        "MemoryScopeSnapshotCompatibilityError",
        "PreviewMemoryScopeSnapshotRequest",
        "RestoreMemoryScopeHttpRequest",
        "TransferMemoryScopeOwnershipHttpRequest",
        "UpdateMemoryScopeCompatibilityCommand",
        "UpdateMemoryScopeRequest",
        "FEATURE_ID",
        "archive_memory_scope_command_from_http",
        "archive_memory_scope_result_to_response",
        "build_memory_scopes_server_feature",
        "create_memory_scope_compatibility_command_from_request",
        "create_memory_scope_command_from_contract",
        "create_memory_scope_contract_from_http_request",
        "create_memory_scope_result_to_contract",
        "create_memory_scopes_router",
        "delete_memory_scope_compatibility_command_from_path",
        "graph_export_scope_not_found_response",
        "graph_export_to_response",
        "memory_scope_collection_compatibility_response",
        "memory_scope_compatibility_response",
        "memory_scope_actor_from_http",
        "memory_scope_owner_from_http",
        "memory_scope_snapshot_export_response",
        "memory_scope_snapshot_transfer_response",
        "memory_scope_snapshot_to_contract",
        "memory_scope_to_response",
        "restore_memory_scope_command_from_http",
        "restore_memory_scope_result_to_response",
        "space_to_response",
        "thread_to_response",
        "transfer_memory_scope_ownership_command_from_http",
        "transfer_memory_scope_ownership_result_to_response",
        "update_memory_scope_compatibility_command_from_request",
        "validate_memory_scope_snapshot_import_request",
        "validate_memory_scope_snapshot_preview_request",
        "verify_memory_scope_snapshot_manifest",
    )
    assert {route.path for route in feature.create_router().routes} == {
        "/memory-scopes-feature/memory-scopes",
        "/memory-scopes-feature/memory-scopes/{memory_scope_id}/archive",
        "/memory-scopes-feature/memory-scopes/{memory_scope_id}/ownership",
        "/memory-scopes-feature/memory-scopes/{memory_scope_id}/restore",
    }


def test_memory_scopes_mapper_builds_feature_public_application_commands() -> None:
    create_request = CreateMemoryScopeRequestDto(
        space_id="space_1",
        external_ref="default",
        name="Default",
        description="Default client app memory scope.",
        idempotency_key="create_scope_1",
    )
    owner = server_public.MemoryScopeOwnerHttpRequest(
        principal_id="owner_1",
        principal_kind="user",
    )

    create_command = server_public.create_memory_scope_command_from_contract(
        create_request,
        owner=owner,
    )

    assert isinstance(create_command, memory_scopes.CreateMemoryScopeCommand)
    assert create_command.space_id == "space_1"
    assert create_command.external_ref == "default"
    assert create_command.owner == memory_scopes.MemoryScopeOwner(
        principal_id="owner_1",
        principal_kind="user",
    )
    assert create_command.idempotency_key == "create_scope_1"

    transfer_request = server_public.TransferMemoryScopeOwnershipHttpRequest(
        space_id="space_1",
        new_owner=server_public.MemoryScopeOwnerHttpRequest(
            principal_id="owner_2",
            principal_kind="team",
        ),
        initiated_by=server_public.MemoryScopeActorHttpRequest(
            principal_id="owner_1",
            capabilities=["memory_scope:transfer", " "],
        ),
        expected_current_owner=owner,
        reason="owner rotation",
        idempotency_key="transfer_scope_1",
    )

    transfer_command = server_public.transfer_memory_scope_ownership_command_from_http(
        "scope_1",
        transfer_request,
    )

    assert isinstance(
        transfer_command,
        memory_scopes.TransferMemoryScopeOwnershipCommand,
    )
    assert transfer_command.identity == memory_scopes.MemoryScopeIdentity(
        space_id="space_1",
        memory_scope_id="scope_1",
    )
    assert transfer_command.new_owner.principal_id == "owner_2"
    assert transfer_command.initiated_by.capabilities == ("memory_scope:transfer",)
    assert transfer_command.expected_current_owner == create_command.owner

    archive_request = server_public.ArchiveMemoryScopeHttpRequest(
        space_id="space_1",
        initiated_by=server_public.MemoryScopeActorHttpRequest(
            principal_id="owner_1",
            capabilities=["memory_scope:lifecycle", " "],
        ),
        expected_status=memory_scopes.MEMORY_SCOPE_STATUS_ACTIVE,
        reason="hide default memory",
        idempotency_key="archive_scope_1",
    )

    archive_command = server_public.archive_memory_scope_command_from_http(
        "scope_1",
        archive_request,
    )

    assert isinstance(archive_command, memory_scopes.ArchiveMemoryScopeCommand)
    assert archive_command.identity == memory_scopes.MemoryScopeIdentity(
        space_id="space_1",
        memory_scope_id="scope_1",
    )
    assert archive_command.initiated_by.capabilities == (
        "memory_scope:lifecycle",
    )
    assert archive_command.expected_status == memory_scopes.MEMORY_SCOPE_STATUS_ACTIVE
    assert archive_command.reason == "hide default memory"
    assert archive_command.idempotency_key == "archive_scope_1"

    restore_request = server_public.RestoreMemoryScopeHttpRequest(
        space_id="space_1",
        initiated_by=server_public.MemoryScopeActorHttpRequest(
            principal_id="owner_1",
            capabilities=["memory_scope:lifecycle"],
        ),
        expected_status=memory_scopes.MEMORY_SCOPE_STATUS_ARCHIVED,
        reason="memory needed again",
        idempotency_key="restore_scope_1",
    )

    restore_command = server_public.restore_memory_scope_command_from_http(
        "scope_1",
        restore_request,
    )

    assert isinstance(restore_command, memory_scopes.RestoreMemoryScopeCommand)
    assert restore_command.identity == memory_scopes.MemoryScopeIdentity(
        space_id="space_1",
        memory_scope_id="scope_1",
    )
    assert restore_command.initiated_by.principal_id == "owner_1"
    assert restore_command.expected_status == (
        memory_scopes.MEMORY_SCOPE_STATUS_ARCHIVED
    )
    assert restore_command.reason == "memory needed again"
    assert restore_command.idempotency_key == "restore_scope_1"


def test_memory_scopes_mapper_requires_resolved_scope_ids() -> None:
    request = CreateMemoryScopeRequestDto(
        space_slug="client-app",
        external_ref="default",
        name="Default",
    )
    owner = server_public.MemoryScopeOwnerHttpRequest(principal_id="owner_1")

    with pytest.raises(ValueError, match="space_id is required"):
        server_public.create_memory_scope_command_from_contract(request, owner=owner)


def test_memory_scopes_feature_owns_legacy_v1_spaces_memory_scope_api_mapping() -> None:
    api_path = (
        REPO_ROOT
        / "packages"
        / "infinity_context_server"
        / "infinity_context_server"
        / "api"
        / "v1"
        / "spaces_memory_scopes.py"
    )
    api_source = api_path.read_text(encoding="utf-8")
    api_tree = ast.parse(api_source, filename=str(api_path))
    api_class_names = {
        node.name for node in ast.walk(api_tree) if isinstance(node, ast.ClassDef)
    }
    api_function_names = {
        node.name
        for node in ast.walk(api_tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    assert "CreateSpaceRequest" not in api_class_names
    assert "CreateMemoryScopeRequest" not in api_class_names
    assert "UpdateMemoryScopeRequest" not in api_class_names
    assert "space_to_response" not in api_function_names
    assert "memory_scopes_feature.space_to_response" in api_source

    create_space_request = server_public.CreateSpaceRequest(
        slug="client-app",
        name="Client App",
    )

    assert create_space_request.slug == "client-app"
    assert create_space_request.name == "Client App"

    create_request = server_public.CreateMemoryScopeRequest(
        space_id="space_1",
        external_ref="default",
        name="Default",
    )
    create_command = (
        server_public.create_memory_scope_compatibility_command_from_request(
            create_request,
        )
    )

    assert create_command == server_public.CreateMemoryScopeCompatibilityCommand(
        space_id="space_1",
        external_ref="default",
        name="Default",
    )

    update_request = server_public.UpdateMemoryScopeRequest(
        external_ref="sales-crm",
        name="Sales CRM",
    )
    update_command = (
        server_public.update_memory_scope_compatibility_command_from_request(
            "scope_1",
            update_request,
        )
    )
    delete_command = server_public.delete_memory_scope_compatibility_command_from_path(
        "scope_1",
    )

    assert update_command == server_public.UpdateMemoryScopeCompatibilityCommand(
        memory_scope_id="scope_1",
        external_ref="sales-crm",
        name="Sales CRM",
    )
    assert delete_command == server_public.DeleteMemoryScopeCompatibilityCommand(
        memory_scope_id="scope_1",
    )
    with pytest.raises(ValueError, match="At least one memory_scope field is required"):
        server_public.update_memory_scope_compatibility_command_from_request(
            "scope_1",
            server_public.UpdateMemoryScopeRequest(),
        )


def test_memory_browser_route_uses_memory_scopes_public_response_mapping() -> None:
    source = MEMORY_BROWSER_API_PATH.read_text(encoding="utf-8")
    api_tree = ast.parse(source, filename=str(MEMORY_BROWSER_API_PATH))
    public_import_aliases = [
        alias.asname
        for node in ast.walk(api_tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "infinity_context_server.features.memory_scopes"
        for alias in node.names
        if alias.name == "public"
    ]
    public_calls = [
        node.func.attr
        for node in ast.walk(api_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "memory_scopes_feature"
    ]
    api_function_names = {
        node.name
        for node in ast.walk(api_tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    assert "infinity_context_server.api.v1.spaces_memory_scopes" not in _imports(
        MEMORY_BROWSER_API_PATH,
    )
    assert "infinity_context_core.domain.entities" not in _imports(
        MEMORY_BROWSER_API_PATH,
    )
    assert public_import_aliases == ["memory_scopes_feature"]
    assert "memory_scope_to_response" in public_calls
    assert "thread_to_response" in public_calls
    assert "thread_to_response" not in api_function_names


def test_memory_scopes_feature_owns_snapshot_compatibility_api_mapping() -> None:
    api_source = EXPORT_API_PATH.read_text(encoding="utf-8")
    api_tree = ast.parse(api_source, filename=str(EXPORT_API_PATH))
    api_class_names = {
        node.name for node in ast.walk(api_tree) if isinstance(node, ast.ClassDef)
    }
    api_function_names = {
        node.name
        for node in ast.walk(api_tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    assert "ImportMemoryScopeSnapshotRequest" not in api_class_names
    assert "PreviewMemoryScopeSnapshotRequest" not in api_class_names
    assert "_verify_memory_scope_snapshot_manifest" not in api_function_names
    assert "_validate_memory_scope_snapshot_import_request" not in api_function_names
    assert "_validate_memory_scope_snapshot_preview_request" not in api_function_names
    assert "graph_export_to_response" not in api_function_names
    assert "graph_export_scope_not_found_response" not in api_function_names
    assert "infinity_context_core.memory_scope_snapshots" not in _imports(EXPORT_API_PATH)
    assert "infinity_context_server.features.memory_scopes" in _imports(EXPORT_API_PATH)
    assert "memory_scopes_feature.graph_export_to_response" in api_source
    assert "memory_scopes_feature.graph_export_scope_not_found_response" in api_source
    assert "memory_scopes_feature.memory_scope_snapshot_export_response" in api_source
    assert "memory_scopes_feature.validate_memory_scope_snapshot_import_request" in api_source
    assert "memory_scopes_feature.validate_memory_scope_snapshot_preview_request" in api_source
    assert "graph_export_to_response" in server_public.__all__
    assert "graph_export_scope_not_found_response" in server_public.__all__


def test_memory_scopes_feature_owns_graph_export_api_responses() -> None:
    graph = SimpleNamespace(
        schema_version="infinity_context.graph_export.v1",
        scope={"space_id": "space_1"},
        nodes=(
            SimpleNamespace(
                id="fact:fact_1",
                type="fact",
                label="Fact",
                data={"text": "A fact"},
            ),
        ),
        edges=(
            SimpleNamespace(
                id="edge_1",
                type="contains_fact",
                source="scope:scope_1",
                target="fact:fact_1",
                label="contains",
                data={"rank": 1},
            ),
        ),
        counts={"facts": 1, "nodes": 1, "edges": 1},
        truncated=False,
        warnings=("truncated_facts",),
    )

    assert server_public.graph_export_to_response(graph) == {
        "schema_version": "infinity_context.graph_export.v1",
        "scope": {"space_id": "space_1"},
        "nodes": [
            {
                "id": "fact:fact_1",
                "type": "fact",
                "label": "Fact",
                "data": {"text": "A fact"},
            }
        ],
        "edges": [
            {
                "id": "edge_1",
                "type": "contains_fact",
                "source": "scope:scope_1",
                "target": "fact:fact_1",
                "label": "contains",
                "data": {"rank": 1},
            }
        ],
        "counts": {"facts": 1, "nodes": 1, "edges": 1},
        "truncated": False,
        "warnings": ["truncated_facts"],
    }
    assert server_public.graph_export_scope_not_found_response() == {
        "schema_version": "infinity_context.graph_export.v1",
        "scope": {"scope_not_found": True},
        "nodes": [],
        "edges": [],
        "counts": {
            "facts": 0,
            "documents": 0,
            "episodes": 0,
            "chunks": 0,
            "anchors": 0,
            "nodes": 0,
            "edges": 0,
            "relations": 0,
            "anchor_relations": 0,
        },
        "truncated": False,
        "warnings": ["scope_not_found"],
    }


def test_export_graph_route_delegates_response_to_memory_scopes_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infinity_context_server.api.v1 import export as export_api

    calls: list[tuple[str, object]] = []

    class RecordingExportGraph:
        async def execute(self, query: object) -> object:
            calls.append(("execute", query))
            return SimpleNamespace(schema_version="graph.v1")

    async def fake_resolve_existing_single_scope(
        _container: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        calls.append(("resolve", kwargs))
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1", thread_id="thread_1")

    def fake_graph_export_to_response(graph: object) -> dict[str, object]:
        calls.append(("response", graph))
        return {"delegated": True}

    monkeypatch.setattr(
        export_api,
        "resolve_existing_single_scope",
        fake_resolve_existing_single_scope,
    )
    monkeypatch.setattr(
        export_api.memory_scopes_feature,
        "graph_export_to_response",
        fake_graph_export_to_response,
    )

    response = asyncio.run(
        export_api.export_graph_json(
            SimpleNamespace(export_graph=RecordingExportGraph()),
            space_slug="team",
            memory_scope_external_ref="atlas",
            thread_external_ref="planning",
            include_deleted=True,
            include_restricted=True,
            max_facts=10,
            max_anchors=14,
        )
    )

    assert response == {"data": {"delegated": True}}
    assert [name for name, _payload in calls] == ["resolve", "execute", "response"]
    query = calls[1][1]
    assert (query.space_id, query.memory_scope_id) == ("space_1", "scope_1")
    assert query.thread_id == "thread_1"
    assert (query.include_deleted, query.include_restricted) == (True, True)
    assert (query.max_facts, query.max_anchors) == (10, 14)


def test_export_graph_route_delegates_scope_not_found_payload_to_memory_scopes_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infinity_context_server.api.v1 import export as export_api

    calls: list[tuple[str, object]] = []

    class FailingExportGraph:
        async def execute(self, query: object) -> object:
            raise AssertionError(f"export should not execute for unresolved scope: {query!r}")

    async def fake_resolve_existing_single_scope(
        _container: object,
        **kwargs: object,
    ) -> None:
        calls.append(("resolve", kwargs))
        return None

    def fake_scope_not_found_response() -> dict[str, object]:
        calls.append(("scope_not_found", {}))
        return {"delegated": "missing"}

    monkeypatch.setattr(
        export_api,
        "resolve_existing_single_scope",
        fake_resolve_existing_single_scope,
    )
    monkeypatch.setattr(
        export_api.memory_scopes_feature,
        "graph_export_scope_not_found_response",
        fake_scope_not_found_response,
    )

    response = asyncio.run(
        export_api.export_graph_json(
            SimpleNamespace(export_graph=FailingExportGraph()),
            space_slug="team",
            memory_scope_external_ref="missing",
        )
    )

    assert response == {"data": {"delegated": "missing"}}
    assert [name for name, _payload in calls] == ["resolve", "scope_not_found"]


def test_export_route_delegates_snapshot_export_envelope_to_memory_scopes_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infinity_context_server.api.v1 import export as export_api

    calls: list[tuple[str, object]] = []

    async def fake_export_memory_scope_payload(**kwargs: object) -> dict[str, object]:
        calls.append(("transfer", kwargs))
        return {
            "status": "ok",
            "snapshot": {"schema_version": 9, "redacted": True},
            "counts": {"facts": 0},
            "redacted": True,
        }

    def fake_export_response(
        *,
        result: dict[str, object],
        space_slug: str,
        memory_scope_external_ref: str,
    ) -> dict[str, object]:
        calls.append(("response", result))
        return {
            "delegated": True,
            "space_slug": space_slug,
            "memory_scope_external_ref": memory_scope_external_ref,
        }

    monkeypatch.setattr(
        export_api,
        "export_memory_scope_payload",
        fake_export_memory_scope_payload,
    )
    monkeypatch.setattr(
        export_api.memory_scopes_feature,
        "memory_scope_snapshot_export_response",
        fake_export_response,
    )

    response = asyncio.run(
        export_api.export_memory_scope_snapshot(
            SimpleNamespace(engine="engine", blob_storage="blob_storage"),
            space_slug="team",
            memory_scope_external_ref="atlas",
            redacted=True,
        )
    )

    assert response == {
        "delegated": True,
        "space_slug": "team",
        "memory_scope_external_ref": "atlas",
    }
    assert [name for name, _payload in calls] == ["transfer", "response"]
    assert calls[0][1] == {
        "engine": "engine",
        "space_slug": "team",
        "memory_scope_external_ref": "atlas",
        "redacted": True,
        "blob_storage": "blob_storage",
    }


def test_import_route_delegates_snapshot_validation_and_envelope_to_memory_scopes_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infinity_context_server.api.v1 import export as export_api

    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    calls: list[tuple[str, object]] = []

    def fake_validate(
        request: server_public.ImportMemoryScopeSnapshotRequest,
        *,
        supported_merge_strategies: object,
    ) -> None:
        calls.append(
            (
                "validate",
                {
                    "merge_strategy": request.merge_strategy,
                    "supported": supported_merge_strategies,
                },
            )
        )

    async def fake_resolve_existing_single_scope(
        _container: object,
        **kwargs: object,
    ) -> SimpleNamespace:
        calls.append(("resolve", kwargs))
        return SimpleNamespace(space_id="space_1", memory_scope_id="scope_1")

    async def fake_import_memory_scope_payload(**kwargs: object) -> dict[str, object]:
        calls.append(("transfer", kwargs))
        return {"status": "dry_run", "conflicts": []}

    def fake_transfer_response(result: dict[str, object]) -> dict[str, object]:
        calls.append(("response", result))
        return {"delegated": result}

    monkeypatch.setattr(
        export_api.memory_scopes_feature,
        "validate_memory_scope_snapshot_import_request",
        fake_validate,
    )
    monkeypatch.setattr(
        export_api,
        "resolve_existing_single_scope",
        fake_resolve_existing_single_scope,
    )
    monkeypatch.setattr(
        export_api,
        "import_memory_scope_payload",
        fake_import_memory_scope_payload,
    )
    monkeypatch.setattr(
        export_api.memory_scopes_feature,
        "memory_scope_snapshot_transfer_response",
        fake_transfer_response,
    )

    request = export_api.memory_scopes_feature.ImportMemoryScopeSnapshotRequest(
        space_slug="team",
        memory_scope_external_ref="atlas",
        snapshot={"schema_version": 9},
        dry_run=True,
        merge_strategy="fail_on_conflict",
    )
    response = asyncio.run(
        export_api.import_memory_scope_snapshot(
            request,
            SimpleNamespace(
                engine="engine",
                clock=SimpleNamespace(now=lambda: now),
                blob_storage="blob_storage",
            ),
        )
    )

    assert response == {"delegated": {"status": "dry_run", "conflicts": []}}
    assert [name for name, _payload in calls] == [
        "validate",
        "resolve",
        "transfer",
        "response",
    ]
    assert calls[2][1] == {
        "engine": "engine",
        "now": now,
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "payload": {"schema_version": 9},
        "dry_run": True,
        "merge_strategy": "fail_on_conflict",
        "source_name": "api-memory_scope-snapshot",
        "blob_storage": "blob_storage",
    }


def test_memory_scopes_feature_owns_legacy_v1_memory_scope_api_responses() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated_at = datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC)
    space = SimpleNamespace(
        id="space_1",
        slug="client-app",
        name="Client App",
        status="active",
        created_at=created_at,
        updated_at=updated_at,
    )
    scope = SimpleNamespace(
        id="scope_1",
        space_id="space_1",
        external_ref="default",
        name="Default",
        status="active",
        created_at=created_at,
        updated_at=updated_at,
    )
    expected_scope = {
        "id": "scope_1",
        "space_id": "space_1",
        "external_ref": "default",
        "name": "Default",
        "status": "active",
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }

    assert server_public.space_to_response(space) == {
        "id": "space_1",
        "slug": "client-app",
        "name": "Client App",
        "status": "active",
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }
    assert server_public.memory_scope_to_response(scope) == expected_scope
    assert server_public.memory_scope_compatibility_response(scope) == {
        "data": expected_scope,
    }
    assert server_public.memory_scope_collection_compatibility_response([scope]) == {
        "data": [expected_scope],
    }


def test_memory_scopes_feature_owns_memory_browser_thread_response_mapping() -> None:
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated_at = datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC)
    thread = SimpleNamespace(
        id="thread_1",
        space_id="space_1",
        memory_scope_id="scope_1",
        external_ref="alex-call",
        status=SimpleNamespace(value="active"),
        created_at=created_at,
        updated_at=updated_at,
    )

    assert server_public.thread_to_response(thread) == {
        "id": "thread_1",
        "space_id": "space_1",
        "memory_scope_id": "scope_1",
        "external_ref": "alex-call",
        "status": "active",
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def test_memory_scopes_routes_map_http_contracts_to_feature_use_cases() -> None:
    create_recorder = RecordingCreateMemoryScope()
    transfer_recorder = RecordingTransferMemoryScopeOwnership()
    archive_recorder = RecordingArchiveMemoryScope()
    restore_recorder = RecordingRestoreMemoryScope()
    use_cases = memory_scopes.MemoryScopeUseCases(
        create_memory_scope=create_recorder,
        transfer_memory_scope_ownership=transfer_recorder,
        archive_memory_scope=archive_recorder,
        restore_memory_scope=restore_recorder,
    )
    router = server_public.create_memory_scopes_router(use_cases)
    create_route = next(
        route
        for route in router.routes
        if route.path == "/memory-scopes" and "POST" in route.methods
    )
    transfer_route = next(
        route
        for route in router.routes
        if route.path == "/memory-scopes/{memory_scope_id}/ownership"
        and "POST" in route.methods
    )
    archive_route = next(
        route
        for route in router.routes
        if route.path == "/memory-scopes/{memory_scope_id}/archive"
        and "POST" in route.methods
    )
    restore_route = next(
        route
        for route in router.routes
        if route.path == "/memory-scopes/{memory_scope_id}/restore"
        and "POST" in route.methods
    )

    create_body = asyncio.run(
        create_route.endpoint(
            server_public.CreateMemoryScopeHttpRequest(
                space_id="space_1",
                external_ref="default",
                name="Default",
                description="Default client app memory scope.",
                owner=server_public.MemoryScopeOwnerHttpRequest(
                    principal_id="owner_1",
                    principal_kind="user",
                ),
            )
        )
    )

    assert create_route.status_code == 201
    assert len(create_recorder.commands) == 1
    assert create_recorder.commands[0].space_id == "space_1"
    assert create_recorder.commands[0].owner.principal_id == "owner_1"
    assert create_body["data"]["scope"] == {
        "id": "scope_1",
        "space_id": "space_1",
        "external_ref": "default",
        "name": "Default",
        "owner": {
            "principal_id": "owner_1",
            "principal_kind": "user",
        },
        "description": "Default client app memory scope.",
        "status": "active",
        "policy_mode": "manual_only",
        "created_at": None,
        "updated_at": None,
        "metadata": {
            "owner": {
                "principal_id": "owner_1",
                "principal_kind": "user",
            }
        },
    }
    assert create_body["data"]["created"] is True

    transfer_body = asyncio.run(
        transfer_route.endpoint(
            "scope_1",
            server_public.TransferMemoryScopeOwnershipHttpRequest(
                space_id="space_1",
                new_owner=server_public.MemoryScopeOwnerHttpRequest(
                    principal_id="owner_2",
                    principal_kind="team",
                ),
                initiated_by=server_public.MemoryScopeActorHttpRequest(
                    principal_id="owner_1",
                    capabilities=["memory_scope:transfer"],
                ),
                expected_current_owner=server_public.MemoryScopeOwnerHttpRequest(
                    principal_id="owner_1",
                    principal_kind="user",
                ),
                reason="owner rotation",
            ),
        )
    )

    assert len(transfer_recorder.commands) == 1
    transfer_command = transfer_recorder.commands[0]
    assert transfer_command.identity.memory_scope_id == "scope_1"
    assert transfer_command.new_owner.principal_id == "owner_2"
    assert transfer_command.initiated_by.capabilities == ("memory_scope:transfer",)
    assert transfer_body["data"]["scope"]["metadata"]["owner"] == {
        "principal_id": "owner_2",
        "principal_kind": "team",
    }
    assert transfer_body["data"]["previous_owner"] == {
        "principal_id": "owner_1",
        "principal_kind": "user",
    }
    assert transfer_body["data"]["transferred"] is True

    archive_body = asyncio.run(
        archive_route.endpoint(
            "scope_1",
            server_public.ArchiveMemoryScopeHttpRequest(
                space_id="space_1",
                initiated_by=server_public.MemoryScopeActorHttpRequest(
                    principal_id="owner_1",
                    capabilities=["memory_scope:lifecycle"],
                ),
                expected_status="active",
                reason="hide default memory",
            ),
        )
    )

    assert len(archive_recorder.commands) == 1
    archive_command = archive_recorder.commands[0]
    assert archive_command.identity == memory_scopes.MemoryScopeIdentity(
        space_id="space_1",
        memory_scope_id="scope_1",
    )
    assert archive_command.initiated_by.capabilities == (
        "memory_scope:lifecycle",
    )
    assert archive_command.expected_status == "active"
    assert archive_body["data"]["scope"]["status"] == "archived"
    assert archive_body["data"]["previous_status"] == "active"
    assert archive_body["data"]["archived"] is True

    restore_body = asyncio.run(
        restore_route.endpoint(
            "scope_1",
            server_public.RestoreMemoryScopeHttpRequest(
                space_id="space_1",
                initiated_by=server_public.MemoryScopeActorHttpRequest(
                    principal_id="owner_1",
                    capabilities=["memory_scope:lifecycle"],
                ),
                expected_status="archived",
                reason="memory needed again",
            ),
        )
    )

    assert len(restore_recorder.commands) == 1
    restore_command = restore_recorder.commands[0]
    assert restore_command.identity == memory_scopes.MemoryScopeIdentity(
        space_id="space_1",
        memory_scope_id="scope_1",
    )
    assert restore_command.expected_status == "archived"
    assert restore_command.reason == "memory needed again"
    assert restore_body["data"]["scope"]["status"] == "active"
    assert restore_body["data"]["previous_status"] == "archived"
    assert restore_body["data"]["restored"] is True


def test_memory_scopes_server_slice_uses_only_public_feature_boundaries() -> None:
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


def _use_cases() -> memory_scopes.MemoryScopeUseCases:
    return memory_scopes.MemoryScopeUseCases(
        create_memory_scope=RecordingCreateMemoryScope(),
        transfer_memory_scope_ownership=RecordingTransferMemoryScopeOwnership(),
        archive_memory_scope=RecordingArchiveMemoryScope(),
        restore_memory_scope=RecordingRestoreMemoryScope(),
    )


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
