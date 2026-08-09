import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.application.dto_benchmark_runs import (
    FinalizeUnsealedBenchmarkAbortCommand,
)
from infinity_context_core.application.use_cases.benchmark_unsealed_abort import (
    FinalizeUnsealedBenchmarkAbortUseCase,
    _fingerprint,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
    GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
    GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
    QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
    QDRANT_SCOPE_MAPPING_POLICY_SHA256,
    QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkProjectionPassReceipt,
    BenchmarkUnsealedProjectionCleanupProof,
    BenchmarkUnsealedProjectionScope,
    BenchmarkUnsealedRecoveryInventory,
    benchmark_unsealed_projection_proof_sha256,
)
from infinity_context_server.benchmark_unsealed_projection_absence import (
    ServerBenchmarkUnsealedProjectionAbsence,
)

D = "a" * 64


def _record() -> BenchmarkRunRegistryRecord:
    receipt = BenchmarkCleanupReceipt(
        run_id_sha256=D,
        space_id="benchmark-space-" + D[:48],
        space_slug="memory-comparison-test",
        disposition="cleanup_pending",
        projection_cleanup="blocked",
        counts=BenchmarkCleanupCounts(0, 0, 1, 0, 0, 1, 0, 1, 0, 0),
        vector_delete_outbox_ids=(1,),
        graph_delete_outbox_ids=(),
        cognee_delete_outbox_ids=(),
        receipt_sha256="b" * 64,
    )
    plan = {
        "qdrant": {
            "target_commitment_sha256": "4" * 64,
            "collection_projection_policy_sha256": QDRANT_COLLECTION_PROJECTION_POLICY_SHA256,
            "deterministic_scope_mapping_policy_sha256": QDRANT_SCOPE_MAPPING_POLICY_SHA256,
            "space_wide_scan_policy_sha256": QDRANT_SPACE_WIDE_SCAN_POLICY_SHA256,
        },
        "graphiti": {
            "target_commitment_sha256": "5" * 64,
            "group_mapping_policy_sha256": GRAPHITI_GROUP_MAPPING_POLICY_SHA256,
            "space_prefix_scan_policy_sha256": GRAPHITI_SPACE_PREFIX_SCAN_POLICY_SHA256,
        },
        "cognee": {
            "disposition": "not_projected",
            "policy_sha256": COGNEE_NOT_PROJECTED_POLICY_SHA256,
        },
    }
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return BenchmarkRunRegistryRecord(
        run_id_sha256=D,
        binding_commitment_sha256="c" * 64,
        infinity_target_identity_sha256="d" * 64,
        space_id=receipt.space_id,
        space_slug=receipt.space_slug,
        idempotency_key_sha256="e" * 64,
        registration_fingerprint_sha256="f" * 64,
        state="cleanup_pending",
        projection_manifest_json=None,
        projection_manifest_sha256=None,
        projection_cleanup_state="blocked",
        cleanup_fingerprint_sha256="1" * 64,
        cleanup_receipt=receipt,
        finalization_fingerprint_sha256=None,
        completion_receipt=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
        cleanup_plan_json=plan,
        cleanup_plan_sha256="2" * 64,
        cleanup_plan_state="sealed",
    )


class _Inventory:
    async def load_inventory(self, *, record: BenchmarkRunRegistryRecord) -> object:
        return BenchmarkUnsealedRecoveryInventory(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            cleanup_plan_sha256=record.cleanup_plan_sha256,
            cleanup_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            scopes=(BenchmarkUnsealedProjectionScope("scope", None, ("chunk",), ()),),
            document_source_external_ids=(),
            episode_source_external_ids=(),
            chunk_source_external_ids=("source",),
            chunk_source_hashes=("hash",),
            delete_outbox_ids=(1,),
            inventory_sha256="3" * 64,
        )


