import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Response
from infinity_context_core.domain.entities import LifecycleStatus
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryPolicyBlockedError,
    MemoryValidationError,
)
from infinity_context_server.api.v1 import spaces_memory_scopes as api
from infinity_context_server.config import MemoryPolicyMode


def test_create_and_list_spaces_memory_scopes() -> None:
    container = FakeSpacesMemoryScopesContainer()

    response = Response(status_code=201)
    space = asyncio.run(
        api.create_space(
            api.CreateSpaceRequest(slug="client-app", name="Client App"),
            container,
            response,
        )
    )
    duplicate_response = Response(status_code=201)
    duplicate_space = asyncio.run(
        api.create_space(
            api.CreateSpaceRequest(slug="client-app", name="Client App"),
            container,
            duplicate_response,
        )
    )
    memory_scope_response = Response(status_code=201)
    memory_scope = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="default",
                name="Default",
            ),
            container,
            memory_scope_response,
        )
    )
    duplicate_memory_scope_response = Response(status_code=201)
    duplicate_memory_scope = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="default",
                name="Default",
            ),
            container,
            duplicate_memory_scope_response,
        )
    )
    spaces = asyncio.run(api.list_spaces(container))
    memory_scopes = asyncio.run(
        api.list_memory_scopes(container, space_id=space["data"]["id"])
    )

    assert response.status_code == 201
    assert duplicate_response.status_code == 200
    assert duplicate_space["data"]["id"] == space["data"]["id"]
    assert memory_scope_response.status_code == 201
    assert duplicate_memory_scope_response.status_code == 200
    assert duplicate_memory_scope["data"]["id"] == memory_scope["data"]["id"]
    assert [item["id"] for item in spaces["data"]] == [space["data"]["id"]]
    assert [item["id"] for item in memory_scopes["data"]] == [
        memory_scope["data"]["id"],
    ]


def test_memory_scope_requires_existing_space() -> None:
    container = FakeSpacesMemoryScopesContainer()

    with pytest.raises(MemoryValidationError, match="space is required"):
        asyncio.run(
            api.create_memory_scope(
                api.CreateMemoryScopeRequest(
                    space_id="space_missing",
                    external_ref="default",
                    name="Default",
                ),
                container,
                Response(),
            )
        )


def test_update_and_delete_memory_scope() -> None:
    container = FakeSpacesMemoryScopesContainer()
    space = asyncio.run(
        api.create_space(
            api.CreateSpaceRequest(slug="client-app", name="Client App"),
            container,
            Response(),
        )
    )
    memory_scope = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="default",
                name="Default",
            ),
            container,
            Response(),
        )
    )
    memory_scope_id = memory_scope["data"]["id"]

    updated = asyncio.run(
        api.update_memory_scope(
            memory_scope_id,
            api.UpdateMemoryScopeRequest(external_ref="sales-crm", name="Sales CRM"),
            container,
        )
    )
    listed_after_update = asyncio.run(
        api.list_memory_scopes(container, space_id=space["data"]["id"])
    )
    deleted = asyncio.run(api.delete_memory_scope(memory_scope_id, container))
    listed_after_delete = asyncio.run(
        api.list_memory_scopes(container, space_id=space["data"]["id"])
    )
    recreated_response = Response(status_code=201)
    recreated = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="sales-crm",
                name="Sales CRM Restored",
            ),
            container,
            recreated_response,
        )
    )

    assert updated["data"]["external_ref"] == "sales-crm"
    assert updated["data"]["name"] == "Sales CRM"
    assert [item["external_ref"] for item in listed_after_update["data"]] == [
        "sales-crm",
    ]
    assert deleted["data"]["status"] == "deleted"
    assert listed_after_delete["data"] == []
    assert recreated_response.status_code == 200
    assert recreated["data"]["id"] == memory_scope_id
    assert recreated["data"]["status"] == "active"
    assert recreated["data"]["name"] == "Sales CRM Restored"


def test_update_memory_scope_rejects_duplicate_ref() -> None:
    container = FakeSpacesMemoryScopesContainer()
    space = asyncio.run(
        api.create_space(
            api.CreateSpaceRequest(slug="client-app", name="Client App"),
            container,
            Response(),
        )
    )
    first = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="first",
                name="First",
            ),
            container,
            Response(),
        )
    )
    second = asyncio.run(
        api.create_memory_scope(
            api.CreateMemoryScopeRequest(
                space_id=space["data"]["id"],
                external_ref="second",
                name="Second",
            ),
            container,
            Response(),
        )
    )

    with pytest.raises(MemoryConflictError, match="memory_scope external_ref exists"):
        asyncio.run(
            api.update_memory_scope(
                second["data"]["id"],
                api.UpdateMemoryScopeRequest(
                    external_ref=first["data"]["external_ref"],
                ),
                container,
            )
        )


