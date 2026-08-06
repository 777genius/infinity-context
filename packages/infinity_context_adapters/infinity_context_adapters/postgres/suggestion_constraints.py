"""Canonical pending-suggestion deduplication indexes."""

from sqlalchemy import Index, text


def pending_suggestion_fingerprint_indexes() -> tuple[Index, Index]:
    return (
        Index(
            "uq_pending_suggestion_fingerprint_no_target",
            "space_id",
            "memory_scope_id",
            "operation",
            "candidate_fingerprint",
            unique=True,
            sqlite_where=text(
                "status = 'pending' AND candidate_fingerprint IS NOT NULL "
                "AND target_fact_id IS NULL"
            ),
            postgresql_where=text(
                "status = 'pending' AND candidate_fingerprint IS NOT NULL "
                "AND target_fact_id IS NULL"
            ),
        ),
        Index(
            "uq_pending_suggestion_fingerprint_target",
            "space_id",
            "memory_scope_id",
            "operation",
            "target_fact_id",
            "candidate_fingerprint",
            unique=True,
            sqlite_where=text(
                "status = 'pending' AND candidate_fingerprint IS NOT NULL "
                "AND target_fact_id IS NOT NULL"
            ),
            postgresql_where=text(
                "status = 'pending' AND candidate_fingerprint IS NOT NULL "
                "AND target_fact_id IS NOT NULL"
            ),
        ),
    )


__all__ = ("pending_suggestion_fingerprint_indexes",)
