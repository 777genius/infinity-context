"""SQLAlchemy persistence models for canonical Postgres storage."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def json_type() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


class MemoryServiceTokenRow(Base):
    __tablename__ = "memory_service_tokens"
    __table_args__ = (Index("ix_memory_service_tokens_status", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    memory_scope_ids_json: Mapped[list[str] | None] = mapped_column(json_type(), nullable=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    permissions_json: Mapped[list[str] | None] = mapped_column(json_type(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemorySpaceRow(Base):
    __tablename__ = "memory_spaces"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryScopeRow(Base):
    __tablename__ = "memory_scopes"
    __table_args__ = (
        UniqueConstraint("space_id", "external_ref", name="uq_memory_scope_external_ref"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_spaces.id"),
        nullable=False,
    )
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryUsageRecordRow(Base):
    __tablename__ = "memory_usage_records"
    __table_args__ = (
        Index("uq_memory_usage_idempotency", "idempotency_key", unique=True),
        Index(
            "ix_memory_usage_subject_window",
            "subject_type",
            "subject_id",
            "resource",
            "status",
            "window_start",
            "window_end",
        ),
        Index("ix_memory_usage_space_created", "space_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(80), nullable=False)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryThreadRow(Base):
    __tablename__ = "memory_threads"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "memory_scope_id", "external_ref", name="uq_thread_external_ref"
        ),
        Index("ix_memory_threads_scope_status", "space_id", "memory_scope_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryAnchorRow(Base):
    __tablename__ = "memory_anchors"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    aliases_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_memory_anchor_active_key",
            "space_id",
            "memory_scope_id",
            "kind",
            "normalized_key",
            unique=True,
            sqlite_where=status == "active",
            postgresql_where=status == "active",
        ),
        Index(
            "ix_memory_anchors_scope_kind",
            "space_id",
            "memory_scope_id",
            "kind",
            "status",
            "updated_at",
        ),
    )


class MemoryFactRow(Base):
    __tablename__ = "memory_facts"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_fact_version_positive"),
        Index(
            "ix_memory_facts_scope_status", "space_id", "memory_scope_id", "status", "updated_at"
        ),
        Index("ix_memory_facts_taxonomy", "space_id", "memory_scope_id", "category", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="internal")
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    ttl_policy: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEpisodeRow(Base):
    __tablename__ = "memory_episodes"
    __table_args__ = (
        UniqueConstraint(
            "space_id",
            "memory_scope_id",
            "thread_id",
            "source_external_id",
            name="uq_episode_source",
        ),
        Index("ix_memory_episodes_thread_status", "thread_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)


class MemoryDocumentRow(Base):
    __tablename__ = "memory_documents"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_document_content_hash_memory_scope_wide",
            "space_id",
            "memory_scope_id",
            "content_hash",
            unique=True,
            sqlite_where=thread_id.is_(None) & (status != "deleted"),
            postgresql_where=thread_id.is_(None) & (status != "deleted"),
        ),
        Index(
            "uq_document_content_hash_thread",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "content_hash",
            unique=True,
            sqlite_where=thread_id.is_not(None) & (status != "deleted"),
            postgresql_where=thread_id.is_not(None) & (status != "deleted"),
        ),
        Index("ix_memory_documents_scope_status", "space_id", "memory_scope_id", "status"),
    )


class MemoryAssetRow(Base):
    __tablename__ = "memory_assets"
    __table_args__ = (
        Index(
            "ix_memory_assets_scope_status", "space_id", "memory_scope_id", "status", "created_at"
        ),
        Index("ix_memory_assets_hash_scope", "space_id", "memory_scope_id", "sha256_hex", "status"),
        Index("ix_memory_assets_thread_status", "thread_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="stored")
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryAssetExtractionJobRow(Base):
    __tablename__ = "memory_asset_extraction_jobs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    parser_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_config_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    source_sha256_hex: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_document_ids_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_after_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    __table_args__ = (
        Index("ix_asset_extraction_jobs_asset_status", "asset_id", "status", "created_at"),
        Index(
            "ix_asset_extraction_jobs_scope_status",
            "space_id",
            "memory_scope_id",
            "status",
            "updated_at",
        ),
        Index(
            "uq_asset_extraction_jobs_active_profile",
            "asset_id",
            "parser_profile",
            "parser_config_hash",
            "source_sha256_hex",
            unique=True,
            sqlite_where=status.in_(("pending", "running", "succeeded")),
            postgresql_where=status.in_(("pending", "running", "succeeded")),
        ),
        Index(
            "ix_asset_extraction_jobs_running_lease",
            "status",
            "lease_expires_at",
            "heartbeat_at",
        ),
    )


class MemoryAssetExtractionArtifactRow(Base):
    __tablename__ = "memory_asset_extraction_artifacts"
    __table_args__ = (
        Index("ix_asset_extraction_artifacts_job", "job_id", "artifact_type"),
        Index("ix_asset_extraction_artifacts_asset", "asset_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(80), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(80), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryChunkRow(Base):
    __tablename__ = "memory_chunks"
    __table_args__ = (
        UniqueConstraint("space_id", "memory_scope_id", "source_hash", name="uq_chunk_source_hash"),
        Index("ix_memory_chunks_scope_status", "space_id", "memory_scope_id", "status"),
        Index("ix_memory_chunks_thread_status", "thread_id", "status"),
        Index("ix_memory_chunks_document", "document_id", "status", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    episode_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)


class MemorySourceRefRow(Base):
    __tablename__ = "memory_source_refs"
    __table_args__ = (Index("ix_memory_source_refs_fact", "fact_id", "fact_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(String(80), ForeignKey("memory_facts.id"), nullable=False)
    fact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_preview: Mapped[str | None] = mapped_column(String(240), nullable=True)


class MemoryFactVersionRow(Base):
    __tablename__ = "memory_fact_versions"
    __table_args__ = (UniqueConstraint("fact_id", "version", name="uq_fact_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(String(80), ForeignKey("memory_facts.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_refs_json: Mapped[list[dict[str, object]]] = mapped_column(json_type(), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryFactRelationRow(Base):
    __tablename__ = "memory_fact_relations"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_fact_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_facts.id"),
        nullable=False,
    )
    target_fact_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_facts.id"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_memory_fact_relation_active",
            "source_fact_id",
            "target_fact_id",
            "relation_type",
            unique=True,
            sqlite_where=status == "active",
            postgresql_where=status == "active",
        ),
        Index("ix_memory_fact_relations_source", "source_fact_id", "status"),
        Index("ix_memory_fact_relations_target", "target_fact_id", "status"),
        Index("ix_memory_fact_relations_scope", "space_id", "memory_scope_id", "status"),
    )


class MemorySuggestionRow(Base):
    __tablename__ = "memory_suggestions"
    __table_args__ = (
        Index("ix_memory_suggestions_scope_status", "space_id", "memory_scope_id", "status"),
        Index("ix_memory_suggestions_target", "target_fact_id", "status"),
        Index(
            "ix_memory_suggestions_expiry", "space_id", "memory_scope_id", "status", "expires_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False, default="add")
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_refs_json: Mapped[list[dict[str, object]]] = mapped_column(json_type(), nullable=False)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_reason: Mapped[str] = mapped_column(String(320), nullable=False)
    target_fact_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    ttl_policy: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_from_capture_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    candidate_fingerprint: Mapped[str | None] = mapped_column(String(80), nullable=True)
    review_payload_json: Mapped[dict[str, object]] = mapped_column(
        json_type(),
        nullable=False,
        default=dict,
    )
    review_reason: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryCaptureRow(Base):
    __tablename__ = "memory_captures"
    __table_args__ = (
        UniqueConstraint("space_id", "idempotency_key", name="uq_capture_idempotency"),
        Index(
            "ix_memory_captures_scope_status", "space_id", "memory_scope_id", "status", "created_at"
        ),
        Index(
            "ix_memory_captures_consolidation",
            "space_id",
            "memory_scope_id",
            "consolidation_status",
            "created_at",
        ),
        Index(
            "ix_memory_captures_source",
            "space_id",
            "memory_scope_id",
            "source_agent",
            "event_type",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_agent: Mapped[str] = mapped_column(String(80), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    text_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[list[dict[str, object]]] = mapped_column(json_type(), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    consolidation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    source_authority: Mapped[str] = mapped_column(String(80), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(40), nullable=False)
    data_classification: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_actor_external_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    client_instance_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    agent_session_external_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    turn_external_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    parent_capture_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sequence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    redaction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    extractor_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extractor_prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(400), nullable=True)


class MemoryContextLinkRow(Base):
    __tablename__ = "memory_context_links"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    reason: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_memory_context_link_active",
            "space_id",
            "memory_scope_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            unique=True,
            sqlite_where=status == "active",
            postgresql_where=status == "active",
        ),
        Index(
            "ix_memory_context_links_source",
            "space_id",
            "memory_scope_id",
            "source_type",
            "source_id",
            "status",
        ),
        Index(
            "ix_memory_context_links_target",
            "space_id",
            "memory_scope_id",
            "target_type",
            "target_id",
            "status",
        ),
    )


class MemoryContextLinkSuggestionRow(Base):
    __tablename__ = "memory_context_link_suggestions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    reason: Mapped[str] = mapped_column(String(320), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(320), nullable=True)
    __table_args__ = (
        Index(
            "uq_context_link_suggestion_pending",
            "space_id",
            "memory_scope_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            unique=True,
            sqlite_where=status == "pending",
            postgresql_where=status == "pending",
        ),
        Index(
            "ix_context_link_suggestions_source",
            "space_id",
            "memory_scope_id",
            "source_type",
            "source_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_context_link_suggestions_status",
            "space_id",
            "memory_scope_id",
            "status",
            "updated_at",
        ),
    )


class MemoryOutboxRow(Base):
    __tablename__ = "memory_outbox"
    __table_args__ = (
        Index("ix_memory_outbox_status_next", "status", "next_attempt_at"),
        Index(
            "ix_memory_outbox_workload_fairness",
            "status",
            "workload_class",
            "fairness_key",
            "next_attempt_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workload_class: Mapped[str] = mapped_column(String(80), nullable=False, default="projection")
    fairness_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payload_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_safe_error: Mapped[str | None] = mapped_column(String(400), nullable=True)
    last_safe_diagnostic_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryIdempotencyRecordRow(Base):
    __tablename__ = "memory_idempotency_records"
    __table_args__ = (UniqueConstraint("space_id", "key", name="uq_idempotency_space_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(240), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(80), nullable=False)
    result_type: Mapped[str] = mapped_column(String(80), nullable=False)
    result_id: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
