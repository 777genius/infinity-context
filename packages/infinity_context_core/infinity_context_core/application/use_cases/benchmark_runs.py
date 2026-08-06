"""Internal use cases for exact managed benchmark run registration and cleanup."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Literal

from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    CleanupBenchmarkRunResult,
    FinalizeBenchmarkRunCleanupCommand,
    FinalizeBenchmarkRunCleanupResult,
    GetBenchmarkRunLifecycleQuery,
    GetBenchmarkRunLifecycleResult,
    RegisterBenchmarkRunCommand,
    RegisterBenchmarkRunResult,
    SealProjectionManifestCommand,
    SealProjectionManifestResult,
)
from infinity_context_core.application.use_cases.benchmark_unsealed_abort import (
    FinalizeUnsealedBenchmarkAbortUseCase,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkProjectionAbsencePort,
    BenchmarkProjectionCleanupProof,
    BenchmarkRunRegistryRecord,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.derived_projection_policy import (
    derived_not_projected_policy_sha256,
)
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")
_MANIFEST_SCHEMA_V1 = "memory-comparison-projection-manifest.v1"
_MANIFEST_SCHEMA_V2 = "memory-comparison-projection-manifest.v2"
_COGNEE_NOT_PROJECTED_POLICY_SCHEMA = "memory-comparison-cognee-not-projected-policy.v1"
BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256 = hashlib.sha256(
    json.dumps(
        {
            "disposition": "not_projected",
            "schema_version": _COGNEE_NOT_PROJECTED_POLICY_SCHEMA,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
_MAX_MANIFEST_BYTES = 2_000_000
_MAX_SCOPES = 5_000
_MAX_CANONICAL_IDS = 5_000
_MAX_GRAPH_IDS = 20_000
_CANONICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_GRAPH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")


class RegisterBenchmarkRunUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RegisterBenchmarkRunCommand) -> RegisterBenchmarkRunResult:
        _validate_registration(command)
        fingerprint = _fingerprint(
            "register",
            command.run_id_sha256,
            command.binding_commitment_sha256,
            command.infinity_target_identity_sha256,
            command.space_slug,
            command.idempotency_key_sha256,
        )
        existing = await self._load_existing(
            command.run_id_sha256,
            command.idempotency_key_sha256,
        )
        if existing is not None:
            return _registration_replay(existing, fingerprint)

        now = self._clock.now()
        record = BenchmarkRunRegistryRecord(
            run_id_sha256=command.run_id_sha256,
            binding_commitment_sha256=command.binding_commitment_sha256,
            infinity_target_identity_sha256=command.infinity_target_identity_sha256,
            space_id=f"benchmark-space-{command.run_id_sha256[:48]}",
            space_slug=command.space_slug,
            idempotency_key_sha256=command.idempotency_key_sha256,
            registration_fingerprint_sha256=fingerprint,
            state="active",
            projection_manifest_json=None,
            projection_manifest_sha256=None,
            projection_cleanup_state="unsealed",
            cleanup_fingerprint_sha256=None,
            cleanup_receipt=None,
            finalization_fingerprint_sha256=None,
            completion_receipt=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.benchmark_runs.add(record)
                await uow.commit()
        except MemoryConflictError:
            concurrent = await self._load_existing(
                command.run_id_sha256,
                command.idempotency_key_sha256,
            )
            if concurrent is None:
                raise
            return _registration_replay(concurrent, fingerprint)
        return RegisterBenchmarkRunResult(record=record, created=True)

    async def _load_existing(
        self,
        run_id_sha256: str,
        idempotency_key_sha256: str,
    ) -> BenchmarkRunRegistryRecord | None:
        async with self._uow_factory() as uow:
            by_run = await uow.benchmark_runs.get_by_run_id_sha256(run_id_sha256)
            by_key = await uow.benchmark_runs.get_by_idempotency_key_sha256(idempotency_key_sha256)
        if by_run is not None and by_key is not None and by_run != by_key:
            raise MemoryConflictError("Benchmark registration identity conflicted")
        return by_run or by_key


class SealProjectionManifestUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        command: SealProjectionManifestCommand,
    ) -> SealProjectionManifestResult:
        _digest(command.run_id_sha256)
        manifest = _validated_projection_manifest_with_digest(
            command.projection_manifest_json,
            command.projection_manifest_sha256,
        )

        async with self._uow_factory() as uow:
            record = await uow.benchmark_runs.get_by_run_id_sha256(
                command.run_id_sha256,
                for_update=True,
            )
            if record is None:
                raise MemoryNotFoundError("Benchmark run not found")
            _require_projection_manifest_binding(
                manifest,
                run_id_sha256=record.run_id_sha256,
                binding_commitment_sha256=record.binding_commitment_sha256,
                infinity_target_identity_sha256=record.infinity_target_identity_sha256,
                space_id=record.space_id,
            )
            if record.projection_manifest_json is not None:
                if (
                    record.projection_manifest_sha256 != command.projection_manifest_sha256
                    or record.projection_manifest_json != manifest
                ):
                    raise MemoryConflictError("Projection manifest conflicted")
                if (record.state, record.projection_cleanup_state) not in {
                    ("active", "sealed"),
                    ("cleanup_pending", "pending"),
                }:
                    raise MemoryConflictError("Projection manifest state conflicted")
                return SealProjectionManifestResult(record=record, replayed=True)
            if record.state != "active" or record.projection_cleanup_state != "unsealed":
                raise MemoryConflictError("Projection manifest state conflicted")
            updated = await uow.benchmark_runs.seal_projection_manifest(
                record,
                projection_manifest_json=manifest,
                projection_manifest_sha256=command.projection_manifest_sha256,
                now=self._clock.now(),
            )
            if (
                updated.projection_manifest_json != manifest
                or updated.projection_manifest_sha256 != command.projection_manifest_sha256
                or updated.projection_cleanup_state != "sealed"
            ):
                raise MemoryConflictError("Projection manifest was not persisted")
            await uow.commit()
            return SealProjectionManifestResult(record=updated, replayed=False)


class CleanupBenchmarkRunUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: CleanupBenchmarkRunCommand) -> CleanupBenchmarkRunResult:
        _validate_cleanup(command)
        fingerprint = _fingerprint(
            "cleanup",
            command.run_id_sha256,
            command.binding_commitment_sha256,
            command.infinity_target_identity_sha256,
            command.space_id,
            command.space_slug,
            command.idempotency_key_sha256,
        )
        async with self._uow_factory() as uow:
            record = await uow.benchmark_runs.get_by_run_id_sha256(
                command.run_id_sha256,
                for_update=True,
            )
            if record is None:
                raise MemoryNotFoundError("Benchmark run not found")
            _require_cleanup_binding(record, command)
            if record.cleanup_receipt is not None:
                if record.cleanup_fingerprint_sha256 != fingerprint:
                    raise MemoryConflictError("Benchmark cleanup fingerprint conflicted")
                return CleanupBenchmarkRunResult(
                    receipt=record.cleanup_receipt,
                    projection_cleanup_state=_authoritative_cleanup_state(record),
                    replayed=True,
                )
            if record.state != "active":
                raise MemoryConflictError("Benchmark run state conflicted")
            updated = await uow.benchmark_runs.begin_cleanup(
                record,
                cleanup_fingerprint_sha256=fingerprint,
                now=self._clock.now(),
            )
            if updated.cleanup_receipt is None or updated.state != "cleanup_pending":
                raise MemoryConflictError("Benchmark cleanup receipt was not persisted")
            projection_cleanup_state = _authoritative_cleanup_state(updated)
            await uow.commit()
            return CleanupBenchmarkRunResult(
                receipt=updated.cleanup_receipt,
                projection_cleanup_state=projection_cleanup_state,
                replayed=False,
            )


class GetBenchmarkRunLifecycleUseCase:
    """Load one authoritative lifecycle snapshot without acquiring a write lock."""

    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self,
        query: GetBenchmarkRunLifecycleQuery,
    ) -> GetBenchmarkRunLifecycleResult:
        _digest(query.run_id_sha256)
        async with self._uow_factory() as uow:
            record = await uow.benchmark_runs.get_by_run_id_sha256(query.run_id_sha256)
        if record is None:
            raise MemoryNotFoundError("Benchmark run not found")
        _require_lifecycle_snapshot_consistent(record)
        return GetBenchmarkRunLifecycleResult(record=record)


class FinalizeBenchmarkRunCleanupUseCase:
    """Finalize only after an internal projection absence proof succeeds."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        projection_absence: BenchmarkProjectionAbsencePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._projection_absence = projection_absence

    async def execute(
        self,
        command: FinalizeBenchmarkRunCleanupCommand,
    ) -> FinalizeBenchmarkRunCleanupResult:
        _validate_finalization(command)
        fingerprint = _fingerprint(
            "finalize_cleanup",
            command.run_id_sha256,
            command.expected_cleanup_receipt_sha256,
            command.idempotency_key_sha256,
        )
        record = await self._load(command.run_id_sha256)
        replay = _finalization_replay(record, fingerprint)
        if replay is not None:
            return replay
        _require_finalization_candidate(record, command.expected_cleanup_receipt_sha256)

        proof = await self._projection_absence.prove_absence(record=record)
        proof_sha256 = _validated_projection_cleanup_proof(record, proof)

        async with self._uow_factory() as uow:
            locked = await uow.benchmark_runs.get_by_run_id_sha256(
                command.run_id_sha256,
                for_update=True,
            )
            if locked is None:
                raise MemoryNotFoundError("Benchmark run not found")
            replay = _finalization_replay(locked, fingerprint)
            if replay is not None:
                return replay
            _require_finalization_candidate(
                locked,
                command.expected_cleanup_receipt_sha256,
            )
            if _pending_registry_identity(locked) != _pending_registry_identity(record):
                raise MemoryConflictError("Benchmark cleanup changed during finalization")
            updated = await uow.benchmark_runs.finalize_cleanup(
                locked,
                finalization_fingerprint_sha256=fingerprint,
                projection_absence_proof_sha256=proof_sha256,
                now=self._clock.now(),
            )
            if (
                updated.state != "cleanup_complete"
                or updated.projection_cleanup_state != "complete"
                or updated.completion_receipt is None
                or updated.finalization_fingerprint_sha256 != fingerprint
            ):
                raise MemoryConflictError("Benchmark cleanup completion was not persisted")
            await uow.commit()
            return FinalizeBenchmarkRunCleanupResult(
                receipt=updated.completion_receipt,
                replayed=False,
            )

    async def _load(self, run_id_sha256: str) -> BenchmarkRunRegistryRecord:
        async with self._uow_factory() as uow:
            record = await uow.benchmark_runs.get_by_run_id_sha256(run_id_sha256)
        if record is None:
            raise MemoryNotFoundError("Benchmark run not found")
        return record


