"""Operational console API for ingestion and memory linking."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from infinity_context_core.application import MemoryOperationsConsoleQuery

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1.context_links import context_link_suggestion_to_response
from infinity_context_server.api.v1.scope_resolution import resolve_existing_single_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.document_ingestion import public as document_ingestion_server

router = APIRouter(
    tags=["operations"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/operations-console")
async def get_operations_console(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        return {
            "data": {
                "generated_at": None,
                "scope": None,
                "extraction_status_counts": {},
                "link_suggestion_status_counts": {},
                "extraction_jobs": [],
                "context_link_suggestions": [],
                "diagnostics": {"scope_not_found": True},
            }
        }

    result = await container.build_memory_operations_console.execute(
        MemoryOperationsConsoleQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            limit=limit,
        )
    )
    return {
        "data": {
            "generated_at": result.generated_at.isoformat(),
            "scope": result.scope,
            "extraction_status_counts": result.extraction_status_counts,
            "link_suggestion_status_counts": result.link_suggestion_status_counts,
            "extraction_jobs": [
                document_ingestion_server.asset_extraction_to_response(job)
                for job in result.extraction_jobs
            ],
            "context_link_suggestions": [
                context_link_suggestion_to_response(item)
                for item in result.context_link_suggestions
            ],
            "diagnostics": result.diagnostics,
        }
    }
