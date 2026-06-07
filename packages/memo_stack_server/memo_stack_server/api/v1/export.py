"""Portable memory export API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from memo_stack_core.application import EnsureScopeCommand, ExportGraphQuery, GraphExportResult
from memo_stack_core.domain.errors import MemoryValidationError
from memo_stack_core.profile_snapshots import (
    build_snapshot_manifest,
    verify_snapshot_manifest_payload,
)
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.api.v1.scope_resolution import resolve_existing_single_scope
from memo_stack_server.composition import Container
from memo_stack_server.profile_transfer import (
    SUPPORTED_MERGE_STRATEGIES,
    export_profile_payload,
    import_profile_payload,
)

router = APIRouter(
    prefix="/export",
    tags=["export"],
    dependencies=[Depends(require_service_token)],
)


class ImportProfileSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_slug: str = Field(min_length=1, max_length=160)
    profile_external_ref: str = Field(min_length=1, max_length=200)
    snapshot: dict[str, Any]
    manifest: dict[str, Any] | None = None
    dry_run: bool = True
    merge_strategy: str = Field(default="fail_on_conflict", max_length=80)
    confirmed: bool = False
    source_name: str = Field(default="api-profile-snapshot", max_length=160)


@router.get("/graph.json")
async def export_graph_json(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    profile_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    profile_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    include_deleted: Annotated[bool, Query()] = False,
    include_restricted: Annotated[bool, Query()] = False,
    max_facts: Annotated[int, Query(ge=0, le=1_000)] = 250,
    max_documents: Annotated[int, Query(ge=0, le=500)] = 100,
    max_chunks: Annotated[int, Query(ge=0, le=2_000)] = 500,
) -> dict[str, Any]:
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        profile_id=profile_id,
        thread_id=thread_id,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        return {
            "data": {
                "schema_version": "memo_stack.graph_export.v1",
                "scope": {"scope_not_found": True},
                "nodes": [],
                "edges": [],
                "counts": {"facts": 0, "documents": 0, "chunks": 0, "nodes": 0, "edges": 0},
                "truncated": False,
                "warnings": ["scope_not_found"],
            }
        }
    graph = await container.export_graph.execute(
        ExportGraphQuery(
            space_id=scope.space_id,
            profile_id=scope.profile_id,
            thread_id=scope.thread_id,
            include_deleted=include_deleted,
            include_restricted=include_restricted,
            max_facts=max_facts,
            max_documents=max_documents,
            max_chunks=max_chunks,
        )
    )
    return {"data": graph_export_to_response(graph)}


@router.get("/profile-snapshot")
async def export_profile_snapshot(
    container: Annotated[Container, Depends(get_container)],
    space_slug: Annotated[str, Query(min_length=1, max_length=160)],
    profile_external_ref: Annotated[str, Query(min_length=1, max_length=200)],
    redacted: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    result = await export_profile_payload(
        engine=container.engine,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        redacted=redacted,
    )
    if result["status"] != "ok":
        return {"data": None, "status": result["status"]}
    snapshot = result["snapshot"]
    redacted = bool(result["redacted"])
    return {
        "data": snapshot,
        "status": "ok",
        "counts": result["counts"],
        "redacted": redacted,
        "manifest": build_snapshot_manifest(
            snapshot=snapshot,
            space_slug=space_slug,
            profile_external_ref=profile_external_ref,
            redacted=redacted,
        ),
    }


@router.post("/profile-snapshot/import")
async def import_profile_snapshot(
    request: ImportProfileSnapshotRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    if request.merge_strategy not in SUPPORTED_MERGE_STRATEGIES:
        raise MemoryValidationError("Unsupported profile snapshot merge strategy")
    if not request.dry_run and not request.confirmed:
        raise MemoryValidationError("Profile snapshot import requires confirmed=true")
    if request.manifest is not None:
        verification = verify_snapshot_manifest_payload(
            snapshot=request.snapshot,
            manifest=request.manifest,
            expected_snapshot_file=None,
        )
        if not verification["ok"]:
            errors = ", ".join(verification["errors"])
            raise MemoryValidationError(
                f"Profile snapshot manifest verification failed: {errors}"
            )

    if request.dry_run:
        scope = await resolve_existing_single_scope(
            container,
            space_id=None,
            profile_id=None,
            thread_id=None,
            space_slug=request.space_slug,
            profile_external_ref=request.profile_external_ref,
            thread_external_ref=None,
            thread_required=False,
        )
        space_id = str(scope.space_id) if scope else ""
        profile_id = str(scope.profile_id) if scope else ""
    else:
        ensure_server_writes_enabled(container)
        scope_result = await container.ensure_scope.execute(
            EnsureScopeCommand(
                space_slug=request.space_slug,
                profile_external_ref=request.profile_external_ref,
            )
        )
        space_id = str(scope_result.space_id)
        profile_id = str(scope_result.profile_id)

    result = await import_profile_payload(
        engine=container.engine,
        now=container.clock.now(),
        space_id=space_id,
        profile_id=profile_id,
        payload=request.snapshot,
        dry_run=request.dry_run,
        merge_strategy=request.merge_strategy,
        source_name=request.source_name,
    )
    return {"data": result}


def graph_export_to_response(graph: GraphExportResult) -> dict[str, Any]:
    return {
        "schema_version": graph.schema_version,
        "scope": graph.scope,
        "nodes": [
            {
                "id": node.id,
                "type": node.type,
                "label": node.label,
                "data": node.data,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "id": edge.id,
                "type": edge.type,
                "source": edge.source,
                "target": edge.target,
                "label": edge.label,
                "data": edge.data,
            }
            for edge in graph.edges
        ],
        "counts": graph.counts,
        "truncated": graph.truncated,
        "warnings": list(graph.warnings),
    }