def _require_lifecycle_snapshot_consistent(record: BenchmarkRunRegistryRecord) -> None:
    manifest_pair = (
        record.projection_manifest_json is not None,
        record.projection_manifest_sha256 is not None,
    )
    if manifest_pair[0] != manifest_pair[1]:
        raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")

    if record.state == "active":
        expected_manifest = record.projection_cleanup_state == "sealed"
        if (
            record.projection_cleanup_state not in {"unsealed", "sealed"}
            or manifest_pair[0] is not expected_manifest
            or any(
                value is not None
                for value in (
                    record.cleanup_fingerprint_sha256,
                    record.cleanup_receipt,
                    record.finalization_fingerprint_sha256,
                    record.completion_receipt,
                    record.completed_at,
                )
            )
        ):
            raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")
        return

    if record.state == "cleanup_pending":
        receipt = record.cleanup_receipt
        expected_manifest = record.projection_cleanup_state == "pending"
        if (
            record.projection_cleanup_state not in {"blocked", "pending"}
            or manifest_pair[0] is not expected_manifest
            or record.cleanup_fingerprint_sha256 is None
            or receipt is None
            or record.finalization_fingerprint_sha256 is not None
            or record.completion_receipt is not None
            or record.completed_at is not None
            or (
                receipt.run_id_sha256,
                receipt.space_id,
                receipt.space_slug,
            )
            != (
                record.run_id_sha256,
                record.space_id,
                record.space_slug,
            )
            or (
                record.projection_cleanup_state == "pending"
                and receipt.projection_cleanup != "pending"
            )
            or receipt.projection_cleanup not in {"pending", "blocked"}
        ):
            raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")
        return

    if record.state == "cleanup_complete":
        initiation = record.cleanup_receipt
        completion = record.completion_receipt
        if (
            record.projection_cleanup_state != "complete"
            or manifest_pair != (True, True)
            or record.cleanup_fingerprint_sha256 is None
            or initiation is None
            or record.finalization_fingerprint_sha256 is None
            or completion is None
            or record.completed_at is None
            or (
                initiation.run_id_sha256,
                initiation.space_id,
                initiation.space_slug,
                initiation.projection_cleanup,
            )
            != (record.run_id_sha256, record.space_id, record.space_slug, "pending")
            or (
                completion.run_id_sha256,
                completion.space_id,
                completion.space_slug,
                completion.projection_manifest_sha256,
                completion.cleanup_initiation_receipt_sha256,
                completion.completed_at,
            )
            != (
                record.run_id_sha256,
                record.space_id,
                record.space_slug,
                record.projection_manifest_sha256,
                initiation.receipt_sha256,
                record.completed_at,
            )
        ):
            raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")
        return

    if record.state == "cleanup_aborted":
        initiation = record.cleanup_receipt
        completion = record.completion_receipt
        if (
            record.projection_cleanup_state != "unsealed_abort_complete"
            or manifest_pair != (False, False)
            or record.cleanup_fingerprint_sha256 is None
            or initiation is None
            or initiation.projection_cleanup != "blocked"
            or record.finalization_fingerprint_sha256 is None
            or type(completion) is not BenchmarkAbortCompletionReceipt
            or record.completed_at is None
            or (
                completion.run_id_sha256,
                completion.binding_commitment_sha256,
                completion.infinity_target_identity_sha256,
                completion.space_id,
                completion.space_slug,
                completion.cleanup_initiation_receipt_sha256,
                completion.completed_at,
            )
            != (
                record.run_id_sha256,
                record.binding_commitment_sha256,
                record.infinity_target_identity_sha256,
                record.space_id,
                record.space_slug,
                initiation.receipt_sha256,
                record.completed_at,
            )
        ):
            raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")
        return

    raise MemoryConflictError("Benchmark lifecycle snapshot is inconsistent")


