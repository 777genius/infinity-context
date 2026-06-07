"""Agent-facing Memo Stack MCP tool service."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from memo_stack_mcp.application.policy import MemoryPolicyService
from memo_stack_mcp.application.ports import MemoryGatewayPort
from memo_stack_mcp.application.usage_guide import MEMORY_USAGE_GUIDE
from memo_stack_mcp.config import MemoryMcpSettings
from memo_stack_mcp.domain.models import (
    McpDiagnostics,
    McpToolError,
    McpToolResponse,
    MemoryCandidateOperation,
    MemoryGatewayError,
    MemoryReadScope,
    MemoryScope,
    MemoryUpdateCandidateInput,
    SourceRef,
    contains_sensitive_value,
    has_control_characters,
    has_zero_width_characters,
    public_error_code,
    redact_sensitive_text,
    safe_message,
)
from memo_stack_mcp.domain.policy import (
    MemoryPolicyDecision,
    MemoryPolicyInput,
    MemoryPolicyOperation,
    MemoryPolicyResult,
)

_MEMORY_KINDS = {"note", "architecture_decision", "constraint", "user_preference"}
_CLASSIFICATIONS = {"public", "internal", "restricted", "unknown"}
_FACT_STATUSES = {"active", "superseded", "disputed", "deleted"}
_SUGGESTION_STATUSES = {"pending", "approved", "rejected", "expired"}
_SUGGESTION_OPERATIONS = {"add", "update", "delete", "review"}
_CAPTURE_STATUSES = {"accepted", "rejected", "redacted", "purged"}
_CAPTURE_CONSOLIDATION_STATUSES = {
    "not_required",
    "pending",
    "running",
    "consolidated",
    "retry_pending",
    "dead",
    "skipped",
}
_CONFIDENCE_VALUES = {"low", "medium", "high"}
_TRUST_VALUES = {"low", "medium", "high"}
_PROFILE_SNAPSHOT_MERGE_STRATEGIES = {
    "fail_on_conflict",
    "skip_existing",
    "create_new_profile",
    "supersede_matching_facts",
}
_UNCERTAIN_EVIDENCE_MARKERS = (
    "could be",
    "guess",
    "guessed",
    "i am not sure",
    "i heard",
    "i might",
    "if true",
    "low confidence",
    "maybe",
    "might",
    "not confirmed",
    "not sure",
    "possibly",
    "probably",
    "review needed",
    "rumor",
    "rumour",
    "unconfirmed",
    "uncertain",
)
_SOURCE_TYPES = {
    "manual",
    "document",
    "system_audio",
    "microphone",
    "manual_prompt",
    "focus_copy",
    "browser_selection",
    "ai_response",
    "assistant_answer",
    "assistant_summary",
    "tool_result",
    "retrieved_memory",
    "codex_thread",
    "unknown",
}


class MemoryToolService:
    def __init__(
        self,
        *,
        gateway: MemoryGatewayPort,
        settings: MemoryMcpSettings,
        policy: MemoryPolicyService | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings
        self._policy = policy or MemoryPolicyService()

    async def status(self) -> dict[str, Any]:
        health, health_error = await self._capture_gateway(self._gateway.health)
        capabilities, capabilities_error = await self._capture_gateway(self._gateway.capabilities)
        capability_diagnostics = capabilities.get("capabilities", []) if capabilities else []
        readiness = self._readiness(
            health=health,
            health_error=health_error,
            capabilities=capabilities,
            capabilities_error=capabilities_error,
        )
        warnings = list(readiness["degraded_reasons"])
        return self._ok(
            "Memo Stack MCP adapter status computed.",
            data={
                "api_url": self._settings.sanitized_api_url,
                "auth_configured": self._settings.auth_token is not None,
                "default_scope": asdict(self._default_scope()),
                "health": health,
                "capabilities": capabilities,
                "capability_diagnostics": capability_diagnostics,
                "readiness": readiness,
                "writes_enabled": self._settings.writes_enabled,
                "deletes_enabled": self._settings.deletes_enabled,
                "ingest_enabled": self._settings.ingest_enabled,
                "write_mode": self._settings.write_mode.value,
                "delete_mode": self._settings.delete_mode.value,
                "ingest_mode": self._settings.ingest_mode.value,
                "usage_guide": MEMORY_USAGE_GUIDE,
            },
            degraded=bool(readiness["degraded"]),
            warnings=warnings,
            backend={
                "health_error": self._safe_gateway_error(health_error),
                "capabilities_error": self._safe_gateway_error(capabilities_error),
            },
        )

    async def search(
        self,
        *,
        query: str,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        token_budget: int = 1800,
        max_facts: int = 12,
        max_chunks: int = 12,
        category: str | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        tags_none: list[str] | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if contains_sensitive_value(query):
                raise MemoryGatewayError(
                    status_code=403,
                    code="memo_stack_mcp.policy.secret_detected",
                    message="Search query contains a credential-like value",
                    retryable=False,
                )
            effective_token_budget, token_warnings = self._clamp_int(
                name="token_budget",
                value=token_budget,
                minimum=self._settings.min_token_budget,
                maximum=self._settings.max_token_budget,
            )
            effective_max_facts, facts_warnings = self._clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_chunks, chunks_warnings = self._clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            warnings = token_warnings + facts_warnings + chunks_warnings
            scope = self._read_scope(
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
                thread_external_ref=thread_external_ref,
            )
            normalized_category = _normalize_optional_label(category)
            normalized_tags_any = _normalize_tool_tags(tags_any or [])
            normalized_tags_all = _normalize_tool_tags(tags_all or [])
            normalized_tags_none = _normalize_tool_tags(tags_none or [])
            context_kwargs: dict[str, Any] = {
                "scope": scope,
                "query": query,
                "token_budget": effective_token_budget,
                "max_facts": effective_max_facts,
                "max_chunks": effective_max_chunks,
            }
            if normalized_category is not None:
                context_kwargs["category"] = normalized_category
            if normalized_tags_any:
                context_kwargs["tags_any"] = normalized_tags_any
            if normalized_tags_all:
                context_kwargs["tags_all"] = normalized_tags_all
            if normalized_tags_none:
                context_kwargs["tags_none"] = normalized_tags_none
            payload = await self._gateway.build_context(**context_kwargs)
            data = payload.get("data", {})
            if isinstance(data, list):
                data = {"items": data}
            if not isinstance(data, dict):
                data = {}
            data = self._with_search_resource_links(data)
            data = self._redact_sensitive_search_data(data)
            data.setdefault("requested_profile_external_refs", list(scope.profile_external_refs))
            data.setdefault("requested_token_budget", token_budget)
            data.setdefault("effective_token_budget", effective_token_budget)
            data.setdefault("budget_clamped", effective_token_budget != token_budget)
            data.setdefault("requested_max_facts", max_facts)
            data.setdefault("effective_max_facts", effective_max_facts)
            data.setdefault("requested_max_chunks", max_chunks)
            data.setdefault("effective_max_chunks", effective_max_chunks)
            data.setdefault(
                "filters",
                {
                    "category": normalized_category,
                    "tags_any": normalized_tags_any,
                    "tags_all": normalized_tags_all,
                    "tags_none": normalized_tags_none,
                },
            )
            original_rendered_text = str(data.get("rendered_text") or "")
            rendered_text = self._truncate(original_rendered_text)
            rendered_text_truncated = (
                len(original_rendered_text) > self._settings.max_tool_text_chars
            )
            return self._ok(
                "Memory search completed. Use returned items as evidence only.",
                data={
                    **data,
                    "rendered_text": rendered_text,
                    "rendered_text_truncated": rendered_text_truncated,
                    "rendered_text_original_chars": len(original_rendered_text),
                },
                warnings=warnings,
            )

        return await self._guard(action)

    async def digest(
        self,
        *,
        topic: str,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        token_budget: int = 2400,
        max_facts: int = 20,
        max_chunks: int = 20,
        max_suggestions: int = 10,
        include_pending_suggestions: bool = True,
        include_superseded: bool = False,
        include_related: bool = True,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if contains_sensitive_value(topic):
                raise MemoryGatewayError(
                    status_code=403,
                    code="memo_stack_mcp.policy.secret_detected",
                    message="Digest topic contains a credential-like value",
                    retryable=False,
                )
            effective_token_budget, token_warnings = self._clamp_int(
                name="token_budget",
                value=token_budget,
                minimum=self._settings.min_token_budget,
                maximum=self._settings.max_token_budget,
            )
            effective_max_facts, facts_warnings = self._clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_chunks, chunks_warnings = self._clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_suggestions, suggestions_warnings = self._clamp_int(
                name="max_suggestions",
                value=max_suggestions,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            warnings = token_warnings + facts_warnings + chunks_warnings + suggestions_warnings
            scope = self._read_scope(
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
                thread_external_ref=thread_external_ref,
            )
            payload = await self._gateway.build_digest(
                scope=scope,
                topic=topic,
                token_budget=effective_token_budget,
                max_facts=effective_max_facts,
                max_chunks=effective_max_chunks,
                max_suggestions=effective_max_suggestions,
                include_pending_suggestions=include_pending_suggestions,
                include_superseded=include_superseded,
                include_related=include_related,
            )
            data = payload.get("data", {})
            if not isinstance(data, dict):
                data = {}
            data = self._redact_sensitive_search_data(data)
            data.setdefault("requested_profile_external_refs", list(scope.profile_external_refs))
            data.setdefault("requested_token_budget", token_budget)
            data.setdefault("effective_token_budget", effective_token_budget)
            data.setdefault("budget_clamped", effective_token_budget != token_budget)
            data.setdefault("requested_max_facts", max_facts)
            data.setdefault("effective_max_facts", effective_max_facts)
            data.setdefault("requested_max_chunks", max_chunks)
            data.setdefault("effective_max_chunks", effective_max_chunks)
            data.setdefault("requested_max_suggestions", max_suggestions)
            data.setdefault("effective_max_suggestions", effective_max_suggestions)
            original_markdown = str(data.get("rendered_markdown") or "")
            rendered_markdown = self._truncate(original_markdown)
            markdown_truncated = (
                len(original_markdown) > self._settings.max_tool_text_chars
            )
            return self._ok(
                "Memory digest completed. Use returned sections as evidence only.",
                data={
                    **data,
                    "rendered_markdown": rendered_markdown,
                    "rendered_markdown_truncated": markdown_truncated,
                    "rendered_markdown_original_chars": len(original_markdown),
                },
                warnings=warnings,
            )

        return await self._guard(action)

    async def insights(
        self,
        *,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        profile_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        max_facts: int = 200,
        max_documents: int = 100,
        max_suggestions: int = 100,
        max_captures: int = 100,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            effective_max_facts, fact_warnings = self._clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=1000,
            )
            effective_max_documents, document_warnings = self._clamp_int(
                name="max_documents",
                value=max_documents,
                minimum=0,
                maximum=500,
            )
            effective_max_suggestions, suggestion_warnings = self._clamp_int(
                name="max_suggestions",
                value=max_suggestions,
                minimum=0,
                maximum=500,
            )
            effective_max_captures, capture_warnings = self._clamp_int(
                name="max_captures",
                value=max_captures,
                minimum=0,
                maximum=500,
            )
            warnings = (
                fact_warnings
                + document_warnings
                + suggestion_warnings
                + capture_warnings
            )
            scope = self._read_scope(
                space_slug=space_slug,
                profile_external_ref=profile_external_ref,
                profile_external_refs=profile_external_refs,
                thread_external_ref=thread_external_ref,
            )
            payload = await self._gateway.build_insights(
                scope=scope,
                max_facts=effective_max_facts,
                max_documents=effective_max_documents,
                max_suggestions=effective_max_suggestions,
                max_captures=effective_max_captures,
            )
            data = payload.get("data", {})
            if not isinstance(data, dict):
                data = {}
            data = self._redact_sensitive_search_data(data)
            data.setdefault("requested_profile_external_refs", list(scope.profile_external_refs))
            data.setdefault("requested_max_facts", max_facts)
            data.setdefault("effective_max_facts", effective_max_facts)
            data.setdefault("requested_max_documents", max_documents)
            data.setdefault("effective_max_documents", effective_max_documents)
            data.setdefault("requested_max_suggestions", max_suggestions)
            data.setdefault("effective_max_suggestions", effective_max_suggestions)
            data.setdefault("requested_max_captures", max_captures)
            data.setdefault("effective_max_captures", effective_max_captures)
            return self._ok(
                "Memory insights completed. Use action_items as review/cleanup guidance only.",
                data=data,
                warnings=warnings,
            )

        return await self._guard(action)

    def _redact_sensitive_search_data(self, value: Any) -> Any:
        if isinstance(value, str):
            return redact_sensitive_text(value)
        if isinstance(value, list):
            return [self._redact_sensitive_search_data(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_sensitive_search_data(item) for key, item in value.items()}
        return value

    async def remember_fact(
        self,
        *,
        text: str,
        kind: str = "note",
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        classification: str = "internal",
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_choice("kind", kind, _MEMORY_KINDS)
            self._ensure_choice("classification", classification, _CLASSIFICATIONS)
            safe_tags = _normalize_tool_tags(tags or ())
            scope = self._scope(space_slug, profile_external_ref, thread_external_ref)
            source = self._source_ref(
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                fallback_seed=f"remember:{scope}:{kind}:{text}",
            )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REMEMBER,
                text=text,
                source_type=source.source_type,
            )
            if policy.decision == MemoryPolicyDecision.ALLOW_SUGGESTION:
                payload = await self._gateway.create_suggestion(
                    scope=scope,
                    candidate_text=text,
                    kind=kind,
                    source_refs=[source],
                    confidence="medium",
                    trust_level="medium",
                    safe_reason=policy.code,
                    category=category,
                    tags=safe_tags,
                    ttl_policy=ttl_policy,
                )
                return self._ok(
                    "Suggestion created for review. It will not affect context until approved.",
                    data=payload.get("data", payload),
                    policy=self._policy_payload(policy),
                    side_effects=["created_suggestion"],
                    warnings=list(policy.warnings),
                )
            duplicate = await self._find_duplicate(scope, text)
            if duplicate is not None:
                duplicate_kind, duplicate_id = duplicate
                if duplicate_kind == "duplicate":
                    return self._ok(
                        "Existing memory already matches this fact. No new fact was created.",
                        data={
                            "id": duplicate_id,
                            "status": "duplicate",
                            "safe_reason": "memo_stack_mcp.duplicate.existing_memory",
                            "reason": "Use the existing memory item instead of creating a copy.",
                        },
                        policy=self._policy_payload(policy),
                        warnings=list(policy.warnings),
                    )
                payload = await self._gateway.create_suggestion(
                    scope=scope,
                    candidate_text=text,
                    kind=kind,
                    source_refs=[source],
                    confidence="medium",
                    trust_level="medium",
                    safe_reason="memo_stack_mcp.conflict.requires_review",
                    category=category,
                    tags=safe_tags,
                    ttl_policy=ttl_policy,
                )
                return self._ok(
                    "Potentially conflicting memory found. Suggestion created for review.",
                    data=payload.get("data", payload),
                    policy=self._policy_payload(policy),
                    side_effects=["created_suggestion"],
                    warnings=[*policy.warnings, "memo_stack_mcp.conflict.requires_review"],
                )
            safe_key = idempotency_key or self._stable_key("mcp-remember", scope, kind, text)
            payload = await self._gateway.remember_fact(
                scope=scope,
                text=text,
                kind=kind,
                source_refs=[source],
                classification=classification,
                category=category,
                tags=safe_tags,
                ttl_policy=ttl_policy,
                idempotency_key=safe_key,
            )
            return self._ok(
                "Fact remembered. Save fact_id and version for future updates.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["remembered_fact"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def list_facts(
        self,
        *,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "active",
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                self._ensure_choice("status", status, _FACT_STATUSES)
            payload = await self._gateway.list_facts(
                scope=self._scope(space_slug, profile_external_ref, thread_external_ref),
                status=status,
                category=_normalize_optional_label(category),
                tag=_normalize_optional_label(tag),
                limit=limit,
                cursor=cursor,
            )
            return self._ok("Facts listed.", data=payload.get("data", payload))

        return await self._guard(action)

    async def get_fact(self, *, fact_id: str) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            payload = await self._gateway.get_fact(fact_id=fact_id)
            return self._ok("Fact loaded.", data=payload.get("data", payload))

        return await self._guard(action)

    async def list_fact_versions(self, *, fact_id: str) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            payload = await self._gateway.list_fact_versions(fact_id=fact_id)
            return self._ok("Fact versions loaded.", data=payload.get("data", payload))

        return await self._guard(action)

    async def update_fact(
        self,
        *,
        fact_id: str,
        expected_version: int,
        text: str,
        reason: str,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            source = self._source_ref(
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                fallback_seed=f"update:{fact_id}:{expected_version}:{text}",
            )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.UPDATE,
                text=text,
                source_type=source.source_type,
            )
            payload = await self._gateway.update_fact(
                fact_id=fact_id,
                expected_version=expected_version,
                text=text,
                reason=reason,
                source_refs=[source],
            )
            return self._ok(
                "Fact updated. Use the returned version for the next update.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["updated_fact"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def forget_fact(self, *, fact_id: str) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.FORGET,
                text=fact_id,
                source_type=None,
            )
            payload = await self._gateway.forget_fact(fact_id=fact_id)
            return self._ok(
                "Fact forgotten and hidden from context retrieval.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["forgot_fact"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def suggest_fact(
        self,
        *,
        candidate_text: str,
        kind: str = "note",
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        confidence: str = "medium",
        trust_level: str = "medium",
        safe_reason: str = "mcp_agent_suggestion_requires_review",
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_choice("kind", kind, _MEMORY_KINDS)
            self._ensure_choice("confidence", confidence, _CONFIDENCE_VALUES)
            self._ensure_choice("trust_level", trust_level, _TRUST_VALUES)
            scope = self._scope(space_slug, profile_external_ref, thread_external_ref)
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

    async def propose_updates(
        self,
        *,
        candidates: list[MemoryUpdateCandidateInput | dict[str, Any]],
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        quote_preview: str | None = None,
        dry_run: bool = False,
        user_confirmed: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_bool("dry_run", dry_run)
            self._ensure_bool("user_confirmed", user_confirmed)
            if not candidates:
                raise MemoryGatewayError(
                    status_code=400,
                    code="memo_stack_mcp.validation.input_too_large",
                    message="At least one candidate is required",
                    retryable=False,
                )
            if len(candidates) > 30:
                raise MemoryGatewayError(
                    status_code=400,
                    code="memo_stack_mcp.validation.input_too_large",
                    message="At most 30 candidates are allowed",
                    retryable=False,
                )
            scope = self._scope(space_slug, profile_external_ref, thread_external_ref)
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
                        code="memo_stack_mcp.validation.input_too_large",
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
                            self._candidate_result(
                                index,
                                "conflict",
                                "memo_stack_mcp.conflict.same_target_in_batch",
                                text=candidate.text,
                                target_fact_id=candidate.target_fact_id,
                            )
                        )
                        continue
                    touched_targets.add(target_key)
                candidate_key = self._candidate_fingerprint(
                    scope=scope,
                    candidate=candidate,
                    source_id=source_id,
                )
                if candidate_key in seen:
                    result["duplicates"].append(
                        self._candidate_result(
                            index,
                            "duplicate",
                            "memo_stack_mcp.duplicate.same_batch",
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
                        if decision_code.startswith("memo_stack_mcp.conflict.")
                        else "unsafe_rejected"
                    )
                    result[bucket].append(
                        self._candidate_result(
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
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "pending",
        operation: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                self._ensure_choice("status", status, _SUGGESTION_STATUSES)
            if operation is not None:
                self._ensure_choice("operation", operation, _SUGGESTION_OPERATIONS)
            payload = await self._gateway.list_suggestions(
                scope=self._scope(space_slug, profile_external_ref, thread_external_ref),
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
            self._ensure_bool("force", force)
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
            self._ensure_bool("force", force)
            if action not in {"approve", "reject", "expire"}:
                raise MemoryGatewayError(
                    status_code=400,
                    code="memo_stack_mcp.validation.invalid_input",
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

    async def list_captures(
        self,
        *,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                self._ensure_choice("status", status, _CAPTURE_STATUSES)
            if consolidation_status is not None:
                self._ensure_choice(
                    "consolidation_status",
                    consolidation_status,
                    _CAPTURE_CONSOLIDATION_STATUSES,
                )
            effective_limit, warnings = self._clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=500,
            )
            payload = await self._gateway.list_captures(
                scope=self._scope(space_slug, profile_external_ref, thread_external_ref),
                status=status,
                consolidation_status=consolidation_status,
                limit=effective_limit,
            )
            return self._ok(
                "Captures listed.",
                data=payload.get("data", payload),
                warnings=warnings,
            )

        return await self._guard(action)

    async def consolidate_capture(
        self,
        *,
        capture_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_bool("force", force)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=capture_id,
                source_type=None,
            )
            payload = await self._gateway.consolidate_capture(
                capture_id=capture_id,
                force=force,
            )
            data = payload.get("data", payload)
            side_effects = ["consolidated_capture"]
            if isinstance(data, dict) and int(data.get("auto_applied_facts") or 0) > 0:
                side_effects.append("auto_applied_fact")
            return self._ok(
                "Capture consolidated into review-gated suggestions.",
                data=data,
                policy=self._policy_payload(policy),
                side_effects=side_effects,
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def export_graph(
        self,
        *,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        include_deleted: bool = False,
        include_restricted: bool = False,
        max_facts: int = 250,
        max_documents: int = 100,
        max_chunks: int = 500,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_bool("include_deleted", include_deleted)
            self._ensure_bool("include_restricted", include_restricted)
            bounded_facts, fact_warnings = self._clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=1_000,
            )
            bounded_documents, document_warnings = self._clamp_int(
                name="max_documents",
                value=max_documents,
                minimum=0,
                maximum=500,
            )
            bounded_chunks, chunk_warnings = self._clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=2_000,
            )
            scope = self._scope(space_slug, profile_external_ref, thread_external_ref)
            payload = await self._gateway.export_graph(
                scope=scope,
                include_deleted=include_deleted,
                include_restricted=include_restricted,
                max_facts=bounded_facts,
                max_documents=bounded_documents,
                max_chunks=bounded_chunks,
            )
            return self._ok(
                "Portable canonical memory graph exported.",
                data=payload.get("data", payload),
                scope=asdict(scope),
                side_effects=[],
                warnings=[*fact_warnings, *document_warnings, *chunk_warnings],
            )

        return await self._guard(action)

    async def export_profile_snapshot(
        self,
        *,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        redacted: bool = True,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_bool("redacted", redacted)
            scope = self._scope(space_slug, profile_external_ref, None)
            payload = await self._gateway.export_profile_snapshot(
                scope=scope,
                redacted=redacted,
            )
            status = str(payload.get("status") or "ok")
            data = {
                "status": status,
                "snapshot": payload.get("data") or {},
                "counts": payload.get("counts") or {},
                "redacted": payload.get("redacted"),
                "manifest": payload.get("manifest") or {},
            }
            return self._ok(
                "Portable profile memory snapshot exported.",
                data=data,
                scope=asdict(scope),
                side_effects=[],
                warnings=[] if status == "ok" else [status],
            )

        return await self._guard(action)

    async def import_profile_snapshot(
        self,
        *,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        dry_run: bool = True,
        merge_strategy: str = "fail_on_conflict",
        confirmed: bool = False,
        source_name: str = "mcp-profile-snapshot",
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if not isinstance(snapshot, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="memo_stack_mcp.validation.invalid_input",
                    message="snapshot must be a JSON object",
                    retryable=False,
                )
            if manifest is not None and not isinstance(manifest, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="memo_stack_mcp.validation.invalid_input",
                    message="manifest must be a JSON object when provided",
                    retryable=False,
                )
            self._ensure_bool("dry_run", dry_run)
            self._ensure_bool("confirmed", confirmed)
            self._ensure_choice(
                "merge_strategy",
                merge_strategy,
                _PROFILE_SNAPSHOT_MERGE_STRATEGIES,
            )
            normalized_source_name = (source_name.strip() or "mcp-profile-snapshot")[:160]
            scope = self._scope(space_slug, profile_external_ref, None)
            policy = None
            side_effects: list[str] = []
            if not dry_run:
                if not confirmed:
                    raise MemoryGatewayError(
                        status_code=403,
                        code="memo_stack_mcp.policy.explicit_confirmation_required",
                        message="Profile snapshot import requires confirmed=true",
                        retryable=False,
                    )
                policy = self._decide_policy(
                    operation=MemoryPolicyOperation.REVIEW,
                    text=f"profile_snapshot_import:{normalized_source_name}",
                    source_type="profile_snapshot",
                    user_confirmed=True,
                )
                side_effects.append("imported_profile_snapshot")
            payload = await self._gateway.import_profile_snapshot(
                scope=scope,
                snapshot=snapshot,
                manifest=manifest,
                dry_run=dry_run,
                merge_strategy=merge_strategy,
                confirmed=confirmed,
                source_name=normalized_source_name,
            )
            return self._ok(
                "Profile memory snapshot import checked."
                if dry_run
                else "Profile memory snapshot imported.",
                data=payload.get("data", payload),
                scope=asdict(scope),
                policy=self._policy_payload(policy) if policy is not None else None,
                side_effects=side_effects,
            )

        return await self._guard(action)

    async def ingest_document(
        self,
        *,
        title: str,
        text: str,
        space_slug: str | None = None,
        profile_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str = "document",
        source_external_id: str | None = None,
        classification: str = "unknown",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_choice("classification", classification, _CLASSIFICATIONS)
            scope = self._scope(space_slug, profile_external_ref, thread_external_ref)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.INGEST_DOCUMENT,
                text=text,
                source_type=source_type,
                text_length=len(text),
            )
            safe_source_id = source_external_id or self._stable_key(
                "mcp-doc-source", scope, title, text
            )
            safe_key = idempotency_key or self._stable_key("mcp-doc", scope, safe_source_id, text)
            payload = await self._gateway.ingest_document(
                scope=scope,
                title=title,
                text=text,
                source_type=source_type,
                source_external_id=safe_source_id,
                classification=classification,
                idempotency_key=safe_key,
            )
            return self._ok(
                "Document ingested. Use memory_search to retrieve relevant chunks.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["ingested_document"],
                warnings=list(policy.warnings),
            )

        return await self._guard(action)

    async def resource_status(self) -> str:
        return self._resource_json(await self.status())

    async def resource_scope_summary(self, *, space_slug: str, profile_external_ref: str) -> str:
        scope = self._resource_scope(space_slug, profile_external_ref)
        facts = await self._gateway.list_facts(scope=scope, status="active", limit=10, cursor=None)
        suggestions = await self._gateway.list_suggestions(
            scope=scope,
            status="pending",
            operation=None,
            category=None,
            tag=None,
            limit=10,
        )
        active_facts, facts_truncated = self._bounded_resource_value(self._payload_items(facts))
        pending_suggestions, suggestions_truncated = self._bounded_resource_value(
            self._payload_items(suggestions)
        )
        return self._resource_json(
            {
                "resource_type": "scope_summary",
                "generated_at": self._generated_at(),
                "scope": asdict(scope),
                "active_facts_preview": active_facts,
                "pending_suggestions_preview": pending_suggestions,
                "truncated": facts_truncated or suggestions_truncated,
                "evidence_only": True,
            }
        )

    async def resource_scope_facts(self, *, space_slug: str, profile_external_ref: str) -> str:
        scope = self._resource_scope(space_slug, profile_external_ref)
        payload = await self._gateway.list_facts(
            scope=scope,
            status="active",
            limit=50,
            cursor=None,
        )
        facts, truncated = self._bounded_resource_value(self._payload_items(payload))
        return self._resource_json(
            {
                "resource_type": "scope_facts",
                "generated_at": self._generated_at(),
                "scope": asdict(scope),
                "facts": facts,
                "truncated": truncated,
                "evidence_only": True,
            }
        )

    async def resource_scope_suggestions(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
    ) -> str:
        scope = self._resource_scope(space_slug, profile_external_ref)
        payload = await self._gateway.list_suggestions(
            scope=scope,
            status="pending",
            operation=None,
            category=None,
            tag=None,
            limit=50,
        )
        suggestions, truncated = self._bounded_resource_value(self._payload_items(payload))
        return self._resource_json(
            {
                "resource_type": "scope_suggestions",
                "generated_at": self._generated_at(),
                "scope": asdict(scope),
                "suggestions": suggestions,
                "truncated": truncated,
                "evidence_only": True,
            }
        )

    async def resource_fact(self, *, fact_id: str) -> str:
        safe_fact_id = self._resource_arg("fact_id", fact_id)
        payload = await self._gateway.get_fact(fact_id=safe_fact_id)
        fact, truncated = self._bounded_resource_value(payload.get("data", payload))
        return self._resource_json(
            {
                "resource_type": "fact",
                "generated_at": self._generated_at(),
                "fact": fact,
                "truncated": truncated,
                "evidence_only": True,
            }
        )

    async def resource_fact_versions(self, *, fact_id: str) -> str:
        safe_fact_id = self._resource_arg("fact_id", fact_id)
        payload = await self._gateway.list_fact_versions(fact_id=safe_fact_id)
        versions, truncated = self._bounded_resource_value(payload.get("data", payload))
        return self._resource_json(
            {
                "resource_type": "fact_versions",
                "generated_at": self._generated_at(),
                "versions": versions,
                "truncated": truncated,
                "evidence_only": True,
            }
        )

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
                code="memo_stack_mcp.validation.invalid_input",
                message="Candidate text is required",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.UPDATE and not candidate.target_fact_id:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_input",
                message="Update candidate requires target_fact_id",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.UPDATE and candidate.expected_version is None:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_input",
                message="Update candidate requires expected_version",
                retryable=False,
            )
        if operation == MemoryCandidateOperation.FORGET and not candidate.target_fact_id:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_input",
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
                **self._candidate_result(
                    candidate_index,
                    "needs_review",
                    "memo_stack_mcp.policy.dry_run",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        if self._evidence_mismatch(candidate, source, user_confirmed):
            return {
                **self._candidate_result(
                    candidate_index,
                    "needs_review",
                    "memo_stack_mcp.policy.evidence_mismatch",
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
            duplicate_kind, duplicate_id = duplicate
            if duplicate_kind == "conflict":
                return {
                    **self._candidate_result(
                        candidate_index,
                        "conflict",
                        "memo_stack_mcp.conflict.requires_review",
                        text=candidate.text,
                        duplicate_id=duplicate_id,
                    ),
                    "_bucket": "conflicts",
                }
            return {
                **self._candidate_result(
                    candidate_index,
                    "duplicate",
                    "memo_stack_mcp.duplicate.existing_memory",
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
                safe_reason="memo_stack_mcp.policy.uncertain_claim",
            )
            return {
                **self._candidate_result(
                    candidate_index,
                    "accepted_suggestion",
                    "memo_stack_mcp.policy.uncertain_claim",
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
                safe_reason="memo_stack_mcp.policy.evidence_required",
            )
            return {
                **self._candidate_result(
                    candidate_index,
                    "accepted_suggestion",
                    "memo_stack_mcp.policy.evidence_required",
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
                idempotency_key=self._stable_key("mcp-proposal-remember", scope, candidate.text),
            )
            return {
                **self._candidate_result(
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
            **self._candidate_result(
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
                **self._candidate_result(
                    candidate_index,
                    "needs_review",
                    "memo_stack_mcp.policy.evidence_required",
                    text=candidate.text,
                    target_fact_id=candidate.target_fact_id,
                ),
                "_bucket": "needs_review",
            }
        if self._needs_review_for_uncertainty(candidate, source):
            return {
                **self._candidate_result(
                    candidate_index,
                    "needs_review",
                    "memo_stack_mcp.policy.uncertain_claim",
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
            **self._candidate_result(
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
            **self._candidate_result(
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
        text = self._normalize_candidate(
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
        return any(marker in text for marker in _UNCERTAIN_EVIDENCE_MARKERS)

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
        candidate_text = self._normalize_candidate(candidate.text)
        evidence_text = self._normalize_candidate(source.quote_preview)
        if not candidate_text or not evidence_text:
            return False
        if candidate_text in evidence_text or evidence_text in candidate_text:
            return False
        candidate_terms = self._meaningful_terms(candidate_text)
        evidence_terms = self._meaningful_terms(evidence_text)
        if not candidate_terms:
            return False
        overlap = candidate_terms & evidence_terms
        required = max(1, min(3, len(candidate_terms) // 2))
        return len(overlap) < required

    @staticmethod
    def _meaningful_terms(text: str) -> set[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "use",
            "uses",
            "user",
            "decided",
            "should",
            "memory",
        }
        return {
            token.strip(".,:;!?()[]{}\"'")
            for token in text.split()
            if len(token.strip(".,:;!?()[]{}\"'")) >= 4
            and token.strip(".,:;!?()[]{}\"'") not in stop_words
        }

    async def _find_duplicate(self, scope: MemoryScope, text: str) -> tuple[str, str] | None:
        normalized = self._normalize_candidate(text)
        facts = await self._gateway.list_facts(scope=scope, status="active", limit=50, cursor=None)
        possible_conflict: str | None = None
        for item in self._payload_items(facts):
            item_text = str(item.get("text", ""))
            item_id = str(item.get("id") or item.get("fact_id") or "")
            if self._normalize_candidate(item_text) == normalized:
                return ("duplicate", item_id)
            if possible_conflict is None and self._looks_conflicting_fact(text, item_text):
                possible_conflict = item_id
        suggestions = await self._gateway.list_suggestions(
            scope=scope,
            status="pending",
            operation=None,
            category=None,
            tag=None,
            limit=50,
        )
        for item in self._payload_items(suggestions):
            candidate_text = str(item.get("candidate_text") or item.get("text") or "")
            if self._normalize_candidate(candidate_text) == normalized:
                return ("duplicate", str(item.get("id") or item.get("suggestion_id") or ""))
        if possible_conflict is not None:
            return ("conflict", possible_conflict)
        return None

    def _looks_conflicting_fact(self, candidate_text: str, existing_text: str) -> bool:
        candidate_normalized = self._normalize_candidate(candidate_text)
        existing_normalized = self._normalize_candidate(existing_text)
        if not candidate_normalized or not existing_normalized:
            return False
        if candidate_normalized == existing_normalized:
            return False
        decision_terms = {
            "adapter",
            "backend",
            "cache",
            "canonical",
            "database",
            "engine",
            "memory",
            "model",
            "provider",
            "storage",
            "truth",
            "vector",
        }
        candidate_terms = self._meaningful_terms(candidate_normalized)
        existing_terms = self._meaningful_terms(existing_normalized)
        overlap = candidate_terms & existing_terms
        return len(overlap) >= 2 and bool(overlap & decision_terms)

    @staticmethod
    def _payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data", payload)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            items = data.get("items")
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def _with_search_resource_links(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(data)
        resource_uris: list[str] = []
        for key in ("items", "facts", "chunks"):
            raw_items = normalized.get(key)
            if not isinstance(raw_items, list):
                continue
            linked_items: list[dict[str, Any]] = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                fact_id = str(item.get("fact_id") or item.get("id") or item.get("item_id") or "")
                item_type = str(item.get("item_type") or item.get("type") or "")
                if fact_id and (not item_type or item_type == "fact"):
                    item.setdefault("resource_uri", f"memory://fact/{fact_id}")
                    resource_uris.append(str(item["resource_uri"]))
                    item.setdefault("item_type", "fact")
                    item.setdefault("item_id", fact_id)
                linked_items.append(item)
            normalized[key] = linked_items
        if resource_uris:
            normalized.setdefault("resource_uris", sorted(set(resource_uris)))
        return normalized

    def _candidate_fingerprint(
        self,
        *,
        scope: MemoryScope,
        candidate: MemoryUpdateCandidateInput,
        source_id: str | None,
    ) -> str:
        return self._stable_key(
            "mcp-candidate",
            scope.space_slug,
            scope.profile_external_ref,
            scope.thread_external_ref,
            candidate.operation.value,
            candidate.target_fact_id,
            candidate.expected_version,
            self._normalize_candidate(candidate.text),
            source_id or "",
        )

    @staticmethod
    def _normalize_candidate(text: str) -> str:
        normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
        return " ".join(normalized.strip().casefold().split())

    @staticmethod
    def _candidate_result(
        candidate_index: int,
        status: str,
        decision_code: str,
        *,
        text: str,
        fact_id: str | None = None,
        suggestion_id: str | None = None,
        duplicate_id: str | None = None,
        target_fact_id: str | None = None,
        retryable: bool = False,
        message: str | None = None,
    ) -> dict[str, Any]:
        resource_uri = f"memory://fact/{fact_id}" if fact_id else None
        return {
            "candidate_index": candidate_index,
            "status": status,
            "decision_code": decision_code,
            "text": text,
            "fact_id": fact_id,
            "suggestion_id": suggestion_id,
            "duplicate_id": duplicate_id,
            "target_fact_id": target_fact_id,
            "resource_uri": resource_uri,
            "retryable": retryable,
            "message": message,
        }

    def _resource_scope(self, space_slug: str, profile_external_ref: str) -> MemoryScope:
        return MemoryScope(
            space_slug=self._resource_arg("space_slug", space_slug),
            profile_external_ref=self._resource_arg("profile_external_ref", profile_external_ref),
        )

    def _resource_arg(self, field_name: str, value: str) -> str:
        safe_value = value.strip()
        if not safe_value:
            raise ValueError(f"{field_name} is required")
        if safe_value in {".", ".."}:
            raise ValueError(f"{field_name} is invalid")
        if "%" in safe_value:
            raise ValueError(f"{field_name} cannot contain percent encoding")
        if "/" in safe_value or "\\" in safe_value:
            raise ValueError(f"{field_name} cannot contain path separators")
        if ":" in safe_value:
            raise ValueError(f"{field_name} cannot contain nested URI syntax")
        if has_control_characters(safe_value) or has_zero_width_characters(safe_value):
            raise ValueError(f"{field_name} contains unsafe formatting characters")
        return safe_value

    @staticmethod
    def _resource_json(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _bounded_resource_value(self, value: Any) -> tuple[Any, bool]:
        if isinstance(value, str):
            if len(value) > self._settings.max_tool_text_chars:
                return value[: self._settings.max_tool_text_chars] + "\n[truncated]", True
            return value, False
        if isinstance(value, list):
            bounded_items: list[Any] = []
            truncated = False
            for item in value:
                bounded_item, item_truncated = self._bounded_resource_value(item)
                bounded_items.append(bounded_item)
                truncated = truncated or item_truncated
            return bounded_items, truncated
        if isinstance(value, dict):
            bounded_dict: dict[str, Any] = {}
            truncated = False
            for key, item in value.items():
                bounded_item, item_truncated = self._bounded_resource_value(item)
                bounded_dict[str(key)] = bounded_item
                truncated = truncated or item_truncated
            return bounded_dict, truncated
        return value, False

    @staticmethod
    def _generated_at() -> str:
        return datetime.now(UTC).isoformat()

    def _default_scope(self) -> MemoryScope:
        return MemoryScope(
            space_slug=self._settings.default_space_slug,
            profile_external_ref=self._settings.default_profile_external_ref,
            thread_external_ref=self._settings.default_thread_external_ref,
        )

    def _scope(
        self,
        space_slug: str | None,
        profile_external_ref: str | None,
        thread_external_ref: str | None,
    ) -> MemoryScope:
        return MemoryScope(
            space_slug=(space_slug or self._settings.default_space_slug).strip(),
            profile_external_ref=(
                profile_external_ref or self._settings.default_profile_external_ref
            ).strip(),
            thread_external_ref=thread_external_ref or self._settings.default_thread_external_ref,
        )

    def _read_scope(
        self,
        *,
        space_slug: str | None,
        profile_external_ref: str | None,
        profile_external_refs: list[str] | None,
        thread_external_ref: str | None,
    ) -> MemoryReadScope:
        refs: list[str] = []
        if profile_external_ref:
            refs.append(profile_external_ref)
        refs.extend(profile_external_refs or [])
        if not refs:
            refs.append(self._settings.default_profile_external_ref)
        try:
            return MemoryReadScope(
                space_slug=(space_slug or self._settings.default_space_slug).strip(),
                profile_external_refs=tuple(refs),
                thread_external_ref=(
                    thread_external_ref or self._settings.default_thread_external_ref
                ),
            )
        except ValueError as exc:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.invalid_scope",
                message=str(exc),
                retryable=False,
            ) from exc

    def _source_ref(
        self,
        *,
        source_type: str | None,
        source_id: str | None,
        quote_preview: str | None,
        fallback_seed: str,
    ) -> SourceRef:
        quote = quote_preview.strip() if quote_preview else None
        if contains_sensitive_value(quote):
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.policy.secret_detected",
                message="Quote preview contains a credential-like value",
                retryable=False,
            )
        try:
            return SourceRef(
                source_type=self._safe_source_type(source_type),
                source_id=self._safe_source_id(
                    source_id or self._stable_key("mcp-source", fallback_seed)
                ),
                quote_preview=quote,
            )
        except ValueError as exc:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_source_ref",
                message=str(exc),
                retryable=False,
            ) from exc

    def _safe_source_type(self, source_type: str | None) -> str:
        value = (source_type or self._settings.source_type).strip()
        if value not in _SOURCE_TYPES:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_source_ref",
                message=f"Unsupported source_type: {safe_message(value)}",
                retryable=False,
            )
        return value

    def _safe_source_id(self, source_id: str) -> str:
        value = source_id.strip()
        if contains_sensitive_value(value):
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_source_ref",
                message="Source id contains a credential-like value",
                retryable=False,
            )
        if has_control_characters(value) or has_zero_width_characters(value):
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_source_ref",
                message="Source id contains unsafe formatting characters",
                retryable=False,
            )
        if value.startswith(("/Users/", "/home/")) or "\\Users\\" in value:
            return self._stable_key("mcp-source-path", value)
        return value

    def _decide_policy(
        self,
        *,
        operation: MemoryPolicyOperation,
        text: str,
        source_type: str | None,
        user_confirmed: bool = False,
        text_length: int | None = None,
    ) -> MemoryPolicyResult:
        result = self._policy.decide(
            MemoryPolicyInput(
                operation=operation,
                text=text,
                source_type=source_type,
                write_mode=self._settings.write_mode,
                delete_mode=self._settings.delete_mode,
                ingest_mode=self._settings.ingest_mode,
                writes_enabled=self._settings.writes_enabled,
                deletes_enabled=self._settings.deletes_enabled,
                user_confirmed=user_confirmed,
                text_length=len(text) if text_length is None else text_length,
                small_doc_max_chars=self._settings.small_doc_max_chars,
            )
        )
        if not result.allowed:
            raise MemoryGatewayError(
                status_code=403,
                code=result.code,
                message=result.safe_message,
                retryable=False,
            )
        return result

    @staticmethod
    def _policy_payload(result: MemoryPolicyResult) -> dict[str, Any]:
        return {
            "decision": result.decision.value,
            "code": result.code,
            "direct_allowed": result.direct_allowed,
            "allowed": result.allowed,
        }

    def _ensure_writes_allowed(self) -> None:
        if not self._settings.writes_enabled:
            raise MemoryGatewayError(
                status_code=403,
                code="memo_stack_mcp.policy.write_mode_off",
                message="Memo Stack MCP writes are disabled by local policy",
                retryable=False,
            )

    def _ensure_deletes_allowed(self) -> None:
        if not self._settings.deletes_enabled:
            raise MemoryGatewayError(
                status_code=403,
                code="memo_stack_mcp.policy.delete_mode_off",
                message="Memo Stack MCP deletes are disabled by local policy",
                retryable=False,
            )

    def _ensure_choice(self, field_name: str, value: str, allowed: set[str]) -> None:
        if value not in allowed:
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_input",
                message=f"Invalid {field_name}: {safe_message(value)}",
                retryable=False,
            )

    def _ensure_bool(self, field_name: str, value: object) -> None:
        if not isinstance(value, bool):
            raise MemoryGatewayError(
                status_code=400,
                code="memo_stack_mcp.validation.invalid_input",
                message=f"{field_name} must be a boolean",
                retryable=False,
            )

    @staticmethod
    def _clamp_int(
        *,
        name: str,
        value: int,
        minimum: int,
        maximum: int,
    ) -> tuple[int, list[str]]:
        if value < minimum:
            return minimum, [f"{name}_clamped_to_min"]
        if value > maximum:
            return maximum, [f"{name}_clamped_to_max"]
        return value, []

    def _truncate(self, value: str) -> str:
        if len(value) <= self._settings.max_tool_text_chars:
            return value
        return value[: self._settings.max_tool_text_chars] + "\n[truncated]"

    @staticmethod
    def _stable_key(prefix: str, *parts: object) -> str:
        digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
        return f"{prefix}:{digest[:32]}"

    async def _guard(self, action) -> dict[str, Any]:
        try:
            return await action()
        except MemoryGatewayError as exc:
            code = public_error_code(exc.code, status_code=exc.status_code)
            message = safe_message(exc.message)
            response = McpToolResponse(
                ok=False,
                message=message,
                error=McpToolError(
                    status_code=exc.status_code,
                    code=code,
                    message=message,
                    safe_message=message,
                    retryable=exc.retryable,
                    unknown_commit_state=exc.unknown_commit_state,
                ),
                diagnostics=McpDiagnostics(
                    trace_id=self._trace_id(),
                    backend={"code": safe_message(exc.code), "status_code": exc.status_code},
                    degraded=code.startswith(
                        ("memo_stack_mcp.gateway.", "memo_stack_mcp.degraded.")
                    ),
                ),
            )
            return response.model_dump(exclude_none=True)

    def _ok(
        self,
        message: str,
        *,
        data: dict[str, Any] | list[Any],
        scope: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        side_effects: list[str] | None = None,
        warnings: list[str] | None = None,
        degraded: bool = False,
        backend: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diagnostics = McpDiagnostics(
            trace_id=self._trace_id(),
            scope=scope,
            policy=policy or {},
            side_effects=side_effects or [],
            warnings=warnings or [],
            degraded=degraded,
            backend=backend or {},
        )
        clean_data = _drop_none_values(data)
        response_data: dict[str, Any] | list[Any]
        response_data = {"items": clean_data} if isinstance(clean_data, list) else clean_data
        return {
            "ok": True,
            "message": message,
            "data": response_data,
            "diagnostics": diagnostics.model_dump(exclude_none=True),
        }

    async def _capture_gateway(
        self,
        call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> tuple[dict[str, Any] | None, MemoryGatewayError | None]:
        try:
            return await call(), None
        except MemoryGatewayError as exc:
            return None, exc

    def _readiness(
        self,
        *,
        health: dict[str, Any] | None,
        health_error: MemoryGatewayError | None,
        capabilities: dict[str, Any] | None,
        capabilities_error: MemoryGatewayError | None,
    ) -> dict[str, Any]:
        api_reachable = health_error is None and bool(health)
        capabilities_available = capabilities_error is None and bool(capabilities)
        projection_ready, projection_reasons = self._projection_readiness(capabilities)
        degraded_reasons: list[str] = []
        if not api_reachable:
            degraded_reasons.append("api.unreachable")
        if not capabilities_available:
            degraded_reasons.append("capabilities.unavailable")
        degraded_reasons.extend(projection_reasons)
        read_ready = api_reachable and capabilities_available
        write_ready = read_ready and self._settings.writes_enabled
        delete_ready = read_ready and self._settings.deletes_enabled
        return {
            "api_reachable": api_reachable,
            "read_ready": read_ready,
            "write_ready": write_ready,
            "delete_ready": delete_ready,
            "projection_ready": projection_ready,
            "degraded": bool(degraded_reasons),
            "degraded_reasons": degraded_reasons,
            "checked_endpoints": ["/v1/health", "/v1/capabilities"],
        }

    @staticmethod
    def _projection_readiness(capabilities: dict[str, Any] | None) -> tuple[bool, list[str]]:
        if not capabilities:
            return False, ["projection.unknown"]
        capability_items = capabilities.get("capabilities", [])
        if not isinstance(capability_items, list) or not capability_items:
            return False, ["projection.unknown"]
        reasons: list[str] = []
        for item in capability_items:
            if not isinstance(item, dict):
                reasons.append("projection.invalid_capability")
                continue
            status = str(item.get("status") or "")
            healthy = bool(item.get("healthy", status == "ok"))
            enabled = bool(item.get("enabled", True))
            name = str(item.get("adapter_name") or item.get("capability") or "adapter")
            if not enabled:
                reasons.append(f"{name}.disabled")
            elif not healthy or status not in {"ok", "healthy"}:
                reasons.append(f"{name}.degraded")
        return not reasons, reasons

    @staticmethod
    def _safe_gateway_error(error: MemoryGatewayError | None) -> dict[str, Any] | None:
        if error is None:
            return None
        return {
            "status_code": error.status_code,
            "code": public_error_code(error.code, status_code=error.status_code),
            "message": safe_message(error.message),
            "retryable": error.retryable,
        }

    @staticmethod
    def _trace_id() -> str:
        return f"mcp_{uuid.uuid4().hex[:16]}"


def _normalize_optional_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_tool_tags(values: Iterable[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        normalized = _normalize_optional_label(value)
        if normalized and normalized not in tags:
            tags.append(normalized)
        if len(tags) >= 10:
            break
    return tags


def _drop_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_drop_none_values(item) for item in value]
    return value
