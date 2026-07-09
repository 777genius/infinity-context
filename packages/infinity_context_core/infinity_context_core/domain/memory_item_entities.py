"""Fact, relation, episode, document and chunk domain entities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_core.domain.entity_policies import (
    _classification_value,
    _validate_taxonomy,
    _validate_temporal_range,
)
from infinity_context_core.domain.entity_types import (
    Confidence,
    DataClassification,
    FactRelationType,
    FactStatus,
    LifecycleStatus,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryEpisodeId,
    MemoryFactId,
    MemoryFactRelationId,
    MemoryKind,
    MemoryScopeId,
    SpaceId,
    SpeakerRole,
    ThreadId,
    TrustLevel,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.domain.source_refs import SourceRef, _unique_source_refs


@dataclass(frozen=True)
class MemoryFact:
    id: MemoryFactId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    text: str
    kind: MemoryKind
    source_refs: tuple[SourceRef, ...]
    status: FactStatus
    version: int
    confidence: Confidence
    trust_level: TrustLevel
    thread_id: ThreadId | None
    created_at: datetime
    updated_at: datetime
    classification: str = "internal"
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    expires_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        fact_id: MemoryFactId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        text: str,
        kind: MemoryKind,
        source_refs: tuple[SourceRef, ...],
        now: datetime,
        thread_id: ThreadId | None = None,
        confidence: Confidence = Confidence.MEDIUM,
        trust_level: TrustLevel = TrustLevel.MEDIUM,
        classification: str = "internal",
        category: str | None = None,
        tags: tuple[str, ...] = (),
        ttl_policy: str | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryFact:
        if not text.strip():
            raise MemoryValidationError("Active fact text is required")
        if not source_refs:
            raise MemoryValidationError("Active fact requires source refs")
        _validate_taxonomy(tags=tags, ttl_policy=ttl_policy)
        return cls(
            id=fact_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            text=text.strip(),
            kind=kind,
            source_refs=_unique_source_refs(source_refs),
            status=FactStatus.ACTIVE,
            version=1,
            confidence=confidence,
            trust_level=trust_level,
            classification=_classification_value(classification),
            category=category,
            tags=tuple(tags),
            ttl_policy=ttl_policy,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    def update(
        self,
        *,
        expected_version: int,
        text: str,
        source_refs: tuple[SourceRef, ...],
        reason: str,
        now: datetime,
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        ttl_policy: str | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryFact:
        if self.status == FactStatus.DELETED:
            raise MemoryConflictError("Deleted fact cannot be updated")
        if self.version != expected_version:
            raise MemoryConflictError("Stale fact version")
        if not text.strip():
            raise MemoryValidationError("Active fact text is required")
        if not source_refs:
            raise MemoryValidationError("Active fact requires source refs")
        if not reason.strip():
            raise MemoryValidationError("Fact update requires reason")
        next_tags = self.tags if tags is None else tuple(tags)
        _validate_taxonomy(tags=next_tags, ttl_policy=ttl_policy or self.ttl_policy)
        return replace(
            self,
            text=text.strip(),
            source_refs=_unique_source_refs(source_refs),
            version=self.version + 1,
            category=self.category if category is None else category,
            tags=next_tags,
            ttl_policy=self.ttl_policy if ttl_policy is None else ttl_policy,
            expires_at=self.expires_at if expires_at is None else expires_at,
            updated_at=now,
        )

    def merge_source_refs(
        self,
        *,
        expected_version: int,
        source_refs: tuple[SourceRef, ...],
        reason: str,
        now: datetime,
    ) -> MemoryFact:
        if self.status == FactStatus.DELETED:
            raise MemoryConflictError("Deleted fact cannot be updated")
        if self.version != expected_version:
            raise MemoryConflictError("Stale fact version")
        if not source_refs:
            raise MemoryValidationError("Fact merge requires source refs")
        if not reason.strip():
            raise MemoryValidationError("Fact merge requires reason")
        return replace(
            self,
            source_refs=_unique_source_refs((*self.source_refs, *source_refs)),
            version=self.version + 1,
            updated_at=now,
        )

    def forget(self, *, now: datetime) -> MemoryFact:
        if self.status == FactStatus.DELETED:
            return self
        return replace(self, status=FactStatus.DELETED, version=self.version + 1, updated_at=now)

    def mark_disputed(self, *, now: datetime) -> MemoryFact:
        if self.status == FactStatus.DELETED:
            raise MemoryConflictError("Deleted fact cannot be disputed")
        if self.status == FactStatus.DISPUTED:
            return self
        if self.status == FactStatus.SUPERSEDED:
            return self
        return replace(self, status=FactStatus.DISPUTED, version=self.version + 1, updated_at=now)

@dataclass(frozen=True)
class MemoryFactRelation:
    id: MemoryFactRelationId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    source_fact_id: MemoryFactId
    target_fact_id: MemoryFactId
    relation_type: FactRelationType
    reason: str
    status: LifecycleStatus
    observed_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        relation_id: MemoryFactRelationId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        source_fact_id: MemoryFactId,
        target_fact_id: MemoryFactId,
        relation_type: FactRelationType,
        reason: str,
        now: datetime,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> MemoryFactRelation:
        if source_fact_id == target_fact_id:
            raise MemoryValidationError("Fact relation requires two distinct facts")
        if not reason.strip():
            raise MemoryValidationError("Fact relation reason is required")
        _validate_temporal_range(valid_from=valid_from, valid_to=valid_to)
        return cls(
            id=relation_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            reason=reason.strip(),
            status=LifecycleStatus.ACTIVE,
            observed_at=observed_at or now,
            valid_from=valid_from,
            valid_to=valid_to,
            created_at=now,
            updated_at=now,
        )

    def delete(self, *, now: datetime) -> MemoryFactRelation:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(self, status=LifecycleStatus.DELETED, updated_at=now)

@dataclass(frozen=True)
class MemoryEpisode:
    id: MemoryEpisodeId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId
    source_type: str
    source_external_id: str
    text: str
    speaker: SpeakerRole
    trust_level: TrustLevel
    status: LifecycleStatus
    occurred_at: datetime
    created_at: datetime
    metadata: dict[str, object]

    @classmethod
    def create(
        cls,
        *,
        episode_id: MemoryEpisodeId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        thread_id: ThreadId,
        source_type: str,
        source_external_id: str,
        text: str,
        speaker: SpeakerRole,
        trust_level: TrustLevel,
        occurred_at: datetime,
        now: datetime,
        metadata: dict[str, object] | None = None,
    ) -> MemoryEpisode:
        if not source_type.strip():
            raise MemoryValidationError("Episode source_type is required")
        if not source_external_id.strip():
            raise MemoryValidationError("Episode source_external_id is required")
        if not text.strip():
            raise MemoryValidationError("Episode text is required")
        return cls(
            id=episode_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            source_type=source_type.strip(),
            source_external_id=source_external_id.strip(),
            text=text.strip(),
            speaker=speaker,
            trust_level=trust_level,
            status=LifecycleStatus.ACTIVE,
            occurred_at=occurred_at,
            created_at=now,
            metadata=dict(metadata or {}),
        )

@dataclass(frozen=True)
class MemoryDocument:
    id: MemoryDocumentId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    title: str
    source_type: str
    source_external_id: str
    content_hash: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime
    classification: str = DataClassification.UNKNOWN.value

    @classmethod
    def create(
        cls,
        *,
        document_id: MemoryDocumentId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        title: str,
        source_type: str,
        source_external_id: str,
        content_hash: str,
        now: datetime,
        thread_id: ThreadId | None = None,
        classification: str = DataClassification.UNKNOWN.value,
    ) -> MemoryDocument:
        if not title.strip():
            raise MemoryValidationError("Document title is required")
        if not source_type.strip():
            raise MemoryValidationError("Document source_type is required")
        if not source_external_id.strip():
            raise MemoryValidationError("Document source_external_id is required")
        if not content_hash.strip():
            raise MemoryValidationError("Document content_hash is required")
        return cls(
            id=document_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            title=title.strip(),
            source_type=source_type.strip(),
            source_external_id=source_external_id.strip(),
            content_hash=content_hash,
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            classification=_classification_value(classification),
        )

@dataclass(frozen=True)
class MemoryChunk:
    id: MemoryChunkId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    document_id: MemoryDocumentId | None
    episode_id: MemoryEpisodeId | None
    source_type: str
    source_external_id: str
    source_hash: str
    kind: MemoryChunkKind
    text: str
    normalized_text: str
    status: LifecycleStatus
    sequence: int
    char_start: int
    char_end: int
    token_estimate: int
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, object]
    classification: str = DataClassification.UNKNOWN.value

    @classmethod
    def create(
        cls,
        *,
        chunk_id: MemoryChunkId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        source_type: str,
        source_external_id: str,
        source_hash: str,
        kind: MemoryChunkKind,
        text: str,
        normalized_text: str,
        sequence: int,
        char_start: int,
        char_end: int,
        token_estimate: int,
        now: datetime,
        thread_id: ThreadId | None = None,
        document_id: MemoryDocumentId | None = None,
        episode_id: MemoryEpisodeId | None = None,
        metadata: dict[str, object] | None = None,
        classification: str = DataClassification.UNKNOWN.value,
    ) -> MemoryChunk:
        if document_id is None and episode_id is None:
            raise MemoryValidationError("Chunk requires document_id or episode_id")
        if document_id is not None and episode_id is not None:
            raise MemoryValidationError("Chunk cannot belong to both document and episode")
        if not text.strip():
            raise MemoryValidationError("Chunk text is required")
        if char_start < 0 or char_end < char_start:
            raise MemoryValidationError("Chunk character range is invalid")
        return cls(
            id=chunk_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            thread_id=thread_id,
            document_id=document_id,
            episode_id=episode_id,
            source_type=source_type.strip(),
            source_external_id=source_external_id.strip(),
            source_hash=source_hash,
            kind=kind,
            text=text.strip(),
            normalized_text=normalized_text,
            status=LifecycleStatus.ACTIVE,
            sequence=sequence,
            char_start=char_start,
            char_end=char_end,
            token_estimate=token_estimate,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
            classification=_classification_value(classification),
        )

    def forget(self, *, now: datetime) -> MemoryChunk:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(self, status=LifecycleStatus.DELETED, updated_at=now)
