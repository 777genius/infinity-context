"""Suggestion and proposal application service operations for MCP memory tools."""

from __future__ import annotations

from typing import Any

from infinity_context_mcp.application.normalization import (
    normalize_optional_label as _normalize_optional_label,
)
from infinity_context_mcp.application.review_batch import normalize_review_batch_items
from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_constants import (
    CONFIDENCE_VALUES,
    MEMORY_KINDS,
    SUGGESTION_OPERATIONS,
    SUGGESTION_STATUSES,
    TRUST_VALUES,
    UNCERTAIN_EVIDENCE_MARKERS,
)
from infinity_context_mcp.application.service_duplicates import MemoryToolDuplicateMixin
from infinity_context_mcp.application.service_helpers import (
    candidate_fingerprint,
    ensure_bool,
    ensure_choice,
    meaningful_terms,
    normalize_candidate,
    stable_key,
)
from infinity_context_mcp.application.service_helpers import (
    candidate_result as build_candidate_result,
)
from infinity_context_mcp.application.suggest_batch import normalize_suggest_batch_items
from infinity_context_mcp.domain.models import (
    MemoryCandidateOperation,
    MemoryGatewayError,
    MemoryScope,
    MemorySuggestBatchItemInput,
    MemoryUpdateCandidateInput,
    SourceRef,
    public_error_code,
    safe_message,
)
from infinity_context_mcp.domain.policy import MemoryPolicyOperation


