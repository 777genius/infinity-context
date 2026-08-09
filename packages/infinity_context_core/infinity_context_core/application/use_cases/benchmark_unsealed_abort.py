"""Finalize managed benchmark cleanup that never sealed a projection manifest."""

from __future__ import annotations

import hashlib
import hmac
import json
import re

from infinity_context_core.application.dto_benchmark_runs import (
    FinalizeUnsealedBenchmarkAbortCommand,
    FinalizeUnsealedBenchmarkAbortResult,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkRunRegistryRecord,
)
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkUnsealedProjectionAbsencePort,
    BenchmarkUnsealedProjectionCleanupProof,
    benchmark_unsealed_projection_proof_sha256,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_SLUG = re.compile(r"^memory-comparison-[a-z0-9-]{1,80}$")


class FinalizeUnsealedBenchmarkAbortUseCase:
    """Finalize manifestless cleanup from server-owned canonical/outbox evidence."""

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        projection_absence: BenchmarkUnsealedProjectionAbsencePort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._projection_absence = projection_absence

    async def execute(
        self,
        command: FinalizeUnsealedBenchmarkAbortCommand,
    ) -> FinalizeUnsealedBenchmarkAbortResult:
        _validate_command(command)
        fingerprint = _fingerprint(
            "finalize_unsealed_abort",
            command.run_id_sha256,
            command.binding_commitment_sha256,
            command.infinity_target_identity_sha256,
            command.space_id,
            command.space_slug,
            command.expected_cleanup_receipt_sha256,
            command.expected_cleanup_plan_sha256,
            command.idempotency_key_sha256,
        )
        async with self._uow_factory() as candidate_uow:
            candidate = await candidate_uow.benchmark_runs.get_by_run_id_sha256(
                command.run_id_sha256,
            )
            if candidate is None:
                raise MemoryNotFoundError("Benchmark run not found")
            _require_binding(candidate, command)
            if candidate.state == "cleanup_aborted":
                return FinalizeUnsealedBenchmarkAbortResult(
                    receipt=_require_terminal_replay(candidate, command, fingerprint),
                    replayed=True,
                )
            _require_pending(candidate, command)
        proof = await self._projection_absence.prove_absence(record=candidate)
        _require_proof(candidate, proof)
        async with self._uow_factory() as uow:
            record = await uow.benchmark_runs.get_by_run_id_sha256(
                command.run_id_sha256, for_update=True
            )
            if record is None:
                raise MemoryConflictError("Benchmark unsealed abort changed during absence proof")
            _require_binding(record, command)
            if record.state == "cleanup_aborted":
                return FinalizeUnsealedBenchmarkAbortResult(
                    receipt=_require_terminal_replay(record, command, fingerprint),
                    replayed=True,
                )
            if record != candidate:
                raise MemoryConflictError("Benchmark unsealed abort changed during absence proof")
            updated = await uow.benchmark_runs.finalize_unsealed_abort(
                record,
                finalization_fingerprint_sha256=fingerprint,
                projection_absence_proof_sha256=proof.proof_sha256,
                now=self._clock.now(),
            )
            if (
                updated.state != "cleanup_aborted"
                or updated.projection_cleanup_state != "unsealed_abort_complete"
                or type(updated.completion_receipt) is not BenchmarkAbortCompletionReceipt
            ):
                raise MemoryConflictError("Benchmark abort completion was not persisted")
            await uow.commit()
            return FinalizeUnsealedBenchmarkAbortResult(
                receipt=updated.completion_receipt,
                replayed=False,
            )


def _require_pending(
    record: BenchmarkRunRegistryRecord,
    command: FinalizeUnsealedBenchmarkAbortCommand,
) -> None:
    if (
        record.state != "cleanup_pending"
        or record.projection_cleanup_state != "blocked"
        or record.projection_manifest_json is not None
        or record.projection_manifest_sha256 is not None
        or record.cleanup_plan_json is None
        or record.cleanup_plan_sha256 is None
        or not hmac.compare_digest(
            record.cleanup_plan_sha256,
            command.expected_cleanup_plan_sha256,
        )
        or record.cleanup_plan_state != "sealed"
        or record.cleanup_receipt is None
        or not hmac.compare_digest(
            record.cleanup_receipt.receipt_sha256,
            command.expected_cleanup_receipt_sha256,
        )
    ):
        raise MemoryConflictError("Benchmark unsealed abort is not finalizable")


