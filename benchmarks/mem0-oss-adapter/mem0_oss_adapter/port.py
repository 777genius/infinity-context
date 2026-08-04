"""Small provider port owned by the OSS compatibility adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol


class OssPort(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def extraction_mode(self) -> Literal["raw_passthrough", "subscription_llm"]: ...

    def add(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        user_id: str,
        agent_id: str | None,
        run_id: str,
        metadata: Mapping[str, Any],
        timestamp: int,
        mode_override: Literal["raw_passthrough", "subscription_llm"] | None = None,
    ) -> Mapping[str, Any]: ...

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        limit: int,
    ) -> Mapping[str, Any]: ...

    def search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]: ...

    def delete_memories(self, *, user_id: str, run_id: str) -> bool: ...

    def delete_source_memories(
        self,
        *,
        user_id: str,
        run_id: str,
        source_id: str,
        source_sha256: str,
    ) -> bool: ...


class UnconfiguredOssPort:
    @property
    def configured(self) -> bool:
        return False

    @property
    def extraction_mode(self) -> Literal["raw_passthrough"]:
        return "raw_passthrough"

    def _raise(self) -> None:
        raise RuntimeError("Mem0 OSS runtime is not configured")

    def add(self, **_: Any) -> Mapping[str, Any]:
        self._raise()

    def get_all(self, **_: Any) -> Mapping[str, Any]:
        self._raise()

    def search(self, **_: Any) -> Mapping[str, Any]:
        self._raise()

    def delete_memories(self, **_: Any) -> bool:
        self._raise()

    def delete_source_memories(self, **_: Any) -> bool:
        self._raise()
