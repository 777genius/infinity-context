"""Persistence model for the canonical transactional outbox."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.orm import Base, json_type


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
        Index(
            "ix_memory_outbox_active_reconciliation_binding",
            "aggregate_id",
            "event_type",
            "aggregate_type",
            "aggregate_version",
            postgresql_where=text("status IN ('pending', 'running', 'retry_pending')"),
            sqlite_where=text("status IN ('pending', 'running', 'retry_pending')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_version: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
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


__all__ = ("MemoryOutboxRow",)
