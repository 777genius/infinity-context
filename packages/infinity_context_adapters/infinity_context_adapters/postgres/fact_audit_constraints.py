"""Database backstops for tenant-bound fact audit records."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, and_


def memory_fact_relation_tenant_constraints() -> tuple[ForeignKeyConstraint, ...]:
    return (
        ForeignKeyConstraint(
            ["source_fact_id", "space_id", "memory_scope_id", "thread_scope_key"],
            [
                "memory_facts.id",
                "memory_facts.space_id",
                "memory_facts.memory_scope_id",
                "memory_facts.thread_scope_key",
            ],
            name="fk_memory_fact_relation_source_scope",
        ),
        ForeignKeyConstraint(
            ["target_fact_id", "space_id", "memory_scope_id", "thread_scope_key"],
            [
                "memory_facts.id",
                "memory_facts.space_id",
                "memory_facts.memory_scope_id",
                "memory_facts.thread_scope_key",
            ],
            name="fk_memory_fact_relation_target_scope",
        ),
        ForeignKeyConstraint(
            [
                "temporal_decision_id",
                "space_id",
                "memory_scope_id",
                "thread_scope_key",
                "source_fact_id",
                "source_fact_version",
                "target_fact_id",
                "target_fact_version",
                "valid_from",
            ],
            [
                "memory_fact_temporal_decisions.id",
                "memory_fact_temporal_decisions.space_id",
                "memory_fact_temporal_decisions.memory_scope_id",
                "memory_fact_temporal_decisions.thread_scope_key",
                "memory_fact_temporal_decisions.source_fact_id",
                "memory_fact_temporal_decisions.source_fact_version",
                "memory_fact_temporal_decisions.target_fact_id",
                "memory_fact_temporal_decisions.target_fact_version",
                "memory_fact_temporal_decisions.effective_at",
            ],
            name="fk_memory_fact_relation_temporal_decision_identity",
        ),
        ForeignKeyConstraint(
            ["source_fact_id", "source_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_memory_fact_relation_source_version",
        ),
        ForeignKeyConstraint(
            ["target_fact_id", "target_fact_version"],
            ["memory_fact_versions.fact_id", "memory_fact_versions.version"],
            name="fk_memory_fact_relation_target_version",
        ),
    )


def active_predecessor_index(relation_type, status, temporal_decision_id) -> Index:
    predicate = and_(
        relation_type == "supersedes",
        status == "active",
        temporal_decision_id.is_not(None),
    )
    return Index(
        "uq_memory_fact_single_active_predecessor",
        "source_fact_id",
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )


def memory_fact_relation_version_constraint() -> CheckConstraint:
    return CheckConstraint(
        "temporal_decision_id IS NULL OR "
        "(relation_type = 'supersedes' AND valid_from IS NOT NULL "
        "AND source_fact_version IS NOT NULL AND target_fact_version IS NOT NULL)",
        name="ck_memory_fact_relation_decision_versions",
    )


__all__ = (
    "active_predecessor_index",
    "memory_fact_relation_tenant_constraints",
    "memory_fact_relation_version_constraint",
)
