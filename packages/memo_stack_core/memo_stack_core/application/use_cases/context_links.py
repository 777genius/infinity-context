"""Context-link creation and suggestion use cases."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from math import log

from memo_stack_core.application.anchor_extraction import extract_observed_anchors
from memo_stack_core.application.dto import (
    ContextLinkCandidate,
    ContextLinkResult,
    ContextLinkSuggestionResult,
    ContextLinkSuggestionsResult,
    CreateContextLinkCommand,
    DeleteContextLinkCommand,
    ListContextLinksQuery,
    ListContextLinkSuggestionsQuery,
    ReviewContextLinkSuggestionCommand,
    SuggestContextLinksCommand,
)
from memo_stack_core.domain.assets import (
    MemoryContextLink,
    MemoryContextLinkId,
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from memo_stack_core.domain.entities import (
    MemoryAnchor,
    MemoryAnchorId,
    MemoryChunk,
)
from memo_stack_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_MAX_CANDIDATE_PREVIEW = 220
_ALLOWED_ENDPOINT_STATUSES: dict[str, set[str]] = {
    "anchor": {"active"},
    "asset": {"stored"},
    "capture": {"accepted"},
    "chunk": {"active"},
    "document": {"active"},
    "fact": {"active", "disputed", "superseded"},
    "suggestion": {"pending", "approved", "rejected"},
    "thread": {"active"},
}


class CreateContextLinkUseCase:
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

    async def execute(self, command: CreateContextLinkCommand) -> ContextLinkResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            await _assert_endpoint_visible(
                uow,
                endpoint_type=command.source_type,
                endpoint_id=command.source_id,
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                role="source",
            )
            await _assert_endpoint_visible(
                uow,
                endpoint_type=command.target_type,
                endpoint_id=command.target_id,
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                role="target",
            )
            existing = await uow.context_links.find_active(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                source_type=command.source_type,
                source_id=command.source_id,
                target_type=command.target_type,
                target_id=command.target_id,
                relation_type=command.relation_type,
            )
            if existing is not None:
                return ContextLinkResult(link=existing, duplicate=True)
            link = MemoryContextLink.create(
                link_id=MemoryContextLinkId(self._ids.new_id("ctxlink")),
                space_id=command.space_id,
                memory_scope_id=command.memory_scope_id,
                source_type=command.source_type,
                source_id=command.source_id,
                target_type=command.target_type,
                target_id=command.target_id,
                relation_type=command.relation_type,
                confidence=command.confidence,
                reason=command.reason,
                metadata=command.metadata,
                now=now,
            )
            saved = await uow.context_links.create(link)
            await uow.commit()
        return ContextLinkResult(link=saved)


class ListContextLinksUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListContextLinksQuery) -> list[MemoryContextLink]:
        async with self._uow_factory() as uow:
            return await uow.context_links.list_for_source(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                source_type=query.source_type,
                source_id=query.source_id,
                status=query.status,
                limit=query.limit,
            )


class DeleteContextLinkUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: DeleteContextLinkCommand) -> ContextLinkResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            link = await uow.context_links.get_by_id(command.context_link_id)
            if link is None:
                raise MemoryNotFoundError("Context link not found")
            saved = await uow.context_links.save(link.delete(now=now))
            await uow.commit()
        return ContextLinkResult(link=saved)


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
            facts = await uow.facts.find_active(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=source_thread_id,
                query=query_text,
                limit=max(command.limit * 3, 12),
            )
            recent_facts = await uow.facts.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=source_thread_id,
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
                thread_id=source_thread_id,
                status="stored",
                limit=max(command.limit, 8),
            )
            documents = await uow.documents.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=source_thread_id,
                status="active",
                limit=max(command.limit, 8),
            )
            chunks = await uow.chunks.keyword_search(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=source_thread_id,
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
                target_text=target_text,
                updated_at=anchor.updated_at,
                now=self._clock.now(),
                base=26,
            )
            observed = observed_by_key.get((anchor.kind.value, anchor.normalized_key))
            if observed is not None:
                score += observed.score_boost
                reasons.append(observed.reason)
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
                target_text=fact.text,
                updated_at=fact.updated_at,
                now=self._clock.now(),
                base=52,
            )
            if fact.thread_id and str(fact.thread_id) == source_thread_id:
                score += 12
                reasons.append("same thread")
            if fact.category:
                reasons.append(f"category:{fact.category}")
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
        for capture in captures:
            key = ("capture", str(capture.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                target_text=capture.text,
                updated_at=capture.created_at,
                now=self._clock.now(),
                base=36,
            )
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
                target_text=suggestion.candidate_text,
                updated_at=suggestion.created_at,
                now=self._clock.now(),
                base=42,
            )
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
                target_text=target_text,
                updated_at=asset.created_at,
                now=self._clock.now(),
                base=34,
            )
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
                target_text=target_text,
                updated_at=document.updated_at,
                now=self._clock.now(),
                base=38,
            )
            if document.thread_id and str(document.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
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
                target_text=chunk.text,
                updated_at=chunk.updated_at,
                now=self._clock.now(),
                base=46,
            )
            if chunk.thread_id and str(chunk.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
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
                target_text=target_text,
                updated_at=thread.updated_at,
                now=self._clock.now(),
                base=30,
            )
            if source_thread_id and str(thread.id) == source_thread_id:
                score += 12
                reasons.append("same thread")
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
            await _assert_endpoint_visible(
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


class ListContextLinkSuggestionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self,
        query: ListContextLinkSuggestionsQuery,
    ) -> list[MemoryContextLinkSuggestion]:
        async with self._uow_factory() as uow:
            return await uow.context_link_suggestions.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                status=query.status,
                limit=query.limit,
                source_type=query.source_type,
                source_id=query.source_id,
            )


class ReviewContextLinkSuggestionUseCase:
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

    async def execute(
        self,
        command: ReviewContextLinkSuggestionCommand,
    ) -> ContextLinkSuggestionResult:
        normalized_action = command.action.strip().lower()
        if normalized_action not in {"approve", "reject"}:
            raise MemoryValidationError("Unknown context link suggestion review action")

        now = self._clock.now()
        async with self._uow_factory() as uow:
            suggestion = await uow.context_link_suggestions.get_by_id(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Context link suggestion not found")

            if normalized_action == "reject":
                saved = await uow.context_link_suggestions.save(
                    suggestion.reject(now=now, reason=command.reason)
                )
                await uow.commit()
                return ContextLinkSuggestionResult(suggestion=saved)

            await _assert_endpoint_visible(
                uow,
                endpoint_type=suggestion.source_type,
                endpoint_id=suggestion.source_id,
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                role="source",
            )
            await _assert_endpoint_visible(
                uow,
                endpoint_type=suggestion.target_type,
                endpoint_id=suggestion.target_id,
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                role="target",
            )
            existing_link = await uow.context_links.find_active(
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                source_type=suggestion.source_type,
                source_id=suggestion.source_id,
                target_type=suggestion.target_type,
                target_id=suggestion.target_id,
                relation_type=suggestion.relation_type,
            )
            duplicate_link = existing_link is not None
            link = existing_link
            if link is None:
                link = MemoryContextLink.create(
                    link_id=MemoryContextLinkId(self._ids.new_id("ctxlink")),
                    space_id=suggestion.space_id,
                    memory_scope_id=suggestion.memory_scope_id,
                    source_type=suggestion.source_type,
                    source_id=suggestion.source_id,
                    target_type=suggestion.target_type,
                    target_id=suggestion.target_id,
                    relation_type=suggestion.relation_type,
                    confidence=suggestion.confidence,
                    reason=command.reason or suggestion.reason,
                    metadata={
                        **dict(suggestion.metadata),
                        "approved_from_suggestion_id": str(suggestion.id),
                    },
                    now=now,
                )
                link = await uow.context_links.create(link)
            saved = await uow.context_link_suggestions.save(
                suggestion.approve(now=now, reason=command.reason)
            )
            await uow.commit()
        return ContextLinkSuggestionResult(
            suggestion=saved,
            link=link,
            duplicate_link=duplicate_link,
        )


async def _assert_endpoint_visible(
    uow: UnitOfWorkPort,
    *,
    endpoint_type: str,
    endpoint_id: str,
    space_id: str,
    memory_scope_id: str,
    role: str,
) -> None:
    normalized_type = endpoint_type.strip().lower()
    allowed_statuses = _ALLOWED_ENDPOINT_STATUSES.get(normalized_type)
    if allowed_statuses is None:
        return

    entity = await _load_endpoint(uow, endpoint_type=normalized_type, endpoint_id=endpoint_id)
    if entity is None:
        raise MemoryValidationError(f"Context link {role} does not exist or is not visible")
    if str(entity.space_id) != space_id or str(entity.memory_scope_id) != memory_scope_id:
        raise MemoryValidationError(f"Context link {role} does not belong to scope")
    status = _status_value(getattr(entity, "status", None))
    if status not in allowed_statuses:
        raise MemoryValidationError(f"Context link {role} status is not linkable")


async def _load_endpoint(
    uow: UnitOfWorkPort,
    *,
    endpoint_type: str,
    endpoint_id: str,
) -> object | None:
    if endpoint_type == "anchor":
        return await uow.anchors.get_by_id(endpoint_id)
    if endpoint_type == "asset":
        return await uow.assets.get_by_id(endpoint_id)
    if endpoint_type == "capture":
        return await uow.captures.get_by_id(endpoint_id)
    if endpoint_type == "chunk":
        return await uow.chunks.get_by_id(endpoint_id)
    if endpoint_type == "document":
        return await uow.documents.get_by_id(endpoint_id)
    if endpoint_type == "fact":
        return await uow.facts.get_by_id(endpoint_id)
    if endpoint_type == "suggestion":
        return await uow.suggestions.get_by_id(endpoint_id)
    if endpoint_type == "thread":
        return await uow.scope.get_thread(endpoint_id)
    return None


def _status_value(status: object) -> str:
    value = getattr(status, "value", status)
    return str(value)


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
        if len(term) >= 3 and term not in seen:
            seen[term] = None
    return tuple(seen)


def _score_text_candidate(
    *,
    query_terms: tuple[str, ...],
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
        score += min(28.0, 9.0 * len(hits))
        reasons.append("matching text")
    age_hours = _age_hours(updated_at, now)
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
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return max((now - value).total_seconds() / 3600, 0.0)


def _is_same_source(
    key: tuple[str, str],
    command: SuggestContextLinksCommand,
) -> bool:
    return key[0] == command.source_type and key[1] == command.source_id
