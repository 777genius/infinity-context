import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import Response
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunResult,
    RegisterBenchmarkRunResult,
)
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from infinity_context_server.api import auth
from infinity_context_server.api.v1 import internal_memory_comparison_runs as api
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_ADMIN, ActiveServiceToken
from infinity_context_server.config import MemoryPolicyMode
from starlette.requests import Request

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"
SPACE_SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_hidden_api_returns_only_hashed_run_identity_and_pending_projection_state() -> None:
    container = FakeContainer()
    response = Response(status_code=201)
    registration = asyncio.run(
        api.register_benchmark_run(
            api.RegisterBenchmarkRunRequest(
                schema_version="memory-comparison-run-registration.v1",
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_slug=SPACE_SLUG,
            ),
            response,
            container,
            "registration-secret-key",
        )
    )
    cleanup = asyncio.run(
        api.cleanup_benchmark_run(
            RUN,
            api.CleanupBenchmarkRunRequest(
                schema_version="memory-comparison-run-cleanup.v1",
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_id=SPACE_ID,
                space_slug=SPACE_SLUG,
            ),
            container,
            "cleanup-secret-key",
        )
    )

    serialized = json.dumps((registration, cleanup), sort_keys=True)
    assert response.status_code == 201
    assert registration["data"]["authority"] == "infinity_canonical"
    assert cleanup["data"]["state"] == "cleanup_pending"
    assert cleanup["data"]["projection_cleanup"] == "pending"
    assert "verified_absent" not in serialized
    assert "cleaned" not in serialized
    assert "registration-secret-key" not in serialized
    assert "cleanup-secret-key" not in serialized
    register_command = container.register_benchmark_run.last_command
    cleanup_command = container.cleanup_benchmark_run.last_command
    assert (
        register_command.idempotency_key_sha256
        == hashlib.sha256(b"registration-secret-key").hexdigest()
    )
    assert (
        cleanup_command.idempotency_key_sha256 == hashlib.sha256(b"cleanup-secret-key").hexdigest()
    )
    assert register_command.idempotency_key_sha256 != cleanup_command.idempotency_key_sha256


def test_exact_registration_replay_returns_http_200() -> None:
    container = FakeContainer(registration_created=False)
    response = Response(status_code=201)

    payload = asyncio.run(
        api.register_benchmark_run(
            api.RegisterBenchmarkRunRequest(
                schema_version="memory-comparison-run-registration.v1",
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_slug=SPACE_SLUG,
            ),
            response,
            container,
            "registration-secret-key",
        )
    )

    assert response.status_code == 200
    assert payload["data"]["created"] is False


def test_root_configured_token_can_access_internal_benchmark_authority() -> None:
    container = SimpleNamespace(settings=SimpleNamespace(service_token="root-token"))
    asyncio.run(
        auth.require_service_token(
            container,
            _request("POST"),
            authorization="Bearer root-token",
        )
    )


def test_space_scoped_admin_db_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def active_token(_container, _token):
        return ActiveServiceToken(
            token_id="token-1",
            space_id=SPACE_ID,
            memory_scope_ids=None,
            permissions=frozenset({MEMORY_PERMISSION_ADMIN}),
        )

    monkeypatch.setattr(auth, "get_active_db_token", active_token)
    container = SimpleNamespace(settings=SimpleNamespace(service_token="root-token"))

    with pytest.raises(MemoryForbiddenError, match="unscoped endpoint"):
        asyncio.run(
            auth.require_service_token(
                container,
                _request("DELETE"),
                authorization="Bearer scoped-token",
            )
        )


def test_internal_route_requires_admin_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    async def active_token(_container, _token):
        return ActiveServiceToken(
            token_id="token-2",
            space_id=None,
            memory_scope_ids=None,
            permissions=frozenset({"memory:read"}),
        )

    monkeypatch.setattr(auth, "get_active_db_token", active_token)
    container = SimpleNamespace(settings=SimpleNamespace(service_token="root-token"))

    with pytest.raises(MemoryForbiddenError, match="required permission"):
        asyncio.run(
            auth.require_service_token(
                container,
                _request("POST"),
                authorization="Bearer read-token",
            )
        )


def _request(method: str) -> Request:
    path = "/v1/internal/memory-comparison/runs"
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
            "path_params": {},
        }
    )


class FakeUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.last_command = None

    async def execute(self, command):
        self.last_command = command
        return self.result


class FakeContainer:
    def __init__(self, *, registration_created: bool = True) -> None:
        record = BenchmarkRunRegistryRecord(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_id=SPACE_ID,
            space_slug=SPACE_SLUG,
            idempotency_key_sha256="d" * 64,
            registration_fingerprint_sha256="e" * 64,
            state="active",
            cleanup_fingerprint_sha256=None,
            cleanup_receipt=None,
            created_at=NOW,
            updated_at=NOW,
        )
        receipt = BenchmarkCleanupReceipt(
            run_id_sha256=RUN,
            space_id=SPACE_ID,
            space_slug=SPACE_SLUG,
            disposition="cleanup_pending",
            projection_cleanup="pending",
            counts=BenchmarkCleanupCounts(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            vector_delete_outbox_ids=(),
            graph_delete_outbox_ids=(),
            cognee_delete_outbox_ids=(),
            receipt_sha256="f" * 64,
        )
        self.settings = SimpleNamespace(policy_mode=MemoryPolicyMode.ACTIVE_CONTEXT)
        self.register_benchmark_run = FakeUseCase(
            RegisterBenchmarkRunResult(record=record, created=registration_created)
        )
        self.cleanup_benchmark_run = FakeUseCase(
            CleanupBenchmarkRunResult(receipt=receipt, replayed=False)
        )
