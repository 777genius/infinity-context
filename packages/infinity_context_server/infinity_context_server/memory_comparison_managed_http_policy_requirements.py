"""Exact typed wire requirements for managed policy evidence endpoints.

The DTOs bind the complete ordered ingest manifest to independently observed
canonical/source/derived presence and terminal absence.  Empty or partial
legacy telemetry can be represented for diagnostics but is never complete.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol, final

from infinity_context_core.ports.derived_projection_policy import (
    DerivedProjectionLaneDisposition,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,511}$")
_KINDS = (
    "infinity_fact",
    "infinity_document",
    "infinity_chunk",
    "infinity_source",
    "mem0_created_memory",
    "mem0_source",
    "qdrant_point",
    "graphiti_group",
    "graphiti_episode",
    "graphiti_entity",
    "graphiti_mentions",
    "graphiti_relates",
)
_MAX_IDENTITIES = 20_000


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
            or not (self.infinity_fact_ids or self.infinity_document_ids or self.infinity_chunk_ids)
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
class ManagedCanonicalProjectionScope:
    """Canonical scope sent to the identity-only diagnostics boundary."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _identity(self.space_id, "space_id")
        _identity(self.memory_scope_id, "memory_scope_id")
        if self.thread_id is not None:
            _identity(self.thread_id, "thread_id")


@final
@dataclass(frozen=True, slots=True)
class ManagedProjectionOutboxObservation:
    """Exact terminal outbox identities returned before derived observation."""

    done_chunk_ids: tuple[str, ...]
    done_fact_ids: tuple[str, ...]
    done_event_count: int
    complete: bool

    def __post_init__(self) -> None:
        _bounded_identity_tuple(self.done_chunk_ids, "done_chunk_ids")
        _bounded_identity_tuple(self.done_fact_ids, "done_fact_ids")
        _count(self.done_event_count, "done_event_count")
        _exact_bool(self.complete)
        if self.complete and self.done_event_count < (
            len(self.done_chunk_ids) + len(self.done_fact_ids)
        ):
            raise ManagedPolicyObservationContractError("outbox count is inconsistent")


@final
@dataclass(frozen=True, slots=True)
class ManagedQdrantPointIdentity:
    """Canonical chunk ID paired with its opaque Qdrant point ID."""

    chunk_id: str
    point_id: str

    def __post_init__(self) -> None:
        _identity(self.chunk_id, "chunk_id")
        _identity(self.point_id, "point_id")


@final
@dataclass(frozen=True, slots=True)
class ManagedQdrantPresenceObservation:
    """Complete exact Qdrant inventory and its service-issued bindings."""

    projection_version: str
    target_commitment_sha256: str
    manifest_binding_sha256: str
    expected: tuple[ManagedQdrantPointIdentity, ...]
    observed: tuple[ManagedQdrantPointIdentity, ...]
    scoped_point_ids: tuple[str, ...]
    exact_scoped_count: int
    complete: bool

    def __post_init__(self) -> None:
        _identity(self.projection_version, "projection_version")
        _digest(self.target_commitment_sha256, "target_commitment_sha256")
        _digest(self.manifest_binding_sha256, "manifest_binding_sha256")
        _point_tuple(self.expected, "expected", allow_empty=False)
        _point_tuple(self.observed, "observed", allow_empty=False)
        _bounded_identity_tuple(self.scoped_point_ids, "scoped_point_ids")
        _count(self.exact_scoped_count, "exact_scoped_count")
        _exact_bool(self.complete)
        expected_points = tuple(item.point_id for item in self.expected)
        if (
            not self.complete
            or self.observed != self.expected
            or set(self.scoped_point_ids) != set(expected_points)
            or self.exact_scoped_count != len(expected_points)
        ):
            raise ManagedPolicyObservationContractError("qdrant presence is incomplete")