class _Lane:
    def __init__(self, lane: str, *, fail_second: bool = False) -> None:
        self.lane = lane
        self.fail_second = fail_second
        self.calls = 0

    async def delete_benchmark_space_two_pass(self, **_: object) -> tuple[object, object]:
        self.calls += 1
        return tuple(
            BenchmarkProjectionPassReceipt(
                lane=self.lane,
                target_commitment_sha256="4" * 64 if self.lane == "qdrant" else "5" * 64,
                pass_index=index,
                observed_count=1 if self.fail_second and index == 2 else 0,
                absent=not (self.fail_second and index == 2),
                receipt_sha256=str(index) * 64,
            )
            for index in (1, 2)
        )


class _HostileInventory:
    async def load_inventory(self, **_: object) -> object:
        return SimpleNamespace(scopes=())


class _HostileLane(_Lane):
    async def delete_benchmark_space_two_pass(self, **_: object) -> tuple[object, object]:
        first, second = await super().delete_benchmark_space_two_pass()
        object.__setattr__(second, "receipt_sha256", first.receipt_sha256)
        return first, second


class _SpoofTargetLane(_Lane):
    async def delete_benchmark_space_two_pass(self, **_: object) -> tuple[object, object]:
        first, second = await super().delete_benchmark_space_two_pass()
        object.__setattr__(second, "target_commitment_sha256", "7" * 64)
        return first, second


def _absence(
    *, inventory: object, qdrant: object, graphiti: object
) -> ServerBenchmarkUnsealedProjectionAbsence:
    return ServerBenchmarkUnsealedProjectionAbsence(
        inventory=inventory,
        qdrant=qdrant,
        graphiti=graphiti,
        qdrant_target_commitment_sha256="4" * 64,
        graphiti_target_commitment_sha256="5" * 64,
    )


def test_unsealed_absence_returns_plan_inventory_and_two_pass_bound_proof() -> None:
    qdrant = _Lane("qdrant")
    graphiti = _Lane("graphiti")
    proof = asyncio.run(
        _absence(inventory=_Inventory(), qdrant=qdrant, graphiti=graphiti).prove_absence(
            record=_record()
        )
    )
    assert proof.cleanup_plan_sha256 == "2" * 64
    assert proof.inventory_sha256 == "3" * 64
    assert proof.qdrant_pass_receipt_sha256s == ("1" * 64, "2" * 64)
    assert proof.graphiti_pass_receipt_sha256s == ("1" * 64, "2" * 64)
    assert qdrant.calls == graphiti.calls == 1


def test_unsealed_absence_rejects_cognee_or_failed_second_pass() -> None:
    record = _record()
    record.cleanup_plan_json["cognee"]["policy_sha256"] = "9" * 64
    with pytest.raises(MemoryConflictError, match="Cognee"):
        asyncio.run(
            _absence(
                inventory=_Inventory(), qdrant=_Lane("qdrant"), graphiti=_Lane("graphiti")
            ).prove_absence(record=record)
        )
    with pytest.raises(MemoryConflictError, match="two-pass"):
        asyncio.run(
            _absence(
                inventory=_Inventory(),
                qdrant=_Lane("qdrant", fail_second=True),
                graphiti=_Lane("graphiti"),
            ).prove_absence(record=_record())
        )


@pytest.mark.parametrize(
    "record",
    [
        replace(_record(), cleanup_plan_state="recovery_blocked"),
        replace(_record(), cleanup_plan_json=None, cleanup_plan_sha256=None),
        replace(_record(), cleanup_receipt=None),
    ],
)
def test_unsealed_absence_rejects_legacy_or_missing_authority(
    record: BenchmarkRunRegistryRecord,
) -> None:
    with pytest.raises(MemoryConflictError, match="not provable"):
        asyncio.run(
            _absence(
                inventory=_Inventory(), qdrant=_Lane("qdrant"), graphiti=_Lane("graphiti")
            ).prove_absence(record=record)
        )


