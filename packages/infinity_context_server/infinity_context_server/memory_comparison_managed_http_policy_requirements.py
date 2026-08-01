"""Exact typed wire requirements for managed policy evidence endpoints.

The DTOs bind the complete ordered ingest manifest to independently observed
canonical/source/derived presence and terminal absence.  Empty or partial
legacy telemetry can be represented for diagnostics but is never complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, final

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KINDS = (
    "infinity_fact",
    "infinity_document",
    "infinity_chunk",
    "infinity_source",
    "mem0_created_memory",
    "mem0_source",
    "qdrant_point",
    "graphiti_entity",
)


class ManagedPolicyObservationContractError(ValueError):
    """Raised when an exact policy observation DTO is malformed."""


@final
@dataclass(frozen=True, slots=True)
class ManagedIngestIdentityManifest:
    """Complete ordered IDs captured from authenticated ingest responses."""

    corpus_id: str
    infinity_fact_ids: tuple[str, ...]
    infinity_document_ids: tuple[str, ...]
    infinity_chunk_ids: tuple[str, ...]
    infinity_source_ids: tuple[str, ...]
    infinity_source_sha256: tuple[str, ...]
    mem0_created_memory_ids: tuple[str, ...]
    mem0_source_ids: tuple[str, ...]
    mem0_source_sha256: tuple[str, ...]
    operation_count: int
    complete: bool
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.corpus_id, "corpus_id")
        identity_lanes = (
            self.infinity_fact_ids,
            self.infinity_document_ids,
            self.infinity_chunk_ids,
            self.infinity_source_ids,
            self.mem0_created_memory_ids,
            self.mem0_source_ids,
        )
        for lane in identity_lanes:
            _identity_tuple(lane)
        for lane in (self.infinity_source_sha256, self.mem0_source_sha256):
            _digest_tuple(lane)
        if type(self.operation_count) is not int or self.operation_count < 1:
            raise ManagedPolicyObservationContractError("operation_count is invalid")
        _exact_bool(self.complete)
        _issues(self.issues)
        if self.complete and (
            self.issues
            or not self.mem0_created_memory_ids
            or not self.infinity_source_ids
            or len(self.infinity_source_sha256) != len(self.infinity_source_ids)
            or not self.mem0_source_ids
            or len(self.mem0_source_sha256) != len(self.mem0_source_ids)
            or (self.infinity_document_ids and not self.infinity_chunk_ids)
            or not (
                self.infinity_fact_ids
                or self.infinity_document_ids
                or self.infinity_chunk_ids
            )
        ):
            raise ManagedPolicyObservationContractError(
                "complete ingest manifest lacks exact identities"
            )

    @property
    def infinity_canonical_count(self) -> int:
        return len(self.infinity_fact_ids) + len(self.infinity_document_ids)

    @property
    def total_identity_count(self) -> int:
        return sum(
            len(lane)
            for lane in (
                self.infinity_fact_ids,
                self.infinity_document_ids,
                self.infinity_chunk_ids,
                self.infinity_source_ids,
                self.mem0_created_memory_ids,
                self.mem0_source_ids,
            )
        )


@final
@dataclass(frozen=True, slots=True)
class ManagedExactPresenceLane:
    """Expected vs authenticated observed IDs for one exact index lane."""

    identity_kind: str
    expected_ids: tuple[str, ...]
    observed_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.identity_kind not in _KINDS:
            raise ManagedPolicyObservationContractError("identity_kind is invalid")
        _identity_tuple(self.expected_ids)
        _identity_tuple(self.observed_ids)
        if any(item not in self.expected_ids for item in self.observed_ids):
            raise ManagedPolicyObservationContractError("observed identity is unexpected")

    @property
    def expected_count(self) -> int:
        return len(self.expected_ids)

    @property
    def observed_count(self) -> int:
        return len(self.observed_ids)

    @property
    def complete(self) -> bool:
        return bool(self.expected_ids) and self.expected_ids == self.observed_ids


@final
@dataclass(frozen=True, slots=True)
class ManagedCanonicalSourceObservation:
    """Complete canonical/source/Qdrant/Graphiti presence for one corpus."""

    infinity_target_identity_sha256: str
    mem0_target_identity_sha256: str
    manifest: ManagedIngestIdentityManifest
    canonical: ManagedExactPresenceLane
    infinity_source: ManagedExactPresenceLane
    mem0_source: ManagedExactPresenceLane
    qdrant: ManagedExactPresenceLane
    graphiti: ManagedExactPresenceLane
    source_revision: int
    source_sha256: str
    complete: bool
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.infinity_target_identity_sha256, "infinity target")
        _digest(self.mem0_target_identity_sha256, "mem0 target")
        if type(self.manifest) is not ManagedIngestIdentityManifest:
            raise ManagedPolicyObservationContractError("manifest type is invalid")
        lanes = (
            self.canonical,
            self.infinity_source,
            self.mem0_source,
            self.qdrant,
            self.graphiti,
        )
        if any(type(lane) is not ManagedExactPresenceLane for lane in lanes):
            raise ManagedPolicyObservationContractError("presence lane type is invalid")
        if (
            self.canonical.identity_kind
            not in ("infinity_fact", "infinity_document")
            or self.infinity_source.identity_kind != "infinity_source"
            or self.mem0_source.identity_kind != "mem0_source"
            or self.qdrant.identity_kind != "qdrant_point"
            or self.graphiti.identity_kind != "graphiti_entity"
        ):
            raise ManagedPolicyObservationContractError(
                "presence lane roles are invalid"
            )
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise ManagedPolicyObservationContractError("source_revision is invalid")
        _digest(self.source_sha256, "source_sha256")
        _exact_bool(self.complete)
        _issues(self.issues)
        if self.complete:
            raise ManagedPolicyObservationContractError(
                "authenticated derived identity manifest is unavailable"
            )
        if not self.issues:
            raise ManagedPolicyObservationContractError("presence completeness is inconsistent")

    @property
    def expected_count(self) -> int:
        return sum(
            lane.expected_count
            for lane in (
                self.canonical,
                self.infinity_source,
                self.mem0_source,
                self.qdrant,
                self.graphiti,
            )
        )

    @property
    def observed_count(self) -> int:
        return sum(
            lane.observed_count
            for lane in (
                self.canonical,
                self.infinity_source,
                self.mem0_source,
                self.qdrant,
                self.graphiti,
            )
        )


@final
@dataclass(frozen=True, slots=True)
class ManagedDeleteIdentityLane:
    """Exact expected, deleted, and remaining IDs for one terminal lane."""

    identity_kind: str
    expected_ids: tuple[str, ...]
    deleted_ids: tuple[str, ...]
    remaining_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.identity_kind not in _KINDS:
            raise ManagedPolicyObservationContractError("identity_kind is invalid")
        _identity_tuple(self.expected_ids)
        _identity_tuple(self.deleted_ids)
        _identity_tuple(self.remaining_ids)
        deleted = set(self.deleted_ids)
        remaining = set(self.remaining_ids)
        if deleted.intersection(remaining):
            raise ManagedPolicyObservationContractError("delete identity sets overlap")
        if deleted.union(remaining) != set(self.expected_ids):
            raise ManagedPolicyObservationContractError("delete identity coverage differs")
        if self.deleted_ids != tuple(item for item in self.expected_ids if item in deleted):
            raise ManagedPolicyObservationContractError("deleted identity order differs")
        if self.remaining_ids != tuple(
            item for item in self.expected_ids if item in remaining
        ):
            raise ManagedPolicyObservationContractError("remaining identity order differs")

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_ids)

    @property
    def remaining_count(self) -> int:
        return len(self.remaining_ids)

    @property
    def verified_absent(self) -> bool:
        return not self.remaining_ids


@final
@dataclass(frozen=True, slots=True)
class ManagedTerminalDeleteObservation:
    """Exact two-pass deletion result bound to the complete ingest manifest."""

    target_identity_sha256: str
    corpus_id: str
    pass_index: int
    manifest_sha256: str
    lanes: tuple[ManagedDeleteIdentityLane, ...]
    verified_absent: bool
    complete: bool
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        _digest(self.target_identity_sha256, "target_identity_sha256")
        _text(self.corpus_id, "corpus_id")
        if self.pass_index not in (1, 2):
            raise ManagedPolicyObservationContractError("pass_index is invalid")
        _digest(self.manifest_sha256, "manifest_sha256")
        if (
            type(self.lanes) is not tuple
            or not self.lanes
            or any(type(lane) is not ManagedDeleteIdentityLane for lane in self.lanes)
            or len({lane.identity_kind for lane in self.lanes}) != len(self.lanes)
        ):
            raise ManagedPolicyObservationContractError("delete lanes are invalid")
        _exact_bool(self.verified_absent)
        _exact_bool(self.complete)
        _issues(self.issues)
        actual_absent = all(lane.verified_absent for lane in self.lanes)
        if self.verified_absent != actual_absent:
            raise ManagedPolicyObservationContractError("absence claim is inconsistent")
        if self.complete:
            raise ManagedPolicyObservationContractError(
                "terminal manifest binding is unavailable"
            )
        if not self.issues:
            raise ManagedPolicyObservationContractError("delete completeness is inconsistent")

    @property
    def deleted_count(self) -> int:
        return sum(lane.deleted_count for lane in self.lanes)

    @property
    def remaining_count(self) -> int:
        return sum(lane.remaining_count for lane in self.lanes)


class ManagedPolicyHttpEvidencePort(Protocol):
    """Future internal endpoint adapter, never injected by benchmark callers."""

    def observe_canonical_source(
        self,
        *,
        run_id: str,
        manifest: ManagedIngestIdentityManifest,
        infinity_target_identity_sha256: str,
        mem0_target_identity_sha256: str,
    ) -> ManagedCanonicalSourceObservation: ...

    def cleanup_and_readback(
        self,
        *,
        run_id: str,
        manifest: ManagedIngestIdentityManifest,
        target_identity_sha256: str,
        pass_index: int,
    ) -> ManagedTerminalDeleteObservation: ...


def _identity_tuple(value: object) -> None:
    if (
        type(value) is not tuple
        or any(type(item) is not str or not item or item != item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ManagedPolicyObservationContractError("identity tuple is invalid")


def _digest_tuple(value: object) -> None:
    if type(value) is not tuple or any(
        type(item) is not str or _SHA256.fullmatch(item) is None for item in value
    ):
        raise ManagedPolicyObservationContractError("digest tuple is invalid")


def _issues(value: object) -> None:
    if type(value) is not tuple or any(
        type(item) is not str or not item or item != item.strip() for item in value
    ):
        raise ManagedPolicyObservationContractError("issues are invalid")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 500:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")


def _exact_bool(value: object) -> None:
    if type(value) is not bool:
        raise ManagedPolicyObservationContractError("observation flag is invalid")


__all__ = (
    "ManagedCanonicalSourceObservation",
    "ManagedDeleteIdentityLane",
    "ManagedExactPresenceLane",
    "ManagedIngestIdentityManifest",
    "ManagedPolicyHttpEvidencePort",
    "ManagedPolicyObservationContractError",
    "ManagedTerminalDeleteObservation",
)