@final
@dataclass(frozen=True, slots=True)
class ManagedGraphitiIdentitySnapshot:
    """Exact Graphiti physical UUID lanes; empty individual lanes are valid."""

    episode_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    mentions_edge_ids: tuple[str, ...]
    relates_to_edge_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        lanes = (
            self.episode_ids,
            self.entity_ids,
            self.mentions_edge_ids,
            self.relates_to_edge_ids,
        )
        for name, lane in zip(
            (
                "episode_ids",
                "entity_ids",
                "mentions_edge_ids",
                "relates_to_edge_ids",
            ),
            lanes,
            strict=True,
        ):
            _bounded_identity_tuple(lane, name)
        flattened = tuple(identity for lane in lanes for identity in lane)
        if len(flattened) > _MAX_IDENTITIES or len(set(flattened)) != len(flattened):
            raise ManagedPolicyObservationContractError("graphiti snapshot identities are invalid")

    @property
    def exact_identity_count(self) -> int:
        return sum(
            len(lane)
            for lane in (
                self.episode_ids,
                self.entity_ids,
                self.mentions_edge_ids,
                self.relates_to_edge_ids,
            )
        )

    @property
    def empty(self) -> bool:
        return self.exact_identity_count == 0


@final
@dataclass(frozen=True, slots=True)
class ManagedGraphitiPresenceObservation:
    """Graph group scope plus exact episode/entity/edge identity lanes."""

    group_scope: ManagedCanonicalProjectionScope
    target_commitment_sha256: str
    manifest_binding_sha256: str
    identity_manifest: ManagedGraphitiIdentitySnapshot
    exact_identity_count: int
    complete: bool

    def __post_init__(self) -> None:
        if type(self.group_scope) is not ManagedCanonicalProjectionScope:
            raise ManagedPolicyObservationContractError("graphiti group scope is invalid")
        _digest(self.target_commitment_sha256, "target_commitment_sha256")
        _digest(self.manifest_binding_sha256, "manifest_binding_sha256")
        if type(self.identity_manifest) is not ManagedGraphitiIdentitySnapshot:
            raise ManagedPolicyObservationContractError("graphiti manifest is invalid")
        _count(self.exact_identity_count, "exact_identity_count")
        _exact_bool(self.complete)
        if (
            not self.complete
            or self.identity_manifest.empty
            or self.exact_identity_count != self.identity_manifest.exact_identity_count
        ):
            raise ManagedPolicyObservationContractError("graphiti presence is incomplete")


@final
@dataclass(frozen=True, slots=True)
class ManagedDerivedPresenceObservation:
    """Identity-only presence bound to one lifecycle target and ingest manifest."""

    lifecycle_target_identity_sha256: str
    ingest_manifest_sha256: str
    scope: ManagedCanonicalProjectionScope
    outbox: ManagedProjectionOutboxObservation
    qdrant: ManagedQdrantPresenceObservation | DerivedProjectionLaneDisposition | None
    graphiti: ManagedGraphitiPresenceObservation | DerivedProjectionLaneDisposition | None

    def __post_init__(self) -> None:
        _digest(
            self.lifecycle_target_identity_sha256,
            "lifecycle_target_identity_sha256",
        )
        _digest(self.ingest_manifest_sha256, "ingest_manifest_sha256")
        if type(self.scope) is not ManagedCanonicalProjectionScope:
            raise ManagedPolicyObservationContractError("presence scope is invalid")
        if type(self.outbox) is not ManagedProjectionOutboxObservation:
            raise ManagedPolicyObservationContractError("presence outbox is invalid")
        if self.qdrant is not None and type(self.qdrant) not in {
            ManagedQdrantPresenceObservation,
            DerivedProjectionLaneDisposition,
        }:
            raise ManagedPolicyObservationContractError("qdrant presence type is invalid")
        if type(self.qdrant) is DerivedProjectionLaneDisposition and (
            self.qdrant.lane != "qdrant" or not self.qdrant.is_not_projected
        ):
            raise ManagedPolicyObservationContractError("qdrant disposition is invalid")
        if (
            self.graphiti is not None
            and type(self.graphiti)
            not in {ManagedGraphitiPresenceObservation, DerivedProjectionLaneDisposition}
        ):
            raise ManagedPolicyObservationContractError("graphiti presence type is invalid")
        if type(self.graphiti) is DerivedProjectionLaneDisposition and (
            self.graphiti.lane != "graphiti" or not self.graphiti.is_not_projected
        ):
            raise ManagedPolicyObservationContractError("graphiti disposition is invalid")


