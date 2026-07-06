"""Thread-scoped memory lifecycle API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application import DeleteThreadMemoryCommand, GetSessionStatusQuery

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import resolve_existing_single_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.memory_scopes import public as memory_scopes_feature

ThreadMemoryScopeRequest = memory_scopes_feature.ThreadMemoryScopeRequest

router = APIRouter(
    prefix="/thread-memory",
    tags=["thread-memory"],
    dependencies=[Depends(require_service_token)],
)


@router.post("/status")
async def thread_memory_status(
    request: ThreadMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    scope = await resolve_existing_single_scope(
        container,
        **memory_scopes_feature.thread_memory_scope_resolution_kwargs(request),
    )
    if scope is None:
        return memory_scopes_feature.empty_thread_memory_status_response()
    result = await container.get_session_status.execute(
        GetSessionStatusQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        )
    )
    return memory_scopes_feature.thread_memory_status_response(result)


@router.delete("")
async def delete_thread_memory(
    request: ThreadMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await resolve_existing_single_scope(
        container,
        **memory_scopes_feature.thread_memory_scope_resolution_kwargs(request),
    )
    if scope is None:
        return memory_scopes_feature.empty_thread_memory_delete_response()
    result = await container.delete_thread_memory.execute(
        DeleteThreadMemoryCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        )
    )
    return memory_scopes_feature.thread_memory_delete_response(result)


@router.post("/delete")
async def delete_thread_memory_compat(
    request: ThreadMemoryScopeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return await delete_thread_memory(request, container)
