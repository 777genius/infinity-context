"""Review-gated memory suggestions."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    ApproveSuggestionCommand,
    CreateSuggestionCommand,
    ExpireSuggestionCommand,
    ListSuggestionsQuery,
    RejectSuggestionCommand,
    ReviewSuggestionBatchItemCommand,
    ReviewSuggestionBatchItemResult,
    ReviewSuggestionsBatchCommand,
    ReviewSuggestionsBatchResult,
    SuggestionResult,
)
from memo_stack_core.domain.entities import (
    Confidence,
    MemoryFact,
    MemoryFactId,
    MemorySuggestion,
    MemorySuggestionId,
    SuggestionOperation,
    TrustLevel,
)
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

_TRUST_RANK = {TrustLevel.LOW: 1, TrustLevel.MEDIUM: 2, TrustLevel.HIGH: 3}
_ASSISTANT_SOURCES = {"ai_response", "assistant_answer", "assistant_summary"}


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
        suggestion = MemorySuggestion.create(
            suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
            space_id=command.space_id,
            profile_id=command.profile_id,
            candidate_text=command.candidate_text,
            kind=command.kind,
            source_refs=command.source_refs,
            safe_reason=_safe_reason(command.safe_reason, command.auto_approve, trust),
            confidence=Confidence(command.confidence),
            trust_level=trust,
            target_fact_id=MemoryFactId(command.target_fact_id) if command.target_fact_id else None,
            target_fact_version=command.target_fact_version,
            operation=SuggestionOperation(command.operation),
            category=command.category,
            tags=command.tags,
            ttl_policy=command.ttl_policy,
            expires_at=command.expires_at,
            expiry_reason=command.expiry_reason,
            created_from_capture_id=command.created_from_capture_id,
            candidate_fingerprint=command.candidate_fingerprint,
            review_payload=command.review_payload,
            now=now,
        )
        async with self._uow_factory() as uow:
            saved = await uow.suggestions.create(suggestion)
            await uow.commit()
        return SuggestionResult(suggestion=saved)


class ListSuggestionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListSuggestionsQuery) -> list[MemorySuggestion]:
        async with self._uow_factory() as uow:
            return await uow.suggestions.list_for_scope(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
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

            now = self._clock.now()
            fact: MemoryFact
            if suggestion.target_fact_id:
                current = await uow.facts.get_for_update(str(suggestion.target_fact_id))
                if (
                    current is None
                    or current.space_id != suggestion.space_id
                    or current.profile_id != suggestion.profile_id
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
                    profile_id=suggestion.profile_id,
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
                        error_message=str(exc),
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


def _safe_reason(reason: str, auto_approve: bool, trust: TrustLevel) -> str:
    if auto_approve and trust == TrustLevel.LOW:
        return f"{reason}; auto_approve_blocked_low_trust"
    if auto_approve:
        return f"{reason}; auto_approve_requires_review"
    return reason


def _has_independent_source(suggestion: MemorySuggestion) -> bool:
    return any(ref.source_type not in _ASSISTANT_SOURCES for ref in suggestion.source_refs)
