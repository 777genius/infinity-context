"""Feature-owned memory fact aggregate and public snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TypeAlias

from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactFreshness,
    FactLifecycle,
    FactLifecycleStatus,
    FactQuality,
    FactRetention,
    FactRevision,
    FactTemporalExtent,
)

MemoryFactKind: TypeAlias = str
MemoryFactStatus: TypeAlias = str
MemoryFactConfidence: TypeAlias = str
MemoryFactTrustLevel: TypeAlias = str
MemoryFactClassification: TypeAlias = str


@dataclass(frozen=True, slots=True)
class MemoryFactScope:
    """Canonical scope ownership for a fact without storage concerns."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_non_blank("space_id", self.space_id)
        _require_non_blank("memory_scope_id", self.memory_scope_id)
        if self.thread_id is not None:
            _require_non_blank("thread_id", self.thread_id)


@dataclass(frozen=True, slots=True)
class MemoryFactIdentity:
    """Stable fact identity plus the scope that owns it."""

    fact_id: str
    scope: MemoryFactScope

    def __post_init__(self) -> None:
        _require_non_blank("fact_id", self.fact_id)


@dataclass(frozen=True, slots=True)
class MemoryFactSourceRef:
    """Pointer to the source evidence that supports a fact."""

    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        _require_non_blank("source_type", self.source_type)
        _require_non_blank("source_id", self.source_id)


