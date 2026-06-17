"""Context-link suggestion resolver use case."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import log

from memo_stack_core.application.anchor_extraction import extract_observed_anchors
from memo_stack_core.application.dto import (
    ContextLinkCandidate,
    ContextLinkSuggestionsResult,
    SuggestContextLinksCommand,
)
from memo_stack_core.application.use_cases.context_link_visibility import (
    assert_context_link_endpoint_visible,
)
from memo_stack_core.domain.assets import (
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from memo_stack_core.domain.entities import MemoryAnchor, MemoryAnchorId, MemoryChunk
from memo_stack_core.domain.errors import MemoryValidationError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_MAX_CANDIDATE_PREVIEW = 220
_LINK_STOP_TERMS = {
    "about",
    "after",
    "again",
    "ago",
    "and",
    "days",
    "from",
    "hour",
    "hours",
    "last",
    "note",
    "screenshot",
    "that",
    "the",
    "this",
    "today",
    "with",
    "week",
    "weeks",
    "what",
    "when",
    "where",
    "which",
    "yesterday",
    "вчера",
    "день",
    "дней",
    "дня",
    "когда",
    "назад",
    "неделю",
    "недели",
    "неделе",
    "прошлой",
    "прошлую",
    "про",
    "скриншот",
    "сегодня",
    "что",
    "час",
    "часа",
    "часов",
}
_NUMERIC_TEMPORAL_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, int], ...] = (
    (
        "hours",
        re.compile(
            r"\b(?:(?:about|around)\s+)?(?P<count>\d{1,3})\s+hours?\s+ago\b",
            re.IGNORECASE,
        ),
        1.0,
        24 * 14,
    ),
    (
        "hours",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,3})\s+час(?:а|ов)?\s+назад\b",
            re.IGNORECASE,
        ),
        1.0,
        24 * 14,
    ),
    (
        "days",
        re.compile(
            r"\b(?:(?:about|around)\s+)?(?P<count>\d{1,3})\s+days?\s+ago\b",
            re.IGNORECASE,
        ),
        24.0,
        365,
    ),
    (
        "days",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,3})\s+д(?:ень|ня|ней)\s+назад\b",
            re.IGNORECASE,
        ),
        24.0,
        365,
    ),
    (
        "weeks",
        re.compile(
            r"\b(?:(?:about|around)\s+)?(?P<count>\d{1,2})\s+weeks?\s+ago\b",
            re.IGNORECASE,
        ),
        24.0 * 7,
        52,
    ),
    (
        "weeks",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,2})\s+недел[юи]\s+назад\b",
            re.IGNORECASE,
        ),
        24.0 * 7,
        52,
    ),
)
_TEMPORAL_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, float], ...] = (
    (
        "hour_ago",
        re.compile(
            r"\b(?:an?\s+hour\s+ago|1\s+hour\s+ago|last\s+hour|"
            r"(?<!\d\s)(?:около\s+)?час(?:а|ов)?\s+назад)\b",
            re.IGNORECASE,
        ),
        0.0,
        2.5,
    ),
    (
        "today",
        re.compile(r"\b(?:today|сегодня)\b", re.IGNORECASE),
        0.0,
        30.0,
    ),
    (
        "yesterday",
        re.compile(r"\b(?:yesterday|вчера)\b", re.IGNORECASE),
        18.0,
        54.0,
    ),
    (
        "last_week",
        re.compile(
            r"\b(?:last\s+week|(?:a\s+)?week\s+ago|1\s+week\s+ago|"
            r"на\s+прошлой\s+неделе|прошл(?:ой|ую)\s+недел[юе]|"
            r"недел[юи]\s+назад)\b",
            re.IGNORECASE,
        ),
        24.0,
        24.0 * 10,
    ),
)


@dataclass(frozen=True)
class _TemporalHint:
    code: str
    min_hours: float
    max_hours: float


class SuggestContextLinksUseCase:
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

    async def execute(self, command: SuggestContextLinksCommand) -> ContextLinkSuggestionsResult:
        query_text = command.text.strip()
        diagnostics: dict[str, object] = {
            "resolver_version": "context-link-rule-v1",
            "source_type": command.source_type,
            "source_id": command.source_id,
        }
        if command.persist and (not command.source_type or not command.source_id):
            raise MemoryValidationError(
                "Persisted context link suggestions require source_type and source_id"
            )
        async with self._uow_factory() as uow:
            source_thread_id = str(command.thread_id) if command.thread_id else None
            if command.source_type == "capture" and command.source_id:
                capture = await uow.captures.get_by_id(command.source_id)
                if capture is not None and _same_scope(capture, command):
                    query_text = _join_text(query_text, capture.text)
                    if capture.thread_id:
                        source_thread_id = str(capture.thread_id)
            if command.source_type == "episode" and command.source_id:
                episode = await uow.episodes.get_by_id(command.source_id)
                if episode is not None and _same_scope(episode, command):
                    query_text = _join_text(query_text, episode.text)
                    source_thread_id = str(episode.thread_id)
            facts = await uow.facts.find_active(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=None,
                query=query_text,
                limit=max(command.limit * 3, 12),
            )
            recent_facts = await uow.facts.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(command.limit, 8),
            )
            episodes = await uow.episodes.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(command.limit, 8),
            )
            captures = await uow.captures.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="accepted",
                consolidation_status=None,
                limit=max(command.limit, 8),
            )
            suggestions = await uow.suggestions.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="pending",
                operation=None,
                category=None,
                tag=None,
                limit=max(command.limit, 8),
            )
            assets = await uow.assets.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="stored",
                limit=max(command.limit, 8),
            )
            documents = await uow.documents.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(command.limit, 8),
            )
            chunks = await uow.chunks.keyword_search(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=None,
                query=query_text,
                limit=max(command.limit * 2, 12),
            )
            threads = await uow.scope.list_threads(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="active",
                limit=max(command.limit, 8),
            )
            anchors = await uow.anchors.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                kind=None,
                status="active",
                limit=max(command.limit * 3, 24),
            )
            if command.persist:
                observed_anchors = await self._upsert_observed_anchors(
                    uow,
                    command=command,
                    text=query_text,
                )
                anchors_by_id = {str(anchor.id): anchor for anchor in anchors}
                for anchor in observed_anchors:
                    anchors_by_id[str(anchor.id)] = anchor
                anchors = list(anchors_by_id.values())
                await uow.commit()

        terms = _terms(query_text)
        temporal_hints = _temporal_hints(query_text)
        now = self._clock.now()
        if temporal_hints:
            diagnostics["temporal_hints"] = [hint.code for hint in temporal_hints]
        observed_by_key = {
            (anchor.kind.value, anchor.normalized_key): anchor
            for anchor in extract_observed_anchors(query_text)
        }
        candidates: list[ContextLinkCandidate] = []
        seen: set[tuple[str, str]] = set()
        for anchor in anchors:
            key = ("anchor", str(anchor.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            target_text = " ".join(
                part
                for part in (
                    anchor.kind.value,
                    anchor.label,
                    " ".join(anchor.aliases),
                    anchor.description or "",
                )
                if part
            )
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=target_text,
                updated_at=anchor.updated_at,
                now=now,
                base=26,
            )
            observed = observed_by_key.get((anchor.kind.value, anchor.normalized_key))
            if observed is not None:
                score += observed.score_boost
                reasons.append(observed.reason)
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="anchor",
                    target_id=str(anchor.id),
                    label=f"{anchor.kind.value}: {anchor.label}",
                    preview=anchor.description or anchor.label,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "anchor_kind": anchor.kind.value,
                        "normalized_key": anchor.normalized_key,
                        "aliases": list(anchor.aliases),
                        "matched_terms": list(matched_terms),
                        **(observed.metadata if observed is not None else {}),
                    },
                )
            )
        for fact in [*facts, *recent_facts]:
            key = ("fact", str(fact.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=fact.text,
                updated_at=fact.updated_at,
                now=now,
                base=52,
            )
            if fact.thread_id and str(fact.thread_id) == source_thread_id:
                score += 12
                reasons.append("same thread")
            if fact.category:
                reasons.append(f"category:{fact.category}")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="fact",
                    target_id=str(fact.id),
                    label=fact.category or fact.kind.value,
                    preview=fact.text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "version": fact.version,
                        "tags": list(fact.tags),
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for episode in episodes:
            key = ("episode", str(episode.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            target_text = " ".join(
                part
                for part in (
                    episode.text,
                    episode.source_type,
                    episode.source_external_id,
                    episode.speaker.value,
                )
                if part
            )
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=target_text,
                updated_at=episode.occurred_at,
                now=now,
                base=44,
            )
            if str(episode.thread_id) == source_thread_id:
                score += 12
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="episode",
                    target_id=str(episode.id),
                    label=_episode_label(episode),
                    preview=episode.text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "source_type": episode.source_type,
                        "source_external_id": episode.source_external_id,
                        "thread_id": str(episode.thread_id),
                        "speaker": episode.speaker.value,
                        "trust_level": episode.trust_level.value,
                        "occurred_at": episode.occurred_at.isoformat(),
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for capture in captures:
            key = ("capture", str(capture.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=capture.text,
                updated_at=capture.created_at,
                now=now,
                base=36,
            )
            if capture.thread_id and str(capture.thread_id) == source_thread_id:
                score += 12
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="capture",
                    target_id=str(capture.id),
                    label=capture.event_type,
                    preview=capture.text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "source_agent": capture.source_agent,
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for suggestion in suggestions:
            key = ("suggestion", str(suggestion.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=suggestion.candidate_text,
                updated_at=suggestion.created_at,
                now=now,
                base=42,
            )
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="suggestion",
                    target_id=str(suggestion.id),
                    label=suggestion.operation.value,
                    preview=suggestion.candidate_text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "confidence": suggestion.confidence.value,
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for asset in assets:
            key = ("asset", str(asset.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            target_text = f"{asset.filename} {asset.content_type}"
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=target_text,
                updated_at=asset.created_at,
                now=now,
                base=34,
            )
            if asset.thread_id and str(asset.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="asset",
                    target_id=str(asset.id),
                    label=asset.filename,
                    preview=target_text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "content_type": asset.content_type,
                        "byte_size": asset.byte_size,
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for document in documents:
            key = ("document", str(document.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            target_text = f"{document.title} {document.source_type} {document.source_external_id}"
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=target_text,
                updated_at=document.updated_at,
                now=now,
                base=38,
            )
            if document.thread_id and str(document.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="document",
                    target_id=str(document.id),
                    label=document.title,
                    preview=target_text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "source_type": document.source_type,
                        "source_external_id": document.source_external_id,
                        "classification": document.classification,
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for chunk in chunks:
            key = ("chunk", str(chunk.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=chunk.text,
                updated_at=chunk.updated_at,
                now=now,
                base=46,
            )
            if chunk.thread_id and str(chunk.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="chunk",
                    target_id=str(chunk.id),
                    label=_chunk_label(chunk),
                    preview=chunk.text,
                    score=score,
                    reasons=reasons,
                    metadata={
                        "document_id": str(chunk.document_id) if chunk.document_id else None,
                        "source_type": chunk.source_type,
                        "source_external_id": chunk.source_external_id,
                        "kind": chunk.kind.value,
                        "sequence": chunk.sequence,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "matched_terms": list(matched_terms),
                    },
                )
            )
        for thread in threads:
            key = ("thread", str(thread.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            target_text = thread.external_ref.replace("-", " ")
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=target_text,
                updated_at=thread.updated_at,
                now=now,
                base=30,
            )
            if source_thread_id and str(thread.id) == source_thread_id:
                score += 12
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            candidates.append(
                _candidate(
                    target_type="thread",
                    target_id=str(thread.id),
                    label=thread.external_ref,
                    preview=f"Thread {thread.external_ref}",
                    score=score,
                    reasons=reasons,
                    metadata={
                        "external_ref": thread.external_ref,
                        "matched_terms": list(matched_terms),
                    },
                )
            )

        ranked = sorted(
            candidates,
            key=lambda item: (-item.score, item.target_type, item.target_id),
        )
        diagnostics["query_terms"] = list(terms)
        diagnostics["candidate_count"] = len(ranked)
        ranked = ranked[: command.limit]
        if command.persist:
            ranked = await self._persist_candidates(command, ranked, diagnostics)
        return ContextLinkSuggestionsResult(
            candidates=tuple(ranked),
            diagnostics=diagnostics,
        )

    async def _upsert_observed_anchors(
        self,
        uow: UnitOfWorkPort,
        *,
        command: SuggestContextLinksCommand,
        text: str,
    ) -> list[MemoryAnchor]:
        now = self._clock.now()
        anchors: list[MemoryAnchor] = []
        for observed in extract_observed_anchors(text):
            existing = await uow.anchors.find_active_by_key(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                kind=observed.kind.value,
                normalized_key=observed.normalized_key,
            )
            metadata = {
                **observed.metadata,
                "last_observed_source_type": command.source_type,
                "last_observed_source_id": command.source_id,
                "resolver_version": "context-link-rule-v1",
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
            else:
                saved = await uow.anchors.create(
                    MemoryAnchor.create(
                        anchor_id=MemoryAnchorId(self._ids.new_id("anchor")),
                        space_id=command.space_id,
                        memory_scope_id=command.memory_scope_id,
                        kind=observed.kind,
                        normalized_key=observed.normalized_key,
                        label=observed.label,
                        aliases=observed.aliases,
                        description=f"Observed {observed.kind.value} anchor from memory evidence.",
                        metadata=metadata,
                        now=now,
                    )
                )
            anchors.append(saved)
        return anchors

    async def _persist_candidates(
        self,
        command: SuggestContextLinksCommand,
        candidates: list[ContextLinkCandidate],
        diagnostics: dict[str, object],
    ) -> list[ContextLinkCandidate]:
        if not command.source_type or not command.source_id:
            return candidates
        now = self._clock.now()
        persisted: list[ContextLinkCandidate] = []
        skipped_existing_links = 0
        async with self._uow_factory() as uow:
            await assert_context_link_endpoint_visible(
                uow,
                endpoint_type=command.source_type,
                endpoint_id=command.source_id,
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                role="source",
            )
            for candidate in candidates:
                existing_link = await uow.context_links.find_active(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    source_type=command.source_type,
                    source_id=command.source_id,
                    target_type=candidate.target_type,
                    target_id=candidate.target_id,
                    relation_type="related_to",
                )
                if existing_link is not None:
                    skipped_existing_links += 1
                    continue
                existing = await uow.context_link_suggestions.find_pending(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    source_type=command.source_type,
                    source_id=command.source_id,
                    target_type=candidate.target_type,
                    target_id=candidate.target_id,
                    relation_type="related_to",
                )
                if existing is None:
                    suggestion = MemoryContextLinkSuggestion.create(
                        suggestion_id=MemoryContextLinkSuggestionId(self._ids.new_id("ctxlinksug")),
                        space_id=command.space_id,
                        memory_scope_id=command.memory_scope_id,
                        source_type=command.source_type,
                        source_id=command.source_id,
                        target_type=candidate.target_type,
                        target_id=candidate.target_id,
                        relation_type="related_to",
                        confidence=_confidence_for_candidate(candidate),
                        reason=_candidate_reason(candidate),
                        score=candidate.score,
                        metadata=_candidate_metadata(candidate, diagnostics),
                        now=now,
                    )
                    saved = await uow.context_link_suggestions.create(suggestion)
                else:
                    saved = existing
                persisted.append(
                    replace(
                        candidate,
                        suggestion_id=str(saved.id),
                        status=saved.status.value,
                    )
                )
            await uow.commit()
        diagnostics["persisted_count"] = len(persisted)
        diagnostics["skipped_existing_link_count"] = skipped_existing_links
        return persisted


def _same_scope(entity: object, command: SuggestContextLinksCommand) -> bool:
    return str(entity.space_id) == str(command.space_id) and str(entity.memory_scope_id) == str(
        command.memory_scope_id
    )


def _join_text(left: str, right: str) -> str:
    return " ".join(part for part in (left.strip(), right.strip()) if part)


def _terms(text: str) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for raw in _TERM_PATTERN.findall(text.lower()):
        term = raw.strip("._-:/#")
        if len(term) >= 3 and term not in _LINK_STOP_TERMS and term not in seen:
            seen[term] = None
    return tuple(seen)


def _score_text_candidate(
    *,
    query_terms: tuple[str, ...],
    temporal_hints: tuple[_TemporalHint, ...],
    target_text: str,
    updated_at: datetime,
    now: datetime,
    base: float,
) -> tuple[float, list[str], tuple[str, ...]]:
    score = base
    reasons: list[str] = []
    lowered = target_text.lower()
    hits = tuple(term for term in query_terms if term in lowered)
    if hits:
        score += min(48.0, 8.0 * len(hits))
        reasons.append("matching text")
    relative_age_hours = _relative_age_hours(updated_at, now)
    if _matches_temporal_hint(temporal_hints, relative_age_hours):
        score += 6 if hits else 22
        reasons.append("temporal intent match")
    age_hours = max(relative_age_hours, 0.0)
    if age_hours <= 1:
        score += 18
        reasons.append("recent activity")
    elif age_hours <= 24:
        score += 12
        reasons.append("recent activity")
    elif age_hours <= 24 * 7:
        score += max(2.0, 10.0 - log(age_hours + 1))
        reasons.append("near in time")
    if not reasons:
        reasons.append("recent context")
    return min(score, 99.0), reasons, hits


def _has_link_signal(*, matched_terms: tuple[str, ...], reasons: list[str]) -> bool:
    if matched_terms:
        return True
    return any(
        reason
        in {
            "same thread",
            "explicit project reference",
            "known project/tool reference",
            "event phrase",
            "person name",
            "temporal intent match",
        }
        for reason in reasons
    )


def _temporal_hints(text: str) -> tuple[_TemporalHint, ...]:
    hints: list[_TemporalHint] = []
    seen: set[str] = set()
    for hint in _numeric_temporal_hints(text):
        seen.add(hint.code)
        hints.append(hint)
    for code, pattern, min_hours, max_hours in _TEMPORAL_HINT_PATTERNS:
        if code in seen or not pattern.search(text):
            continue
        seen.add(code)
        hints.append(_TemporalHint(code=code, min_hours=min_hours, max_hours=max_hours))
    return tuple(hints)


def _numeric_temporal_hints(text: str) -> tuple[_TemporalHint, ...]:
    hints: list[_TemporalHint] = []
    seen: set[str] = set()
    for unit, pattern, unit_hours, max_count in _NUMERIC_TEMPORAL_HINT_PATTERNS:
        for match in pattern.finditer(text):
            count = int(match.group("count"))
            if count <= 0 or count > max_count:
                continue
            code = f"{count}_{unit}_ago"
            if code in seen:
                continue
            seen.add(code)
            min_hours, max_hours = _numeric_temporal_window(count * unit_hours)
            hints.append(_TemporalHint(code=code, min_hours=min_hours, max_hours=max_hours))
    return tuple(hints)


def _numeric_temporal_window(target_hours: float) -> tuple[float, float]:
    if target_hours <= 24:
        tolerance = max(1.0, target_hours * 0.3)
    elif target_hours <= 24 * 7:
        tolerance = max(6.0, target_hours * 0.2)
    else:
        tolerance = max(24.0, target_hours * 0.15)
    return max(0.0, target_hours - tolerance), target_hours + tolerance


def _matches_temporal_hint(hints: tuple[_TemporalHint, ...], age_hours: float) -> bool:
    return any(hint.min_hours <= age_hours <= hint.max_hours for hint in hints)


def _candidate(
    *,
    target_type: str,
    target_id: str,
    label: str,
    preview: str,
    score: float,
    reasons: list[str],
    metadata: dict[str, object],
) -> ContextLinkCandidate:
    unique_reasons = tuple(dict.fromkeys(reasons))
    safe_metadata = dict(metadata)
    safe_metadata["reason_codes"] = _reason_codes(unique_reasons)
    return ContextLinkCandidate(
        target_type=target_type,
        target_id=target_id,
        label=label[:120],
        preview=preview[:_MAX_CANDIDATE_PREVIEW],
        score=round(score, 2),
        tier=_tier(score),
        reasons=unique_reasons,
        metadata=safe_metadata,
    )


def _candidate_reason(candidate: ContextLinkCandidate) -> str:
    reason = "; ".join(candidate.reasons)
    return reason[:320] if reason else "related memory candidate"


def _chunk_label(chunk: MemoryChunk) -> str:
    sequence = chunk.sequence
    kind = chunk.kind.value
    source = chunk.source_external_id.strip()
    suffix = f" - {source}" if source else ""
    if isinstance(sequence, int):
        return f"{kind} #{sequence}{suffix}"
    return f"{kind}{suffix}"


def _episode_label(episode: object) -> str:
    source = str(getattr(episode, "source_external_id", "")).strip()
    source_type = str(getattr(episode, "source_type", "")).strip()
    return " - ".join(part for part in (source_type, source) if part) or "episode"


def _confidence_for_candidate(candidate: ContextLinkCandidate) -> str:
    if candidate.tier == "likely":
        return "high"
    if candidate.tier == "possible":
        return "medium"
    return "low"


def _candidate_metadata(
    candidate: ContextLinkCandidate,
    diagnostics: dict[str, object],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "target_label": candidate.label,
        "target_preview": candidate.preview,
        "target_tier": candidate.tier,
        "resolver_version": str(diagnostics.get("resolver_version", "unknown")),
        "reason_codes": _reason_codes(candidate.reasons),
    }
    for key, value in (candidate.metadata or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            metadata[str(key)] = value
        elif isinstance(value, (list, tuple)):
            cleaned = [
                item for item in value if isinstance(item, (str, int, float, bool)) or item is None
            ]
            if cleaned:
                metadata[str(key)] = cleaned
    return metadata


def _reason_codes(reasons: tuple[str, ...]) -> list[str]:
    codes: list[str] = []
    for reason in reasons:
        if reason == "matching text":
            codes.append("text_match")
        elif reason == "recent activity":
            codes.append("recent_activity")
        elif reason == "near in time":
            codes.append("temporal_proximity")
        elif reason == "temporal intent match":
            codes.append("temporal_intent_match")
        elif reason == "same thread":
            codes.append("same_thread")
        elif reason.startswith("category:"):
            codes.append("shared_category")
        elif reason == "recent context":
            codes.append("recent_context")
        else:
            codes.append("rule_signal")
    return list(dict.fromkeys(codes))


def _tier(score: float) -> str:
    if score >= 75:
        return "likely"
    if score >= 55:
        return "possible"
    return "weak"


def _age_hours(value: datetime, now: datetime) -> float:
    return max(_relative_age_hours(value, now), 0.0)


def _relative_age_hours(value: datetime, now: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - value).total_seconds() / 3600


def _is_same_source(
    key: tuple[str, str],
    command: SuggestContextLinksCommand,
) -> bool:
    return key[0] == command.source_type and key[1] == command.source_id
