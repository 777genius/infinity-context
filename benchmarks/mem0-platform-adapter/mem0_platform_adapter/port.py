"""Narrow port owned by the compatibility adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from mem0_platform_adapter.models import EventSnapshot


class PlatformPort(Protocol):
    @property
    def configured(self) -> bool: ...

    def add(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        user_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        metadata: Mapping[str, Any],
        timestamp: int | None,
    ) -> Mapping[str, Any]: ...

    def get_event(self, event_id: str) -> EventSnapshot: ...

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        page: int,
        page_size: int,
    ) -> Mapping[str, Any]: ...

    def search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]: ...

    def delete_memories(self, *, user_id: str, run_id: str) -> bool: ...


class UnconfiguredPlatformPort:
    @property
    def configured(self) -> bool:
        return False

    def _raise(self) -> None:
        raise RuntimeError("MEM0_API_KEY is not configured")

    def add(self, **_: Any) -> Mapping[str, Any]:
        self._raise()

    def get_event(self, event_id: str) -> EventSnapshot:
        self._raise()

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        page: int,
        page_size: int,
    ) -> Mapping[str, Any]:
        self._raise()

    def search(self, **_: Any) -> Mapping[str, Any]:
        self._raise()

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        self._raise()
