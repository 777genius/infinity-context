"""Shared domain identifiers, enums and constants."""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

SpaceId = NewType("SpaceId", str)

UserId = NewType("UserId", str)

SpaceMembershipId = NewType("SpaceMembershipId", str)

MemoryScopeId = NewType("MemoryScopeId", str)

ThreadId = NewType("ThreadId", str)

MemoryFactId = NewType("MemoryFactId", str)

MemoryFactRelationId = NewType("MemoryFactRelationId", str)

MemoryEpisodeId = NewType("MemoryEpisodeId", str)

MemoryDocumentId = NewType("MemoryDocumentId", str)

MemoryChunkId = NewType("MemoryChunkId", str)

MemorySuggestionId = NewType("MemorySuggestionId", str)

MemoryAnchorId = NewType("MemoryAnchorId", str)

MAX_SOURCE_REFS_PER_ITEM = 20

MAX_SUGGESTION_REVIEW_EVENTS = 20

MAX_SUGGESTION_REVIEW_REASON_CHARS = 320

_AUDIT_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "authorization:",
    "bearer ",
    "password",
    "private_key",
    "secret",
    "sk-",
    "token",
)

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

class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"

class SpaceMembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

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

class MemoryAnchorKind(StrEnum):
    PERSON = "person"
    EVENT = "event"
    PROJECT = "project"
    ORGANIZATION = "organization"

class SpeakerRole(StrEnum):
    USER = "user"
    INTERVIEWER = "interviewer"
    ASSISTANT = "assistant"
    UNKNOWN = "unknown"
