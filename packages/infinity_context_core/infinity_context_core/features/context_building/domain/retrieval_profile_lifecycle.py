"""Lifecycle policy for the canonical Retrieval projection profile registry."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class RetrievalProfileState(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    RETAINED = "retained"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class RetainedProfile:
    profile_id: str
    retained_at: datetime


def retained_profiles_to_retire(
    profiles: tuple[RetainedProfile, ...], *, maximum_retained: int
) -> tuple[str, ...]:
    """Select oldest retained profiles with a stable id tie-breaker."""

    if not isinstance(maximum_retained, int) or isinstance(maximum_retained, bool):
        raise ValueError("Maximum retained profiles must be an integer")
    if not 0 <= maximum_retained <= 100:
        raise ValueError("Maximum retained profiles must be within 0..100")
    if not isinstance(profiles, tuple) or not all(
        isinstance(item, RetainedProfile) for item in profiles
    ):
        raise ValueError("Retained profiles must be an immutable tuple")
    ordered = sorted(profiles, key=lambda item: (item.retained_at, item.profile_id))
    excess = max(0, len(ordered) - maximum_retained)
    return tuple(item.profile_id for item in ordered[:excess])


@dataclass(frozen=True, slots=True)
class RetrievalProfileIdentity:
    profile_id: str
    generation: str
    profile_digest: str
    collection_name: str

    def __post_init__(self) -> None:
        for name in ("profile_id", "generation", "collection_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Retrieval profile {name} must be normalized")
        if len(self.profile_id) > 120:
            raise ValueError("Retrieval profile profile_id is too long")
        if len(self.generation) > 160:
            raise ValueError("Retrieval profile generation is too long")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
            for character in self.profile_id
        ):
            raise ValueError("Retrieval profile profile_id contains unsafe characters")
        if len(self.collection_name) > 240 or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in self.collection_name
        ):
            raise ValueError("Retrieval profile collection_name is invalid")
        if (
            not isinstance(self.profile_digest, str)
            or len(self.profile_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.profile_digest)
        ):
            raise ValueError("Retrieval profile digest must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ProfileCoverageAttestation:
    expected_count: int
    projected_count: int
    expected_digest: str
    projected_digest: str
    canonical_watermark: int
    projected_watermark: int
    backfill_complete: bool

    def __post_init__(self) -> None:
        _require_nonnegative_int("expected_count", self.expected_count)
        _require_nonnegative_int("projected_count", self.projected_count)
        _require_nonnegative_int("canonical_watermark", self.canonical_watermark)
        _require_nonnegative_int("projected_watermark", self.projected_watermark)
        _require_digest("expected_digest", self.expected_digest)
        _require_digest("projected_digest", self.projected_digest)
        if not isinstance(self.backfill_complete, bool):
            raise ValueError("Profile backfill_complete must be boolean")

    @property
    def exact(self) -> bool:
        return (
            self.backfill_complete
            and self.expected_count == self.projected_count
            and self.expected_digest == self.projected_digest
            and self.canonical_watermark == self.projected_watermark
        )


@dataclass(frozen=True, slots=True)
class ProfileQueueHealth:
    retry_count: int
    dead_count: int
    oldest_pending_at: datetime | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_nonnegative_int("retry_count", self.retry_count)
        _require_nonnegative_int("dead_count", self.dead_count)
        if not isinstance(self.observed_at, datetime):
            raise ValueError("Profile queue observed_at must be a datetime")
        if self.observed_at.utcoffset() is None:
            raise ValueError("Profile queue observed_at must be timezone-aware")
        if self.oldest_pending_at is not None and not isinstance(self.oldest_pending_at, datetime):
            raise ValueError("Profile queue oldest_pending_at must be a datetime")
        if self.oldest_pending_at is not None and self.oldest_pending_at.utcoffset() is None:
            raise ValueError("Profile queue oldest_pending_at must be timezone-aware")

    def lag_within(self, maximum: timedelta) -> bool:
        return (
            self.oldest_pending_at is None or self.observed_at - self.oldest_pending_at <= maximum
        )


@dataclass(frozen=True, slots=True)
class ProfileLaneHealth:
    lane_id: str
    required: bool
    healthy: bool
    profile_qualified: bool
    observed_count: int = 0
    observed_digest: str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def __post_init__(self) -> None:
        if not isinstance(self.lane_id, str) or not self.lane_id:
            raise ValueError("Profile lane_id must be non-empty")
        if not all(
            isinstance(value, bool)
            for value in (self.required, self.healthy, self.profile_qualified)
        ):
            raise ValueError("Profile lane flags must be boolean")
        _require_nonnegative_int("lane observed_count", self.observed_count)
        _require_digest("lane observed_digest", self.observed_digest)


@dataclass(frozen=True, slots=True)
class ProfileAttestationLease:
    """Opaque, single-use fence over one exact qualification observation."""

    lease_id: str
    profile_id: str
    generation: str
    evidence_digest: str
    issued_at: datetime
    expires_at: datetime
    evidence_version: int = 0
    mutation_epoch: int = 0

    def __post_init__(self) -> None:
        for name in ("lease_id", "profile_id", "generation"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Profile lease {name} must be normalized")
        _require_digest("lease evidence_digest", self.evidence_digest)
        if not isinstance(self.issued_at, datetime) or not isinstance(self.expires_at, datetime):
            raise ValueError("Profile lease timestamps must be datetimes")
        if self.issued_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("Profile lease timestamps must be timezone-aware")
        if self.expires_at <= self.issued_at:
            raise ValueError("Profile lease expiry must follow issuance")
        _require_nonnegative_int("lease evidence_version", self.evidence_version)
        _require_nonnegative_int("lease mutation_epoch", self.mutation_epoch)

    def valid_at(self, now: datetime) -> bool:
        return now.utcoffset() is not None and self.issued_at <= now < self.expires_at


@dataclass(frozen=True, slots=True)
class ProfileTombstoneHealth:
    required_count: int
    completed_count: int

    def __post_init__(self) -> None:
        _require_nonnegative_int("required_count", self.required_count)
        _require_nonnegative_int("completed_count", self.completed_count)
        if self.completed_count > self.required_count:
            raise ValueError("Completed profile tombstones cannot exceed required")

    @property
    def complete(self) -> bool:
        return self.required_count == self.completed_count


@dataclass(frozen=True, slots=True)
class ProfileActivationEvidence:
    coverage: ProfileCoverageAttestation
    queue: ProfileQueueHealth
    lanes: tuple[ProfileLaneHealth, ...]
    tombstones: ProfileTombstoneHealth

    def __post_init__(self) -> None:
        if not isinstance(self.coverage, ProfileCoverageAttestation):
            raise ValueError("Profile activation coverage is invalid")
        if not isinstance(self.queue, ProfileQueueHealth):
            raise ValueError("Profile activation queue health is invalid")
        if not isinstance(self.lanes, tuple) or not all(
            isinstance(item, ProfileLaneHealth) for item in self.lanes
        ):
            raise ValueError("Profile activation lanes must be an immutable tuple")
        if len({item.lane_id for item in self.lanes}) != len(self.lanes):
            raise ValueError("Profile activation lanes must be unique")
        if not isinstance(self.tombstones, ProfileTombstoneHealth):
            raise ValueError("Profile activation tombstone health is invalid")

    def digest(self) -> str:
        """Bind every gate without provider-specific or high-cardinality values."""

        values = [
            str(self.coverage.expected_count),
            self.coverage.expected_digest,
            str(self.coverage.canonical_watermark),
            str(self.coverage.projected_count),
            self.coverage.projected_digest,
            str(self.coverage.projected_watermark),
            str(int(self.coverage.backfill_complete)),
            str(self.queue.retry_count),
            str(self.queue.dead_count),
            self.queue.oldest_pending_at.isoformat() if self.queue.oldest_pending_at else "",
            str(self.tombstones.required_count),
            str(self.tombstones.completed_count),
        ]
        for lane in sorted(self.lanes, key=lambda item: item.lane_id.encode("utf-8")):
            values.extend(
                (
                    lane.lane_id,
                    str(int(lane.required)),
                    str(int(lane.healthy)),
                    str(int(lane.profile_qualified)),
                    str(lane.observed_count),
                    lane.observed_digest,
                )
            )
        return hashlib.sha256("\0".join(values).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileActivationDecision:
    accepted: bool
    rejection_reasons: tuple[str, ...]


def assess_profile_activation(
    evidence: ProfileActivationEvidence,
    *,
    maximum_queue_lag: timedelta,
) -> ProfileActivationDecision:
    """Return stable, privacy-safe reasons; no override path exists in this slice."""

    if not isinstance(evidence, ProfileActivationEvidence):
        raise ValueError("Profile activation evidence is invalid")
    if not isinstance(maximum_queue_lag, timedelta) or maximum_queue_lag <= timedelta(0):
        raise ValueError("Profile maximum queue lag must be positive")
    reasons: list[str] = []
    if not evidence.coverage.backfill_complete:
        reasons.append("backfill_incomplete")
    if evidence.coverage.expected_count != evidence.coverage.projected_count:
        reasons.append("coverage_count_mismatch")
    if evidence.coverage.expected_digest != evidence.coverage.projected_digest:
        reasons.append("coverage_digest_mismatch")
    if evidence.coverage.canonical_watermark != evidence.coverage.projected_watermark:
        reasons.append("coverage_watermark_mismatch")
    if evidence.queue.dead_count:
        reasons.append("projection_jobs_dead")
    if not evidence.queue.lag_within(maximum_queue_lag):
        reasons.append("projection_queue_lag_exceeded")
    if not any(lane.required for lane in evidence.lanes):
        reasons.append("required_lane_missing")
    if any(lane.required and not lane.healthy for lane in evidence.lanes):
        reasons.append("required_lane_unhealthy")
    if any(lane.required and not lane.profile_qualified for lane in evidence.lanes):
        reasons.append("required_lane_unqualified")
    if not evidence.tombstones.complete:
        reasons.append("retained_profile_tombstones_incomplete")
    return ProfileActivationDecision(not reasons, tuple(reasons))


def _require_nonnegative_int(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"Profile {name} must be a non-negative integer")


def _require_digest(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"Profile {name} must be lowercase SHA-256")


def accumulate_attestation_digest(
    accumulator: str, identity: str, version: int, payload_digest: str
) -> str:
    """Order-independent, resumable multiset accumulator for bounded adapters."""

    _require_digest("attestation accumulator", accumulator)
    _require_digest("attestation payload_digest", payload_digest)
    framed = f"{identity}\0{version}\0{payload_digest}\n".encode()
    value = (int(accumulator, 16) + int(hashlib.sha256(framed).hexdigest(), 16)) % (1 << 256)
    return f"{value:064x}"


def finalize_attestation_digest(count: int, accumulator: str) -> str:
    _require_nonnegative_int("attestation count", count)
    _require_digest("attestation accumulator", accumulator)
    if count == 0:
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(f"{count}\0{accumulator}".encode()).hexdigest()


__all__ = (
    "ProfileActivationDecision",
    "ProfileActivationEvidence",
    "ProfileAttestationLease",
    "ProfileCoverageAttestation",
    "ProfileLaneHealth",
    "ProfileQueueHealth",
    "ProfileTombstoneHealth",
    "RetrievalProfileIdentity",
    "RetrievalProfileState",
    "RetainedProfile",
    "assess_profile_activation",
    "accumulate_attestation_digest",
    "finalize_attestation_digest",
    "retained_profiles_to_retire",
)
