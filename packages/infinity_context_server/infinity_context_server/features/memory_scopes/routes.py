"""Feature-owned FastAPI route seam for memory_scopes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
import infinity_context_core.features.memory_scopes.public as memory_scopes

from infinity_context_server.features.memory_scopes.contracts import (
    ArchiveMemoryScopeHttpRequest,
    CreateMemoryScopeHttpRequest,
    RestoreMemoryScopeHttpRequest,
    TransferMemoryScopeOwnershipHttpRequest,
)
from infinity_context_server.features.memory_scopes.mappers import (
    archive_memory_scope_command_from_http,
    archive_memory_scope_result_to_response,
    create_memory_scope_command_from_contract,
    create_memory_scope_result_to_contract,
    restore_memory_scope_command_from_http,
    restore_memory_scope_result_to_response,
    transfer_memory_scope_ownership_command_from_http,
    transfer_memory_scope_ownership_result_to_response,
)


def create_memory_scopes_router(
    use_cases: memory_scopes.MemoryScopeUseCases,
    *,
    prefix: str = "",
) -> APIRouter:
    """Create routes that only translate HTTP contracts to feature use cases."""

    router = APIRouter(prefix=prefix, tags=["memory_scopes"])

    @router.post("/memory-scopes", status_code=status.HTTP_201_CREATED)
    async def create_memory_scope(
        request: CreateMemoryScopeHttpRequest,
    ) -> dict[str, Any]:
        try:
            command = create_memory_scope_command_from_contract(
                request.to_contract(),
                owner=request.owner,
            )
            result = await use_cases.create_memory_scope.execute(command)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeDomainError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        return create_memory_scope_result_to_contract(result).to_dict()

    @router.post("/memory-scopes/{memory_scope_id}/ownership")
    async def transfer_memory_scope_ownership(
        memory_scope_id: str,
        request: TransferMemoryScopeOwnershipHttpRequest,
    ) -> dict[str, Any]:
        try:
            command = transfer_memory_scope_ownership_command_from_http(
                memory_scope_id,
                request,
            )
            result = await use_cases.transfer_memory_scope_ownership.execute(command)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeOwnershipError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeDomainError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return transfer_memory_scope_ownership_result_to_response(result)

    @router.post("/memory-scopes/{memory_scope_id}/archive")
    async def archive_memory_scope(
        memory_scope_id: str,
        request: ArchiveMemoryScopeHttpRequest,
    ) -> dict[str, Any]:
        try:
            command = archive_memory_scope_command_from_http(
                memory_scope_id,
                request,
            )
            result = await use_cases.archive_memory_scope.execute(command)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeLifecycleError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeDomainError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return archive_memory_scope_result_to_response(result)

    @router.post("/memory-scopes/{memory_scope_id}/restore")
    async def restore_memory_scope(
        memory_scope_id: str,
        request: RestoreMemoryScopeHttpRequest,
    ) -> dict[str, Any]:
        try:
            command = restore_memory_scope_command_from_http(
                memory_scope_id,
                request,
            )
            result = await use_cases.restore_memory_scope.execute(command)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeLifecycleError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except memory_scopes.MemoryScopeDomainError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        return restore_memory_scope_result_to_response(result)

    return router


__all__ = ("create_memory_scopes_router",)