def test_unsealed_absence_rejects_hostile_inventory_and_pass_receipts() -> None:
    with pytest.raises(MemoryConflictError, match="inventory type"):
        asyncio.run(
            _absence(
                inventory=_HostileInventory(),
                qdrant=_Lane("qdrant"),
                graphiti=_Lane("graphiti"),
            ).prove_absence(record=_record())
        )
    with pytest.raises(MemoryConflictError, match="two-pass"):
        asyncio.run(
            _absence(
                inventory=_Inventory(),
                qdrant=_HostileLane("qdrant"),
                graphiti=_Lane("graphiti"),
            ).prove_absence(record=_record())
        )


def test_unsealed_absence_rejects_provider_target_drift_before_evidence_calls() -> None:
    qdrant = _Lane("qdrant")
    record = _record()
    record.cleanup_plan_json["qdrant"]["target_commitment_sha256"] = "7" * 64
    with pytest.raises(MemoryConflictError, match="target authority"):
        asyncio.run(
            _absence(
                inventory=_Inventory(), qdrant=qdrant, graphiti=_Lane("graphiti")
            ).prove_absence(record=record)
        )
    assert qdrant.calls == 0
    with pytest.raises(MemoryConflictError, match="two-pass"):
        asyncio.run(
            _absence(
                inventory=_Inventory(),
                qdrant=_SpoofTargetLane("qdrant"),
                graphiti=_Lane("graphiti"),
            ).prove_absence(record=_record())
        )


class _Uow(AbstractAsyncContextManager):
    def __init__(self, repository: object) -> None:
        self.benchmark_runs = repository

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class _Repository:
    def __init__(self, record: BenchmarkRunRegistryRecord) -> None:
        self.record = record
        self.reads = 0
        self.finalize_calls = 0

    async def get_by_run_id_sha256(self, *_: object, **__: object) -> object:
        self.reads += 1
        return self.record

    async def finalize_unsealed_abort(self, record: object, **kwargs: object) -> object:
        self.finalize_calls += 1
        receipt = BenchmarkAbortCompletionReceipt(
            run_id_sha256=D,
            binding_commitment_sha256="c" * 64,
            infinity_target_identity_sha256="d" * 64,
            space_id=self.record.space_id,
            space_slug=self.record.space_slug,
            disposition="abort_complete",
            projection_cleanup="unsealed_abort_complete",
            cleanup_initiation_receipt_sha256="b" * 64,
            cleanup_plan_sha256=self.record.cleanup_plan_sha256,
            projection_absence_proof_sha256=kwargs["projection_absence_proof_sha256"],
            completed_at=self.record.updated_at,
            receipt_sha256="9" * 64,
        )
        self.record = replace(
            self.record,
            state="cleanup_aborted",
            projection_cleanup_state="unsealed_abort_complete",
            finalization_fingerprint_sha256=kwargs["finalization_fingerprint_sha256"],
            completion_receipt=receipt,
        )
        return self.record