@final
@dataclass(frozen=True, slots=True)
class ManagedQdrantDeletePassObservation:
    """One internal Qdrant delete/readback pass."""

    pass_index: int
    target_commitment_sha256: str
    expected: tuple[ManagedQdrantPointIdentity, ...]
    present_before: tuple[ManagedQdrantPointIdentity, ...]
    remaining: tuple[ManagedQdrantPointIdentity, ...]
    scoped_point_ids_after: tuple[str, ...]
    exact_scoped_count_after: int
    delete_completed: bool
    verified_absent: bool

    def __post_init__(self) -> None:
        if type(self.pass_index) is not int or self.pass_index not in (1, 2):
            raise ManagedPolicyObservationContractError("qdrant pass index is invalid")
        _digest(self.target_commitment_sha256, "target_commitment_sha256")
        _point_tuple(self.expected, "expected", allow_empty=False)
        _point_tuple(self.present_before, "present_before", allow_empty=True)
        _point_tuple(self.remaining, "remaining", allow_empty=True)
        _bounded_identity_tuple(self.scoped_point_ids_after, "scoped_point_ids_after")
        _count(self.exact_scoped_count_after, "exact_scoped_count_after")
        _exact_bool(self.delete_completed)
        _exact_bool(self.verified_absent)
        if any(item not in self.expected for item in (*self.present_before, *self.remaining)):
            raise ManagedPolicyObservationContractError("qdrant delete identity is unexpected")
        absent = (
            self.delete_completed
            and not self.remaining
            and not self.scoped_point_ids_after
            and self.exact_scoped_count_after == 0
        )
        if not self.verified_absent or not absent:
            raise ManagedPolicyObservationContractError("qdrant delete pass is incomplete")


@final
@dataclass(frozen=True, slots=True)
class ManagedQdrantDeleteObservation:
    """Exact internal two-pass Qdrant deletion bound to a prior presence receipt."""

    lifecycle_target_identity_sha256: str
    ingest_manifest_sha256: str
    target_commitment_sha256: str
    manifest_binding_sha256: str
    expected_chunk_ids: tuple[str, ...]
    passes: tuple[ManagedQdrantDeletePassObservation, ...]
    verified_absent: bool

    def __post_init__(self) -> None:
        for name in (
            "lifecycle_target_identity_sha256",
            "ingest_manifest_sha256",
            "target_commitment_sha256",
            "manifest_binding_sha256",
        ):
            _digest(getattr(self, name), name)
        _bounded_identity_tuple(self.expected_chunk_ids, "expected_chunk_ids")
        if not self.expected_chunk_ids:
            raise ManagedPolicyObservationContractError("expected_chunk_ids cannot be empty")
        if (
            type(self.passes) is not tuple
            or len(self.passes) != 2
            or any(type(item) is not ManagedQdrantDeletePassObservation for item in self.passes)
            or tuple(item.pass_index for item in self.passes) != (1, 2)
        ):
            raise ManagedPolicyObservationContractError("qdrant delete passes are invalid")
        _exact_bool(self.verified_absent)
        expected_chunks = tuple(item.chunk_id for item in self.passes[0].expected)
        if (
            not self.verified_absent
            or expected_chunks != self.expected_chunk_ids
            or self.passes[1].expected != self.passes[0].expected
            or self.passes[0].present_before not in (self.passes[0].expected, ())
            or self.passes[1].present_before
            or any(
                item.target_commitment_sha256 != self.target_commitment_sha256
                for item in self.passes
            )
        ):
            raise ManagedPolicyObservationContractError("qdrant delete evidence differs")


