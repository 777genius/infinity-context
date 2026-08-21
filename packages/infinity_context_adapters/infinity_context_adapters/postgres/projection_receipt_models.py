"""Normalized persistence rows for authenticated projection-result receipts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

_DIGEST_PATTERN = "^[0-9a-f]{64}$"
_IDENTITY_KINDS = (
    "qdrant_point_id",
    "graphiti_group_id",
    "graphiti_group_name",
    "graphiti_episode_uuid",
    "graphiti_episode_name",
    "graphiti_node_uuid",
    "graphiti_node_name",
    "graphiti_relation_uuid",
    "graphiti_relation_name",
)
_INVENTORY_KINDS = (
    "memory_scopes",
    "memory_threads",
    "facts",
    "fact_source_refs",
    "documents",
    "chunks",
    "qdrant_target_identities",
    "graphiti_target_names",
    "graphiti_target_uuids",
    "qdrant_upsert_jobs",
    "qdrant_delete_jobs",
    "graphiti_upsert_jobs",
    "graphiti_delete_jobs",
    "cleanup_outbox_receipts",
    "unsupported_rows",
)


def _sql_literals(values: tuple[str, ...]) -> str:
    return ", ".join(repr(value) for value in values)


def _pg_digest_constraint(columns: tuple[str, ...], name: str):
    expression = " AND ".join(f"{column} ~ {_DIGEST_PATTERN!r}" for column in columns)
    return CheckConstraint(expression, name=name).ddl_if(dialect="postgresql")


class MemoryCleanupV3ContextAuthorityRow(Base):
    __tablename__ = "memory_cleanup_v3_context_authorities"
    __table_args__ = (
        UniqueConstraint(
            "run_id_sha256",
            "context_sha256",
            name="uq_cleanup_v3_context_authority_run_context",
        ),
        UniqueConstraint(
            "run_id_sha256",
            "context_sha256",
            "authority_terminal_sha256",
            name="uq_cleanup_v3_context_authority_run_context_terminal",
        ),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "context_sha256",
                "authority_terminal_sha256",
                "registration_sha256",
                "registration_mac_sha256",
            ),
            "ck_projection_context_authority_digests",
        ),
    )

    run_id_sha256: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("memory_comparison_benchmark_runs.run_id_sha256"),
        nullable=False,
    )
    context_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    authority_terminal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    authority_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    registration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryProjectionReceiptClaimRow(Base):
    __tablename__ = "memory_projection_receipt_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "context_sha256"],
            [
                "memory_cleanup_v3_context_authorities.run_id_sha256",
                "memory_cleanup_v3_context_authorities.context_sha256",
            ],
            name="fk_projection_receipt_claim_context",
        ),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "context_sha256",
                "worker_authority_sha256",
                "projection_key_sha256",
                "expected_identities_sha256",
                "claim_token_sha256",
            ),
            "ck_projection_receipt_claim_digests",
        ),
        CheckConstraint(
            f"state IN ({chr(39)}prepared{chr(39)}, {chr(39)}dispatch_started{chr(39)}) "
            f"AND generation > 0 AND operation IN ({chr(39)}upsert{chr(39)}, "
            f"{chr(39)}delete{chr(39)})",
            name="ck_projection_receipt_claim_state",
        ),
    )

    outbox_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("memory_outbox.id", ondelete="CASCADE"), primary_key=True
    )
    run_id_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_identities_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryProjectionResultReceiptRow(Base):
    __tablename__ = "memory_projection_result_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "context_sha256"],
            [
                "memory_cleanup_v3_context_authorities.run_id_sha256",
                "memory_cleanup_v3_context_authorities.context_sha256",
            ],
            name="fk_projection_receipt_context_authority",
        ),
        CheckConstraint(
            "identity_count BETWEEN 1 AND 1000000",
            name="ck_projection_receipt_identity_count",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'delete')",
            name="ck_projection_receipt_operation",
        ),
        CheckConstraint(
            "result_state IN ('present', 'absent')",
            name="ck_projection_receipt_result_state",
        ),
        CheckConstraint(
            "(operation = 'upsert' AND result_state = 'present') OR "
            "(operation = 'delete' AND result_state = 'absent')",
            name="ck_projection_receipt_operation_result",
        ),
        CheckConstraint("lane IN ('qdrant', 'graphiti')", name="ck_projection_receipt_lane"),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "context_sha256",
                "target_authority_sha256",
                "worker_authority_sha256",
                "outbox_event_commitment_sha256",
                "ordered_identity_root_sha256",
                "lineage_root_sha256",
                "receipt_sha256",
                "receipt_mac_sha256",
            ),
            "ck_projection_receipt_digests",
        ),
        Index("ix_projection_receipts_run_receipt", "run_id_sha256", "receipt_sha256"),
        Index(
            "ix_projection_receipts_cleanup_page",
            "run_id_sha256",
            "context_sha256",
            "space_id",
            "outbox_id",
        ),
        Index(
            "ix_projection_receipts_inventory_page",
            "run_id_sha256",
            "context_sha256",
            "space_id",
            "lane",
            "operation",
            "outbox_id",
        ),
        Index(
            "ix_projection_receipts_operation_page",
            "run_id_sha256",
            "context_sha256",
            "space_id",
            "operation",
            "outbox_id",
        ),
        Index(
            "ix_projection_receipts_delete_page",
            "run_id_sha256",
            "context_sha256",
            "space_id",
            "outbox_id",
            postgresql_where=text("operation = 'delete'"),
        ),
        UniqueConstraint("outbox_id", "run_id_sha256", name="uq_projection_receipt_outbox_run"),
        UniqueConstraint(
            "run_id_sha256",
            "context_sha256",
            "lane",
            "operation",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            name="uq_projection_receipt_canonical_job",
            postgresql_nulls_not_distinct=True,
        ),
    )

    outbox_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("memory_outbox.id"), primary_key=True
    )
    run_id_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_comparison_benchmark_runs.run_id_sha256"), nullable=False
    )
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lane: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    result_state: Mapped[str] = mapped_column(String(20), nullable=False)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    outbox_event_commitment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ordered_identity_root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class MemoryProjectionTargetIdentityRow(Base):
    __tablename__ = "memory_projection_target_identities"
    __table_args__ = (
        CheckConstraint(
            "canonical_source_id <> '' AND physical_identity <> ''",
            name="ck_projection_identity_physical_value",
        ),
        CheckConstraint(
            "kind IN ('qdrant_point_id', 'graphiti_group_id', 'graphiti_group_name', "
            "'graphiti_episode_uuid', 'graphiti_episode_name', 'graphiti_node_uuid', "
            "'graphiti_node_name', 'graphiti_relation_uuid', 'graphiti_relation_name')",
            name="ck_projection_identity_kind",
        ),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "identity_sha256",
                "identity_commitment_sha256",
                "lineage_root_sha256",
                "target_authority_sha256",
                "identity_mac_sha256",
            ),
            "ck_projection_identity_digests",
        ),
        UniqueConstraint(
            "run_id_sha256",
            "kind",
            "identity_sha256",
            "identity_commitment_sha256",
            name="uq_projection_identity_authenticated",
        ),
    )

    run_id_sha256: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("memory_comparison_benchmark_runs.run_id_sha256"),
        primary_key=True,
    )
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    identity_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_commitment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    physical_identity: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    target_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryProjectionReceiptIdentityLinkRow(Base):
    __tablename__ = "memory_projection_receipt_identity_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "kind", "identity_sha256", "identity_commitment_sha256"],
            [
                "memory_projection_target_identities.run_id_sha256",
                "memory_projection_target_identities.kind",
                "memory_projection_target_identities.identity_sha256",
                "memory_projection_target_identities.identity_commitment_sha256",
            ],
            name="fk_projection_receipt_link_identity",
        ),
        ForeignKeyConstraint(
            ["outbox_id", "run_id_sha256"],
            [
                "memory_projection_result_receipts.outbox_id",
                "memory_projection_result_receipts.run_id_sha256",
            ],
            name="fk_projection_receipt_link_receipt",
            ondelete="CASCADE",
        ),
        CheckConstraint("ordinal >= 0", name="ck_projection_receipt_link_ordinal"),
        _pg_digest_constraint(
            ("run_id_sha256", "identity_sha256", "identity_commitment_sha256"),
            "ck_projection_receipt_link_digests",
        ),
        UniqueConstraint("outbox_id", "ordinal", name="uq_projection_receipt_link_ordinal"),
        Index(
            "ix_projection_links_identity_outbox",
            "run_id_sha256",
            "kind",
            "identity_sha256",
            "identity_commitment_sha256",
            "outbox_id",
            postgresql_include=("ordinal",),
        ),
        Index(
            "ix_projection_links_outbox_page",
            "run_id_sha256",
            "outbox_id",
            "identity_sha256",
            "kind",
            "identity_commitment_sha256",
        ),
    )

    outbox_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    run_id_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    identity_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity_commitment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class MemoryCleanupInventoryMaterializationRow(Base):
    __tablename__ = "memory_cleanup_inventory_materializations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "context_sha256", "authority_terminal_sha256"],
            [
                "memory_cleanup_v3_context_authorities.run_id_sha256",
                "memory_cleanup_v3_context_authorities.context_sha256",
                "memory_cleanup_v3_context_authorities.authority_terminal_sha256",
            ],
            name="fk_cleanup_inventory_context_authority",
        ),
        CheckConstraint(
            "expected_count BETWEEN 0 AND 1000000000",
            name="ck_cleanup_inventory_expected_count",
        ),
        CheckConstraint(
            f"kind IN ({_sql_literals(_INVENTORY_KINDS)})",
            name="ck_cleanup_inventory_materialization_kind",
        ),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "context_sha256",
                "cleanup_receipt_sha256",
                "authority_terminal_sha256",
                "ordered_rows_root_sha256",
                "row_mac_sha256",
            ),
            "ck_cleanup_inventory_materialization_digests",
        ),
    )

    run_id_sha256: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("memory_comparison_benchmark_runs.run_id_sha256"),
        primary_key=True,
    )
    context_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    cleanup_receipt_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), primary_key=True)
    authority_terminal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ordered_rows_root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    complete: Mapped[bool] = mapped_column(nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class MemoryCleanupInventoryKeyRow(Base):
    __tablename__ = "memory_cleanup_inventory_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "context_sha256", "cleanup_receipt_sha256", "kind"],
            [
                "memory_cleanup_inventory_materializations.run_id_sha256",
                "memory_cleanup_inventory_materializations.context_sha256",
                "memory_cleanup_inventory_materializations.cleanup_receipt_sha256",
                "memory_cleanup_inventory_materializations.kind",
            ],
            name="fk_cleanup_inventory_key_materialization",
        ),
        UniqueConstraint(
            "run_id_sha256",
            "context_sha256",
            "cleanup_receipt_sha256",
            "kind",
            "locator_sha256",
            name="uq_cleanup_inventory_locator",
        ),
        CheckConstraint(
            f"kind IN ({_sql_literals(_INVENTORY_KINDS)})",
            name="ck_cleanup_inventory_key_kind",
        ),
        _pg_digest_constraint(
            (
                "run_id_sha256",
                "context_sha256",
                "cleanup_receipt_sha256",
                "canonical_key_sha256",
                "locator_sha256",
                "row_sha256",
                "row_mac_sha256",
            ),
            "ck_cleanup_inventory_key_digests",
        ),
    )

    run_id_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    context_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    cleanup_receipt_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), primary_key=True)
    canonical_key_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    locator_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    locator_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


__all__ = (
    "MemoryCleanupInventoryKeyRow",
    "MemoryCleanupInventoryMaterializationRow",
    "MemoryCleanupV3ContextAuthorityRow",
    "MemoryProjectionReceiptClaimRow",
    "MemoryProjectionReceiptIdentityLinkRow",
    "MemoryProjectionResultReceiptRow",
    "MemoryProjectionTargetIdentityRow",
)
