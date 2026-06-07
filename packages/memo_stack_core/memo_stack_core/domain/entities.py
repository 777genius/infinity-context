"""Core domain entities and value objects.

This module intentionally uses only Python stdlib. Provider SDKs, HTTP frameworks
and persistence models belong outside memo_stack_core.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NewType

from memo_stack_core.domain.errors import MemoryConflictError, MemoryValidationError

SpaceId = NewType("SpaceId", str)
ProfileId = NewType("ProfileId", str)
ThreadId = NewType("ThreadId", str)
MemoryFactId = NewType("MemoryFactId", str)
MemoryFactRelationId = NewType("MemoryFactRelationId", str)
MemoryEpisodeId = NewType("MemoryEpisodeId", str)
MemoryDocumentId = NewType("MemoryDocumentId", str)
MemoryChunkId = NewType("MemoryChunkId", str)
MemorySuggestionId = NewType("MemorySuggestionId", str)


class FactStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    DELETED = "deleted"


class FactRelationType(StrEnum):
    SUPPORTS = "supports"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DUPLICATES = "duplicates"
    REFERENCES = "references"
    DEPENDS_ON = "depends_on"
    RELATED_TO = "related_to"


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SuggestionOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    REVIEW = "review"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TrustLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


class MemoryKind(StrEnum):
    NOTE = "note"
    ARCHITECTURE_DECISION = "architecture_decision"
    CONSTRAINT = "constraint"
    USER_PREFERENCE = "user_preference"


class MemorySourceType(StrEnum):
    MANUAL = "manual"
    DOCUMENT = "document"
    SYSTEM_AUDIO = "system_audio"
    MICROPHONE = "microphone"
    MANUAL_PROMPT = "manual_prompt"
    FOCUS_COPY = "focus_copy"
    BROWSER_SELECTION = "browser_selection"
    AI_RESPONSE = "ai_response"
    UNKNOWN = "unknown"


class MemoryChunkKind(StrEnum):
    RAW_TRANSCRIPT_CHUNK = "raw_transcript_chunk"
    VOICE_QUESTION = "voice_question"
    CONSTRAINT = "constraint"
    CURRENT_CODE = "current_code"
    SELECTED_MESSAGE = "selected_message"
    USER_PROMPT = "user_prompt"
    DOCUMENT_SECTION = "document_section"
    DOCUMENT_CLAIM = "document_claim"
    DOCUMENT_PLAN_ITEM = "document_plan_item"
    DOCUMENT_RISK = "document_risk"
    DOCUMENT_REFERENCE = "document_reference"
    FACT_EVIDENCE = "fact_evidence"
    AI_RESPONSE = "ai_response"


class SpeakerRole(StrEnum):
    USER = "user"
    INTERVIEWER = "interviewer"
    ASSISTANT = "assistant"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MemorySpace:
    id: SpaceId
    slug: str
    name: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        space_id: SpaceId,
        slug: str,
        name: str,
        now: datetime,
    ) -> MemorySpace:
        if not slug.strip():
            raise MemoryValidationError("Space slug is required")
        if not name.strip():
            raise MemoryValidationError("Space name is required")
        return cls(
            id=space_id,
            slug=slug.strip(),
            name=name.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class MemoryProfile:
    id: ProfileId
    space_id: SpaceId
    external_ref: str
    name: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        profile_id: ProfileId,
        space_id: SpaceId,
        external_ref: str,
        name: str,
        now: datetime,
    ) -> MemoryProfile:
        if not external_ref.strip():
            raise MemoryValidationError("Profile external_ref is required")
        if not name.strip():
            raise MemoryValidationError("Profile name is required")
        return cls(
            id=profile_id,
            space_id=space_id,
            external_ref=external_ref.strip(),
            name=name.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None

    def __post_init__(self) -> None:
        if not self.source_type:
            raise MemoryValidationError("SourceRef.source_type is required")
        if not self.source_id:
            raise MemoryValidationError("SourceRef.source_id is required")
        if self.char_start is not None and self.char_start < 0:
            raise MemoryValidationError("SourceRef.char_start must be non-negative")
        if self.char_end is not None and self.char_end < 0:
            raise MemoryValidationError("SourceRef.char_end must be non-negative")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise MemoryValidationError("SourceRef.char_end must be >= char_start")


@dataclass(frozen=True)
class MemoryThread:
    id: ThreadId
    space_id: SpaceId
    profile_id: ProfileId
    external_ref: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        thread_id: ThreadId,
        space_id: SpaceId,
        profile_id: ProfileId,
        external_ref: str,
        now: datetime,
    ) -> MemoryThread:
        if not external_ref.strip():
            raise MemoryValidationError("Thread external_ref is required")
        return cls(
            id=thread_id,
            space_id=space_id,
            profile_id=profile_id,
            external_ref=external_ref.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class MemoryFact:
    id: MemoryFactId
    space_id: SpaceId
    profile_id: ProfileId
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
        profile_id: ProfileId,
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
            profile_id=profile_id,
            thread_id=thread_id,
            text=text.strip(),
            kind=kind,
            source_refs=source_refs,
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
            source_refs=source_refs,
            version=self.version + 1,
            category=self.category if category is None else category,
            tags=next_tags,
            ttl_policy=self.ttl_policy if ttl_policy is None else ttl_policy,
            expires_at=self.expires_at if expires_at is None else expires_at,
            updated_at=now,
        )

    def forget(self, *, now: datetime) -> MemoryFact:
        if self.status == FactStatus.DELETED:
            return self
        return replace(self, status=FactStatus.DELETED, version=self.version + 1, updated_at=now)


@dataclass(frozen=True)
class MemoryFactRelation:
    id: MemoryFactRelationId
    space_id: SpaceId
    profile_id: ProfileId
    source_fact_id: MemoryFactId
    target_fact_id: MemoryFactId
    relation_type: FactRelationType
    reason: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        relation_id: MemoryFactRelationId,
        space_id: SpaceId,
        profile_id: ProfileId,
        source_fact_id: MemoryFactId,
        target_fact_id: MemoryFactId,
        relation_type: FactRelationType,
        reason: str,
        now: datetime,
    ) -> MemoryFactRelation:
        if source_fact_id == target_fact_id:
            raise MemoryValidationError("Fact relation requires two distinct facts")
        if not reason.strip():
            raise MemoryValidationError("Fact relation reason is required")
        return cls(
            id=relation_id,
            space_id=space_id,
            profile_id=profile_id,
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            reason=reason.strip(),
            status=LifecycleStatus.ACTIVE,
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
    profile_id: ProfileId
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
        profile_id: ProfileId,
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
            profile_id=profile_id,
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
    profile_id: ProfileId
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
        profile_id: ProfileId,
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
            profile_id=profile_id,
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
    profile_id: ProfileId
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
        profile_id: ProfileId,
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
            profile_id=profile_id,
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


def _classification_value(value: str) -> str:
    try:
        return DataClassification(value).value
    except ValueError as exc:
        raise MemoryValidationError("Unknown data classification") from exc


def _validate_taxonomy(*, tags: tuple[str, ...], ttl_policy: str | None) -> None:
    if len(tags) > 10:
        raise MemoryValidationError("Fact tags exceed limit")
    if any(len(tag) > 48 for tag in tags):
        raise MemoryValidationError("Fact tag exceeds max length")
    if ttl_policy is not None and len(ttl_policy) > 80:
        raise MemoryValidationError("Fact ttl_policy exceeds max length")


@dataclass(frozen=True)
class MemorySuggestion:
    id: MemorySuggestionId
    space_id: SpaceId
    profile_id: ProfileId
    candidate_text: str
    kind: MemoryKind
    operation: SuggestionOperation
    status: SuggestionStatus
    source_refs: tuple[SourceRef, ...]
    confidence: Confidence
    trust_level: TrustLevel
    safe_reason: str
    target_fact_id: MemoryFactId | None
    target_fact_version: int | None
    created_at: datetime
    updated_at: datetime
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    expires_at: datetime | None = None
    expiry_reason: str | None = None
    created_from_capture_id: str | None = None
    candidate_fingerprint: str | None = None
    review_payload: dict[str, object] | None = None
    reviewed_at: datetime | None = None
    review_reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        suggestion_id: MemorySuggestionId,
        space_id: SpaceId,
        profile_id: ProfileId,
        candidate_text: str,
        kind: MemoryKind,
        source_refs: tuple[SourceRef, ...],
        safe_reason: str,
        now: datetime,
        confidence: Confidence = Confidence.MEDIUM,
        trust_level: TrustLevel = TrustLevel.MEDIUM,
        target_fact_id: MemoryFactId | None = None,
        target_fact_version: int | None = None,
        operation: SuggestionOperation = SuggestionOperation.ADD,
        category: str | None = None,
        tags: tuple[str, ...] = (),
        ttl_policy: str | None = None,
        expires_at: datetime | None = None,
        expiry_reason: str | None = None,
        created_from_capture_id: str | None = None,
        candidate_fingerprint: str | None = None,
        review_payload: dict[str, object] | None = None,
    ) -> MemorySuggestion:
        if not candidate_text.strip():
            raise MemoryValidationError("Suggestion candidate_text is required")
        if not safe_reason.strip():
            raise MemoryValidationError("Suggestion safe_reason is required")
        if len(tags) > 10:
            raise MemoryValidationError("Suggestion tags exceed limit")
        if (
            operation in {SuggestionOperation.UPDATE, SuggestionOperation.DELETE}
            and not target_fact_id
        ):
            raise MemoryValidationError("Update/delete suggestion requires target fact")
        return cls(
            id=suggestion_id,
            space_id=space_id,
            profile_id=profile_id,
            candidate_text=candidate_text.strip(),
            kind=kind,
            operation=operation,
            status=SuggestionStatus.PENDING,
            source_refs=source_refs,
            confidence=confidence,
            trust_level=trust_level,
            safe_reason=safe_reason.strip(),
            target_fact_id=target_fact_id,
            target_fact_version=target_fact_version,
            category=category,
            tags=tuple(tags),
            ttl_policy=ttl_policy,
            expires_at=expires_at,
            expiry_reason=expiry_reason,
            created_from_capture_id=created_from_capture_id,
            candidate_fingerprint=candidate_fingerprint,
            review_payload=dict(review_payload or {}),
            created_at=now,
            updated_at=now,
        )

    def approve(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            raise MemoryConflictError("Only pending suggestion can be approved")
        if not self.source_refs:
            raise MemoryValidationError("Suggestion approval requires source refs")
        return replace(
            self,
            status=SuggestionStatus.APPROVED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
        )

    def reject(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            raise MemoryConflictError("Only pending suggestion can be rejected")
        return replace(
            self,
            status=SuggestionStatus.REJECTED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
        )

    def expire(self, *, now: datetime, reason: str | None = None) -> MemorySuggestion:
        if self.status != SuggestionStatus.PENDING:
            return self
        return replace(
            self,
            status=SuggestionStatus.EXPIRED,
            updated_at=now,
            reviewed_at=now,
            review_reason=reason,
        )
