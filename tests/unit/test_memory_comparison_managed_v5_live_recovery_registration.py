from __future__ import annotations

from datetime import UTC, datetime

import httpx
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
)
from infinity_context_server.memory_comparison_managed_v5_live_recovery_registration import (
    register_and_observe_managed_v5,
)
from memory_comparison_managed_benchmark_registry_test_support import (
    BINDING,
    RUN,
    SPACE_SLUG,
    _config,
    _lifecycle,
    _plan,
    _registration,
)


class _Journal:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


def test_registration_fresh_active_get_relinquishes_without_close_refusal() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        return httpx.Response(
            201 if request.method == "POST" else 200,
            json=_registration() if request.method == "POST" else _lifecycle(),
        )

    config = _config(httpx.MockTransport(handler))
    registry = ManagedBenchmarkRegistryHttpAdapter(config)
    journal = _Journal()
    registration = register_and_observe_managed_v5(
        registry,
        cleanup_plan=_plan(),
        recovery_authority=object(),
        recovery_journal=journal,
        registry_config=config,
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        space_slug=SPACE_SLUG,
        clock=lambda: datetime(2026, 8, 9, tzinfo=UTC),
    )

    assert registration.cleanup_plan_sha256 == _plan().sha256
    assert requests == ["POST", "GET"]
    assert journal.calls[0]["recorded_at"] == "2026-08-09T00:00:00.000000Z"
    registry.relinquish_recovery_authority(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=config.target_identity_sha256,
        space_slug=SPACE_SLUG,
        cleanup_plan_sha256=_plan().sha256,
    )
