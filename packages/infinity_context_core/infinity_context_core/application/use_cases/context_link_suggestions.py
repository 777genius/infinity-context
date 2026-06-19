"""Context-link suggestion resolver use case."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    extract_observed_anchors,
)
from infinity_context_core.application.context_link_candidate_policy import (
    candidate as _candidate,
)
from infinity_context_core.application.context_link_candidate_policy import (
    candidate_metadata as _candidate_metadata,
)
from infinity_context_core.application.context_link_candidate_policy import (
    candidate_reason as _candidate_reason,
)
from infinity_context_core.application.context_link_candidate_policy import (
    chunk_label as _chunk_label,
)
from infinity_context_core.application.context_link_candidate_policy import (
    chunk_multimodal_evidence_metadata as _chunk_multimodal_evidence_metadata,
)
from infinity_context_core.application.context_link_candidate_policy import (
    confidence_for_candidate as _confidence_for_candidate,
)
from infinity_context_core.application.context_link_candidate_policy import (
    episode_label as _episode_label,
)
from infinity_context_core.application.context_link_candidate_policy import (
    evidence_summary as _evidence_summary,
)
from infinity_context_core.application.context_link_candidate_policy import (
    excluded_term_hits as _excluded_term_hits,
)
from infinity_context_core.application.context_link_candidate_policy import (
    excluded_terms as _excluded_terms,
)
from infinity_context_core.application.context_link_candidate_policy import (
    has_link_signal as _has_link_signal,
)
from infinity_context_core.application.context_link_candidate_policy import (
    is_same_source as _is_same_source,
)
from infinity_context_core.application.context_link_candidate_policy import (
    multimodal_reason_hints as _multimodal_reason_hints,
)
from infinity_context_core.application.context_link_candidate_policy import (
    score_text_candidate as _score_text_candidate,
)
from infinity_context_core.application.context_link_candidate_policy import (
    source_text_risk_metadata as _source_text_risk_metadata,
)
from infinity_context_core.application.context_link_candidate_policy import (
    source_text_risk_metadata_from_mapping as _source_text_risk_metadata_from_mapping,
)
from infinity_context_core.application.context_link_candidate_policy import (
    temporal_hints as _temporal_hints,
)
from infinity_context_core.application.context_link_candidate_policy import (
    terms as _terms,
)
from infinity_context_core.application.context_link_policy import (
    apply_context_link_policy,
    policy_confidence_for_candidate,
    policy_relation_type_for_candidate,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import (
    ContextLinkCandidate,
    ContextLinkSuggestionsResult,
    SuggestContextLinksCommand,
)
from infinity_context_core.application.observed_anchor_resolution import (
    canonical_anchor_keys,
    find_active_by_observed_canonical_key,
    observed_canonical_key,
    preferred_observed_label,
    should_promote_observed_key,
)
from infinity_context_core.application.source_refs import chunk_source_refs as _chunk_source_refs
from infinity_context_core.application.use_cases.context_link_visibility import (
    assert_context_link_endpoint_visible,
)
from infinity_context_core.domain.assets import (
    ContextLinkSuggestionStatus,
    MemoryContextLinkSuggestion,
    MemoryContextLinkSuggestionId,
)
from infinity_context_core.domain.entities import (
    Confidence,
    MemoryAnchor,
    MemoryAnchorId,
    MemoryAnchorKind,
    SourceRef,
)
from infinity_context_core.domain.errors import MemoryValidationError
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort, UnitOfWorkPort

MAX_CONTEXT_LINK_SUGGESTION_LIMIT = 30


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
        effective_limit = _bounded_suggestion_limit(command.limit)
        diagnostics["requested_limit"] = command.limit
        diagnostics["effective_limit"] = effective_limit
        if effective_limit != command.limit:
            diagnostics["limit_clamped"] = True
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
            source_risk_metadata = dict(_source_text_risk_metadata(query_text))
            if command.source_type == "asset_extraction" and command.source_id:
                extraction_job = await uow.asset_extractions.get_by_id(command.source_id)
                if extraction_job is not None and _same_scope(extraction_job, command):
                    if extraction_job.thread_id:
                        source_thread_id = str(extraction_job.thread_id)
                    source_risk_metadata.update(
                        _source_extraction_risk_metadata(extraction_job.metadata)
                    )
            if source_risk_metadata:
                diagnostics.update(source_risk_metadata)
            facts = await uow.facts.find_active(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=None,
                query=query_text,
                limit=max(effective_limit * 3, 12),
            )
            recent_facts = await uow.facts.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(effective_limit, 8),
            )
            episodes = await uow.episodes.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(effective_limit, 8),
            )
            captures = await uow.captures.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="accepted",
                consolidation_status=None,
                limit=max(effective_limit, 8),
            )
            suggestions = await uow.suggestions.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="pending",
                operation=None,
                category=None,
                tag=None,
                limit=max(effective_limit, 8),
            )
            assets = await uow.assets.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="stored",
                limit=max(effective_limit, 8),
            )
            documents = await uow.documents.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                thread_id=None,
                status="active",
                limit=max(effective_limit, 8),
            )
            chunks = await uow.chunks.keyword_search(
                space_id=str(command.space_id),
                memory_scope_ids=(str(command.memory_scope_id),),
                thread_id=None,
                query=query_text,
                limit=max(effective_limit * 2, 12),
            )
            threads = await uow.scope.list_threads(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                status="active",
                limit=max(effective_limit, 8),
            )
            anchors = await uow.anchors.list_for_scope(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                kind=None,
                status="active",
                limit=max(effective_limit * 3, 24),
            )
            if command.persist and not source_risk_metadata:
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
            elif command.persist and source_risk_metadata:
                diagnostics["observed_anchor_upsert_skipped_reason"] = _source_risk_skip_reason(
                    source_risk_metadata
                )

        terms = _terms(query_text)
        excluded_terms = _excluded_terms(query_text)
        temporal_hints = _temporal_hints(query_text)
        now = self._clock.now()
        if excluded_terms:
            diagnostics["excluded_query_terms"] = list(excluded_terms)
        if temporal_hints:
            diagnostics["temporal_hints"] = [hint.code for hint in temporal_hints]
        observed_for_query = extract_observed_anchors(query_text)
        observed_by_key = {
            (anchor.kind.value, anchor.normalized_key): anchor
            for anchor in observed_for_query
        }
        observed_by_canonical_key = {
            (anchor.kind.value, key): anchor
            for anchor in observed_for_query
            if (key := observed_canonical_key(anchor))
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
            observed = _observed_anchor_for_candidate(
                anchor,
                observed_by_key=observed_by_key,
                observed_by_canonical_key=observed_by_canonical_key,
            )
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
                        **_evidence_summary(anchor.evidence_refs),
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
                        **_evidence_summary(fact.source_refs),
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
                        **_evidence_summary(capture.evidence_refs),
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
                        **_evidence_summary(suggestion.source_refs),
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
                        **_evidence_summary(
                            (SourceRef(source_type="asset", source_id=str(asset.id)),)
                        ),
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
                        **_evidence_summary(
                            (
                                SourceRef(
                                    source_type=document.source_type,
                                    source_id=document.source_external_id,
                                ),
                            )
                        ),
                    },
                )
            )
        for chunk in chunks:
            key = ("chunk", str(chunk.id))
            if key in seen or _is_same_source(key, command):
                continue
            seen.add(key)
            retrieval_text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            )
            score, reasons, matched_terms = _score_text_candidate(
                query_terms=terms,
                temporal_hints=temporal_hints,
                target_text=retrieval_text,
                updated_at=chunk.updated_at,
                now=now,
                base=46,
            )
            if chunk.thread_id and str(chunk.thread_id) == source_thread_id:
                score += 8
                reasons.append("same thread")
            if not _has_link_signal(matched_terms=matched_terms, reasons=reasons):
                continue
            reasons.extend(
                _multimodal_reason_hints(
                    metadata=chunk.metadata,
                    matched_terms=matched_terms,
                )
            )
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
                        **_evidence_summary(_chunk_source_refs(chunk, text_preview=chunk.text)),
                        **_chunk_multimodal_evidence_metadata(chunk.metadata),
                        **_source_text_risk_metadata_from_mapping(chunk.metadata),
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

        if source_risk_metadata:
            candidates = [
                _with_source_text_risk_metadata(candidate, source_risk_metadata)
                for candidate in candidates
            ]
        if excluded_terms:
            candidates = [
                _with_excluded_term_penalty(candidate, excluded_terms) for candidate in candidates
            ]
        ranked = sorted(
            candidates,
            key=lambda item: (-item.score, item.target_type, item.target_id),
        )
        diagnostics["query_terms"] = list(terms)
        diagnostics["candidate_count_before_policy"] = len(ranked)
        policy_result = apply_context_link_policy(
            tuple(ranked),
            limit=effective_limit,
            persist=command.persist,
        )
        ranked = list(policy_result.candidates)
        diagnostics.update(policy_result.diagnostics)
        diagnostics["candidate_count"] = len(ranked)
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
            if existing is None:
                existing = await find_active_by_observed_canonical_key(
                    uow,
                    observed=observed,
                    space_id=command.space_id,
                    memory_scope_id=command.memory_scope_id,
                )
            metadata = {
                **observed.metadata,
                "last_observed_source_type": command.source_type,
                "last_observed_source_id": command.source_id,
                "resolver_version": "context-link-rule-v1",
            }
            confidence = _confidence_for_observed_anchor(observed.score_boost)
            evidence_refs = (
                (SourceRef(source_type=command.source_type, source_id=command.source_id),)
                if command.source_type and command.source_id
                else ()
            )
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
                    if should_promote_observed_key(existing, observed)
                    else existing.merge_observation(
                        label=preferred_observed_label(existing, observed),
                        aliases=observed.aliases,
                        confidence=confidence,
                        evidence_refs=evidence_refs,
                        observed_at=now,
                        metadata=metadata,
                        now=now,
                    )
                )
                saved = await uow.anchors.save(merged)
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
                        confidence=confidence,
                        evidence_refs=evidence_refs,
                        observed_at=now,
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
        skipped_reviewed_suggestions = 0
        skipped_reviewed_by_status: dict[str, int] = {}
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
                relation_type = _suggestion_relation_type(candidate)
                existing_link = await uow.context_links.find_active(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    source_type=command.source_type,
                    source_id=command.source_id,
                    target_type=candidate.target_type,
                    target_id=candidate.target_id,
                    relation_type=relation_type,
                )
                if existing_link is not None:
                    skipped_existing_links += 1
                    continue
                existing = await uow.context_link_suggestions.find_latest_for_pair(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    source_type=command.source_type,
                    source_id=command.source_id,
                    target_type=candidate.target_type,
                    target_id=candidate.target_id,
                    relation_type=relation_type,
                )
                if existing is not None and existing.status in {
                    ContextLinkSuggestionStatus.APPROVED,
                    ContextLinkSuggestionStatus.REJECTED,
                }:
                    skipped_reviewed_suggestions += 1
                    status = existing.status.value
                    skipped_reviewed_by_status[status] = (
                        skipped_reviewed_by_status.get(status, 0) + 1
                    )
                    continue
                if existing is None:
                    suggestion = MemoryContextLinkSuggestion.create(
                        suggestion_id=MemoryContextLinkSuggestionId(self._ids.new_id("ctxlinksug")),
                        space_id=command.space_id,
                        memory_scope_id=command.memory_scope_id,
                        source_type=command.source_type,
                        source_id=command.source_id,
                        target_type=candidate.target_type,
                        target_id=candidate.target_id,
                        relation_type=relation_type,
                        confidence=_suggestion_confidence(candidate),
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
        diagnostics["skipped_reviewed_suggestion_count"] = skipped_reviewed_suggestions
        diagnostics["skipped_reviewed_suggestion_status_counts"] = skipped_reviewed_by_status
        return persisted


def _confidence_for_observed_anchor(score_boost: int) -> Confidence:
    if score_boost >= 22:
        return Confidence.HIGH
    if score_boost <= 8:
        return Confidence.LOW
    return Confidence.MEDIUM


def _observed_anchor_for_candidate(
    anchor: MemoryAnchor,
    *,
    observed_by_key: dict[tuple[str, str], ObservedAnchor],
    observed_by_canonical_key: dict[tuple[str, str], ObservedAnchor],
) -> ObservedAnchor | None:
    observed = observed_by_key.get((anchor.kind.value, anchor.normalized_key))
    if observed is not None:
        return observed
    if anchor.kind not in {MemoryAnchorKind.ORGANIZATION, MemoryAnchorKind.PROJECT}:
        return None
    for key in canonical_anchor_keys(anchor):
        if observed := observed_by_canonical_key.get((anchor.kind.value, key)):
            return observed
    return None


def _suggestion_confidence(candidate: ContextLinkCandidate) -> str:
    return policy_confidence_for_candidate(candidate) or _confidence_for_candidate(candidate)


def _suggestion_relation_type(candidate: ContextLinkCandidate) -> str:
    return policy_relation_type_for_candidate(candidate) or "related_to"


def _same_scope(entity: object, command: SuggestContextLinksCommand) -> bool:
    return str(entity.space_id) == str(command.space_id) and str(entity.memory_scope_id) == str(
        command.memory_scope_id
    )


def _join_text(left: str, right: str) -> str:
    return ". ".join(part for part in (left.strip(" ."), right.strip(" .")) if part)


def _bounded_suggestion_limit(limit: int) -> int:
    return min(max(1, limit), MAX_CONTEXT_LINK_SUGGESTION_LIMIT)


def _with_source_text_risk_metadata(
    candidate: ContextLinkCandidate,
    source_risk_metadata: dict[str, object],
) -> ContextLinkCandidate:
    metadata = dict(candidate.metadata or {})
    metadata.update(source_risk_metadata)
    return replace(candidate, metadata=metadata)


def _with_excluded_term_penalty(
    candidate: ContextLinkCandidate,
    excluded_terms: tuple[str, ...],
) -> ContextLinkCandidate:
    hits = _excluded_term_hits(candidate, excluded_terms)
    if not hits:
        return candidate
    metadata = dict(candidate.metadata or {})
    metadata["excluded_matched_terms"] = list(hits)
    penalty = min(40.0, 24.0 * len(hits))
    return replace(
        candidate,
        score=max(0.0, candidate.score - penalty),
        reasons=(*candidate.reasons, "excluded query term"),
        metadata=metadata,
    )


def _source_extraction_risk_metadata(metadata: dict[str, object]) -> dict[str, object]:
    prompt_risk_metadata = _source_text_risk_metadata_from_mapping(metadata)
    risk_metadata: dict[str, object] = {
        **prompt_risk_metadata,
    }
    if metadata.get("mime_content_type_mismatch") is True:
        risk_metadata["mime_content_type_mismatch"] = True
        _copy_scalar_metadata(
            risk_metadata,
            metadata,
            keys=(
                "mime_declared_content_type",
                "mime_detected_content_type",
                "mime_magic_content_type",
                "mime_extension_content_type",
                "mime_detector_reason",
                "detector_confidence",
            ),
        )
    if metadata.get("mime_archive_review_required") is True:
        risk_metadata["mime_archive_review_required"] = True
        _copy_scalar_metadata(
            risk_metadata,
            metadata,
            keys=(
                "mime_archive_detected",
                "mime_archive_review_reason",
                "mime_declared_content_type",
                "mime_detected_content_type",
                "mime_magic_content_type",
                "mime_filename_extension",
                "mime_detector_reason",
                "detector_confidence",
            ),
        )
    return risk_metadata


def _source_risk_skip_reason(source_risk_metadata: dict[str, object]) -> str:
    if source_risk_metadata.get("prompt_injection_signals_detected") is True:
        return "prompt_injection_evidence"
    if source_risk_metadata.get("mime_content_type_mismatch") is True:
        return "mime_content_type_mismatch"
    if source_risk_metadata.get("mime_archive_review_required") is True:
        return "mime_archive_review_required"
    return "source_risk_evidence"


def _copy_scalar_metadata(
    target: dict[str, object],
    source: dict[str, object],
    *,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            target[key] = value
