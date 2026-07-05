"""Portable memory export API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from infinity_context_core.application import (
    EnsureScopeCommand,
    ExportGraphQuery,
)
from infinity_context_core.domain.errors import MemoryValidationError

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import resolve_existing_single_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.memory_scopes import public as memory_scopes_feature
from infinity_context_server.memory_scope_transfer import (
    SUPPORTED_MERGE_STRATEGIES,
    export_memory_scope_payload,
    import_memory_scope_payload,
)

router = APIRouter(
    prefix="/export",
    tags=["export"],
    dependencies=[Depends(require_service_token)],
)


@router.get("/graph.json")
async def export_graph_json(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    include_deleted: Annotated[bool, Query()] = False,
    include_restricted: Annotated[bool, Query()] = False,
    max_facts: Annotated[int, Query(ge=0, le=1_000)] = 250,
    max_documents: Annotated[int, Query(ge=0, le=500)] = 100,
    max_episodes: Annotated[int, Query(ge=0, le=500)] = 100,
    max_chunks: Annotated[int, Query(ge=0, le=2_000)] = 500,
    max_anchors: Annotated[int, Query(ge=0, le=500)] = 100,
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
        return {"data": memory_scopes_feature.graph_export_scope_not_found_response()}
    graph = await container.export_graph.execute(
        ExportGraphQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            include_deleted=include_deleted,
            include_restricted=include_restricted,
            max_facts=max_facts,
            max_documents=max_documents,
            max_episodes=max_episodes,
            max_chunks=max_chunks,
            max_anchors=max_anchors,
        )
    )
    return {"data": memory_scopes_feature.graph_export_to_response(graph)}


@router.get("/memory_scope-snapshot")
async def export_memory_scope_snapshot(
    container: Annotated[Container, Depends(get_container)],
    space_slug: Annotated[str, Query(min_length=1, max_length=160)],
    memory_scope_external_ref: Annotated[str, Query(min_length=1, max_length=200)],
    redacted: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    result = await export_memory_scope_payload(
        engine=container.engine,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        redacted=redacted,
        blob_storage=container.blob_storage,
    )
    return memory_scopes_feature.memory_scope_snapshot_export_response(
        result=result,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
    )


@router.post("/memory_scope-snapshot/import")
async def import_memory_scope_snapshot(
    request: memory_scopes_feature.ImportMemoryScopeSnapshotRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    try:
        memory_scopes_feature.validate_memory_scope_snapshot_import_request(
            request,
            supported_merge_strategies=SUPPORTED_MERGE_STRATEGIES,
        )
    except memory_scopes_feature.MemoryScopeSnapshotCompatibilityError as exc:
        raise MemoryValidationError(str(exc)) from exc

    if request.dry_run:
        scope = await resolve_existing_single_scope(
            container,
            space_id=None,
            memory_scope_id=None,
            thread_id=None,
            space_slug=request.space_slug,
            memory_scope_external_ref=request.memory_scope_external_ref,
            thread_external_ref=None,
            thread_required=False,
        )
        space_id = str(scope.space_id) if scope else ""
        memory_scope_id = str(scope.memory_scope_id) if scope else ""
    else:
        ensure_server_writes_enabled(container)
        scope_result = await container.ensure_scope.execute(
            EnsureScopeCommand(
                space_slug=request.space_slug,
                memory_scope_external_ref=request.memory_scope_external_ref,
            )
        )
        space_id = str(scope_result.space_id)
        memory_scope_id = str(scope_result.memory_scope_id)

    result = await import_memory_scope_payload(
        engine=container.engine,
        now=container.clock.now(),
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        payload=request.snapshot,
        dry_run=request.dry_run,
        merge_strategy=request.merge_strategy,
        source_name=request.source_name,
        blob_storage=container.blob_storage,
    )
    return memory_scopes_feature.memory_scope_snapshot_transfer_response(result)


@router.post("/memory_scope-snapshot/preview")
async def preview_memory_scope_snapshot_import(
    request: memory_scopes_feature.PreviewMemoryScopeSnapshotRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    try:
        memory_scopes_feature.validate_memory_scope_snapshot_preview_request(
            request,
            supported_merge_strategies=SUPPORTED_MERGE_STRATEGIES,
        )
    except memory_scopes_feature.MemoryScopeSnapshotCompatibilityError as exc:
        raise MemoryValidationError(str(exc)) from exc
    scope = await resolve_existing_single_scope(
        container,
        space_id=None,
        memory_scope_id=None,
        thread_id=None,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    result = await import_memory_scope_payload(
        engine=container.engine,
        now=container.clock.now(),
        space_id=str(scope.space_id) if scope else "",
        memory_scope_id=str(scope.memory_scope_id) if scope else "",
        payload=request.snapshot,
        dry_run=True,
        merge_strategy=request.merge_strategy,
        source_name="api-memory_scope-snapshot-preview",
        blob_storage=container.blob_storage,
    )
    return memory_scopes_feature.memory_scope_snapshot_transfer_response(result)
