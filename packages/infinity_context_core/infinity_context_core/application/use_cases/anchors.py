"""Semantic anchor lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key,
    extract_observed_anchors,
    normalize_anchor_key,
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.dto import (
    AnchorBackfillSourceSummary,
    AnchorMergeCandidate,
    AnchorMergeSuggestionsQuery,
    AnchorMergeSuggestionsResult,
    AnchorResult,
    AnchorsResult,
    BackfillAnchorsCommand,
    BackfillAnchorsResult,
    CreateAnchorCommand,
    DeleteAnchorCommand,
    ListAnchorsQuery,
    MergeAnchorsCommand,
    SplitAnchorCommand,
    UpdateAnchorCommand,
)
from infinity_context_core.application.observed_anchor_resolution import (
    canonical_anchor_keys as _canonical_anchor_keys,
)
from infinity_context_core.application.observed_anchor_resolution import (
    find_active_by_observed_canonical_key as _find_active_by_observed_canonical_key,
)
from infinity_context_core.application.observed_anchor_resolution import (
    preferred_observed_label as _preferred_observed_label,
)
from infinity_context_core.application.observed_anchor_resolution import (
    should_promote_observed_key as _should_promote_observed_key,
)
from infinity_context_core.domain.entities import (
    Confidence,
    LifecycleStatus,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

_ANCHOR_RESOLVER_VERSION = "anchor-lifecycle-v2"
_LABEL_SIMILARITY_MERGE_THRESHOLD = 0.86


@dataclass(frozen=True)
class _ObservedAnchorUpsertResult:
    anchor: MemoryAnchor | None
    created: bool = False
    skipped_reason: str | None = None


class ListAnchorsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListAnchorsQuery) -> AnchorsResult:
        async with self._uow_factory() as uow:
            anchors = await uow.anchors.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                kind=query.kind,
                status=query.status,
                limit=query.limit,
            )
        return AnchorsResult(anchors=tuple(anchors))


class CreateAnchorUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: CreateAnchorCommand) -> AnchorResult:
        label = command.label.strip()
        if not label:
            raise MemoryValidationError("Anchor label is required")
        try:
            kind = MemoryAnchorKind(command.kind.strip().lower())
        except ValueError as exc:
            supported = ", ".join(item.value for item in MemoryAnchorKind)
            raise MemoryValidationError(
                f"Unsupported anchor kind. Supported kinds: {supported}"
            ) from exc
        normalized_key = normalize_anchor_key(label)
        if not normalized_key:
            raise MemoryValidationError("Anchor normalized key is required")
        confidence = _parse_anchor_confidence(command.confidence)
        now = self._clock.now()
        metadata = _manual_anchor_metadata(
            kind=kind,
            label=label,
            metadata=command.metadata,
            audit={"creation_source": "manual"},
        )
        async with self._uow_factory() as uow:
            existing = await uow.anchors.find_active_by_key(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                kind=kind.value,
                normalized_key=normalized_key,
            )
            if existing is not None:
                await _assert_anchor_aliases_available(
                    uow,
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    kind=kind.value,
                    label=label,
                    aliases=command.aliases,
                    exclude_anchor_ids=(str(existing.id),),
                )
                anchor = await uow.anchors.save(
                    existing.update_details(
                        label=label,
                        aliases=command.aliases,
                        description=command.description,
                        confidence=confidence,
                        evidence_refs=command.evidence_refs,
                        observed_at=command.observed_at,
                        valid_from=command.valid_from,
                        valid_to=command.valid_to,
                        metadata=metadata,
                        now=now,
                    )
                )
            else:
                await _assert_anchor_aliases_available(
                    uow,
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    kind=kind.value,
                    label=label,
                    aliases=command.aliases,
                )
                anchor = await uow.anchors.create(
                    MemoryAnchor.create(
                        anchor_id=MemoryAnchorId(self._ids.new_id("anchor")),
                        space_id=command.space_id,
                        memory_scope_id=command.memory_scope_id,
                        kind=kind,
                        normalized_key=normalized_key,
                        label=label,
                        aliases=command.aliases,
                        description=command.description,
                        confidence=confidence,
                        evidence_refs=command.evidence_refs,
                        observed_at=command.observed_at,
                        valid_from=command.valid_from,
                        valid_to=command.valid_to,
                        metadata=metadata,
                        now=now,
                    )
                )
            await uow.commit()
        return AnchorResult(anchor=anchor)


class UpdateAnchorUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: UpdateAnchorCommand) -> AnchorResult:
        label = command.label.strip() if command.label is not None else None
        if command.label is not None and not label:
            raise MemoryValidationError("Anchor label is required")
        normalized_key = normalize_anchor_key(label) if label else None
        confidence = _parse_optional_anchor_confidence(command.confidence)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            anchor = await _get_anchor(uow, command.anchor_id, role="anchor")
            if normalized_key and normalized_key != anchor.normalized_key:
                conflict = await uow.anchors.find_active_by_key(
                    space_id=str(anchor.space_id),
                    memory_scope_id=str(anchor.memory_scope_id),
                    kind=anchor.kind.value,
                    normalized_key=normalized_key,
                )
                if conflict is not None and conflict.id != anchor.id:
                    raise MemoryConflictError(
                        "Anchor label conflicts with an existing active anchor"
                    )
            await _assert_anchor_aliases_available(
                uow,
                space_id=str(anchor.space_id),
                memory_scope_id=str(anchor.memory_scope_id),
                kind=anchor.kind.value,
                label=label or anchor.label,
                aliases=command.aliases,
                exclude_anchor_ids=(str(anchor.id),),
            )
            saved = await uow.anchors.save(
                anchor.update_details(
                    normalized_key=normalized_key,
                    label=label,
                    aliases=command.aliases,
                    description=command.description,
                    confidence=confidence,
                    evidence_refs=command.evidence_refs,
                    observed_at=command.observed_at,
                    valid_from=command.valid_from,
                    valid_to=command.valid_to,
                    metadata=_manual_anchor_metadata(
                        kind=anchor.kind,
                        label=label,
                        metadata=command.metadata,
                        audit={"last_edit_source": "manual"},
                    ),
                    now=now,
                )
            )
            await uow.commit()
        return AnchorResult(anchor=saved)


class DeleteAnchorUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: DeleteAnchorCommand) -> AnchorResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            anchor = await _get_anchor(uow, command.anchor_id, role="anchor")
            deleted = await uow.anchors.save(anchor.delete(reason=command.reason, now=now))
            await uow.commit()
        return AnchorResult(anchor=deleted)


class SuggestAnchorMergesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: AnchorMergeSuggestionsQuery) -> AnchorMergeSuggestionsResult:
        async with self._uow_factory() as uow:
            anchors = await uow.anchors.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                kind=query.kind,
                status=LifecycleStatus.ACTIVE.value,
                limit=max(query.limit * 4, 100),
            )
        candidates = _rank_merge_candidates(anchors)[: query.limit]
        return AnchorMergeSuggestionsResult(
            candidates=tuple(candidates),
            diagnostics={
                "resolver_version": _ANCHOR_RESOLVER_VERSION,
                "anchor_count": len(anchors),
                "candidate_count": len(candidates),
            },
        )


class MergeAnchorsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: MergeAnchorsCommand) -> AnchorResult:
        reason = command.reason.strip()
        if not reason:
            raise MemoryValidationError("Anchor merge reason is required")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            source = await _get_anchor(uow, command.source_anchor_id, role="source")
            target = await _get_anchor(uow, command.target_anchor_id, role="target")
            await _assert_anchor_aliases_available(
                uow,
                space_id=str(target.space_id),
                memory_scope_id=str(target.memory_scope_id),
                kind=target.kind.value,
                label=target.label,
                aliases=(*target.aliases, source.label, *source.aliases),
                exclude_anchor_ids=(str(source.id), str(target.id)),
            )
            merged_target = target.merge_source(source=source, reason=reason, now=now)
            merged_source = source.mark_merged_into(
                target_anchor_id=target.id,
                reason=reason,
                now=now,
            )
            await uow.anchors.save(merged_target)
            await uow.anchors.save(merged_source)
            await uow.commit()
        return AnchorResult(anchor=merged_target)


class SplitAnchorUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: SplitAnchorCommand) -> AnchorResult:
        alias = command.alias.strip()
        label = (command.new_label or alias).strip()
        reason = command.reason.strip() or "manual split"
        if not alias:
            raise MemoryValidationError("Anchor split alias is required")
        if not label:
            raise MemoryValidationError("Anchor split label is required")
        normalized_key = normalize_anchor_key(label)
        if not normalized_key:
            raise MemoryValidationError("Anchor split normalized key is required")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            anchor = await _get_anchor(uow, command.anchor_id, role="anchor")
            updated_anchor = anchor.remove_alias(alias=alias, reason=reason, now=now)
            existing = await uow.anchors.find_active_by_key(
                space_id=str(anchor.space_id),
                memory_scope_id=str(anchor.memory_scope_id),
                kind=anchor.kind.value,
                normalized_key=normalized_key,
            )
            if existing is None:
                existing = await _find_active_anchor_by_alias_key(
                    uow,
                    space_id=str(anchor.space_id),
                    memory_scope_id=str(anchor.memory_scope_id),
                    kind=anchor.kind.value,
                    alias_key=normalized_key,
                    exclude_anchor_ids=(str(anchor.id),),
                )
            await _assert_anchor_aliases_available(
                uow,
                space_id=str(anchor.space_id),
                memory_scope_id=str(anchor.memory_scope_id),
                kind=anchor.kind.value,
                label=label,
                aliases=(alias,),
                exclude_anchor_ids=(
                    str(anchor.id),
                    *((str(existing.id),) if existing is not None else ()),
                ),
            )
            if existing is not None:
                new_anchor = existing.merge_observation(
                    label=label,
                    aliases=(alias,),
                    evidence_refs=anchor.evidence_refs,
                    confidence=anchor.confidence,
                    observed_at=anchor.observed_at,
                    valid_from=anchor.valid_from,
                    valid_to=anchor.valid_to,
                    metadata={
                        "resolver_version": _ANCHOR_RESOLVER_VERSION,
                        "split_from_anchor_id": str(anchor.id),
                        "split_reason": reason,
                        **structured_anchor_metadata_for_label(anchor.kind, label),
                    },
                    now=now,
                )
                await uow.anchors.save(new_anchor)
            else:
                new_anchor = MemoryAnchor.create(
                    anchor_id=MemoryAnchorId(self._ids.new_id("anchor")),
                    space_id=anchor.space_id,
                    memory_scope_id=anchor.memory_scope_id,
                    kind=anchor.kind,
                    normalized_key=normalized_key,
                    label=label,
                    aliases=(alias,),
                    description=f"Split from {anchor.kind.value} anchor {anchor.label}.",
                    confidence=anchor.confidence,
                    evidence_refs=anchor.evidence_refs,
                    observed_at=anchor.observed_at,
                    valid_from=anchor.valid_from,
                    valid_to=anchor.valid_to,
                    metadata={
                        "resolver_version": _ANCHOR_RESOLVER_VERSION,
                        "split_from_anchor_id": str(anchor.id),
                        "split_reason": reason,
                        **structured_anchor_metadata_for_label(anchor.kind, label),
                    },
                    now=now,
                )
                await uow.anchors.create(new_anchor)
            await uow.anchors.save(updated_anchor)
            await uow.commit()
        return AnchorResult(anchor=new_anchor)


class BackfillAnchorsUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: BackfillAnchorsCommand) -> BackfillAnchorsResult:
        limit = max(1, min(command.limit_per_source, 500))
        now = self._clock.now()
        created = 0
        updated = 0
        skipped_conflicts = 0
        touched: dict[str, MemoryAnchor] = {}
        source_summaries: list[AnchorBackfillSourceSummary] = []
        async with self._uow_factory() as uow:
            sources = await _load_backfill_sources(
                uow,
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                limit=limit,
            )
            for source_type, items in sources:
                observed_count = 0
                source_skipped_conflicts = 0
                for item in items:
                    observed = extract_observed_anchors(item.text)
                    observed_count += len(observed)
                    for anchor in observed:
                        upsert_result = await _upsert_observed_anchor(
                            uow,
                            ids=self._ids,
                            observed=anchor,
                            space_id=command.space_id,
                            memory_scope_id=command.memory_scope_id,
                            source_type=source_type,
                            source_id=item.source_id,
                            now=now,
                        )
                        if upsert_result.anchor is None:
                            if upsert_result.skipped_reason == "alias_conflict":
                                skipped_conflicts += 1
                                source_skipped_conflicts += 1
                            continue
                        touched[str(upsert_result.anchor.id)] = upsert_result.anchor
                        if upsert_result.created:
                            created += 1
                        else:
                            updated += 1
                source_summaries.append(
                    AnchorBackfillSourceSummary(
                        source_type=source_type,
                        scanned=len(items),
                        observed=observed_count,
                        skipped_conflicts=source_skipped_conflicts,
                    )
                )
            await uow.commit()
        return BackfillAnchorsResult(
            anchors=tuple(touched.values()),
            created=created,
            updated=updated,
            sources=tuple(source_summaries),
            diagnostics={
                "resolver_version": _ANCHOR_RESOLVER_VERSION,
                "limit_per_source": limit,
                "skipped_count": skipped_conflicts,
                "skipped_conflict_count": skipped_conflicts,
            },
        )


@dataclass(frozen=True)
class _BackfillText:
    source_id: str
    text: str


async def _get_anchor(uow: UnitOfWorkPort, anchor_id: str, *, role: str) -> MemoryAnchor:
    anchor = await uow.anchors.get_by_id(anchor_id)
    if anchor is None:
        raise MemoryNotFoundError(f"Anchor {role} not found")
    return anchor


async def _load_backfill_sources(
    uow: UnitOfWorkPort,
    *,
    space_id: str,
    memory_scope_id: str,
    limit: int,
) -> tuple[tuple[str, tuple[_BackfillText, ...]], ...]:
    captures = await uow.captures.list_for_scope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        status="accepted",
        consolidation_status=None,
        limit=limit,
    )
    facts = await uow.facts.list_for_scope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=None,
        status="active",
        limit=limit,
    )
    documents = await uow.documents.list_for_scope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=None,
        status="active",
        limit=limit,
    )
    chunks: list[_BackfillText] = []
    for document in documents:
        for chunk in await uow.documents.list_chunks(str(document.id), limit=20):
            chunks.append(_BackfillText(source_id=str(chunk.id), text=chunk.text))
            if len(chunks) >= limit:
                break
        if len(chunks) >= limit:
            break
    return (
        (
            "capture",
            tuple(_BackfillText(source_id=str(item.id), text=item.text) for item in captures),
        ),
        ("fact", tuple(_BackfillText(source_id=str(item.id), text=item.text) for item in facts)),
        ("chunk", tuple(chunks)),
    )


async def _upsert_observed_anchor(
    uow: UnitOfWorkPort,
    *,
    ids: IdGeneratorPort,
    observed: ObservedAnchor,
    space_id: SpaceId,
    memory_scope_id: MemoryScopeId,
    source_type: str,
    source_id: str,
    now: datetime,
) -> _ObservedAnchorUpsertResult:
    existing = await uow.anchors.find_active_by_key(
        space_id=str(space_id),
        memory_scope_id=str(memory_scope_id),
        kind=observed.kind.value,
        normalized_key=observed.normalized_key,
    )
    if existing is None:
        existing = await _find_active_by_observed_canonical_key(
            uow,
            observed=observed,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )
    if existing is None:
        existing = await _find_active_anchor_by_alias_key(
            uow,
            space_id=str(space_id),
            memory_scope_id=str(memory_scope_id),
            kind=observed.kind.value,
            alias_key=observed.normalized_key,
        )
    metadata = {
        **observed.metadata,
        "last_backfill_source_type": source_type,
        "last_backfill_source_id": source_id,
        "resolver_version": _ANCHOR_RESOLVER_VERSION,
    }
    confidence = _confidence_for_observed_anchor(observed)
    evidence_refs = (SourceRef(source_type=source_type, source_id=source_id),)
    try:
        await _assert_anchor_aliases_available(
            uow,
            space_id=str(space_id),
            memory_scope_id=str(memory_scope_id),
            kind=observed.kind.value,
            label=observed.label,
            aliases=observed.aliases,
            exclude_anchor_ids=(str(existing.id),) if existing is not None else (),
        )
    except MemoryConflictError:
        return _ObservedAnchorUpsertResult(anchor=None, skipped_reason="alias_conflict")
    if existing is not None:
        merged = (
            existing.update_details(
                normalized_key=observed.normalized_key,
                label=observed.label,
                aliases=observed.aliases,
                confidence=confidence,
                evidence_refs=evidence_refs,
                observed_at=now,
                metadata=metadata,
                now=now,
            )
            if _should_promote_observed_key(existing, observed)
            else existing.merge_observation(
                label=_preferred_observed_label(existing, observed),
                aliases=observed.aliases,
                confidence=confidence,
                evidence_refs=evidence_refs,
                observed_at=now,
                metadata=metadata,
                now=now,
            )
        )
        saved = await uow.anchors.save(merged)
        return _ObservedAnchorUpsertResult(anchor=saved, created=False)
    saved = await uow.anchors.create(
        MemoryAnchor.create(
            anchor_id=MemoryAnchorId(ids.new_id("anchor")),
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            kind=observed.kind,
            normalized_key=observed.normalized_key,
            label=observed.label,
            aliases=observed.aliases,
            description=f"Observed {observed.kind.value} anchor from memory backfill.",
            confidence=confidence,
            evidence_refs=evidence_refs,
            observed_at=now,
            metadata=metadata,
            now=now,
        )
    )
    return _ObservedAnchorUpsertResult(anchor=saved, created=True)


async def _assert_anchor_aliases_available(
    uow: UnitOfWorkPort,
    *,
    space_id: str,
    memory_scope_id: str,
    kind: str,
    label: str,
    aliases: tuple[str, ...],
    exclude_anchor_ids: tuple[str, ...] = (),
) -> None:
    proposed_keys = _anchor_alias_keys(kind=kind, label=label, aliases=aliases)
    if not proposed_keys:
        return
    conflict = await _find_active_anchor_by_alias_key(
        uow,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        kind=kind,
        alias_key=None,
        candidate_keys=proposed_keys,
        exclude_anchor_ids=exclude_anchor_ids,
    )
    if conflict is not None:
        raise MemoryConflictError("Anchor alias conflicts with an existing active anchor")


async def _find_active_anchor_by_alias_key(
    uow: UnitOfWorkPort,
    *,
    space_id: str,
    memory_scope_id: str,
    kind: str,
    alias_key: str | None = None,
    candidate_keys: tuple[str, ...] | None = None,
    exclude_anchor_ids: tuple[str, ...] = (),
) -> MemoryAnchor | None:
    keys = candidate_keys or ((alias_key,) if alias_key else ())
    keys = tuple(key for key in keys if key)
    if not keys:
        return None
    excluded = set(exclude_anchor_ids)
    anchors = await uow.anchors.list_for_scope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        kind=kind,
        status=LifecycleStatus.ACTIVE.value,
        limit=1000,
    )
    for anchor in anchors:
        if str(anchor.id) in excluded:
            continue
        if set(keys) & set(
            _anchor_alias_keys(kind=kind, label=anchor.label, aliases=anchor.aliases)
        ):
            return anchor
    return None


def _anchor_alias_keys(*, kind: str, label: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    keys = {
        normalized
        for value in (label, *aliases)
        if (normalized := normalize_anchor_key(value))
    }
    if kind in {MemoryAnchorKind.ORGANIZATION.value, MemoryAnchorKind.PROJECT.value}:
        keys.update(_compact_anchor_key(key) for key in tuple(keys))
    return tuple(sorted(keys))


def _compact_anchor_key(value: str) -> str:
    return "".join(value.split())


def _parse_anchor_confidence(value: str | None) -> Confidence:
    if value is None:
        return Confidence.MEDIUM
    return _parse_optional_anchor_confidence(value) or Confidence.MEDIUM


def _parse_optional_anchor_confidence(value: str | None) -> Confidence | None:
    if value is None:
        return None
    try:
        return Confidence(value.strip().lower())
    except ValueError as exc:
        supported = ", ".join(item.value for item in Confidence)
        raise MemoryValidationError(
            f"Unsupported anchor confidence. Supported: {supported}"
        ) from exc


def _confidence_for_observed_anchor(observed: ObservedAnchor) -> Confidence:
    if observed.score_boost >= 22:
        return Confidence.HIGH
    if observed.score_boost <= 8:
        return Confidence.LOW
    return Confidence.MEDIUM


def _rank_merge_candidates(anchors: list[MemoryAnchor]) -> list[AnchorMergeCandidate]:
    candidates: list[AnchorMergeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for index, anchor in enumerate(anchors):
        for other in anchors[index + 1 :]:
            if anchor.kind != other.kind:
                continue
            score, reasons, metadata = _merge_score(anchor, other)
            if score < 78 or not reasons:
                continue
            source, target = _merge_order(anchor, other)
            key = (str(source.id), str(target.id))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                AnchorMergeCandidate(
                    source_anchor=source,
                    target_anchor=target,
                    confidence="high" if score >= 92 else "medium",
                    score=score,
                    reasons=tuple(reasons),
                    metadata=metadata,
                )
            )
    return sorted(
        candidates,
        key=lambda item: (-item.score, item.target_anchor.kind.value, item.target_anchor.label),
    )


def _merge_score(
    anchor: MemoryAnchor,
    other: MemoryAnchor,
) -> tuple[float, list[str], dict[str, object]]:
    anchor_keys = _canonical_anchor_keys(anchor)
    other_keys = _canonical_anchor_keys(other)
    shared = sorted(anchor_keys & other_keys)
    reasons: list[str] = []
    if shared:
        reasons.append("canonical key overlap")
        return 96.0, reasons, {"shared_keys": shared}
    alias_overlap = sorted(
        {
            normalize_anchor_key(value)
            for value in (anchor.label, *anchor.aliases)
            if normalize_anchor_key(value)
        }
        & {
            normalize_anchor_key(value)
            for value in (other.label, *other.aliases)
            if normalize_anchor_key(value)
        }
    )
    if alias_overlap:
        reasons.append("alias overlap")
        return 92.0, reasons, {"shared_aliases": alias_overlap}
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _event_merge_score(anchor, other)
    anchor_key = canonical_anchor_key(anchor.label)
    other_key = canonical_anchor_key(other.label)
    ratio = SequenceMatcher(a=anchor_key, b=other_key).ratio()
    if ratio < _LABEL_SIMILARITY_MERGE_THRESHOLD:
        return 0.0, reasons, {"label_similarity": ratio, "keys": [anchor_key, other_key]}
    reasons.append("label similarity")
    score = round(ratio * 100, 2)
    return score, reasons, {"label_similarity": ratio, "keys": [anchor_key, other_key]}


def _event_merge_score(
    anchor: MemoryAnchor,
    other: MemoryAnchor,
) -> tuple[float, list[str], dict[str, object]]:
    anchor_identity = _event_identity(anchor)
    other_identity = _event_identity(other)
    compatible, conflict_reason = _event_identities_compatible(anchor_identity, other_identity)
    metadata: dict[str, object] = {
        "event_identity": {
            "source": anchor_identity,
            "target": other_identity,
        }
    }
    if not compatible:
        metadata["event_identity_conflict"] = conflict_reason
        return 0.0, [], metadata

    anchor_key = canonical_anchor_key(anchor.label)
    other_key = canonical_anchor_key(other.label)
    ratio = SequenceMatcher(a=anchor_key, b=other_key).ratio()
    metadata.update({"label_similarity": ratio, "keys": [anchor_key, other_key]})
    if ratio < _LABEL_SIMILARITY_MERGE_THRESHOLD:
        return 0.0, [], metadata
    return round(ratio * 100, 2), ["event identity similarity"], metadata


def _event_identity(anchor: MemoryAnchor) -> dict[str, str]:
    metadata = dict(anchor.metadata or {})
    if metadata.get("anchor_family") != "event":
        metadata = structured_anchor_metadata_for_label(anchor.kind, anchor.label)
    event_type = _metadata_text(metadata, "event_type_canonical") or canonical_anchor_key(
        _first_anchor_token(anchor.label)
    )
    participant = _metadata_text(metadata, "event_participant_canonical_key")
    temporal = _event_temporal_identity(metadata)
    return {
        "event_type": event_type,
        "participant": participant,
        "temporal": temporal,
    }


def _event_identities_compatible(
    left: dict[str, str],
    right: dict[str, str],
) -> tuple[bool, str | None]:
    for key in ("event_type", "participant", "temporal"):
        left_value = left.get(key, "")
        right_value = right.get(key, "")
        if left_value != right_value:
            return False, f"{key}_mismatch"
    return bool(left.get("event_type")), None


def _event_temporal_identity(metadata: dict[str, object]) -> str:
    hint = _metadata_text(metadata, "event_temporal_hint_code")
    if not hint:
        return ""
    quantity = metadata.get("event_temporal_quantity")
    unit = _metadata_text(metadata, "event_temporal_unit")
    if isinstance(quantity, int) and unit:
        return f"{hint}:{quantity}:{unit}"
    return hint


def _manual_anchor_metadata(
    *,
    kind: MemoryAnchorKind,
    label: str | None,
    metadata: dict[str, object] | None,
    audit: dict[str, object],
) -> dict[str, object]:
    return {
        **(structured_anchor_metadata_for_label(kind, label) if label else {}),
        **dict(metadata or {}),
        "resolver_version": _ANCHOR_RESOLVER_VERSION,
        **audit,
    }


def _metadata_text(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _first_anchor_token(label: str) -> str:
    return (normalize_anchor_key(label).split() or [""])[0]


def _merge_order(anchor: MemoryAnchor, other: MemoryAnchor) -> tuple[MemoryAnchor, MemoryAnchor]:
    anchor_weight = (len(anchor.aliases), -len(anchor.label), -int(anchor.created_at.timestamp()))
    other_weight = (len(other.aliases), -len(other.label), -int(other.created_at.timestamp()))
    if anchor_weight >= other_weight:
        return other, anchor
    return anchor, other
