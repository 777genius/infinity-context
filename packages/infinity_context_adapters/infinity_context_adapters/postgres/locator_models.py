"""Canonical Postgres rows owned by locator Retrieval."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.orm import Base, json_type


class MemoryChunkRow(Base):
    __tablename__ = "memory_chunks"
    __table_args__ = (
        UniqueConstraint("space_id", "memory_scope_id", "source_hash", name="uq_chunk_source_hash"),
        CheckConstraint(
            "(document_id IS NOT NULL) <> (episode_id IS NOT NULL)",
            name="ck_chunk_owner",
        ),
        CheckConstraint(
            "retrieval_version BETWEEN 1 AND 9007199254740991",
            name="ck_memory_chunks_retrieval_version_positive",
        ),
        CheckConstraint(
            "retrieval_sequence_ordinal IS NULL OR "
            "retrieval_sequence_ordinal BETWEEN 0 AND 2147483647",
            name="ck_memory_chunks_retrieval_ordinal_range",
        ),
        CheckConstraint(
            "(retrieval_start_at IS NULL) = (retrieval_end_at IS NULL)",
            name="ck_memory_chunks_retrieval_time_complete",
        ),
        CheckConstraint(
            "retrieval_start_at IS NULL OR retrieval_start_at <= retrieval_end_at",
            name="ck_memory_chunks_retrieval_time_ordered",
        ),
        CheckConstraint(
            "(retrieval_relative_start_ms IS NULL) = (retrieval_relative_end_ms IS NULL)",
            name="ck_memory_chunks_retrieval_relative_time_complete",
        ),
        CheckConstraint(
            "retrieval_relative_start_ms IS NULL OR "
            "(retrieval_relative_start_ms BETWEEN 0 AND 9007199254740991 AND "
            "retrieval_relative_end_ms BETWEEN retrieval_relative_start_ms "
            "AND 9007199254740991)",
            name="ck_memory_chunks_retrieval_relative_time_range",
        ),
        CheckConstraint(
            "(retrieval_locator IS NULL AND retrieval_source_key IS NULL AND "
            "retrieval_projection_generation IS NULL AND "
            "retrieval_sequence_ordinal IS NULL AND retrieval_kind IS NULL AND "
            "retrieval_category IS NULL) OR (retrieval_locator IS NOT NULL AND "
            "retrieval_source_key IS NOT NULL AND "
            "retrieval_projection_generation IS NOT NULL AND "
            "retrieval_sequence_ordinal IS NOT NULL AND retrieval_kind IS NOT NULL "
            "AND retrieval_category IS NOT NULL)",
            name="ck_memory_chunks_retrieval_coordinates_complete",
        ),
        Index("ix_memory_chunks_scope_status", "space_id", "memory_scope_id", "status"),
        Index("ix_memory_chunks_thread_status", "thread_id", "status"),
        Index("ix_memory_chunks_document", "document_id", "status", "sequence"),
        Index(
            "ix_memory_chunks_locator_retrieval",
            "space_id",
            "memory_scope_id",
            "status",
            "retrieval_projection_generation",
            "retrieval_source_key",
            "retrieval_sequence_ordinal",
        ),
        Index(
            "uq_memory_chunks_retrieval_locator_owner",
            "space_id",
            "memory_scope_id",
            "retrieval_locator",
            unique=True,
            postgresql_where=text("retrieval_locator IS NOT NULL"),
        ),
        Index(
            "uq_memory_chunks_retrieval_active_ordinal_owner",
            "space_id",
            "memory_scope_id",
            text("COALESCE(thread_id, '')"),
            "retrieval_source_key",
            "retrieval_projection_generation",
            "retrieval_sequence_ordinal",
            unique=True,
            postgresql_where=text(
                "retrieval_locator IS NOT NULL AND status = 'active' AND "
                "classification IN ('public', 'internal')"
            ),
            sqlite_where=text(
                "retrieval_locator IS NOT NULL AND status = 'active' AND "
                "classification IN ('public', 'internal')"
            ),
        ),
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
    retrieval_locator: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieval_source_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieval_projection_generation: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieval_sequence_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_kind: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieval_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    retrieval_actor_keys_json: Mapped[list[str]] = mapped_column(
        json_type(), nullable=False, default=list
    )
    retrieval_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieval_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieval_relative_start_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retrieval_relative_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retrieval_category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    retrieval_tags_json: Mapped[list[str]] = mapped_column(
        json_type(), nullable=False, default=list
    )
    retrieval_commit_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class MemoryDocumentProjectionReceiptRow(Base):
    __tablename__ = "memory_document_projection_receipts"
    space_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(240), primary_key=True)
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("memory_documents.id"), nullable=False
    )
    locator: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileRow(Base):
    __tablename__ = "memory_locator_profiles"
    __table_args__ = (
        CheckConstraint(
            "state IN ('building', 'active', 'retained', 'retired')",
            name="ck_locator_profile_state",
        ),
        CheckConstraint(
            "expected_count >= 0 AND projected_count >= 0 AND canonical_watermark >= 0 "
            "AND projected_watermark >= 0",
            name="ck_locator_profile_counts",
        ),
        UniqueConstraint("generation", "profile_digest", name="uq_locator_profile_identity"),
        UniqueConstraint("collection_name", name="uq_locator_profile_collection"),
        Index(
            "uq_locator_profile_one_building",
            "state",
            unique=True,
            postgresql_where=text("state = 'building'"),
            sqlite_where=text("state = 'building'"),
        ),
        Index(
            "uq_locator_profile_one_active",
            "state",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
        Index(
            "ix_locator_profiles_routable",
            "state",
            "created_at",
            postgresql_where=text("state IN ('building', 'active', 'retained')"),
            sqlite_where=text("state IN ('building', 'active', 'retained')"),
        ),
    )
    profile_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    generation: Mapped[str] = mapped_column(String(160), nullable=False)
    profile_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(240), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    backfill_cursor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canonical_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    projected_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expected_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    projected_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expected_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    projected_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backfill_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_lease_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activation_evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    activation_lease_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activation_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activation_evidence_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    activation_mutation_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciliation_drifted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    provider_mutation_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class MemoryLocatorProfileProjectionReceiptRow(Base):
    __tablename__ = "memory_locator_profile_projection_receipts"
    __table_args__ = (
        CheckConstraint(
            "canonical_version BETWEEN 1 AND 9007199254740991",
            name="ck_locator_profile_receipt_version",
        ),
        CheckConstraint(
            "canonical_watermark >= 0",
            name="ck_locator_profile_receipt_watermark",
        ),
    )
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    canonical_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    projected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileLaneRow(Base):
    __tablename__ = "memory_locator_profile_lanes"
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    lane_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    healthy: Mapped[bool] = mapped_column(Boolean, nullable=False)
    profile_qualified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    observed_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )


class MemoryLocatorProfileAttestationCheckpointRow(Base):
    __tablename__ = "memory_locator_profile_attestation_checkpoints"
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    digest_accumulator: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    validation_page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_item_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    validation_accumulator: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    owner_operation_id: Mapped[str | None] = mapped_column(String(120), nullable=True)


class MemoryLocatorProfileReconciliationOperationRow(Base):
    __tablename__ = "memory_locator_profile_reconciliation_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ("runtime_instance_id", "runtime_generation"),
            (
                "memory_locator_runtime_incarnations.instance_id",
                "memory_locator_runtime_incarnations.generation",
            ),
            name="fk_locator_reconciliation_operation_runtime",
        ),
    )
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    predecessor_lease_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    predecessor_generation: Mapped[str] = mapped_column(String(160), nullable=False)
    predecessor_evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predecessor_lease_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    predecessor_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    predecessor_drifted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    runtime_instance_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    runtime_generation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lifecycle_identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileProviderMutationRow(Base):
    __tablename__ = "memory_locator_profile_provider_mutations"
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_generation: Mapped[str] = mapped_column(String(120), nullable=False)
    started_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileQueryRow(Base):
    """Exact active-lease reader held for the complete retrieval operation."""

    __tablename__ = "memory_locator_profile_queries"
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_generation: Mapped[str] = mapped_column(String(120), nullable=False)
    activation_lease_id: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileEvidenceVersionRow(Base):
    __tablename__ = "memory_locator_profile_evidence_versions"
    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    aggregate_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileMaintenanceFenceRow(Base):
    """Singleton row lock serializing admission with explicit operator recovery."""

    __tablename__ = "memory_locator_profile_maintenance_fence"
    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    fence_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorRuntimeIncarnationRow(Base):
    """Durable identity and drain acknowledgement for one runtime incarnation."""

    __tablename__ = "memory_locator_runtime_incarnations"
    instance_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    generation: Mapped[str] = mapped_column(String(120), primary_key=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    supervisor_key_id: Mapped[str] = mapped_column(String(120), nullable=False)
    supervisor_public_key: Mapped[str] = mapped_column(String(64), nullable=False)
    trust_root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    trust_registry_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    launch_token: Mapped[str] = mapped_column(String(120), nullable=False)
    process_pid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    process_birth_identity: Mapped[str] = mapped_column(String(120), nullable=False)
    executable_identity: Mapped[str] = mapped_column(String(512), nullable=False)
    executable_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    release_source_tree_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    release_installed_distribution_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    release_runtime_modules_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    release_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    launch_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_dead_generation: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sealed_dead_proof_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sealed_dead_proof_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sealed_dead_authority: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sealed_dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryLocatorProviderReconciliationReceiptRow(Base):
    """Provider-produced observation bound to one maintenance recovery epoch."""

    __tablename__ = "memory_locator_provider_reconciliation_receipts"
    receipt_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_generation: Mapped[str] = mapped_column(String(160), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(240), nullable=False)
    maintenance_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    evidence_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_generation: Mapped[str] = mapped_column(String(120), nullable=False)
    mutation_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stale_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    observed_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_state: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    launch_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_by_recovery_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryLocatorProfileRecoveryReceiptRow(Base):
    """Create-only audit receipt for one exact abandoned-fence recovery."""

    __tablename__ = "memory_locator_profile_recovery_receipts"
    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_instance_id: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_generation: Mapped[str] = mapped_column(String(120), nullable=False)
    lease_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mutation_epoch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stale_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    reconciliation_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_receipt_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    maintenance_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    launch_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sealed_dead_proof_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sealed_dead_proof_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileAttestationPageRow(Base):
    __tablename__ = "memory_locator_profile_attestation_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ("profile_id", "operation_id"),
            (
                "memory_locator_profile_attestation_checkpoints.profile_id",
                "memory_locator_profile_attestation_checkpoints.operation_id",
            ),
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "page_number >= 0 AND item_count >= 0 AND byte_count >= 0",
            name="ck_locator_profile_attestation_page_bounds",
        ),
    )
    profile_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    end_cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_digest: Mapped[str] = mapped_column(String(64), nullable=False)


class MemoryLocatorProfileOperatorReceiptRow(Base):
    """Exact-result receipt for the strict-admin profile mutation boundary."""

    __tablename__ = "memory_locator_profile_operator_receipts"
    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    result_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    runtime_instance_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    runtime_generation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    launch_identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lifecycle_identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileOperatorOperationRow(Base):
    """Durable key/fingerprint reservation while bounded work is incomplete."""

    __tablename__ = "memory_locator_profile_operator_operations"
    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileOperatorRebuildRow(Base):
    """Recoverable plan removed atomically when its exact receipt is appended."""

    __tablename__ = "memory_locator_profile_operator_rebuilds"
    idempotency_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), nullable=False
    )
    plan_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileTransitionAuditRow(Base):
    """Append-only evidence for active-profile pointer and attestation-lease transitions."""

    __tablename__ = "memory_locator_profile_transition_audit"
    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), nullable=False
    )
    previous_active_profile_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_instance_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    runtime_generation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lifecycle_identity_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mutation_epoch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reconciliation_drifted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileTombstoneRow(Base):
    __tablename__ = "memory_locator_profile_tombstones"
    __table_args__ = (
        CheckConstraint("canonical_version > 0", name="ck_locator_profile_tombstone_version"),
        CheckConstraint(
            "delete_canonical_version > 0",
            name="ck_locator_profile_tombstone_delete_version",
        ),
        Index(
            "ix_locator_profile_tombstones_pending",
            "profile_id",
            "updated_at",
            "chunk_id",
            postgresql_where=text("completed_at IS NULL"),
            sqlite_where=text("completed_at IS NULL"),
        ),
    )
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    chunk_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    canonical_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delete_canonical_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryLocatorProfileCleanupRow(Base):
    __tablename__ = "memory_locator_profile_cleanups"
    __table_args__ = (
        CheckConstraint(
            "phase IN ('requested', 'waiting_for_jobs', 'collection_deleted', "
            "'postgres_cleaned', 'complete')",
            name="ck_locator_profile_cleanup_phase",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_locator_profile_cleanup_attempt_count"),
        CheckConstraint(
            "(delete_token IS NULL AND delete_epoch IS NULL AND delete_authorized_at IS NULL) "
            "OR (delete_token IS NOT NULL AND delete_epoch > 0 "
            "AND delete_authorized_at IS NOT NULL)",
            name="ck_locator_profile_cleanup_delete_authority",
        ),
        Index(
            "ix_locator_profile_cleanups_pending",
            "phase",
            "updated_at",
            postgresql_where=text("phase <> 'complete'"),
            sqlite_where=text("phase <> 'complete'"),
        ),
    )
    profile_id: Mapped[str] = mapped_column(
        String(120), ForeignKey("memory_locator_profiles.profile_id"), primary_key=True
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delete_token: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delete_epoch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delete_authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = (
    "MemoryChunkRow",
    "MemoryDocumentProjectionReceiptRow",
    "MemoryLocatorProfileLaneRow",
    "MemoryLocatorProfileAttestationCheckpointRow",
    "MemoryLocatorProfileAttestationPageRow",
    "MemoryLocatorProfileProviderMutationRow",
    "MemoryLocatorProfileQueryRow",
    "MemoryLocatorProfileEvidenceVersionRow",
    "MemoryLocatorProfileMaintenanceFenceRow",
    "MemoryLocatorProviderReconciliationReceiptRow",
    "MemoryLocatorRuntimeIncarnationRow",
    "MemoryLocatorProfileRecoveryReceiptRow",
    "MemoryLocatorProfileReconciliationOperationRow",
    "MemoryLocatorProfileOperatorReceiptRow",
    "MemoryLocatorProfileOperatorOperationRow",
    "MemoryLocatorProfileOperatorRebuildRow",
    "MemoryLocatorProfileTransitionAuditRow",
    "MemoryLocatorProfileCleanupRow",
    "MemoryLocatorProfileProjectionReceiptRow",
    "MemoryLocatorProfileRow",
    "MemoryLocatorProfileTombstoneRow",
)
