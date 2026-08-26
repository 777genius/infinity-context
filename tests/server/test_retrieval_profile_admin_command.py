from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_server.admin_retrieval_profiles import (
    retrieval_profile_lifecycle_command,
)
from infinity_context_server.retrieval_profile_composition import ActiveReconciliationResult


def test_active_reconcile_operator_reports_bounded_continuation(monkeypatch) -> None:
    calls = []
    lifecycle_calls = []

    async def reconcile_active(*, now):
        calls.append(now)
        complete = len(calls) > 1
        return ActiveReconciliationResult(
            complete,
            complete,
            "runtime-a" if complete else None,
            "generation-a" if complete else None,
            "a" * 64 if complete else None,
            "b" * 64 if complete else None,
            "applied" if complete else "skipped",
        )

    async def dispose():
        return None

    async def start_retrieval_runtime():
        lifecycle_calls.append("register")

    async def aclose():
        lifecycle_calls.append("retire")

    container = SimpleNamespace(
        locator_retrieval=SimpleNamespace(reconcile_active=reconcile_active),
        retrieval_profile_lifecycle=object(),
        clock=SimpleNamespace(now=lambda: datetime(2026, 8, 25, tzinfo=UTC)),
        engine=SimpleNamespace(dispose=dispose),
        start_retrieval_runtime=start_retrieval_runtime,
        aclose=aclose,
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
    assert first["renewed"] is False
    assert first["reconciliation_outcome"] == "skipped"
    assert "provenance" not in first
    assert second["status"] == "ok"
    assert second["phase"] == "complete"
    assert second["renewed"] is True
    assert second["reconciliation_outcome"] == "applied"
    assert second["provenance"] == {
        "runtime_instance_id": "runtime-a",
        "runtime_generation": "generation-a",
        "release_identity_sha256": "a" * 64,
        "lifecycle_identity_sha256": "b" * 64,
    }
    assert len(calls) == 2
    assert lifecycle_calls == ["register", "retire", "register", "retire"]