def _finalization_replay(
    record: BenchmarkRunRegistryRecord,
    fingerprint: str,
) -> FinalizeBenchmarkRunCleanupResult | None:
    if record.completion_receipt is None:
        if record.finalization_fingerprint_sha256 is not None or record.completed_at is not None:
            raise MemoryConflictError("Benchmark cleanup completion state conflicted")
        return None
    if record.finalization_fingerprint_sha256 != fingerprint:
        raise MemoryConflictError("Benchmark cleanup finalization fingerprint conflicted")
    if record.state != "cleanup_complete" or record.projection_cleanup_state != "complete":
        raise MemoryConflictError("Benchmark cleanup completion state conflicted")
    return FinalizeBenchmarkRunCleanupResult(receipt=record.completion_receipt, replayed=True)


def _require_finalization_candidate(
    record: BenchmarkRunRegistryRecord,
    expected_cleanup_receipt_sha256: str,
) -> None:
    if (
        record.state != "cleanup_pending"
        or record.projection_cleanup_state != "pending"
        or record.projection_manifest_json is None
        or record.projection_manifest_sha256 is None
        or record.cleanup_receipt is None
    ):
        raise MemoryConflictError("Benchmark cleanup is not finalizable")
    if not hmac.compare_digest(
        record.cleanup_receipt.receipt_sha256,
        expected_cleanup_receipt_sha256,
    ):
        raise MemoryConflictError("Benchmark cleanup initiation receipt conflicted")


