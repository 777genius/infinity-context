"""Review-gated memory suggestions."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from infinity_context_core.application.code_scope_metadata import code_scope_from_metadata
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
from infinity_context_core.application.review_payloads import (
    CONFLICT_REVIEW_KIND,
    DUPLICATE_FACT_MERGE_REVIEW_KIND,
)
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.application.suggestion_fact_resolution import (
    annotate_canonical_review_resolution,
    annotate_suggestion_reviewer,
    apply_reviewed_fact_mutation,
    authorize_suggestion_review,
    reviewed_fact_decision,
    targeted_suggestion_resolution_kind,
)
from infinity_context_core.application.suggestion_resolution_replay import (
    load_suggestion_resolution_replay,
    new_suggestion_resolution_receipt,
    suggestion_resolution_identity,
)
from infinity_context_core.domain.entities import (
    Confidence,
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
from infinity_context_core.features.review_governance.public import (
    SuggestionResolutionUnitOfWorkFactoryPort,
    SuggestionReviewScope,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

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
            raise MemoryValidationError("Target fact version is required for targeted suggestion")
        candidate_fingerprint = command.candidate_fingerprint or _suggestion_fingerprint(
            command=command,
            operation=operation,
        )
        suggestion = MemorySuggestion.create(
            suggestion_id=MemorySuggestionId(self._ids.new_id("sug")),
            space_id=command.space_id,
            memory_scope_id=command.memory_scope_id,
            thread_id=command.thread_id,
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
        if (
            suggestion.target_fact_id is not None
            and suggestion.operation is not SuggestionOperation.DELETE
            and not _is_conflict_or_duplicate_review(suggestion)
        ):
            targeted_suggestion_resolution_kind(suggestion)
        try:
            async with self._uow_factory() as uow:
                duplicate = await uow.suggestions.find_pending_duplicate(
                    space_id=str(command.space_id),
                    memory_scope_id=str(command.memory_scope_id),
                    thread_id=str(command.thread_id) if command.thread_id is not None else None,
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
                thread_id=str(command.thread_id) if command.thread_id is not None else None,
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
        uow_factory: SuggestionResolutionUnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: ApproveSuggestionCommand) -> SuggestionResult:
        operation = "approve"
        idempotency_key, request_fingerprint = suggestion_resolution_identity(
            suggestion_id=command.suggestion_id,
            operation=operation,
            idempotency_key=command.idempotency_key,
            request={
                "reason": command.reason,
                "force": command.force,
                "actor_id": command.actor_id,
            },
        )
        async with self._uow_factory() as uow:
            replay = await load_suggestion_resolution_replay(
                uow.suggestion_resolution_receipts,
                suggestion_id=command.suggestion_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                review_scope=command.review_scope,
            )
            if replay is not None:
                return replay
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            replay = await load_suggestion_resolution_replay(
                uow.suggestion_resolution_receipts,
                suggestion_id=command.suggestion_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                review_scope=command.review_scope,
            )
            if replay is not None:
                return replay
            authorize_suggestion_review(suggestion, command.review_scope)
            if not _has_independent_source(suggestion):
                raise MemoryValidationError(
                    "Suggestion approval requires non-assistant source refs"
                )
            if suggestion.target_fact_id and suggestion.target_fact_version is None:
                raise MemoryValidationError(
                    "Target fact version is required for targeted suggestion approval"
                )
            now = self._clock.now()
            decision = reviewed_fact_decision(
                suggestion,
                actor_id=command.actor_id,
                reason=command.reason or suggestion.safe_reason,
                now=now,
                allow_weaker=command.force,
            )
            if suggestion.target_fact_id is None:
                if suggestion.operation == SuggestionOperation.DELETE:
                    raise MemoryValidationError("Delete suggestion requires target fact")
                outcome = await apply_reviewed_fact_mutation(uow.reviewed_facts.remember(decision))
                resolution_kind = "remember"
            elif suggestion.operation == SuggestionOperation.DELETE:
                outcome = await apply_reviewed_fact_mutation(uow.reviewed_facts.forget(decision))
                resolution_kind = "forget"
            elif _is_duplicate_fact_merge_review(suggestion):
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.attach_evidence(decision)
                )
                resolution_kind = "attach_evidence"
            else:
                resolution_kind = targeted_suggestion_resolution_kind(suggestion)
                if resolution_kind == "correction":
                    outcome = await apply_reviewed_fact_mutation(
                        uow.reviewed_facts.correct(decision)
                    )
                else:
                    outcome = await apply_reviewed_fact_mutation(
                        uow.reviewed_facts.create_and_supersede(decision)
                    )

            reviewed = annotate_canonical_review_resolution(
                suggestion,
                outcome=outcome,
                resolution_kind=resolution_kind,
                actor_id=command.actor_id,
                now=now,
            ).approve(now=now, reason=command.reason)
            saved_suggestion = await uow.suggestions.save(reviewed)
            result = SuggestionResult(
                suggestion=saved_suggestion,
                fact=outcome.primary_fact,
                indexing_status="pending",
            )
            await uow.suggestion_resolution_receipts.create(
                new_suggestion_resolution_receipt(
                    result=result,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    outcome=outcome,
                    created_at=now,
                )
            )
            await uow.commit()
        return result


class RejectSuggestionUseCase:
    def __init__(
        self,
        *,
        uow_factory: SuggestionResolutionUnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RejectSuggestionCommand) -> SuggestionResult:
        return await _resolve_terminal_suggestion(
            uow_factory=self._uow_factory,
            clock=self._clock,
            command=command,
            operation="reject",
        )


class ExpireSuggestionUseCase:
    def __init__(
        self,
        *,
        uow_factory: SuggestionResolutionUnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ExpireSuggestionCommand) -> SuggestionResult:
        return await _resolve_terminal_suggestion(
            uow_factory=self._uow_factory,
            clock=self._clock,
            command=command,
            operation="expire",
        )


async def _resolve_terminal_suggestion(
    *,
    uow_factory: SuggestionResolutionUnitOfWorkFactoryPort,
    clock: ClockPort,
    command: RejectSuggestionCommand | ExpireSuggestionCommand,
    operation: str,
) -> SuggestionResult:
    idempotency_key, request_fingerprint = suggestion_resolution_identity(
        suggestion_id=command.suggestion_id,
        operation=operation,
        idempotency_key=command.idempotency_key,
        request={"reason": command.reason, "actor_id": command.actor_id},
    )
    async with uow_factory() as uow:
        replay = await load_suggestion_resolution_replay(
            uow.suggestion_resolution_receipts,
            suggestion_id=command.suggestion_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            review_scope=command.review_scope,
        )
        if replay is not None:
            return replay
        suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
        if suggestion is None:
            raise MemoryNotFoundError("Suggestion not found")
        replay = await load_suggestion_resolution_replay(
            uow.suggestion_resolution_receipts,
            suggestion_id=command.suggestion_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            review_scope=command.review_scope,
        )
        if replay is not None:
            return replay
        authorize_suggestion_review(suggestion, command.review_scope)
        now = clock.now()
        reviewed = annotate_suggestion_reviewer(
            suggestion,
            actor_id=command.actor_id,
            now=now,
        )
        resolved = (
            reviewed.reject(now=now, reason=command.reason)
            if operation == "reject"
            else reviewed.expire(now=now, reason=command.reason)
        )
        result = SuggestionResult(suggestion=await uow.suggestions.save(resolved))
        await uow.suggestion_resolution_receipts.create(
            new_suggestion_resolution_receipt(
                result=result,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                outcome=None,
                created_at=now,
            )
        )
        await uow.commit()
        return result


class ResolveSuggestionConflictUseCase:
    def __init__(
        self,
        *,
        uow_factory: SuggestionResolutionUnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: ResolveSuggestionConflictCommand) -> SuggestionResult:
        action = _normalize_conflict_resolution_action(command.action)
        operation = f"resolve_conflict:{action}"
        idempotency_key, request_fingerprint = suggestion_resolution_identity(
            suggestion_id=command.suggestion_id,
            operation=operation,
            idempotency_key=command.idempotency_key,
            request={
                "action": action,
                "reason": command.reason,
                "force": command.force,
                "actor_id": command.actor_id,
            },
        )
        async with self._uow_factory() as uow:
            replay = await load_suggestion_resolution_replay(
                uow.suggestion_resolution_receipts,
                suggestion_id=command.suggestion_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                review_scope=command.review_scope,
            )
            if replay is not None:
                return replay
            suggestion = await uow.suggestions.get_for_update(command.suggestion_id)
            if suggestion is None:
                raise MemoryNotFoundError("Suggestion not found")
            replay = await load_suggestion_resolution_replay(
                uow.suggestion_resolution_receipts,
                suggestion_id=command.suggestion_id,
                operation=operation,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                review_scope=command.review_scope,
            )
            if replay is not None:
                return replay
            authorize_suggestion_review(suggestion, command.review_scope)
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
                    annotate_suggestion_reviewer(
                        suggestion,
                        actor_id=command.actor_id,
                        now=now,
                    ),
                    action=action,
                    effect="keep_existing_fact",
                    now=now,
                    reason=reason,
                ).reject(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                result = SuggestionResult(suggestion=saved)
                await uow.suggestion_resolution_receipts.create(
                    new_suggestion_resolution_receipt(
                        result=result,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        outcome=None,
                        created_at=now,
                    )
                )
                await uow.commit()
                return result

            if action == "expire_candidate":
                reviewed = _annotate_conflict_resolution(
                    annotate_suggestion_reviewer(
                        suggestion,
                        actor_id=command.actor_id,
                        now=now,
                    ),
                    action=action,
                    effect="hide_pending_suggestion",
                    now=now,
                    reason=reason,
                ).expire(now=now, reason=reason)
                saved = await uow.suggestions.save(reviewed)
                result = SuggestionResult(suggestion=saved)
                await uow.suggestion_resolution_receipts.create(
                    new_suggestion_resolution_receipt(
                        result=result,
                        operation=operation,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        outcome=None,
                        created_at=now,
                    )
                )
                await uow.commit()
                return result

            if action in {
                "approve_candidate",
                "replace_existing_fact",
                "mark_existing_disputed",
            }:
                _ensure_conflict_candidate_has_independent_source(suggestion)

            expected_version = _conflicting_fact_version(payload)
            conflicting_fact_id = _payload_text(payload, "conflicting_fact_id")
            if conflicting_fact_id is None:
                raise MemoryValidationError("Conflict review requires conflicting_fact_id")
            decision = reviewed_fact_decision(
                suggestion,
                actor_id=command.actor_id,
                reason=reason,
                now=now,
                allow_weaker=command.force,
                target_fact_id=conflicting_fact_id,
                target_fact_version=expected_version,
            )
            if action == "replace_existing_fact":
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.create_and_supersede(decision)
                )
                resolution_kind = "supersede"
            elif action == "approve_candidate":
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.remember(replace(decision, target=None))
                )
                resolution_kind = "remember_separate"
            else:
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.create_and_dispute(decision)
                )
                resolution_kind = "dispute"
            reviewed = annotate_canonical_review_resolution(
                _annotate_conflict_resolution(
                    suggestion,
                    action=action,
                    effect=(
                        "create_successor_and_supersede_conflicting_fact"
                        if action == "replace_existing_fact"
                        else (
                            "create_new_fact_keep_conflicting_fact"
                            if action == "approve_candidate"
                            else "create_challenger_and_dispute_both_facts"
                        )
                    ),
                    now=now,
                    reason=reason,
                ),
                outcome=outcome,
                resolution_kind=resolution_kind,
                actor_id=command.actor_id,
                now=now,
            ).approve(now=now, reason=reason)
            saved = await uow.suggestions.save(reviewed)
            result = SuggestionResult(
                suggestion=saved,
                fact=outcome.primary_fact,
                indexing_status="pending",
            )
            await uow.suggestion_resolution_receipts.create(
                new_suggestion_resolution_receipt(
                    result=result,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    outcome=outcome,
                    created_at=now,
                )
            )
            await uow.commit()
            return result


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
                result = await self._review_one(
                    item,
                    actor_id=command.actor_id,
                    review_scope=command.review_scope,
                )
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

    async def _review_one(
        self,
        item: ReviewSuggestionBatchItemCommand,
        *,
        actor_id: str,
        review_scope: SuggestionReviewScope | None,
    ) -> SuggestionResult:
        if item.action == "approve":
            return await self._approve_suggestion.execute(
                ApproveSuggestionCommand(
                    suggestion_id=item.suggestion_id,
                    reason=item.reason,
                    force=item.force,
                    actor_id=actor_id,
                    review_scope=review_scope,
                    idempotency_key=item.idempotency_key,
                )
            )
        if item.action == "reject":
            return await self._reject_suggestion.execute(
                RejectSuggestionCommand(
                    suggestion_id=item.suggestion_id,
                    reason=item.reason,
                    actor_id=actor_id,
                    review_scope=review_scope,
                    idempotency_key=item.idempotency_key,
                )
            )
        return await self._expire_suggestion.execute(
            ExpireSuggestionCommand(
                suggestion_id=item.suggestion_id,
                reason=item.reason,
                actor_id=actor_id,
                review_scope=review_scope,
                idempotency_key=item.idempotency_key,
            )
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
    repository_id, code_scope_id = code_scope_from_metadata(
        command.review_payload or {},
        source="Suggestion",
    )
    raw = "|".join(
        (
            str(command.space_id),
            str(command.memory_scope_id),
            operation.value,
            repository_id or "",
            code_scope_id or "",
            str(command.thread_id or ""),
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
        and (suggestion.review_payload or {}).get("review_kind") == DUPLICATE_FACT_MERGE_REVIEW_KIND
    )


def _is_conflict_or_duplicate_review(suggestion: MemorySuggestion) -> bool:
    return (suggestion.review_payload or {}).get("review_kind") in {
        CONFLICT_REVIEW_KIND,
        DUPLICATE_FACT_MERGE_REVIEW_KIND,
    }


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
) -> MemorySuggestion:
    payload = dict(suggestion.review_payload or {})
    updates: dict[str, object] = {
        "resolved_conflict_action": action,
        "resolved_conflict_effect": effect,
        "resolved_at": now.isoformat(),
        "resolution_reason": redact_sensitive_text(reason)[:320],
    }
    payload.update(updates)
    return replace(suggestion, review_payload=payload, updated_at=now)


def _batch_candidate_key(command: CreateSuggestionCommand) -> tuple[object, ...]:
    return (
        str(command.space_id),
        str(command.memory_scope_id),
        str(command.thread_id or ""),
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
