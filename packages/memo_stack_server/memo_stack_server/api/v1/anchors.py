"""Semantic anchor lifecycle API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from memo_stack_core.application import (
    AnchorMergeCandidate,
    AnchorMergeSuggestionsQuery,
    BackfillAnchorsCommand,
    CreateAnchorCommand,
    DeleteAnchorCommand,
    ListAnchorsQuery,
    MergeAnchorsCommand,
    SplitAnchorCommand,
    UpdateAnchorCommand,
)
from memo_stack_core.domain.entities import MemoryAnchor, SourceRef
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.api.public_payload import safe_public_metadata
from memo_stack_server.api.v1.scope_resolution import resolve_existing_single_scope
from memo_stack_server.api.v1.source_refs import source_ref_to_response
from memo_stack_server.composition import Container

router = APIRouter(
    tags=["anchors"],
    dependencies=[Depends(require_service_token)],
)


class AnchorScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)


class BackfillAnchorsRequest(AnchorScopeRequest):
    limit_per_source: int = Field(default=100, ge=1, le=500)


class AnchorEvidenceRefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)
    chunk_id: str | None = Field(default=None, max_length=160)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote_preview: str | None = Field(default=None, max_length=240)
    page_number: int | None = Field(default=None, ge=1)
    time_start_ms: int | None = Field(default=None, ge=0)
    time_end_ms: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None


class CreateAnchorRequest(AnchorScopeRequest):
    kind: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    confidence: str | None = Field(default=None, max_length=40)
    evidence_refs: list[AnchorEvidenceRefRequest] = Field(default_factory=list, max_length=20)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=240)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    confidence: str | None = Field(default=None, max_length=40)
    evidence_refs: list[AnchorEvidenceRefRequest] = Field(default_factory=list, max_length=20)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeleteAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="manual delete", min_length=1, max_length=320)


class MergeAnchorsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_anchor_id: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=320)


class SplitAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(min_length=1, max_length=240)
    new_label: str | None = Field(default=None, min_length=1, max_length=240)
    reason: str = Field(default="manual split", min_length=1, max_length=320)


@router.get("/anchors")
async def list_anchors(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
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
        return {"data": []}
    result = await container.list_anchors.execute(
        ListAnchorsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            kind=kind,
            status=status_filter,
            limit=limit,
        )
    )
    return {"data": [anchor_to_response(anchor) for anchor in result.anchors]}


@router.post("/anchors")
async def create_anchor(
    request: CreateAnchorRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await resolve_existing_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=None,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": None, "scope_not_found": True}
    result = await container.create_anchor.execute(
        CreateAnchorCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            kind=request.kind,
            label=request.label,
            aliases=tuple(request.aliases),
            description=request.description,
            confidence=request.confidence,
            evidence_refs=tuple(_map_anchor_evidence_ref(ref) for ref in request.evidence_refs),
            observed_at=request.observed_at,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            metadata=request.metadata,
        )
    )
    return {"data": anchor_to_response(result.anchor)}


@router.patch("/anchors/{anchor_id}")
async def update_anchor(
    anchor_id: str,
    request: UpdateAnchorRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.update_anchor.execute(
        UpdateAnchorCommand(
            anchor_id=anchor_id,
            label=request.label,
            aliases=tuple(request.aliases),
            description=request.description,
            confidence=request.confidence,
            evidence_refs=tuple(_map_anchor_evidence_ref(ref) for ref in request.evidence_refs),
            observed_at=request.observed_at,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            metadata=request.metadata,
        )
    )
    return {"data": anchor_to_response(result.anchor)}


@router.delete("/anchors/{anchor_id}")
async def delete_anchor(
    anchor_id: str,
    request: DeleteAnchorRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_anchor.execute(
        DeleteAnchorCommand(anchor_id=anchor_id, reason=request.reason)
    )
    return {"data": anchor_to_response(result.anchor)}


@router.get("/anchors/merge-suggestions")
async def suggest_anchor_merges(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
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
        return {"data": {"candidates": [], "diagnostics": {"scope_not_found": True}}}
    result = await container.suggest_anchor_merges.execute(
        AnchorMergeSuggestionsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            kind=kind,
            limit=limit,
        )
    )
    return {
        "data": {
            "candidates": [merge_candidate_to_response(item) for item in result.candidates],
            "diagnostics": result.diagnostics,
        }
    }


@router.post("/anchors/backfill")
async def backfill_anchors(
    request: BackfillAnchorsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await resolve_existing_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=None,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": {"anchors": [], "created": 0, "updated": 0, "scope_not_found": True}}
    result = await container.backfill_anchors.execute(
        BackfillAnchorsCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            limit_per_source=request.limit_per_source,
        )
    )
    return {
        "data": {
            "anchors": [anchor_to_response(anchor) for anchor in result.anchors],
            "created": result.created,
            "updated": result.updated,
            "sources": [
                {
                    "source_type": item.source_type,
                    "scanned": item.scanned,
                    "observed": item.observed,
                }
                for item in result.sources
            ],
            "diagnostics": result.diagnostics,
        }
    }


@router.post("/anchors/{source_anchor_id}/merge")
async def merge_anchor(
    source_anchor_id: str,
    request: MergeAnchorsRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.merge_anchors.execute(
        MergeAnchorsCommand(
            source_anchor_id=source_anchor_id,
            target_anchor_id=request.target_anchor_id,
            reason=request.reason,
        )
    )
    return {"data": anchor_to_response(result.anchor)}


@router.post("/anchors/{anchor_id}/split")
async def split_anchor(
    anchor_id: str,
    request: SplitAnchorRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.split_anchor.execute(
        SplitAnchorCommand(
            anchor_id=anchor_id,
            alias=request.alias,
            new_label=request.new_label,
            reason=request.reason,
        )
    )
    return {"data": anchor_to_response(result.anchor)}


def merge_candidate_to_response(candidate: AnchorMergeCandidate) -> dict[str, Any]:
    return {
        "source_anchor": anchor_to_response(candidate.source_anchor),
        "target_anchor": anchor_to_response(candidate.target_anchor),
        "confidence": candidate.confidence,
        "score": candidate.score,
        "reasons": list(candidate.reasons),
        "metadata": safe_public_metadata(candidate.metadata),
    }


def anchor_to_response(anchor: MemoryAnchor) -> dict[str, Any]:
    confidence = getattr(anchor, "confidence", None)
    observed_at = getattr(anchor, "observed_at", None) or anchor.created_at
    return {
        "id": str(anchor.id),
        "space_id": str(anchor.space_id),
        "memory_scope_id": str(anchor.memory_scope_id),
        "kind": _enum_or_text(anchor.kind),
        "normalized_key": anchor.normalized_key,
        "label": anchor.label,
        "aliases": list(anchor.aliases),
        "description": anchor.description,
        "status": _enum_or_text(anchor.status),
        "confidence": _enum_or_text(confidence or "medium"),
        "evidence_refs": [
            _anchor_evidence_ref_to_response(ref) for ref in getattr(anchor, "evidence_refs", ())
        ],
        "observed_at": _datetime_to_response(observed_at),
        "valid_from": _datetime_to_response(getattr(anchor, "valid_from", None)),
        "valid_to": _datetime_to_response(getattr(anchor, "valid_to", None)),
        "metadata": safe_public_metadata(getattr(anchor, "metadata", {})),
        "created_at": _datetime_to_response(anchor.created_at),
        "updated_at": _datetime_to_response(anchor.updated_at),
    }


def _map_anchor_evidence_ref(request: AnchorEvidenceRefRequest) -> SourceRef:
    return SourceRef(
        source_type=request.source_type,
        source_id=request.source_id,
        chunk_id=request.chunk_id,
        char_start=request.char_start,
        char_end=request.char_end,
        quote_preview=request.quote_preview,
        page_number=request.page_number,
        time_start_ms=request.time_start_ms,
        time_end_ms=request.time_end_ms,
        bbox=request.bbox,
    )


def _anchor_evidence_ref_to_response(ref: SourceRef) -> dict[str, Any]:
    return source_ref_to_response(ref)


def _datetime_to_response(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _enum_or_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)
