"""Review-gated memory suggestions."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Any

from infinity_context_core.application.dto import (
    ApproveSuggestionCommand,
    CreateSuggestionBatchItemResult,
    CreateSuggestionCommand,
    CreateSuggestionsBatchCommand,
    CreateSuggestionsBatchResult,
    ExpireSuggestionCommand,
    ListSuggestionsQuery,
    RejectSuggestionCommand,
    ResolveSuggestionConflictCommand,
    ReviewSuggestionBatchItemCommand,
    ReviewSuggestionBatchItemResult,
    ReviewSuggestionsBatchCommand,
    ReviewSuggestionsBatchResult,
    SuggestionResult,
)
from infinity_context_core.application.review_payloads import CONFLICT_REVIEW_KIND
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.domain.entities import (
    Confidence,
    FactStatus,
    MemoryFact,
    MemoryFactId,
    MemorySuggestion,
    MemorySuggestionId,
    SuggestionOperation,
    SuggestionStatus,
    TrustLevel,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_TRUST_RANK = {TrustLevel.LOW: 1, TrustLevel.MEDIUM: 2, TrustLevel.HIGH: 3}
_ASSISTANT_SOURCES = {"ai_response", "assistant_answer", "assistant_summary"}
_CONFLICT_REVIEW_ACTION_ALIASES = {
    "approve_candidate": "approve_candidate",
    "keep_both": "approve_candidate",
    "replace_existing_fact": "replace_existing_fact",
    "reject_candidate": "reject_candidate",
    "expire_candidate": "expire_candidate",
    "mark_existing_disputed": "mark_existing_disputed",
    "mark_disputed": "mark_existing_disputed",
}


class CreateSuggestionUseCase:
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

    async def execute(self, command: CreateSuggestionCommand) -> SuggestionResult:
        now = self._clock.now()
        trust = TrustLevel(command.trust_level)
        operation = SuggestionOperation(command.operation)
        if command.target_fact_id and command.target_fact_version is None:
            raise MemoryValidationError(
                "Target fact version is required for targeted suggestion"
            )
        candidate_fingerprint = command.candidate_fingerprint or _suggestion_fingerprint(
            command=command,
            operation=operation,
        )
        suggestion = MemorySuggestion.create(
            suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            candidate_text=command.candidate_text,
            kind=command.kind,
            source_refs=command.source_refs,
            safe_reason=_safe_reason(command.safe_reason, command.auto_approve, trust),
            confidence=Confidence(command.confidence),
            trust_level=trust,
            target_fact_id=MemoryFactId(command.target_fact_id) if command.target_fact_id else None,
            target_fact_version=command.target_fact_version,
            operation=operation,
            category=command.category,
            tags=command.tags,
            ttl_policy=command.ttl_policy,
            expires_at=command.expires_at,
            expiry_reason=command.expiry_reason,
            created_from_capture_id=command.created_from_capture_id,
            candidate_fingerprint=candidate_fingerprint,
            review_payload=command.review_payload,
            now=now,
        )
        try:
            async with self._uow_factory() as uow:
                duplicate = await uow.suggestions.find_pending_duplicate(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    candidate_fingerprint=candidate_fingerprint,
                    operation=operation.value,
                    target_fact_id=command.target_fact_id,
                )
                if duplicate is not None:
                    return SuggestionResult(suggestion=duplicate, created=False)
                saved = await uow.suggestions.create(suggestion)
                await uow.commit()
        except MemoryConflictError:
            duplicate = await self._load_pending_duplicate(
                command=command,
                operation=operation,
                candidate_fingerprint=candidate_fingerprint,
            )
            if duplicate is not None:
                return SuggestionResult(suggestion=duplicate, created=False)
            raise
        return SuggestionResult(suggestion=saved)

    async def _load_pending_duplicate(
        self,
        *,
        command: CreateSuggestionCommand,
        operation: SuggestionOperation,
        candidate_fingerprint: str,
    ) -> MemorySuggestion | None:
        async with self._uow_factory() as uow:
            return await uow.suggestions.find_pending_duplicate(
                space_id=str(command.space_id),
                memory_scope_id=str(command.memory_scope_id),
                candidate_fingerprint=candidate_fingerprint,
                operation=operation.value,
                target_fact_id=command.target_fact_id,
            )


class CreateSuggestionsBatchUseCase:
    def __init__(self, *, create_suggestion: CreateSuggestionUseCase) -> None:
        self._create_suggestion = create_suggestion

    async def execute(self, command: CreateSuggestionsBatchCommand) -> CreateSuggestionsBatchResult:
        if not command.items:
            raise MemoryValidationError("Batch suggestion create requires at least one item")
        if len(command.items) > 50:
            raise MemoryValidationError("Batch suggestion create supports at most 50 items")

        results: list[CreateSuggestionBatchItemResult] = []
        stopped = False
        seen: set[tuple[object, ...]] = set()
        for index, item in enumerate(command.items):
            duplicate_key = _batch_candidate_key(item)
            if duplicate_key in seen:
                results.append(
                    CreateSuggestionBatchItemResult(
                        index=index,
                        status="failed",
                        error_code=MemoryConflictError.code,
                        error_message="Duplicate suggestion candidate in batch",
                    )
                )
                if not command.continue_on_error:
                    stopped = True
                    break
                continue
            seen.add(duplicate_key)
            try:
                result = await self._create_suggestion.execute(item)
                status = "created" if result.created else "existing"
                results.append(
                    CreateSuggestionBatchItemResult(
                        index=index,
                        status=status,
                        result=result,
                    )
                )
            except MemoryError as exc:
                results.append(
                    CreateSuggestionBatchItemResult(
                        index=index,
                        status="failed",
                        error_code=exc.code,
                        error_message=_safe_batch_error_message(exc),
                    )
                )
                if not command.continue_on_error:
                    stopped = True
                    break

        created = sum(1 for result in results if result.status == "created")
        existing = sum(1 for result in results if result.status == "existing")
        failed = sum(1 for result in results if result.status == "failed")
        return CreateSuggestionsBatchResult(
            created=created,
            existing=existing,
            failed=failed,
            stopped=stopped,
            results=tuple(results),
        )


class ListSuggestionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListSuggestionsQuery) -> list[MemorySuggestion]:
        async with self._uow_factory() as uow:
            return await uow.suggestions.list_for_scope(
                space_id=str(query.space_id),
                memory_scope_id=str(query.memory_scope_id),
                status=query.status,
                operation=query.operation,
                category=query.category,
                tag=query.tag,
                limit=query.limit,
            )


class ApproveSuggestionUseCase:
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

    async def execute(self, command: ApproveSuggestionCommand) -> SuggestionResult:
        async with self._uow_factory() as uow:
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            if not _has_independent_source(suggestion):
                raise MemoryValidationError(
                    "Suggestion approval requires non-assistant source refs"
                )
            if suggestion.target_fact_id and suggestion.target_fact_version is None:
                raise MemoryValidationError(
                    "Target fact version is required for targeted suggestion approval"
                )

            now = self._clock.now()
            fact: MemoryFact
            if suggestion.target_fact_id:
                current = await uow.facts.get_for_update(str(suggestion.target_fact_id))
                if (
                    current is None
                    or current.space_id != suggestion.space_id
                    or current.memory_scope_id != suggestion.memory_scope_id
                ):
                    raise MemoryNotFoundError("Target fact not found")
                if (
                    _TRUST_RANK[suggestion.trust_level] < _TRUST_RANK[current.trust_level]
                    and not command.force
                ):
                    raise MemoryConflictError("Weak suggestion cannot supersede stronger fact")
                if suggestion.operation == SuggestionOperation.DELETE:
                    expected = suggestion.target_fact_version or current.version
                    if current.version != expected:
                        raise MemoryConflictError("Stale fact version")
                    fact = current.forget(now=now)
                elif _is_duplicate_fact_merge_review(suggestion):
                    fact = current.merge_source_refs(
                        expected_version=suggestion.target_fact_version or current.version,
                        source_refs=suggestion.source_refs,
                        reason=command.reason or suggestion.safe_reason,
                        now=now,
                    )
                else:
                    fact = current.update(
                        expected_version=suggestion.target_fact_version or current.version,
                        text=suggestion.candidate_text,
                        source_refs=suggestion.source_refs,
                        reason=command.reason or suggestion.safe_reason,
                        category=suggestion.category,
                        tags=suggestion.tags,
                        ttl_policy=suggestion.ttl_policy,
                        expires_at=suggestion.expires_at,
                        now=now,
                    )
                fact = await uow.facts.save(fact)
            else:
                if suggestion.operation == SuggestionOperation.DELETE:
                    raise MemoryValidationError("Delete suggestion requires target fact")
                fact = MemoryFact.create(
                    fact_id=MemoryFactId(self._ids.new_id("fact")),
                    space_id=suggestion.space_id,
                    memory_scope_id=suggestion.memory_scope_id,
                    text=suggestion.candidate_text,
                    kind=suggestion.kind,
                    source_refs=suggestion.source_refs,
                    confidence=suggestion.confidence,
                    trust_level=suggestion.trust_level,
                    category=suggestion.category,
                    tags=suggestion.tags,
                    ttl_policy=suggestion.ttl_policy,
                    expires_at=suggestion.expires_at,
                    now=now,
                )
                fact = await uow.facts.create(fact)

            reviewed = suggestion.approve(now=now, reason=command.reason)
            saved_suggestion = await uow.suggestions.save(reviewed)
            projection_event = (
                "graph.delete_fact"
                if suggestion.operation == SuggestionOperation.DELETE
                else "graph.upsert_fact"
            )
            await uow.outbox.enqueue(
                OutboxEvent(
                    event_type=projection_event,
                    aggregate_type="fact",
                    aggregate_id=str(fact.id),
                    aggregate_version=fact.version,
                    payload={"fact_id": str(fact.id), "version": fact.version},
                )
            )
            await uow.commit()
        return SuggestionResult(
            suggestion=saved_suggestion,
            fact=fact,
            indexing_status="pending",
        )


class RejectSuggestionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RejectSuggestionCommand) -> SuggestionResult:
        async with self._uow_factory() as uow:
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            saved = await uow.suggestions.save(
                suggestion.reject(now=self._clock.now(), reason=command.reason)
            )
            await uow.commit()
        return SuggestionResult(suggestion=saved)


class ExpireSuggestionUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ExpireSuggestionCommand) -> SuggestionResult:
        async with self._uow_factory() as uow:
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            saved = await uow.suggestions.save(
                suggestion.expire(now=self._clock.now(), reason=command.reason)
            )
            await uow.commit()
        return SuggestionResult(suggestion=saved)


class ResolveSuggestionConflictUseCase:
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

    async def execute(self, command: ResolveSuggestionConflictCommand) -> SuggestionResult:
        action = _normalize_conflict_resolution_action(command.action)
        async with self._uow_factory() as uow:
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            payload = _conflict_review_payload(suggestion)
            if suggestion.status != SuggestionStatus.PENDING:
                raise MemoryConflictError("Only pending conflict suggestion can be resolved")
            now = self._clock.now()
            reason = _conflict_resolution_reason(
                action=action,
                reason=command.reason,
                fallback=suggestion.safe_reason,
            )

            if action == "reject_candidate":
                reviewed = _annotate_conflict_resolution(
                    suggestion,
                    action=action,
                    effect="keep_existing_fact",
                    now=now,
                    reason=reason,
                ).reject(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                await uow.commit()
                return SuggestionResult(suggestion=saved)

            if action == "expire_candidate":
                reviewed = _annotate_conflict_resolution(
                    suggestion,
                    action=action,
                    effect="hide_pending_suggestion",
                    now=now,
                    reason=reason,
                ).expire(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                await uow.commit()
                return SuggestionResult(suggestion=saved)

            if action in {
                "approve_candidate",
                "replace_existing_fact",
                "mark_existing_disputed",
            }:
                _ensure_conflict_candidate_has_independent_source(suggestion)

            conflict_fact = await _load_conflicting_fact_for_resolution(
                uow,
                suggestion=suggestion,
                payload=payload,
            )
            expected_version = _conflicting_fact_version(payload)
            if conflict_fact.version != expected_version:
                raise MemoryConflictError("Stale conflict fact version")

            if action == "approve_candidate":
                fact = MemoryFact.create(
                    fact_id=MemoryFactId(self._ids.new_id("fact")),
                    space_id=suggestion.space_id,
                    memory_scope_id=suggestion.memory_scope_id,
                    text=suggestion.candidate_text,
                    kind=suggestion.kind,
                    source_refs=suggestion.source_refs,
                    confidence=suggestion.confidence,
                    trust_level=suggestion.trust_level,
                    category=suggestion.category,
                    tags=suggestion.tags,
                    ttl_policy=suggestion.ttl_policy,
                    expires_at=suggestion.expires_at,
                    now=now,
                )
                fact = await uow.facts.create(fact)
                reviewed = _annotate_conflict_resolution(
                    suggestion,
                    action=action,
                    effect="create_new_fact_keep_conflicting_fact",
                    now=now,
                    reason=reason,
                    conflicting_fact=conflict_fact,
                    applied_fact=fact,
                ).approve(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                await _enqueue_fact_projection(uow, fact)
                await uow.commit()
                return SuggestionResult(
                    suggestion=saved,
                    fact=fact,
                    indexing_status="pending",
                )

            if action == "replace_existing_fact":
                if conflict_fact.status not in {FactStatus.ACTIVE, FactStatus.DISPUTED}:
                    raise MemoryConflictError("Conflict fact cannot be replaced")
                if (
                    _TRUST_RANK[suggestion.trust_level] < _TRUST_RANK[conflict_fact.trust_level]
                    and not command.force
                ):
                    raise MemoryConflictError("Weak suggestion cannot replace stronger fact")
                fact = conflict_fact.update(
                    expected_version=expected_version,
                    text=suggestion.candidate_text,
                    source_refs=suggestion.source_refs,
                    reason=reason,
                    category=suggestion.category,
                    tags=suggestion.tags,
                    ttl_policy=suggestion.ttl_policy,
                    expires_at=suggestion.expires_at,
                    now=now,
                )
                fact = await uow.facts.save(fact)
                reviewed = _annotate_conflict_resolution(
                    suggestion,
                    action=action,
                    effect="update_conflicting_fact_with_candidate",
                    now=now,
                    reason=reason,
                    conflicting_fact=conflict_fact,
                    applied_fact=fact,
                ).approve(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                await _enqueue_fact_projection(uow, fact)
                await uow.commit()
                return SuggestionResult(
                    suggestion=saved,
                    fact=fact,
                    indexing_status="pending",
                )

            fact = conflict_fact.mark_disputed(now=now)
            fact_changed = fact != conflict_fact
            if fact_changed:
                fact = await uow.facts.save(fact)
            reviewed = _annotate_conflict_resolution(
                suggestion,
                action=action,
                effect="mark_existing_fact_disputed_keep_candidate_as_evidence",
                now=now,
                reason=reason,
                conflicting_fact=conflict_fact,
                applied_fact=fact,
            ).approve(now=now, reason=reason)
            saved = await uow.suggestions.save(reviewed)
            if fact_changed:
                await _enqueue_fact_projection(uow, fact)
            await uow.commit()
            return SuggestionResult(
                suggestion=saved,
                fact=fact,
                indexing_status="pending",
            )


class ReviewSuggestionsBatchUseCase:
    def __init__(
        self,
        *,
        approve_suggestion: ApproveSuggestionUseCase,
        reject_suggestion: RejectSuggestionUseCase,
        expire_suggestion: ExpireSuggestionUseCase,
    ) -> None:
        self._approve_suggestion = approve_suggestion
        self._reject_suggestion = reject_suggestion
        self._expire_suggestion = expire_suggestion

    async def execute(self, command: ReviewSuggestionsBatchCommand) -> ReviewSuggestionsBatchResult:
        if not command.items:
            raise MemoryValidationError("Batch review requires at least one item")
        if len(command.items) > 50:
            raise MemoryValidationError("Batch review supports at most 50 items")
        _assert_unique_review_batch_suggestion_ids(command.items)

        results: list[ReviewSuggestionBatchItemResult] = []
        stopped = False
        for item in command.items:
            if item.action not in {"approve", "reject", "expire"}:
                raise MemoryValidationError("Unknown suggestion review action")
            try:
                result = await self._review_one(item)
                results.append(
                    ReviewSuggestionBatchItemResult(
                        suggestion_id=item.suggestion_id,
                        action=item.action,
                        status="applied",
                        result=result,
                    )
                )
            except MemoryError as exc:
                results.append(
                    ReviewSuggestionBatchItemResult(
                        suggestion_id=item.suggestion_id,
                        action=item.action,
                        status="failed",
                        error_code=exc.code,
                        error_message=_safe_batch_error_message(exc),
                    )
                )
                if not command.continue_on_error:
                    stopped = True
                    break

        failed = sum(1 for result in results if result.status == "failed")
        return ReviewSuggestionsBatchResult(
            applied=len(results) - failed,
            failed=failed,
            stopped=stopped,
            results=tuple(results),
        )

    async def _review_one(self, item: ReviewSuggestionBatchItemCommand) -> SuggestionResult:
        if item.action == "approve":
            return await self._approve_suggestion.execute(
                ApproveSuggestionCommand(
                    suggestion_id=item.suggestion_id,
                    reason=item.reason,
                    force=item.force,
                )
            )
        if item.action == "reject":
            return await self._reject_suggestion.execute(
                RejectSuggestionCommand(suggestion_id=item.suggestion_id, reason=item.reason)
            )
        return await self._expire_suggestion.execute(
            ExpireSuggestionCommand(suggestion_id=item.suggestion_id, reason=item.reason)
        )


def _assert_unique_review_batch_suggestion_ids(
    items: tuple[ReviewSuggestionBatchItemCommand, ...],
) -> None:
    seen: set[str] = set()
    for item in items:
        suggestion_id = item.suggestion_id.strip()
        if not suggestion_id:
            raise MemoryValidationError("Batch review requires suggestion_id")
        if suggestion_id in seen:
            raise MemoryValidationError("Batch review contains duplicate suggestion_id")
        seen.add(suggestion_id)


def _safe_reason(reason: str, auto_approve: bool, trust: TrustLevel) -> str:
    if auto_approve and trust == TrustLevel.LOW:
        return f"{reason}; auto_approve_blocked_low_trust"
    if auto_approve:
        return f"{reason}; auto_approve_requires_review"
    return reason


def _suggestion_fingerprint(
    *,
    command: CreateSuggestionCommand,
    operation: SuggestionOperation,
) -> str:
    raw = "|".join(
        (
            str(command.space_id),
            str(command.memory_scope_id),
            operation.value,
            command.target_fact_id or "",
            str(command.target_fact_version or ""),
            command.kind.value,
            command.category or "",
            command.ttl_policy or "",
            ",".join(command.tags),
            _normalize_candidate_text(command.candidate_text),
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _normalize_candidate_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _has_independent_source(suggestion: MemorySuggestion) -> bool:
    return any(ref.source_type not in _ASSISTANT_SOURCES for ref in suggestion.source_refs)


def _is_duplicate_fact_merge_review(suggestion: MemorySuggestion) -> bool:
    return (
        suggestion.operation == SuggestionOperation.REVIEW
        and suggestion.target_fact_id is not None
        and (suggestion.review_payload or {}).get("review_kind") == "duplicate_fact_merge"
    )


def _normalize_conflict_resolution_action(action: str) -> str:
    normalized = action.strip().lower()
    resolved = _CONFLICT_REVIEW_ACTION_ALIASES.get(normalized)
    if resolved is None:
        raise MemoryValidationError("Unknown conflict resolution action")
    return resolved


def _conflict_review_payload(suggestion: MemorySuggestion) -> dict[str, object]:
    payload = dict(suggestion.review_payload or {})
    if payload.get("review_kind") != CONFLICT_REVIEW_KIND:
        raise MemoryValidationError("Suggestion is not a conflict review")
    if not _payload_text(payload, "conflicting_fact_id"):
        raise MemoryValidationError("Conflict review requires conflicting_fact_id")
    _conflicting_fact_version(payload)
    return payload


def _conflicting_fact_version(payload: dict[str, object]) -> int:
    value = payload.get("conflicting_fact_version")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return int(value)
    raise MemoryValidationError("Conflict review requires conflicting_fact_version")


async def _load_conflicting_fact_for_resolution(
    uow: Any,
    *,
    suggestion: MemorySuggestion,
    payload: dict[str, object],
) -> MemoryFact:
    fact_id = _payload_text(payload, "conflicting_fact_id")
    if fact_id is None:
        raise MemoryValidationError("Conflict review requires conflicting_fact_id")
    fact = await uow.facts.get_for_update(fact_id)
    if fact is None:
        raise MemoryNotFoundError("Conflicting fact not found")
    if fact.space_id != suggestion.space_id or fact.memory_scope_id != suggestion.memory_scope_id:
        raise MemoryConflictError("Conflicting fact scope mismatch")
    if fact.status == FactStatus.DELETED:
        raise MemoryConflictError("Deleted conflict fact cannot be resolved")
    return fact


def _payload_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ensure_conflict_candidate_has_independent_source(suggestion: MemorySuggestion) -> None:
    if not _has_independent_source(suggestion):
        raise MemoryValidationError("Conflict resolution requires non-assistant source refs")


def _conflict_resolution_reason(
    *,
    action: str,
    reason: str | None,
    fallback: str,
) -> str:
    base = (reason or fallback or "conflict resolved").strip()
    text = f"conflict_resolution:{action}; {base}"
    return redact_sensitive_text(text)[:320]


def _annotate_conflict_resolution(
    suggestion: MemorySuggestion,
    *,
    action: str,
    effect: str,
    now: datetime,
    reason: str,
    conflicting_fact: MemoryFact | None = None,
    applied_fact: MemoryFact | None = None,
) -> MemorySuggestion:
    payload = dict(suggestion.review_payload or {})
    updates: dict[str, object] = {
        "resolved_conflict_action": action,
        "resolved_conflict_effect": effect,
        "resolved_at": now.isoformat(),
        "resolution_reason": redact_sensitive_text(reason)[:320],
    }
    if conflicting_fact is not None:
        updates["resolved_conflicting_fact_id"] = str(conflicting_fact.id)
        updates["resolved_conflicting_fact_version"] = conflicting_fact.version
        updates["resolved_conflicting_fact_status"] = conflicting_fact.status.value
    if applied_fact is not None:
        updates["resolved_fact_id"] = str(applied_fact.id)
        updates["resolved_fact_version"] = applied_fact.version
        updates["resolved_fact_status"] = applied_fact.status.value
    payload.update(updates)
    return replace(suggestion, review_payload=payload, updated_at=now)


async def _enqueue_fact_projection(uow: Any, fact: MemoryFact) -> None:
    await uow.outbox.enqueue(
        OutboxEvent(
            event_type="graph.upsert_fact",
            aggregate_type="fact",
            aggregate_id=str(fact.id),
            aggregate_version=fact.version,
            payload={"fact_id": str(fact.id), "version": fact.version},
        )
    )


def _batch_candidate_key(command: CreateSuggestionCommand) -> tuple[object, ...]:
    return (
        str(command.space_id),
        str(command.memory_scope_id),
        command.operation,
        command.target_fact_id or "",
        command.target_fact_version or 0,
        getattr(command.kind, "value", str(command.kind)),
        " ".join(command.candidate_text.strip().casefold().split()),
        command.category or "",
        tuple(command.tags),
    )


def _safe_batch_error_message(value: object) -> str:
    text = str(value).strip() or value.__class__.__name__
    return redact_sensitive_text(text)[:320]