@final
@dataclass(frozen=True, slots=True)
class ManagedGraphitiDeletePassObservation:
    """One internal Graphiti group delete with scoped and global readback."""

    pass_index: int
    before: ManagedGraphitiIdentitySnapshot
    deleted: ManagedGraphitiIdentitySnapshot
    group_readback: ManagedGraphitiIdentitySnapshot
    global_readback: ManagedGraphitiIdentitySnapshot
    verified_absent: bool

    def __post_init__(self) -> None:
        if type(self.pass_index) is not int or self.pass_index not in (1, 2):
            raise ManagedPolicyObservationContractError("graphiti pass index is invalid")
        for name in ("before", "deleted", "group_readback", "global_readback"):
            if type(getattr(self, name)) is not ManagedGraphitiIdentitySnapshot:
                raise ManagedPolicyObservationContractError("graphiti delete snapshot is invalid")
        _exact_bool(self.verified_absent)
        if not self.verified_absent or not (
            self.group_readback.empty and self.global_readback.empty
        ):
            raise ManagedPolicyObservationContractError("graphiti delete pass is incomplete")


@final
@dataclass(frozen=True, slots=True)
class ManagedGraphitiDeleteObservation:
    """Exact internal two-pass Graphiti deletion bound to a prior presence receipt."""

    lifecycle_target_identity_sha256: str
    ingest_manifest_sha256: str
    target_commitment_sha256: str
    manifest_binding_sha256: str
    expected_fact_ids: tuple[str, ...]
    expected: ManagedGraphitiIdentitySnapshot
    group_scope: ManagedCanonicalProjectionScope
    passes: tuple[ManagedGraphitiDeletePassObservation, ...]
    verified_absent: bool

    def __post_init__(self) -> None:
        for name in (
            "lifecycle_target_identity_sha256",
            "ingest_manifest_sha256",
            "target_commitment_sha256",
            "manifest_binding_sha256",
        ):
            _digest(getattr(self, name), name)
        _bounded_identity_tuple(self.expected_fact_ids, "expected_fact_ids")
        if not self.expected_fact_ids:
            raise ManagedPolicyObservationContractError("expected_fact_ids cannot be empty")
        if type(self.expected) is not ManagedGraphitiIdentitySnapshot or self.expected.empty:
            raise ManagedPolicyObservationContractError("graphiti expected manifest is invalid")
        if type(self.group_scope) is not ManagedCanonicalProjectionScope:
            raise ManagedPolicyObservationContractError("graphiti group scope is invalid")
        if (
            type(self.passes) is not tuple
            or len(self.passes) != 2
            or any(type(item) is not ManagedGraphitiDeletePassObservation for item in self.passes)
            or tuple(item.pass_index for item in self.passes) != (1, 2)
        ):
            raise ManagedPolicyObservationContractError("graphiti delete passes are invalid")
        _exact_bool(self.verified_absent)
        empty = ManagedGraphitiIdentitySnapshot((), (), (), ())
        first_pass_is_initial = (
            self.passes[0].before == self.expected and self.passes[0].deleted == self.expected
        )
        first_pass_is_replay = self.passes[0].before == empty and self.passes[0].deleted == empty
        if (
            not self.verified_absent
            or not (first_pass_is_initial or first_pass_is_replay)
            or self.passes[1].before != empty
            or self.passes[1].deleted != empty
        ):
            raise ManagedPolicyObservationContractError("graphiti delete evidence differs")


