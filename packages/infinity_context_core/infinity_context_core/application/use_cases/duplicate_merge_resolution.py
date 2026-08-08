"""Resolve duplicate fact merge reviews."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from infinity_context_core.application.dto import ResolveDuplicateMergeCommand, SuggestionResult
from infinity_context_core.application.review_payloads import DUPLICATE_FACT_MERGE_REVIEW_KIND
from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.application.suggestion_fact_resolution import (
    annotate_canonical_review_resolution,
    annotate_suggestion_reviewer,
    apply_reviewed_fact_mutation,
    authorize_suggestion_review,
    reviewed_fact_decision,
)
from infinity_context_core.application.suggestion_resolution_replay import (
    load_suggestion_resolution_replay,
    new_suggestion_resolution_receipt,
    suggestion_resolution_identity,
)
from infinity_context_core.domain.entities import (
    MemorySuggestion,
    SuggestionStatus,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.features.review_governance.public import (
    SuggestionResolutionUnitOfWorkFactoryPort,
)
from infinity_context_core.ports.clock import ClockPort
from infinity_context_core.ports.ids import IdGeneratorPort

_ASSISTANT_SOURCES = {"ai_response", "assistant_answer", "assistant_summary"}
_DUPLICATE_MERGE_ACTION_ALIASES = {
    "merge_source_refs": "merge_source_refs",
    "merge": "merge_source_refs",
    "approve_merge": "merge_source_refs",
    "keep_separate_fact": "keep_separate_fact",
    "keep_separate": "keep_separate_fact",
    "create_separate_fact": "keep_separate_fact",
    "reject_candidate": "reject_candidate",
    "reject_duplicate": "reject_candidate",
    "expire_candidate": "expire_candidate",
    "expire_duplicate": "expire_candidate",
}


class ResolveDuplicateMergeUseCase:
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

    async def execute(self, command: ResolveDuplicateMergeCommand) -> SuggestionResult:
        action = _normalize_duplicate_merge_action(command.action)
        operation = f"resolve_duplicate:{action}"
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
            payload = _duplicate_fact_merge_review_payload(suggestion)
            if suggestion.status != SuggestionStatus.PENDING:
                raise MemoryConflictError("Only pending duplicate merge suggestion can be resolved")
            now = self._clock.now()
            reason = _duplicate_merge_resolution_reason(
                action=action,
                reason=command.reason,
                fallback=suggestion.safe_reason,
            )

            if action == "reject_candidate":
                saved = await uow.suggestions.save(
                    _annotate_duplicate_merge_resolution(
                        annotate_suggestion_reviewer(
                            suggestion,
                            actor_id=command.actor_id,
                            now=now,
                        ),
                        action=action,
                        effect="keep_existing_fact_without_candidate_source_refs",
                        now=now,
                        reason=reason,
                    ).reject(now=now, reason=reason)
                )
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
                saved = await uow.suggestions.save(
                    _annotate_duplicate_merge_resolution(
                        annotate_suggestion_reviewer(
                            suggestion,
                            actor_id=command.actor_id,
                            now=now,
                        ),
                        action=action,
                        effect="hide_pending_duplicate_merge_review",
                        now=now,
                        reason=reason,
                    ).expire(now=now, reason=reason)
                )
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

            _ensure_duplicate_candidate_has_independent_source(suggestion)
            expected_version = _duplicate_merge_target_version(payload, suggestion)
            decision = reviewed_fact_decision(
                suggestion,
                actor_id=command.actor_id,
                reason=reason,
                now=now,
                allow_weaker=command.force,
                target_fact_version=expected_version,
            )
            if action == "merge_source_refs":
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.attach_evidence(decision)
                )
                resolution_kind = "attach_evidence"
                effect = "merge_source_refs_into_existing_fact"
            else:
                outcome = await apply_reviewed_fact_mutation(
                    uow.reviewed_facts.remember(replace(decision, target=None))
                )
                resolution_kind = "remember_separate"
                effect = "create_new_fact_keep_existing_fact"
            reviewed = annotate_canonical_review_resolution(
                _annotate_duplicate_merge_resolution(
                    suggestion,
                    action=action,
                    effect=effect,
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


def _normalize_duplicate_merge_action(action: str) -> str:
    normalized = action.strip().lower()
    resolved = _DUPLICATE_MERGE_ACTION_ALIASES.get(normalized)
    if resolved is None:
        raise MemoryValidationError("Unknown duplicate merge resolution action")
    return resolved


def _duplicate_fact_merge_review_payload(suggestion: MemorySuggestion) -> dict[str, object]:
    payload = dict(suggestion.review_payload or {})
    if payload.get("review_kind") != DUPLICATE_FACT_MERGE_REVIEW_KIND:
        raise MemoryValidationError("Suggestion is not a duplicate merge review")
    if suggestion.target_fact_id is None:
        raise MemoryValidationError("Duplicate merge review requires target_fact_id")
    _duplicate_merge_target_version(payload, suggestion)
    return payload


def _duplicate_merge_target_version(
    payload: dict[str, object],
    suggestion: MemorySuggestion,
) -> int:
    value = payload.get("duplicate_fact_version")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return int(value)
    if suggestion.target_fact_version is not None and suggestion.target_fact_version > 0:
        return suggestion.target_fact_version
    raise MemoryValidationError("Duplicate merge review requires duplicate_fact_version")


def _ensure_duplicate_candidate_has_independent_source(suggestion: MemorySuggestion) -> None:
    if not any(ref.source_type not in _ASSISTANT_SOURCES for ref in suggestion.source_refs):
        raise MemoryValidationError("Duplicate merge resolution requires non-assistant source refs")


def _duplicate_merge_resolution_reason(
    *,
    action: str,
    reason: str | None,
    fallback: str,
) -> str:
    base = (reason or fallback or "duplicate merge resolved").strip()
    text = f"duplicate_merge_resolution:{action}; {base}"
    return redact_sensitive_text(text)[:320]


def _annotate_duplicate_merge_resolution(
    suggestion: MemorySuggestion,
    *,
    action: str,
    effect: str,
    now: datetime,
    reason: str,
) -> MemorySuggestion:
    payload = dict(suggestion.review_payload or {})
    updates: dict[str, object] = {
        "resolved_duplicate_action": action,
        "resolved_duplicate_effect": effect,
        "resolved_at": now.isoformat(),
        "resolution_reason": redact_sensitive_text(reason)[:320],
    }
    payload.update(updates)
    return replace(suggestion, review_payload=payload, updated_at=now)
