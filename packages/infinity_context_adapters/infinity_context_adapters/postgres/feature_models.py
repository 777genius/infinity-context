"""SQLAlchemy rows owned by feature slices added during the strangler migration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.models import Base, json_type


class MemoryFactOperationReceiptRow(Base):
    __tablename__ = "memory_fact_operation_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["result_fact_id", "space_id", "memory_scope_id", "thread_scope_key"],
            [
                "memory_facts.id",
                "memory_facts.space_id",
                "memory_facts.memory_scope_id",
                "memory_facts.thread_scope_key",
            ],
            name="fk_memory_fact_operation_receipt_fact_scope",
        ),
        ForeignKeyConstraint(
            ["result_fact_id", "result_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_memory_fact_operation_receipt_fact_version",
        ),
        UniqueConstraint(
            "space_id",
            "memory_scope_id",
            "thread_scope_key",
            "operation",
            "idempotency_key",
            name="uq_memory_fact_operation_receipt_idempotency",
        ),
        CheckConstraint(
            "(thread_id IS NULL AND thread_scope_key = 'global') OR "
            "(thread_id IS NOT NULL AND thread_scope_key = 'thread:' || thread_id)",
            name="ck_memory_fact_operation_receipt_thread_scope_key",
        ),
        CheckConstraint(
            "result_fact_version > 0",
            name="ck_memory_fact_operation_receipt_result_version",
        ),
        Index("ix_memory_fact_operation_receipts_fact", "result_fact_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thread_scope_key: Mapped[str] = mapped_column(String(87), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_fact_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_facts.id"),
        nullable=False,
    )
    result_fact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_snapshot_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    outbox_message_ids_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    tombstone_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SuggestionResolutionReceiptRow(Base):
    __tablename__ = "suggestion_resolution_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["suggestion_id", "space_id", "memory_scope_id"],
            [
                "memory_suggestions.id",
                "memory_suggestions.space_id",
                "memory_suggestions.memory_scope_id",
            ],
            name="fk_suggestion_resolution_receipt_suggestion_scope",
        ),
        ForeignKeyConstraint(
            ["temporal_decision_id", "space_id", "memory_scope_id"],
            [
                "memory_fact_temporal_decisions.id",
                "memory_fact_temporal_decisions.space_id",
                "memory_fact_temporal_decisions.memory_scope_id",
            ],
            name="fk_suggestion_resolution_receipt_decision_scope",
        ),
        ForeignKeyConstraint(
            ["result_fact_id", "space_id", "memory_scope_id"],
            ["memory_facts.id", "memory_facts.space_id", "memory_facts.memory_scope_id"],
            name="fk_suggestion_resolution_receipt_fact_scope",
        ),
        ForeignKeyConstraint(
            ["result_fact_id", "result_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_suggestion_resolution_receipt_fact_version",
        ),
        ForeignKeyConstraint(
            [
                "relation_id",
                "space_id",
                "memory_scope_id",
                "temporal_decision_id",
            ],
            [
                "memory_fact_relations.id",
                "memory_fact_relations.space_id",
                "memory_fact_relations.memory_scope_id",
                "memory_fact_relations.temporal_decision_id",
            ],
            name="fk_suggestion_resolution_receipt_relation_decision",
        ),
        CheckConstraint(
            "relation_id IS NULL OR temporal_decision_id IS NOT NULL",
            name="ck_suggestion_resolution_receipt_relation_decision",
        ),
        CheckConstraint(
            "(result_fact_id IS NULL) = (result_fact_version IS NULL)",
            name="ck_suggestion_resolution_receipt_fact_pair",
        ),
        CheckConstraint(
            "(result_fact_id IS NULL) = (result_fact_json IS NULL)",
            name="ck_suggestion_resolution_receipt_fact_snapshot",
        ),
        UniqueConstraint(
            "suggestion_id",
            "operation",
            "idempotency_key",
            name="uq_suggestion_resolution_receipt_idempotency",
        ),
        Index("ix_suggestion_resolution_receipts_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suggestion_id: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
    )
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_suggestion_json: Mapped[dict[str, object]] = mapped_column(
        json_type(),
        nullable=False,
    )
    result_fact_json: Mapped[dict[str, object] | None] = mapped_column(
        json_type(none_as_null=True),
        nullable=True,
    )
    result_fact_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexing_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    affected_fact_ids_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    affected_fact_versions_json: Mapped[list[int]] = mapped_column(json_type(), nullable=False)
    temporal_decision_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    relation_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    outbox_message_ids_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeRepositoryRow(Base):
    __tablename__ = "code_repositories"
    __table_args__ = (
        UniqueConstraint("space_id", "repo_key", name="uq_code_repository_key"),
        UniqueConstraint("id", "space_id", name="uq_code_repository_id_space"),
        CheckConstraint("version > 0", name="ck_code_repository_version_positive"),
        Index("ix_code_repositories_space_status", "space_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_spaces.id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    repo_key: Mapped[str] = mapped_column(String(160), nullable=False)
    safe_label: Mapped[str | None] = mapped_column(String(240), nullable=True)
    remote_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_branch: Mapped[str | None] = mapped_column(String(240), nullable=True)
    monorepo_root: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeRepositoryAliasRow(Base):
    __tablename__ = "code_repository_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "space_id"],
            ["code_repositories.id", "code_repositories.space_id"],
            name="fk_code_repository_aliases_repository_space",
        ),
        UniqueConstraint(
            "space_id",
            "evidence_kind",
            "evidence_digest",
            name="uq_code_repository_alias_evidence",
        ),
        Index("ix_code_repository_aliases_repository", "repository_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repository_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("code_repositories.id"),
        nullable=False,
    )
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeRepositoryBindingRow(Base):
    __tablename__ = "code_repository_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "space_id"],
            ["code_repositories.id", "code_repositories.space_id"],
            name="fk_code_repository_bindings_repository_space",
        ),
        UniqueConstraint("grant_hash", name="uq_code_repository_binding_grant"),
        CheckConstraint(
            "version > 0",
            name="ck_code_repository_binding_version_positive",
        ),
        Index("ix_code_repository_bindings_repository_status", "repository_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("code_repositories.id"),
        nullable=False,
    )
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    grant_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_json: Mapped[list[dict[str, str]]] = mapped_column(json_type(), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CodeScopeAuthorizationRow(Base):
    __tablename__ = "code_scope_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["repository_id", "space_id"],
            ["code_repositories.id", "code_repositories.space_id"],
            name="fk_code_scope_authorizations_repository_space",
        ),
        UniqueConstraint(
            "repository_id",
            "code_scope_id",
            name="uq_code_scope_authorization_repository_scope",
        ),
        CheckConstraint(
            "version > 0",
            name="ck_code_scope_authorization_version_positive",
        ),
        CheckConstraint(
            "scope_level IN ('repository', 'branch', 'commit')",
            name="ck_code_scope_authorizations_level",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_code_scope_authorizations_status",
        ),
        Index(
            "ix_code_scope_authorizations_lookup",
            "repository_id",
            "space_id",
            "code_scope_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    repository_id: Mapped[str] = mapped_column(String(80), nullable=False)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    code_scope_id: Mapped[str] = mapped_column(String(96), nullable=False)
    scope_level: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryCognitiveProjectionRow(Base):
    __tablename__ = "memory_cognitive_projections"
    __table_args__ = (
        Index(
            "ix_memory_cognitive_projections_scope_state",
            "space_id",
            "memory_scope_id",
            "state",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    derivation_origin: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(80), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    invalidation_event_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryCognitiveDependencyRow(Base):
    __tablename__ = "memory_cognitive_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "projection_id",
            "evidence_type",
            "evidence_id",
            "evidence_version",
            name="uq_memory_cognitive_dependency",
        ),
        Index(
            "ix_memory_cognitive_dependencies_source",
            "space_id",
            "memory_scope_id",
            "evidence_type",
            "evidence_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    projection_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_cognitive_projections.id"),
        nullable=False,
    )
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(80), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    citation: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = (
    "CodeRepositoryAliasRow",
    "CodeRepositoryBindingRow",
    "CodeRepositoryRow",
    "CodeScopeAuthorizationRow",
    "MemoryCognitiveDependencyRow",
    "MemoryCognitiveProjectionRow",
    "MemoryFactOperationReceiptRow",
    "SuggestionResolutionReceiptRow",
)
