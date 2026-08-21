from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    FinalizeBenchmarkRunCleanupCommand,
    RegisterBenchmarkRunCommand,
    SealProjectionManifestCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    CleanupBenchmarkRunUseCase,
    FinalizeBenchmarkRunCleanupUseCase,
    RegisterBenchmarkRunUseCase,
    SealProjectionManifestUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCompletionReceipt,
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkProjectionCleanupProof,
    BenchmarkRunRegistryRecord,
)

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
REGISTER_KEY = "d" * 64
CLEANUP_KEY = "e" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_registration_is_idempotent_and_rejects_fingerprint_mismatch() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    use_case = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())

    first = asyncio.run(use_case.execute(_registration()))
    replay = asyncio.run(use_case.execute(_registration()))

    assert first.created is True
    assert replay.created is False
    assert replay.record == first.record
    assert repository.add_calls == 1
    assert replay.record.run_id_sha256 == RUN

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(replace(_registration(), idempotency_key_sha256="1" * 64)))

    with pytest.raises(MemoryConflictError, match="conflicted"):
        asyncio.run(use_case.execute(replace(_registration(), run_id_sha256="f" * 64)))

    with pytest.raises(MemoryConflictError, match="conflicted"):
        asyncio.run(
            use_case.execute(replace(_registration(), infinity_target_identity_sha256="f" * 64))
        )


def test_cleanup_without_manifest_locks_once_and_replays_blocked_receipt() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    register = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    registered = asyncio.run(register.execute(_registration())).record
    command = CleanupBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=registered.space_id,
        space_slug=SLUG,
        idempotency_key_sha256=CLEANUP_KEY,
        cleanup_plan_sha256=_cleanup_plan_sha256(),
    )

    first = asyncio.run(cleanup.execute(command))
    replay = asyncio.run(cleanup.execute(command))

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert first.receipt.projection_cleanup == "blocked"
    assert first.projection_cleanup_state == "blocked"
    assert replay.projection_cleanup_state == "blocked"
    assert repository.cleanup_calls == 1
    assert repository.for_update_calls == 2

    with pytest.raises(MemoryConflictError, match="binding conflicted"):
        asyncio.run(cleanup.execute(replace(command, space_slug=f"{SLUG}-wrong")))


def test_cleanup_replay_exposes_legacy_blocked_state_without_mutating_pending_receipt() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    register = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    seal = SealProjectionManifestUseCase(uow_factory=factory, clock=FakeClock())
    cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    registered = asyncio.run(register.execute(_registration())).record
    manifest = _manifest(registered.space_id)
    asyncio.run(
        seal.execute(
            SealProjectionManifestCommand(
                run_id_sha256=RUN,
                projection_manifest_json=manifest,
                projection_manifest_sha256=_manifest_sha256(manifest),
            )
        )
    )
    command = CleanupBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=registered.space_id,
        space_slug=SLUG,
        idempotency_key_sha256=CLEANUP_KEY,
        cleanup_plan_sha256=_cleanup_plan_sha256(),
    )

    first = asyncio.run(cleanup.execute(command))
    immutable_receipt = first.receipt
    assert immutable_receipt.projection_cleanup == "pending"
    assert repository.record is not None
    repository.record = replace(
        repository.record,
        projection_manifest_json=None,
        projection_manifest_sha256=None,
        projection_cleanup_state="blocked",
    )

    replay = asyncio.run(cleanup.execute(command))

    assert replay.replayed is True
    assert replay.projection_cleanup_state == "blocked"
    assert replay.receipt is immutable_receipt
    assert replay.receipt.projection_cleanup == "pending"
    assert repository.cleanup_calls == 1


