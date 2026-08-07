"""Explicit loader for the complete canonical SQLAlchemy model registry."""

from importlib import import_module

from sqlalchemy import MetaData

from infinity_context_adapters.postgres.orm import Base

_SCHEMA_MODULES = (
    "infinity_context_adapters.postgres.models",
    "infinity_context_adapters.postgres.feature_models",
    "infinity_context_adapters.postgres.temporal_models",
    "infinity_context_adapters.postgres.outbox_models",
)


def load_schema_metadata() -> MetaData:
    for module_name in _SCHEMA_MODULES:
        import_module(module_name)
    return Base.metadata


__all__ = ("load_schema_metadata",)
