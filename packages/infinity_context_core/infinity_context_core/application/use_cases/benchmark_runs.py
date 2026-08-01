"""Internal use cases for exact managed benchmark run registration and cleanup."""

from __future__ import annotations

import hashlib
import json
import re

from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    CleanupBenchmarkRunResult,
    RegisterBenchmarkRunCommand,
    RegisterBenchmarkRunResult,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")


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
            cleanup_fingerprint_sha256=None,
            cleanup_receipt=None,
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
                return CleanupBenchmarkRunResult(receipt=record.cleanup_receipt, replayed=True)
            if record.state != "active":
                raise MemoryConflictError("Benchmark run state conflicted")
            updated = await uow.benchmark_runs.begin_cleanup(
                record,
                cleanup_fingerprint_sha256=fingerprint,
                now=self._clock.now(),
            )
            if updated.cleanup_receipt is None or updated.state != "cleanup_pending":
                raise MemoryConflictError("Benchmark cleanup receipt was not persisted")
            await uow.commit()
            return CleanupBenchmarkRunResult(receipt=updated.cleanup_receipt, replayed=False)


def _registration_replay(
    record: BenchmarkRunRegistryRecord,
    fingerprint: str,
) -> RegisterBenchmarkRunResult:
    if record.registration_fingerprint_sha256 != fingerprint:
        raise MemoryConflictError("Benchmark registration fingerprint conflicted")
    return RegisterBenchmarkRunResult(record=record, created=False)


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


__all__ = ("CleanupBenchmarkRunUseCase", "RegisterBenchmarkRunUseCase")