class _Proof:
    def __init__(
        self,
        repository: _Repository,
        *,
        race: bool,
        corrupt: bool = False,
        terminal_race: str | None = None,
    ) -> None:
        self.repository = repository
        self.race = race
        self.calls = 0
        self.corrupt = corrupt
        self.terminal_race = terminal_race

    async def prove_absence(self, *, record: BenchmarkRunRegistryRecord) -> object:
        self.calls += 1
        if self.race:
            self.repository.record = replace(record, cleanup_plan_sha256="8" * 64)
        proof_sha256 = benchmark_unsealed_projection_proof_sha256(
            run_id_sha256=record.run_id_sha256,
            cleanup_plan_sha256=record.cleanup_plan_sha256,
            cleanup_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            inventory_sha256="3" * 64,
            qdrant_pass_receipt_sha256s=("1" * 64, "2" * 64),
            graphiti_pass_receipt_sha256s=("4" * 64, "5" * 64),
            cognee_policy_sha256=COGNEE_NOT_PROJECTED_POLICY_SHA256,
        )
        proof = BenchmarkUnsealedProjectionCleanupProof(
            record.run_id_sha256,
            record.cleanup_plan_sha256,
            record.cleanup_receipt.receipt_sha256,
            "3" * 64,
            ("1" * 64, "2" * 64),
            ("4" * 64, "5" * 64),
            "not_projected",
            COGNEE_NOT_PROJECTED_POLICY_SHA256,
            proof_sha256,
        )
        if self.corrupt:
            object.__setattr__(proof, "proof_sha256", "9" * 64)
        if self.terminal_race is not None:
            receipt = BenchmarkAbortCompletionReceipt(
                run_id_sha256=D,
                binding_commitment_sha256="c" * 64,
                infinity_target_identity_sha256="d" * 64,
                space_id=record.space_id,
                space_slug=record.space_slug,
                disposition="abort_complete",
                projection_cleanup="unsealed_abort_complete",
                cleanup_initiation_receipt_sha256=(
                    "7" * 64 if self.terminal_race == "receipt" else "b" * 64
                ),
                cleanup_plan_sha256="2" * 64,
                projection_absence_proof_sha256=(
                    "7" * 64 if self.terminal_race == "proof" else proof.proof_sha256
                ),
                completed_at=record.updated_at,
                receipt_sha256="9" * 64,
            )
            fingerprint = _fingerprint(
                "finalize_unsealed_abort",
                D,
                "c" * 64,
                "d" * 64,
                record.space_id,
                record.space_slug,
                "b" * 64,
                "2" * 64,
                "e" * 64,
            )
            self.repository.record = replace(
                record,
                state="cleanup_aborted",
                projection_cleanup_state="unsealed_abort_complete",
                finalization_fingerprint_sha256=(
                    "8" * 64 if self.terminal_race == "fingerprint" else fingerprint
                ),
                completion_receipt=receipt,
            )
        return proof


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 1, 2, tzinfo=UTC)


def test_unsealed_finalize_rejects_registry_race_after_external_proof() -> None:
    repository = _Repository(_record())
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=lambda: _Uow(repository),
        clock=_Clock(),
        projection_absence=_Proof(repository, race=True),
    )
    command = FinalizeUnsealedBenchmarkAbortCommand(
        run_id_sha256=D,
        binding_commitment_sha256="c" * 64,
        infinity_target_identity_sha256="d" * 64,
        space_id=repository.record.space_id,
        space_slug=repository.record.space_slug,
        expected_cleanup_receipt_sha256="b" * 64,
        expected_cleanup_plan_sha256="2" * 64,
        idempotency_key_sha256="e" * 64,
    )
    with pytest.raises(MemoryConflictError, match="changed during"):
        asyncio.run(use_case.execute(command))
    assert repository.reads == 2


def test_unsealed_finalize_replays_exact_terminal_race_after_external_proof() -> None:
    repository = _Repository(_record())
    proof = _Proof(repository, race=False, terminal_race="exact")
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=lambda: _Uow(repository), clock=_Clock(), projection_absence=proof
    )
    result = asyncio.run(
        use_case.execute(
            FinalizeUnsealedBenchmarkAbortCommand(
                D,
                "c" * 64,
                "d" * 64,
                repository.record.space_id,
                repository.record.space_slug,
                "b" * 64,
                "2" * 64,
                "e" * 64,
            )
        )
    )
    assert result.replayed is True
    assert proof.calls == 1
    assert repository.finalize_calls == 0


@pytest.mark.parametrize("corruption", ["fingerprint", "receipt"])
def test_unsealed_finalize_rejects_divergent_terminal_race(corruption: str) -> None:
    repository = _Repository(_record())
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=lambda: _Uow(repository),
        clock=_Clock(),
        projection_absence=_Proof(repository, race=False, terminal_race=corruption),
    )
    with pytest.raises(MemoryConflictError, match="finalization conflicted"):
        asyncio.run(
            use_case.execute(
                FinalizeUnsealedBenchmarkAbortCommand(
                    D,
                    "c" * 64,
                    "d" * 64,
                    repository.record.space_id,
                    repository.record.space_slug,
                    "b" * 64,
                    "2" * 64,
                    "e" * 64,
                )
            )
        )
    assert repository.finalize_calls == 0


