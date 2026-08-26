"""Strict-admin, bounded and idempotent Retrieval V2 profile operations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from infinity_context_core.features.context_building.public import RetrievalProfileIdentity
from pydantic import BaseModel, ConfigDict, Field, model_validator

from infinity_context_server.api.auth import require_strict_admin_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.composition import Container

router = APIRouter(
    prefix="/internal/retrieval-profiles",
    tags=["internal-retrieval-profiles"],
    dependencies=[Depends(require_strict_admin_service_token)],
)


class RetrievalProfileOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "rebuild", "attest", "activate"]
    idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    profile_id: str = Field(min_length=1, max_length=120)
    generation: str | None = Field(default=None, min_length=1, max_length=160)
    profile_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    collection_name: str | None = Field(default=None, min_length=1, max_length=240)
    page_limit: int = Field(default=1, ge=1, le=100)

    @model_validator(mode="after")
    def require_create_identity(self):
        values = (self.generation, self.profile_digest, self.collection_name)
        if self.operation == "create" and any(value is None for value in values):
            raise ValueError("create requires the complete immutable profile identity")
        if self.operation != "create" and any(value is not None for value in values):
            raise ValueError("immutable profile identity fields are create-only")
        return self


class RetrievalProfileFenceRecoveryRequest(BaseModel):
    """Exact operator assertion; elapsed time alone never invokes this path."""

    model_config = ConfigDict(extra="forbid")

    fence_kind: Literal["reader", "provider_mutation"]
    profile_id: str = Field(min_length=1, max_length=120)
    operation_id: str = Field(min_length=1, max_length=120)
    owner_instance_id: str = Field(min_length=1, max_length=120)
    owner_generation: str = Field(min_length=1, max_length=120)
    stale_deadline: datetime
    maintenance_generation: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    activation_lease_id: str | None = Field(default=None, min_length=1, max_length=120)
    mutation_epoch: int | None = Field(default=None, ge=1)
    provider_receipt_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_exact_fence_identity(self):
        if self.stale_deadline.utcoffset() is None:
            raise ValueError("stale_deadline must be timezone-aware")
        if self.reason != self.reason.strip():
            raise ValueError("reason must be normalized")
        if self.fence_kind == "reader":
            if self.activation_lease_id is None:
                raise ValueError("reader recovery requires activation_lease_id")
            if self.mutation_epoch is not None or self.provider_receipt_id is not None:
                raise ValueError("reader recovery forbids provider reconciliation fields")
        elif (
            self.activation_lease_id is not None
            or self.mutation_epoch is None
            or self.provider_receipt_id is None
        ):
            raise ValueError("provider recovery requires epoch and provider receipt")
        return self


@router.post("/recoveries", include_in_schema=False)
async def recover_retrieval_profile_fence(
    request: RetrievalProfileFenceRecoveryRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, object]:
    try:
        return await container.retrieval_profile_lifecycle.registry.recover_abandoned_fence(
            **request.model_dump()
        )
    except RuntimeError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=code if code.startswith("retrieval_profile_") else "retrieval_profile_failed",
        ) from exc


@router.post("/operations", include_in_schema=False)
async def operate_retrieval_profile(
    request: RetrievalProfileOperationRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, object]:
    lifecycle = container.retrieval_profile_lifecycle
    now = container.clock.now()
    fingerprint = _request_fingerprint(request)
    try:
        async with lifecycle.registry.operator_operation_lock(request.idempotency_key):
            return await _operate_once(request, lifecycle, now, fingerprint)
    except TimeoutError:
        return {
            **_result(request, "in_progress", lifecycle),
            "accepted": False,
            "rejection_reasons": [],
        }
    except RuntimeError as exc:
        code = str(exc)
        if code in {
            "retrieval_profile_attestation_incomplete",
            "retrieval_profile_attestation_deadline",
            "retrieval_profile_attestation_byte_budget",
            "retrieval_profile_attestation_cursor_raced",
            "retrieval_profile_attestation_page_raced",
            "retrieval_profile_provider_mutation_active",
        }:
            return {
                **_result(request, "in_progress", lifecycle),
                "accepted": False,
                "rejection_reasons": [],
            }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=code if code.startswith("retrieval_profile_") else "retrieval_profile_failed",
        ) from exc


async def _operate_once(request, lifecycle, now, fingerprint) -> dict[str, object]:
    replay = await lifecycle.registry.operator_receipt(
        idempotency_key=request.idempotency_key,
        request_fingerprint=fingerprint,
    )
    if replay is not None:
        return replay
    await lifecycle.registry.reserve_operator_operation(
        idempotency_key=request.idempotency_key,
        request_fingerprint=fingerprint,
        operation=request.operation,
        profile_id=request.profile_id,
        now=now,
    )
    if request.operation == "create":
        await lifecycle.create_building(
            RetrievalProfileIdentity(
                request.profile_id,
                request.generation or "",
                request.profile_digest or "",
                request.collection_name or "",
            ),
            now=now,
        )
        result = _result(request, "complete", lifecycle)
        return await _record_result(lifecycle, request, fingerprint, result, now)
    if request.operation == "rebuild":
        atomic_rebuild = getattr(lifecycle, "rebuild_profile_page_atomic", None)
        if atomic_rebuild is not None:
            return await atomic_rebuild(
                request.profile_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                page_limit=request.page_limit,
                now=now,
            )
        result = None
        for _ in range(request.page_limit):
            result = await lifecycle.rebuild_profile_page(request.profile_id, now=now)
            if result.complete:
                break
        if result is None or result.profile_id != request.profile_id:
            raise RuntimeError("retrieval_profile_building_mismatch")
        result = {
            **_result(request, "complete" if result.complete else "pending", lifecycle),
            "projected_count": result.projected_count,
            "next_cursor": result.next_cursor,
        }
        return await _record_result(lifecycle, request, fingerprint, result, now)
    if request.operation == "attest":
        decision = await lifecycle.attest(
            request.profile_id,
            operation_id=_operation_id(request),
            now=now,
        )
    else:
        decision = await lifecycle.activate(
            request.profile_id,
            operation_id=_operation_id(request),
            now=now,
        )
    result = {
        **_result(request, "complete" if decision.accepted else "refused", lifecycle),
        "accepted": decision.accepted,
        "rejection_reasons": list(decision.rejection_reasons),
    }
    return await _record_result(lifecycle, request, fingerprint, result, now)


def _operation_id(request: RetrievalProfileOperationRequest) -> str:
    digest = hashlib.sha256(
        f"{request.operation}\0{request.profile_id}\0{request.idempotency_key}".encode()
    ).hexdigest()
    return f"operator-{digest}"


def _request_fingerprint(request: RetrievalProfileOperationRequest) -> str:
    canonical = json.dumps(
        request.model_dump(exclude={"idempotency_key"}),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(b"retrieval-profile-operator.v1\0" + canonical).hexdigest()


async def _record_result(lifecycle, request, fingerprint, result, now):
    return await lifecycle.registry.record_operator_receipt(
        idempotency_key=request.idempotency_key,
        request_fingerprint=fingerprint,
        operation=request.operation,
        profile_id=request.profile_id,
        result=result,
        now=now,
    )


def _result(
    request: RetrievalProfileOperationRequest, phase: str, lifecycle=None
) -> dict[str, object]:
    result = {
        "operation": request.operation,
        "profile_id": request.profile_id,
        "idempotency_key": request.idempotency_key,
        "phase": phase,
    }
    provenance = getattr(lifecycle, "runtime_trust_provenance", None)
    if provenance is not None:
        result["runtime_trust_provenance"] = provenance()
    return result


__all__ = ("router",)
