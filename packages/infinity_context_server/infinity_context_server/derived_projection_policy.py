"""Server composition mapping for known derived projection lanes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
    DerivedProjectionLanePolicyError,
    derived_not_projected_policy_sha256,
)
from infinity_context_core.ports.graph_evidence import GraphProjectionEvidencePort
from infinity_context_core.ports.vector_projection_evidence import VectorProjectionEvidencePort

_DERIVED_LANES = ("qdrant", "graphiti")


@final
@dataclass(frozen=True, slots=True)
class DerivedProjectionLanePolicies:
    """Immutable server mapping for Qdrant and Graphiti evidence lanes."""

    qdrant: DerivedProjectionLaneDisposition
    graphiti: DerivedProjectionLaneDisposition

    def __post_init__(self) -> None:
        if (
            type(self.qdrant) is not DerivedProjectionLaneDisposition
            or type(self.graphiti) is not DerivedProjectionLaneDisposition
            or self.qdrant.lane != _DERIVED_LANES[0]
            or self.graphiti.lane != _DERIVED_LANES[1]
        ):
            raise DerivedProjectionLanePolicyError("derived_lane_policies_invalid")


def derived_projection_lane_policies(
    *,
    qdrant_enabled: bool,
    graphiti_enabled: bool,
) -> DerivedProjectionLanePolicies:
    """Freeze configured provider availability before derived evidence is requested."""

    if type(qdrant_enabled) is not bool or type(graphiti_enabled) is not bool:
        raise DerivedProjectionLanePolicyError("derived_lane_policy_settings_invalid")
    return DerivedProjectionLanePolicies(
        qdrant=_policy("qdrant", enabled=qdrant_enabled),
        graphiti=_policy("graphiti", enabled=graphiti_enabled),
    )


def validate_derived_evidence_wiring(
    lane_policies: DerivedProjectionLanePolicies,
    *,
    vector_evidence: VectorProjectionEvidencePort | None,
    graph_evidence: GraphProjectionEvidencePort | None,
    graph_target_commitment_sha256: str | None,
) -> None:
    if lane_policies.qdrant.is_not_projected:
        if vector_evidence is not None:
            raise MemoryValidationError("Not-projected Qdrant lane has an evidence adapter")
    elif vector_evidence is None:
        raise MemoryValidationError("Projected Qdrant lane lacks an evidence adapter")

    if lane_policies.graphiti.is_not_projected:
        if graph_evidence is not None or graph_target_commitment_sha256 is not None:
            raise MemoryValidationError("Not-projected Graphiti lane has configured evidence")
    elif graph_evidence is None or graph_target_commitment_sha256 is None:
        raise MemoryValidationError("Projected Graphiti lane lacks configured evidence")


def _policy(lane: str, *, enabled: bool) -> DerivedProjectionLaneDisposition:
    return DerivedProjectionLaneDisposition(
        lane=lane,
        disposition="projected" if enabled else "not_projected",
        policy_sha256=None if enabled else derived_not_projected_policy_sha256(lane),
    )


__all__ = (
    "DerivedProjectionLanePolicies",
    "derived_projection_lane_policies",
    "validate_derived_evidence_wiring",
)
