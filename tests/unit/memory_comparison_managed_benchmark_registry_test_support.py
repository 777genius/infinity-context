from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from infinity_context_server.memory_comparison_managed_benchmark_registry_http import (
    ManagedBenchmarkRegistryHttpAdapter,
    ManagedBenchmarkRegistryHttpConfig,
    ManagedBenchmarkRegistryHttpError,
)
from infinity_context_server.memory_comparison_managed_preflight import (
    managed_backend_target_identity_sha256,
)

BASE_URL = "http://127.0.0.1:7788"
RUN = "a" * 64
BINDING = "b" * 64
SPACE_ID = "benchmark-space-1"
SPACE_SLUG = "memory-comparison-managed-run"
TOKEN = "private-admin-token"


class _MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class _DeadlineAdvancingStream(httpx.SyncByteStream):
    def __init__(self, body: bytes, clock: _MutableClock) -> None:
        self._body = body
        self._clock = clock

    def __iter__(self) -> Iterator[bytes]:
        midpoint = len(self._body) // 2
        yield self._body[:midpoint]
        self._clock.value += timedelta(minutes=10)
        yield self._body[midpoint:]


class _TruncatedCommittedStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b'{"data":'
        raise RuntimeError(f"committed response leaked {TOKEN}")


def _target(base_url: str = BASE_URL) -> str:
    return managed_backend_target_identity_sha256(
        backend_role="infinity-context",
        base_url=base_url,
    )


def _config(
    transport: httpx.MockTransport,
    *,
    expired: bool = False,
    base_url: str = BASE_URL,
    clock=None,
):
    now = datetime.now(UTC)
    benchmark_deadline = now + timedelta(minutes=-1 if expired else 5)
    return ManagedBenchmarkRegistryHttpConfig(
        base_url=base_url,
        admin_bearer_token=TOKEN,
        target_identity_sha256=_target(base_url),
        timeout_seconds=30,
        benchmark_deadline=benchmark_deadline,
        cleanup_recovery_timeout_seconds=600,
        transport=transport,
        **({"clock": clock} if clock is not None else {}),
    )


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": _target(),
        "space_id": SPACE_ID,
        "scopes": [],
    }


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _close_with_cleanup_required(adapter: ManagedBenchmarkRegistryHttpAdapter) -> None:
    with pytest.raises(ManagedBenchmarkRegistryHttpError) as caught:
        adapter.close()
    assert caught.value.code == "managed_benchmark_registry_cleanup_required"
    assert adapter.cleanup_required is True
    assert adapter._client.is_closed is False


def _registration(
    *,
    created: bool = True,
    binding: str = BINDING,
    target: str | None = None,
    state: str = "active",
) -> dict[str, object]:
    return {
        "data": {
            "schema_version": "memory-comparison-run-registration-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": RUN,
            "binding_commitment_sha256": binding,
            "infinity_target_identity_sha256": target or _target(),
            "space_id": SPACE_ID,
            "space_slug": SPACE_SLUG,
            "state": state,
            "created": created,
        }
    }


def _seal(manifest_sha256: str, *, replayed: bool = False) -> dict[str, object]:
    return {
        "data": {
            "schema_version": "memory-comparison-projection-manifest-seal-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": RUN,
            "binding_commitment_sha256": BINDING,
            "infinity_target_identity_sha256": _target(),
            "projection_manifest_sha256": manifest_sha256,
            "state": "active",
            "projection_cleanup_state": "sealed",
            "replayed": replayed,
        }
    }


