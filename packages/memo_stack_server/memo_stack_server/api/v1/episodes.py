"""Episode ingest API for transcript-like memory events."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from memo_stack_core.application import IngestEpisodeCommand
from memo_stack_core.domain.entities import MemoryChunkKind, MemoryEpisode, SpeakerRole, TrustLevel
from memo_stack_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict, Field

from memo_stack_server.api.auth import require_service_token
from memo_stack_server.api.dependencies import get_container
from memo_stack_server.api.policy import should_ingest_legacy_transcript
from memo_stack_server.api.public_payload import safe_public_metadata
from memo_stack_server.api.v1.scope_resolution import resolve_single_scope
from memo_stack_server.composition import Container

router = APIRouter(tags=["episodes"], dependencies=[Depends(require_service_token)])


class IngestEpisodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: str = Field(default="unknown", min_length=1, max_length=80)
    source_external_id: str = Field(min_length=1, max_length=240)
    text: str = Field(min_length=1, max_length=500_000)
    occurred_at: datetime | None = None
    speaker: str | None = Field(default=None, max_length=40)
    trust_level: str = Field(default="medium", max_length=40)
    kind_hint: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, max_length=240)


def episode_to_response(episode: MemoryEpisode) -> dict[str, Any]:
    return {
        "id": str(episode.id),
        "space_id": str(episode.space_id),
        "memory_scope_id": str(episode.memory_scope_id),
        "thread_id": str(episode.thread_id),
        "source_type": episode.source_type,
        "source_external_id": episode.source_external_id,
        "text": episode.text,
        "speaker": episode.speaker.value,
        "trust_level": episode.trust_level.value,
        "status": episode.status.value,
        "occurred_at": episode.occurred_at.isoformat(),
        "created_at": episode.created_at.isoformat(),
        "metadata": safe_public_metadata(episode.metadata),
    }


@router.post("/episodes")
async def ingest_episode(
    request: IngestEpisodeRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    if not should_ingest_legacy_transcript(container):
        return {
            "data": {
                "episode_id": None,
                "durability": "ignore",
                "stored_chunks": 0,
                "duplicate_chunks": 0,
                "created_suggestions": 0,
                "suggestion_ids": [],
            }
        }

    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=True,
    )
    result = await container.ingest_episode.execute(
        IngestEpisodeCommand(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            source_type=request.source_type.strip(),
            source_external_id=request.source_external_id,
            text=request.text,
            occurred_at=request.occurred_at,
            speaker=_speaker(request.speaker),
            trust_level=_trust_level(request.trust_level),
            kind_hint=_kind_hint(request.kind_hint),
            language=request.language,
            metadata=request.metadata,
            idempotency_key=request.idempotency_key,
        )
    )
    return {
        "data": {
            "episode_id": str(result.episode.id) if result.episode else None,
            "durability": result.durability,
            "stored_chunks": result.stored_chunks,
            "duplicate_chunks": result.duplicate_chunks,
            "created_suggestions": result.created_suggestions,
            "suggestion_ids": list(result.suggestion_ids),
        }
    }


def _speaker(value: str | None) -> SpeakerRole:
    if not value:
        return SpeakerRole.UNKNOWN
    try:
        return SpeakerRole(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown speaker") from exc


def _trust_level(value: str) -> TrustLevel:
    try:
        return TrustLevel(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown trust_level") from exc


def _kind_hint(value: str | None) -> MemoryChunkKind | None:
    if not value:
        return None
    try:
        return MemoryChunkKind(value)
    except ValueError as exc:
        raise MemoryValidationError("Unknown kind_hint") from exc