class _ConcurrentProof:
    def __init__(self) -> None:
        self.arrived = 0
        self.ready = asyncio.Event()

    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedProjectionCleanupProof:
        ordinal = self.arrived
        self.arrived += 1
        if self.arrived == 2:
            self.ready.set()
        await self.ready.wait()
        inventory_sha256 = str(ordinal + 3) * 64
        proof_sha256 = benchmark_unsealed_projection_proof_sha256(
            run_id_sha256=record.run_id_sha256,
            cleanup_plan_sha256=record.cleanup_plan_sha256,
            cleanup_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            inventory_sha256=inventory_sha256,
            qdrant_pass_receipt_sha256s=("1" * 64, "2" * 64),
            graphiti_pass_receipt_sha256s=("4" * 64, "5" * 64),
            cognee_policy_sha256=COGNEE_NOT_PROJECTED_POLICY_SHA256,
        )
        return BenchmarkUnsealedProjectionCleanupProof(
            record.run_id_sha256,
            record.cleanup_plan_sha256,
            record.cleanup_receipt.receipt_sha256,
            inventory_sha256,
            ("1" * 64, "2" * 64),
            ("4" * 64, "5" * 64),
            "not_projected",
            COGNEE_NOT_PROJECTED_POLICY_SHA256,
            proof_sha256,
        )


def test_unsealed_finalize_concurrent_same_key_replays_persisted_proof() -> None:
    async def run() -> None:
        repository = _Repository(_record())
        proofs = _ConcurrentProof()
        use_case = FinalizeUnsealedBenchmarkAbortUseCase(
            uow_factory=lambda: _Uow(repository),
            clock=_Clock(),
            projection_absence=proofs,
        )
        command = FinalizeUnsealedBenchmarkAbortCommand(
            D,
            "c" * 64,
            "d" * 64,
            repository.record.space_id,
            repository.record.space_slug,
            "b" * 64,
            "2" * 64,
            "e" * 64,
        )
        results = await asyncio.gather(use_case.execute(command), use_case.execute(command))
        assert sorted(result.replayed for result in results) == [False, True]
        assert repository.finalize_calls == 1
        assert len({result.receipt.projection_absence_proof_sha256 for result in results}) == 1

    asyncio.run(run())


def test_unsealed_finalize_exact_replay_does_not_probe_providers_again() -> None:
    repository = _Repository(_record())
    proof = _Proof(repository, race=False)
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=lambda: _Uow(repository), clock=_Clock(), projection_absence=proof
    )
    command = FinalizeUnsealedBenchmarkAbortCommand(
        run_id_sha256=D,
        binding_commitment_sha256="c" * 64,
        infinity_target_identity_sha256="d" * 64,
        space_id=repository.record.space_id,
        space_slug=repository.record.space_slug,
        expected_cleanup_receipt_sha256="b" * 64,
        expected_cleanup_plan_sha256="2" * 64,
        idempotency_key_sha256="e" * 64,
    )
    first = asyncio.run(use_case.execute(command))
    replay = asyncio.run(use_case.execute(command))
    assert first.replayed is False and replay.replayed is True
    assert proof.calls == 1


def test_unsealed_finalize_rejects_nominal_proof_with_forged_digest() -> None:
    repository = _Repository(_record())
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=lambda: _Uow(repository),
        clock=_Clock(),
        projection_absence=_Proof(repository, race=False, corrupt=True),
    )
    command = FinalizeUnsealedBenchmarkAbortCommand(
        D,
        "c" * 64,
        "d" * 64,
        repository.record.space_id,
        repository.record.space_slug,
        "b" * 64,
        "2" * 64,
        "e" * 64,
    )
    with pytest.raises(MemoryConflictError, match="proof binding differs"):
        asyncio.run(use_case.execute(command))
