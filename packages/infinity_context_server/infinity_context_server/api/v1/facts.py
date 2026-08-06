"""Fact lifecycle API."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

import infinity_context_core.features.memory_facts.public as canonical_memory_facts
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from infinity_context_core.application import (
    ListFactRelationsQuery,
    RelatedFactsQuery,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryForbiddenError,
    MemoryNotFoundError,
    MemoryValidationError,
)

from infinity_context_server.api.auth import (
    get_authenticated_actor_id,
    get_authorized_agent_context,
    require_service_token,
)
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.auth_tokens import (
    MEMORY_PERMISSION_ADMIN,
    MEMORY_PERMISSION_DELETE,
    MEMORY_PERMISSION_FACT_WRITE,
    MEMORY_PERMISSION_GOVERN,
    MEMORY_PERMISSION_READ,
    MEMORY_PERMISSION_WRITE,
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
    http_request: Request,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
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
    authorized_context = get_authorized_agent_context(http_request)
    authorized = _authorize_lifecycle_scope(
        authorized_context,
        scope=scope,
        required_permission=MEMORY_PERMISSION_FACT_WRITE,
        requested_repository_id=request.repository_id,
        requested_code_scope_id=request.code_scope_id,
    )
    command = memory_facts_feature.remember_fact_request_to_command(
        request,
        scope=memory_facts_feature.memory_fact_scope_from_ids(
            space_id=str(scope.space_id),
            memory_scope_id=str(scope.memory_scope_id),
            thread_id=str(scope.thread_id) if scope.thread_id else None,
        ),
        idempotency_key=idempotency_key,
    )
    if authorized is not None and authorized.repository_id is not None:
        command = replace(
            command,
            code_scope=canonical_memory_facts.FactCodeScopeReference(
                repository_id=authorized.repository_id,
                code_scope_id=authorized.code_scope_id,
            ),
        )
    result = await _execute_fact_command(
        container.memory_fact_lifecycle.remember_fact,
        command,
    )
    if result.replayed:
        response.status_code = status.HTTP_200_OK
    payload = memory_facts_feature.memory_fact_snapshot_to_response(result.fact)
    payload["indexing_status"] = "pending"
    return {"data": payload}


@router.get("")
async def list_facts(
    http_request: Request,
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
    authorized = _authorize_lifecycle_scope(
        get_authorized_agent_context(http_request),
        scope=memory_facts_feature.memory_fact_scope_from_ids(
            space_id=str(scope.space_id),
            memory_scope_id=str(scope.memory_scope_id),
            thread_id=str(scope.thread_id) if scope.thread_id else None,
        ),
        required_permission=MEMORY_PERMISSION_READ,
    )
    facts = list(
        await container.memory_fact_reads.list_facts.execute(
            canonical_memory_facts.MemoryFactListSpec(
                space_id=str(scope.space_id),
                memory_scope_id=str(scope.memory_scope_id),
                thread_id=str(scope.thread_id) if scope.thread_id else None,
                status=status_filter,
                limit=limit + 1,
                cursor_updated_at=cursor_datetime(decoded_cursor, "updated_at"),
                cursor_id=cursor_str(decoded_cursor, "id"),
                category=category,
                tag=tag,
                context_visible_at=(
                    container.clock.now() if status_filter == "active" else None
                ),
                repository_id=authorized.repository_id if authorized is not None else None,
                code_scope_id=authorized.code_scope_id if authorized is not None else None,
                restrict_to_repository_visibility=authorized is not None,
            )
        )
    )
    visible_facts = facts[:limit]
    next_cursor = None
    if len(facts) > limit and visible_facts:
        last = visible_facts[-1]
        next_cursor = encode_cursor(
            "facts",
            updated_at=last.updated_at.isoformat(),
            id=last.identity.fact_id,
        )
    return {
        "data": [
            memory_facts_feature.memory_fact_snapshot_to_response(fact) for fact in visible_facts
        ],
        "next_cursor": next_cursor,
    }


@router.get("/{fact_id}")
async def get_fact(
    fact_id: str,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    fact = await _execute_fact_command(container.memory_fact_reads.get_fact, fact_id)
    _authorize_fact_read(http_request, fact)
    return {"data": memory_facts_feature.memory_fact_snapshot_to_response(fact)}


@router.get("/{fact_id}/versions")
async def list_fact_versions(
    fact_id: str,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    versions = await _execute_fact_command(container.memory_fact_reads.list_versions, fact_id)
    _authorize_fact_read(http_request, versions[-1])
    return {
        "data": [
            memory_facts_feature.memory_fact_snapshot_to_response(version) for version in versions
        ]
    }


@router.get("/{fact_id}/related")
async def related_facts(
    fact_id: str,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    include_other_threads: bool = False,
) -> dict[str, Any]:
    context = get_authorized_agent_context(http_request)
    result = await container.related_facts.execute(
        RelatedFactsQuery(
            fact_id=fact_id,
            limit=limit,
            include_other_threads=include_other_threads,
            enforce_code_scope=True,
            repository_id=context.repository_id if context is not None else None,
            code_scope_id=context.code_scope_id if context is not None else None,
        )
    )
    related_ids = tuple(str(item.fact.id) for item in result.items)
    snapshots = await container.memory_fact_reads.get_fact.get_many((fact_id, *related_ids))
    by_id = {snapshot.identity.fact_id: snapshot for snapshot in snapshots}
    target = by_id.get(fact_id)
    if target is None:
        raise MemoryNotFoundError(f"Memory fact not found: {fact_id}")
    _authorize_fact_read(http_request, target)
    items = []
    for item in result.items:
        snapshot = by_id.get(str(item.fact.id))
        if snapshot is None or not _fact_visible_to_context(snapshot, context):
            continue
        body = memory_facts_feature.memory_fact_snapshot_to_response(snapshot)
        body["score"] = item.score
        body["relation_reasons"] = list(item.relation_reasons)
        items.append(body)
    return {
        "data": {
            "target": memory_facts_feature.memory_fact_snapshot_to_response(target),
            "items": items,
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
    if request.relation_type in {"supersedes", "contradicts"}:
        raise MemoryValidationError(
            "Temporal relations require the audited supersede or dispute endpoint"
        )
    command = memory_facts_feature.link_fact_relation_command_from_v1_request(
        fact_id,
        request,
    )
    result = await container.link_facts.execute(command)
    return {"data": fact_relation_to_response(result.relation)}


@router.post("/{fact_id}/confirm")
async def confirm_fact(
    fact_id: str,
    request: memory_facts_feature.ConfirmFactHttpRequest,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _resolve_temporal_scope(request, container)
    actor_id, authorized_code_scope = _temporal_actor_and_code_scope(
        request,
        http_request=http_request,
        scope=scope,
    )
    result = await _execute_fact_command(
        container.memory_fact_temporal.confirm_fact,
        memory_facts_feature.confirm_fact_command(
            fact_id,
            request,
            scope=scope,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            authorized_code_scope=authorized_code_scope,
        ),
    )
    return {"data": _single_temporal_result(result)}


@router.post("/{fact_id}/end-validity")
async def end_fact_validity(
    fact_id: str,
    request: memory_facts_feature.EndFactValidityHttpRequest,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _resolve_temporal_scope(request, container)
    actor_id, authorized_code_scope = _temporal_actor_and_code_scope(
        request,
        http_request=http_request,
        scope=scope,
    )
    result = await _execute_fact_command(
        container.memory_fact_temporal.end_validity,
        memory_facts_feature.end_fact_validity_command(
            fact_id,
            request,
            scope=scope,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            authorized_code_scope=authorized_code_scope,
        ),
    )
    return {"data": _single_temporal_result(result)}


@router.post("/{fact_id}/supersede")
async def supersede_fact(
    fact_id: str,
    request: memory_facts_feature.SupersedeFactHttpRequest,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _resolve_temporal_scope(request, container)
    actor_id, authorized_code_scope = _temporal_actor_and_code_scope(
        request,
        http_request=http_request,
        scope=scope,
    )
    result = await _execute_fact_command(
        container.memory_fact_temporal.supersede_fact,
        memory_facts_feature.supersede_fact_command(
            fact_id,
            request,
            scope=scope,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            authorized_code_scope=authorized_code_scope,
        ),
    )
    return {
        "data": {
            "successor": memory_facts_feature.memory_fact_snapshot_to_response(result.successor),
            "predecessor": memory_facts_feature.memory_fact_snapshot_to_response(
                result.predecessor
            ),
            "decision": memory_facts_feature.temporal_decision_to_response(result.decision),
            "relation": memory_facts_feature.supersession_relation_to_response(result.relation),
            "replayed": result.replayed,
        }
    }


@router.post("/{fact_id}/dispute")
async def dispute_fact(
    fact_id: str,
    request: memory_facts_feature.DisputeFactHttpRequest,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _resolve_temporal_scope(request, container)
    actor_id, authorized_code_scope = _temporal_actor_and_code_scope(
        request,
        http_request=http_request,
        scope=scope,
    )
    result = await _execute_fact_command(
        container.memory_fact_temporal.dispute_facts,
        memory_facts_feature.dispute_facts_command(
            fact_id,
            request,
            scope=scope,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            authorized_code_scope=authorized_code_scope,
        ),
    )
    return {
        "data": {
            "challenger": memory_facts_feature.memory_fact_snapshot_to_response(result.challenger),
            "challenged": memory_facts_feature.memory_fact_snapshot_to_response(result.challenged),
            "decision": memory_facts_feature.temporal_decision_to_response(result.decision),
            "replayed": result.replayed,
        }
    }


@router.post("/reinstate-supersession")
async def reinstate_supersession(
    request: memory_facts_feature.ReinstateSupersessionHttpRequest,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _resolve_temporal_scope(request, container)
    actor_id, authorized_code_scope = _temporal_actor_and_code_scope(
        request,
        http_request=http_request,
        scope=scope,
    )
    result = await _execute_fact_command(
        container.memory_fact_temporal.reinstate_supersession,
        memory_facts_feature.reinstate_supersession_command(
            request,
            scope=scope,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            authorized_code_scope=authorized_code_scope,
        ),
    )
    return {
        "data": {
            "reinstated_fact": memory_facts_feature.memory_fact_snapshot_to_response(
                result.reinstated_fact
            ),
            "rejected_successor": memory_facts_feature.memory_fact_snapshot_to_response(
                result.rejected_successor
            ),
            "decision": memory_facts_feature.temporal_decision_to_response(result.decision),
            "relation": memory_facts_feature.supersession_relation_to_response(result.relation),
            "replayed": result.replayed,
        }
    }


@router.get("/{fact_id}/relations")
async def list_fact_relations(
    fact_id: str,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = "active",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    _validate_relation_status(status_filter)
    context = get_authorized_agent_context(http_request)
    result = await container.list_fact_relations.execute(
        ListFactRelationsQuery(
            fact_id=fact_id,
            status=status_filter,
            limit=limit,
            enforce_code_scope=True,
            repository_id=context.repository_id if context is not None else None,
            code_scope_id=context.code_scope_id if context is not None else None,
        )
    )
    related_ids = tuple(str(item.related_fact.id) for item in result.items)
    snapshots = await container.memory_fact_reads.get_fact.get_many((fact_id, *related_ids))
    by_id = {snapshot.identity.fact_id: snapshot for snapshot in snapshots}
    target = by_id.get(fact_id)
    if target is None:
        raise MemoryNotFoundError(f"Memory fact not found: {fact_id}")
    _authorize_fact_read(http_request, target)
    items = []
    for item in result.items:
        snapshot = by_id.get(str(item.related_fact.id))
        if snapshot is None or not _fact_visible_to_context(snapshot, context):
            continue
        items.append(
            {
                "relation": fact_relation_to_response(item.relation),
                "related_fact": memory_facts_feature.memory_fact_snapshot_to_response(snapshot),
                "direction": item.direction,
            }
        )
    return {
        "data": {
            "target": memory_facts_feature.memory_fact_snapshot_to_response(target),
            "items": items,
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
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _scope_for_existing_fact(container, fact_id)
    authorized = _authorize_lifecycle_scope(
        get_authorized_agent_context(http_request),
        scope=scope,
        required_permission=MEMORY_PERMISSION_FACT_WRITE,
    )
    command = memory_facts_feature.update_fact_request_to_command(
        request,
        scope=scope,
        fact_id=fact_id,
        idempotency_key=idempotency_key,
    )
    if authorized is not None and authorized.repository_id is not None:
        command = replace(
            command,
            authorized_code_scope=canonical_memory_facts.FactCodeScopeReference(
                repository_id=authorized.repository_id,
                code_scope_id=authorized.code_scope_id,
            ),
        )
    result = await _execute_fact_command(
        container.memory_fact_lifecycle.update_fact,
        command,
    )
    payload = memory_facts_feature.memory_fact_result_to_response(result)
    payload["indexing_status"] = "pending"
    return {"data": payload}


@router.delete("/{fact_id}")
async def forget_fact(
    fact_id: str,
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    scope = await _scope_for_existing_fact(container, fact_id)
    authorized = _authorize_lifecycle_scope(
        get_authorized_agent_context(http_request),
        scope=scope,
        required_permission=MEMORY_PERMISSION_DELETE,
    )
    command = memory_facts_feature.forget_fact_request_to_command(
        scope=scope,
        fact_id=fact_id,
        idempotency_key=idempotency_key,
    )
    if authorized is not None and authorized.repository_id is not None:
        command = replace(
            command,
            authorized_code_scope=canonical_memory_facts.FactCodeScopeReference(
                repository_id=authorized.repository_id,
                code_scope_id=authorized.code_scope_id,
            ),
        )
    result = await _execute_fact_command(
        container.memory_fact_lifecycle.forget_fact,
        command,
    )
    payload = memory_facts_feature.memory_fact_result_to_response(result)
    payload["indexing_status"] = "already_deleted" if result.already_deleted else "pending"
    return {"data": payload}


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


async def _resolve_temporal_scope(request, container: Container):
    resolved = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=False,
    )
    return memory_facts_feature.memory_fact_scope_from_ids(
        space_id=str(resolved.space_id),
        memory_scope_id=str(resolved.memory_scope_id),
        thread_id=str(resolved.thread_id) if resolved.thread_id else None,
    )


def _temporal_actor_and_code_scope(request, *, http_request: Request, scope):
    context = get_authorized_agent_context(http_request)
    if context is None:
        actor_id = request.actor_id or get_authenticated_actor_id(http_request)
        if actor_id is None:
            raise MemoryValidationError("Temporal decision requires actor_id")
        return actor_id, None
    required_permission = (
        MEMORY_PERMISSION_GOVERN
        if MEMORY_PERMISSION_GOVERN in context.permissions
        else (
            MEMORY_PERMISSION_WRITE
            if context.repository_id is None and MEMORY_PERMISSION_WRITE in context.permissions
            else MEMORY_PERMISSION_ADMIN
        )
    )
    try:
        authorized = context.authorize(
            requested_space_id=scope.space_id,
            requested_memory_scope_ids=(scope.memory_scope_id,),
            required_permission=required_permission,
        )
    except PermissionError as exc:
        raise MemoryForbiddenError(str(exc)) from exc
    code_scope = (
        canonical_memory_facts.FactCodeScopeReference(
            repository_id=authorized.repository_id,
            code_scope_id=authorized.code_scope_id,
        )
        if authorized.repository_id is not None
        else None
    )
    return authorized.actor_id, code_scope


async def _scope_for_existing_fact(
    container: Container,
    fact_id: str,
):
    current = await _execute_fact_command(container.memory_fact_reads.get_fact, fact_id)
    scope = current.identity.scope
    return memory_facts_feature.memory_fact_scope_from_ids(
        space_id=scope.space_id,
        memory_scope_id=scope.memory_scope_id,
        thread_id=scope.thread_id,
    )


def _authorize_fact_read(http_request: Request, fact) -> None:
    code_scope = fact.code_scope
    _authorize_lifecycle_scope(
        get_authorized_agent_context(http_request),
        scope=fact.identity.scope,
        required_permission=MEMORY_PERMISSION_READ,
        requested_repository_id=(code_scope.repository_id if code_scope is not None else None),
        requested_code_scope_id=(code_scope.code_scope_id if code_scope is not None else None),
    )


def _fact_visible_to_context(fact, context) -> bool:
    if context is None or fact.code_scope is None:
        return True
    if context.repository_id != fact.code_scope.repository_id:
        return False
    return (
        fact.code_scope.code_scope_id is None
        or context.code_scope_id == fact.code_scope.code_scope_id
    )


def _authorize_lifecycle_scope(
    context,
    *,
    scope,
    required_permission: str,
    requested_repository_id: str | None = None,
    requested_code_scope_id: str | None = None,
):
    if context is None:
        if requested_repository_id is not None or requested_code_scope_id is not None:
            raise MemoryForbiddenError(
                "Repository-scoped fact writes require an authorized project token"
            )
        return None
    authorized_permission = (
        required_permission
        if required_permission in context.permissions
        else (
            MEMORY_PERMISSION_WRITE
            if context.repository_id is None
            and required_permission == MEMORY_PERMISSION_FACT_WRITE
            and MEMORY_PERMISSION_WRITE in context.permissions
            else MEMORY_PERMISSION_ADMIN
        )
    )
    try:
        return context.authorize(
            requested_space_id=scope.space_id,
            requested_memory_scope_ids=(scope.memory_scope_id,),
            required_permission=authorized_permission,
            requested_repository_id=requested_repository_id,
            requested_code_scope_id=requested_code_scope_id,
        )
    except PermissionError as exc:
        raise MemoryForbiddenError(str(exc)) from exc


def _single_temporal_result(result) -> dict[str, Any]:
    return {
        "fact": memory_facts_feature.memory_fact_snapshot_to_response(result.fact),
        "decision": memory_facts_feature.temporal_decision_to_response(result.decision),
        "replayed": result.replayed,
        "outbox_message_ids": list(result.outbox_message_ids),
    }


async def _execute_fact_command(use_case, command):
    try:
        return await use_case.execute(command)
    except PermissionError as exc:
        raise MemoryForbiddenError(str(exc)) from exc
    except LookupError as exc:
        raise MemoryNotFoundError(str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if _is_fact_conflict(message):
            raise MemoryConflictError(message) from exc
        raise MemoryValidationError(message) from exc


def _is_fact_conflict(message: str) -> bool:
    normalized = message.casefold()
    return any(
        marker in normalized
        for marker in (
            "already used",
            "already deleted",
            "already exists",
            "append-only",
            "conflict",
            "expected version",
            "idempotency key was reused",
            "stale",
            "version conflict",
        )
    )
