"""SQLAlchemy persistence models for canonical Postgres storage."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.fact_audit_constraints import (
    active_predecessor_index,
    memory_fact_relation_tenant_constraints,
    memory_fact_relation_version_constraint,
)
from infinity_context_adapters.postgres.fact_storage_constraints import (
    memory_fact_storage_constraints,
)
from infinity_context_adapters.postgres.orm import Base, json_type
from infinity_context_adapters.postgres.suggestion_constraints import (
    pending_suggestion_fingerprint_indexes,
)


class MemoryServiceTokenRow(Base):
    __tablename__ = "memory_service_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "space_id"],
            ["code_repositories.id", "code_repositories.space_id"],
            name="fk_memory_service_tokens_repository_space",
        ),
        CheckConstraint(
            "repository_id IS NULL OR space_id IS NOT NULL",
            name="ck_memory_service_tokens_repository_space_pair",
        ),
        CheckConstraint(
            "code_scope_id IS NULL OR repository_id IS NOT NULL",
            name="ck_memory_service_tokens_code_scope_pair",
        ),
        Index("ix_memory_service_tokens_status", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    memory_scope_ids_json: Mapped[list[str] | None] = mapped_column(json_type(), nullable=True)
    repository_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    code_scope_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    permissions_json: Mapped[list[str] | None] = mapped_column(json_type(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryUserRow(Base):
    __tablename__ = "memory_users"
    __table_args__ = (
        Index("uq_memory_user_external_ref", "external_ref", unique=True),
        Index("ix_memory_users_status", "status", "updated_at"),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    external_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    metadata_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemorySpaceRow(Base):
    __tablename__ = "memory_spaces"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemorySpaceMembershipRow(Base):
    __tablename__ = "memory_space_memberships"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_spaces.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_users.id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_memory_space_membership_active_user",
            "space_id",
            "user_id",
            unique=True,
            sqlite_where=status == "active",
            postgresql_where=status == "active",
        ),
        Index("ix_memory_space_memberships_space", "space_id", "status", "updated_at"),
        Index("ix_memory_space_memberships_user", "user_id", "status", "updated_at"),
    )


class MemoryScopeRow(Base):
    __tablename__ = "memory_scopes"
    __table_args__ = (
        UniqueConstraint("space_id", "external_ref", name="uq_memory_scope_external_ref"),
        Index("ix_memory_scopes_space_id_id", "space_id", "id"),
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
        Index("ix_memory_threads_space_scope_id", "space_id", "memory_scope_id", "id"),
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
    confidence: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    evidence_refs_json: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(),
        nullable=False,
        default=list,
    )
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            name="uq_memory_facts_id_scope",
        ),
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            "thread_scope_key",
            name="uq_memory_facts_id_scope_thread",
        ),
        ForeignKeyConstraint(
            ["repository_id", "space_id"],
            ["code_repositories.id", "code_repositories.space_id"],
            name="fk_memory_facts_repository_space",
        ),
        *memory_fact_storage_constraints(),
        Index(
            "ix_memory_facts_scope_status", "space_id", "memory_scope_id", "status", "updated_at"
        ),
        Index("ix_memory_facts_taxonomy", "space_id", "memory_scope_id", "category", "status"),
        Index(
            "ix_memory_facts_temporal_selection",
            "space_id",
            "memory_scope_id",
            "status",
            "temporal_kind",
            "valid_from",
            "valid_to",
        ),
        Index(
            "ix_memory_facts_code_scope",
            "space_id",
            "memory_scope_id",
            "repository_id",
            "code_scope_id",
            "status",
        ),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thread_scope_key: Mapped[str] = mapped_column(
        String(87),
        Computed(
            "CASE WHEN thread_id IS NULL THEN 'global' ELSE 'thread:' || thread_id END",
            persisted=True,
        ),
    )
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="internal")
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False, default=list)
    evidence_refs_json: Mapped[list[dict[str, object]]] = mapped_column(
        json_type(), nullable=False, default=list
    )
    ttl_policy: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temporal_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="state")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temporal_basis: Mapped[str] = mapped_column(
        String(80), nullable=False, default="migrated_legacy"
    )
    temporal_precision: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmation_basis: Mapped[str | None] = mapped_column(String(120), nullable=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    epistemic_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="world_claim")
    asserted_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    perspective_subject: Mapped[str | None] = mapped_column(String(160), nullable=True)
    repository_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    code_scope_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
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
    retrieval_projected: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index(
            "uq_document_content_hash_memory_scope_wide",
            "space_id",
            "memory_scope_id",
            "content_hash",
            unique=True,
            sqlite_where=thread_id.is_(None)
            & (status != "deleted")
            & retrieval_projected.is_(False),
            postgresql_where=thread_id.is_(None)
            & (status != "deleted")
            & retrieval_projected.is_(False),
        ),
        Index(
            "uq_document_content_hash_thread",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "content_hash",
            unique=True,
            sqlite_where=thread_id.is_not(None)
            & (status != "deleted")
            & retrieval_projected.is_(False),
            postgresql_where=thread_id.is_not(None)
            & (status != "deleted")
            & retrieval_projected.is_(False),
        ),
        Index("ix_memory_documents_scope_status", "space_id", "memory_scope_id", "status"),
        Index(
            "ix_memory_documents_scope_status_page",
            "space_id",
            "memory_scope_id",
            "status",
            updated_at.desc(),
            id.desc(),
        ),
        Index(
            "ix_memory_documents_scope_thread_status_page",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "status",
            updated_at.desc(),
            id.desc(),
        ),
        Index(
            "ix_memory_documents_scope_thread_source_page",
            "space_id",
            "memory_scope_id",
            "thread_id",
            "source_external_id",
            "status",
            updated_at.desc(),
            id.desc(),
        ),
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
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox_json: Mapped[list[float] | None] = mapped_column(json_type(), nullable=True)


class MemoryFactVersionRow(Base):
    __tablename__ = "memory_fact_versions"
    __table_args__ = (UniqueConstraint("fact_id", "version", name="uq_fact_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(String(80), ForeignKey("memory_facts.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_refs_json: Mapped[list[dict[str, object]]] = mapped_column(json_type(), nullable=False)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(
        json_type(), nullable=False, default=dict
    )
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryFactRelationRow(Base):
    __tablename__ = "memory_fact_relations"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thread_scope_key: Mapped[str] = mapped_column(
        String(87),
        Computed(
            "CASE WHEN thread_id IS NULL THEN 'global' ELSE 'thread:' || thread_id END",
            persisted=True,
        ),
    )
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
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temporal_decision_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            "temporal_decision_id",
            name="uq_memory_fact_relations_receipt_identity",
        ),
        *memory_fact_relation_tenant_constraints(),
        memory_fact_relation_version_constraint(),
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
        Index(
            "uq_memory_fact_single_active_supersession",
            "target_fact_id",
            unique=True,
            sqlite_where=and_(
                relation_type == "supersedes",
                status == "active",
                temporal_decision_id.is_not(None),
            ),
            postgresql_where=and_(
                relation_type == "supersedes",
                status == "active",
                temporal_decision_id.is_not(None),
            ),
        ),
        active_predecessor_index(relation_type, status, temporal_decision_id),
    )


class MemorySuggestionRow(Base):
    __tablename__ = "memory_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            name="uq_memory_suggestions_id_scope",
        ),
        Index("ix_memory_suggestions_scope_status", "space_id", "memory_scope_id", "status"),
        Index("ix_memory_suggestions_target", "target_fact_id", "status"),
        Index(
            "ix_memory_suggestions_expiry", "space_id", "memory_scope_id", "status", "expires_at"
        ),
        *pending_suggestion_fingerprint_indexes(),
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


# Imported last to preserve the legacy public model surface.
from infinity_context_adapters.postgres.benchmark_run_models import (  # noqa: E402
    MemoryComparisonBenchmarkRunRow,  # noqa: F401
)
from infinity_context_adapters.postgres.locator_models import (  # noqa: E402
    MemoryChunkRow,  # noqa: F401
    MemoryDocumentProjectionReceiptRow,  # noqa: F401
    MemoryLocatorProfileAttestationCheckpointRow,  # noqa: F401
    MemoryLocatorProfileAttestationPageRow,  # noqa: F401
    MemoryLocatorProfileCleanupRow,  # noqa: F401
    MemoryLocatorProfileEvidenceVersionRow,  # noqa: F401
    MemoryLocatorProfileLaneRow,  # noqa: F401
    MemoryLocatorProfileMaintenanceFenceRow,  # noqa: F401
    MemoryLocatorProfileOperatorOperationRow,  # noqa: F401
    MemoryLocatorProfileOperatorRebuildRow,  # noqa: F401
    MemoryLocatorProfileOperatorReceiptRow,  # noqa: F401
    MemoryLocatorProfileProjectionReceiptRow,  # noqa: F401
    MemoryLocatorProfileProviderMutationRow,  # noqa: F401
    MemoryLocatorProfileQueryRow,  # noqa: F401
    MemoryLocatorProfileReconciliationOperationRow,  # noqa: F401
    MemoryLocatorProfileRecoveryReceiptRow,  # noqa: F401
    MemoryLocatorProfileRow,  # noqa: F401
    MemoryLocatorProfileTombstoneReplayRow,  # noqa: F401
    MemoryLocatorProfileTombstoneRow,  # noqa: F401
    MemoryLocatorProfileTransitionAuditRow,  # noqa: F401
    MemoryLocatorProviderReconciliationReceiptRow,  # noqa: F401
    MemoryLocatorRuntimeIncarnationRow,  # noqa: F401
)
from infinity_context_adapters.postgres.outbox_models import (  # noqa: E402
    MemoryOutboxRow,  # noqa: F401
)
from infinity_context_adapters.postgres.projection_receipt_models import (  # noqa: E402
    MemoryCleanupInventoryKeyRow,  # noqa: F401
    MemoryCleanupInventoryMaterializationRow,  # noqa: F401
    MemoryCleanupV3ContextAuthorityRow,  # noqa: F401
    MemoryProjectionReceiptClaimRow,  # noqa: F401
    MemoryProjectionReceiptIdentityLinkRow,  # noqa: F401
    MemoryProjectionResultReceiptRow,  # noqa: F401
    MemoryProjectionTargetIdentityRow,  # noqa: F401
)
from infinity_context_adapters.postgres.strict_v4_preparation_models import (  # noqa: E402
    MemoryComparisonStrictV4PreparationRow,  # noqa: F401
)
from infinity_context_adapters.postgres.temporal_models import (  # noqa: E402
    MemoryFactTemporalDecisionRow,  # noqa: F401
)
from infinity_context_adapters.postgres.vector_rebuild_models import (  # noqa: E402
    MemoryVectorRebuildOperationRow,  # noqa: F401
)
