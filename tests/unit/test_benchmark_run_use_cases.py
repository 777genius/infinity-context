import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    RegisterBenchmarkRunCommand,
    SealProjectionManifestCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    CleanupBenchmarkRunUseCase,
    RegisterBenchmarkRunUseCase,
    SealProjectionManifestUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
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

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(replace(_registration(), run_id_sha256="f" * 64)))

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
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
    changed["scopes"][0]["cognee"]["policy_sha256"] = "9" * 64
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


def _registration() -> RegisterBenchmarkRunCommand:
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256=REGISTER_KEY,
    )


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
                "policy_sha256": "5" * 64,
            },
        }

    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": space_id,
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

    async def get_by_run_id_sha256(
        self, run_id_sha256: str, *, for_update: bool = False
    ) -> BenchmarkRunRegistryRecord | None:
        if for_update:
            self.for_update_calls += 1
        return self.record if self.record and self.record.run_id_sha256 == run_id_sha256 else None

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
