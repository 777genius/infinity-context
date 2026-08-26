from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_core.features.context_building.public import (
    ProfileCleanup,
    RetrievalProfileIdentity,
)
from infinity_context_server import admin, admin_retrieval_profiles


def test_actual_admin_entry_point_requires_target_and_returns_safe_bounded_json(
    monkeypatch, capsys
) -> None:
    container = _Container()
    lifecycle = container.retrieval_profile_lifecycle
    monkeypatch.setattr(admin_retrieval_profiles, "build_container", lambda settings: container)
    monkeypatch.setattr(
        admin.sys,
        "argv",
        [
            "infinity_context_server.admin",
            "retrieval-profile",
            "--operation",
            "delete",
            "--target",
            "profile-a",
            "--limit",
            "4",
            "--deadline-seconds",
            "1",
        ],
    )

    admin.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "attempt_count": 1,
        "error_code": None,
        "operation": "delete",
        "phase": "complete",
        "status": "ok",
        "steps": 3,
        "target": "profile-a",
    }
    assert lifecycle.phases == ["collection_deleted", "postgres_cleaned", "complete"]
    assert container.events == ["start", "close"]


class _Container:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.retrieval_profile_lifecycle = _Lifecycle()
        self.clock = SimpleNamespace(now=lambda: datetime(2026, 8, 23, tzinfo=UTC))

    async def start_retrieval_runtime(self) -> None:
        self.events.append("start")

    async def aclose(self) -> None:
        self.events.append("close")


class _Lifecycle:
    def __init__(self):
        self.phases = []
        self.retirement = self

    async def delete(self, profile_id, *, now):
        return self._next("collection_deleted")

    async def cleanup_step(self, profile_id, *, now):
        return self._next(
            "postgres_cleaned" if self.phases[-1] == "collection_deleted" else "complete"
        )

    def _next(self, phase):
        self.phases.append(phase)
        return ProfileCleanup(
            RetrievalProfileIdentity("profile-a", "generation-a", "a" * 64, "collection_a"),
            phase,
            1,
            None,
        )
