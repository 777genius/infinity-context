"""Spaces and memory scopes API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from infinity_context_core.application import (
    CreateMemoryScopeCommand,
    CreateSpaceCommand,
    DeleteMemoryScopeCommand,
    UpdateMemoryScopeCommand,
)
from infinity_context_core.domain.entities import MemoryScopeId, MemorySpace, SpaceId
from infinity_context_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.composition import Container
from infinity_context_server.features.memory_scopes import public as memory_scopes_feature

router = APIRouter(tags=["spaces-memory-scopes"], dependencies=[Depends(require_service_token)])


class CreateSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)


CreateMemoryScopeRequest = memory_scopes_feature.CreateMemoryScopeRequest
UpdateMemoryScopeRequest = memory_scopes_feature.UpdateMemoryScopeRequest


def space_to_response(space: MemorySpace) -> dict[str, Any]:
    return {
        "id": str(space.id),
        "slug": space.slug,
        "name": space.name,
        "status": space.status.value,
        "created_at": space.created_at.isoformat(),
        "updated_at": space.updated_at.isoformat(),
    }


def memory_scope_to_response(memory_scope: object) -> dict[str, Any]:
    return memory_scopes_feature.memory_scope_to_response(memory_scope)


@router.post("/spaces", status_code=status.HTTP_201_CREATED)
async def create_space(
    request: CreateSpaceRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.create_space.execute(
        CreateSpaceCommand(slug=request.slug, name=request.name)
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"data": space_to_response(result.space)}


@router.get("/spaces")
async def list_spaces(
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    spaces = await container.list_spaces.execute(limit=limit)
    return {"data": [space_to_response(space) for space in spaces]}


@router.post("/memory-scopes", status_code=status.HTTP_201_CREATED)
async def create_memory_scope(
    request: CreateMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    command_payload = (
        memory_scopes_feature.create_memory_scope_compatibility_command_from_request(
            request,
        )
    )
    result = await container.create_memory_scope.execute(
        CreateMemoryScopeCommand(
            space_id=SpaceId(command_payload.space_id),
            external_ref=command_payload.external_ref,
            name=command_payload.name,
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return memory_scopes_feature.memory_scope_compatibility_response(result.memory_scope)


@router.get("/memory-scopes")
async def list_memory_scopes(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str, Query(min_length=1, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    memory_scopes = await container.list_memory_scopes.execute(
        space_id=SpaceId(space_id),
        limit=limit,
    )
    return memory_scopes_feature.memory_scope_collection_compatibility_response(
        memory_scopes,
    )


@router.patch("/memory-scopes/{memory_scope_id}")
async def update_memory_scope(
    memory_scope_id: str,
    request: UpdateMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    try:
        command_payload = (
            memory_scopes_feature.update_memory_scope_compatibility_command_from_request(
                memory_scope_id,
                request,
            )
        )
    except ValueError as exc:
        raise MemoryValidationError(str(exc)) from exc
    result = await container.update_memory_scope.execute(
        UpdateMemoryScopeCommand(
            memory_scope_id=MemoryScopeId(command_payload.memory_scope_id),
            external_ref=command_payload.external_ref,
            name=command_payload.name,
        )
    )
    return memory_scopes_feature.memory_scope_compatibility_response(result.memory_scope)


@router.delete("/memory-scopes/{memory_scope_id}")
async def delete_memory_scope(
    memory_scope_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    command_payload = (
        memory_scopes_feature.delete_memory_scope_compatibility_command_from_path(
            memory_scope_id,
        )
    )
    result = await container.delete_memory_scope.execute(
        DeleteMemoryScopeCommand(
            memory_scope_id=MemoryScopeId(command_payload.memory_scope_id)
        )
    )
    return memory_scopes_feature.memory_scope_compatibility_response(result.memory_scope)
