"""Opaque request-local coverage values for prompt evidence selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

_OPAQUE_ID_RE = re.compile(r"o-[0-9a-z]{1,24}\Z")


@dataclass(frozen=True, slots=True)
class EvidenceObligationId:
    """Request-local identifier that carries no source or content semantics."""

    value: str

    def __post_init__(self) -> None:
        if _OPAQUE_ID_RE.fullmatch(self.value) is None:
            raise ValueError("Evidence obligation id must be opaque")

    def __str__(self) -> str:
        return self.value


class EvidenceObligationConfidence(StrEnum):
    """Confidence that a coverage preference is justified for this request."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EvidenceObligation:
    """A bounded preference for one independently useful evidence item."""

    obligation_id: EvidenceObligationId
    confidence: EvidenceObligationConfidence


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """A candidate's content-independent claim to satisfy an obligation."""

    obligation_id: EvidenceObligationId
    strength: float

    def __post_init__(self) -> None:
        if not isfinite(self.strength) or not 0.0 <= self.strength <= 1.0:
            raise ValueError("Evidence claim strength must be between zero and one")


__all__ = (
    "EvidenceClaim",
    "EvidenceObligation",
    "EvidenceObligationConfidence",
    "EvidenceObligationId",
)