def test_manifest_seal_accepts_multi_thread_scope_and_replays_exactly() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    register = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    seal = SealProjectionManifestUseCase(uow_factory=factory, clock=FakeClock())
    cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    registered = asyncio.run(register.execute(_registration())).record
    manifest = _manifest(registered.space_id)
    command = SealProjectionManifestCommand(
        run_id_sha256=RUN,
        projection_manifest_json=manifest,
        projection_manifest_sha256=_manifest_sha256(manifest),
    )

    first = asyncio.run(seal.execute(command))
    replay = asyncio.run(seal.execute(command))

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.record == first.record
    assert repository.seal_calls == 1
    assert first.record.projection_cleanup_state == "sealed"

    changed = _manifest(registered.space_id)
    changed["scopes"][0]["qdrant"]["target_commitment_sha256"] = "9" * 64
    with pytest.raises(MemoryConflictError, match="manifest conflicted"):
        asyncio.run(
            seal.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=changed,
                    projection_manifest_sha256=_manifest_sha256(changed),
                )
            )
        )

    cleanup_result = asyncio.run(
        cleanup.execute(
            CleanupBenchmarkRunCommand(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_id=registered.space_id,
                space_slug=SLUG,
                idempotency_key_sha256=CLEANUP_KEY,
                cleanup_plan_sha256=_cleanup_plan_sha256(),
            )
        )
    )
    assert cleanup_result.receipt.projection_cleanup == "pending"
    assert repository.record.projection_cleanup_state == "pending"
    post_cleanup_replay = asyncio.run(seal.execute(command))
    assert post_cleanup_replay.replayed is True
    assert post_cleanup_replay.record.state == "cleanup_pending"
    assert repository.seal_calls == 1


def test_manifest_rejects_fact_lane_without_graphiti_evidence() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    asyncio.run(
        RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(_registration())
    )
    manifest = _manifest(repository.record.space_id)
    manifest["scopes"][0]["graphiti"] = None

    with pytest.raises(MemoryValidationError, match="graphiti evidence"):
        asyncio.run(
            SealProjectionManifestUseCase(
                uow_factory=factory,
                clock=FakeClock(),
            ).execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        )


def test_manifest_rejects_canonical_identity_reused_across_scopes() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    asyncio.run(
        RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(_registration())
    )
    manifest = _manifest(repository.record.space_id)
    manifest["scopes"][1]["chunk_ids"] = list(manifest["scopes"][0]["chunk_ids"])

    with pytest.raises(MemoryValidationError, match="globally unique"):
        asyncio.run(
            SealProjectionManifestUseCase(
                uow_factory=factory,
                clock=FakeClock(),
            ).execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        )


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("empty", "incomplete or ambiguous"),
        ("cross_lane_duplicate", "incomplete or ambiguous"),
        ("invalid_format", "graph identifiers are invalid"),
    ],
)
def test_manifest_rejects_unusable_graphiti_physical_identity(
    failure: str,
    message: str,
) -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    asyncio.run(
        RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(_registration())
    )
    manifest = _manifest(repository.record.space_id)
    graphiti = manifest["scopes"][0]["graphiti"]
    assert isinstance(graphiti, dict)
    if failure == "empty":
        for key in (
            "episode_ids",
            "entity_ids",
            "mentions_edge_ids",
            "relates_to_edge_ids",
        ):
            graphiti[key] = []
    elif failure == "cross_lane_duplicate":
        graphiti["entity_ids"] = list(graphiti["episode_ids"])
    else:
        graphiti["episode_ids"] = ["provider identity with spaces"]

    with pytest.raises(MemoryValidationError, match=message):
        asyncio.run(
            SealProjectionManifestUseCase(
                uow_factory=factory,
                clock=FakeClock(),
            ).execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        )


def test_finalization_uses_bound_internal_proof_and_replays_same_fingerprint() -> None:
    repository, factory, pending = _pending_cleanup()
    proof = FakeProjectionAbsence()
    use_case = FinalizeBenchmarkRunCleanupUseCase(
        uow_factory=factory,
        clock=FakeClock(),
        projection_absence=proof,
    )
    command = FinalizeBenchmarkRunCleanupCommand(
        run_id_sha256=RUN,
        expected_cleanup_receipt_sha256=pending.cleanup_receipt.receipt_sha256,
        expected_cleanup_plan_sha256=_cleanup_plan_sha256(),
        idempotency_key_sha256="6" * 64,
    )

    first = asyncio.run(use_case.execute(command))
    replay = asyncio.run(use_case.execute(command))

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert first.receipt.disposition == "cleanup_complete"
    assert repository.record.state == "cleanup_complete"
    assert repository.finalize_calls == 1
    assert proof.calls == 1
    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(replace(command, idempotency_key_sha256="7" * 64)))


