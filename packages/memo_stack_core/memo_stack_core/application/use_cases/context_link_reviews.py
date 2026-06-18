"""Review use cases for persisted context-link suggestions."""

from __future__ import annotations

from dataclasses import replace

from memo_stack_core.application.dto import (
    ContextLinkSuggestionResult,
    ListContextLinkSuggestionsQuery,
    ReviewContextLinkSuggestionBatchItemCommand,
    ReviewContextLinkSuggestionBatchItemResult,
    ReviewContextLinkSuggestionCommand,
    ReviewContextLinkSuggestionsBatchCommand,
    ReviewContextLinkSuggestionsBatchResult,
)
from memo_stack_core.application.sensitive_text import redact_sensitive_text
from memo_stack_core.application.use_cases.context_link_visibility import (
    assert_context_link_endpoint_visible,
)
from memo_stack_core.domain.assets import (
    ContextLinkSuggestionStatus,
    MemoryContextLink,
    MemoryContextLinkId,
    MemoryContextLinkSuggestion,
)
from memo_stack_core.domain.errors import MemoryError, MemoryNotFoundError, MemoryValidationError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort

MAX_CONTEXT_LINK_BATCH_REVIEW_ITEMS = 50
MAX_SAFE_BATCH_ERROR_CHARS = 320


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
                statuses=query.statuses,
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
            if suggestion.status != ContextLinkSuggestionStatus.PENDING and _has_approval_override(
                command
            ):
                raise MemoryValidationError(
                    "Context link suggestion overrides require pending suggestion"
                )

            if normalized_action == "reject":
                if _has_approval_override(command):
                    raise MemoryValidationError(
                        "Context link suggestion overrides require approve action"
                    )
                saved = await uow.context_link_suggestions.save(
                    suggestion.reject(now=now, reason=command.reason)
                )
                await uow.commit()
                return ContextLinkSuggestionResult(suggestion=saved)

            target_type, target_id = _review_target(suggestion, command)
            relation_type = (command.relation_type or suggestion.relation_type).strip()
            confidence = (command.confidence or suggestion.confidence).strip()
            link_reason = (command.link_reason or command.reason or suggestion.reason).strip()
            override_metadata = _review_override_metadata(
                suggestion=suggestion,
                target_type=target_type,
                target_id=target_id,
                relation_type=relation_type,
                confidence=confidence,
                link_reason=link_reason,
                link_reason_overridden=command.link_reason is not None,
            )

            await assert_context_link_endpoint_visible(
                uow,
                endpoint_type=suggestion.source_type,
                endpoint_id=suggestion.source_id,
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                role="source",
            )
            await assert_context_link_endpoint_visible(
                uow,
                endpoint_type=target_type,
                endpoint_id=target_id,
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                role="target",
            )
            existing_link = await uow.context_links.find_active(
                space_id=str(suggestion.space_id),
                memory_scope_id=str(suggestion.memory_scope_id),
                source_type=suggestion.source_type,
                source_id=suggestion.source_id,
                target_type=target_type,
                target_id=target_id,
                relation_type=relation_type,
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
                    target_type=target_type,
                    target_id=target_id,
                    relation_type=relation_type,
                    confidence=confidence,
                    reason=link_reason,
                    metadata={
                        **dict(suggestion.metadata),
                        "approved_from_suggestion_id": str(suggestion.id),
                        **override_metadata,
                    },
                    now=now,
                )
                link = await uow.context_links.create(link)
            reviewed_suggestion = _with_review_override_metadata(
                suggestion,
                override_metadata,
            )
            saved = await uow.context_link_suggestions.save(
                reviewed_suggestion.approve(now=now, reason=command.reason)
            )
            await uow.commit()
        return ContextLinkSuggestionResult(
            suggestion=saved,
            link=link,
            duplicate_link=duplicate_link,
        )


