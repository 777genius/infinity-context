"""Shared SQLAlchemy registry and provider-specific JSON type."""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def json_type() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


__all__ = ("Base", "json_type")
