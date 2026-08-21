"""SQLAlchemy parity for immutable strict-v4 preparation authorities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infinity_context_adapters.postgres.orm import Base, json_type


class MemoryComparisonStrictV4PreparationRow(Base):
    __tablename__ = "memory_comparison_strict_v4_preparations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id_sha256", "context_sha256", "authority_terminal_sha256"],
            [
                "memory_cleanup_v3_context_authorities.run_id_sha256",
                "memory_cleanup_v3_context_authorities.context_sha256",
                "memory_cleanup_v3_context_authorities.authority_terminal_sha256",
            ],
            name="fk_strict_v4_preparation_context_authority",
        ),
        UniqueConstraint("context_sha256", name="uq_strict_v4_preparation_context"),
        CheckConstraint(
            "provider_calls = 0 AND paid_go_ready = FALSE",
            name="ck_strict_v4_preparation_provider_free",
        ),
        CheckConstraint(
            "(state = 'sealed' AND closed_at IS NULL) OR "
            "(state = 'closed' AND closed_at IS NOT NULL AND closed_at >= sealed_at)",
            name="ck_strict_v4_preparation_lifecycle",
        ),
        CheckConstraint(
            "preparation_receipt_json ? 'prepared_at' AND "
            "preparation_receipt_json ? 'registered_at' AND "
            "writer_authority_json ? 'sealed_at' AND "
            "sealed_at >= (preparation_receipt_json->>'prepared_at')::timestamptz AND "
            "(preparation_receipt_json->>'prepared_at')::timestamptz >= "
            "(preparation_receipt_json->>'registered_at')::timestamptz AND "
            "sealed_at >= (preparation_receipt_json->>'registered_at')::timestamptz AND "
            "(writer_authority_json->>'sealed_at')::timestamptz = sealed_at",
            name="ck_strict_v4_preparation_temporal_binding",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "run_id_sha256 ~ '^[0-9a-f]{64}$' "
            "AND context_sha256 ~ '^[0-9a-f]{64}$' "
            "AND authority_terminal_sha256 ~ '^[0-9a-f]{64}$' "
            "AND preparation_receipt_sha256 ~ '^[0-9a-f]{64}$' "
            "AND preparation_receipt_mac_sha256 ~ '^[0-9a-f]{64}$' "
            "AND writer_authority_sha256 ~ '^[0-9a-f]{64}$' "
            "AND writer_authority_mac_sha256 ~ '^[0-9a-f]{64}$' "
            "AND registration_sha256 ~ '^[0-9a-f]{64}$' "
            "AND registration_mac_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_strict_v4_preparation_digests",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "preparation_receipt_json->>'schema_version' "
            "= 'memory-comparison-strict-v4-full-preparation.v1' "
            "AND preparation_receipt_json->>'run_id_sha256' = run_id_sha256 "
            "AND preparation_receipt_json#>>'{a2_context,context_sha256}' = context_sha256 "
            "AND preparation_receipt_json#>>'{a2_authority,terminal_commitment_sha256}' "
            "= authority_terminal_sha256 "
            "AND preparation_receipt_json->>'receipt_sha256' "
            "= preparation_receipt_sha256 "
            "AND preparation_receipt_json->>'receipt_mac_sha256' "
            "= preparation_receipt_mac_sha256 "
            "AND preparation_receipt_json->>'registration_sha256' = registration_sha256 "
            "AND preparation_receipt_json->>'registration_mac_sha256' "
            "= registration_mac_sha256 "
            "AND preparation_receipt_json->>'provider_calls' = '0' "
            "AND preparation_receipt_json->>'paid_go_ready' = 'false'",
            name="ck_strict_v4_preparation_receipt_binding",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "writer_authority_json->>'schema_version' "
            "= 'memory-comparison-strict-v4-writer-authority.v1' "
            "AND writer_authority_json->>'run_id_sha256' = run_id_sha256 "
            "AND writer_authority_json->>'context_sha256' = context_sha256 "
            "AND writer_authority_json->>'authority_terminal_sha256' "
            "= authority_terminal_sha256 "
            "AND writer_authority_json->>'preparation_receipt_sha256' "
            "= preparation_receipt_sha256 "
            "AND writer_authority_json->>'preparation_receipt_mac_sha256' "
            "= preparation_receipt_mac_sha256 "
            "AND writer_authority_json->>'registration_sha256' = registration_sha256 "
            "AND writer_authority_json->>'registration_mac_sha256' "
            "= registration_mac_sha256 "
            "AND writer_authority_json->>'a2_terminal_commitment_sha256' "
            "= authority_terminal_sha256 "
            "AND writer_authority_json->>'expected_index_terminal_sha256' "
            "= authority_terminal_sha256 "
            "AND writer_authority_json->>'provider_calls' = '0' "
            "AND writer_authority_json->>'paid_go_ready' = 'false' "
            "AND writer_authority_json->>'writer_authority_sha256' "
            "= writer_authority_sha256 "
            "AND writer_authority_json->>'writer_authority_mac_sha256' "
            "= writer_authority_mac_sha256",
            name="ck_strict_v4_writer_authority_binding",
        ).ddl_if(dialect="postgresql"),
    )

    run_id_sha256: Mapped[str] = mapped_column(
        String(64), ForeignKey("memory_comparison_benchmark_runs.run_id_sha256"), primary_key=True
    )
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_terminal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preparation_receipt_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    preparation_receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    preparation_receipt_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    writer_authority_json: Mapped[dict[str, object]] = mapped_column(json_type(), nullable=False)
    writer_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    writer_authority_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_mac_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_go_ready: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ("MemoryComparisonStrictV4PreparationRow",)
