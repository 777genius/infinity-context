"""Fact lifecycle API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from memo_stack_core.application import (
    FactRelationItem,
    FactVersionsQuery,
    ForgetFactCommand,
    GetFactQuery,
    LinkFactsCommand,
    ListFactRelationsQuery,
    ListFactsQuery,
    RelatedFactItem,
    RelatedFactsQuery,
    RememberFactCommand,
    UnlinkFactRelationCommand,
    UpdateFactCommand,
)
from memo_stack_core.domain.entities import (
    FactRelationType,
    FactStatus,
    LifecycleStatus,
    MemoryFact,
    MemoryFactRelation,
    MemoryKind,
    SourceRef,
)
from memo_stack_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled
from memo_stack_server.api.public_payload import safe_public_text
from memo_stack_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from memo_stack_server.api.v1.source_refs import source_ref_to_response
from memo_stack_server.composition import Container
from memo_stack_server.pagination import cursor_datetime, cursor_str, decode_cursor, encode_cursor

router = APIRouter(
    prefix="/facts",
    tags=["facts"],
    dependencies=[Depends(require_service_token)],
)


class SourceRefRequest(BaseModel):
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


class RememberFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4000)
    kind: str = "note"
    source_refs: list[SourceRefRequest] = Field(min_length=1)
    classification: str = Field(default="internal", max_length=40)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=10)
    ttl_policy: str | None = Field(default=None, max_length=80)


class UpdateFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=240)
    source_refs: list[SourceRefRequest] = Field(min_length=1)


class LinkFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_fact_id: str = Field(min_length=1, max_length=160)
    relation_type: str = Field(default=FactRelationType.RELATED_TO.value, max_length=80)
    reason: str = Field(min_length=1, max_length=320)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def map_source_ref(request: SourceRefRequest) -> SourceRef:
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


def map_memory_kind(value: str) -> MemoryKind:
    try:
        return MemoryKind(value)
    except ValueError as exc:
        raise MemoryValidationError(f"Unknown memory kind: {value}") from exc


def fact_to_response(fact: MemoryFact, indexing_status: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(fact.id),
        "space_id": str(fact.space_id),
        "memory_scope_id": str(fact.memory_scope_id),
        "thread_id": str(fact.thread_id) if fact.thread_id else None,
        "text": fact.text,
        "kind": fact.kind.value,
        "status": fact.status.value,
        "version": fact.version,
        "confidence": fact.confidence.value,
        "trust_level": fact.trust_level.value,
        "classification": fact.classification,
        "category": fact.category,
        "tags": list(fact.tags),
        "ttl_policy": fact.ttl_policy,
        "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
        "source_refs": [source_ref_to_response(ref) for ref in fact.source_refs],
        "created_at": fact.created_at.isoformat(),
        "updated_at": fact.updated_at.isoformat(),
    }
    if indexing_status is not None:
        body["indexing_status"] = indexing_status
    return body


def related_fact_to_response(item: RelatedFactItem) -> dict[str, Any]:
    body = fact_to_response(item.fact)
    body["score"] = item.score
    body["relation_reasons"] = list(item.relation_reasons)
    return body


def fact_relation_to_response(relation: MemoryFactRelation) -> dict[str, Any]:
    observed_at = getattr(relation, "observed_at", None) or relation.created_at
    return {
        "id": str(relation.id),
        "space_id": str(relation.space_id),
        "memory_scope_id": str(relation.memory_scope_id),
        "source_fact_id": str(relation.source_fact_id),
        "target_fact_id": str(relation.target_fact_id),
        "relation_type": _enum_or_text(relation.relation_type),
        "reason": safe_public_text(getattr(relation, "reason", "")),
        "status": _enum_or_text(relation.status),
        "observed_at": _datetime_to_response(observed_at),
        "valid_from": _datetime_to_response(getattr(relation, "valid_from", None)),
        "valid_to": _datetime_to_response(getattr(relation, "valid_to", None)),
        "created_at": _datetime_to_response(relation.created_at),
        "updated_at": _datetime_to_response(relation.updated_at),
    }


def fact_relation_item_to_response(item: FactRelationItem) -> dict[str, Any]:
    return {
        "relation": fact_relation_to_response(item.relation),
        "related_fact": fact_to_response(item.related_fact),
        "direction": item.direction,
    }


def _datetime_to_response(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _enum_or_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


@router.post("", status_code=status.HTTP_201_CREATED)
async def remember_fact(
    request: RememberFactRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=False,
    )
    result = await container.remember_fact.execute(
        RememberFactCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            text=request.text,
            kind=map_memory_kind(request.kind),
            source_refs=tuple(map_source_ref(ref) for ref in request.source_refs),
            classification=request.classification,
            category=request.category,
            tags=tuple(request.tags),
            ttl_policy=request.ttl_policy,
            idempotency_key=idempotency_key,
        )
    )
    if result.indexing_status == "already_indexed_or_pending":
        response.status_code = status.HTTP_200_OK
    return {"data": fact_to_response(result.fact, result.indexing_status)}


@router.get("")
async def list_facts(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    thread_id: Annotated[str | None, Query(max_length=80)] = None,
    thread_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    category: Annotated[str | None, Query(max_length=80)] = None,
    tag: Annotated[str | None, Query(max_length=48)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> dict[str, Any]:
    _validate_fact_status(status_filter)
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
        return {"data": [], "next_cursor": None}
    decoded_cursor = decode_cursor(cursor, kind="facts")
    result = await container.list_facts.execute(
        ListFactsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            status=status_filter,
            limit=limit + 1,
            cursor_updated_at=cursor_datetime(decoded_cursor, "updated_at"),
            cursor_id=cursor_str(decoded_cursor, "id"),
            category=category,
            tag=tag,
        )
    )
    facts = list(result.facts)
    visible_facts = facts[:limit]
    next_cursor = None
    if len(facts) > limit and visible_facts:
        last = visible_facts[-1]
        next_cursor = encode_cursor(
            "facts",
            updated_at=last.updated_at.isoformat(),
            id=str(last.id),
        )
    return {
        "data": [fact_to_response(fact) for fact in visible_facts],
        "next_cursor": next_cursor,
    }


@router.get("/{fact_id}")
async def get_fact(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_fact.execute(GetFactQuery(fact_id=fact_id))
    return {"data": fact_to_response(result.fact)}


@router.get("/{fact_id}/versions")
async def list_fact_versions(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.list_fact_versions.execute(FactVersionsQuery(fact_id=fact_id))
    return {"data": [fact_to_response(version) for version in result.facts]}


@router.get("/{fact_id}/related")
async def related_facts(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_other_threads: bool = False,
) -> dict[str, Any]:
    result = await container.related_facts.execute(
        RelatedFactsQuery(
            fact_id=fact_id,
            limit=limit,
            include_other_threads=include_other_threads,
        )
    )
    return {
        "data": {
            "target": fact_to_response(result.target),
            "items": [related_fact_to_response(item) for item in result.items],
            "diagnostics": result.diagnostics,
        }
    }


@router.post("/{fact_id}/relations", status_code=status.HTTP_201_CREATED)
async def link_fact_relation(
    fact_id: str,
    request: LinkFactRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.link_facts.execute(
        LinkFactsCommand(
            source_fact_id=fact_id,
            target_fact_id=request.target_fact_id,
            relation_type=request.relation_type,
            reason=request.reason,
            observed_at=request.observed_at,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
        )
    )
    return {"data": fact_relation_to_response(result.relation)}


@router.get("/{fact_id}/relations")
async def list_fact_relations(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _validate_relation_status(status_filter)
    result = await container.list_fact_relations.execute(
        ListFactRelationsQuery(fact_id=fact_id, status=status_filter, limit=limit)
    )
    return {
        "data": {
            "target": fact_to_response(result.target),
            "items": [fact_relation_item_to_response(item) for item in result.items],
        }
    }


@router.delete("/relations/{relation_id}")
async def unlink_fact_relation(
    relation_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.unlink_fact_relation.execute(
        UnlinkFactRelationCommand(relation_id=relation_id)
    )
    return {"data": fact_relation_to_response(result.relation)}


@router.patch("/{fact_id}")
async def update_fact(
    fact_id: str,
    request: UpdateFactRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.update_fact.execute(
        UpdateFactCommand(
            fact_id=fact_id,
            expected_version=request.expected_version,
            text=request.text,
            reason=request.reason,
            source_refs=tuple(map_source_ref(ref) for ref in request.source_refs),
        )
    )
    return {"data": fact_to_response(result.fact, result.indexing_status)}


@router.delete("/{fact_id}")
async def forget_fact(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.forget_fact.execute(ForgetFactCommand(fact_id=fact_id))
    return {"data": fact_to_response(result.fact, result.indexing_status)}


def _validate_fact_status(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        FactStatus(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact status") from exc


def _validate_relation_status(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        LifecycleStatus(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact relation status") from exc
