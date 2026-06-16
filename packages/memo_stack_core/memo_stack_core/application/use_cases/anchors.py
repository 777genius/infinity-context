"""Semantic anchor lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from memo_stack_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key,
    extract_observed_anchors,
    normalize_anchor_key,
)
from memo_stack_core.application.dto import (
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
from memo_stack_core.domain.entities import (
    LifecycleStatus,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    MemoryScopeId,
    SpaceId,
)
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

_ANCHOR_RESOLVER_VERSION = "anchor-lifecycle-v2"


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
        now = self._clock.now()
        metadata = {
            **dict(command.metadata or {}),
            "resolver_version": _ANCHOR_RESOLVER_VERSION,
            "creation_source": "manual",
            "canonical_key": canonical_anchor_key(label),
        }
        async with self._uow_factory() as uow:
            existing = await uow.anchors.find_active_by_key(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                kind=kind.value,
                normalized_key=normalized_key,
            )
            if existing is not None:
                anchor = await uow.anchors.save(
                    existing.update_details(
                        label=label,
                        aliases=command.aliases,
                        description=command.description,
                        metadata=metadata,
                        now=now,
                    )
                )
            else:
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
            saved = await uow.anchors.save(
                anchor.update_details(
                    normalized_key=normalized_key,
                    label=label,
                    aliases=command.aliases,
                    description=command.description,
                    metadata={
                        **dict(command.metadata or {}),
                        "resolver_version": _ANCHOR_RESOLVER_VERSION,
                        "last_edit_source": "manual",
                    },
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
        now = self._clock.now()
        async with self._uow_factory() as uow:
            anchor = await _get_anchor(uow, command.anchor_id, role="anchor")
            updated_anchor = anchor.remove_alias(alias=alias, reason=reason, now=now)
            normalized_key = normalize_anchor_key(label)
            existing = await uow.anchors.find_active_by_key(
                space_id=str(anchor.space_id),
                memory_scope_id=str(anchor.memory_scope_id),
                kind=anchor.kind.value,
                normalized_key=normalized_key,
            )
            if existing is not None:
                new_anchor = existing.merge_observation(
                    label=label,
                    aliases=(alias,),
                    metadata={
                        "resolver_version": _ANCHOR_RESOLVER_VERSION,
                        "split_from_anchor_id": str(anchor.id),
                        "split_reason": reason,
                        "canonical_key": canonical_anchor_key(label),
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
                    metadata={
                        "resolver_version": _ANCHOR_RESOLVER_VERSION,
                        "split_from_anchor_id": str(anchor.id),
                        "split_reason": reason,
                        "canonical_key": canonical_anchor_key(label),
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
                for item in items:
                    observed = extract_observed_anchors(item.text)
                    observed_count += len(observed)
                    for anchor in observed:
                        saved, was_created = await _upsert_observed_anchor(
                            uow,
                            ids=self._ids,
                            observed=anchor,
                            space_id=command.space_id,
                            memory_scope_id=command.memory_scope_id,
                            source_type=source_type,
                            source_id=item.source_id,
                            now=now,
                        )
                        touched[str(saved.id)] = saved
                        if was_created:
                            created += 1
                        else:
                            updated += 1
                source_summaries.append(
                    AnchorBackfillSourceSummary(
                        source_type=source_type,
                        scanned=len(items),
                        observed=observed_count,
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
) -> tuple[MemoryAnchor, bool]:
    existing = await uow.anchors.find_active_by_key(
        space_id=str(space_id),
        memory_scope_id=str(memory_scope_id),
        kind=observed.kind.value,
        normalized_key=observed.normalized_key,
    )
    metadata = {
        **observed.metadata,
        "last_backfill_source_type": source_type,
        "last_backfill_source_id": source_id,
        "resolver_version": _ANCHOR_RESOLVER_VERSION,
    }
    if existing is not None:
        saved = await uow.anchors.save(
            existing.merge_observation(
                label=observed.label,
                aliases=observed.aliases,
                metadata=metadata,
                now=now,
            )
        )
        return saved, False
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
            metadata=metadata,
            now=now,
        )
    )
    return saved, True


def _rank_merge_candidates(anchors: list[MemoryAnchor]) -> list[AnchorMergeCandidate]:
    candidates: list[AnchorMergeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for index, anchor in enumerate(anchors):
        for other in anchors[index + 1 :]:
            if anchor.kind != other.kind:
                continue
            score, reasons, metadata = _merge_score(anchor, other)
            if score < 78:
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
    anchor_key = canonical_anchor_key(anchor.label)
    other_key = canonical_anchor_key(other.label)
    ratio = SequenceMatcher(a=anchor_key, b=other_key).ratio()
    if ratio >= 0.78:
        reasons.append("label similarity")
    score = round(ratio * 100, 2)
    return score, reasons, {"label_similarity": ratio, "keys": [anchor_key, other_key]}


def _canonical_anchor_keys(anchor: MemoryAnchor) -> set[str]:
    keys = {
        canonical_anchor_key(anchor.normalized_key),
        canonical_anchor_key(anchor.label),
    }
    keys.update(canonical_anchor_key(alias) for alias in anchor.aliases)
    metadata_key = anchor.metadata.get("canonical_key")
    if isinstance(metadata_key, str):
        keys.add(metadata_key)
    return {key for key in keys if key}


def _merge_order(anchor: MemoryAnchor, other: MemoryAnchor) -> tuple[MemoryAnchor, MemoryAnchor]:
    anchor_weight = (len(anchor.aliases), -len(anchor.label), -int(anchor.created_at.timestamp()))
    other_weight = (len(other.aliases), -len(other.label), -int(other.created_at.timestamp()))
    if anchor_weight >= other_weight:
        return other, anchor
    return anchor, other