def managed_ingest_identity_manifest_sha256(
    manifest: ManagedIngestIdentityManifest,
    scope: ManagedCanonicalProjectionScope,
) -> str:
    """Bind an exact ingest manifest to the canonical derived-projection scope."""

    if type(manifest) is not ManagedIngestIdentityManifest or not manifest.complete:
        raise ManagedPolicyObservationContractError("complete ingest manifest is required")
    if type(scope) is not ManagedCanonicalProjectionScope:
        raise ManagedPolicyObservationContractError("canonical scope is invalid")
    payload = {
        "scope": {
            "space_id": scope.space_id,
            "memory_scope_id": scope.memory_scope_id,
            "thread_id": scope.thread_id,
        },
        "manifest": {
            "corpus_id": manifest.corpus_id,
            "infinity_fact_ids": list(manifest.infinity_fact_ids),
            "infinity_document_ids": list(manifest.infinity_document_ids),
            "infinity_chunk_ids": list(manifest.infinity_chunk_ids),
            "infinity_source_ids": list(manifest.infinity_source_ids),
            "infinity_source_sha256": list(manifest.infinity_source_sha256),
            "mem0_created_memory_ids": list(manifest.mem0_created_memory_ids),
            "mem0_source_ids": list(manifest.mem0_source_ids),
            "mem0_source_sha256": list(manifest.mem0_source_sha256),
            "operation_count": manifest.operation_count,
            "complete": manifest.complete,
            "issues": list(manifest.issues),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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
            self.canonical.identity_kind not in ("infinity_fact", "infinity_document")
            or self.infinity_source.identity_kind != "infinity_source"
            or self.mem0_source.identity_kind != "mem0_source"
            or self.qdrant.identity_kind != "qdrant_point"
            or self.graphiti.identity_kind != "graphiti_entity"
        ):
            raise ManagedPolicyObservationContractError("presence lane roles are invalid")
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
        if self.remaining_ids != tuple(item for item in self.expected_ids if item in remaining):
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
            raise ManagedPolicyObservationContractError("terminal manifest binding is unavailable")
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


def _bounded_identity_tuple(value: object, name: str) -> None:
    if type(value) is not tuple or len(value) > _MAX_IDENTITIES:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")
    for item in value:
        _identity(item, name)
    if len(set(value)) != len(value):
        raise ManagedPolicyObservationContractError(f"{name} is invalid")


def _point_tuple(value: object, name: str, *, allow_empty: bool) -> None:
    if (
        type(value) is not tuple
        or (not allow_empty and not value)
        or len(value) > _MAX_IDENTITIES
        or any(type(item) is not ManagedQdrantPointIdentity for item in value)
    ):
        raise ManagedPolicyObservationContractError(f"{name} is invalid")
    chunks = tuple(item.chunk_id for item in value)
    points = tuple(item.point_id for item in value)
    if len(set(chunks)) != len(chunks) or len(set(points)) != len(points):
        raise ManagedPolicyObservationContractError(f"{name} is invalid")


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


def _identity(value: object, name: str) -> str:
    if type(value) is not str or _OPAQUE_IDENTITY.fullmatch(value) is None:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")
    return value


def _digest(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")


def _exact_bool(value: object) -> None:
    if type(value) is not bool:
        raise ManagedPolicyObservationContractError("observation flag is invalid")


def _count(value: object, name: str) -> None:
    if type(value) is not int or value < 0 or value > _MAX_IDENTITIES * 10:
        raise ManagedPolicyObservationContractError(f"{name} is invalid")


__all__ = (
    "ManagedCanonicalProjectionScope",
    "ManagedCanonicalSourceObservation",
    "ManagedDeleteIdentityLane",
    "ManagedDerivedPresenceObservation",
    "ManagedExactPresenceLane",
    "ManagedGraphitiDeleteObservation",
    "ManagedGraphitiDeletePassObservation",
    "ManagedGraphitiIdentitySnapshot",
    "ManagedGraphitiPresenceObservation",
    "ManagedIngestIdentityManifest",
    "ManagedPolicyHttpEvidencePort",
    "ManagedPolicyObservationContractError",
    "ManagedProjectionOutboxObservation",
    "ManagedQdrantDeleteObservation",
    "ManagedQdrantDeletePassObservation",
    "ManagedQdrantPointIdentity",
    "ManagedQdrantPresenceObservation",
    "ManagedTerminalDeleteObservation",
    "managed_ingest_identity_manifest_sha256",
)