def _pending_registry_identity(record: BenchmarkRunRegistryRecord) -> tuple[object, ...]:
    receipt = record.cleanup_receipt
    return (
        record.run_id_sha256,
        record.state,
        record.projection_cleanup_state,
        record.projection_manifest_sha256,
        record.cleanup_fingerprint_sha256,
        receipt.receipt_sha256 if receipt is not None else None,
        record.updated_at,
    )


def _validated_projection_cleanup_proof(
    record: BenchmarkRunRegistryRecord,
    proof: BenchmarkProjectionCleanupProof,
) -> str:
    if (
        type(proof) is not BenchmarkProjectionCleanupProof
        or record.projection_manifest_sha256 is None
        or record.cleanup_receipt is None
        or (
            proof.run_id_sha256,
            proof.projection_manifest_sha256,
            proof.cleanup_initiation_receipt_sha256,
        )
        != (
            record.run_id_sha256,
            record.projection_manifest_sha256,
            record.cleanup_receipt.receipt_sha256,
        )
        or proof.qdrant_absent is not True
        or proof.graphiti_absent is not True
        or proof.cognee_absent is not True
    ):
        raise MemoryConflictError("Benchmark projection absence proof conflicted")
    return _fingerprint(
        "projection_absence",
        proof.run_id_sha256,
        proof.projection_manifest_sha256,
        proof.cleanup_initiation_receipt_sha256,
        "qdrant_absent",
        "graphiti_absent",
        "cognee_absent",
    )


