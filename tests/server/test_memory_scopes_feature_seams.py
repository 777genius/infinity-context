from __future__ import annotations

import ast
import asyncio
from pathlib import Path

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
        "CreateMemoryScopeHttpRequest",
        "MemoryScopeActorHttpRequest",
        "MemoryScopeLifecycleHttpRequest",
        "MemoryScopeOwnerHttpRequest",
        "MemoryScopesServerFeature",
        "RestoreMemoryScopeHttpRequest",
        "TransferMemoryScopeOwnershipHttpRequest",
        "FEATURE_ID",
        "archive_memory_scope_command_from_http",
        "archive_memory_scope_result_to_response",
        "build_memory_scopes_server_feature",
        "create_memory_scope_command_from_contract",
        "create_memory_scope_contract_from_http_request",
        "create_memory_scope_result_to_contract",
        "create_memory_scopes_router",
        "memory_scope_actor_from_http",
        "memory_scope_owner_from_http",
        "memory_scope_snapshot_to_contract",
        "memory_scope_to_response",
        "restore_memory_scope_command_from_http",
        "restore_memory_scope_result_to_response",
        "transfer_memory_scope_ownership_command_from_http",
        "transfer_memory_scope_ownership_result_to_response",
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
