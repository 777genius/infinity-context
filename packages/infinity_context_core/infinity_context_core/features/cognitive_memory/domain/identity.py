"""Stable identities for cognitive candidates and their canonical evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .errors import CognitiveMemoryInvariantError


def _required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CognitiveMemoryInvariantError(f"{field} is required")
    return normalized


@dataclass(frozen=True, slots=True)
class CognitiveScope:
    """Canonical tenant and visibility address for a derived candidate."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "space_id", _required_text(self.space_id, "space_id"))
        object.__setattr__(
            self,
            "memory_scope_id",
            _required_text(self.memory_scope_id, "memory_scope_id"),
        )
        if self.thread_id is not None:
            object.__setattr__(self, "thread_id", _required_text(self.thread_id, "thread_id"))

    def stable_fields(self) -> dict[str, str | None]:
        return {
            "memory_scope_id": self.memory_scope_id,
            "space_id": self.space_id,
            "thread_id": self.thread_id,
        }


@dataclass(frozen=True, slots=True)
class CanonicalEvidenceIdentity:
    """Exact Postgres-owned source identity, including its canonical version."""

    evidence_type: str
    evidence_id: str
    version: int
    scope: CognitiveScope

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_type",
            _required_text(self.evidence_type, "evidence_type"),
        )
        object.__setattr__(self, "evidence_id", _required_text(self.evidence_id, "evidence_id"))
        if type(self.version) is not int or self.version < 1:
            raise CognitiveMemoryInvariantError("canonical evidence version must be positive")

    def stable_fields(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "scope": self.scope.stable_fields(),
            "version": self.version,
        }

    def sort_key(self) -> str:
        return json.dumps(self.stable_fields(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class CognitiveProjectionVersion:
    """Semantic version of synthesis schema, policy, and model behavior."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _required_text(self.value, "projection_version"))


@dataclass(frozen=True, slots=True)
class CognitiveCandidateIdentity:
    """Provider-independent digest of the complete candidate derivation identity."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _required_text(self.value, "candidate_identity"))

    @classmethod
    def derive(
        cls,
        *,
        scope: CognitiveScope,
        kind: str,
        evidence_identities: tuple[CanonicalEvidenceIdentity, ...],
        content_hash: str,
        projection_version: CognitiveProjectionVersion,
    ) -> CognitiveCandidateIdentity:
        if not evidence_identities:
            raise CognitiveMemoryInvariantError("candidate identity requires canonical evidence")
        payload = {
            "content_hash": _required_text(content_hash, "content_hash"),
            "evidence": [
                identity.stable_fields()
                for identity in sorted(evidence_identities, key=lambda item: item.sort_key())
            ],
            "kind": _required_text(kind, "kind"),
            "projection_version": projection_version.value,
            "scope": scope.stable_fields(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return cls(f"sha256:{hashlib.sha256(encoded).hexdigest()}")


def cognitive_content_hash(content: str) -> str:
    """Hash candidate content without assigning it canonical authority."""

    normalized = _required_text(content, "content")
    return f"sha256:{hashlib.sha256(normalized.encode()).hexdigest()}"
