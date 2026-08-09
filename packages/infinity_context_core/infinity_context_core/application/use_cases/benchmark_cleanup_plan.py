"""Atomic registration of a managed benchmark and its cleanup capability."""

from __future__ import annotations

import hashlib
import json
import re

from infinity_context_core.application.dto_benchmark_runs import (
    RegisterBenchmarkRunCommand,
    RegisterBenchmarkRunResult,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    CanonicalCleanupPlanSeal,
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")


class RegisterBenchmarkRunUseCase:
    """Persist space, run, and exact cleanup plan in one transaction."""

    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RegisterBenchmarkRunCommand) -> RegisterBenchmarkRunResult:
        _validate_registration(command)
        cleanup_plan = validate_managed_benchmark_cleanup_plan(
            command.cleanup_plan_json,
            command.cleanup_plan_sha256,
            run_id_sha256=command.run_id_sha256,
            binding_commitment_sha256=command.binding_commitment_sha256,
            infinity_target_identity_sha256=command.infinity_target_identity_sha256,
            space_slug=command.space_slug,
        )
        fingerprint = _fingerprint(
            "register",
            command.run_id_sha256,
            command.binding_commitment_sha256,
            command.infinity_target_identity_sha256,
            command.space_slug,
            command.idempotency_key_sha256,
            cleanup_plan.sha256,
        )
        existing = await self._load_existing(command.run_id_sha256, command.idempotency_key_sha256)
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
            cleanup_plan_json=cleanup_plan.value,
            cleanup_plan_sha256=cleanup_plan.sha256,
            cleanup_plan_state="sealed",
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
                command.run_id_sha256, command.idempotency_key_sha256
            )
            if concurrent is None:
                raise
            return _registration_replay(concurrent, fingerprint)
        return _result(record, created=True)

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


def _registration_replay(
    record: BenchmarkRunRegistryRecord,
    fingerprint: str,
) -> RegisterBenchmarkRunResult:
    if record.registration_fingerprint_sha256 != fingerprint:
        raise MemoryConflictError("Benchmark registration fingerprint conflicted")
    if record.cleanup_plan_state != "sealed" or record.cleanup_plan_sha256 is None:
        raise MemoryConflictError("Benchmark registration cleanup plan conflicted")
    return _result(record, created=False)


def _result(record: BenchmarkRunRegistryRecord, *, created: bool) -> RegisterBenchmarkRunResult:
    if record.cleanup_plan_sha256 is None or record.cleanup_plan_state != "sealed":
        raise MemoryConflictError("Benchmark registration cleanup plan conflicted")
    return RegisterBenchmarkRunResult(
        record=record,
        created=created,
        cleanup_plan_seal=CanonicalCleanupPlanSeal(
            record.run_id_sha256, record.cleanup_plan_sha256
        ),
    )


def _validate_registration(command: RegisterBenchmarkRunCommand) -> None:
    for value in (
        command.run_id_sha256,
        command.binding_commitment_sha256,
        command.infinity_target_identity_sha256,
        command.idempotency_key_sha256,
    ):
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise MemoryValidationError("Benchmark digest is invalid")
    if _SPACE_SLUG.fullmatch(command.space_slug) is None:
        raise MemoryValidationError("Benchmark space slug is invalid")


def _fingerprint(operation: str, *values: str) -> str:
    payload = json.dumps(
        {"operation": operation, "values": values}, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = ("RegisterBenchmarkRunUseCase",)
