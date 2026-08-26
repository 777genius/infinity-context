import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryValidationError,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from infinity_context_server.benchmark_projection_absence import (
    ServerBenchmarkProjectionAbsence,
)
from infinity_context_server.derived_identity_evidence import CanonicalProjectionScope
from infinity_context_server.memory_comparison_managed_projection_manifest import (
    MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
)

from tests.unit.benchmark_cleanup_plan_fixtures import cleanup_plan_pair

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"
SPACE_SLUG = "memory-comparison-managed-run"
INITIATION = "d" * 64
NOW = datetime(2026, 1, 1, tzinfo=UTC)
CLEANUP_PLAN, CLEANUP_PLAN_SHA256 = cleanup_plan_pair(
    run_id=RUN,
    binding=BINDING,
    target=TARGET,
    space_slug=SPACE_SLUG,
)


def test_server_absence_reconstructs_exact_manifest_lanes() -> None:
    evidence = FakeEvidence()
    record = _record(_manifest())

    proof = asyncio.run(ServerBenchmarkProjectionAbsence(evidence).prove_absence(record=record))

    scope = CanonicalProjectionScope(SPACE_ID, "scope-1", "thread-1")
    assert evidence.calls == [
        (
            "qdrant",
            {
                "scope": scope,
                "chunk_ids": ("chunk-1",),
                "target_commitment_sha256": "1" * 64,
                "manifest_binding_sha256": "2" * 64,
                "delete_outbox_ids": (101,),
            },
        ),
        (
            "graphiti",
            {
                "scope": scope,
                "fact_ids": ("fact-1",),
                "episode_ids": ("episode-1",),
                "entity_ids": ("entity-1",),
                "mentions_edge_ids": ("mentions-1",),
                "relates_to_edge_ids": ("relates-1",),
                "target_commitment_sha256": "3" * 64,
                "manifest_binding_sha256": "4" * 64,
                "delete_outbox_ids": (),
            },
        ),
    ]
    assert proof.run_id_sha256 == RUN
    assert proof.projection_manifest_sha256 == record.projection_manifest_sha256
    assert proof.cleanup_initiation_receipt_sha256 == INITIATION
    assert proof.qdrant_absent is True
    assert proof.graphiti_absent is True
    assert proof.cognee_absent is True


def test_server_absence_accepts_v2_canonical_episode_inventory() -> None:
    evidence = FakeEvidence()
    manifest = _manifest()
    manifest["schema_version"] = "memory-comparison-projection-manifest.v2"
    manifest["scopes"][0]["episode_ids"] = ["canonical-episode-1"]

    proof = asyncio.run(
        ServerBenchmarkProjectionAbsence(evidence).prove_absence(record=_record(manifest))
    )

    assert proof.qdrant_absent is True
    assert [lane for lane, _ in evidence.calls] == ["qdrant", "graphiti"]


def test_server_absence_rejects_non_server_cognee_policy_before_provider_calls() -> None:
    evidence = FakeEvidence()
    manifest = _manifest()
    manifest["scopes"][0]["cognee"]["policy_sha256"] = "9" * 64

    with pytest.raises(MemoryValidationError, match="cognee policy"):
        asyncio.run(
            ServerBenchmarkProjectionAbsence(evidence).prove_absence(record=_record(manifest))
        )

    assert evidence.calls == []


def test_server_absence_requires_cleanup_initiation_receipt() -> None:
    evidence = FakeEvidence()
    record = _record(_manifest(), include_cleanup_receipt=False)

    with pytest.raises(MemoryConflictError, match="initiation receipt"):
        asyncio.run(ServerBenchmarkProjectionAbsence(evidence).prove_absence(record=record))

    assert evidence.calls == []


class FakeEvidence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def delete_qdrant_two_pass(self, **kwargs: object) -> object:
        self.calls.append(("qdrant", kwargs))
        absent = SimpleNamespace(verified_absent=True)
        return SimpleNamespace(first_pass=absent, second_pass=absent)

    async def delete_graphiti_two_pass(self, **kwargs: object) -> object:
        self.calls.append(("graphiti", kwargs))
        return SimpleNamespace(evidence=SimpleNamespace(verified_absent=True))


def _record(
    manifest: dict[str, object],
    *,
    include_cleanup_receipt: bool = True,
) -> BenchmarkRunRegistryRecord:
    cleanup_receipt = None
    if include_cleanup_receipt:
        cleanup_receipt = BenchmarkCleanupReceipt(
            run_id_sha256=RUN,
            space_id=SPACE_ID,
            space_slug=SPACE_SLUG,
            disposition="cleanup_pending",
            projection_cleanup="pending",
            counts=BenchmarkCleanupCounts(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            vector_delete_outbox_ids=(101,),
            graph_delete_outbox_ids=(),
            cognee_delete_outbox_ids=(),
            receipt_sha256=INITIATION,
        )
    return BenchmarkRunRegistryRecord(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        idempotency_key_sha256="e" * 64,
        registration_fingerprint_sha256="f" * 64,
        state="cleanup_pending",
        cleanup_plan_json=CLEANUP_PLAN,
        cleanup_plan_sha256=CLEANUP_PLAN_SHA256,
        cleanup_plan_state="sealed",
        projection_manifest_json=manifest,
        projection_manifest_sha256=_sha256(manifest),
        projection_cleanup_state="pending",
        cleanup_fingerprint_sha256="6" * 64,
        cleanup_receipt=cleanup_receipt,
        finalization_fingerprint_sha256=None,
        completion_receipt=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": SPACE_ID,
        "cleanup_plan_sha256": CLEANUP_PLAN_SHA256,
        "scopes": [
            {
                "memory_scope_id": "scope-1",
                "thread_id": "thread-1",
                "chunk_ids": ["chunk-1"],
                "fact_ids": ["fact-1"],
                "document_ids": ["document-1"],
                "qdrant": {
                    "target_commitment_sha256": "1" * 64,
                    "manifest_binding_sha256": "2" * 64,
                },
                "graphiti": {
                    "target_commitment_sha256": "3" * 64,
                    "manifest_binding_sha256": "4" * 64,
                    "episode_ids": ["episode-1"],
                    "entity_ids": ["entity-1"],
                    "mentions_edge_ids": ["mentions-1"],
                    "relates_to_edge_ids": ["relates-1"],
                },
                "cognee": {
                    "disposition": "not_projected",
                    "policy_sha256": MANAGED_COGNEE_NOT_PROJECTED_POLICY_SHA256,
                },
            }
        ],
    }


def _sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
