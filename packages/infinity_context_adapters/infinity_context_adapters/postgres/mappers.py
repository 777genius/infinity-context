"""ORM/domain mapping helpers."""

from __future__ import annotations

from dataclasses import asdict

from infinity_context_core.domain.capture import (
    CanonicalCapture,
    CaptureActorRole,
    CaptureSensitivity,
    CaptureSourceKind,
    CaptureStatus,
    ConsolidationStatus,
    MemoryCaptureId,
    SourceAuthority,
)
from infinity_context_core.domain.entities import (
    Confidence,
    DataClassification,
    FactRelationType,
    FactStatus,
    LifecycleStatus,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryChunk,
    MemoryChunkId,
    MemoryChunkKind,
    MemoryDocument,
    MemoryDocumentId,
    MemoryEpisode,
    MemoryEpisodeId,
    MemoryFact,
    MemoryFactId,
    MemoryFactRelation,
    MemoryFactRelationId,
    MemoryKind,
    MemoryScope,
    MemoryScopeId,
    MemorySpace,
    MemorySuggestion,
    MemorySuggestionId,
    MemoryThread,
    SourceRef,
    SpaceId,
    SpaceMembership,
    SpaceMembershipId,
    SpaceMembershipRole,
    SpeakerRole,
    SuggestionOperation,
    SuggestionStatus,
    ThreadId,
    TrustLevel,
    User,
    UserId,
    UserStatus,
)

from infinity_context_adapters.postgres.asset_mappers import (
    apply_asset_extraction_job_to_row,
    apply_asset_to_row,
    apply_context_link_suggestion_to_row,
    apply_context_link_to_row,
    asset_extraction_job_row_to_domain,
    asset_extraction_job_to_row,
    asset_row_to_domain,
    asset_to_row,
    context_link_row_to_domain,
    context_link_suggestion_row_to_domain,
    context_link_suggestion_to_row,
    context_link_to_row,
    extraction_artifact_row_to_domain,
    extraction_artifact_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryScopeRow,
    MemorySourceRefRow,
    MemorySpaceMembershipRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
    MemoryUserRow,
)

__all__ = [
    "anchor_row_to_domain",
    "anchor_to_row",
    "apply_anchor_to_row",
    "apply_asset_extraction_job_to_row",
    "apply_asset_to_row",
    "apply_capture_to_row",
    "apply_context_link_suggestion_to_row",
    "apply_context_link_to_row",
    "apply_fact_to_row",
    "apply_space_membership_to_row",
    "apply_suggestion_to_row",
    "apply_user_to_row",
    "asset_extraction_job_row_to_domain",
    "asset_extraction_job_to_row",
    "asset_row_to_domain",
    "asset_to_row",
    "capture_row_to_domain",
    "capture_to_row",
    "chunk_row_to_domain",
    "chunk_to_row",
    "context_link_row_to_domain",
    "context_link_suggestion_row_to_domain",
    "context_link_suggestion_to_row",
    "context_link_to_row",
    "document_row_to_domain",
    "document_to_row",
    "episode_row_to_domain",
    "episode_to_row",
    "extraction_artifact_row_to_domain",
    "extraction_artifact_to_row",
    "fact_relation_row_to_domain",
    "fact_relation_to_row",
    "fact_row_to_domain",
    "memory_scope_row_to_domain",
    "source_ref_from_json",
    "source_ref_row_to_domain",
    "source_ref_to_json",
    "space_membership_row_to_domain",
    "space_membership_to_row",
    "space_row_to_domain",
    "suggestion_row_to_domain",
    "suggestion_to_row",
    "thread_row_to_domain",
    "user_row_to_domain",
    "user_to_row",
]


def source_ref_to_json(ref: SourceRef) -> dict[str, object]:
    return {key: value for key, value in asdict(ref).items() if value is not None}


def source_ref_row_to_domain(row: MemorySourceRefRow) -> SourceRef:
    return SourceRef(
        source_type=row.source_type,
        source_id=row.source_id,
        chunk_id=row.chunk_id,
        char_start=row.char_start,
        char_end=row.char_end,
        quote_preview=row.quote_preview,
        page_number=getattr(row, "page_number", None),
        time_start_ms=getattr(row, "time_start_ms", None),
        time_end_ms=getattr(row, "time_end_ms", None),
        bbox=_source_ref_bbox(getattr(row, "bbox_json", None)),
    )


