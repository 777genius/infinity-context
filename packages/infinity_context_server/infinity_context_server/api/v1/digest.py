"""Memory digest API."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
)

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import should_retrieve
from infinity_context_server.api.public_payload import safe_public_metadata, safe_public_text
from infinity_context_server.api.v1.scope_resolution import resolve_existing_context_scope
from infinity_context_server.composition import Container
from infinity_context_server.features.context_building import public as context_building_server

router = APIRouter(tags=["digest"], dependencies=[Depends(require_service_token)])

DigestRequest = context_building_server.DigestRequest

_LEGACY_DIGEST_API_RESPONSES = context_building_server.LegacyDigestApiResponseMapper(
    normalize_context_diagnostics=normalize_context_diagnostics,
    safe_public_metadata=safe_public_metadata,
    safe_public_text=safe_public_text,
)
digest_to_response = _LEGACY_DIGEST_API_RESPONSES.digest_to_response


@router.post("/digest")
async def build_digest(
    request: context_building_server.DigestRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    started = perf_counter()
    request_id = container.ids.new_id("req")
    if not should_retrieve(container):
        response = _LEGACY_DIGEST_API_RESPONSES.empty_digest_response(
            topic=request.topic,
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_digest",
        )
        return response

    scope = await resolve_existing_context_scope(
        container,
        space_id=request.space_id,
        memory_scope_ids=request.memory_scope_ids,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        memory_scope_external_refs=request.memory_scope_external_refs,
        thread_external_ref=request.thread_external_ref,
    )
    if scope is None:
        response = _LEGACY_DIGEST_API_RESPONSES.empty_digest_response(
            topic=request.topic,
            policy_mode=container.settings.policy_mode.value,
            request_id=request_id,
            scope_not_found=True,
        )
        container.runtime_metrics.record_context(
            latency_ms=_elapsed_ms(started),
            diagnostics=response["data"]["diagnostics"],
            request_id=request_id,
            use_case="build_digest",
        )
        return response

    digest = await container.build_memory_digest.execute(
        context_building_server.build_legacy_digest_query_from_request(
            request,
            scope=scope,
            max_rendered_chars=container.settings.max_context_chars,
        )
    )
    response = {
        "meta": {"request_id": request_id},
        "data": _LEGACY_DIGEST_API_RESPONSES.digest_to_response(digest),
    }
    container.runtime_metrics.record_context(
        latency_ms=_elapsed_ms(started),
        diagnostics=digest.diagnostics,
        request_id=request_id,
        use_case="build_digest",
        scope={
            "space_id": str(scope.space_id),
            "memory_scope_ids": [
                str(memory_scope_id) for memory_scope_id in scope.memory_scope_ids
            ],
            "thread_id": str(scope.thread_id) if scope.thread_id else None,
        },
    )
    return response


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)
