"""Ingest transcript/interview episodes as canonical evidence chunks."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from memo_stack_core.application.auto_memory import (
    MemoryAdmissionService,
    NoopMemoryClassifier,
)
from memo_stack_core.application.chunker import chunk_text
from memo_stack_core.application.dto import IngestEpisodeCommand, IngestEpisodeResult
from memo_stack_core.application.normalize import (
    estimate_tokens,
    normalize_text,
    scoped_idempotency_key,
    scoped_source_hash,
)
from memo_stack_core.domain.entities import (
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryEpisode,
    MemoryEpisodeId,
    MemorySuggestion,
    MemorySuggestionId,
    TrustLevel,
)
from memo_stack_core.domain.errors import MemoryConflictError, MemoryInvariantError
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.domain.idempotency import IdempotencyRecord
from memo_stack_core.ports.auto_memory import MemoryClassifierPort, SourceProvenance
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


def episode_fingerprint(command: IngestEpisodeCommand) -> str:
    raw = (
        f"{command.space_id}:{command.profile_id}:{command.thread_id}:"
        f"{command.source_type}:{command.source_external_id}:{command.text}:"
        f"{command.kind_hint}:{command.language}"
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def durability_for_episode(command: IngestEpisodeCommand) -> str:
    metadata = command.metadata or {}
    if command.source_type == "ai_response" or metadata.get("final_answer") is True:
        return "ignore"
    if (
        command.source_type == "microphone"
        and metadata.get("explicit_interview_context") is not True
    ):
        return "request_scoped_only"
    if (
        command.source_type == "browser_selection"
        and metadata.get("attached_to_prompt") is not True
    ):
        return "request_scoped_only"
    return "durable"


class IngestEpisodeUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
        classifier: MemoryClassifierPort | None = None,
        admission: MemoryAdmissionService | None = None,
        auto_suggestions_enabled: bool = False,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._classifier = classifier or NoopMemoryClassifier()
        self._admission = admission or MemoryAdmissionService()
        self._auto_suggestions_enabled = auto_suggestions_enabled

    async def execute(self, command: IngestEpisodeCommand) -> IngestEpisodeResult:
        durability = durability_for_episode(command)
        if durability != "durable":
            return IngestEpisodeResult(
                episode=None,
                stored_chunks=0,
                duplicate_chunks=0,
                durability=durability,
            )

        fingerprint = episode_fingerprint(command)
        raw_key = command.idempotency_key or command.source_external_id
        key = scoped_idempotency_key(
            "ingest_episode",
            command.profile_id,
            command.thread_id,
            raw_key,
        )
        async with self._uow_factory() as uow:
            existing = await uow.idempotency.find(space_id=str(command.space_id), key=key)
            if existing:
                if existing.fingerprint != fingerprint:
                    raise MemoryConflictError("Idempotency key was used with different episode")
                return IngestEpisodeResult(
                    episode=None,
                    stored_chunks=0,
                    duplicate_chunks=1,
                    durability=durability,
                )

            now = self._clock.now()
            occurred_at = _safe_occurred_at(command.occurred_at, now)
            episode = MemoryEpisode.create(
                episode_id=MemoryEpisodeId(self._ids.new_id("episode")),
                space_id=command.space_id,
                profile_id=command.profile_id,
                thread_id=command.thread_id,
                source_type=command.source_type,
                source_external_id=command.source_external_id,
                text=command.text,
                speaker=command.speaker,
                trust_level=_trust_for_source(command.source_type, command.trust_level),
                occurred_at=occurred_at,
                now=now,
                metadata=command.metadata,
            )
            saved_episode = await uow.episodes.create(episode)

            stored = 0
            duplicates = 0
            source_chunk_id: str | None = None
            for piece in chunk_text(command.text):
                kind = command.kind_hint or _kind_for_source(command.source_type)
                chunk = MemoryChunk.create(
                    chunk_id=MemoryChunkId(self._ids.new_id("chunk")),
                    space_id=command.space_id,
                    profile_id=command.profile_id,
                    thread_id=command.thread_id,
                    episode_id=saved_episode.id,
                    document_id=None,
                    source_type=command.source_type,
                    source_external_id=command.source_external_id,
                    source_hash=scoped_source_hash(
                        command.space_id,
                        command.profile_id,
                        command.thread_id,
                        command.source_external_id,
                        piece.sequence,
                        normalize_text(piece.text),
                    ),
                    kind=kind,
                    text=piece.text,
                    normalized_text=normalize_text(piece.text),
                    sequence=piece.sequence,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    token_estimate=estimate_tokens(piece.text),
                    now=now,
                    metadata={"language": command.language or "", "source": command.source_type},
                )
                result = await uow.chunks.upsert(chunk)
                if result.duplicate:
                    duplicates += 1
                else:
                    stored += 1
                    source_chunk_id = source_chunk_id or result.chunk_id
                    await uow.outbox.enqueue(
                        OutboxEvent(
                            event_type="vector.upsert_chunk",
                            aggregate_type="chunk",
                            aggregate_id=result.chunk_id,
                            payload={"chunk_id": result.chunk_id},
                        )
                    )

            suggestion_ids: list[str] = []
            if self._auto_suggestions_enabled and source_chunk_id is not None:
                provenance = SourceProvenance(
                    source_type=command.source_type,
                    source_id=str(saved_episode.id),
                    trust_level=_trust_for_source(command.source_type, command.trust_level),
                    chunk_id=source_chunk_id,
                )
                candidates = await self._classifier.classify(
                    text=command.text,
                    source=provenance,
                )
                for candidate in candidates:
                    decision = self._admission.decide(
                        source=provenance,
                        candidate=candidate,
                        allow_auto_promote=False,
                    )
                    if decision.outcome != "create_suggestion":
                        continue
                    suggestion = MemorySuggestion.create(
                        suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
                        space_id=command.space_id,
                        profile_id=command.profile_id,
                        candidate_text=candidate.text,
                        kind=candidate.kind,
                        source_refs=candidate.source_refs,
                        safe_reason=decision.reason,
                        confidence=decision.confidence,
                        trust_level=decision.trust_level,
                        now=now,
                    )
                    saved = await uow.suggestions.create(suggestion)
                    suggestion_ids.append(str(saved.id))

            await uow.idempotency.save(
                IdempotencyRecord(
                    space_id=str(command.space_id),
                    key=key,
                    fingerprint=fingerprint,
                    result_type="episode",
                    result_id=str(saved_episode.id),
                )
            )
            await uow.commit()

        if stored == 0 and duplicates == 0:
            raise MemoryInvariantError("Durable episode produced no chunks")
        return IngestEpisodeResult(
            episode=saved_episode,
            stored_chunks=stored,
            duplicate_chunks=duplicates,
            durability=durability,
            created_suggestions=len(suggestion_ids),
            suggestion_ids=tuple(suggestion_ids),
        )


def _trust_for_source(source_type: str, default: TrustLevel) -> TrustLevel:
    if source_type == "ai_response":
        return TrustLevel.LOW
    if source_type in {"manual", "manual_prompt", "focus_copy"}:
        return TrustLevel.HIGH
    return default


def _safe_occurred_at(value: object | None, now: datetime) -> datetime:
    if not isinstance(value, datetime):
        return now
    if _as_utc(value) > _as_utc(now):
        return now
    return value


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _kind_for_source(source_type: str) -> MemoryChunkKind:
    return {
        "manual_prompt": MemoryChunkKind.USER_PROMPT,
        "focus_copy": MemoryChunkKind.CURRENT_CODE,
        "ai_response": MemoryChunkKind.AI_RESPONSE,
    }.get(source_type, MemoryChunkKind.RAW_TRANSCRIPT_CHUNK)
