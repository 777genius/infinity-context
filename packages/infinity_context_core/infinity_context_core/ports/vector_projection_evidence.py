"""Provider-neutral exact identity evidence for derived vector projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_MAX_EVIDENCE_IDENTITIES = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class VectorProjectionScope:
    """Exact canonical scope encoded into every derived vector payload."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None
    projection_version: str

    def __post_init__(self) -> None:
        _required_identity(self.space_id, "space_id")
        _required_identity(self.memory_scope_id, "memory_scope_id")
        if self.thread_id is not None:
            _required_identity(self.thread_id, "thread_id")
        _required_identity(self.projection_version, "projection_version")


@dataclass(frozen=True, slots=True)
class VectorProjectionPointIdentity:
    """Canonical chunk identity paired with its provider point identity."""

    chunk_id: str
    point_id: str

    def __post_init__(self) -> None:
        _required_identity(self.chunk_id, "chunk_id")
        _required_identity(self.point_id, "point_id")


@dataclass(frozen=True, slots=True)
class VectorProjectionPresenceEvidence:
    """Exact expected/retrieved/exhaustively-scrolled vector identities."""

    scope: VectorProjectionScope
    target_commitment_sha256: str
    expected: tuple[VectorProjectionPointIdentity, ...]
    observed: tuple[VectorProjectionPointIdentity, ...]
    scoped_point_ids: tuple[str, ...]
    exact_scoped_count: int
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _scope(self.scope)
        _digest(self.target_commitment_sha256, "target_commitment_sha256")
        _point_identities(self.expected, "expected", require_nonempty=True)
        _point_identities(self.observed, "observed", require_nonempty=False)
        _subset(self.observed, self.expected, "observed")
        _identity_tuple(self.scoped_point_ids, "scoped_point_ids", require_nonempty=False)
        _non_negative_count(self.exact_scoped_count, "exact_scoped_count")
        _issues(self.issues)

    @property
    def complete(self) -> bool:
        expected_ids = {item.point_id for item in self.expected}
        return (
            not self.issues
            and self.observed == self.expected
            and set(self.scoped_point_ids) == expected_ids
            and self.exact_scoped_count == len(expected_ids)
        )

    @property
    def unexpected_point_ids(self) -> tuple[str, ...]:
        expected_ids = {item.point_id for item in self.expected}
        return tuple(point_id for point_id in self.scoped_point_ids if point_id not in expected_ids)


@dataclass(frozen=True, slots=True)
class VectorProjectionDeleteEvidence:
    """Strong ordered delete acknowledgement plus exhaustive terminal readback."""

    scope: VectorProjectionScope
    target_commitment_sha256: str
    pass_index: int
    expected: tuple[VectorProjectionPointIdentity, ...]
    present_before: tuple[VectorProjectionPointIdentity, ...]
    remaining: tuple[VectorProjectionPointIdentity, ...]
    scoped_point_ids_after: tuple[str, ...]
    exact_scoped_count_after: int
    delete_completed: bool
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _scope(self.scope)
        _digest(self.target_commitment_sha256, "target_commitment_sha256")
        if type(self.pass_index) is not int or self.pass_index not in (1, 2):
            raise ValueError("pass_index must be 1 or 2")
        _point_identities(self.expected, "expected", require_nonempty=True)
        _point_identities(self.present_before, "present_before", require_nonempty=False)
        _point_identities(self.remaining, "remaining", require_nonempty=False)
        _subset(self.present_before, self.expected, "present_before")
        _subset(self.remaining, self.expected, "remaining")
        if self.pass_index == 2 and self.present_before:
            raise ValueError("second delete pass must observe idempotent absence")
        _identity_tuple(
            self.scoped_point_ids_after,
            "scoped_point_ids_after",
            require_nonempty=False,
        )
        _non_negative_count(self.exact_scoped_count_after, "exact_scoped_count_after")
        if type(self.delete_completed) is not bool:
            raise ValueError("delete_completed must be bool")
        _issues(self.issues)

    @property
    def verified_absent(self) -> bool:
        return (
            self.delete_completed
            and not self.issues
            and not self.remaining
            and not self.scoped_point_ids_after
            and self.exact_scoped_count_after == 0
        )


class VectorProjectionEvidencePort(Protocol):
    """Exact evidence capability kept separate from ordinary vector recall/write."""

    async def observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
    ) -> VectorProjectionPresenceEvidence: ...

    async def delete_and_observe_exact(
        self,
        *,
        scope: VectorProjectionScope,
        chunk_ids: tuple[str, ...],
        pass_index: int,
    ) -> VectorProjectionDeleteEvidence: ...


def _scope(value: object) -> None:
    if type(value) is not VectorProjectionScope:
        raise ValueError("scope must be VectorProjectionScope")


def _required_identity(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a bounded non-blank identity")


def _digest(value: object, name: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _point_identities(
    value: object,
    name: str,
    *,
    require_nonempty: bool,
) -> None:
    if type(value) is not tuple or any(
        type(item) is not VectorProjectionPointIdentity for item in value
    ):
        raise ValueError(f"{name} must contain exact point identities")
    if require_nonempty and not value:
        raise ValueError(f"{name} cannot be empty")
    if len(value) > _MAX_EVIDENCE_IDENTITIES:
        raise ValueError(f"{name} exceeds the evidence identity limit")
    chunks = [item.chunk_id for item in value]
    points = [item.point_id for item in value]
    if len(set(chunks)) != len(chunks) or len(set(points)) != len(points):
        raise ValueError(f"{name} contains duplicate identities")


def _identity_tuple(value: object, name: str, *, require_nonempty: bool) -> None:
    if type(value) is not tuple:
        raise ValueError(f"{name} must be a tuple")
    if require_nonempty and not value:
        raise ValueError(f"{name} cannot be empty")
    if len(value) > _MAX_EVIDENCE_IDENTITIES:
        raise ValueError(f"{name} exceeds the evidence identity limit")
    for item in value:
        _required_identity(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicate identities")


def _subset(
    value: tuple[VectorProjectionPointIdentity, ...],
    expected: tuple[VectorProjectionPointIdentity, ...],
    name: str,
) -> None:
    expected_set = set(expected)
    if any(item not in expected_set for item in value):
        raise ValueError(f"{name} contains an unexpected identity")
    value_set = set(value)
    expected_order = tuple(item for item in expected if item in value_set)
    if value != expected_order:
        raise ValueError(f"{name} order must follow expected identities")


def _non_negative_count(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")


def _issues(value: object) -> None:
    if type(value) is not tuple or any(
        type(item) is not str or not item or item != item.strip() or len(item) > 160
        for item in value
    ):
        raise ValueError("issues must contain bounded safe codes")
    if len(set(value)) != len(value):
        raise ValueError("issues cannot contain duplicates")


__all__ = (
    "VectorProjectionDeleteEvidence",
    "VectorProjectionEvidencePort",
    "VectorProjectionPointIdentity",
    "VectorProjectionPresenceEvidence",
    "VectorProjectionScope",
)
