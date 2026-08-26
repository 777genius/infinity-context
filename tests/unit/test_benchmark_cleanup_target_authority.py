import asyncio

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from fastapi import Response
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_server.api.v1 import internal_memory_comparison_runs as api
from infinity_context_server.config import Settings
from pydantic import ValidationError

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-target-authority"


class _NeverRegister:
    calls = 0

    async def execute(self, _command):
        self.calls += 1
        raise AssertionError("registration must not execute without target authority")


class _Container:
    def __init__(self, *, qdrant_enabled: bool, graphiti_enabled: bool) -> None:
        self.settings = Settings(
            qdrant_enabled=qdrant_enabled,
            graphiti_enabled=graphiti_enabled,
        )
        self.register_benchmark_run = _NeverRegister()


def test_target_authority_request_rejects_unused_binding_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        api.CleanupTargetAuthorityRequest.model_validate(
            {
                "schema_version": ("memory-comparison-cleanup-target-authority-request.v1"),
                "infinity_target_identity_sha256": TARGET,
                "run_id_sha256": RUN,
            }
        )


def _request() -> api.RegisterBenchmarkRunRequest:
    plan, plan_sha256 = cleanup_plan_pair(
        run_id=RUN,
        binding=BINDING,
        target=TARGET,
        space_slug=SLUG,
    )
    return api.RegisterBenchmarkRunRequest(
        schema_version="memory-comparison-run-registration.v2",
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        cleanup_plan=plan,
        cleanup_plan_sha256=plan_sha256,
    )


@pytest.mark.parametrize(
    ("qdrant_enabled", "graphiti_enabled"),
    [(False, True), (True, False), (False, False)],
)
def test_registration_fails_before_db_mutation_when_a_required_lane_is_disabled(
    qdrant_enabled: bool,
    graphiti_enabled: bool,
) -> None:
    container = _Container(
        qdrant_enabled=qdrant_enabled,
        graphiti_enabled=graphiti_enabled,
    )

    with pytest.raises(MemoryConflictError, match="requires Qdrant and Graphiti"):
        asyncio.run(
            api.register_benchmark_run(
                _request(),
                Response(status_code=201),
                container,
                "target-authority-idempotency",
            )
        )

    assert container.register_benchmark_run.calls == 0