def _cleanup(
    *,
    receipt_sha256: str | None = None,
    projection_cleanup: str = "pending",
    replayed: bool = False,
) -> dict[str, object]:
    counts = {
        "facts": 2,
        "documents": 1,
        "chunks": 3,
        "episodes": 0,
        "threads": 1,
        "memory_scopes": 1,
        "obsolete_upsert_jobs": 2,
        "vector_delete_jobs": 1,
        "graph_delete_jobs": 1,
        "cognee_delete_jobs": 0,
    }
    material = {
        "run_id_sha256": RUN,
        "space_id": SPACE_ID,
        "space_slug": SPACE_SLUG,
        "disposition": "cleanup_pending",
        "projection_cleanup": projection_cleanup,
        "counts": counts,
        "vector_delete_outbox_ids": [101],
        "graph_delete_outbox_ids": [201],
        "cognee_delete_outbox_ids": [],
    }
    return {
        "data": {
            "schema_version": "memory-comparison-run-cleanup-response.v1",
            "authority": "infinity_canonical",
            **material,
            "state": "cleanup_pending",
            "receipt_sha256": receipt_sha256 or _digest(material),
            "replayed": replayed,
        }
    }


PROJECTION_ABSENCE_PROOF = "c" * 64
COMPLETED_AT = "2026-08-02T04:05:06.123456Z"


def _finalize(
    projection_manifest_sha256: str,
    *,
    cleanup_initiation_receipt_sha256: str | None = None,
    projection_absence_proof_sha256: str = PROJECTION_ABSENCE_PROOF,
    receipt_sha256: str | None = None,
    completed_at: str = COMPLETED_AT,
    replayed: bool = False,
) -> dict[str, object]:
    initiation = cleanup_initiation_receipt_sha256 or str(_cleanup()["data"]["receipt_sha256"])
    material = {
        "run_id_sha256": RUN,
        "space_id": SPACE_ID,
        "space_slug": SPACE_SLUG,
        "disposition": "cleanup_complete",
        "projection_cleanup": "complete",
        "projection_manifest_sha256": projection_manifest_sha256,
        "cleanup_initiation_receipt_sha256": initiation,
        "projection_absence_proof_sha256": projection_absence_proof_sha256,
        "completed_at": completed_at,
    }
    return {
        "data": {
            "schema_version": "memory-comparison-run-cleanup-finalize-response.v1",
            "authority": "infinity_canonical",
            **material,
            "state": "cleanup_complete",
            "receipt_sha256": receipt_sha256 or _digest(material),
            "replayed": replayed,
        }
    }


def _persisted_cleanup(
    *,
    projection_cleanup: str = "pending",
    receipt_sha256: str | None = None,
) -> dict[str, object]:
    value = dict(
        _cleanup(
            projection_cleanup=projection_cleanup,
            receipt_sha256=receipt_sha256,
        )["data"]
    )
    for key in ("schema_version", "authority", "state", "replayed"):
        value.pop(key)
    return value


def _persisted_completion(
    projection_manifest_sha256: str,
    *,
    cleanup_initiation_receipt_sha256: str | None = None,
    receipt_sha256: str | None = None,
) -> dict[str, object]:
    value = dict(
        _finalize(
            projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=cleanup_initiation_receipt_sha256,
            receipt_sha256=receipt_sha256,
        )["data"]
    )
    for key in ("schema_version", "authority", "state", "replayed"):
        value.pop(key)
    return value


def _lifecycle(
    *,
    state: str = "active",
    projection_cleanup_state: str = "unsealed",
    projection_manifest_sha256: str | None = None,
    cleanup_receipt: dict[str, object] | None = None,
    completion_receipt: dict[str, object] | None = None,
    binding: str = BINDING,
    target: str | None = None,
) -> dict[str, object]:
    return {
        "data": {
            "schema_version": "memory-comparison-run-lifecycle-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": RUN,
            "binding_commitment_sha256": binding,
            "infinity_target_identity_sha256": target or _target(),
            "space_id": SPACE_ID,
            "space_slug": SPACE_SLUG,
            "state": state,
            "projection_cleanup_state": projection_cleanup_state,
            "projection_manifest_sha256": projection_manifest_sha256,
            "cleanup_receipt": cleanup_receipt,
            "completion_receipt": completion_receipt,
        }
    }
