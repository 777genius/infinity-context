"""Spaces and profiles API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from memo_stack_core.application import CreateProfileCommand, CreateSpaceCommand
from memo_stack_core.domain.entities import MemoryProfile, MemorySpace, SpaceId
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.composition import Container

router = APIRouter(tags=["spaces-profiles"], dependencies=[Depends(require_service_token)])


class CreateSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)


class CreateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    external_ref: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=240)


def space_to_response(space: MemorySpace) -> dict[str, Any]:
    return {
        "id": str(space.id),
        "slug": space.slug,
        "name": space.name,
        "status": space.status.value,
        "created_at": space.created_at.isoformat(),
        "updated_at": space.updated_at.isoformat(),
    }


def profile_to_response(profile: MemoryProfile) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "space_id": str(profile.space_id),
        "external_ref": profile.external_ref,
        "name": profile.name,
        "status": profile.status.value,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


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


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    request: CreateProfileRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.create_profile.execute(
        CreateProfileCommand(
            space_id=SpaceId(request.space_id),
            external_ref=request.external_ref,
            name=request.name,
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"data": profile_to_response(result.profile)}


@router.get("/profiles")
async def list_profiles(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str, Query(min_length=1, max_length=80)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    profiles = await container.list_profiles.execute(space_id=SpaceId(space_id), limit=limit)
    return {"data": [profile_to_response(profile) for profile in profiles]}
