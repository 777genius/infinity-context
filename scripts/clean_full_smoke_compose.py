"""Docker Compose command policy for the clean full-provider smoke."""

FULL_PROVIDER_COMPOSE_ARGS = (
    "--profile",
    "full",
    "up",
    "-d",
    "infinity_context_postgres",
    "infinity_context_qdrant",
    "infinity_context_neo4j",
)

__all__ = ("FULL_PROVIDER_COMPOSE_ARGS",)
