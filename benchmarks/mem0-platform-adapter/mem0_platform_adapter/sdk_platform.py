"""Concrete Mem0 SDK and event API implementation of the platform port."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from mem0_platform_adapter.models import EventSnapshot
from mem0_platform_adapter.port import PlatformPort, UnconfiguredPlatformPort
from mem0_platform_adapter.runtime_pin import PLATFORM_API_ORIGIN

_POSITIVE_DELETE_ACK_MESSAGES = frozenset(
    {
        "memories deleted successfully!",
        "ok",
        "success",
    }
)


def _is_positive_delete_ack(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    message = payload.get("message")
    if not isinstance(message, str):
        return False
    normalized = " ".join(message.strip().casefold().split())
    return normalized in _POSITIVE_DELETE_ACK_MESSAGES


class Mem0SdkPlatformPort:
    def __init__(self, *, client: Any, event_client: httpx.Client) -> None:
        self._client = client
        self._event_client = event_client

    @property
    def configured(self) -> bool:
        return True

    def add(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        user_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        metadata: Mapping[str, Any],
        timestamp: int | None,
    ) -> Mapping[str, Any]:
        kwargs = {
            "user_id": user_id,
            "agent_id": agent_id,
            "run_id": run_id,
            "metadata": dict(metadata),
            "timestamp": timestamp,
        }
        supplied = {key: value for key, value in kwargs.items() if value is not None}
        return self._client.add(list(messages), **supplied)

    def get_event(self, event_id: str) -> EventSnapshot:
        response = self._event_client.get(f"/v1/event/{event_id}/")
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        return EventSnapshot(status=str(payload.get("status") or ""), results=results)

    def get_all(
        self,
        *,
        filters: Mapping[str, Any],
        page: int,
        page_size: int,
    ) -> Mapping[str, Any]:
        return self._client.get_all(
            filters=dict(filters),
            page=page,
            page_size=page_size,
        )

    def search(
        self,
        *,
        query: str,
        filters: Mapping[str, Any],
        top_k: int,
    ) -> Mapping[str, Any]:
        return self._client.search(query, filters=dict(filters), top_k=top_k)

    def delete_memories(self, *, user_id: str, run_id: str) -> bool:
        response = self._client.delete_all(
            filters={"AND": [{"user_id": user_id}, {"run_id": run_id}]},
        )
        return _is_positive_delete_ack(response)


def platform_from_environment() -> PlatformPort:
    api_key = os.getenv("MEM0_API_KEY", "").strip()
    if not api_key:
        return UnconfiguredPlatformPort()

    from mem0 import MemoryClient

    client = MemoryClient(api_key=api_key)
    event_client = httpx.Client(
        base_url=PLATFORM_API_ORIGIN,
        headers={"Authorization": f"Token {api_key}"},
        timeout=30.0,
    )
    return Mem0SdkPlatformPort(client=client, event_client=event_client)
