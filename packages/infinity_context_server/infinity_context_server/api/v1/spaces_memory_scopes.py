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
from infinity_context_core.domain.entities import MemoryScope, MemoryScopeId, MemorySpace, SpaceId
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


class CreateMemoryScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    external_ref: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=240)


class UpdateMemoryScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=240)


def space_to_response(space: MemorySpace) -> dict[str, Any]:
    return {
        "id": str(space.id),
        "slug": space.slug,
        "name": space.name,
        "status": space.status.value,
        "created_at": space.created_at.isoformat(),
        "updated_at": space.updated_at.isoformat(),
    }


def memory_scope_to_response(memory_scope: MemoryScope) -> dict[str, Any]:
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
    contract = memory_scopes_feature.create_memory_scope_contract_from_http_request(
        request,
    )
    result = await container.create_memory_scope.execute(
        CreateMemoryScopeCommand(
            space_id=SpaceId(contract.space_id or ""),
            external_ref=contract.external_ref,
            name=contract.name,
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"data": memory_scope_to_response(result.memory_scope)}


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
    return {"data": [memory_scope_to_response(memory_scope) for memory_scope in memory_scopes]}


@router.patch("/memory-scopes/{memory_scope_id}")
async def update_memory_scope(
    memory_scope_id: str,
    request: UpdateMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    if request.external_ref is None and request.name is None:
        raise MemoryValidationError("At least one memory_scope field is required")
    result = await container.update_memory_scope.execute(
        UpdateMemoryScopeCommand(
            memory_scope_id=MemoryScopeId(memory_scope_id),
            external_ref=request.external_ref,
            name=request.name,
        )
    )
    return {"data": memory_scope_to_response(result.memory_scope)}


@router.delete("/memory-scopes/{memory_scope_id}")
async def delete_memory_scope(
    memory_scope_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_memory_scope.execute(
        DeleteMemoryScopeCommand(memory_scope_id=MemoryScopeId(memory_scope_id))
    )
    return {"data": memory_scope_to_response(result.memory_scope)}
