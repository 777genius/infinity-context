"""Memory browser read model API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from infinity_context_core.application import MemoryBrowserQuery

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1.anchors import anchor_to_response
from infinity_context_server.api.v1.captures import capture_to_response
from infinity_context_server.api.v1.context_links import (
    context_link_suggestion_to_response,
    context_link_to_response,
)
from infinity_context_server.api.v1.episodes import episode_to_response
from infinity_context_server.api.v1.scope_resolution import resolve_existing_single_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.document_ingestion import (
    public as document_ingestion_feature,
)
from infinity_context_server.features.memory_facts import public as memory_facts_feature
from infinity_context_server.features.memory_scopes import public as memory_scopes_feature

router = APIRouter(
    tags=["memory-browser"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/memory-browser")
async def get_memory_browser(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    fact_status: Annotated[str | None, Query(max_length=40)] = "active",
    episode_status: Annotated[str | None, Query(max_length=40)] = "active",
    document_status: Annotated[str | None, Query(max_length=40)] = "active",
    chunk_status: Annotated[str | None, Query(max_length=40)] = "active",
    extraction_status: Annotated[str | None, Query(max_length=40)] = None,
    thread_status: Annotated[str | None, Query(max_length=40)] = "active",
    capture_status: Annotated[str | None, Query(max_length=40)] = None,
    asset_status: Annotated[str | None, Query(max_length=40)] = "stored",
    anchor_status: Annotated[str | None, Query(max_length=40)] = "active",
    link_status: Annotated[str | None, Query(max_length=40)] = None,
    suggestion_status: Annotated[str | None, Query(max_length=40)] = None,
) -> dict[str, Any]:
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=None,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": _empty_browser_response(limit=limit)}
    result = await container.build_memory_browser.execute(
        MemoryBrowserQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            limit=limit,
            fact_status=fact_status,
            episode_status=episode_status,
            document_status=document_status,
            chunk_status=chunk_status,
            extraction_status=extraction_status,
            thread_status=thread_status,
            capture_status=capture_status,
            asset_status=asset_status,
            anchor_status=anchor_status,
            link_status=link_status,
            suggestion_status=suggestion_status,
        )
    )
    return {
        "data": {
            "generated_at": result.generated_at.isoformat(),
            "memory_scope": memory_scopes_feature.memory_scope_to_response(
                result.memory_scope,
            ),
            "facts": [
                memory_facts_feature.fact_to_response(fact) for fact in result.facts
            ],
            "episodes": [episode_to_response(episode) for episode in result.episodes],
            "documents": [
                document_ingestion_feature.document_to_response(document)
                for document in result.documents
            ],
            "chunks": [
                document_ingestion_feature.chunk_to_response(chunk)
                for chunk in result.chunks
            ],
            "extraction_jobs": [
                document_ingestion_feature.asset_extraction_to_response(job)
                for job in result.extraction_jobs
            ],
            "threads": [
                memory_scopes_feature.thread_to_response(thread) for thread in result.threads
            ],
            "captures": [capture_to_response(capture) for capture in result.captures],
            "assets": [
                document_ingestion_feature.asset_to_response(asset)
                for asset in result.assets
            ],
            "anchors": [anchor_to_response(anchor) for anchor in result.anchors],
            "context_links": [context_link_to_response(link) for link in result.context_links],
            "context_link_suggestions": [
                context_link_suggestion_to_response(suggestion)
                for suggestion in result.context_link_suggestions
            ],
            "stats": result.stats,
            "visual_summary": result.visual_summary,
            "quick_actions": list(result.quick_actions),
            "diagnostics": result.diagnostics,
        }
    }


def _empty_browser_response(*, limit: int) -> dict[str, Any]:
    return {
        "generated_at": None,
        "memory_scope": None,
        "facts": [],
        "episodes": [],
        "documents": [],
        "chunks": [],
        "extraction_jobs": [],
        "threads": [],
        "captures": [],
        "assets": [],
        "anchors": [],
        "context_links": [],
        "context_link_suggestions": [],
        "stats": {
            "facts": 0,
            "episodes": 0,
            "documents": 0,
            "chunks": 0,
            "extraction_jobs": 0,
            "threads": 0,
            "captures": 0,
            "assets": 0,
            "anchors": 0,
            "context_links": 0,
            "context_link_suggestions": 0,
            "pending_context_link_suggestions": 0,
            "active_context_links": 0,
        },
        "visual_summary": {
            "status": "empty",
            "evidence_count": 0,
            "relationship_count": 0,
            "pending_review_count": 0,
            "active_link_count": 0,
            "processing_job_count": 0,
            "failed_job_count": 0,
            "visible_sources": [],
            "limit_reached": False,
            "health_hints": ["scope_not_found", "empty_scope"],
        },
        "quick_actions": [
            {
                "id": "create_memory_scope",
                "label": "Create memory scope",
                "description": "Create this MemoryScope before saving visual memory.",
                "priority": 1,
            }
        ],
        "diagnostics": {
            "scope_not_found": True,
            "browser_version": "memory-browser-v1",
            "visual_summary_version": "visual-memory-summary-v1",
            "limit": limit,
        },
    }
