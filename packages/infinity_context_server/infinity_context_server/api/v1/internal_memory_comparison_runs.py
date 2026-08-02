"""Hidden internal API for Infinity canonical managed benchmark lifecycle."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Response, status
from infinity_context_core.application import (
    CleanupBenchmarkRunCommand,
    FinalizeBenchmarkRunCleanupCommand,
    FinalizeUnsealedBenchmarkAbortCommand,
    GetBenchmarkRunLifecycleQuery,
    RegisterBenchmarkRunCommand,
    SealProjectionManifestCommand,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkCleanupCompletionReceipt,
    BenchmarkCleanupReceipt,
)
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import (
    require_strict_admin_service_token,
)
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.composition import Container

router = APIRouter(
    prefix="/internal/memory-comparison/runs",
    tags=["internal-memory-comparison"],
    dependencies=[Depends(require_strict_admin_service_token)],
)
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class RegisterBenchmarkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^memory-comparison-run-registration\.v1$")
    run_id_sha256: str = Field(pattern=_DIGEST_PATTERN)
    binding_commitment_sha256: str = Field(pattern=_DIGEST_PATTERN)
    infinity_target_identity_sha256: str = Field(pattern=_DIGEST_PATTERN)
    space_slug: str = Field(
        min_length=19,
        max_length=98,
        pattern=r"^memory-comparison-[a-z0-9-]{1,80}$",
    )


class CleanupBenchmarkRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^memory-comparison-run-cleanup\.v1$")
    binding_commitment_sha256: str = Field(pattern=_DIGEST_PATTERN)
    infinity_target_identity_sha256: str = Field(pattern=_DIGEST_PATTERN)
    space_id: str = Field(min_length=1, max_length=80)
    space_slug: str = Field(
        min_length=19,
        max_length=98,
        pattern=r"^memory-comparison-[a-z0-9-]{1,80}$",
    )


class FinalizeBenchmarkRunCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = Field(pattern=r"^memory-comparison-run-cleanup-finalize\.v1$")
    receipt_sha256: str = Field(pattern=_DIGEST_PATTERN)


class FinalizeUnsealedBenchmarkAbortRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = Field(pattern=r"^memory-comparison-run-abort-finalize\.v1$")
    binding_commitment_sha256: str = Field(pattern=_DIGEST_PATTERN)
    infinity_target_identity_sha256: str = Field(pattern=_DIGEST_PATTERN)
    space_id: str = Field(min_length=1, max_length=80)
    space_slug: str = Field(
        min_length=19,
        max_length=98,
        pattern=r"^memory-comparison-[a-z0-9-]{1,80}$",
    )
    receipt_sha256: str = Field(pattern=_DIGEST_PATTERN)


class SealProjectionManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: str = Field(pattern=r"^memory-comparison-projection-manifest-seal\.v1$")
    projection_manifest_sha256: str = Field(pattern=_DIGEST_PATTERN)
    projection_manifest: dict[str, object]


@router.post("", include_in_schema=False, status_code=status.HTTP_201_CREATED)
async def register_benchmark_run(
    request: RegisterBenchmarkRunRequest,
    response: Response,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=240),
    ],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.register_benchmark_run.execute(
        RegisterBenchmarkRunCommand(
            run_id_sha256=request.run_id_sha256,
            binding_commitment_sha256=request.binding_commitment_sha256,
            infinity_target_identity_sha256=request.infinity_target_identity_sha256,
            space_slug=request.space_slug,
            idempotency_key_sha256=_sha256(idempotency_key),
        )
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    record = result.record
    return {
        "data": {
            "schema_version": "memory-comparison-run-registration-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": record.run_id_sha256,
            "binding_commitment_sha256": record.binding_commitment_sha256,
            "infinity_target_identity_sha256": record.infinity_target_identity_sha256,
            "space_id": record.space_id,
            "space_slug": record.space_slug,
            "state": record.state,
            "created": result.created,
        }
    }


@router.put("/{run_id_sha256}/projection-manifest", include_in_schema=False)
async def seal_projection_manifest(
    run_id_sha256: Annotated[str, Path(pattern=_DIGEST_PATTERN)],
    request: SealProjectionManifestRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.seal_projection_manifest.execute(
        SealProjectionManifestCommand(
            run_id_sha256=run_id_sha256,
            projection_manifest_json=request.projection_manifest,
            projection_manifest_sha256=request.projection_manifest_sha256,
        )
    )
    record = result.record
    return {
        "data": {
            "schema_version": "memory-comparison-projection-manifest-seal-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": record.run_id_sha256,
            "binding_commitment_sha256": record.binding_commitment_sha256,
            "infinity_target_identity_sha256": (record.infinity_target_identity_sha256),
            "projection_manifest_sha256": record.projection_manifest_sha256,
            "state": record.state,
            "projection_cleanup_state": record.projection_cleanup_state,
            "replayed": result.replayed,
        }
    }


@router.get("/{run_id_sha256}/cleanup", include_in_schema=False)
async def get_benchmark_run_lifecycle(
    run_id_sha256: Annotated[str, Path(pattern=_DIGEST_PATTERN)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_benchmark_run_lifecycle.execute(
        GetBenchmarkRunLifecycleQuery(run_id_sha256=run_id_sha256)
    )
    record = result.record
    return {
        "data": {
            "schema_version": "memory-comparison-run-lifecycle-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": record.run_id_sha256,
            "binding_commitment_sha256": record.binding_commitment_sha256,
            "infinity_target_identity_sha256": (record.infinity_target_identity_sha256),
            "space_id": record.space_id,
            "space_slug": record.space_slug,
            "state": record.state,
            "projection_cleanup_state": record.projection_cleanup_state,
            "projection_manifest_sha256": record.projection_manifest_sha256,
            "cleanup_receipt": _cleanup_receipt_json(record.cleanup_receipt),
            "completion_receipt": _completion_receipt_json(record.completion_receipt),
        }
    }


@router.delete("/{run_id_sha256}", include_in_schema=False)
async def cleanup_benchmark_run(
    run_id_sha256: Annotated[str, Path(pattern=_DIGEST_PATTERN)],
    request: CleanupBenchmarkRunRequest,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=240),
    ],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.cleanup_benchmark_run.execute(
        CleanupBenchmarkRunCommand(
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=request.binding_commitment_sha256,
            infinity_target_identity_sha256=request.infinity_target_identity_sha256,
            space_id=request.space_id,
            space_slug=request.space_slug,
            idempotency_key_sha256=_sha256(idempotency_key),
        )
    )
    receipt = result.receipt
    return {
        "data": {
            "schema_version": "memory-comparison-run-cleanup-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": receipt.run_id_sha256,
            "space_id": receipt.space_id,
            "space_slug": receipt.space_slug,
            "state": "cleanup_pending",
            "disposition": receipt.disposition,
            "projection_cleanup": result.projection_cleanup_state,
            "counts": {
                "facts": receipt.counts.facts,
                "documents": receipt.counts.documents,
                "chunks": receipt.counts.chunks,
                "episodes": receipt.counts.episodes,
                "threads": receipt.counts.threads,
                "memory_scopes": receipt.counts.memory_scopes,
                "obsolete_upsert_jobs": receipt.counts.obsolete_upsert_jobs,
                "vector_delete_jobs": receipt.counts.vector_delete_jobs,
                "graph_delete_jobs": receipt.counts.graph_delete_jobs,
                "cognee_delete_jobs": receipt.counts.cognee_delete_jobs,
            },
            "vector_delete_outbox_ids": list(receipt.vector_delete_outbox_ids),
            "graph_delete_outbox_ids": list(receipt.graph_delete_outbox_ids),
            "cognee_delete_outbox_ids": list(receipt.cognee_delete_outbox_ids),
            "receipt_sha256": receipt.receipt_sha256,
            "replayed": result.replayed,
        }
    }


@router.post(
    "/{run_id_sha256}/cleanup/finalize",
    include_in_schema=False,
)
async def finalize_benchmark_run_cleanup(
    run_id_sha256: Annotated[str, Path(pattern=_DIGEST_PATTERN)],
    request: FinalizeBenchmarkRunCleanupRequest,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=240),
    ],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.finalize_benchmark_run_cleanup.execute(
        FinalizeBenchmarkRunCleanupCommand(
            run_id_sha256=run_id_sha256,
            expected_cleanup_receipt_sha256=request.receipt_sha256,
            idempotency_key_sha256=_sha256(idempotency_key),
        )
    )
    receipt = result.receipt
    return {
        "data": {
            "schema_version": "memory-comparison-run-cleanup-finalize-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": receipt.run_id_sha256,
            "space_id": receipt.space_id,
            "space_slug": receipt.space_slug,
            "state": "cleanup_complete",
            "disposition": receipt.disposition,
            "projection_cleanup": receipt.projection_cleanup,
            "projection_manifest_sha256": receipt.projection_manifest_sha256,
            "cleanup_initiation_receipt_sha256": (receipt.cleanup_initiation_receipt_sha256),
            "projection_absence_proof_sha256": (receipt.projection_absence_proof_sha256),
            "completed_at": _rfc3339(receipt.completed_at),
            "receipt_sha256": receipt.receipt_sha256,
            "replayed": result.replayed,
        }
    }


@router.post(
    "/{run_id_sha256}/cleanup/abort/finalize",
    include_in_schema=False,
)
async def finalize_unsealed_benchmark_abort(
    run_id_sha256: Annotated[str, Path(pattern=_DIGEST_PATTERN)],
    request: FinalizeUnsealedBenchmarkAbortRequest,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=240),
    ],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.finalize_unsealed_benchmark_abort.execute(
        FinalizeUnsealedBenchmarkAbortCommand(
            run_id_sha256=run_id_sha256,
            binding_commitment_sha256=request.binding_commitment_sha256,
            infinity_target_identity_sha256=request.infinity_target_identity_sha256,
            space_id=request.space_id,
            space_slug=request.space_slug,
            expected_cleanup_receipt_sha256=request.receipt_sha256,
            idempotency_key_sha256=_sha256(idempotency_key),
        )
    )
    receipt = result.receipt
    return {
        "data": {
            "schema_version": "memory-comparison-run-abort-finalize-response.v1",
            "authority": "infinity_canonical",
            "run_id_sha256": receipt.run_id_sha256,
            "binding_commitment_sha256": receipt.binding_commitment_sha256,
            "infinity_target_identity_sha256": receipt.infinity_target_identity_sha256,
            "space_id": receipt.space_id,
            "space_slug": receipt.space_slug,
            "state": "cleanup_aborted",
            "disposition": receipt.disposition,
            "projection_cleanup": receipt.projection_cleanup,
            "cleanup_initiation_receipt_sha256": (receipt.cleanup_initiation_receipt_sha256),
            "cleanup_verification_sha256": receipt.cleanup_verification_sha256,
            "completed_at": _rfc3339(receipt.completed_at),
            "receipt_sha256": receipt.receipt_sha256,
            "replayed": result.replayed,
        }
    }


def _cleanup_receipt_json(
    receipt: BenchmarkCleanupReceipt | None,
) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "run_id_sha256": receipt.run_id_sha256,
        "space_id": receipt.space_id,
        "space_slug": receipt.space_slug,
        "disposition": receipt.disposition,
        "projection_cleanup": receipt.projection_cleanup,
        "counts": {
            "facts": receipt.counts.facts,
            "documents": receipt.counts.documents,
            "chunks": receipt.counts.chunks,
            "episodes": receipt.counts.episodes,
            "threads": receipt.counts.threads,
            "memory_scopes": receipt.counts.memory_scopes,
            "obsolete_upsert_jobs": receipt.counts.obsolete_upsert_jobs,
            "vector_delete_jobs": receipt.counts.vector_delete_jobs,
            "graph_delete_jobs": receipt.counts.graph_delete_jobs,
            "cognee_delete_jobs": receipt.counts.cognee_delete_jobs,
        },
        "vector_delete_outbox_ids": list(receipt.vector_delete_outbox_ids),
        "graph_delete_outbox_ids": list(receipt.graph_delete_outbox_ids),
        "cognee_delete_outbox_ids": list(receipt.cognee_delete_outbox_ids),
        "receipt_sha256": receipt.receipt_sha256,
    }


def _completion_receipt_json(
    receipt: BenchmarkCleanupCompletionReceipt | BenchmarkAbortCompletionReceipt | None,
) -> dict[str, Any] | None:
    if receipt is None:
        return None
    if type(receipt) is BenchmarkAbortCompletionReceipt:
        return {
            "run_id_sha256": receipt.run_id_sha256,
            "binding_commitment_sha256": receipt.binding_commitment_sha256,
            "infinity_target_identity_sha256": receipt.infinity_target_identity_sha256,
            "space_id": receipt.space_id,
            "space_slug": receipt.space_slug,
            "disposition": receipt.disposition,
            "projection_cleanup": receipt.projection_cleanup,
            "cleanup_initiation_receipt_sha256": (receipt.cleanup_initiation_receipt_sha256),
            "cleanup_verification_sha256": receipt.cleanup_verification_sha256,
            "completed_at": _rfc3339(receipt.completed_at),
            "receipt_sha256": receipt.receipt_sha256,
        }
    return {
        "run_id_sha256": receipt.run_id_sha256,
        "space_id": receipt.space_id,
        "space_slug": receipt.space_slug,
        "disposition": receipt.disposition,
        "projection_cleanup": receipt.projection_cleanup,
        "projection_manifest_sha256": receipt.projection_manifest_sha256,
        "cleanup_initiation_receipt_sha256": (receipt.cleanup_initiation_receipt_sha256),
        "projection_absence_proof_sha256": receipt.projection_absence_proof_sha256,
        "completed_at": _rfc3339(receipt.completed_at),
        "receipt_sha256": receipt.receipt_sha256,
    }


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ("router",)
