"""SQLAlchemy model for the managed benchmark canonical registry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from infinity_context_adapters.postgres.orm import Base


class MemoryComparisonBenchmarkRunRow(Base):
    __tablename__ = "memory_comparison_benchmark_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'cleanup_pending', 'cleanup_complete', 'cleanup_aborted')",
            name="ck_memory_comparison_benchmark_run_state",
        ),
        CheckConstraint(
            "((state = 'active' AND cleanup_fingerprint_sha256 IS NULL "
            "AND cleanup_receipt_json IS NULL AND finalization_fingerprint_sha256 IS NULL "
            "AND completion_receipt_json IS NULL AND completed_at IS NULL) OR "
            "(state = 'cleanup_pending' AND cleanup_fingerprint_sha256 IS NOT NULL "
            "AND cleanup_receipt_json IS NOT NULL AND finalization_fingerprint_sha256 IS NULL "
            "AND completion_receipt_json IS NULL AND completed_at IS NULL) OR "
            "(state = 'cleanup_complete' AND cleanup_fingerprint_sha256 IS NOT NULL "
            "AND cleanup_receipt_json IS NOT NULL AND finalization_fingerprint_sha256 IS NOT NULL "
            "AND completion_receipt_json IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(state = 'cleanup_aborted' AND cleanup_fingerprint_sha256 IS NOT NULL "
            "AND cleanup_receipt_json IS NOT NULL AND finalization_fingerprint_sha256 IS NOT NULL "
            "AND completion_receipt_json IS NOT NULL AND completed_at IS NOT NULL))",
            name="ck_memory_comparison_benchmark_run_cleanup_state",
        ),
        CheckConstraint(
            "((projection_manifest_json IS NULL AND projection_manifest_sha256 IS NULL) OR "
            "(projection_manifest_json IS NOT NULL AND projection_manifest_sha256 IS NOT NULL))",
            name="ck_memory_comparison_benchmark_run_manifest_coupling",
        ),
        CheckConstraint(
            "((cleanup_plan_json IS NOT NULL AND cleanup_plan_sha256 IS NOT NULL "
            "AND cleanup_plan_state = 'sealed') OR (cleanup_plan_json IS NULL "
            "AND cleanup_plan_sha256 IS NULL AND cleanup_plan_state = 'recovery_blocked'))",
            name="ck_memory_comparison_benchmark_run_cleanup_plan_coupling",
        ),
        CheckConstraint(
            "projection_cleanup_state IN ('unsealed', 'sealed', 'pending', 'blocked', "
            "'complete', 'unsealed_abort_complete')",
            name="ck_memory_comparison_benchmark_run_projection_cleanup_state",
        ),
        CheckConstraint(
            "((state = 'active' AND projection_cleanup_state = 'unsealed' "
            "AND projection_manifest_json IS NULL) OR "
            "(state = 'active' AND projection_cleanup_state = 'sealed' "
            "AND projection_manifest_json IS NOT NULL) OR "
            "(state = 'cleanup_pending' AND projection_cleanup_state = 'blocked' "
            "AND projection_manifest_json IS NULL) OR "
            "(state = 'cleanup_pending' AND projection_cleanup_state = 'pending' "
            "AND projection_manifest_json IS NOT NULL) OR "
            "(state = 'cleanup_complete' AND projection_cleanup_state = 'complete' "
            "AND projection_manifest_json IS NOT NULL) OR "
            "(state = 'cleanup_aborted' AND projection_cleanup_state = "
            "'unsealed_abort_complete' AND projection_manifest_json IS NULL))",
            name="ck_memory_comparison_benchmark_run_projection_lifecycle",
        ),
        UniqueConstraint("space_id", name="uq_memory_comparison_benchmark_run_space_id"),
        UniqueConstraint("space_slug", name="uq_memory_comparison_benchmark_run_space_slug"),
        UniqueConstraint(
            "idempotency_key_sha256",
            name="uq_memory_comparison_benchmark_run_idempotency",
        ),
    )

    run_id_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    binding_commitment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    infinity_target_identity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    space_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("memory_spaces.id"), nullable=False
    )
    space_slug: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    cleanup_plan_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    cleanup_plan_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleanup_plan_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="recovery_blocked", server_default="recovery_blocked"
    )
    projection_manifest_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )
    projection_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    projection_cleanup_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unsealed", server_default="unsealed"
    )
    cleanup_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleanup_receipt_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    finalization_fingerprint_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completion_receipt_json: Mapped[dict[str, object] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ("MemoryComparisonBenchmarkRunRow",)
