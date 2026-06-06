"""Capture persistence ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from memo_stack_core.domain.capture import CanonicalCapture


class CaptureRepositoryPort(Protocol):
    async def create(self, capture: CanonicalCapture) -> CanonicalCapture:
        """Persist a canonical capture."""

    async def get_by_id(self, capture_id: str) -> CanonicalCapture | None:
        """Load a capture by id."""

    async def get_by_idempotency_key(
        self,
        *,
        space_id: str,
        idempotency_key: str,
    ) -> CanonicalCapture | None:
        """Load a capture by scoped idempotency key."""

    async def get_for_update(self, capture_id: str) -> CanonicalCapture | None:
        """Load a capture with a write lock when supported."""

    async def save(self, capture: CanonicalCapture) -> CanonicalCapture:
        """Persist capture status changes."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[CanonicalCapture]:
        """List safe capture diagnostics in stable cursor order."""

    async def count_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        status: str | None,
        consolidation_statuses: tuple[str, ...],
    ) -> int:
        """Count captures for ingress limits without returning raw evidence."""
