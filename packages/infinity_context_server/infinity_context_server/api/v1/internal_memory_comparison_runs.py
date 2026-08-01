"""Hidden internal API for Infinity canonical managed benchmark lifecycle."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Response, status
from infinity_context_core.application import (
    CleanupBenchmarkRunCommand,
    RegisterBenchmarkRunCommand,
    SealProjectionManifestCommand,
)
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.composition import Container

router = APIRouter(
    prefix="/internal/memory-comparison/runs",
    tags=["internal-memory-comparison"],
    dependencies=[Depends(require_service_token)],
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


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ("router",)
