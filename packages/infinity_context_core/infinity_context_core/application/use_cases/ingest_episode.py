"""Ingest transcript/interview episodes as canonical evidence chunks."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

from infinity_context_core.application.auto_memory import (
    MemoryAdmissionService,
    NoopMemoryClassifier,
)
from infinity_context_core.application.chunker import chunk_text
from infinity_context_core.application.dto import IngestEpisodeCommand, IngestEpisodeResult
from infinity_context_core.application.normalize import (
    estimate_tokens,
    normalize_text,
    scoped_idempotency_key,
    scoped_source_hash,
)
from infinity_context_core.domain.entities import (
    LifecycleStatus,
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryEpisode,
    MemoryEpisodeId,
    MemorySuggestion,
    MemorySuggestionId,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryInvariantError
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.ports.auto_memory import MemoryClassifierPort, SourceProvenance
from infinity_context_core.ports.benchmark_runs import is_managed_benchmark_space_id
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import (
    UnitOfWorkFactoryPort,
    UnitOfWorkPort,
)


def episode_fingerprint(command: IngestEpisodeCommand) -> str:
    payload = {
        "fingerprint_version": 1,
        "kind_hint": command.kind_hint.value if command.kind_hint else None,
        "language": command.language or "",
        "memory_scope_id": str(command.memory_scope_id),
        "metadata": command.metadata or {},
        "occurred_at": _canonical_datetime(command.occurred_at),
        "source_external_id": command.source_external_id,
        "source_type": command.source_type,
        "space_id": str(command.space_id),
        "speaker": command.speaker.value,
        "text": command.text,
        "thread_id": str(command.thread_id),
        "trust_level": command.trust_level.value,
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    return sha256(canonical.encode("utf-8")).hexdigest()


def legacy_episode_fingerprint(command: IngestEpisodeCommand) -> str:
    """Reproduce the unversioned digest persisted before canonical fingerprints."""
    raw = (
        f"{command.space_id}:{command.memory_scope_id}:{command.thread_id}:"
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
        try:
            return await self._execute_once(command)
        except MemoryConflictError as exc:
            raw_key = command.idempotency_key or command.source_external_id
            key = scoped_idempotency_key(
                "ingest_episode",
                command.memory_scope_id,
                command.thread_id,
                raw_key,
            )
            return await self._recover_write_conflict(
                command=command,
                key=key,
                fingerprint=episode_fingerprint(command),
                conflict=exc,
            )

    async def _execute_once(self, command: IngestEpisodeCommand) -> IngestEpisodeResult:
        durability = durability_for_episode(command)
        fingerprint = episode_fingerprint(command)
        raw_key = command.idempotency_key or command.source_external_id
        key = scoped_idempotency_key(
            "ingest_episode",
            command.memory_scope_id,
            command.thread_id,
            raw_key,
        )
        async with self._uow_factory() as uow:
            space_id = str(command.space_id)
            if is_managed_benchmark_space_id(space_id):
                raise MemoryConflictError("Managed benchmark episode admission is unsupported")
            existing = await uow.idempotency.find(space_id=str(command.space_id), key=key)
            if existing:
                return await self._replay_result(
                    uow=uow,
                    record=existing,
                    command=command,
                    fingerprint=fingerprint,
                    durability=durability,
                )
            if durability != "durable":
                return IngestEpisodeResult(
                    episode=None,
                    stored_chunks=0,
                    duplicate_chunks=0,
                    durability=durability,
                )

            now = self._clock.now()
            occurred_at = _safe_occurred_at(command.occurred_at, now)
            episode = MemoryEpisode.create(
                episode_id=MemoryEpisodeId(self._ids.new_id("episode")),
                space_id=command.space_id,
                memory_scope_id=command.memory_scope_id,
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
            written_chunk_ids: list[str] = []
            source_chunk_id: str | None = None
            for piece in chunk_text(command.text):
                kind = command.kind_hint or _kind_for_source(command.source_type)
                chunk = MemoryChunk.create(
                    chunk_id=MemoryChunkId(self._ids.new_id("chunk")),
                    space_id=command.space_id,
                    memory_scope_id=command.memory_scope_id,
                    thread_id=command.thread_id,
                    episode_id=saved_episode.id,
                    document_id=None,
                    source_type=command.source_type,
                    source_external_id=command.source_external_id,
                    source_hash=scoped_source_hash(
                        command.space_id,
                        command.memory_scope_id,
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
                written_chunk_ids.append(result.chunk_id)
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

            canonical_chunks = sorted(
                await uow.chunks.list_for_episode(str(saved_episode.id)),
                key=lambda item: (item.sequence, str(item.id)),
            )
            _validate_chunk_projection(command, saved_episode, canonical_chunks)
            canonical_chunk_ids = tuple(str(chunk.id) for chunk in canonical_chunks)
            if canonical_chunk_ids != tuple(written_chunk_ids):
                raise MemoryInvariantError("Episode ingest chunk identities are divergent")

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
                        memory_scope_id=command.memory_scope_id,
                        thread_id=command.thread_id,
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
            chunk_ids=canonical_chunk_ids,
        )

    async def _recover_write_conflict(
        self,
        *,
        command: IngestEpisodeCommand,
        key: str,
        fingerprint: str,
        conflict: MemoryConflictError,
    ) -> IngestEpisodeResult:
        async with self._uow_factory() as recovery_uow:
            existing = await recovery_uow.idempotency.find(
                space_id=str(command.space_id),
                key=key,
            )
            if existing is None:
                raise conflict
            try:
                return await self._replay_result(
                    uow=recovery_uow,
                    record=existing,
                    command=command,
                    fingerprint=fingerprint,
                    durability=durability_for_episode(command),
                )
            except (MemoryConflictError, MemoryInvariantError) as exc:
                raise exc from conflict

    @staticmethod
    async def _replay_result(
        *,
        uow: UnitOfWorkPort,
        record: IdempotencyRecord,
        command: IngestEpisodeCommand,
        fingerprint: str,
        durability: str,
    ) -> IngestEpisodeResult:
        canonical_match = record.fingerprint == fingerprint
        legacy_match = record.fingerprint == legacy_episode_fingerprint(command)
        if not canonical_match and not legacy_match:
            raise MemoryConflictError("Idempotency key was used with different episode")
        if record.result_type != "episode":
            raise MemoryInvariantError("Idempotency result has unexpected type for episode")
        episode = await uow.episodes.get_by_id(record.result_id)
        if episode is None:
            raise MemoryInvariantError("Idempotency result points to missing episode")
        if not _episode_identity_matches_command(episode, command):
            raise MemoryInvariantError("Idempotency result points to unrelated episode")
        if not _episode_semantics_match_command(episode, command):
            if legacy_match:
                raise MemoryConflictError("Legacy idempotency request differs from stored episode")
            raise MemoryInvariantError("Idempotency result episode semantics are corrupted")
        chunks = sorted(
            await uow.chunks.list_for_episode(str(episode.id)),
            key=lambda item: (item.sequence, str(item.id)),
        )
        _validate_chunk_projection(command, episode, chunks)
        return IngestEpisodeResult(
            episode=episode,
            stored_chunks=0,
            duplicate_chunks=len(chunks),
            durability=durability,
            chunk_ids=tuple(str(chunk.id) for chunk in chunks),
        )


def _episode_identity_matches_command(
    episode: MemoryEpisode,
    command: IngestEpisodeCommand,
) -> bool:
    return (
        episode.space_id == command.space_id
        and episode.memory_scope_id == command.memory_scope_id
        and episode.thread_id == command.thread_id
        and episode.source_type == command.source_type.strip()
        and episode.source_external_id == command.source_external_id.strip()
    )


def _episode_semantics_match_command(
    episode: MemoryEpisode,
    command: IngestEpisodeCommand,
) -> bool:
    historically_normalized_occurred_at = _safe_occurred_at(
        command.occurred_at,
        episode.created_at,
    )
    return (
        episode.text == command.text.strip()
        and episode.speaker == command.speaker
        and episode.trust_level == _trust_for_source(command.source_type, command.trust_level)
        and episode.metadata == (command.metadata or {})
        and _as_utc(episode.occurred_at) == _as_utc(historically_normalized_occurred_at)
    )


def _validate_chunk_projection(
    command: IngestEpisodeCommand,
    episode: MemoryEpisode,
    chunks: list[MemoryChunk],
) -> None:
    pieces = chunk_text(command.text)
    if not chunks or len(chunks) != len(pieces):
        raise MemoryInvariantError("Episode chunk projection is incomplete")
    expected_kind = command.kind_hint or _kind_for_source(command.source_type)
    for chunk, piece in zip(chunks, pieces, strict=True):
        if (
            chunk.episode_id != episode.id
            or chunk.document_id is not None
            or chunk.status != LifecycleStatus.ACTIVE
            or chunk.space_id != command.space_id
            or chunk.memory_scope_id != command.memory_scope_id
            or chunk.thread_id != command.thread_id
            or chunk.source_type != command.source_type.strip()
            or chunk.source_external_id != command.source_external_id.strip()
            or chunk.kind != expected_kind
            or chunk.text != piece.text
            or chunk.normalized_text != normalize_text(piece.text)
            or chunk.sequence != piece.sequence
            or chunk.char_start != piece.char_start
            or chunk.char_end != piece.char_end
            or chunk.token_estimate != estimate_tokens(piece.text)
            or chunk.metadata
            != {"language": command.language or "", "source": command.source_type.strip()}
            or chunk.classification != "unknown"
            or chunk.source_hash
            != scoped_source_hash(
                command.space_id,
                command.memory_scope_id,
                command.thread_id,
                command.source_external_id,
                piece.sequence,
                normalize_text(piece.text),
            )
        ):
            raise MemoryInvariantError("Episode chunk projection is divergent")


def _canonical_datetime(value: object | None) -> str | None:
    if not isinstance(value, datetime):
        return None
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


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
