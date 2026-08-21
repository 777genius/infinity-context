"""Strict decoding for canonical managed benchmark registry rows."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable

from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkCleanupCompletionReceipt,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)

from infinity_context_adapters.postgres.benchmark_run_completion import (
    abort_completion_receipt_from_json,
    completion_receipt_from_json,
    same_completion_timestamp,
)
from infinity_context_adapters.postgres.models import MemoryComparisonBenchmarkRunRow


def benchmark_run_record_from_row(
    row: MemoryComparisonBenchmarkRunRow,
    *,
    receipt_from_json: Callable[[dict[str, object]], BenchmarkCleanupReceipt],
) -> BenchmarkRunRegistryRecord:
    digests = (
        row.run_id_sha256,
        row.binding_commitment_sha256,
        row.infinity_target_identity_sha256,
        row.idempotency_key_sha256,
        row.registration_fingerprint_sha256,
    )
    if any(not _valid_digest(value) for value in digests):
        _invalid()
    for optional in (row.cleanup_fingerprint_sha256, row.finalization_fingerprint_sha256):
        if optional is not None and not _valid_digest(optional):
            _invalid()
    if row.state not in {"active", "cleanup_pending", "cleanup_complete", "cleanup_aborted"}:
        _invalid()

    cleanup_plan, cleanup_plan_sha256 = _cleanup_plan(row)
    manifest = row.projection_manifest_json
    manifest_sha256 = row.projection_manifest_sha256
    if (manifest is None) != (manifest_sha256 is None):
        _invalid()
    if manifest is not None and (
        type(manifest) is not dict
        or not _valid_digest(manifest_sha256)
        or not hmac.compare_digest(str(manifest_sha256), _json_sha256(manifest))
        or (
            manifest.get("run_id_sha256"),
            manifest.get("binding_commitment_sha256"),
            manifest.get("infinity_target_identity_sha256"),
            manifest.get("space_id"),
            manifest.get("cleanup_plan_sha256"),
        )
        != (
            row.run_id_sha256,
            row.binding_commitment_sha256,
            row.infinity_target_identity_sha256,
            row.space_id,
            cleanup_plan_sha256,
        )
    ):
        raise RuntimeError("benchmark_projection_manifest_invalid")
    if (row.state, row.projection_cleanup_state, manifest is not None) not in {
        ("active", "unsealed", False),
        ("active", "sealed", True),
        ("cleanup_pending", "blocked", False),
        ("cleanup_pending", "pending", True),
        ("cleanup_complete", "complete", True),
        ("cleanup_aborted", "unsealed_abort_complete", False),
    }:
        _invalid()

    receipt = (
        receipt_from_json(row.cleanup_receipt_json)
        if row.cleanup_receipt_json is not None
        else None
    )
    _require_receipt_lifecycle(row, receipt)
    completion = _completion(row)
    _require_completion_lifecycle(row, receipt, completion)
    return BenchmarkRunRegistryRecord(
        run_id_sha256=row.run_id_sha256,
        binding_commitment_sha256=row.binding_commitment_sha256,
        infinity_target_identity_sha256=row.infinity_target_identity_sha256,
        space_id=row.space_id,
        space_slug=row.space_slug,
        idempotency_key_sha256=row.idempotency_key_sha256,
        registration_fingerprint_sha256=row.registration_fingerprint_sha256,
        state=row.state,
        projection_manifest_json=manifest,
        projection_manifest_sha256=manifest_sha256,
        projection_cleanup_state=row.projection_cleanup_state,
        cleanup_fingerprint_sha256=row.cleanup_fingerprint_sha256,
        cleanup_receipt=receipt,
        finalization_fingerprint_sha256=row.finalization_fingerprint_sha256,
        completion_receipt=completion,
        completed_at=completion.completed_at if completion is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        cleanup_plan_json=cleanup_plan,
        cleanup_plan_sha256=cleanup_plan_sha256,
        cleanup_plan_state=row.cleanup_plan_state,
    )


def _cleanup_plan(
    row: MemoryComparisonBenchmarkRunRow,
) -> tuple[dict[str, object] | None, str | None]:
    value, digest = row.cleanup_plan_json, row.cleanup_plan_sha256
    if row.cleanup_plan_state == "recovery_blocked":
        if value is not None or digest is not None:
            raise RuntimeError("benchmark_cleanup_plan_invalid")
        return None, None
    if row.cleanup_plan_state != "sealed":
        raise RuntimeError("benchmark_cleanup_plan_invalid")
    try:
        validated = validate_managed_benchmark_cleanup_plan(
            value,
            digest,
            run_id_sha256=row.run_id_sha256,
            binding_commitment_sha256=row.binding_commitment_sha256,
            infinity_target_identity_sha256=row.infinity_target_identity_sha256,
            space_slug=row.space_slug,
        )
    except (MemoryConflictError, MemoryValidationError) as exc:
        raise RuntimeError("benchmark_cleanup_plan_invalid") from exc
    return validated.value, validated.sha256


def _require_receipt_lifecycle(
    row: MemoryComparisonBenchmarkRunRow,
    receipt: BenchmarkCleanupReceipt | None,
) -> None:
    if row.state == "active" and (
        row.cleanup_fingerprint_sha256 is not None or receipt is not None
    ):
        _invalid()
    if row.state != "active" and (row.cleanup_fingerprint_sha256 is None or receipt is None):
        _invalid()
    if receipt is not None and (
        receipt.run_id_sha256,
        receipt.space_id,
        receipt.space_slug,
    ) != (row.run_id_sha256, row.space_id, row.space_slug):
        _invalid()


def _completion(
    row: MemoryComparisonBenchmarkRunRow,
) -> BenchmarkCleanupCompletionReceipt | BenchmarkAbortCompletionReceipt | None:
    if row.completion_receipt_json is None:
        return None
    if row.completion_receipt_json.get("disposition") == "abort_complete":
        return abort_completion_receipt_from_json(row.completion_receipt_json)
    return completion_receipt_from_json(row.completion_receipt_json)


def _require_completion_lifecycle(row, receipt, completion) -> None:
    terminal = row.state in {"cleanup_complete", "cleanup_aborted"}
    fields_present = (
        row.finalization_fingerprint_sha256 is not None
        and completion is not None
        and row.completed_at is not None
    )
    if terminal != fields_present:
        _invalid()
    if completion is None:
        return
    invalid = (
        receipt is None
        or completion.run_id_sha256 != row.run_id_sha256
        or completion.space_id != row.space_id
        or completion.space_slug != row.space_slug
        or completion.cleanup_initiation_receipt_sha256 != receipt.receipt_sha256
        or not same_completion_timestamp(completion.completed_at, row.completed_at)
    )
    if row.state == "cleanup_complete":
        invalid = invalid or (
            type(completion) is not BenchmarkCleanupCompletionReceipt
            or completion.projection_manifest_sha256 != row.projection_manifest_sha256
        )
    else:
        invalid = invalid or (
            type(completion) is not BenchmarkAbortCompletionReceipt
            or completion.binding_commitment_sha256 != row.binding_commitment_sha256
            or completion.infinity_target_identity_sha256 != row.infinity_target_identity_sha256
        )
    if invalid:
        _invalid()


def _valid_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _json_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _invalid() -> None:
    raise RuntimeError("benchmark_run_registry_invalid")


__all__ = ("benchmark_run_record_from_row",)
