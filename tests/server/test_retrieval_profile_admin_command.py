from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_server.admin_retrieval_profiles import (
    retrieval_profile_lifecycle_command,
)


def test_active_reconcile_operator_reports_bounded_continuation(monkeypatch) -> None:
    calls = []

    async def reconcile_active(*, now):
        calls.append(now)
        return len(calls) > 1

    async def dispose():
        return None

    container = SimpleNamespace(
        locator_retrieval=SimpleNamespace(reconcile_active=reconcile_active),
        retrieval_profile_lifecycle=object(),
        clock=SimpleNamespace(now=lambda: datetime(2026, 8, 25, tzinfo=UTC)),
        engine=SimpleNamespace(dispose=dispose),
    )
    monkeypatch.setattr(
        "infinity_context_server.admin_retrieval_profiles.build_container",
        lambda _settings: container,
    )

    first = asyncio.run(
        retrieval_profile_lifecycle_command(
            operation="reconcile", target="active", limit=1, deadline_seconds=1
        )
    )
    second = asyncio.run(
        retrieval_profile_lifecycle_command(
            operation="reconcile", target="active", limit=1, deadline_seconds=1
        )
    )

    assert first["status"] == "pending"
    assert first["phase"] == "in_progress"
    assert second["status"] == "ok"
    assert second["phase"] == "complete"
    assert len(calls) == 2
