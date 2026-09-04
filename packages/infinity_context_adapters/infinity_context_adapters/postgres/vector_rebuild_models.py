"""Durable operation state for bounded generic vector rebuilds."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.orm import Base


class MemoryVectorRebuildOperationRow(Base):
    __tablename__ = "memory_vector_rebuild_operations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'complete')",
            name="ck_vector_rebuild_operation_status",
        ),
        CheckConstraint(
            "canonical_watermark >= 0 AND dead_event_watermark >= 0 "
            "AND cursor_watermark >= 0 AND cursor_watermark <= canonical_watermark",
            name="ck_vector_rebuild_operation_watermarks",
        ),
        CheckConstraint(
            "processed_count >= 0 AND failed_count >= 0",
            name="ck_vector_rebuild_operation_counts",
        ),
        CheckConstraint(
            "batch_size BETWEEN 1 AND 256",
            name="ck_vector_rebuild_operation_batch_size",
        ),
        Index(
            "ix_vector_rebuild_operation_scope_state",
            "space_id",
            "memory_scope_id",
            "status",
            "updated_at",
        ),
    )

    operation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    space_id: Mapped[str] = mapped_column(String(80), nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    canonical_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dead_event_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cursor_watermark: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cursor_chunk_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    processed_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ("MemoryVectorRebuildOperationRow",)
