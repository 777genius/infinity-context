"""Deterministic exact-document reconciliation policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .errors import DocumentIngestionValidationError
from .source_document import DocumentIngestionScope, SourceDocumentOrigin

DocumentReconciliationState: TypeAlias = Literal[
    "present",
    "processing",
    "indexed",
    "deleted_or_proven_absent",
    "conflict",
    "unavailable",
]
DocumentVisibilityEvidence: TypeAlias = Literal[
    "accepted",
    "processing",
    "indexed",
    "not_queryable",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class ExactDocumentIdentity:
    """Opaque consumer identity, interpreted only inside one exact canonical scope."""

    scope: DocumentIngestionScope
    origin: SourceDocumentOrigin
    projection_generation: str | None = None
    profile_generation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, DocumentIngestionScope):
            raise DocumentIngestionValidationError("scope has an invalid type")
        if not isinstance(self.origin, SourceDocumentOrigin):
            raise DocumentIngestionValidationError("origin has an invalid type")
        for name in ("projection_generation", "profile_generation"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise DocumentIngestionValidationError(f"{name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class ExactDocumentObservation:
    """One canonical read observation supplied by a narrow adapter."""

    document_id: str
    canonical_status: str
    projection_generation: str | None
    profile_generation: str | None
    visibility: DocumentVisibilityEvidence
    idempotency_key_matches: bool | None = None
    binding_conflict: bool = False


@dataclass(frozen=True, slots=True)
class ExactDocumentReconciliation:
    state: DocumentReconciliationState
    identity: ExactDocumentIdentity
    document_id: str | None = None
    canonical_status: str | None = None
    projection_generation: str | None = None
    profile_generation: str | None = None
    visibility: DocumentVisibilityEvidence = "not_queryable"
    idempotency_key_matches: bool | None = None


def reconcile_exact_document(
    identity: ExactDocumentIdentity,
    observations: tuple[ExactDocumentObservation, ...],
) -> ExactDocumentReconciliation:
    """Fail closed while mapping canonical evidence to the public bounded states."""

    if not observations:
        return ExactDocumentReconciliation("deleted_or_proven_absent", identity)
    if len(observations) != 1:
        return ExactDocumentReconciliation("conflict", identity)
    observed = observations[0]
    common = dict(
        document_id=observed.document_id,
        canonical_status=observed.canonical_status,
        projection_generation=observed.projection_generation,
        profile_generation=observed.profile_generation,
        visibility=observed.visibility,
        idempotency_key_matches=observed.idempotency_key_matches,
    )
    if observed.canonical_status in {"deleted", "superseded"}:
        return ExactDocumentReconciliation("deleted_or_proven_absent", identity, **common)
    if observed.binding_conflict:
        return ExactDocumentReconciliation("conflict", identity, **common)
    if observed.canonical_status != "active":
        return ExactDocumentReconciliation("conflict", identity, **common)
    if (
        identity.projection_generation is not None
        and observed.projection_generation != identity.projection_generation
    ):
        return ExactDocumentReconciliation("conflict", identity, **common)
    if (
        identity.profile_generation is not None
        and observed.profile_generation != identity.profile_generation
    ):
        return ExactDocumentReconciliation("unavailable", identity, **common)
    state_by_visibility: dict[DocumentVisibilityEvidence, DocumentReconciliationState] = {
        "accepted": "present",
        "processing": "processing",
        "indexed": "indexed",
        "not_queryable": "present",
        "unavailable": "unavailable",
    }
    return ExactDocumentReconciliation(state_by_visibility[observed.visibility], identity, **common)


__all__ = (
    "DocumentReconciliationState",
    "DocumentVisibilityEvidence",
    "ExactDocumentIdentity",
    "ExactDocumentObservation",
    "ExactDocumentReconciliation",
    "reconcile_exact_document",
)
