"""Fact lifecycle API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from infinity_context_core.application import (
    FactVersionsQuery,
    GetFactQuery,
    ListFactRelationsQuery,
    ListFactsQuery,
    RelatedFactsQuery,
)
from infinity_context_core.domain.errors import MemoryValidationError

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
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


RememberFactRequest = memory_facts_feature.RememberFactRequest
UpdateFactRequest = memory_facts_feature.UpdateFactRequest
LinkFactRequest = memory_facts_feature.LinkFactRequest


def fact_to_response(fact: object, indexing_status: str | None = None) -> dict[str, Any]:
    return memory_facts_feature.fact_to_response(fact, indexing_status)


related_fact_to_response = memory_facts_feature.related_fact_to_response
fact_relation_to_response = memory_facts_feature.fact_relation_to_response
fact_relation_item_to_response = memory_facts_feature.fact_relation_item_to_response
map_memory_kind = memory_facts_feature.memory_kind_from_v1_request


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
    command = memory_facts_feature.remember_fact_command_from_v1_request(
        request,
        resolved_scope=scope,
        idempotency_key=idempotency_key,
    )
    result = await container.remember_fact.execute(command)
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
    command = memory_facts_feature.link_fact_relation_command_from_v1_request(
        fact_id,
        request,
    )
    result = await container.link_facts.execute(command)
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
    command = memory_facts_feature.unlink_fact_relation_command_from_v1_path(relation_id)
    result = await container.unlink_fact_relation.execute(command)
    return {"data": fact_relation_to_response(result.relation)}


@router.patch("/{fact_id}")
async def update_fact(
    fact_id: str,
    request: UpdateFactRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    command = memory_facts_feature.update_fact_command_from_v1_request(
        fact_id=fact_id,
        request=request,
    )
    result = await container.update_fact.execute(command)
    return {"data": fact_to_response(result.fact, result.indexing_status)}


@router.delete("/{fact_id}")
async def forget_fact(
    fact_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    command = memory_facts_feature.forget_fact_command_from_v1_path(fact_id)
    result = await container.forget_fact.execute(command)
    return {"data": fact_to_response(result.fact, result.indexing_status)}


def _validate_fact_status(status_filter: str | None) -> None:
    try:
        memory_facts_feature.validate_fact_status_filter(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact status") from exc


def _validate_relation_status(status_filter: str | None) -> None:
    try:
        memory_facts_feature.validate_fact_relation_status_filter(status_filter)
    except ValueError as exc:
        raise MemoryValidationError("Unknown fact relation status") from exc