def test_update_memory_scope_rejects_empty_patch() -> None:
    container = FakeSpacesMemoryScopesContainer()

    with pytest.raises(
        MemoryValidationError,
        match="At least one memory_scope field is required",
    ):
        asyncio.run(
            api.update_memory_scope(
                "scope_1",
                api.UpdateMemoryScopeRequest(),
                container,
            )
        )


def test_disabled_policy_blocks_space_memory_scope_writes() -> None:
    container = FakeSpacesMemoryScopesContainer(policy_mode=MemoryPolicyMode.DISABLED)

    with pytest.raises(MemoryPolicyBlockedError, match="Memory writes are disabled"):
        asyncio.run(
            api.create_space(
                api.CreateSpaceRequest(slug="blocked", name="Blocked"),
                container,
                Response(),
            )
        )


class FakeSpacesMemoryScopesContainer:
    def __init__(
        self,
        *,
        policy_mode: MemoryPolicyMode = MemoryPolicyMode.SUGGESTIONS,
    ) -> None:
        self.settings = SimpleNamespace(policy_mode=policy_mode)
        self.spaces: dict[str, SimpleNamespace] = {}
        self.space_ids_by_slug: dict[str, str] = {}
        self.scopes: dict[str, SimpleNamespace] = {}
        self.scope_ids_by_space_and_ref: dict[tuple[str, str], str] = {}
        self.create_space = SimpleNamespace(execute=self._create_space)
        self.list_spaces = SimpleNamespace(execute=self._list_spaces)
        self.create_memory_scope = SimpleNamespace(execute=self._create_memory_scope)
        self.list_memory_scopes = SimpleNamespace(execute=self._list_memory_scopes)
        self.update_memory_scope = SimpleNamespace(execute=self._update_memory_scope)
        self.delete_memory_scope = SimpleNamespace(execute=self._delete_memory_scope)

    async def _create_space(self, command: object) -> SimpleNamespace:
        slug = str(command.slug)
        if slug in self.space_ids_by_slug:
            return SimpleNamespace(
                space=self.spaces[self.space_ids_by_slug[slug]],
                created=False,
            )
        space_id = f"space_{len(self.spaces) + 1}"
        space = SimpleNamespace(
            id=space_id,
            slug=slug,
            name=command.name,
            status=LifecycleStatus.ACTIVE,
            created_at=_now(),
            updated_at=_now(),
        )
        self.spaces[space_id] = space
        self.space_ids_by_slug[slug] = space_id
        return SimpleNamespace(space=space, created=True)

    async def _list_spaces(self, *, limit: int) -> list[SimpleNamespace]:
        return list(self.spaces.values())[:limit]

    async def _create_memory_scope(self, command: object) -> SimpleNamespace:
        space_id = str(command.space_id)
        if space_id not in self.spaces:
            raise MemoryValidationError("space is required")
        key = (space_id, command.external_ref)
        if key in self.scope_ids_by_space_and_ref:
            scope = self.scopes[self.scope_ids_by_space_and_ref[key]]
            if scope.status == LifecycleStatus.DELETED:
                scope.status = LifecycleStatus.ACTIVE
                scope.name = command.name
                scope.updated_at = _now()
            return SimpleNamespace(memory_scope=scope, created=False)
        scope_id = f"scope_{len(self.scopes) + 1}"
        scope = SimpleNamespace(
            id=scope_id,
            space_id=space_id,
            external_ref=command.external_ref,
            name=command.name,
            status=LifecycleStatus.ACTIVE,
            created_at=_now(),
            updated_at=_now(),
        )
        self.scopes[scope_id] = scope
        self.scope_ids_by_space_and_ref[key] = scope_id
        return SimpleNamespace(memory_scope=scope, created=True)

    async def _list_memory_scopes(
        self,
        *,
        space_id: object,
        limit: int,
    ) -> list[SimpleNamespace]:
        return [
            scope
            for scope in self.scopes.values()
            if scope.space_id == str(space_id) and scope.status != LifecycleStatus.DELETED
        ][:limit]

    async def _update_memory_scope(self, command: object) -> SimpleNamespace:
        scope = self.scopes[str(command.memory_scope_id)]
        if command.external_ref is not None:
            key = (scope.space_id, command.external_ref)
            existing_id = self.scope_ids_by_space_and_ref.get(key)
            if existing_id is not None and existing_id != scope.id:
                raise MemoryConflictError("memory_scope external_ref exists")
            old_key = (scope.space_id, scope.external_ref)
            self.scope_ids_by_space_and_ref.pop(old_key, None)
            self.scope_ids_by_space_and_ref[key] = scope.id
            scope.external_ref = command.external_ref
        if command.name is not None:
            scope.name = command.name
        scope.updated_at = _now()
        return SimpleNamespace(memory_scope=scope)

    async def _delete_memory_scope(self, command: object) -> SimpleNamespace:
        scope = self.scopes[str(command.memory_scope_id)]
        scope.status = LifecycleStatus.DELETED
        scope.updated_at = _now()
        return SimpleNamespace(memory_scope=scope)


def _now() -> datetime:
    return datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