def test_finalization_rejects_blocked_cleanup_before_provider_probe() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    registered = asyncio.run(
        RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(_registration())
    ).record
    pending = asyncio.run(
        CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(
            CleanupBenchmarkRunCommand(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_id=registered.space_id,
                space_slug=SLUG,
                idempotency_key_sha256=CLEANUP_KEY,
                cleanup_plan_sha256=_cleanup_plan_sha256(),
            )
        )
    )
    proof = FakeProjectionAbsence()
    with pytest.raises(MemoryConflictError, match="not finalizable"):
        asyncio.run(
            FinalizeBenchmarkRunCleanupUseCase(
                uow_factory=factory,
                clock=FakeClock(),
                projection_absence=proof,
            ).execute(
                FinalizeBenchmarkRunCleanupCommand(
                    RUN, pending.receipt.receipt_sha256, _cleanup_plan_sha256(), "6" * 64
                )
            )
        )
    assert proof.calls == 0


def test_finalization_rejects_false_or_stale_provider_proof() -> None:
    _, factory, pending = _pending_cleanup()
    proof = FakeProjectionAbsence(graphiti_absent=False)
    with pytest.raises(MemoryConflictError, match="absence proof conflicted"):
        asyncio.run(
            FinalizeBenchmarkRunCleanupUseCase(
                uow_factory=factory,
                clock=FakeClock(),
                projection_absence=proof,
            ).execute(
                FinalizeBenchmarkRunCleanupCommand(
                    RUN,
                    pending.cleanup_receipt.receipt_sha256,
                    _cleanup_plan_sha256(),
                    "6" * 64,
                )
            )
        )


def test_finalization_revalidates_registry_after_provider_probe() -> None:
    repository, factory, pending = _pending_cleanup()

    def mutate() -> None:
        repository.record = replace(repository.record, updated_at=datetime(2026, 1, 2, tzinfo=UTC))

    proof = FakeProjectionAbsence(after_proof=mutate)
    with pytest.raises(MemoryConflictError, match="changed during finalization"):
        asyncio.run(
            FinalizeBenchmarkRunCleanupUseCase(
                uow_factory=factory,
                clock=FakeClock(),
                projection_absence=proof,
            ).execute(
                FinalizeBenchmarkRunCleanupCommand(
                    RUN,
                    pending.cleanup_receipt.receipt_sha256,
                    _cleanup_plan_sha256(),
                    "6" * 64,
                )
            )
        )
    assert repository.finalize_calls == 0


def _pending_cleanup() -> tuple[
    FakeBenchmarkRunRepository, FakeUnitOfWorkFactory, BenchmarkRunRegistryRecord
]:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    registered = asyncio.run(
        RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(_registration())
    ).record
    manifest = _manifest(registered.space_id)
    asyncio.run(
        SealProjectionManifestUseCase(uow_factory=factory, clock=FakeClock()).execute(
            SealProjectionManifestCommand(RUN, manifest, _manifest_sha256(manifest))
        )
    )
    asyncio.run(
        CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock()).execute(
            CleanupBenchmarkRunCommand(
                RUN,
                BINDING,
                TARGET,
                registered.space_id,
                SLUG,
                CLEANUP_KEY,
                _cleanup_plan_sha256(),
            )
        )
    )
    return repository, factory, repository.record


def _registration() -> RegisterBenchmarkRunCommand:
    cleanup_plan, cleanup_plan_sha256 = cleanup_plan_pair(
        run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG
    )
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256=REGISTER_KEY,
        cleanup_plan_json=cleanup_plan,
        cleanup_plan_sha256=cleanup_plan_sha256,
    )


def _cleanup_plan_sha256() -> str:
    return cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)[1]


def _manifest(space_id: str) -> dict[str, object]:
    def scope(thread_id: str, suffix: str) -> dict[str, object]:
        return {
            "memory_scope_id": "scope-shared",
            "thread_id": thread_id,
            "chunk_ids": [f"chunk-{suffix}"],
            "fact_ids": [f"fact-{suffix}"],
            "document_ids": [f"document-{suffix}"],
            "qdrant": {
                "target_commitment_sha256": "1" * 64,
                "manifest_binding_sha256": "2" * 64,
            },
            "graphiti": {
                "target_commitment_sha256": "3" * 64,
                "manifest_binding_sha256": "4" * 64,
                "episode_ids": [f"provider-episode-{suffix}"],
                "entity_ids": [f"provider-entity-{suffix}"],
                "mentions_edge_ids": [f"provider-mentions-edge-{suffix}"],
                "relates_to_edge_ids": [f"provider-relates-edge-{suffix}"],
            },
            "cognee": {
                "disposition": "not_projected",
                "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
            },
        }

    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": space_id,
        "cleanup_plan_sha256": _cleanup_plan_sha256(),
        "scopes": [scope("thread-a", "a"), scope("thread-b", "b")],
    }