def user_to_row(user: User) -> MemoryUserRow:
    return MemoryUserRow(
        id=str(user.id),
        external_ref=user.external_ref,
        display_name=user.display_name,
        email=user.email,
        status=user.status.value,
        metadata_json=dict(user.metadata),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def user_row_to_domain(row: MemoryUserRow) -> User:
    return User(
        id=UserId(row.id),
        external_ref=row.external_ref,
        display_name=row.display_name,
        email=row.email,
        status=UserStatus(row.status),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def apply_user_to_row(user: User, row: MemoryUserRow) -> None:
    row.external_ref = user.external_ref
    row.display_name = user.display_name
    row.email = user.email
    row.status = user.status.value
    row.metadata_json = dict(user.metadata)
    row.created_at = user.created_at
    row.updated_at = user.updated_at


def space_membership_to_row(membership: SpaceMembership) -> MemorySpaceMembershipRow:
    return MemorySpaceMembershipRow(
        id=str(membership.id),
        space_id=str(membership.space_id),
        user_id=str(membership.user_id),
        role=membership.role.value,
        status=membership.status.value,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


def space_membership_row_to_domain(row: MemorySpaceMembershipRow) -> SpaceMembership:
    return SpaceMembership(
        id=SpaceMembershipId(row.id),
        space_id=SpaceId(row.space_id),
        user_id=UserId(row.user_id),
        role=SpaceMembershipRole(row.role),
        status=LifecycleStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def apply_space_membership_to_row(
    membership: SpaceMembership,
    row: MemorySpaceMembershipRow,
) -> None:
    row.space_id = str(membership.space_id)
    row.user_id = str(membership.user_id)
    row.role = membership.role.value
    row.status = membership.status.value
    row.created_at = membership.created_at
    row.updated_at = membership.updated_at


def anchor_to_row(anchor: MemoryAnchor) -> MemoryAnchorRow:
    return MemoryAnchorRow(
        id=str(anchor.id),
        space_id=str(anchor.space_id),
        memory_scope_id=str(anchor.memory_scope_id),
        kind=anchor.kind.value,
        normalized_key=anchor.normalized_key,
        label=anchor.label,
        aliases_json=list(anchor.aliases),
        description=anchor.description,
        status=anchor.status.value,
        confidence=anchor.confidence.value,
        evidence_refs_json=[source_ref_to_json(ref) for ref in anchor.evidence_refs],
        observed_at=anchor.observed_at,
        valid_from=anchor.valid_from, valid_to=anchor.valid_to,
        metadata_json=dict(anchor.metadata),
        created_at=anchor.created_at,
        updated_at=anchor.updated_at,
    )


def apply_anchor_to_row(anchor: MemoryAnchor, row: MemoryAnchorRow) -> None:
    row.space_id = str(anchor.space_id)
    row.memory_scope_id = str(anchor.memory_scope_id)
    row.kind = anchor.kind.value
    row.normalized_key = anchor.normalized_key
    row.label = anchor.label
    row.aliases_json = list(anchor.aliases)
    row.description = anchor.description
    row.status = anchor.status.value
    row.confidence = anchor.confidence.value
    row.evidence_refs_json = [source_ref_to_json(ref) for ref in anchor.evidence_refs]
    row.observed_at = anchor.observed_at
    row.valid_from = anchor.valid_from
    row.valid_to = anchor.valid_to
    row.metadata_json = dict(anchor.metadata)
    row.created_at = anchor.created_at
    row.updated_at = anchor.updated_at


def anchor_row_to_domain(row: MemoryAnchorRow) -> MemoryAnchor:
    return MemoryAnchor(
        id=MemoryAnchorId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        kind=MemoryAnchorKind(row.kind),
        normalized_key=row.normalized_key,
        label=row.label,
        aliases=tuple(row.aliases_json or ()),
        description=row.description,
        status=LifecycleStatus(row.status),
        confidence=Confidence(getattr(row, "confidence", None) or Confidence.MEDIUM.value),
        evidence_refs=tuple(
            source_ref_from_json(ref) for ref in (getattr(row, "evidence_refs_json", None) or ())
        ),
        observed_at=getattr(row, "observed_at", None) or row.created_at,
        valid_from=getattr(row, "valid_from", None),
        valid_to=getattr(row, "valid_to", None),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def fact_row_to_domain(row: MemoryFactRow, source_refs: list[MemorySourceRefRow]) -> MemoryFact:
    return MemoryFact(
        id=MemoryFactId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if getattr(row, "thread_id", None) else None,
        text=row.text,
        kind=MemoryKind(row.kind),
        source_refs=tuple(source_ref_row_to_domain(ref) for ref in source_refs),
        status=FactStatus(getattr(row, "status", None) or FactStatus.ACTIVE.value),
        version=getattr(row, "version", None) or 1,
        confidence=Confidence(getattr(row, "confidence", None) or Confidence.MEDIUM.value),
        trust_level=TrustLevel(getattr(row, "trust_level", None) or TrustLevel.MEDIUM.value),
        classification=getattr(row, "classification", None) or "internal",
        category=getattr(row, "category", None),
        tags=tuple(getattr(row, "tags_json", None) or ()),
        ttl_policy=getattr(row, "ttl_policy", None),
        expires_at=getattr(row, "expires_at", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def fact_relation_to_row(relation: MemoryFactRelation) -> MemoryFactRelationRow:
    return MemoryFactRelationRow(
        id=str(relation.id),
        space_id=str(relation.space_id),
        memory_scope_id=str(relation.memory_scope_id),
        source_fact_id=str(relation.source_fact_id),
        target_fact_id=str(relation.target_fact_id),
        relation_type=relation.relation_type.value,
        reason=relation.reason,
        status=relation.status.value,
        observed_at=relation.observed_at,
        valid_from=relation.valid_from, valid_to=relation.valid_to,
        created_at=relation.created_at,
        updated_at=relation.updated_at,
    )


def fact_relation_row_to_domain(row: MemoryFactRelationRow) -> MemoryFactRelation:
    return MemoryFactRelation(
        id=MemoryFactRelationId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        source_fact_id=MemoryFactId(row.source_fact_id),
        target_fact_id=MemoryFactId(row.target_fact_id),
        relation_type=FactRelationType(row.relation_type),
        reason=row.reason,
        status=LifecycleStatus(row.status),
        observed_at=getattr(row, "observed_at", None) or row.created_at,
        valid_from=getattr(row, "valid_from", None),
        valid_to=getattr(row, "valid_to", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def space_row_to_domain(row: MemorySpaceRow) -> MemorySpace:
    return MemorySpace(
        id=SpaceId(row.id),
        slug=row.slug,
        name=row.name,
        status=LifecycleStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def memory_scope_row_to_domain(row: MemoryScopeRow) -> MemoryScope:
    return MemoryScope(
        id=MemoryScopeId(row.id),
        space_id=SpaceId(row.space_id),
        external_ref=row.external_ref,
        name=row.name,
        status=LifecycleStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def thread_row_to_domain(row: MemoryThreadRow) -> MemoryThread:
    return MemoryThread(
        id=ThreadId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        external_ref=row.external_ref,
        status=LifecycleStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def apply_fact_to_row(fact: MemoryFact, row: MemoryFactRow) -> None:
    row.space_id = str(fact.space_id)
    row.memory_scope_id = str(fact.memory_scope_id)
    row.thread_id = str(fact.thread_id) if fact.thread_id else None
    row.kind = fact.kind.value
    row.text = fact.text
    row.status = fact.status.value
    row.confidence = fact.confidence.value
    row.trust_level = fact.trust_level.value
    row.classification = fact.classification
    row.category = fact.category
    row.tags_json = list(fact.tags)
    row.ttl_policy = fact.ttl_policy
    row.expires_at = fact.expires_at
    row.version = fact.version
    row.created_at = fact.created_at
    row.updated_at = fact.updated_at


def episode_to_row(episode: MemoryEpisode) -> MemoryEpisodeRow:
    return MemoryEpisodeRow(
        id=str(episode.id),
        space_id=str(episode.space_id),
        memory_scope_id=str(episode.memory_scope_id),
        thread_id=str(episode.thread_id),
        source_type=episode.source_type,
        source_external_id=episode.source_external_id,
        text=episode.text,
        speaker=episode.speaker.value,
        trust_level=episode.trust_level.value,
        status=episode.status.value,
        occurred_at=episode.occurred_at,
        created_at=episode.created_at,
        metadata_json=episode.metadata,
    )


def episode_row_to_domain(row: MemoryEpisodeRow) -> MemoryEpisode:
    return MemoryEpisode(
        id=MemoryEpisodeId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id),
        source_type=row.source_type,
        source_external_id=row.source_external_id,
        text=row.text,
        speaker=SpeakerRole(row.speaker),
        trust_level=TrustLevel(row.trust_level),
        status=LifecycleStatus(row.status),
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        metadata=dict(row.metadata_json or {}),
    )


def document_to_row(document: MemoryDocument) -> MemoryDocumentRow:
    return MemoryDocumentRow(
        id=str(document.id),
        space_id=str(document.space_id),
        memory_scope_id=str(document.memory_scope_id),
        thread_id=str(document.thread_id) if document.thread_id else None,
        title=document.title,
        source_type=document.source_type,
        source_external_id=document.source_external_id,
        content_hash=document.content_hash,
        classification=document.classification,
        status=document.status.value,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def document_row_to_domain(row: MemoryDocumentRow) -> MemoryDocument:
    return MemoryDocument(
        id=MemoryDocumentId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if row.thread_id else None,
        title=row.title,
        source_type=row.source_type,
        source_external_id=row.source_external_id,
        content_hash=row.content_hash,
        classification=row.classification,
        status=LifecycleStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def chunk_to_row(chunk: MemoryChunk) -> MemoryChunkRow:
    return MemoryChunkRow(
        id=str(chunk.id),
        space_id=str(chunk.space_id),
        memory_scope_id=str(chunk.memory_scope_id),
        thread_id=str(chunk.thread_id) if chunk.thread_id else None,
        document_id=str(chunk.document_id) if chunk.document_id else None,
        episode_id=str(chunk.episode_id) if chunk.episode_id else None,
        source_type=chunk.source_type,
        source_external_id=chunk.source_external_id,
        source_hash=chunk.source_hash,
        kind=chunk.kind.value,
        text=chunk.text,
        normalized_text=chunk.normalized_text,
        status=chunk.status.value,
        sequence=chunk.sequence,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        token_estimate=chunk.token_estimate,
        classification=chunk.classification,
        created_at=chunk.created_at,
        updated_at=chunk.updated_at,
        metadata_json=chunk.metadata,
    )


def chunk_row_to_domain(row: MemoryChunkRow) -> MemoryChunk:
    return MemoryChunk(
        id=MemoryChunkId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if row.thread_id else None,
        document_id=MemoryDocumentId(row.document_id) if row.document_id else None,
        episode_id=MemoryEpisodeId(row.episode_id) if row.episode_id else None,
        source_type=row.source_type,
        source_external_id=row.source_external_id,
        source_hash=row.source_hash,
        kind=MemoryChunkKind(row.kind),
        text=row.text,
        normalized_text=row.normalized_text,
        status=LifecycleStatus(row.status),
        sequence=row.sequence,
        char_start=row.char_start,
        char_end=row.char_end,
        token_estimate=row.token_estimate,
        classification=row.classification,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
    )


def source_ref_from_json(ref: dict[str, object]) -> SourceRef:
    return SourceRef(
        source_type=str(ref["source_type"]),
        source_id=str(ref["source_id"]),
        chunk_id=str(ref["chunk_id"]) if ref.get("chunk_id") else None,
        char_start=int(ref["char_start"]) if ref.get("char_start") is not None else None,
        char_end=int(ref["char_end"]) if ref.get("char_end") is not None else None,
        quote_preview=str(ref["quote_preview"]) if ref.get("quote_preview") is not None else None,
        page_number=int(ref["page_number"]) if ref.get("page_number") is not None else None,
        time_start_ms=(
            int(ref["time_start_ms"]) if ref.get("time_start_ms") is not None else None
        ),
        time_end_ms=int(ref["time_end_ms"]) if ref.get("time_end_ms") is not None else None,
        bbox=_source_ref_bbox(ref.get("bbox")),
    )


def _source_ref_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    items = tuple(float(item) for item in value)
    return (items[0], items[1], items[2], items[3])


def suggestion_to_row(suggestion: MemorySuggestion) -> MemorySuggestionRow:
    return MemorySuggestionRow(
        id=str(suggestion.id),
        space_id=str(suggestion.space_id),
        memory_scope_id=str(suggestion.memory_scope_id),
        candidate_text=suggestion.candidate_text,
        kind=suggestion.kind.value,
        operation=suggestion.operation.value,
        status=suggestion.status.value,
        source_refs_json=[source_ref_to_json(ref) for ref in suggestion.source_refs],
        confidence=suggestion.confidence.value,
        trust_level=suggestion.trust_level.value,
        safe_reason=suggestion.safe_reason,
        target_fact_id=str(suggestion.target_fact_id) if suggestion.target_fact_id else None,
        target_fact_version=suggestion.target_fact_version,
        category=suggestion.category,
        tags_json=list(suggestion.tags),
        ttl_policy=suggestion.ttl_policy,
        expires_at=suggestion.expires_at,
        expiry_reason=suggestion.expiry_reason,
        created_from_capture_id=suggestion.created_from_capture_id,
        candidate_fingerprint=suggestion.candidate_fingerprint,
        review_payload_json=suggestion.review_payload or {},
        review_reason=suggestion.review_reason,
        created_at=suggestion.created_at,
        updated_at=suggestion.updated_at,
        reviewed_at=suggestion.reviewed_at,
    )


def suggestion_row_to_domain(row: MemorySuggestionRow) -> MemorySuggestion:
    return MemorySuggestion(
        id=MemorySuggestionId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        candidate_text=row.candidate_text,
        kind=MemoryKind(row.kind),
        operation=SuggestionOperation(getattr(row, "operation", None) or "add"),
        status=SuggestionStatus(row.status),
        source_refs=tuple(source_ref_from_json(ref) for ref in row.source_refs_json),
        confidence=Confidence(row.confidence),
        trust_level=TrustLevel(row.trust_level),
        safe_reason=row.safe_reason,
        target_fact_id=MemoryFactId(row.target_fact_id) if row.target_fact_id else None,
        target_fact_version=row.target_fact_version,
        category=getattr(row, "category", None),
        tags=tuple(getattr(row, "tags_json", None) or ()),
        ttl_policy=getattr(row, "ttl_policy", None),
        expires_at=getattr(row, "expires_at", None),
        expiry_reason=getattr(row, "expiry_reason", None),
        created_from_capture_id=getattr(row, "created_from_capture_id", None),
        candidate_fingerprint=getattr(row, "candidate_fingerprint", None),
        review_payload=dict(getattr(row, "review_payload_json", None) or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
        reviewed_at=row.reviewed_at,
        review_reason=row.review_reason,
    )


def apply_suggestion_to_row(suggestion: MemorySuggestion, row: MemorySuggestionRow) -> None:
    row.candidate_text = suggestion.candidate_text
    row.kind = suggestion.kind.value
    row.operation = suggestion.operation.value
    row.status = suggestion.status.value
    row.source_refs_json = [source_ref_to_json(ref) for ref in suggestion.source_refs]
    row.confidence = suggestion.confidence.value
    row.trust_level = suggestion.trust_level.value
    row.safe_reason = suggestion.safe_reason
    row.target_fact_id = str(suggestion.target_fact_id) if suggestion.target_fact_id else None
    row.target_fact_version = suggestion.target_fact_version
    row.category = suggestion.category
    row.tags_json = list(suggestion.tags)
    row.ttl_policy = suggestion.ttl_policy
    row.expires_at = suggestion.expires_at
    row.expiry_reason = suggestion.expiry_reason
    row.created_from_capture_id = suggestion.created_from_capture_id
    row.candidate_fingerprint = suggestion.candidate_fingerprint
    row.review_payload_json = suggestion.review_payload or {}
    row.review_reason = suggestion.review_reason
    row.updated_at = suggestion.updated_at
    row.reviewed_at = suggestion.reviewed_at


def capture_to_row(capture: CanonicalCapture) -> MemoryCaptureRow:
    return MemoryCaptureRow(
        id=str(capture.id),
        space_id=str(capture.space_id),
        memory_scope_id=str(capture.memory_scope_id),
        thread_id=str(capture.thread_id) if capture.thread_id else None,
        source_agent=capture.source_agent,
        source_kind=capture.source_kind.value,
        event_type=capture.event_type,
        actor_role=capture.actor_role.value,
        text_redacted=capture.text,
        evidence_refs_json=[source_ref_to_json(ref) for ref in capture.evidence_refs],
        payload_hash=capture.payload_hash,
        idempotency_key=capture.idempotency_key,
        status=capture.status.value,
        consolidation_status=capture.consolidation_status.value,
        trust_level=capture.trust_level.value,
        source_authority=capture.source_authority.value,
        sensitivity=capture.sensitivity.value,
        data_classification=capture.data_classification.value,
        occurred_at=capture.occurred_at,
        received_at=capture.received_at,
        created_at=capture.created_at,
        updated_at=capture.updated_at,
        metadata_json=dict(capture.metadata),
        source_event_id=capture.source_event_id,
        source_actor_external_ref=capture.source_actor_external_ref,
        client_instance_id=capture.client_instance_id,
        agent_session_external_ref=capture.agent_session_external_ref,
        turn_external_ref=capture.turn_external_ref,
        parent_capture_id=str(capture.parent_capture_id) if capture.parent_capture_id else None,
        sequence_index=capture.sequence_index,
        trace_id=capture.trace_id,
        schema_version=capture.schema_version,
        parser_version=capture.parser_version,
        redaction_version=capture.redaction_version,
        admission_version=capture.admission_version,
        normalization_version=capture.normalization_version,
        policy_version=capture.policy_version,
        extractor_version=capture.extractor_version,
        extractor_prompt_version=capture.extractor_prompt_version,
        resolver_version=capture.resolver_version,
        last_error_code=capture.last_error_code,
        last_error_message=capture.last_error_message,
    )


def capture_row_to_domain(row: MemoryCaptureRow) -> CanonicalCapture:
    return CanonicalCapture(
        id=MemoryCaptureId(row.id),
        space_id=SpaceId(row.space_id),
        memory_scope_id=MemoryScopeId(row.memory_scope_id),
        thread_id=ThreadId(row.thread_id) if row.thread_id else None,
        source_agent=row.source_agent,
        source_kind=CaptureSourceKind(row.source_kind),
        event_type=row.event_type,
        actor_role=CaptureActorRole(row.actor_role),
        text=row.text_redacted,
        evidence_refs=tuple(source_ref_from_json(ref) for ref in row.evidence_refs_json),
        payload_hash=row.payload_hash,
        idempotency_key=row.idempotency_key,
        status=CaptureStatus(row.status),
        consolidation_status=ConsolidationStatus(row.consolidation_status),
        trust_level=TrustLevel(row.trust_level),
        source_authority=SourceAuthority(row.source_authority),
        sensitivity=CaptureSensitivity(row.sensitivity),
        data_classification=DataClassification(row.data_classification),
        occurred_at=row.occurred_at,
        received_at=row.received_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata_json or {}),
        source_event_id=row.source_event_id,
        source_actor_external_ref=row.source_actor_external_ref,
        client_instance_id=row.client_instance_id,
        agent_session_external_ref=row.agent_session_external_ref,
        turn_external_ref=row.turn_external_ref,
        parent_capture_id=MemoryCaptureId(row.parent_capture_id) if row.parent_capture_id else None,
        sequence_index=row.sequence_index,
        trace_id=row.trace_id,
        schema_version=row.schema_version,
        parser_version=row.parser_version,
        redaction_version=row.redaction_version,
        admission_version=row.admission_version,
        normalization_version=row.normalization_version,
        policy_version=row.policy_version,
        extractor_version=row.extractor_version,
        extractor_prompt_version=row.extractor_prompt_version,
        resolver_version=row.resolver_version,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
    )


def apply_capture_to_row(capture: CanonicalCapture, row: MemoryCaptureRow) -> None:
    row.status = capture.status.value
    row.consolidation_status = capture.consolidation_status.value
    row.text_redacted = capture.text
    row.evidence_refs_json = [source_ref_to_json(ref) for ref in capture.evidence_refs]
    row.sensitivity = capture.sensitivity.value
    row.data_classification = capture.data_classification.value
    row.metadata_json = dict(capture.metadata)
    row.updated_at = capture.updated_at
    row.extractor_version = capture.extractor_version
    row.extractor_prompt_version = capture.extractor_prompt_version
    row.resolver_version = capture.resolver_version
    row.last_error_code = capture.last_error_code
    row.last_error_message = capture.last_error_message