def _require_terminal_replay(
    record: BenchmarkRunRegistryRecord,
    command: FinalizeUnsealedBenchmarkAbortCommand,
    fingerprint: str,
) -> BenchmarkAbortCompletionReceipt:
    receipt = record.completion_receipt
    if (
        record.state != "cleanup_aborted"
        or record.projection_cleanup_state != "unsealed_abort_complete"
        or record.cleanup_plan_state != "sealed"
        or record.cleanup_plan_sha256 != command.expected_cleanup_plan_sha256
        or record.cleanup_receipt is None
        or record.cleanup_receipt.receipt_sha256 != command.expected_cleanup_receipt_sha256
        or record.finalization_fingerprint_sha256 != fingerprint
        or type(receipt) is not BenchmarkAbortCompletionReceipt
        or (
            receipt.run_id_sha256,
            receipt.binding_commitment_sha256,
            receipt.infinity_target_identity_sha256,
            receipt.space_id,
            receipt.space_slug,
            receipt.disposition,
            receipt.projection_cleanup,
        )
        != (
            command.run_id_sha256,
            command.binding_commitment_sha256,
            command.infinity_target_identity_sha256,
            command.space_id,
            command.space_slug,
            "abort_complete",
            "unsealed_abort_complete",
        )
        or not hmac.compare_digest(
            receipt.cleanup_plan_sha256,
            command.expected_cleanup_plan_sha256,
        )
        or not hmac.compare_digest(
            receipt.cleanup_initiation_receipt_sha256,
            command.expected_cleanup_receipt_sha256,
        )
        or receipt.projection_absence_proof_sha256
        != receipt.projection_absence_proof_sha256.lower()
        or _SHA256.fullmatch(receipt.projection_absence_proof_sha256) is None
    ):
        raise MemoryConflictError("Benchmark abort finalization conflicted")
    return receipt


def _require_proof(
    record: BenchmarkRunRegistryRecord,
    proof: BenchmarkUnsealedProjectionCleanupProof,
) -> None:
    receipt = record.cleanup_receipt
    if receipt is None or record.cleanup_plan_sha256 is None:
        raise MemoryConflictError("Benchmark unsealed projection proof binding is incomplete")
    if (
        type(proof) is not BenchmarkUnsealedProjectionCleanupProof
        or proof.run_id_sha256 != record.run_id_sha256
        or not hmac.compare_digest(proof.cleanup_plan_sha256, record.cleanup_plan_sha256)
        or not hmac.compare_digest(proof.cleanup_receipt_sha256, receipt.receipt_sha256)
        or not hmac.compare_digest(
            proof.proof_sha256,
            benchmark_unsealed_projection_proof_sha256(
                run_id_sha256=proof.run_id_sha256,
                cleanup_plan_sha256=proof.cleanup_plan_sha256,
                cleanup_receipt_sha256=proof.cleanup_receipt_sha256,
                inventory_sha256=proof.inventory_sha256,
                qdrant_pass_receipt_sha256s=proof.qdrant_pass_receipt_sha256s,
                graphiti_pass_receipt_sha256s=proof.graphiti_pass_receipt_sha256s,
                cognee_policy_sha256=proof.cognee_policy_sha256,
            ),
        )
    ):
        raise MemoryConflictError("Benchmark unsealed projection proof binding differs")


def _validate_command(command: FinalizeUnsealedBenchmarkAbortCommand) -> None:
    for value in (
        command.run_id_sha256,
        command.binding_commitment_sha256,
        command.infinity_target_identity_sha256,
        command.idempotency_key_sha256,
        command.expected_cleanup_receipt_sha256,
        command.expected_cleanup_plan_sha256,
    ):
        _digest(value)
    if _SPACE_SLUG.fullmatch(command.space_slug) is None:
        raise MemoryValidationError("Benchmark space slug is invalid")
    if not command.space_id or len(command.space_id) > 80:
        raise MemoryValidationError("Benchmark space id is invalid")


def _require_binding(
    record: BenchmarkRunRegistryRecord,
    command: FinalizeUnsealedBenchmarkAbortCommand,
) -> None:
    if (
        record.binding_commitment_sha256,
        record.infinity_target_identity_sha256,
        record.space_id,
        record.space_slug,
    ) != (
        command.binding_commitment_sha256,
        command.infinity_target_identity_sha256,
        command.space_id,
        command.space_slug,
    ):
        raise MemoryConflictError("Benchmark abort binding conflicted")


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


__all__ = ("FinalizeUnsealedBenchmarkAbortUseCase",)
