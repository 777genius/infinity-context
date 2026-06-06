"""Identifier generation port."""

from typing import Protocol


class IdGeneratorPort(Protocol):
    def new_id(self, prefix: str) -> str:
        """Return a new opaque id with the given prefix."""

    def projection_id(self, adapter: str, aggregate_type: str, aggregate_id: str) -> str:
        """Return deterministic projection id for adapter side effects."""
