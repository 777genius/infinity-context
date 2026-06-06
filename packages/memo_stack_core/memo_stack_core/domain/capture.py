"""Canonical auto-memory capture domain.

Captures are immutable evidence envelopes. They are not active memory and they
do not project directly into graph/vector engines.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import NewType

from memo_stack_core.domain.entities import (
    DataClassification,
    ProfileId,
    SourceRef,
    SpaceId,
    ThreadId,
    TrustLevel,
)
from memo_stack_core.domain.errors import MemoryValidationError

MemoryCaptureId = NewType("MemoryCaptureId", str)

MAX_CAPTURE_TEXT_CHARS = 20_000
MAX_CAPTURE_METADATA_KEYS = 80


class CaptureSourceKind(StrEnum):
    HOOK = "hook"
    MCP_TOOL = "mcp_tool"
    TRANSCRIPT_TAIL = "transcript_tail"
    MANUAL = "manual"
    TOOL_RESULT = "tool_result"
    DOCUMENT = "document"
    IMPORT = "import"
    COMPACTION = "compaction"
    SUBAGENT = "subagent"


class CaptureActorRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    SUBAGENT = "subagent"
    UNKNOWN = "unknown"


class CaptureStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REDACTED = "redacted"
    PURGED = "purged"


class ConsolidationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RUNNING = "running"
    CONSOLIDATED = "consolidated"
    RETRY_PENDING = "retry_pending"
    DEAD = "dead"
    SKIPPED = "skipped"


class CaptureSensitivity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SECRET = "secret"


class SourceAuthority(StrEnum):
    EXPLICIT_USER_COMMAND = "explicit_user_command"
    TOOL_VERIFIED = "tool_verified"
    REPO_FILE = "repo_file"
    USER_STATEMENT = "user_statement"
    DOCUMENT = "document"
    TRANSCRIPT_INFERENCE = "transcript_inference"
    ASSISTANT_INFERENCE = "assistant_inference"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CanonicalCapture:
    id: MemoryCaptureId
    space_id: SpaceId
    profile_id: ProfileId
    thread_id: ThreadId | None
    source_agent: str
    source_kind: CaptureSourceKind
    event_type: str
    actor_role: CaptureActorRole
    text: str
    evidence_refs: tuple[SourceRef, ...]
    payload_hash: str
    idempotency_key: str
    status: CaptureStatus
    consolidation_status: ConsolidationStatus
    trust_level: TrustLevel
    source_authority: SourceAuthority
    sensitivity: CaptureSensitivity
    data_classification: DataClassification
    occurred_at: datetime
    received_at: datetime
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, object]
    source_event_id: str | None = None
    source_actor_external_ref: str | None = None
    client_instance_id: str | None = None
    agent_session_external_ref: str | None = None
    turn_external_ref: str | None = None
    parent_capture_id: MemoryCaptureId | None = None
    sequence_index: int | None = None
    trace_id: str | None = None
    schema_version: int = 1
    parser_version: str = "capture-parser-v1"
    redaction_version: str = "redaction-v1"
    admission_version: str = "capture-admission-v1"
    normalization_version: str = "capture-normalization-v1"
    policy_version: str = "capture-policy-v1"
    extractor_version: str | None = None
    extractor_prompt_version: str | None = None
    resolver_version: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None

    @classmethod
    def create(
        cls,
        *,
        capture_id: MemoryCaptureId,
        space_id: SpaceId,
        profile_id: ProfileId,
        thread_id: ThreadId | None,
        source_agent: str,
        source_kind: CaptureSourceKind,
        event_type: str,
        actor_role: CaptureActorRole,
        text: str,
        evidence_refs: tuple[SourceRef, ...],
        payload_hash: str,
        idempotency_key: str,
        trust_level: TrustLevel,
        source_authority: SourceAuthority,
        sensitivity: CaptureSensitivity,
        data_classification: DataClassification,
        occurred_at: datetime,
        now: datetime,
        metadata: Mapping[str, object] | None = None,
        consolidation_status: ConsolidationStatus = ConsolidationStatus.PENDING,
        source_event_id: str | None = None,
        source_actor_external_ref: str | None = None,
        client_instance_id: str | None = None,
        agent_session_external_ref: str | None = None,
        turn_external_ref: str | None = None,
        parent_capture_id: MemoryCaptureId | None = None,
        sequence_index: int | None = None,
        trace_id: str | None = None,
    ) -> CanonicalCapture:
        normalized_text = _bounded_text(text)
        if not source_agent.strip():
            raise MemoryValidationError("Capture source_agent is required")
        if not event_type.strip():
            raise MemoryValidationError("Capture event_type is required")
        if not payload_hash.strip():
            raise MemoryValidationError("Capture payload_hash is required")
        if not idempotency_key.strip():
            raise MemoryValidationError("Capture idempotency_key is required")
        if sequence_index is not None and sequence_index < 0:
            raise MemoryValidationError("Capture sequence_index must be non-negative")
        safe_metadata = dict(metadata or {})
        if len(safe_metadata) > MAX_CAPTURE_METADATA_KEYS:
            raise MemoryValidationError("Capture metadata has too many keys")
        return cls(
            id=capture_id,
            space_id=space_id,
            profile_id=profile_id,
            thread_id=thread_id,
            source_agent=source_agent.strip(),
            source_kind=source_kind,
            event_type=event_type.strip(),
            actor_role=actor_role,
            text=normalized_text,
            evidence_refs=evidence_refs,
            payload_hash=payload_hash.strip(),
            idempotency_key=idempotency_key.strip(),
            status=CaptureStatus.ACCEPTED,
            consolidation_status=consolidation_status,
            trust_level=trust_level,
            source_authority=source_authority,
            sensitivity=sensitivity,
            data_classification=data_classification,
            occurred_at=occurred_at,
            received_at=now,
            created_at=now,
            updated_at=now,
            metadata=safe_metadata,
            source_event_id=_optional_str(source_event_id),
            source_actor_external_ref=_optional_str(source_actor_external_ref),
            client_instance_id=_optional_str(client_instance_id),
            agent_session_external_ref=_optional_str(agent_session_external_ref),
            turn_external_ref=_optional_str(turn_external_ref),
            parent_capture_id=parent_capture_id,
            sequence_index=sequence_index,
            trace_id=_optional_str(trace_id),
        )

    def mark_running(self, *, now: datetime) -> CanonicalCapture:
        if self.consolidation_status not in {
            ConsolidationStatus.PENDING,
            ConsolidationStatus.RETRY_PENDING,
        }:
            return self
        return replace(self, consolidation_status=ConsolidationStatus.RUNNING, updated_at=now)

    def mark_consolidated(
        self,
        *,
        now: datetime,
        extractor_version: str | None,
        extractor_prompt_version: str | None,
        resolver_version: str,
    ) -> CanonicalCapture:
        return replace(
            self,
            consolidation_status=ConsolidationStatus.CONSOLIDATED,
            extractor_version=extractor_version,
            extractor_prompt_version=extractor_prompt_version,
            resolver_version=resolver_version,
            last_error_code=None,
            last_error_message=None,
            updated_at=now,
        )

    def mark_skipped(self, *, now: datetime, reason: str) -> CanonicalCapture:
        return replace(
            self,
            consolidation_status=ConsolidationStatus.SKIPPED,
            last_error_code=reason[:120],
            last_error_message=None,
            updated_at=now,
        )

    def mark_dead(
        self,
        *,
        now: datetime,
        code: str,
        message: str | None = None,
    ) -> CanonicalCapture:
        return replace(
            self,
            consolidation_status=ConsolidationStatus.DEAD,
            last_error_code=code[:120],
            last_error_message=(message or "")[:400] or None,
            updated_at=now,
        )

    def mark_retry_pending(
        self,
        *,
        now: datetime,
        code: str,
        message: str | None = None,
    ) -> CanonicalCapture:
        return replace(
            self,
            consolidation_status=ConsolidationStatus.RETRY_PENDING,
            last_error_code=code[:120],
            last_error_message=(message or "")[:400] or None,
            updated_at=now,
        )

    def mark_purged(self, *, now: datetime, reason: str = "privacy_purge") -> CanonicalCapture:
        return replace(
            self,
            text="[purged]",
            evidence_refs=tuple(_purged_source_ref(ref) for ref in self.evidence_refs),
            status=CaptureStatus.PURGED,
            consolidation_status=ConsolidationStatus.NOT_REQUIRED,
            sensitivity=CaptureSensitivity.SECRET,
            data_classification=DataClassification.RESTRICTED,
            metadata={
                **dict(self.metadata),
                "privacy_purged_at": now.isoformat(),
                "privacy_purge_reason": reason[:160],
            },
            last_error_code=None,
            last_error_message=None,
            updated_at=now,
        )


def _bounded_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise MemoryValidationError("Capture text is required")
    if len(stripped) > MAX_CAPTURE_TEXT_CHARS:
        return stripped[:MAX_CAPTURE_TEXT_CHARS].rstrip()
    return stripped


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _purged_source_ref(ref: SourceRef) -> SourceRef:
    return replace(
        ref,
        char_start=None,
        char_end=None,
        quote_preview="[purged]",
    )