def _validate_finalization(command: FinalizeBenchmarkRunCleanupCommand) -> None:
    _digest(command.run_id_sha256)
    _digest(command.expected_cleanup_receipt_sha256)
    _digest(command.idempotency_key_sha256)


def _registration_replay(
    record: BenchmarkRunRegistryRecord,
    fingerprint: str,
) -> RegisterBenchmarkRunResult:
    if record.registration_fingerprint_sha256 != fingerprint:
        raise MemoryConflictError("Benchmark registration fingerprint conflicted")
    return RegisterBenchmarkRunResult(record=record, created=False)


def _authoritative_cleanup_state(
    record: BenchmarkRunRegistryRecord,
) -> Literal["pending", "blocked"]:
    if record.projection_cleanup_state not in {"pending", "blocked"}:
        raise MemoryConflictError("Benchmark projection cleanup state conflicted")
    return record.projection_cleanup_state


def _require_cleanup_binding(
    record: BenchmarkRunRegistryRecord,
    command: CleanupBenchmarkRunCommand,
) -> None:
    expected = (
        record.binding_commitment_sha256,
        record.infinity_target_identity_sha256,
        record.space_id,
        record.space_slug,
    )
    actual = (
        command.binding_commitment_sha256,
        command.infinity_target_identity_sha256,
        command.space_id,
        command.space_slug,
    )
    if actual != expected:
        raise MemoryConflictError("Benchmark cleanup binding conflicted")


def validate_projection_manifest(
    value: object,
    projection_manifest_sha256: object,
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    infinity_target_identity_sha256: str,
    space_id: str,
) -> dict[str, object]:
    """Validate a canonical manifest, its digest, and its registry binding."""

    manifest = _validated_projection_manifest_with_digest(value, projection_manifest_sha256)
    _require_projection_manifest_binding(
        manifest,
        run_id_sha256=run_id_sha256,
        binding_commitment_sha256=binding_commitment_sha256,
        infinity_target_identity_sha256=infinity_target_identity_sha256,
        space_id=space_id,
    )
    return manifest


def _validated_projection_manifest_with_digest(
    value: object,
    projection_manifest_sha256: object,
) -> dict[str, object]:
    _digest(projection_manifest_sha256)
    manifest = _validated_projection_manifest(value)
    if not hmac.compare_digest(projection_manifest_sha256, _json_sha256(manifest)):
        raise MemoryValidationError("Projection manifest digest is invalid")
    return manifest


def _require_projection_manifest_binding(
    manifest: dict[str, object],
    *,
    run_id_sha256: str,
    binding_commitment_sha256: str,
    infinity_target_identity_sha256: str,
    space_id: str,
) -> None:
    expected = (
        run_id_sha256,
        binding_commitment_sha256,
        infinity_target_identity_sha256,
        space_id,
    )
    actual = (
        manifest["run_id_sha256"],
        manifest["binding_commitment_sha256"],
        manifest["infinity_target_identity_sha256"],
        manifest["space_id"],
    )
    if actual != expected:
        raise MemoryConflictError("Projection manifest binding conflicted")


def _validate_registration(command: RegisterBenchmarkRunCommand) -> None:
    for value in (
        command.run_id_sha256,
        command.binding_commitment_sha256,
        command.infinity_target_identity_sha256,
        command.idempotency_key_sha256,
    ):
        _digest(value)
    if _SPACE_SLUG.fullmatch(command.space_slug) is None:
        raise MemoryValidationError("Benchmark space slug is invalid")


