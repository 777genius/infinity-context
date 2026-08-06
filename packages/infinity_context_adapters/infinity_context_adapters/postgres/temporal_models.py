"""Temporal decision persistence models split from the legacy model registry."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.models import Base, json_type


class MemoryFactTemporalDecisionRow(Base):
    __tablename__ = "memory_fact_temporal_decisions"
    __table_args__ = (
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            name="uq_memory_fact_temporal_decisions_id_scope",
        ),
        UniqueConstraint(
            "id",
            "space_id",
            "memory_scope_id",
            "source_fact_id",
            "source_fact_version",
            "target_fact_id",
            "target_fact_version",
            "effective_at",
            name="uq_memory_fact_temporal_decision_relation_identity",
        ),
        ForeignKeyConstraint(
            ["source_fact_id", "space_id", "memory_scope_id"],
            ["memory_facts.id", "memory_facts.space_id", "memory_facts.memory_scope_id"],
            name="fk_memory_fact_temporal_decision_source_scope",
        ),
        ForeignKeyConstraint(
            ["target_fact_id", "space_id", "memory_scope_id"],
            ["memory_facts.id", "memory_facts.space_id", "memory_facts.memory_scope_id"],
            name="fk_memory_fact_temporal_decision_target_scope",
        ),
        ForeignKeyConstraint(
            ["source_fact_id", "source_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_memory_fact_temporal_decision_source_version",
        ),
        ForeignKeyConstraint(
            ["target_fact_id", "target_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_memory_fact_temporal_decision_target_version",
        ),
        ForeignKeyConstraint(
            ["compensates_decision_id", "space_id", "memory_scope_id"],
            [
                "memory_fact_temporal_decisions.id",
                "memory_fact_temporal_decisions.space_id",
                "memory_fact_temporal_decisions.memory_scope_id",
            ],
            name="fk_memory_fact_temporal_decision_compensation_scope",
        ),
        UniqueConstraint(
            "space_id",
            "memory_scope_id",
            "thread_scope_key",
            "decision_type",
            "idempotency_key",
            name="uq_memory_fact_temporal_decision_idempotency",
        ),
        CheckConstraint(
            "(thread_id IS NULL AND thread_scope_key = 'global') OR "
            "(thread_id IS NOT NULL AND thread_scope_key = 'thread:' || thread_id)",
            name="ck_memory_fact_temporal_decision_thread_scope_key",
        ),
        CheckConstraint(
            "source_fact_version > 0",
            name="ck_memory_fact_temporal_decision_source_version",
        ),
        CheckConstraint(
            "target_fact_version IS NULL OR target_fact_version > 0",
            name="ck_memory_fact_temporal_decision_target_version",
        ),
        CheckConstraint(
            "(target_fact_id IS NULL) = (target_fact_version IS NULL)",
            name="ck_memory_fact_temporal_decision_target_pair",
        ),
        CheckConstraint(
            "target_fact_id IS NULL OR source_fact_id <> target_fact_id",
            name="ck_memory_fact_temporal_decision_distinct_facts",
        ),
        Index("ix_memory_fact_temporal_decisions_source", "source_fact_id", "applied_at"),
        Index("ix_memory_fact_temporal_decisions_target", "target_fact_id", "applied_at"),
        Index(
            "uq_memory_fact_temporal_decision_compensation",
            "compensates_decision_id",
            unique=True,
            sqlite_where=text("compensates_decision_id IS NOT NULL"),
            postgresql_where=text("compensates_decision_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thread_scope_key: Mapped[str] = mapped_column(String(87), nullable=False)
    source_fact_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("memory_facts.id"),
        nullable=False,
    )
    source_fact_version: Mapped[int] = mapped_column(Integer, nullable=False)
    target_fact_id: Mapped[str | None] = mapped_column(
        String(80),
        ForeignKey("memory_facts.id"),
        nullable=True,
    )
    target_fact_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_refs_json: Mapped[list[dict[str, object]]] = mapped_column(json_type(), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    compensates_decision_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    outbox_message_ids_json: Mapped[list[str]] = mapped_column(json_type(), nullable=False)


__all__ = ("MemoryFactTemporalDecisionRow",)
