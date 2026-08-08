"""Relational backstops for canonical MemoryFact value-object shapes."""

from __future__ import annotations

from sqlalchemy import CheckConstraint


def memory_fact_storage_constraints() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            "temporal_kind IN ('state', 'event', 'timeless')",
            name="ck_memory_facts_temporal_kind",
        ),
        CheckConstraint(
            "(temporal_kind = 'state' AND occurred_from IS NULL AND occurred_to IS NULL) OR "
            "(temporal_kind = 'event' AND valid_from IS NULL AND valid_to IS NULL "
            "AND occurred_from IS NOT NULL) OR "
            "(temporal_kind = 'timeless' AND valid_from IS NULL AND valid_to IS NULL "
            "AND occurred_from IS NULL AND occurred_to IS NULL)",
            name="ck_memory_facts_temporal_shape",
        ),
        CheckConstraint(
            "valid_to IS NULL OR (valid_from IS NOT NULL AND valid_to > valid_from)",
            name="ck_memory_facts_validity_order",
        ),
        CheckConstraint(
            "occurred_to IS NULL OR (occurred_from IS NOT NULL AND occurred_to > occurred_from)",
            name="ck_memory_facts_occurrence_order",
        ),
        CheckConstraint(
            "(last_confirmed_at IS NULL) = (confirmation_basis IS NULL)",
            name="ck_memory_facts_confirmation_pair",
        ),
        CheckConstraint(
            "purge_after IS NULL OR expires_at IS NULL OR purge_after >= expires_at",
            name="ck_memory_facts_retention_order",
        ),
        CheckConstraint(
            "code_scope_id IS NULL OR repository_id IS NOT NULL",
            name="ck_memory_facts_code_scope_pair",
        ),
        CheckConstraint(
            "epistemic_mode IN ('world_claim', 'perspective', 'hypothesis')",
            name="ck_memory_facts_epistemic_mode",
        ),
        CheckConstraint(
            "(epistemic_mode = 'perspective' AND perspective_subject IS NOT NULL) OR "
            "(epistemic_mode <> 'perspective' AND perspective_subject IS NULL)",
            name="ck_memory_facts_perspective_subject",
        ),
    )


__all__ = ("memory_fact_storage_constraints",)