def _validate_cleanup(command: CleanupBenchmarkRunCommand) -> None:
    _validate_registration(
        RegisterBenchmarkRunCommand(
            run_id_sha256=command.run_id_sha256,
            binding_commitment_sha256=command.binding_commitment_sha256,
            infinity_target_identity_sha256=command.infinity_target_identity_sha256,
            space_slug=command.space_slug,
            idempotency_key_sha256=command.idempotency_key_sha256,
        )
    )
    if not command.space_id or len(command.space_id) > 80:
        raise MemoryValidationError("Benchmark space id is invalid")


def _digest(value: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise MemoryValidationError("Benchmark digest is invalid")


def _fingerprint(operation: str, *values: str) -> str:
    payload = json.dumps(
        {"operation": operation, "values": values},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _validated_projection_manifest(value: object) -> dict[str, object]:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("Projection manifest is not canonical JSON") from exc
    if len(encoded.encode()) > _MAX_MANIFEST_BYTES:
        raise MemoryValidationError("Projection manifest exceeds size limit")
    if type(value) is not dict or set(value) != {
        "schema_version",
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
        "space_id",
        "scopes",
    }:
        raise MemoryValidationError("Projection manifest envelope is invalid")
    schema_version = value["schema_version"]
    if schema_version not in {_MANIFEST_SCHEMA_V1, _MANIFEST_SCHEMA_V2}:
        raise MemoryValidationError("Projection manifest schema is invalid")
    for key in (
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
    ):
        _digest(value[key])
    _canonical_id(value["space_id"])
    scopes = value["scopes"]
    if type(scopes) is not list or len(scopes) > _MAX_SCOPES:
        raise MemoryValidationError("Projection manifest scopes are invalid")
    scope_identities: list[tuple[str, str]] = []
    canonical_identity_fields = ("chunk_ids", "fact_ids", "document_ids")
    canonical_identities_by_kind = {field_name: set() for field_name in canonical_identity_fields}
    canonical_identities_v2: set[str] = set()
    for scope in scopes:
        scope_identities.append(_validate_manifest_scope(scope, schema_version=schema_version))
        identity_fields = (
            (*canonical_identity_fields, "episode_ids")
            if schema_version == _MANIFEST_SCHEMA_V2
            else canonical_identity_fields
        )
        for field_name in identity_fields:
            identities = set(scope[field_name])
            seen = (
                canonical_identities_v2
                if schema_version == _MANIFEST_SCHEMA_V2
                else canonical_identities_by_kind[field_name]
            )
            if seen.intersection(identities):
                raise MemoryValidationError(
                    "Projection manifest canonical identities are not globally unique"
                )
            seen.update(identities)
    if scope_identities != sorted(scope_identities) or len(scope_identities) != len(
        set(scope_identities)
    ):
        raise MemoryValidationError("Projection manifest scopes are not sorted and unique")
    canonical = json.loads(encoded)
    if canonical != value:
        raise MemoryValidationError("Projection manifest is not canonical JSON")
    return canonical


def _validate_manifest_scope(value: object, *, schema_version: str) -> tuple[str, str]:
    expected_fields = {
        "memory_scope_id",
        "thread_id",
        "chunk_ids",
        "fact_ids",
        "document_ids",
        "qdrant",
        "graphiti",
        "cognee",
    }
    if schema_version == _MANIFEST_SCHEMA_V2:
        expected_fields.add("episode_ids")
    if type(value) is not dict or set(value) != expected_fields:
        raise MemoryValidationError("Projection manifest scope is invalid")
    memory_scope_id = _canonical_id(value["memory_scope_id"])
    thread_id = ""
    if value["thread_id"] is not None:
        thread_id = _canonical_id(value["thread_id"])
    chunk_ids = _sorted_unique_ids(value["chunk_ids"], limit=_MAX_CANONICAL_IDS)
    if schema_version == _MANIFEST_SCHEMA_V2:
        episode_ids = _sorted_unique_ids(value["episode_ids"], limit=_MAX_CANONICAL_IDS)
        if episode_ids and not thread_id:
            raise MemoryValidationError("Projection manifest episode scope is invalid")
    fact_ids = _sorted_unique_ids(value["fact_ids"], limit=_MAX_CANONICAL_IDS)
    _sorted_unique_ids(value["document_ids"], limit=_MAX_CANONICAL_IDS)
    qdrant = value["qdrant"]
    if not chunk_ids and qdrant is not None:
        raise MemoryValidationError("Projection manifest qdrant evidence is invalid")
    if chunk_ids and _is_not_projected_lane(qdrant, lane="qdrant"):
        pass
    elif chunk_ids:
        _validate_commitment_pair(qdrant, lane="qdrant")
    graphiti = value["graphiti"]
    if not fact_ids and graphiti is not None:
        raise MemoryValidationError("Projection manifest graphiti evidence is invalid")
    if fact_ids and _is_not_projected_lane(graphiti, lane="graphiti"):
        pass
    elif fact_ids:
        if type(graphiti) is not dict or set(graphiti) != {
            "target_commitment_sha256",
            "manifest_binding_sha256",
            "episode_ids",
            "entity_ids",
            "mentions_edge_ids",
            "relates_to_edge_ids",
        }:
            raise MemoryValidationError("Projection manifest graphiti evidence is invalid")
        _digest(graphiti["target_commitment_sha256"])
        _digest(graphiti["manifest_binding_sha256"])
        graph_identity_lanes = tuple(
            _sorted_unique_graph_ids(graphiti[key], limit=_MAX_GRAPH_IDS)
            for key in (
                "episode_ids",
                "entity_ids",
                "mentions_edge_ids",
                "relates_to_edge_ids",
            )
        )
        graph_identities = tuple(identity for lane in graph_identity_lanes for identity in lane)
        if (
            not graph_identities
            or len(graph_identities) > _MAX_GRAPH_IDS
            or len(set(graph_identities)) != len(graph_identities)
        ):
            raise MemoryValidationError(
                "Projection manifest graph identities are incomplete or ambiguous"
            )
    cognee = value["cognee"]
    if type(cognee) is not dict or set(cognee) != {"disposition", "policy_sha256"}:
        raise MemoryValidationError("Projection manifest cognee evidence is invalid")
    if (
        cognee["disposition"] != "not_projected"
        or cognee["policy_sha256"] != BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256
    ):
        raise MemoryValidationError("Projection manifest cognee policy is invalid")
    return memory_scope_id, thread_id


def _validate_commitment_pair(value: object, *, lane: str) -> None:
    if type(value) is not dict or set(value) != {
        "target_commitment_sha256",
        "manifest_binding_sha256",
    }:
        raise MemoryValidationError(f"Projection manifest {lane} evidence is invalid")
    _digest(value["target_commitment_sha256"])
    _digest(value["manifest_binding_sha256"])


def _is_not_projected_lane(value: object, *, lane: str) -> bool:
    return value == {
        "disposition": "not_projected",
        "policy_sha256": derived_not_projected_policy_sha256(lane),
    }


def _sorted_unique_ids(value: object, *, limit: int) -> list[str]:
    if type(value) is not list or len(value) > limit:
        raise MemoryValidationError("Projection manifest identifiers are invalid")
    identifiers = [_canonical_id(item) for item in value]
    if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
        raise MemoryValidationError("Projection manifest identifiers are not sorted and unique")
    return identifiers


def _sorted_unique_graph_ids(value: object, *, limit: int) -> list[str]:
    if type(value) is not list or len(value) > limit:
        raise MemoryValidationError("Projection manifest graph identifiers are invalid")
    identifiers = value
    if any(type(item) is not str or _GRAPH_ID.fullmatch(item) is None for item in identifiers):
        raise MemoryValidationError("Projection manifest graph identifiers are invalid")
    if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
        raise MemoryValidationError(
            "Projection manifest graph identifiers are not sorted and unique"
        )
    return identifiers


def _canonical_id(value: object) -> str:
    if type(value) is not str or _CANONICAL_ID.fullmatch(value) is None:
        raise MemoryValidationError("Projection manifest identifier is invalid")
    return value


def _json_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = (
    "BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256",
    "CleanupBenchmarkRunUseCase",
    "FinalizeBenchmarkRunCleanupUseCase",
    "FinalizeUnsealedBenchmarkAbortUseCase",
    "GetBenchmarkRunLifecycleUseCase",
    "RegisterBenchmarkRunUseCase",
    "SealProjectionManifestUseCase",
    "validate_projection_manifest",
)
