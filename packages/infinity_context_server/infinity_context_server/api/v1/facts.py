"""Fact lifecycle API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from infinity_context_core.application import (
    FactVersionsQuery,
    ForgetFactCommand,
    GetFactQuery,
    LinkFactsCommand,
    ListFactRelationsQuery,
    ListFactsQuery,
    RelatedFactsQuery,
    RememberFactCommand,
    UnlinkFactRelationCommand,
    UpdateFactCommand,
)
from infinity_context_core.domain.entities import (
    FactStatus,
    MemoryFact,
    MemoryKind,
)
from infinity_context_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.api.v1.source_refs import (
    SourceRefRequest,
    map_source_ref,
)
from infinity_context_server.composition import Container
from infinity_context_server.features.memory_facts import public as memory_facts_feature
from infinity_context_server.pagination import (
    cursor_datetime,
    cursor_str,
    decode_cursor,
    encode_cursor,
)

router = APIRouter(
    prefix="/facts",
    tags=["facts"],
    dependencies=[Depends(require_service_token)],
)


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
    relation_type: str = Field(default="related_to", max_length=80)
    reason: str = Field(min_length=1, max_length=320)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def map_memory_kind(value: str) -> MemoryKind:
    try:
        return MemoryKind(value)
    except ValueError as exc:
        raise MemoryValidationError(f"Unknown memory kind: {value}") from exc


def fact_to_response(fact: MemoryFact, indexing_status: str | None = None) -> dict[str, Any]:
    return memory_facts_feature.fact_to_response(fact, indexing_status)


related_fact_to_response = memory_facts_feature.related_fact_to_response
fact_relation_to_response = memory_facts_feature.fact_relation_to_response
fact_relation_item_to_response = memory_facts_feature.fact_relation_item_to_response


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
    feature_command = memory_facts_feature.remember_fact_request_to_command(
        request,
        scope=memory_facts_feature.memory_fact_scope_from_ids(
            space_id=str(scope.space_id),
            memory_scope_id=str(scope.memory_scope_id),
            thread_id=str(scope.thread_id) if scope.thread_id else None,
        ),
        idempotency_key=idempotency_key,
    )
    result = await container.remember_fact.execute(
        RememberFactCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            text=feature_command.text,
            kind=map_memory_kind(feature_command.kind),
            source_refs=tuple(
                map_source_ref(source_ref) for source_ref in feature_command.source_refs
            ),
            classification=request.classification,
            category=request.category,
            tags=tuple(request.tags),
            ttl_policy=request.ttl_policy,
            idempotency_key=feature_command.idempotency_key,
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
    current = await container.get_fact.execute(GetFactQuery(fact_id=fact_id))
    feature_command = memory_facts_feature.update_fact_request_to_command(
        request,
        scope=memory_facts_feature.memory_fact_scope_from_ids(
            space_id=str(current.fact.space_id),
            memory_scope_id=str(current.fact.memory_scope_id),
            thread_id=str(current.fact.thread_id) if current.fact.thread_id else None,
        ),
        fact_id=fact_id,
    )
    result = await container.update_fact.execute(
        UpdateFactCommand(
            fact_id=feature_command.identity.fact_id,
            expected_version=feature_command.expected_version,
            text=feature_command.text,
            reason=feature_command.reason or "",
            source_refs=tuple(
                map_source_ref(source_ref) for source_ref in feature_command.source_refs
            ),
        )
    )
    return {"data": fact_to_response(result.fact, result.indexing_status)}


@router.delete("/{fact_id}")
async def forget_fact(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    current = await container.get_fact.execute(GetFactQuery(fact_id=fact_id))
    feature_command = memory_facts_feature.forget_fact_request_to_command(
        scope=memory_facts_feature.memory_fact_scope_from_ids(
            space_id=str(current.fact.space_id),
            memory_scope_id=str(current.fact.memory_scope_id),
            thread_id=str(current.fact.thread_id) if current.fact.thread_id else None,
        ),
        fact_id=fact_id,
    )
    result = await container.forget_fact.execute(
        ForgetFactCommand(fact_id=feature_command.identity.fact_id)
    )
    return {"data": fact_to_response(result.fact, result.indexing_status)}


def _validate_fact_status(status_filter: str | None) -> None:
    if status_filter is None:
        return
    try:
        FactStatus(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact status") from exc


def _validate_relation_status(status_filter: str | None) -> None:
    try:
        memory_facts_feature.validate_fact_relation_status_filter(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact relation status") from exc