class ReviewContextLinkSuggestionsBatchUseCase:
    def __init__(
        self,
        *,
        review_context_link_suggestion: ReviewContextLinkSuggestionUseCase,
    ) -> None:
        self._review_context_link_suggestion = review_context_link_suggestion

    async def execute(
        self,
        command: ReviewContextLinkSuggestionsBatchCommand,
    ) -> ReviewContextLinkSuggestionsBatchResult:
        if not command.items:
            raise MemoryValidationError("Context link batch review requires at least one item")
        if len(command.items) > MAX_CONTEXT_LINK_BATCH_REVIEW_ITEMS:
            raise MemoryValidationError("Context link batch review supports at most 50 items")
        _assert_unique_batch_suggestion_ids(command.items)

        results: list[ReviewContextLinkSuggestionBatchItemResult] = []
        stopped = False
        for item in command.items:
            if item.action.strip().lower() not in {"approve", "reject"}:
                raise MemoryValidationError("Unknown context link suggestion review action")
            try:
                result = await self._review_one(item)
                results.append(
                    ReviewContextLinkSuggestionBatchItemResult(
                        suggestion_id=item.suggestion_id,
                        action=item.action,
                        status="applied",
                        result=result,
                    )
                )
            except MemoryError as exc:
                results.append(
                    ReviewContextLinkSuggestionBatchItemResult(
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
        return ReviewContextLinkSuggestionsBatchResult(
            applied=len(results) - failed,
            failed=failed,
            stopped=stopped,
            results=tuple(results),
        )

    async def _review_one(
        self,
        item: ReviewContextLinkSuggestionBatchItemCommand,
    ) -> ContextLinkSuggestionResult:
        return await self._review_context_link_suggestion.execute(
            ReviewContextLinkSuggestionCommand(
                suggestion_id=item.suggestion_id,
                action=item.action,
                reason=item.reason,
                target_type=item.target_type,
                target_id=item.target_id,
                relation_type=item.relation_type,
                confidence=item.confidence,
                link_reason=item.link_reason,
            )
        )


def _has_approval_override(command: ReviewContextLinkSuggestionCommand) -> bool:
    return any(
        value is not None
        for value in (
            command.target_type,
            command.target_id,
            command.relation_type,
            command.confidence,
            command.link_reason,
        )
    )


def _assert_unique_batch_suggestion_ids(
    items: tuple[ReviewContextLinkSuggestionBatchItemCommand, ...],
) -> None:
    seen: set[str] = set()
    for item in items:
        suggestion_id = item.suggestion_id.strip()
        if not suggestion_id:
            raise MemoryValidationError("Context link batch review requires suggestion_id")
        if suggestion_id in seen:
            raise MemoryValidationError(
                "Context link batch review contains duplicate suggestion_id"
            )
        seen.add(suggestion_id)


def _review_target(
    suggestion: MemoryContextLinkSuggestion,
    command: ReviewContextLinkSuggestionCommand,
) -> tuple[str, str]:
    target_type = command.target_type.strip() if command.target_type is not None else ""
    target_id = command.target_id.strip() if command.target_id is not None else ""
    if bool(target_type) != bool(target_id):
        raise MemoryValidationError("Context link override target requires type and id")
    if target_type and target_id:
        return target_type, target_id
    return suggestion.target_type, suggestion.target_id


def _review_override_metadata(
    *,
    suggestion: MemoryContextLinkSuggestion,
    target_type: str,
    target_id: str,
    relation_type: str,
    confidence: str,
    link_reason: str,
    link_reason_overridden: bool,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if (
        target_type != suggestion.target_type
        or target_id != suggestion.target_id
        or relation_type != suggestion.relation_type
        or confidence != suggestion.confidence
        or (link_reason_overridden and link_reason != suggestion.reason)
    ):
        metadata["approved_override"] = True
        metadata["original_target_type"] = suggestion.target_type
        metadata["original_target_id"] = suggestion.target_id
        metadata["original_relation_type"] = suggestion.relation_type
        metadata["original_confidence"] = suggestion.confidence
        metadata["approved_target_type"] = target_type
        metadata["approved_target_id"] = target_id
        metadata["approved_relation_type"] = relation_type
        metadata["approved_confidence"] = confidence
        metadata["approved_link_reason"] = redact_sensitive_text(link_reason)[:320]
    return metadata


def _with_review_override_metadata(
    suggestion: MemoryContextLinkSuggestion,
    metadata: dict[str, object],
) -> MemoryContextLinkSuggestion:
    if not metadata:
        return suggestion
    return replace(
        suggestion,
        metadata={**dict(suggestion.metadata), **metadata},
    )


def _safe_batch_error_message(value: object) -> str:
    text = str(value).strip() or value.__class__.__name__
    return redact_sensitive_text(text)[:MAX_SAFE_BATCH_ERROR_CHARS]
