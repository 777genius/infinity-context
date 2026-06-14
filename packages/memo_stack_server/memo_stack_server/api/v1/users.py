"""Canonical users and space membership API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from memo_stack_core.application import (
    CheckSpaceAccessQuery,
    CreateSpaceMembershipCommand,
    CreateUserCommand,
    ListSpaceMembershipsQuery,
    ListUsersQuery,
)
from memo_stack_core.domain.entities import SpaceId, SpaceMembership, User
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.composition import Container

router = APIRouter(
    tags=["users-acl"],
    dependencies=[Depends(require_service_token)],
)


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    metadata: dict[str, Any] | None = None


class CreateSpaceMembershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=80)
    role: str = Field(default="member", min_length=1, max_length=40)


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.create_user.execute(
        CreateUserCommand(
            external_ref=request.external_ref,
            display_name=request.display_name,
            email=request.email,
            metadata=request.metadata,
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"data": user_to_response(result.user)}


@router.get("/users")
async def list_users(
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    result = await container.list_users.execute(
        ListUsersQuery(status=status_filter, limit=limit)
    )
    return {"data": [user_to_response(user) for user in result.users]}


@router.post("/spaces/{space_id}/memberships", status_code=status.HTTP_201_CREATED)
async def create_space_membership(
    space_id: str,
    request: CreateSpaceMembershipRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.create_space_membership.execute(
        CreateSpaceMembershipCommand(
            space_id=SpaceId(space_id),
            user_id=request.user_id,
            role=request.role,
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return {"data": space_membership_to_response(result.membership)}


@router.get("/spaces/{space_id}/memberships")
async def list_space_memberships(
    space_id: str,
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    result = await container.list_space_memberships.execute(
        ListSpaceMembershipsQuery(
            space_id=SpaceId(space_id),
            status=status_filter,
            limit=limit,
        )
    )
    return {"data": [space_membership_to_response(item) for item in result.memberships]}


@router.get("/spaces/{space_id}/memberships/{user_id}/access")
async def check_space_access(
    space_id: str,
    user_id: str,
    container: Annotated[Container, Depends(get_container)],
    required_role: Annotated[str, Query(max_length=40)] = "viewer",
) -> dict[str, Any]:
    result = await container.check_space_access.execute(
        CheckSpaceAccessQuery(
            space_id=SpaceId(space_id),
            user_id=user_id,
            required_role=required_role,
        )
    )
    return {
        "data": {
            "allowed": result.allowed,
            "required_role": result.required_role,
            "membership": (
                space_membership_to_response(result.membership)
                if result.membership is not None
                else None
            ),
        }
    }


def user_to_response(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "external_ref": user.external_ref,
        "display_name": user.display_name,
        "email": user.email,
        "status": user.status.value,
        "metadata": dict(user.metadata),
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def space_membership_to_response(membership: SpaceMembership) -> dict[str, Any]:
    return {
        "id": str(membership.id),
        "space_id": str(membership.space_id),
        "user_id": str(membership.user_id),
        "role": membership.role.value,
        "status": membership.status.value,
        "created_at": membership.created_at.isoformat(),
        "updated_at": membership.updated_at.isoformat(),
    }
