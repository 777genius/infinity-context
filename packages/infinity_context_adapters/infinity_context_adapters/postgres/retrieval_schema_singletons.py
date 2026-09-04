"""Bootstrap Retrieval singleton rows for non-Postgres runtime schemas."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def seed_retrieval_schema_singletons(connection: Connection) -> None:
    """Seed migration-0046 defaults without replacing existing singleton values."""

    statements = (
        """
        INSERT INTO memory_locator_profile_evidence_versions
            (singleton, aggregate_version, changed_at)
        SELECT TRUE, 1, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM memory_locator_profile_evidence_versions WHERE singleton = TRUE
        )
        """,
        """
        INSERT INTO memory_locator_profile_maintenance_fence
            (singleton, fence_generation, active, changed_at)
        SELECT TRUE, 0, FALSE, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM memory_locator_profile_maintenance_fence WHERE singleton = TRUE
        )
        """,
    )
    for statement in statements:
        connection.execute(text(statement))


__all__ = ("seed_retrieval_schema_singletons",)
