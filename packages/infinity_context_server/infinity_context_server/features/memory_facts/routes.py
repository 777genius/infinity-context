"""Feature-owned FastAPI route seam for memory_facts."""

from __future__ import annotations

from typing import Annotated, Any

import infinity_context_core.features.memory_facts.public as memory_facts
from fastapi import APIRouter, Header, HTTPException, status

from infinity_context_server.features.memory_facts.contracts import (
    ForgetFactHttpRequest,
    RememberFactHttpRequest,
    UpdateFactHttpRequest,
)
from infinity_context_server.features.memory_facts.mappers import (
    forget_fact_command_from_http,
    forget_fact_result_to_contract,
    remember_fact_command_from_contract,
    remember_fact_result_to_contract,
    update_fact_command_from_http,
    update_fact_result_to_contract,
)


def create_memory_facts_router(
    use_cases: memory_facts.MemoryFactLifecycleUseCases | None = None,
    *,
    prefix: str = "",
    composition: object | None = None,
) -> APIRouter:
    """Create routes that only translate HTTP contracts to feature use cases."""

    if use_cases is None and composition is not None:
        use_cases = getattr(composition, "use_cases", None)

    router_prefix = prefix
    if use_cases is None and not router_prefix:
        router_prefix = "/facts"
    router = APIRouter(prefix=router_prefix, tags=["memory_facts"])

    if use_cases is None:
        return router

    @router.post("/facts", status_code=status.HTTP_201_CREATED)
    async def remember_fact(
        request: RememberFactHttpRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> dict[str, Any]:
        try:
            command = remember_fact_command_from_contract(
                request.to_contract(),
                idempotency_key=idempotency_key,
            )
            result = await use_cases.remember_fact.execute(command)
        except (KeyError, TypeError, ValueError) as exc:
            _raise_memory_fact_http_error(exc)

        return remember_fact_result_to_contract(result).to_dict()

    @router.patch("/facts/{fact_id}")
    async def update_fact(
        fact_id: str,
        request: UpdateFactHttpRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> dict[str, Any]:
        try:
            command = update_fact_command_from_http(
                fact_id,
                request,
                idempotency_key=idempotency_key,
            )
            result = await use_cases.update_fact.execute(command)
        except (KeyError, TypeError, LookupError, ValueError) as exc:
            _raise_memory_fact_http_error(exc)

        return update_fact_result_to_contract(result).to_dict()

    @router.delete("/facts/{fact_id}")
    async def forget_fact(
        fact_id: str,
        request: ForgetFactHttpRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key"),
        ] = None,
    ) -> dict[str, Any]:
        try:
            command = forget_fact_command_from_http(
                fact_id,
                request,
                idempotency_key=idempotency_key,
            )
            result = await use_cases.forget_fact.execute(command)
        except (KeyError, TypeError, LookupError, ValueError) as exc:
            _raise_memory_fact_http_error(exc)

        return forget_fact_result_to_contract(result).to_dict()

    return router


def _raise_memory_fact_http_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        status_code = status.HTTP_404_NOT_FOUND
    elif "version conflict" in str(exc).casefold():
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


__all__ = ("create_memory_facts_router",)