@dataclass(frozen=True, slots=True)
class MemoryFactEvidenceRef:
    """Named evidence handle that points back to a source reference."""

    source_ref: MemoryFactSourceRef
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactVisibility:
    """Lifecycle fields that determine whether a fact may be shown."""

    status: MemoryFactStatus = "active"
    version: int = 1
    confidence: MemoryFactConfidence = "medium"
    trust_level: MemoryFactTrustLevel = "medium"
    classification: MemoryFactClassification = "internal"
    ttl_policy: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactSnapshot:
    """Immutable read model for a canonical memory fact."""

    identity: MemoryFactIdentity
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    visibility: MemoryFactVisibility = field(default_factory=MemoryFactVisibility)
    kind: MemoryFactKind = "note"
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] = ()
    category: str | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None
    temporal_extent: FactTemporalExtent | None = None
    freshness: FactFreshness = field(default_factory=FactFreshness)
    epistemic_context: FactEpistemicContext = field(default_factory=FactEpistemicContext)
    purge_after: datetime | None = None
    code_scope: FactCodeScopeReference | None = None


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """Canonical aggregate root for fact lifecycle and temporal mutations."""

    identity: MemoryFactIdentity
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    lifecycle: FactLifecycle
    revision: FactRevision
    quality: FactQuality
    temporal_extent: FactTemporalExtent
    freshness: FactFreshness
    retention: FactRetention
    epistemic_context: FactEpistemicContext
    code_scope: FactCodeScopeReference | None = None
    kind: MemoryFactKind = "note"
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] = ()
    category: str | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def remember(
        cls,
        *,
        identity: MemoryFactIdentity,
        text: str,
        source_refs: tuple[MemoryFactSourceRef, ...],
        now: datetime,
        kind: MemoryFactKind = "note",
        evidence_refs: tuple[MemoryFactEvidenceRef, ...] = (),
        category: str | None = None,
        tags: tuple[str, ...] = (),
        quality: FactQuality | None = None,
        temporal_extent: FactTemporalExtent | None = None,
        freshness: FactFreshness | None = None,
        retention: FactRetention | None = None,
        epistemic_context: FactEpistemicContext | None = None,
        code_scope: FactCodeScopeReference | None = None,
    ) -> MemoryFact:
        _require_active_content(text=text, source_refs=source_refs)
        _require_aware("now", now)
        resolved_freshness = freshness or FactFreshness()
        resolved_temporal_extent = temporal_extent or FactTemporalExtent.ongoing_state(
            observed_at=now
        )
        if (
            resolved_freshness.last_confirmed_at is not None
            and resolved_freshness.last_confirmed_at > now
        ):
            raise ValueError("last_confirmed_at cannot be after transaction time")
        if resolved_temporal_extent.observed_at > now:
            raise ValueError("observed_at cannot be after transaction time")
        return cls(
            identity=identity,
            text=text.strip(),
            source_refs=_unique_source_refs(source_refs),
            lifecycle=FactLifecycle(),
            revision=FactRevision(),
            quality=quality or FactQuality(),
            temporal_extent=resolved_temporal_extent,
            freshness=resolved_freshness,
            retention=retention or FactRetention(),
            epistemic_context=epistemic_context or FactEpistemicContext(),
            code_scope=code_scope,
            kind=kind,
            evidence_refs=evidence_refs,
            category=category,
            tags=tuple(tags),
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def restore(cls, snapshot: MemoryFactSnapshot) -> MemoryFact:
        _require_active_content(
            text=snapshot.text,
            source_refs=snapshot.source_refs,
            allow_deleted=snapshot.visibility.status == FactLifecycleStatus.DELETED,
        )
        observed_at = snapshot.created_at or snapshot.updated_at
        if snapshot.temporal_extent is None and observed_at is None:
            raise ValueError("Fact snapshot requires temporal_extent or created_at")
        temporal_extent = snapshot.temporal_extent or FactTemporalExtent(
            kind="state",
            observed_at=observed_at,
            basis="migrated_legacy",
            precision="unknown",
        )
        return cls(
            identity=snapshot.identity,
            text=snapshot.text,
            source_refs=_unique_source_refs(snapshot.source_refs),
            lifecycle=FactLifecycle(snapshot.visibility.status),
            revision=FactRevision(snapshot.visibility.version),
            quality=FactQuality(
                confidence=snapshot.visibility.confidence,
                trust_level=snapshot.visibility.trust_level,
                classification=snapshot.visibility.classification,
            ),
            temporal_extent=temporal_extent,
            freshness=snapshot.freshness,
            retention=FactRetention(
                ttl_policy=snapshot.visibility.ttl_policy,
                context_expires_at=snapshot.visibility.expires_at,
                purge_after=snapshot.purge_after,
            ),
            epistemic_context=snapshot.epistemic_context,
            code_scope=snapshot.code_scope,
            kind=snapshot.kind,
            evidence_refs=snapshot.evidence_refs,
            category=snapshot.category,
            tags=snapshot.tags,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
        )

    def update(
        self,
        *,
        expected_version: int,
        text: str,
        source_refs: tuple[MemoryFactSourceRef, ...],
        now: datetime,
        kind: MemoryFactKind,
        evidence_refs: tuple[MemoryFactEvidenceRef, ...],
        category: str | None,
        tags: tuple[str, ...],
        retention: FactRetention | None = None,
    ) -> MemoryFact:
        self._require_mutable(expected_version)
        if self.lifecycle.status is not FactLifecycleStatus.ACTIVE:
            raise ValueError("Only an active memory fact can receive a content update")
        _require_active_content(text=text, source_refs=source_refs)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        return replace(
            self,
            text=text.strip(),
            source_refs=_unique_source_refs(source_refs),
            lifecycle=self.lifecycle,
            revision=self.revision.next(),
            # Confirmation belongs to the exact content revision. A correction must
            # be confirmed again; otherwise old evidence is falsely attached to new text.
            freshness=FactFreshness(),
            retention=retention or self.retention,
            kind=kind,
            evidence_refs=evidence_refs,
            category=category,
            tags=tuple(tags),
            updated_at=now,
        )

    def forget(self, *, expected_version: int | None, now: datetime) -> MemoryFact:
        if expected_version is not None and self.revision.value != expected_version:
            _raise_version_conflict(expected_version, self.revision.value)
        if self.lifecycle.status is FactLifecycleStatus.DELETED:
            raise ValueError(f"Memory fact is already deleted: {self.identity.fact_id}")
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        return replace(
            self,
            lifecycle=FactLifecycle(FactLifecycleStatus.DELETED),
            revision=self.revision.next(),
            updated_at=now,
        )

    def attach_evidence(
        self,
        *,
        expected_version: int,
        source_refs: tuple[MemoryFactSourceRef, ...],
        evidence_refs: tuple[MemoryFactEvidenceRef, ...],
        now: datetime,
    ) -> MemoryFact:
        """Attach evidence to the same proposition without changing its truth semantics."""

        self._require_mutable(expected_version)
        if self.lifecycle.status is FactLifecycleStatus.DELETED:
            raise ValueError("Deleted memory fact cannot receive evidence")
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        merged_sources = _unique_source_refs((*self.source_refs, *source_refs))
        merged_evidence = tuple(dict.fromkeys((*self.evidence_refs, *evidence_refs)))
        if merged_sources == self.source_refs and merged_evidence == self.evidence_refs:
            raise ValueError("No new fact evidence to attach")
        return replace(
            self,
            source_refs=merged_sources,
            evidence_refs=merged_evidence,
            revision=self.revision.next(),
            updated_at=now,
        )

    def confirm(
        self,
        *,
        expected_version: int,
        confirmed_at: datetime,
        confirmation_basis: str,
        now: datetime,
    ) -> MemoryFact:
        self._require_mutable(expected_version)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        if confirmed_at > now:
            raise ValueError("confirmed_at cannot be after transaction time")
        if (
            self.freshness.last_confirmed_at is not None
            and confirmed_at < self.freshness.last_confirmed_at
        ):
            raise ValueError("confirmed_at cannot move backwards")
        return replace(
            self,
            revision=self.revision.next(),
            freshness=FactFreshness(
                last_confirmed_at=confirmed_at,
                confirmation_basis=confirmation_basis,
            ),
            updated_at=now,
        )

    def end_validity(
        self,
        *,
        expected_version: int,
        effective_at: datetime,
        now: datetime,
    ) -> MemoryFact:
        """Close an open state validity interval without inventing a successor."""

        self._require_mutable(expected_version)
        _require_aware("effective_at", effective_at)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        if effective_at > now:
            raise ValueError("Scheduled validity changes are not supported")
        if self.temporal_extent.kind.value != "state":
            raise ValueError("Only state facts have validity that can be ended")
        if self.temporal_extent.valid_from is None:
            raise ValueError("State fact validity cannot end when valid_from is unknown")
        if self.temporal_extent.valid_to is not None:
            raise ValueError("State fact validity is already closed")
        return replace(
            self,
            revision=self.revision.next(),
            temporal_extent=replace(self.temporal_extent, valid_to=effective_at),
            updated_at=now,
        )

    def record_as_supersession_successor(
        self,
        *,
        expected_version: int,
        effective_at: datetime,
        now: datetime,
    ) -> MemoryFact:
        """Advance the aggregate revision for an owned supersession relation."""

        self._require_mutable(expected_version)
        _require_aware("effective_at", effective_at)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        if effective_at > now:
            raise ValueError("Scheduled supersession is not supported")
        return replace(
            self,
            revision=self.revision.next(),
            updated_at=now,
        )

    def supersede(
        self,
        *,
        expected_version: int,
        effective_at: datetime,
        now: datetime,
    ) -> MemoryFact:
        """Close semantic validity and mark lifecycle only once replacement applies."""

        self._require_mutable(expected_version)
        _require_aware("effective_at", effective_at)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        if effective_at > now:
            raise ValueError("Scheduled supersession is not supported")
        if self.temporal_extent.kind.value != "state":
            raise ValueError("Only state facts can be superseded")
        closed_extent = replace(self.temporal_extent, valid_to=effective_at)
        lifecycle = (
            FactLifecycle(FactLifecycleStatus.SUPERSEDED) if effective_at <= now else self.lifecycle
        )
        return replace(
            self,
            lifecycle=lifecycle,
            revision=self.revision.next(),
            temporal_extent=closed_extent,
            updated_at=now,
        )

    def dispute(
        self,
        *,
        expected_version: int,
        now: datetime,
    ) -> MemoryFact:
        """Move an active claim out of normal context pending explicit resolution."""

        self._require_mutable(expected_version)
        _require_aware("now", now)
        self._require_monotonic_transaction_time(now)
        if self.lifecycle.status is not FactLifecycleStatus.ACTIVE:
            raise ValueError("Only an active memory fact can become disputed")
        return replace(
            self,
            lifecycle=FactLifecycle(FactLifecycleStatus.DISPUTED),
            revision=self.revision.next(),
            updated_at=now,
        )

    def to_snapshot(self) -> MemoryFactSnapshot:
        return MemoryFactSnapshot(
            identity=self.identity,
            text=self.text,
            source_refs=self.source_refs,
            visibility=MemoryFactVisibility(
                status=self.lifecycle.status.value,
                version=self.revision.value,
                confidence=self.quality.confidence,
                trust_level=self.quality.trust_level,
                classification=self.quality.classification,
                ttl_policy=self.retention.ttl_policy,
                expires_at=self.retention.context_expires_at,
            ),
            kind=self.kind,
            evidence_refs=self.evidence_refs,
            category=self.category,
            tags=self.tags,
            created_at=self.created_at,
            updated_at=self.updated_at,
            temporal_extent=self.temporal_extent,
            freshness=self.freshness,
            epistemic_context=self.epistemic_context,
            purge_after=self.retention.purge_after,
            code_scope=self.code_scope,
        )

    def require_revision(self, expected_version: int) -> None:
        if self.revision.value != expected_version:
            _raise_version_conflict(expected_version, self.revision.value)

    def _require_monotonic_transaction_time(self, now: datetime) -> None:
        if self.updated_at is not None and now < self.updated_at:
            raise ValueError("Fact transaction time cannot move backwards")

    def _require_mutable(self, expected_version: int) -> None:
        if self.lifecycle.status in {
            FactLifecycleStatus.DELETED,
            FactLifecycleStatus.SUPERSEDED,
        }:
            raise ValueError(
                f"{self.lifecycle.status.value.title()} memory fact cannot be updated: "
                f"{self.identity.fact_id}"
            )
        self.require_revision(expected_version)


def _require_active_content(
    *,
    text: str,
    source_refs: tuple[MemoryFactSourceRef, ...],
    allow_deleted: bool = False,
) -> None:
    if not text.strip() and not allow_deleted:
        raise ValueError("Memory fact text is required")
    if not source_refs and not allow_deleted:
        raise ValueError("Memory fact source_refs are required")


def _unique_source_refs(
    source_refs: tuple[MemoryFactSourceRef, ...],
) -> tuple[MemoryFactSourceRef, ...]:
    return tuple(dict.fromkeys(source_refs))


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_non_blank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _raise_version_conflict(expected: int, actual: int) -> None:
    raise ValueError(f"Memory fact version conflict: expected {expected}, actual {actual}")


__all__ = (
    "MemoryFactClassification",
    "MemoryFactConfidence",
    "MemoryFact",
    "MemoryFactEvidenceRef",
    "MemoryFactIdentity",
    "MemoryFactKind",
    "MemoryFactScope",
    "MemoryFactSnapshot",
    "MemoryFactSourceRef",
    "MemoryFactStatus",
    "MemoryFactTrustLevel",
    "MemoryFactVisibility",
)
