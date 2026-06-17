"""Build read-only memory management insights for a scope."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from memo_stack_core.application.dto import (
    BuildMemoryInsightsQuery,
    MemoryActivityItem,
    MemoryConsolidationPlanItem,
    MemoryInsightActionItem,
    MemoryInsightsResult,
)
from memo_stack_core.application.sensitive_text import redact_sensitive_text
from memo_stack_core.domain.capture import CanonicalCapture, ConsolidationStatus
from memo_stack_core.domain.entities import (
    FactStatus,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryScopeId,
    MemorySuggestion,
)
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_FACT_STATUSES = ("active", "superseded", "disputed", "deleted")
_SUGGESTION_STATUSES = ("pending", "approved", "rejected", "expired")
_CAPTURE_CONSOLIDATION_STATUSES = (
    "pending",
    "running",
    "retry_pending",
    "dead",
    "skipped",
    "consolidated",
    "not_required",
)
_CAPTURE_ATTENTION_STATUSES = {
    ConsolidationStatus.PENDING.value,
    ConsolidationStatus.RETRY_PENDING.value,
    ConsolidationStatus.DEAD.value,
}


@dataclass(frozen=True)
class _MemoryScopeSample:
    memory_scope_id: str
    facts: tuple[MemoryFact, ...]
    documents: tuple[MemoryDocument, ...]
    episodes: tuple[MemoryEpisode, ...]
    document_chunk_counts: dict[str, int]
    episode_chunk_counts: dict[str, int]
    suggestions: tuple[MemorySuggestion, ...]
    captures: tuple[CanonicalCapture, ...]
    capture_status_counts: dict[str, int]


class BuildMemoryInsightsUseCase:
    """Summarize memory quality and maintenance needs without mutating state."""

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

    async def execute(self, query: BuildMemoryInsightsQuery) -> MemoryInsightsResult:
        now = self._clock.now()
        samples = await self._load_samples(query)
        metrics = _metrics(samples=samples, now=now)
        taxonomy = _taxonomy(samples)
        action_items = _action_items(samples=samples, now=now)
        recent_activity = _recent_activity(samples, limit=query.max_activity)
        consolidation_plan = _consolidation_plan(action_items)
        return MemoryInsightsResult(
            insights_id=self._ids.new_id("ins"),
            generated_at=now,
            scope={
                "space_id": str(query.space_id),
                "memory_scope_ids": [
                    str(memory_scope_id) for memory_scope_id in query.memory_scope_ids
                ],
                "thread_id": str(query.thread_id) if query.thread_id else None,
            },
            health_score=_health_score(metrics),
            metrics=metrics,
            taxonomy=taxonomy,
            action_items=tuple(action_items[:50]),
            recent_activity=tuple(recent_activity),
            consolidation_plan=tuple(consolidation_plan),
            diagnostics={
                "evidence_only": True,
                "read_only": True,
                "sample_limited": True,
                "max_facts_per_memory_scope": query.max_facts,
                "max_documents_per_memory_scope": query.max_documents,
                "max_episodes_per_memory_scope": query.max_episodes,
                "max_suggestions_per_memory_scope": query.max_suggestions,
                "max_captures_per_memory_scope": query.max_captures,
                "max_activity": query.max_activity,
                "memory_scopes_sampled": len(samples),
            },
        )

    async def _load_samples(
        self,
        query: BuildMemoryInsightsQuery,
    ) -> tuple[_MemoryScopeSample, ...]:
        samples: list[_MemoryScopeSample] = []
        async with self._uow_factory() as uow:
            for memory_scope_id in query.memory_scope_ids:
                facts = await self._load_facts(query, memory_scope_id=memory_scope_id, uow=uow)
                documents = tuple(
                    await uow.documents.list_for_scope(
                        space_id=str(query.space_id),
                        memory_scope_id=str(memory_scope_id),
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        status=None,
                        limit=query.max_documents,
                    )
                )
                episodes = tuple(
                    await uow.episodes.list_for_scope(
                        space_id=str(query.space_id),
                        memory_scope_id=str(memory_scope_id),
                        thread_id=str(query.thread_id) if query.thread_id else None,
                        status=None,
                        limit=query.max_episodes,
                    )
                )
                document_chunk_counts: dict[str, int] = {}
                for document in documents:
                    chunks = await uow.documents.list_chunks(str(document.id), limit=501)
                    document_chunk_counts[str(document.id)] = min(len(chunks), 500)
                episode_chunk_counts: dict[str, int] = {}
                for episode in episodes:
                    chunks = await uow.chunks.list_for_episode(str(episode.id), limit=501)
                    episode_chunk_counts[str(episode.id)] = min(len(chunks), 500)
                suggestions = await self._load_suggestions(
                    query, memory_scope_id=memory_scope_id, uow=uow
                )
                captures, capture_counts = await self._load_captures(
                    query,
                    memory_scope_id=memory_scope_id,
                    uow=uow,
                )
                samples.append(
                    _MemoryScopeSample(
                        memory_scope_id=str(memory_scope_id),
                        facts=tuple(facts),
                        documents=documents,
                        episodes=episodes,
                        document_chunk_counts=document_chunk_counts,
                        episode_chunk_counts=episode_chunk_counts,
                        suggestions=tuple(suggestions),
                        captures=captures,
                        capture_status_counts=capture_counts,
                    )
                )
        return tuple(samples)

    async def _load_facts(
        self,
        query: BuildMemoryInsightsQuery,
        *,
        memory_scope_id: MemoryScopeId,
        uow: object,
    ) -> tuple[MemoryFact, ...]:
        facts: list[MemoryFact] = []
        for status in _FACT_STATUSES:
            facts.extend(
                await uow.facts.list_for_scope(
                    space_id=str(query.space_id),
                    memory_scope_id=str(memory_scope_id),
                    thread_id=str(query.thread_id) if query.thread_id else None,
                    status=status,
                    limit=query.max_facts,
                )
            )
        status_none_facts = await uow.facts.list_for_scope(
            space_id=str(query.space_id),
            memory_scope_id=str(memory_scope_id),
            thread_id=str(query.thread_id) if query.thread_id else None,
            status=None,
            limit=query.max_facts,
        )
        return _dedupe_facts((*facts, *status_none_facts))

    async def _load_suggestions(
        self,
        query: BuildMemoryInsightsQuery,
        *,
        memory_scope_id: MemoryScopeId,
        uow: object,
    ) -> tuple[MemorySuggestion, ...]:
        suggestions: list[MemorySuggestion] = []
        for status in _SUGGESTION_STATUSES:
            suggestions.extend(
                await uow.suggestions.list_for_scope(
                    space_id=str(query.space_id),
                    memory_scope_id=str(memory_scope_id),
                    status=status,
                    operation=None,
                    category=None,
                    tag=None,
                    limit=query.max_suggestions,
                )
            )
        return _dedupe_suggestions(tuple(suggestions))

    async def _load_captures(
        self,
        query: BuildMemoryInsightsQuery,
        *,
        memory_scope_id: MemoryScopeId,
        uow: object,
    ) -> tuple[tuple[CanonicalCapture, ...], dict[str, int]]:
        counts: dict[str, int] = {}
        captures: list[CanonicalCapture] = []
        for consolidation_status in _CAPTURE_CONSOLIDATION_STATUSES:
            status_captures = await uow.captures.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(memory_scope_id),
                status=None,
                consolidation_status=consolidation_status,
                limit=query.max_captures,
            )
            counts[consolidation_status] = len(status_captures)
            captures.extend(status_captures)
        return _dedupe_captures(tuple(captures)), counts


def _metrics(*, samples: tuple[_MemoryScopeSample, ...], now: datetime) -> dict[str, object]:
    fact_status_counts: Counter[str] = Counter()
    suggestion_status_counts: Counter[str] = Counter()
    suggestion_operation_counts: Counter[str] = Counter()
    capture_status_counts: Counter[str] = Counter()
    episode_status_counts: Counter[str] = Counter()
    active_facts = 0
    expired_active_facts = 0
    uncategorized_active_facts = 0
    untagged_active_facts = 0
    active_documents = 0
    documents_without_chunks = 0
    total_document_chunks = 0
    active_episodes = 0
    episodes_without_chunks = 0
    total_episode_chunks = 0

    for sample in samples:
        for fact in sample.facts:
            fact_status_counts[fact.status.value] += 1
            if fact.status == FactStatus.ACTIVE:
                active_facts += 1
                if _is_expired(fact.expires_at, now):
                    expired_active_facts += 1
                if not fact.category:
                    uncategorized_active_facts += 1
                if not fact.tags:
                    untagged_active_facts += 1
        for document in sample.documents:
            if document.status.value == "active":
                active_documents += 1
                chunk_count = sample.document_chunk_counts.get(str(document.id), 0)
                total_document_chunks += chunk_count
                if chunk_count == 0:
                    documents_without_chunks += 1
        for episode in sample.episodes:
            episode_status_counts[episode.status.value] += 1
            if episode.status.value == "active":
                active_episodes += 1
                chunk_count = sample.episode_chunk_counts.get(str(episode.id), 0)
                total_episode_chunks += chunk_count
                if chunk_count == 0:
                    episodes_without_chunks += 1
        for suggestion in sample.suggestions:
            suggestion_status_counts[suggestion.status.value] += 1
            suggestion_operation_counts[suggestion.operation.value] += 1
        capture_status_counts.update(sample.capture_status_counts)

    attention_captures = sum(
        count
        for status, count in capture_status_counts.items()
        if status in _CAPTURE_ATTENTION_STATUSES
    )
    return {
        "memory_scopes": len(samples),
        "facts": {
            "total_sampled": sum(fact_status_counts.values()),
            "active": active_facts,
            "expired_active": expired_active_facts,
            "uncategorized_active": uncategorized_active_facts,
            "untagged_active": untagged_active_facts,
            "by_status": dict(sorted(fact_status_counts.items())),
        },
        "documents": {
            "active": active_documents,
            "chunks_sampled": total_document_chunks,
            "without_chunks": documents_without_chunks,
        },
        "episodes": {
            "active": active_episodes,
            "chunks_sampled": total_episode_chunks,
            "without_chunks": episodes_without_chunks,
            "by_status": dict(sorted(episode_status_counts.items())),
        },
        "chunks": {
            "sampled": total_document_chunks + total_episode_chunks,
            "document_chunks_sampled": total_document_chunks,
            "episode_chunks_sampled": total_episode_chunks,
        },
        "suggestions": {
            "total_sampled": sum(suggestion_status_counts.values()),
            "pending": suggestion_status_counts.get("pending", 0),
            "by_status": dict(sorted(suggestion_status_counts.items())),
            "by_operation": dict(sorted(suggestion_operation_counts.items())),
        },
        "captures": {
            "attention_needed": attention_captures,
            "by_consolidation_status": dict(sorted(capture_status_counts.items())),
        },
    }


def _taxonomy(samples: tuple[_MemoryScopeSample, ...]) -> dict[str, object]:
    categories: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    ttl_policies: Counter[str] = Counter()
    for sample in samples:
        for fact in sample.facts:
            if fact.status != FactStatus.ACTIVE:
                continue
            categories[fact.category or "uncategorized"] += 1
            tags.update(fact.tags)
            if fact.ttl_policy:
                ttl_policies[fact.ttl_policy] += 1
    return {
        "top_categories": _top_counts(categories),
        "top_tags": _top_counts(tags),
        "ttl_policies": _top_counts(ttl_policies),
    }


def _action_items(
    *,
    samples: tuple[_MemoryScopeSample, ...],
    now: datetime,
) -> list[MemoryInsightActionItem]:
    items: list[MemoryInsightActionItem] = []
    for sample in samples:
        pending_suggestions = [
            suggestion for suggestion in sample.suggestions if suggestion.status.value == "pending"
        ]
        if pending_suggestions:
            items.append(
                _item(
                    severity="warning",
                    action="review_pending_suggestions",
                    target_type="suggestion_queue",
                    target_id=None,
                    memory_scope_id=sample.memory_scope_id,
                    reason=f"{len(pending_suggestions)} pending suggestions need review.",
                    metadata={"pending_count": len(pending_suggestions)},
                )
            )
        for suggestion in pending_suggestions[:10]:
            items.append(
                _item(
                    severity="info",
                    action="review_suggestion",
                    target_type="suggestion",
                    target_id=str(suggestion.id),
                    memory_scope_id=sample.memory_scope_id,
                    reason=f"Pending {suggestion.operation.value} suggestion.",
                    preview=_preview(suggestion.candidate_text),
                    metadata={
                        "operation": suggestion.operation.value,
                        "category": suggestion.category,
                        "tags": list(suggestion.tags),
                    },
                )
            )
        items.extend(_fact_consolidation_actions(sample=sample, now=now))
        expired = [
            fact
            for fact in sample.facts
            if fact.status == FactStatus.ACTIVE and _is_expired(fact.expires_at, now)
        ]
        for fact in expired[:10]:
            items.append(
                _item(
                    severity="warning",
                    action="review_expired_fact",
                    target_type="fact",
                    target_id=str(fact.id),
                    memory_scope_id=sample.memory_scope_id,
                    reason="Active fact has expired and is hidden from active recall.",
                    preview=_preview(fact.text),
                    metadata={
                        "ttl_policy": fact.ttl_policy,
                        "expires_at": fact.expires_at.isoformat() if fact.expires_at else None,
                    },
                )
            )
        uncategorized = [
            fact for fact in sample.facts if fact.status == FactStatus.ACTIVE and not fact.category
        ]
        if len(uncategorized) >= 5:
            items.append(
                _item(
                    severity="info",
                    action="backfill_fact_taxonomy",
                    target_type="fact_set",
                    target_id=None,
                    memory_scope_id=sample.memory_scope_id,
                    reason=f"{len(uncategorized)} active facts have no category.",
                    metadata={"uncategorized_active_count": len(uncategorized)},
                )
            )
        for document in sample.documents:
            if (
                document.status.value == "active"
                and sample.document_chunk_counts.get(str(document.id), 0) == 0
            ):
                items.append(
                    _item(
                        severity="warning",
                        action="process_document",
                        target_type="document",
                        target_id=str(document.id),
                        memory_scope_id=sample.memory_scope_id,
                        reason="Active document has no indexed chunks.",
                        preview=_preview(document.title),
                    )
                )
        for episode in sample.episodes:
            if (
                episode.status.value == "active"
                and sample.episode_chunk_counts.get(str(episode.id), 0) == 0
            ):
                items.append(
                    _item(
                        severity="warning",
                        action="process_episode",
                        target_type="episode",
                        target_id=str(episode.id),
                        memory_scope_id=sample.memory_scope_id,
                        reason="Active episode has no indexed transcript chunks.",
                        preview=_preview(episode.text),
                        metadata={
                            "source_type": episode.source_type,
                            "source_external_id": episode.source_external_id,
                        },
                    )
                )
        dead_captures = sample.capture_status_counts.get(ConsolidationStatus.DEAD.value, 0)
        if dead_captures:
            items.append(
                _item(
                    severity="critical",
                    action="inspect_dead_captures",
                    target_type="capture_queue",
                    target_id=None,
                    memory_scope_id=sample.memory_scope_id,
                    reason=f"{dead_captures} capture consolidations are dead.",
                    metadata={"dead_capture_count": dead_captures},
                )
            )
    return sorted(items, key=_action_sort_key)


def _fact_consolidation_actions(
    *,
    sample: _MemoryScopeSample,
    now: datetime,
) -> list[MemoryInsightActionItem]:
    active_facts = [
        fact
        for fact in sample.facts
        if fact.status == FactStatus.ACTIVE and not _is_expired(fact.expires_at, now)
    ]
    items = _exact_duplicate_fact_actions(sample.memory_scope_id, active_facts)
    items.extend(_similar_fact_actions(sample.memory_scope_id, active_facts))
    return items[:10]


def _exact_duplicate_fact_actions(
    memory_scope_id: str,
    facts: list[MemoryFact],
) -> list[MemoryInsightActionItem]:
    by_key: dict[str, list[MemoryFact]] = {}
    for fact in facts:
        key = _fact_normalized_text(fact.text)
        if key:
            by_key.setdefault(key, []).append(fact)

    items: list[MemoryInsightActionItem] = []
    for duplicates in by_key.values():
        if len(duplicates) < 2:
            continue
        ordered = sorted(duplicates, key=lambda fact: (fact.updated_at, str(fact.id)), reverse=True)
        primary = ordered[0]
        duplicate_ids = [str(fact.id) for fact in ordered[1:]]
        items.append(
            _item(
                severity="warning",
                action="review_duplicate_facts",
                target_type="fact_set",
                target_id=str(primary.id),
                memory_scope_id=memory_scope_id,
                reason=f"{len(ordered)} active facts have equivalent text.",
                preview=_preview(primary.text),
                metadata={
                    "match_type": "exact_normalized_text",
                    "canonical_candidate_id": str(primary.id),
                    "duplicate_fact_ids": duplicate_ids[:10],
                    "duplicate_count": len(duplicate_ids),
                },
            )
        )
    return sorted(items, key=lambda item: (item.memory_scope_id, item.target_id or item.id))[:5]


def _similar_fact_actions(
    memory_scope_id: str,
    facts: list[MemoryFact],
) -> list[MemoryInsightActionItem]:
    candidates: list[tuple[float, MemoryFact, MemoryFact]] = []
    token_cache = {str(fact.id): _fact_terms(fact.text) for fact in facts}
    for index, left in enumerate(facts):
        left_terms = token_cache[str(left.id)]
        if len(left_terms) < 5:
            continue
        for right in facts[index + 1 :]:
            if left.kind != right.kind or left.category != right.category:
                continue
            right_terms = token_cache[str(right.id)]
            if len(right_terms) < 5:
                continue
            similarity = _jaccard(left_terms, right_terms)
            if 0.82 <= similarity < 1.0 and len(set(left_terms) & set(right_terms)) >= 5:
                candidates.append((similarity, left, right))

    items: list[MemoryInsightActionItem] = []
    seen: set[frozenset[str]] = set()
    for similarity, left, right in sorted(candidates, key=lambda item: item[0], reverse=True):
        pair_key = frozenset((str(left.id), str(right.id)))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        newest, older = sorted(
            (left, right),
            key=lambda fact: (fact.updated_at, str(fact.id)),
        )[::-1]
        items.append(
            _item(
                severity="info",
                action="review_similar_facts",
                target_type="fact_set",
                target_id=str(newest.id),
                memory_scope_id=memory_scope_id,
                reason="Two active facts look similar enough to review for consolidation.",
                preview=_preview(newest.text),
                metadata={
                    "match_type": "same_kind_category_token_overlap",
                    "canonical_candidate_id": str(newest.id),
                    "similar_fact_ids": [str(older.id)],
                    "similarity": round(similarity, 3),
                    "kind": newest.kind.value,
                    "category": newest.category,
                },
            )
        )
        if len(items) >= 5:
            break
    return items


def _recent_activity(
    samples: tuple[_MemoryScopeSample, ...],
    *,
    limit: int,
) -> list[MemoryActivityItem]:
    if limit <= 0:
        return []
    items: list[MemoryActivityItem] = []
    for sample in samples:
        for fact in sample.facts:
            event_type = "fact_created"
            if fact.status == FactStatus.DELETED:
                event_type = "fact_deleted"
            elif fact.version > 1:
                event_type = "fact_updated"
            items.append(
                _activity_item(
                    occurred_at=fact.updated_at,
                    event_type=event_type,
                    entity_type="fact",
                    entity_id=str(fact.id),
                    memory_scope_id=sample.memory_scope_id,
                    thread_id=str(fact.thread_id) if fact.thread_id else None,
                    status=fact.status.value,
                    preview=_preview(fact.text),
                    metadata={
                        "version": fact.version,
                        "kind": fact.kind.value,
                        "category": fact.category,
                        "tags": list(fact.tags),
                    },
                )
            )
        for suggestion in sample.suggestions:
            event_type = (
                "suggestion_created"
                if suggestion.status.value == "pending"
                else "suggestion_reviewed"
            )
            items.append(
                _activity_item(
                    occurred_at=suggestion.updated_at,
                    event_type=event_type,
                    entity_type="suggestion",
                    entity_id=str(suggestion.id),
                    memory_scope_id=sample.memory_scope_id,
                    thread_id=None,
                    status=suggestion.status.value,
                    preview=_preview(suggestion.candidate_text),
                    metadata={
                        "operation": suggestion.operation.value,
                        "target_fact_id": str(suggestion.target_fact_id)
                        if suggestion.target_fact_id
                        else None,
                        "reviewed_at": suggestion.reviewed_at.isoformat()
                        if suggestion.reviewed_at
                        else None,
                    },
                )
            )
        for document in sample.documents:
            event_type = (
                "document_deleted" if document.status.value == "deleted" else "document_ingested"
            )
            items.append(
                _activity_item(
                    occurred_at=document.updated_at,
                    event_type=event_type,
                    entity_type="document",
                    entity_id=str(document.id),
                    memory_scope_id=sample.memory_scope_id,
                    thread_id=str(document.thread_id) if document.thread_id else None,
                    status=document.status.value,
                    preview=_preview(document.title),
                    metadata={
                        "source_type": document.source_type,
                        "classification": document.classification,
                    },
                )
            )
        for episode in sample.episodes:
            event_type = (
                "episode_deleted" if episode.status.value == "deleted" else "episode_ingested"
            )
            items.append(
                _activity_item(
                    occurred_at=episode.created_at,
                    event_type=event_type,
                    entity_type="episode",
                    entity_id=str(episode.id),
                    memory_scope_id=sample.memory_scope_id,
                    thread_id=str(episode.thread_id),
                    status=episode.status.value,
                    preview=_preview(episode.text),
                    metadata={
                        "source_type": episode.source_type,
                        "source_external_id": episode.source_external_id,
                        "speaker": episode.speaker.value,
                        "trust_level": episode.trust_level.value,
                        "occurred_at": episode.occurred_at.isoformat(),
                    },
                )
            )
        for capture in sample.captures:
            event_type = _capture_activity_type(capture)
            items.append(
                _activity_item(
                    occurred_at=capture.updated_at,
                    event_type=event_type,
                    entity_type="capture",
                    entity_id=str(capture.id),
                    memory_scope_id=sample.memory_scope_id,
                    thread_id=str(capture.thread_id) if capture.thread_id else None,
                    status=capture.consolidation_status.value,
                    preview=_preview(capture.text),
                    metadata={
                        "source_agent": capture.source_agent,
                        "source_kind": capture.source_kind.value,
                        "event_type": capture.event_type,
                    },
                )
            )
    return sorted(items, key=_activity_sort_key, reverse=True)[:limit]


def _consolidation_plan(
    action_items: list[MemoryInsightActionItem],
) -> list[MemoryConsolidationPlanItem]:
    items: list[MemoryConsolidationPlanItem] = []
    for action in action_items:
        if action.action == "review_duplicate_facts":
            metadata = action.metadata or {}
            candidate_ids = _metadata_ids(metadata, "duplicate_fact_ids")
            items.append(
                _plan_item(
                    plan_type="exact_duplicate_fact_review",
                    memory_scope_id=action.memory_scope_id,
                    confidence="high",
                    canonical_candidate_id=_metadata_string(
                        metadata,
                        "canonical_candidate_id",
                        fallback=action.target_id,
                    ),
                    candidate_fact_ids=tuple(candidate_ids),
                    recommended_steps=(
                        "Inspect every listed fact and source ref.",
                        "Link confirmed duplicates with relation_type=duplicates.",
                        "Update or forget redundant facts only after explicit confirmation.",
                    ),
                    reason=action.reason,
                    preview=action.preview,
                    metadata=metadata,
                )
            )
        elif action.action == "review_similar_facts":
            metadata = action.metadata or {}
            candidate_ids = _metadata_ids(metadata, "similar_fact_ids")
            items.append(
                _plan_item(
                    plan_type="similar_fact_review",
                    memory_scope_id=action.memory_scope_id,
                    confidence="medium",
                    canonical_candidate_id=_metadata_string(
                        metadata,
                        "canonical_candidate_id",
                        fallback=action.target_id,
                    ),
                    candidate_fact_ids=tuple(candidate_ids),
                    recommended_steps=(
                        "Inspect both facts and source refs.",
                        "If they are equivalent, link them with relation_type=duplicates.",
                        "If they conflict, link them with relation_type=contradicts.",
                        "Do not merge automatically from this read-only plan.",
                    ),
                    reason=action.reason,
                    preview=action.preview,
                    metadata=metadata,
                )
            )
    return items[:10]


def _health_score(metrics: dict[str, object]) -> float:
    facts = metrics["facts"]
    documents = metrics["documents"]
    episodes = metrics["episodes"]
    suggestions = metrics["suggestions"]
    captures = metrics["captures"]
    penalty = 0.0
    penalty += min(25.0, float(suggestions["pending"]) * 1.2)
    penalty += min(20.0, float(facts["expired_active"]) * 2.0)
    penalty += min(15.0, float(captures["attention_needed"]) * 1.5)
    penalty += min(12.0, float(documents["without_chunks"]) * 2.0)
    penalty += min(8.0, float(episodes["without_chunks"]) * 2.0)
    if facts["active"]:
        uncategorized_ratio = float(facts["uncategorized_active"]) / float(facts["active"])
        penalty += min(10.0, uncategorized_ratio * 10.0)
    return round(max(0.0, 100.0 - penalty), 2)


def _item(
    *,
    severity: str,
    action: str,
    target_type: str,
    target_id: str | None,
    memory_scope_id: str,
    reason: str,
    preview: str | None = None,
    metadata: dict[str, object] | None = None,
) -> MemoryInsightActionItem:
    stable = "|".join((severity, action, target_type, str(target_id), memory_scope_id, reason))
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return MemoryInsightActionItem(
        id=f"mai_{digest}",
        severity=severity,
        action=action,
        target_type=target_type,
        target_id=target_id,
        memory_scope_id=memory_scope_id,
        reason=reason,
        preview=preview,
        metadata=metadata or {},
    )


def _activity_item(
    *,
    occurred_at: datetime,
    event_type: str,
    entity_type: str,
    entity_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    status: str,
    preview: str | None,
    metadata: dict[str, object],
) -> MemoryActivityItem:
    stable = "|".join(
        (event_type, entity_type, entity_id, memory_scope_id, occurred_at.isoformat())
    )
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return MemoryActivityItem(
        id=f"act_{digest}",
        occurred_at=occurred_at,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        status=status,
        preview=preview,
        metadata=metadata,
    )


def _plan_item(
    *,
    plan_type: str,
    memory_scope_id: str,
    confidence: str,
    canonical_candidate_id: str,
    candidate_fact_ids: tuple[str, ...],
    recommended_steps: tuple[str, ...],
    reason: str,
    preview: str | None,
    metadata: dict[str, object],
) -> MemoryConsolidationPlanItem:
    stable = "|".join(
        (plan_type, memory_scope_id, canonical_candidate_id, ",".join(candidate_fact_ids), reason)
    )
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
    return MemoryConsolidationPlanItem(
        id=f"mplan_{digest}",
        plan_type=plan_type,
        memory_scope_id=memory_scope_id,
        confidence=confidence,
        canonical_candidate_id=canonical_candidate_id,
        candidate_fact_ids=candidate_fact_ids,
        recommended_steps=recommended_steps,
        reason=reason,
        preview=preview,
        metadata=metadata,
    )


def _action_sort_key(item: MemoryInsightActionItem) -> tuple[int, str, str]:
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    return (
        severity_rank.get(item.severity, 3),
        item.memory_scope_id,
        item.target_id or item.action,
    )


def _activity_sort_key(item: MemoryActivityItem) -> tuple[datetime, str]:
    return (item.occurred_at, item.id)


def _dedupe_facts(facts: tuple[MemoryFact, ...]) -> tuple[MemoryFact, ...]:
    by_id: dict[str, MemoryFact] = {}
    for fact in facts:
        by_id[str(fact.id)] = fact
    return tuple(by_id.values())


def _dedupe_suggestions(
    suggestions: tuple[MemorySuggestion, ...],
) -> tuple[MemorySuggestion, ...]:
    by_id: dict[str, MemorySuggestion] = {}
    for suggestion in suggestions:
        by_id[str(suggestion.id)] = suggestion
    return tuple(by_id.values())


def _dedupe_captures(captures: tuple[CanonicalCapture, ...]) -> tuple[CanonicalCapture, ...]:
    by_id: dict[str, CanonicalCapture] = {}
    for capture in captures:
        by_id[str(capture.id)] = capture
    return tuple(by_id.values())


def _is_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    safe_expires_at = expires_at
    safe_now = now
    if safe_expires_at.tzinfo is None:
        safe_expires_at = safe_expires_at.replace(tzinfo=UTC)
    if safe_now.tzinfo is None:
        safe_now = safe_now.replace(tzinfo=UTC)
    return safe_expires_at <= safe_now


def _preview(value: str, *, max_chars: int = 240) -> str:
    redacted = redact_sensitive_text(value, marker="[redacted]")
    return redacted if len(redacted) <= max_chars else redacted[:max_chars] + "...[truncated]"


def _fact_normalized_text(value: str) -> str:
    return " ".join(_fact_terms(value))


def _fact_terms(value: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for raw_token in value.casefold().replace("-", " ").split():
        token = raw_token.strip(".,:;!?()[]{}\"'`")
        if len(token) < 3 or token in {"the", "and", "for", "with", "that", "this"}:
            continue
        tokens.append(token)
    return tuple(tokens)


def _jaccard(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _metadata_string(
    metadata: dict[str, object],
    key: str,
    *,
    fallback: str | None,
) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback or ""


def _metadata_ids(metadata: dict[str, object], key: str) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _top_counts(counter: Counter[str], *, limit: int = 20) -> list[dict[str, object]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def _capture_activity_type(capture: CanonicalCapture) -> str:
    if capture.consolidation_status == ConsolidationStatus.DEAD:
        return "capture_dead"
    if capture.consolidation_status == ConsolidationStatus.CONSOLIDATED:
        return "capture_consolidated"
    if capture.consolidation_status == ConsolidationStatus.RETRY_PENDING:
        return "capture_retry_pending"
    return "capture_received"
