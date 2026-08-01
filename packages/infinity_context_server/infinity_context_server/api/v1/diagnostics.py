"""Production-safe diagnostics API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from infinity_context_core.ports.graph_evidence import (
    GraphProjectionDeletePass,
    GraphProjectionIdentitySnapshot,
)
from infinity_context_core.ports.vector_projection_evidence import (
    VectorProjectionDeleteEvidence,
    VectorProjectionPointIdentity,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.composition import Container
from infinity_context_server.derived_identity_evidence import (
    MAX_EXPECTED_IDENTITIES,
    MAX_GRAPH_PHYSICAL_IDENTITIES,
    CanonicalProjectionScope,
    DerivedProjectionPresence,
    GraphitiDeleteResult,
    QdrantDeleteResult,
)
from infinity_context_server.diagnostics import (
    adapter_diagnostics,
    memory_scope_diagnostics,
    operational_metrics,
    outbox_diagnostics,
    storage_diagnostics,
)

router = APIRouter(
    prefix="/diagnostics",
    tags=["diagnostics"],
    dependencies=[Depends(require_service_token)],
)


class DerivedPresenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_chunk_ids: list[str] = Field(default_factory=list, max_length=MAX_EXPECTED_IDENTITIES)
    expected_fact_ids: list[str] = Field(default_factory=list, max_length=MAX_EXPECTED_IDENTITIES)

    @model_validator(mode="after")
    def require_identity_manifest(self) -> DerivedPresenceRequest:
        if not self.expected_chunk_ids and not self.expected_fact_ids:
            raise ValueError("at least one expected identity is required")
        return self


class QdrantDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_chunk_ids: list[str] = Field(min_length=1, max_length=MAX_EXPECTED_IDENTITIES)
    target_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GraphitiIdentityManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_ids: list[str] = Field(default_factory=list, max_length=MAX_GRAPH_PHYSICAL_IDENTITIES)
    entity_ids: list[str] = Field(default_factory=list, max_length=MAX_GRAPH_PHYSICAL_IDENTITIES)
    mentions_edge_ids: list[str] = Field(
        default_factory=list, max_length=MAX_GRAPH_PHYSICAL_IDENTITIES
    )
    relates_to_edge_ids: list[str] = Field(
        default_factory=list, max_length=MAX_GRAPH_PHYSICAL_IDENTITIES
    )


class GraphitiDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_fact_ids: list[str] = Field(min_length=1, max_length=MAX_EXPECTED_IDENTITIES)
    identity_manifest: GraphitiIdentityManifestRequest
    target_commitment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/derived-evidence/presence", include_in_schema=False)
async def observe_derived_identity_presence(
    request: DerivedPresenceRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    evidence = await container.derived_identity_evidence.observe_presence(
        scope=_scope(request),
        chunk_ids=tuple(request.expected_chunk_ids),
        fact_ids=tuple(request.expected_fact_ids),
    )
    return {"data": _presence_response(evidence)}


@router.post("/derived-evidence/qdrant/delete", include_in_schema=False)
async def delete_qdrant_identity_manifest(
    request: QdrantDeleteRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    evidence = await container.derived_identity_evidence.delete_qdrant_two_pass(
        scope=_scope(request),
        chunk_ids=tuple(request.expected_chunk_ids),
        target_commitment_sha256=request.target_commitment_sha256,
        manifest_binding_sha256=request.manifest_binding_sha256,
    )
    return {
        "data": _qdrant_delete_response(
            evidence,
            target_commitment_sha256=request.target_commitment_sha256,
            manifest_binding_sha256=request.manifest_binding_sha256,
        )
    }


@router.post("/derived-evidence/graphiti/delete", include_in_schema=False)
async def delete_graphiti_identity_manifest(
    request: GraphitiDeleteRequest,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    manifest = request.identity_manifest
    evidence = await container.derived_identity_evidence.delete_graphiti_two_pass(
        scope=_scope(request),
        fact_ids=tuple(request.expected_fact_ids),
        episode_ids=tuple(manifest.episode_ids),
        entity_ids=tuple(manifest.entity_ids),
        mentions_edge_ids=tuple(manifest.mentions_edge_ids),
        relates_to_edge_ids=tuple(manifest.relates_to_edge_ids),
        target_commitment_sha256=request.target_commitment_sha256,
        manifest_binding_sha256=request.manifest_binding_sha256,
    )
    return {
        "data": _graphiti_delete_response(
            evidence,
            target_commitment_sha256=request.target_commitment_sha256,
            manifest_binding_sha256=request.manifest_binding_sha256,
        )
    }


@router.get("/adapters")
async def get_adapter_diagnostics(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return {"data": await adapter_diagnostics(container)}


@router.get("/outbox")
async def get_outbox_diagnostics(
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> dict[str, Any]:
    return {
        "data": await outbox_diagnostics(container, limit=limit, cursor=cursor),
    }


@router.get("/memory-scope/{memory_scope_id}")
async def get_memory_scope_diagnostics(
    memory_scope_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return {"data": await memory_scope_diagnostics(container, memory_scope_id=memory_scope_id)}


@router.get("/metrics")
async def get_operational_metrics(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return {"data": await operational_metrics(container)}


@router.get("/storage")
async def get_storage_diagnostics(
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    return {"data": storage_diagnostics(container)}


def _scope(request: object) -> CanonicalProjectionScope:
    return CanonicalProjectionScope(
        space_id=str(request.space_id),
        memory_scope_id=str(request.memory_scope_id),
        thread_id=request.thread_id,
    )


def _presence_response(evidence: DerivedProjectionPresence) -> dict[str, Any]:
    qdrant = evidence.qdrant
    graphiti = evidence.graphiti
    return {
        "scope": {
            "space_id": evidence.scope.space_id,
            "memory_scope_id": evidence.scope.memory_scope_id,
            "thread_id": evidence.scope.thread_id,
        },
        "outbox": {
            "complete": evidence.outbox.complete,
            "done_chunk_ids": list(evidence.outbox.done_chunk_ids),
            "done_fact_ids": list(evidence.outbox.done_fact_ids),
            "done_event_count": evidence.outbox.done_event_count,
        },
        "lanes": {
            "qdrant": None
            if qdrant is None
            else {
                "projection_version": qdrant.evidence.scope.projection_version,
                "target_commitment_sha256": qdrant.evidence.target_commitment_sha256,
                "manifest_binding_sha256": qdrant.manifest_binding_sha256,
                "expected": [_point_response(item) for item in qdrant.evidence.expected],
                "observed": [_point_response(item) for item in qdrant.evidence.observed],
                "scoped_point_ids": list(qdrant.evidence.scoped_point_ids),
                "exact_scoped_count": qdrant.evidence.exact_scoped_count,
                "complete": qdrant.evidence.complete,
            },
            "graphiti": None
            if graphiti is None
            else {
                "target_commitment_sha256": graphiti.target_commitment_sha256,
                "manifest_binding_sha256": graphiti.manifest_binding_sha256,
                "identity_manifest": _graph_snapshot_response(graphiti.snapshot),
                "exact_identity_count": graphiti.snapshot.identity_count,
                "complete": True,
            },
        },
    }


def _qdrant_delete_response(
    evidence: QdrantDeleteResult,
    *,
    target_commitment_sha256: str,
    manifest_binding_sha256: str,
) -> dict[str, Any]:
    return {
        "lane": "qdrant",
        "target_commitment_sha256": target_commitment_sha256,
        "manifest_binding_sha256": manifest_binding_sha256,
        "verified_absent": (
            evidence.first_pass.verified_absent and evidence.second_pass.verified_absent
        ),
        "passes": [
            _vector_delete_pass_response(evidence.first_pass),
            _vector_delete_pass_response(evidence.second_pass),
        ],
    }


def _vector_delete_pass_response(evidence: VectorProjectionDeleteEvidence) -> dict[str, Any]:
    return {
        "pass_index": evidence.pass_index,
        "target_commitment_sha256": evidence.target_commitment_sha256,
        "expected": [_point_response(item) for item in evidence.expected],
        "present_before": [_point_response(item) for item in evidence.present_before],
        "remaining": [_point_response(item) for item in evidence.remaining],
        "scoped_point_ids_after": list(evidence.scoped_point_ids_after),
        "exact_scoped_count_after": evidence.exact_scoped_count_after,
        "delete_completed": evidence.delete_completed,
        "verified_absent": evidence.verified_absent,
        "issues": list(evidence.issues),
    }


def _graphiti_delete_response(
    result: GraphitiDeleteResult,
    *,
    target_commitment_sha256: str,
    manifest_binding_sha256: str,
) -> dict[str, Any]:
    evidence = result.evidence
    return {
        "lane": "graphiti",
        "target_commitment_sha256": target_commitment_sha256,
        "manifest_binding_sha256": manifest_binding_sha256,
        "verified_absent": evidence.verified_absent,
        "bound_expected": _graph_snapshot_response(result.bound_expected),
        "delete_expected": _graph_snapshot_response(evidence.expected),
        "passes": [
            _graph_delete_pass_response(evidence.first_pass),
            _graph_delete_pass_response(evidence.second_pass),
        ],
    }


def _graph_delete_pass_response(evidence: GraphProjectionDeletePass) -> dict[str, Any]:
    return {
        "pass_index": evidence.pass_index,
        "before": _graph_snapshot_response(evidence.before),
        "deleted": _graph_snapshot_response(evidence.deleted),
        "group_readback": _graph_snapshot_response(evidence.group_readback),
        "global_readback": _graph_snapshot_response(evidence.global_readback),
        "verified_absent": evidence.group_readback.empty and evidence.global_readback.empty,
    }


def _graph_snapshot_response(snapshot: GraphProjectionIdentitySnapshot) -> dict[str, Any]:
    return {
        "episode_ids": list(snapshot.episode_ids),
        "entity_ids": list(snapshot.entity_ids),
        "mentions_edge_ids": list(snapshot.mentions_edge_ids),
        "relates_to_edge_ids": list(snapshot.relates_to_edge_ids),
    }


def _point_response(identity: VectorProjectionPointIdentity) -> dict[str, str]:
    return {"chunk_id": identity.chunk_id, "point_id": identity.point_id}
