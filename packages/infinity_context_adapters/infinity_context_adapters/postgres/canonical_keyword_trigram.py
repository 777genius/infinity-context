"""PostgreSQL access path for canonical keyword substring retrieval."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

CANONICAL_KEYWORD_TRIGRAM_INDEX = "ix_memory_chunks_canonical_keyword_trgm"
CANONICAL_KEYWORD_TRIGRAM_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    f"""
    CREATE INDEX IF NOT EXISTS {CANONICAL_KEYWORD_TRIGRAM_INDEX}
    ON memory_chunks USING GIN (normalized_text gin_trgm_ops)
    WHERE status = 'active' AND classification <> 'restricted'
    """,
)


def ensure_canonical_keyword_trigram_access_path(connection: Connection) -> None:
    """Install the PostgreSQL-only derived access path after canonical tables exist."""
    if connection.dialect.name != "postgresql":
        return
    for statement in CANONICAL_KEYWORD_TRIGRAM_STATEMENTS:
        connection.execute(text(statement))


__all__ = [
    "CANONICAL_KEYWORD_TRIGRAM_INDEX",
    "CANONICAL_KEYWORD_TRIGRAM_STATEMENTS",
    "ensure_canonical_keyword_trigram_access_path",
]
