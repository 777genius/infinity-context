"""Canonical auto-memory capture API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from memo_stack_core.application import (
    ConsolidateCaptureCommand,
    GetCaptureQuery,
    ListCapturesQuery,
    PurgeCaptureCommand,
    ReceiveCaptureCommand,
)
from memo_stack_core.domain.capture import CanonicalCapture, CaptureStatus, ConsolidationStatus
from memo_stack_core.domain.errors import (
    MemoryIngressLimitError,
    MemoryPolicyBlockedError,
    MemoryValidationError,
)
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import ensure_server_writes_enabled, should_capture
from memo_stack_server.api.v1.facts import SourceRefRequest, map_source_ref
from memo_stack_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from memo_stack_server.composition import Container
from memo_stack_server.config import CaptureMode

router = APIRouter(
    tags=["captures"],
    dependencies=[Depends(require_service_token)],
)


class CreateCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    profile_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    profile_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    source_agent: str = Field(min_length=1, max_length=80)
    source_kind: str = Field(default="hook", max_length=80)
    event_type: str = Field(min_length=1, max_length=120)
    actor_role: str = Field(default="unknown", max_length=40)
    text: str = Field(min_length=1, max_length=100_000)
    source_event_id: str | None = Field(default=None, max_length=240)
    source_actor_external_ref: str | None = Field(default=None, max_length=240)
    client_instance_id: str | None = Field(default=None, max_length=160)
    agent_session_external_ref: str | None = Field(default=None, max_length=240)
    turn_external_ref: str | None = Field(default=None, max_length=240)
    parent_capture_id: str | None = Field(default=None, max_length=80)
    sequence_index: int | None = Field(default=None, ge=0)
    evidence_refs: list[SourceRefRequest] = Field(default_factory=list, max_length=20)
    trust_level: str = Field(default="medium", max_length=40)
    source_authority: str = Field(default="unknown", max_length=80)
    sensitivity: str = Field(default="medium", max_length=40)
    data_classification: str = Field(default="internal", max_length=40)
    occurred_at: datetime | None = None
    metadata: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, max_length=120)
    consolidate: bool | None = None


class ConsolidateCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force: bool = False


class PurgeCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="privacy_purge", min_length=1, max_length=160)


@router.post("/captures", status_code=status.HTTP_201_CREATED)
async def create_capture(
    request: CreateCaptureRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    if (
        container.settings.capture_mode in {CaptureMode.OFF, CaptureMode.RETRIEVE_ONLY}
        or not should_capture(container)
    ):
        raise MemoryPolicyBlockedError("Capture writes are disabled by policy")
    if len(request.text) > container.settings.max_capture_text_chars:
        raise MemoryIngressLimitError("Capture text exceeds configured ingress limit")
    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        profile_id=request.profile_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        profile_external_ref=request.profile_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=False,
    )
    consolidation_allowed = container.settings.capture_mode in {
        CaptureMode.SUGGEST,
        CaptureMode.AUTO_APPLY_SAFE,
    }
    requested_consolidate = (
        request.consolidate
        if request.consolidate is not None
        else container.settings.capture_default_consolidate
    )
    consolidate = bool(requested_consolidate and consolidation_allowed)
    result = await container.receive_capture.execute(
        ReceiveCaptureCommand(
            space_id=scope.space_id,
            profile_id=scope.profile_id,
            thread_id=scope.thread_id,
            source_agent=request.source_agent,
            source_kind=request.source_kind,
            event_type=request.event_type,
            actor_role=request.actor_role,
            text=request.text,
            evidence_refs=tuple(map_source_ref(ref) for ref in request.evidence_refs),
            trust_level=request.trust_level,
            source_authority=request.source_authority,
            sensitivity=request.sensitivity,
            data_classification=request.data_classification,
            occurred_at=request.occurred_at,
            metadata=request.metadata,
            source_event_id=request.source_event_id,
            source_actor_external_ref=request.source_actor_external_ref,
            client_instance_id=request.client_instance_id,
            agent_session_external_ref=request.agent_session_external_ref,
            turn_external_ref=request.turn_external_ref,
            parent_capture_id=request.parent_capture_id,
            sequence_index=request.sequence_index,
            trace_id=request.trace_id,
            idempotency_key=request.idempotency_key,
            consolidate=bool(consolidate),
        )
    )
    return {
        "data": {
            **capture_to_response(result.capture),
            "duplicate": result.duplicate,
            "created_suggestions": result.created_suggestions,
            "suggestion_ids": list(result.suggestion_ids),
            "auto_applied_facts": result.auto_applied_facts,
            "auto_applied_fact_ids": list(result.auto_applied_fact_ids),
        }
    }


@router.get("/captures")
async def list_captures(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    profile_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    profile_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=40)] = None,
    consolidation_status: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> dict[str, Any]:
    _validate_status(status_filter, consolidation_status)
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        profile_id=profile_id,
        thread_id=None,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        thread_external_ref=None,
        thread_required=False,
    )
    if scope is None:
        return {"data": []}
    captures = await container.list_captures.execute(
        ListCapturesQuery(
            space_id=scope.space_id,
            profile_id=scope.profile_id,
            status=status_filter,
            consolidation_status=consolidation_status,
            limit=limit,
        )
    )
    return {"data": [capture_to_response(capture) for capture in captures]}


@router.get("/captures/{capture_id}")
async def get_capture(
    capture_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    capture = await container.get_capture.execute(GetCaptureQuery(capture_id=capture_id))
    if capture is None:
        return {"data": None}
    return {"data": capture_to_response(capture)}


@router.delete("/captures/{capture_id}")
async def purge_capture(
    capture_id: str,
    request: PurgeCaptureRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.purge_capture.execute(
        PurgeCaptureCommand(capture_id=capture_id, reason=request.reason)
    )
    return {"data": capture_to_response(result.capture)}


@router.post("/captures/{capture_id}/consolidate")
async def consolidate_capture(
    capture_id: str,
    request: ConsolidateCaptureRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    if (
        container.settings.capture_mode not in {CaptureMode.SUGGEST, CaptureMode.AUTO_APPLY_SAFE}
        or not should_capture(container)
    ):
        raise MemoryPolicyBlockedError("Capture consolidation is disabled by policy")
    result = await container.consolidate_capture.execute(
        ConsolidateCaptureCommand(capture_id=capture_id, force=request.force)
    )
    return {
        "data": {
            **capture_to_response(result.capture),
            "created_suggestions": result.created_suggestions,
            "suggestion_ids": list(result.suggestion_ids),
            "auto_applied_facts": result.auto_applied_facts,
            "auto_applied_fact_ids": list(result.auto_applied_fact_ids),
        }
    }


@router.get("/diagnostics/captures")
async def capture_diagnostics(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    profile_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    profile_external_ref: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    consolidation_status: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return await list_captures(
        container=container,
        space_id=space_id,
        profile_id=profile_id,
        space_slug=space_slug,
        profile_external_ref=profile_external_ref,
        consolidation_status=consolidation_status,
        limit=limit,
    )


def capture_to_response(capture: CanonicalCapture) -> dict[str, Any]:
    return {
        "id": str(capture.id),
        "space_id": str(capture.space_id),
        "profile_id": str(capture.profile_id),
        "thread_id": str(capture.thread_id) if capture.thread_id else None,
        "source_agent": capture.source_agent,
        "source_kind": capture.source_kind.value,
        "event_type": capture.event_type,
        "actor_role": capture.actor_role.value,
        "text_preview": capture.text[:500],
        "payload_hash": capture.payload_hash,
        "status": capture.status.value,
        "consolidation_status": capture.consolidation_status.value,
        "trust_level": capture.trust_level.value,
        "source_authority": capture.source_authority.value,
        "sensitivity": capture.sensitivity.value,
        "data_classification": capture.data_classification.value,
        "evidence_refs": [
            {
                "source_type": ref.source_type,
                "source_id": ref.source_id,
                "chunk_id": ref.chunk_id,
                "char_start": ref.char_start,
                "char_end": ref.char_end,
                "quote_preview": ref.quote_preview,
            }
            for ref in capture.evidence_refs
        ],
        "metadata": _safe_metadata(capture.metadata),
        "created_at": capture.created_at.isoformat(),
        "updated_at": capture.updated_at.isoformat(),
        "occurred_at": capture.occurred_at.isoformat(),
        "received_at": capture.received_at.isoformat(),
        "trace_id": capture.trace_id,
        "versions": {
            "schema": capture.schema_version,
            "parser": capture.parser_version,
            "redaction": capture.redaction_version,
            "admission": capture.admission_version,
            "normalization": capture.normalization_version,
            "policy": capture.policy_version,
            "extractor": capture.extractor_version,
            "resolver": capture.resolver_version,
        },
        "last_error_code": capture.last_error_code,
    }


def _safe_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        str(key): value
        for key, value in metadata.items()
        if not _looks_sensitive_key(str(key))
        and isinstance(value, (str, int, float, bool, type(None)))
    }


def _looks_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("token", "secret", "key", "password"))


def _validate_status(status_value: str | None, consolidation_value: str | None) -> None:
    if status_value:
        try:
            CaptureStatus(status_value)
        except ValueError as exc:
            raise MemoryValidationError("Unknown capture status") from exc
    if consolidation_value:
        try:
            ConsolidationStatus(consolidation_value)
        except ValueError as exc:
            raise MemoryValidationError("Unknown capture consolidation_status") from exc
