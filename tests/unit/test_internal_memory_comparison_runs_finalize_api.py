import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application.dto_benchmark_runs import (
    FinalizeBenchmarkRunCleanupCommand,
    FinalizeBenchmarkRunCleanupResult,
    GetBenchmarkRunLifecycleQuery,
    GetBenchmarkRunLifecycleResult,
)
from infinity_context_core.domain.errors import (
    MemoryForbiddenError,
    MemoryUnauthorizedError,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCompletionReceipt,
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from infinity_context_server.api import auth
from infinity_context_server.api.v1 import internal_memory_comparison_runs as api
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_ADMIN, ActiveServiceToken
from infinity_context_server.config import MemoryPolicyMode
from pydantic import ValidationError

RUN = "a" * 64
BINDING = "1" * 64
TARGET = "2" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"
SPACE_SLUG = "memory-comparison-managed-run"
INITIATION = "b" * 64
MANIFEST = "c" * 64
PROOF = "d" * 64
COMPLETION = "e" * 64
COMPLETED_AT = datetime(2026, 1, 1, 2, 3, 4, 5000, tzinfo=UTC)


def test_lifecycle_endpoint_returns_exact_persisted_recovery_shape() -> None:
    use_case = FakeUseCase(GetBenchmarkRunLifecycleResult(record=_lifecycle_record()))
    container = SimpleNamespace(get_benchmark_run_lifecycle=use_case)

    payload = asyncio.run(api.get_benchmark_run_lifecycle(RUN, container))

    assert use_case.last_command == GetBenchmarkRunLifecycleQuery(run_id_sha256=RUN)
    data = payload["data"]
    assert set(data) == {
        "schema_version",
        "authority",
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
        "space_id",
        "space_slug",
        "state",
        "projection_cleanup_state",
        "projection_manifest_sha256",
        "cleanup_receipt",
        "completion_receipt",
    }
    assert data["schema_version"] == "memory-comparison-run-lifecycle-response.v1"
    assert data["authority"] == "infinity_canonical"
    assert data["state"] == "cleanup_complete"
    assert data["projection_cleanup_state"] == "complete"
    assert data["projection_manifest_sha256"] == MANIFEST
    assert set(data["cleanup_receipt"]) == {
        "run_id_sha256",
        "space_id",
        "space_slug",
        "disposition",
        "projection_cleanup",
        "counts",
        "vector_delete_outbox_ids",
        "graph_delete_outbox_ids",
        "cognee_delete_outbox_ids",
        "receipt_sha256",
    }
    assert data["cleanup_receipt"]["counts"] == {
        "facts": 1,
        "documents": 2,
        "chunks": 3,
        "episodes": 4,
        "threads": 5,
        "memory_scopes": 6,
        "obsolete_upsert_jobs": 7,
        "vector_delete_jobs": 8,
        "graph_delete_jobs": 9,
        "cognee_delete_jobs": 10,
    }
    assert set(data["completion_receipt"]) == {
        "run_id_sha256",
        "space_id",
        "space_slug",
        "disposition",
        "projection_cleanup",
        "projection_manifest_sha256",
        "cleanup_initiation_receipt_sha256",
        "projection_absence_proof_sha256",
        "completed_at",
        "receipt_sha256",
    }
    assert data["completion_receipt"]["completed_at"] == "2026-01-01T02:03:04.005000Z"
    forbidden = {
        "projection_manifest_json",
        "idempotency_key_sha256",
        "registration_fingerprint_sha256",
        "cleanup_fingerprint_sha256",
        "finalization_fingerprint_sha256",
        "replayed",
    }
    assert forbidden.isdisjoint(data)
    assert forbidden.isdisjoint(data["cleanup_receipt"])
    assert forbidden.isdisjoint(data["completion_receipt"])


def test_finalize_endpoint_forwards_only_receipt_and_returns_persisted_completion() -> None:
    container = FakeContainer(replayed=True)
    payload = asyncio.run(
        api.finalize_benchmark_run_cleanup(
            RUN,
            api.FinalizeBenchmarkRunCleanupRequest(
                schema_version="memory-comparison-run-cleanup-finalize.v1",
                receipt_sha256=INITIATION,
            ),
            container,
            "finalization-secret",
        )
    )

    assert container.finalize_benchmark_run_cleanup.last_command == (
        FinalizeBenchmarkRunCleanupCommand(
            run_id_sha256=RUN,
            expected_cleanup_receipt_sha256=INITIATION,
            idempotency_key_sha256=hashlib.sha256(b"finalization-secret").hexdigest(),
        )
    )
    assert payload == {
        "data": {
            "schema_version": "memory-comparison-run-cleanup-finalize-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": RUN,
            "space_id": SPACE_ID,
            "space_slug": SPACE_SLUG,
            "state": "cleanup_complete",
            "disposition": "cleanup_complete",
            "projection_cleanup": "complete",
            "projection_manifest_sha256": MANIFEST,
            "cleanup_initiation_receipt_sha256": INITIATION,
            "projection_absence_proof_sha256": PROOF,
            "completed_at": "2026-01-01T02:03:04.005000Z",
            "receipt_sha256": COMPLETION,
            "replayed": True,
        }
    }


def test_finalize_request_rejects_caller_provider_evidence() -> None:
    with pytest.raises(ValidationError):
        api.FinalizeBenchmarkRunCleanupRequest(
            schema_version="memory-comparison-run-cleanup-finalize.v1",
            receipt_sha256=INITIATION,
            qdrant_absent=True,
        )


def test_internal_router_uses_strict_auth_for_register_and_finalize() -> None:
    expected = {
        ("POST", "/internal/memory-comparison/runs"),
        ("POST", "/internal/memory-comparison/runs/{run_id_sha256}/cleanup/finalize"),
        ("GET", "/internal/memory-comparison/runs/{run_id_sha256}/cleanup"),
    }
    observed: set[tuple[str, str]] = set()
    for route in api.router.routes:
        methods = route.methods or set()
        if auth.require_strict_admin_service_token not in {
            dependency.call for dependency in route.dependant.dependencies
        }:
            continue
        for method in methods:
            identity = (method, route.path)
            if identity in expected:
                observed.add(identity)
    assert observed == expected


def test_strict_auth_fails_closed_when_root_token_is_unconfigured() -> None:
    container = SimpleNamespace(settings=SimpleNamespace(service_token=None))

    with pytest.raises(MemoryUnauthorizedError, match="Missing or invalid"):
        asyncio.run(
            auth.require_strict_admin_service_token(
                container,
                authorization=None,
            )
        )


def test_strict_auth_accepts_unscoped_database_admin_without_root_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def active_token(_container: object, _token: str) -> ActiveServiceToken:
        return ActiveServiceToken(
            token_id="admin-1",
            space_id=None,
            memory_scope_ids=None,
            permissions=frozenset({MEMORY_PERMISSION_ADMIN}),
        )

    monkeypatch.setattr(auth, "get_active_db_token", active_token)
    container = SimpleNamespace(settings=SimpleNamespace(service_token=None))

    asyncio.run(
        auth.require_strict_admin_service_token(
            container,
            authorization="Bearer database-admin",
        )
    )


def test_strict_auth_rejects_scoped_database_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def active_token(_container: object, _token: str) -> ActiveServiceToken:
        return ActiveServiceToken(
            token_id="admin-2",
            space_id=SPACE_ID,
            memory_scope_ids=None,
            permissions=frozenset({MEMORY_PERMISSION_ADMIN}),
        )

    monkeypatch.setattr(auth, "get_active_db_token", active_token)
    container = SimpleNamespace(settings=SimpleNamespace(service_token=None))

    with pytest.raises(MemoryForbiddenError, match="unscoped endpoint"):
        asyncio.run(
            auth.require_strict_admin_service_token(
                container,
                authorization="Bearer scoped-admin",
            )
        )


def _lifecycle_record() -> BenchmarkRunRegistryRecord:
    initiation = BenchmarkCleanupReceipt(
        run_id_sha256=RUN,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        disposition="cleanup_pending",
        projection_cleanup="pending",
        counts=BenchmarkCleanupCounts(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        vector_delete_outbox_ids=(11,),
        graph_delete_outbox_ids=(12,),
        cognee_delete_outbox_ids=(13,),
        receipt_sha256=INITIATION,
    )
    completion = BenchmarkCleanupCompletionReceipt(
        run_id_sha256=RUN,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=MANIFEST,
        cleanup_initiation_receipt_sha256=INITIATION,
        projection_absence_proof_sha256=PROOF,
        completed_at=COMPLETED_AT,
        receipt_sha256=COMPLETION,
    )
    return BenchmarkRunRegistryRecord(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        idempotency_key_sha256="3" * 64,
        registration_fingerprint_sha256="4" * 64,
        state="cleanup_complete",
        projection_manifest_json={"must_not_leak": True},
        projection_manifest_sha256=MANIFEST,
        projection_cleanup_state="complete",
        cleanup_fingerprint_sha256="5" * 64,
        cleanup_receipt=initiation,
        finalization_fingerprint_sha256="6" * 64,
        completion_receipt=completion,
        completed_at=COMPLETED_AT,
        created_at=COMPLETED_AT,
        updated_at=COMPLETED_AT,
    )


class FakeUseCase:
    def __init__(self, result: object) -> None:
        self.result = result
        self.last_command: object | None = None

    async def execute(self, command: object) -> object:
        self.last_command = command
        return self.result


class FakeContainer:
    def __init__(self, *, replayed: bool) -> None:
        receipt = BenchmarkCleanupCompletionReceipt(
            run_id_sha256=RUN,
            space_id=SPACE_ID,
            space_slug=SPACE_SLUG,
            disposition="cleanup_complete",
            projection_cleanup="complete",
            projection_manifest_sha256=MANIFEST,
            cleanup_initiation_receipt_sha256=INITIATION,
            projection_absence_proof_sha256=PROOF,
            completed_at=COMPLETED_AT,
            receipt_sha256=COMPLETION,
        )
        self.settings = SimpleNamespace(policy_mode=MemoryPolicyMode.ACTIVE_CONTEXT)
        self.finalize_benchmark_run_cleanup = FakeUseCase(
            FinalizeBenchmarkRunCleanupResult(receipt=receipt, replayed=replayed)
        )
