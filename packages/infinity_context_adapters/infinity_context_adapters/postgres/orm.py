"""Shared SQLAlchemy registry and provider-specific JSON type."""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def json_type(*, none_as_null: bool = False) -> JSON:
    return JSON(none_as_null=none_as_null).with_variant(
        JSONB(none_as_null=none_as_null),
        "postgresql",
    )


__all__ = ("Base", "json_type")
