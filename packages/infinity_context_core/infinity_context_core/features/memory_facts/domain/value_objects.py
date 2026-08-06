"""Value objects owned by the memory_facts aggregate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FactLifecycleStatus(StrEnum):
    ACTIVE = "active"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class FactTemporalKind(StrEnum):
    STATE = "state"
    EVENT = "event"
    TIMELESS = "timeless"


class FactEpistemicMode(StrEnum):
    WORLD_CLAIM = "world_claim"
    PERSPECTIVE = "perspective"
    HYPOTHESIS = "hypothesis"


class FactConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactTrustLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FactClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"

    @property
    def prompt_visible(self) -> bool:
        return self in {FactClassification.PUBLIC, FactClassification.INTERNAL}


@dataclass(frozen=True, slots=True)
class FactCodeScopeReference:
    """Opaque cross-context reference to CodeRepository and optional CodeScope."""

    repository_id: str
    code_scope_id: str | None = None

    def __post_init__(self) -> None:
        _require_opaque("repository_id", self.repository_id)
        if self.code_scope_id is not None:
            _require_opaque("code_scope_id", self.code_scope_id)

    def is_visible_in(
        self,
        *,
        repository_id: str | None,
        code_scope_id: str | None,
    ) -> bool:
        if repository_id != self.repository_id:
            return False
        return self.code_scope_id is None or self.code_scope_id == code_scope_id


@dataclass(frozen=True, slots=True)
class FactLifecycle:
    """Canonical lifecycle, independent from real-world temporal validity."""

    status: FactLifecycleStatus = FactLifecycleStatus.ACTIVE

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", FactLifecycleStatus(self.status))


@dataclass(frozen=True, slots=True)
class FactRevision:
    """One monotonic revision clock for every aggregate mutation."""

    value: int = 1

    def __post_init__(self) -> None:
        if self.value < 1:
            raise ValueError("Fact revision must be positive")

    def next(self) -> FactRevision:
        return FactRevision(self.value + 1)


@dataclass(frozen=True, slots=True)
class FactQuality:
    """Evidence quality and disclosure classification."""

    confidence: FactConfidence = FactConfidence.MEDIUM
    trust_level: FactTrustLevel = FactTrustLevel.MEDIUM
    classification: FactClassification = FactClassification.INTERNAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _enum_value(FactConfidence, self.confidence))
        object.__setattr__(self, "trust_level", _enum_value(FactTrustLevel, self.trust_level))
        object.__setattr__(
            self,
            "classification",
            _enum_value(FactClassification, self.classification),
        )


@dataclass(frozen=True, slots=True)
class FactTemporalExtent:
    """Observed time plus mutually exclusive state/event/timeless semantics."""

    kind: FactTemporalKind
    observed_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    basis: str = "unknown"
    precision: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", FactTemporalKind(self.kind))
        for field_name in (
            "observed_at",
            "valid_from",
            "valid_to",
            "occurred_from",
            "occurred_to",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_aware(field_name, value)
        _require_non_blank("basis", self.basis)
        _require_non_blank("precision", self.precision)
        _require_order("validity", self.valid_from, self.valid_to)
        _require_order("occurrence", self.occurred_from, self.occurred_to)

        if self.kind is FactTemporalKind.STATE and (
            self.occurred_from is not None or self.occurred_to is not None
        ):
            raise ValueError("State fact cannot define event occurrence")
        if self.kind is FactTemporalKind.EVENT:
            if self.valid_from is not None or self.valid_to is not None:
                raise ValueError("Event fact cannot define state validity")
            if self.occurred_from is None:
                raise ValueError("Event fact requires occurred_from")
        if self.kind is FactTemporalKind.TIMELESS and any(
            value is not None
            for value in (
                self.valid_from,
                self.valid_to,
                self.occurred_from,
                self.occurred_to,
            )
        ):
            raise ValueError("Timeless fact cannot define a temporal interval")

    @classmethod
    def ongoing_state(
        cls,
        *,
        observed_at: datetime,
        valid_from: datetime | None = None,
        basis: str = "asserted",
        precision: str = "exact",
    ) -> FactTemporalExtent:
        return cls(
            kind=FactTemporalKind.STATE,
            observed_at=observed_at,
            valid_from=valid_from or observed_at,
            basis=basis,
            precision=precision,
        )


@dataclass(frozen=True, slots=True)
class FactFreshness:
    """Explicit evidence confirmation; never derived from aggregate update time."""

    last_confirmed_at: datetime | None = None
    confirmation_basis: str | None = None

    def __post_init__(self) -> None:
        if self.last_confirmed_at is not None:
            _require_aware("last_confirmed_at", self.last_confirmed_at)
            if not self.confirmation_basis or not self.confirmation_basis.strip():
                raise ValueError("Confirmed fact requires confirmation_basis")
        elif self.confirmation_basis is not None:
            raise ValueError("confirmation_basis requires last_confirmed_at")


@dataclass(frozen=True, slots=True)
class FactRetention:
    """Prompt eligibility expiry and optional physical-retention boundary."""

    ttl_policy: str | None = None
    context_expires_at: datetime | None = None
    purge_after: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("context_expires_at", "purge_after"):
            value = getattr(self, field_name)
            if value is not None:
                _require_aware(field_name, value)
        if self.ttl_policy is not None:
            _require_non_blank("ttl_policy", self.ttl_policy)
        if (
            self.context_expires_at is not None
            and self.purge_after is not None
            and self.purge_after < self.context_expires_at
        ):
            raise ValueError("purge_after cannot precede context_expires_at")

    def is_context_visible_at(self, reference_time: datetime) -> bool:
        _require_aware("reference_time", reference_time)
        return self.context_expires_at is None or reference_time < self.context_expires_at


@dataclass(frozen=True, slots=True)
class FactEpistemicContext:
    """Whose claim this is and whether it is asserted as truth or hypothesis."""

    mode: FactEpistemicMode = FactEpistemicMode.WORLD_CLAIM
    asserted_by: str | None = None
    perspective_subject: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", FactEpistemicMode(self.mode))
        if self.asserted_by is not None:
            _require_non_blank("asserted_by", self.asserted_by)
        if self.perspective_subject is not None:
            _require_non_blank("perspective_subject", self.perspective_subject)
        if self.mode is FactEpistemicMode.PERSPECTIVE and self.perspective_subject is None:
            raise ValueError("Perspective fact requires perspective_subject")
        if self.mode is not FactEpistemicMode.PERSPECTIVE and self.perspective_subject is not None:
            raise ValueError("perspective_subject is valid only for perspective facts")

    def is_automatically_comparable_with(self, other: FactEpistemicContext) -> bool:
        if self.mode is FactEpistemicMode.HYPOTHESIS:
            return False
        if other.mode is FactEpistemicMode.HYPOTHESIS:
            return False
        if self.mode is not other.mode:
            return False
        if self.mode is FactEpistemicMode.PERSPECTIVE:
            return self.perspective_subject == other.perspective_subject
        return True


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_non_blank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _enum_value(enum_type: type[StrEnum], value: object) -> StrEnum:
    try:
        return enum_type(str(value).strip().lower())
    except ValueError as exc:
        raise ValueError(f"Unknown {enum_type.__name__}: {value}") from exc


def _require_opaque(field_name: str, value: str) -> None:
    _require_non_blank(field_name, value)
    if "://" in value or value.startswith("/") or "\\" in value or "@" in value:
        raise ValueError(f"{field_name} must be an opaque identifier")


def _require_order(
    interval_name: str,
    start: datetime | None,
    end: datetime | None,
) -> None:
    if start is not None and end is not None and end <= start:
        raise ValueError(f"{interval_name} end must be after start")


__all__ = (
    "FactCodeScopeReference",
    "FactEpistemicContext",
    "FactEpistemicMode",
    "FactFreshness",
    "FactLifecycle",
    "FactLifecycleStatus",
    "FactQuality",
    "FactRetention",
    "FactRevision",
    "FactTemporalExtent",
    "FactTemporalKind",
)