class MemoryToolSuggestionService(MemoryToolDuplicateMixin, MemoryToolApplicationServiceBase):
    async def suggest_fact(
        self,
        *,
        candidate_text: str,
        kind: str = "note",
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        confidence: str = "medium",
        trust_level: str = "medium",
        safe_reason: str = "mcp_agent_suggestion_requires_review",
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_choice("kind", kind, MEMORY_KINDS)
            ensure_choice("confidence", confidence, CONFIDENCE_VALUES)
            ensure_choice("trust_level", trust_level, TRUST_VALUES)
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            source = self._source_ref(
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                fallback_seed=f"suggest:{scope}:{kind}:{candidate_text}",
            )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.SUGGEST,
                text=candidate_text,
                source_type=source.source_type,
            )
            payload = await self._gateway.create_suggestion(
                scope=scope,
                candidate_text=candidate_text,
                kind=kind,
                source_refs=[source],
                confidence=confidence,
                trust_level=trust_level,
                safe_reason=safe_reason,
            )
            return self._ok(
                "Suggestion created for review. It will not affect context until approved.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["created_suggestion"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def suggest_facts_batch(
        self,
        *,
        items: list[MemorySuggestBatchItemInput | dict[str, Any]],
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_bool("continue_on_error", continue_on_error)
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            payload_items, policy_text = normalize_suggest_batch_items(
                items=items,
                scope=scope,
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                source_ref_factory=lambda kind, source, quote, seed: self._source_ref(
                    source_type=kind,
                    source_id=source,
                    quote_preview=quote,
                    fallback_seed=seed,
                ),
            )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.SUGGEST,
                text=policy_text,
                source_type=source_type,
            )
            payload = await self._gateway.create_suggestions_batch(
                scope=scope,
                items=payload_items,
                continue_on_error=continue_on_error,
            )
            data = payload.get("data", payload)
            failed = int(data.get("failed", 0)) if isinstance(data, dict) else 0
            return self._ok(
                "Suggestion batch created for review."
                if failed == 0
                else "Suggestion batch finished with item failures.",
                data=data,
                policy=self._policy_payload(policy),
                side_effects=["created_suggestions_batch"],
                degraded=failed > 0,
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def propose_updates(
        self,
        *,
        candidates: list[MemoryUpdateCandidateInput | dict[str, Any]],
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        dry_run: bool = False,
        user_confirmed: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_bool("dry_run", dry_run)
            ensure_bool("user_confirmed", user_confirmed)
            if not candidates:
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.input_too_large",
                    message="At least one candidate is required",
                    retryable=False,
                )
            if len(candidates) > 30:
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.input_too_large",
                    message="At most 30 candidates are allowed",
                    retryable=False,
                )
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            seen: set[str] = set()
            result: dict[str, list[dict[str, Any]]] = {
                "accepted_suggestions": [],
                "direct_writes": [],
                "duplicates": [],
                "conflicts": [],
                "unsafe_rejected": [],
                "needs_review": [],
            }
            side_effects: list[str] = []
            warnings: list[str] = []
            total_chars = 0
            touched_targets: set[str] = set()
            for index, raw_candidate in enumerate(candidates):
                candidate = MemoryUpdateCandidateInput.model_validate(raw_candidate)
                total_chars += len(candidate.text)
                if total_chars > 60_000:
                    raise MemoryGatewayError(
                        status_code=400,
                        code="infinity_context_mcp.validation.input_too_large",
                        message="Candidate text exceeds the 60000 character batch limit",
                        retryable=False,
                    )
                operation = candidate.operation
                if operation == MemoryCandidateOperation.UNKNOWN:
                    operation = MemoryCandidateOperation.REMEMBER
                if (
                    operation in {MemoryCandidateOperation.UPDATE, MemoryCandidateOperation.FORGET}
                    and candidate.target_fact_id
                ):
                    target_key = f"{operation.value}:{candidate.target_fact_id}"
                    if target_key in touched_targets:
                        result["conflicts"].append(
                            build_candidate_result(
                                index,
                                "conflict",
                                "infinity_context_mcp.conflict.same_target_in_batch",
                                text=candidate.text,
                                target_fact_id=candidate.target_fact_id,
                            )
                        )
                        continue
                    touched_targets.add(target_key)
                candidate_key = candidate_fingerprint(
                    scope=scope,
                    candidate=candidate,
                    source_id=source_id,
                )
                if candidate_key in seen:
                    result["duplicates"].append(
                        build_candidate_result(
                            index,
                            "duplicate",
                            "infinity_context_mcp.duplicate.same_batch",
                            text=candidate.text,
                        )
                    )
                    continue
                seen.add(candidate_key)
                try:
                    candidate_result = await self._process_candidate(
                        candidate_index=index,
                        candidate=candidate,
                        scope=scope,
                        source_type=source_type,
                        source_id=source_id,
                        quote_preview=candidate.evidence_quote or quote_preview,
                        dry_run=dry_run,
                        user_confirmed=user_confirmed,
                    )
                except MemoryGatewayError as exc:
                    decision_code = public_error_code(exc.code, status_code=exc.status_code)
                    bucket = (
                        "conflicts"
                        if decision_code.startswith("infinity_context_mcp.conflict.")
                        else "unsafe_rejected"
                    )
                    result[bucket].append(
                        build_candidate_result(
                            index,
                            "conflict" if bucket == "conflicts" else "unsafe_rejected",
                            decision_code,
                            text=candidate.text,
                            target_fact_id=candidate.target_fact_id,
                            retryable=exc.retryable,
                            message=safe_message(exc.message),
                        )
                    )
                    continue
                bucket = str(candidate_result.pop("_bucket"))
                side_effect = candidate_result.pop("_side_effect", None)
                result[bucket].append(candidate_result)
                if side_effect:
                    side_effects.append(str(side_effect))
            return self._ok(
                "Memory proposal processed.",
                data=result,
                policy={"decision": "processed_proposal_batch"},
                side_effects=side_effects,
                warnings=warnings,
            )

        return await self._guard(action)

    async def list_suggestions(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "pending",
        operation: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                ensure_choice("status", status, SUGGESTION_STATUSES)
            if operation is not None:
                ensure_choice("operation", operation, SUGGESTION_OPERATIONS)
            payload = await self._gateway.list_suggestions(
                scope=self._scope(space_slug, memory_scope_external_ref, thread_external_ref),
                status=status,
                operation=operation,
                category=_normalize_optional_label(category),
                tag=_normalize_optional_label(tag),
                limit=limit,
            )
            return self._ok("Suggestions listed.", data=payload.get("data", payload))

        return await self._guard(action)

    async def approve_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_bool("force", force)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=suggestion_id,
                source_type=None,
            )
            payload = await self._gateway.approve_suggestion(
                suggestion_id=suggestion_id,
                reason=reason,
                force=force,
            )
            return self._ok(
                "Suggestion approved. The returned fact is now canonical memory.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["approved_suggestion"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def reject_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=suggestion_id,
                source_type=None,
            )
            payload = await self._gateway.reject_suggestion(
                suggestion_id=suggestion_id,
                reason=reason,
            )
            return self._ok(
                "Suggestion rejected. It will not affect context retrieval.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["rejected_suggestion"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def expire_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=suggestion_id,
                source_type=None,
            )
            payload = await self._gateway.expire_suggestion(
                suggestion_id=suggestion_id,
                reason=reason,
            )
            return self._ok(
                "Suggestion expired. It will not affect context retrieval.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["expired_suggestion"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def review_suggestion(
        self,
        *,
        suggestion_id: str,
        action: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            ensure_bool("force", force)
            if action not in {"approve", "reject", "expire"}:
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message=f"Invalid review action: {safe_message(action)}",
                    retryable=False,
                )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=suggestion_id,
                source_type=None,
            )
            if action == "approve":
                payload = await self._gateway.approve_suggestion(
                    suggestion_id=suggestion_id,
                    reason=reason,
                    force=force,
                )
                side_effect = "approved_suggestion"
                message = "Suggestion approved. The returned fact is now canonical memory."
            elif action == "reject":
                payload = await self._gateway.reject_suggestion(
                    suggestion_id=suggestion_id,
                    reason=reason,
                )
                side_effect = "rejected_suggestion"
                message = "Suggestion rejected. It will not affect context retrieval."
            else:
                payload = await self._gateway.expire_suggestion(
                    suggestion_id=suggestion_id,
                    reason=reason,
                )
                side_effect = "expired_suggestion"
                message = "Suggestion expired. It will not affect context retrieval."
            return self._ok(
                message,
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=[side_effect],
                warnings=list(policy.warnings),
            )

        return await self._guard(run)

    async def review_suggestions_batch(
        self,
        *,
        items: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            ensure_bool("continue_on_error", continue_on_error)
            normalized = normalize_review_batch_items(items)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=" ".join(item["suggestion_id"] for item in normalized),
                source_type=None,
            )
            payload = await self._gateway.review_suggestions_batch(
                items=normalized,
                continue_on_error=continue_on_error,
            )
            data = payload.get("data", payload)
            failed = int(data.get("failed", 0)) if isinstance(data, dict) else 0
            return self._ok(
                "Suggestion review batch applied."
                if failed == 0
                else "Suggestion review batch finished with item failures.",
                data=data,
                policy=self._policy_payload(policy),
                side_effects=["reviewed_suggestions_batch"],
                warnings=list(policy.warnings),
                degraded=failed > 0,
            )

        return await self._guard(run)

    async def _process_candidate(
        self,
        *,
        candidate_index: int,
        candidate: MemoryUpdateCandidateInput,
        scope: MemoryScope,
        source_type: str | None,
        source_id: str | None,
        quote_preview: str | None,
        dry_run: bool,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        operation = candidate.operation
        if operation == MemoryCandidateOperation.UNKNOWN:
            operation = MemoryCandidateOperation.REMEMBER
        if (
            operation in {MemoryCandidateOperation.REMEMBER, MemoryCandidateOperation.UPDATE}
            and not candidate.text.strip()
        ):
            raise MemoryGatewayError(
                status_code=400,
                code="infinity_context_mcp.validation.invalid_input",
                message="Candidate text is required",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.UPDATE and not candidate.target_fact_id:
            raise MemoryGatewayError(
                status_code=400,
                code="infinity_context_mcp.validation.invalid_input",
                message="Update candidate requires target_fact_id",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.UPDATE and candidate.expected_version is None:
            raise MemoryGatewayError(
                status_code=400,
                code="infinity_context_mcp.validation.invalid_input",
                message="Update candidate requires expected_version",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.FORGET and not candidate.target_fact_id:
            raise MemoryGatewayError(
                status_code=400,
                code="infinity_context_mcp.validation.invalid_input",
                message="Forget candidate requires target_fact_id",
                retryable=False,
            )
        source = self._source_ref(
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
            fallback_seed=f"proposal:{scope}:{candidate_index}:{candidate.text}",
        )
        if dry_run:
            return {
                **build_candidate_result(
                    candidate_index,
                    "needs_review",
                    "infinity_context_mcp.policy.dry_run",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        if self._evidence_mismatch(candidate, source, user_confirmed):
            return {
                **build_candidate_result(
                    candidate_index,
                    "needs_review",
                    "infinity_context_mcp.policy.evidence_mismatch",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        if operation == MemoryCandidateOperation.FORGET:
            return await self._proposal_forget(candidate_index, candidate)
        if operation == MemoryCandidateOperation.UPDATE:
            return await self._proposal_update(candidate_index, candidate, source, user_confirmed)
        return await self._proposal_remember(
            candidate_index,
            candidate,
            scope,
            source,
            user_confirmed,
        )

    async def _proposal_remember(
        self,
        candidate_index: int,
        candidate: MemoryUpdateCandidateInput,
        scope: MemoryScope,
        source: SourceRef,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        policy = self._decide_policy(
            operation=MemoryPolicyOperation.REMEMBER,
            text=candidate.text,
            source_type=source.source_type,
            user_confirmed=user_confirmed,
        )
        duplicate = await self._find_duplicate(scope, candidate.text)
        if duplicate is not None:
            duplicate_kind, duplicate_id, _duplicate_payload = duplicate
            if duplicate_kind == "conflict":
                return {
                    **build_candidate_result(
                        candidate_index,
                        "conflict",
                        "infinity_context_mcp.conflict.requires_review",
                        text=candidate.text,
                        duplicate_id=duplicate_id,
                    ),
                    "_bucket": "conflicts",
                }
            return {
                **build_candidate_result(
                    candidate_index,
                    "duplicate",
                    "infinity_context_mcp.duplicate.existing_memory",
                    text=candidate.text,
                    duplicate_id=duplicate_id,
                ),
                "_bucket": "duplicates",
            }
        if policy.direct_allowed and self._needs_review_for_uncertainty(candidate, source):
            payload = await self._gateway.create_suggestion(
                scope=scope,
                candidate_text=candidate.text,
                kind=candidate.kind,
                source_refs=[source],
                confidence=candidate.confidence,
                trust_level="medium",
                safe_reason="infinity_context_mcp.policy.uncertain_claim",
            )
            return {
                **build_candidate_result(
                    candidate_index,
                    "accepted_suggestion",
                    "infinity_context_mcp.policy.uncertain_claim",
                    text=candidate.text,
                    suggestion_id=str(payload.get("data", payload).get("id", "")),
                ),
                "_bucket": "accepted_suggestions",
                "_side_effect": "created_suggestion",
            }
        if policy.direct_allowed and not self._has_direct_write_evidence(
            source=source,
            user_confirmed=user_confirmed,
        ):
            payload = await self._gateway.create_suggestion(
                scope=scope,
                candidate_text=candidate.text,
                kind=candidate.kind,
                source_refs=[source],
                confidence=candidate.confidence,
                trust_level="medium",
                safe_reason="infinity_context_mcp.policy.evidence_required",
            )
            return {
                **build_candidate_result(
                    candidate_index,
                    "accepted_suggestion",
                    "infinity_context_mcp.policy.evidence_required",
                    text=candidate.text,
                    suggestion_id=str(payload.get("data", payload).get("id", "")),
                ),
                "_bucket": "accepted_suggestions",
                "_side_effect": "created_suggestion",
            }
        if policy.direct_allowed:
            payload = await self._gateway.remember_fact(
                scope=scope,
                text=candidate.text,
                kind=candidate.kind,
                source_refs=[source],
                classification="internal",
                idempotency_key=stable_key("mcp-proposal-remember", scope, candidate.text),
            )
            return {
                **build_candidate_result(
                    candidate_index,
                    "direct_write",
                    policy.code,
                    text=candidate.text,
                    fact_id=str(payload.get("data", payload).get("id", "")),
                ),
                "_bucket": "direct_writes",
                "_side_effect": "remembered_fact",
            }
        payload = await self._gateway.create_suggestion(
            scope=scope,
            candidate_text=candidate.text,
            kind=candidate.kind,
            source_refs=[source],
            confidence=candidate.confidence,
            trust_level="medium",
            safe_reason=policy.code,
        )
        return {
            **build_candidate_result(
                candidate_index,
                "accepted_suggestion",
                policy.code,
                text=candidate.text,
                suggestion_id=str(payload.get("data", payload).get("id", "")),
            ),
            "_bucket": "accepted_suggestions",
            "_side_effect": "created_suggestion",
        }

    async def _proposal_update(
        self,
        candidate_index: int,
        candidate: MemoryUpdateCandidateInput,
        source: SourceRef,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        policy = self._decide_policy(
            operation=MemoryPolicyOperation.UPDATE,
            text=candidate.text,
            source_type=source.source_type,
            user_confirmed=user_confirmed,
        )
        if not self._has_direct_write_evidence(source=source, user_confirmed=user_confirmed):
            return {
                **build_candidate_result(
                    candidate_index,
                    "needs_review",
                    "infinity_context_mcp.policy.evidence_required",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        if self._needs_review_for_uncertainty(candidate, source):
            return {
                **build_candidate_result(
                    candidate_index,
                    "needs_review",
                    "infinity_context_mcp.policy.uncertain_claim",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        payload = await self._gateway.update_fact(
            fact_id=str(candidate.target_fact_id),
            expected_version=int(candidate.expected_version),
            text=candidate.text,
            reason=candidate.reason or "MCP proposal update",
            source_refs=[source],
        )
        return {
            **build_candidate_result(
                candidate_index,
                "direct_update",
                policy.code,
                text=candidate.text,
                fact_id=str(payload.get("data", payload).get("id", candidate.target_fact_id)),
            ),
            "_bucket": "direct_writes",
            "_side_effect": "updated_fact",
        }

    async def _proposal_forget(
        self,
        candidate_index: int,
        candidate: MemoryUpdateCandidateInput,
    ) -> dict[str, Any]:
        policy = self._decide_policy(
            operation=MemoryPolicyOperation.FORGET,
            text=str(candidate.target_fact_id),
            source_type=None,
        )
        payload = await self._gateway.forget_fact(fact_id=str(candidate.target_fact_id))
        return {
            **build_candidate_result(
                candidate_index,
                "direct_forget",
                policy.code,
                text=candidate.text,
                fact_id=str(payload.get("data", payload).get("id", candidate.target_fact_id)),
            ),
            "_bucket": "direct_writes",
            "_side_effect": "forgot_fact",
        }

    def _has_direct_write_evidence(self, *, source: SourceRef, user_confirmed: bool) -> bool:
        return user_confirmed and bool(source.quote_preview)

    def _needs_review_for_uncertainty(
        self,
        candidate: MemoryUpdateCandidateInput,
        source: SourceRef,
    ) -> bool:
        if candidate.confidence == "low":
            return True
        text = normalize_candidate(
            " ".join(
                item
                for item in (
                    candidate.text,
                    candidate.reason,
                    candidate.evidence_quote or "",
                    source.quote_preview or "",
                    " ".join(candidate.labels),
                )
                if item
            )
        )
        return any(marker in text for marker in UNCERTAIN_EVIDENCE_MARKERS)

    def _evidence_mismatch(
        self,
        candidate: MemoryUpdateCandidateInput,
        source: SourceRef,
        user_confirmed: bool,
    ) -> bool:
        if user_confirmed or not source.quote_preview:
            return False
        if candidate.operation not in {
            MemoryCandidateOperation.REMEMBER,
            MemoryCandidateOperation.UPDATE,
            MemoryCandidateOperation.UNKNOWN,
        }:
            return False
        candidate_text = normalize_candidate(candidate.text)
        evidence_text = normalize_candidate(source.quote_preview)
        if not candidate_text or not evidence_text:
            return False
        if candidate_text in evidence_text or evidence_text in candidate_text:
            return False
        candidate_terms = meaningful_terms(candidate_text)
        evidence_terms = meaningful_terms(evidence_text)
        if not candidate_terms:
            return False
        overlap = candidate_terms & evidence_terms
        required = max(1, min(3, len(candidate_terms) // 2))
        return len(overlap) < required