def _manifest_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeBenchmarkRunRepository:
    def __init__(self) -> None:
        self.record: BenchmarkRunRegistryRecord | None = None
        self.add_calls = 0
        self.cleanup_calls = 0
        self.seal_calls = 0
        self.for_update_calls = 0
        self.finalize_calls = 0

    async def get_by_run_id_sha256(
        self, run_id_sha256: str, *, for_update: bool = False
    ) -> BenchmarkRunRegistryRecord | None:
        if for_update:
            self.for_update_calls += 1
        return self.record if self.record and self.record.run_id_sha256 == run_id_sha256 else None

    async def get_by_space_id(self, space_id: str) -> BenchmarkRunRegistryRecord | None:
        if self.record and self.record.space_id == space_id:
            return self.record
        return None

    async def get_by_idempotency_key_sha256(
        self, idempotency_key_sha256: str
    ) -> BenchmarkRunRegistryRecord | None:
        if self.record and self.record.idempotency_key_sha256 == idempotency_key_sha256:
            return self.record
        return None

    async def add(self, record: BenchmarkRunRegistryRecord) -> None:
        self.add_calls += 1
        self.record = record

    async def begin_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        cleanup_fingerprint_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        self.cleanup_calls += 1
        projection_cleanup = "pending" if record.projection_cleanup_state == "sealed" else "blocked"
        receipt = BenchmarkCleanupReceipt(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            disposition="cleanup_pending",
            projection_cleanup=projection_cleanup,
            counts=BenchmarkCleanupCounts(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            vector_delete_outbox_ids=(),
            graph_delete_outbox_ids=(),
            cognee_delete_outbox_ids=(),
            receipt_sha256="f" * 64,
        )
        self.record = replace(
            record,
            state="cleanup_pending",
            projection_cleanup_state=projection_cleanup,
            cleanup_fingerprint_sha256=cleanup_fingerprint_sha256,
            cleanup_receipt=receipt,
            updated_at=now,
        )
        return self.record

    async def finalize_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        finalization_fingerprint_sha256: str,
        projection_absence_proof_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        self.finalize_calls += 1
        receipt = BenchmarkCleanupCompletionReceipt(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            disposition="cleanup_complete",
            projection_cleanup="complete",
            projection_manifest_sha256=record.projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            projection_absence_proof_sha256=projection_absence_proof_sha256,
            completed_at=now,
            receipt_sha256="8" * 64,
        )
        self.record = replace(
            record,
            state="cleanup_complete",
            projection_cleanup_state="complete",
            finalization_fingerprint_sha256=finalization_fingerprint_sha256,
            completion_receipt=receipt,
            completed_at=now,
            updated_at=now,
        )
        return self.record

    async def seal_projection_manifest(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        projection_manifest_json: dict[str, object],
        projection_manifest_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        self.seal_calls += 1
        self.record = replace(
            record,
            projection_manifest_json=projection_manifest_json,
            projection_manifest_sha256=projection_manifest_sha256,
            projection_cleanup_state="sealed",
            updated_at=now,
        )
        return self.record


class FakeProjectionAbsence:
    def __init__(
        self,
        *,
        graphiti_absent: bool = True,
        after_proof=None,
    ) -> None:
        self.graphiti_absent = graphiti_absent
        self.after_proof = after_proof
        self.calls = 0

    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkProjectionCleanupProof:
        self.calls += 1
        proof = BenchmarkProjectionCleanupProof(
            run_id_sha256=record.run_id_sha256,
            projection_manifest_sha256=record.projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            qdrant_absent=True,
            graphiti_absent=self.graphiti_absent,
            cognee_absent=True,
        )
        if self.after_proof is not None:
            self.after_proof()
        return proof


class FakeUnitOfWork:
    def __init__(self, repository: FakeBenchmarkRunRepository) -> None:
        self.benchmark_runs = repository
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeUnitOfWorkFactory:
    def __init__(self, repository: FakeBenchmarkRunRepository) -> None:
        self.repository = repository

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.repository)
