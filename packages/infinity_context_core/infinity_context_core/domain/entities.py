"""Core domain entities and value objects.

This module intentionally uses only Python stdlib. Provider SDKs, HTTP frameworks
and persistence models belong outside infinity_context_core.
"""

from __future__ import annotations

from infinity_context_core.domain.anchor_entities import MemoryAnchor
from infinity_context_core.domain.entity_types import (
    MAX_SOURCE_REFS_PER_ITEM,
    MAX_SUGGESTION_REVIEW_EVENTS,
    MAX_SUGGESTION_REVIEW_REASON_CHARS,
    Confidence,
    DataClassification,
    FactRelationType,
    FactStatus,
    LifecycleStatus,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocumentId,
    MemoryEpisodeId,
    MemoryFactId,
    MemoryFactRelationId,
    MemoryKind,
    MemoryScopeId,
    MemorySourceType,
    MemorySuggestionId,
    SpaceId,
    SpaceMembershipId,
    SpaceMembershipRole,
    SpeakerRole,
    SuggestionOperation,
    SuggestionStatus,
    ThreadId,
    TrustLevel,
    UserId,
    UserStatus,
)
from infinity_context_core.domain.memory_item_entities import (
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
)
from infinity_context_core.domain.source_refs import SourceRef
from infinity_context_core.domain.suggestion_entities import MemorySuggestion
from infinity_context_core.domain.workspace_entities import (
    MemoryScope,
    MemorySpace,
    MemoryThread,
    SpaceMembership,
    User,
)

__all__ = [
    "SpaceId",
    "UserId",
    "SpaceMembershipId",
    "MemoryScopeId",
    "ThreadId",
    "MemoryFactId",
    "MemoryFactRelationId",
    "MemoryEpisodeId",
    "MemoryDocumentId",
    "MemoryChunkId",
    "MemorySuggestionId",
    "MemoryAnchorId",
    "MAX_SOURCE_REFS_PER_ITEM",
    "MAX_SUGGESTION_REVIEW_EVENTS",
    "MAX_SUGGESTION_REVIEW_REASON_CHARS",
    "FactStatus",
    "FactRelationType",
    "LifecycleStatus",
    "UserStatus",
    "SpaceMembershipRole",
    "SuggestionStatus",
    "SuggestionOperation",
    "Confidence",
    "TrustLevel",
    "DataClassification",
    "MemoryKind",
    "MemorySourceType",
    "MemoryChunkKind",
    "MemoryAnchorKind",
    "SpeakerRole",
    "SourceRef",
    "MemorySpace",
    "User",
    "SpaceMembership",
    "MemoryScope",
    "MemoryThread",
    "MemoryAnchor",
    "MemoryFact",
    "MemoryFactRelation",
    "MemoryEpisode",
    "MemoryDocument",
    "MemoryChunk",
    "MemorySuggestion",
]
