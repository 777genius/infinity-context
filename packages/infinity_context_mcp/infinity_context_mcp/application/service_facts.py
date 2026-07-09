"""Fact and relation application service operations for MCP memory tools."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application.review_payloads import conflict_review_contract

from infinity_context_mcp.application.context_link_review import (
    CONTEXT_LINK_STATUSES,
    CONTEXT_LINK_SUGGESTION_STATUSES,
)
from infinity_context_mcp.application.normalization import (
    normalize_optional_label as _normalize_optional_label,
)
from infinity_context_mcp.application.normalization import (
    normalize_tool_tags as _normalize_tool_tags,
)
from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_constants import (
    CAPTURE_STATUSES,
    CLASSIFICATIONS,
    FACT_RELATION_STATUSES,
    FACT_RELATION_TYPES,
    FACT_STATUSES,
    MEMORY_BROWSER_ANCHOR_STATUSES,
    MEMORY_BROWSER_ASSET_STATUSES,
    MEMORY_BROWSER_CHUNK_STATUSES,
    MEMORY_BROWSER_DOCUMENT_STATUSES,
    MEMORY_BROWSER_EPISODE_STATUSES,
    MEMORY_BROWSER_EXTRACTION_STATUSES,
    MEMORY_BROWSER_THREAD_STATUSES,
    MEMORY_KINDS,
)
from infinity_context_mcp.application.service_duplicates import MemoryToolDuplicateMixin
from infinity_context_mcp.application.service_helpers import clamp_int, ensure_choice, stable_key
from infinity_context_mcp.domain.models import (
    MemoryGatewayError,
    contains_sensitive_value,
)
from infinity_context_mcp.domain.policy import MemoryPolicyDecision, MemoryPolicyOperation


class MemoryToolFactService(MemoryToolDuplicateMixin, MemoryToolApplicationServiceBase):
    async def remember_fact(
        self,
        *,
        text: str,
        kind: str = "note",
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
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
            ensure_choice("kind", kind, MEMORY_KINDS)
            ensure_choice("classification", classification, CLASSIFICATIONS)
            safe_tags = _normalize_tool_tags(tags or ())
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
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
                duplicate_kind, duplicate_id, duplicate_payload = duplicate
                if duplicate_kind == "duplicate":
                    return self._ok(
                        "Existing memory already matches this fact. No new fact was created.",
                        data={
                            "id": duplicate_id,
                            "status": "duplicate",
                            "safe_reason": "infinity_context_mcp.duplicate.existing_memory",
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
                    safe_reason="infinity_context_mcp.conflict.requires_review",
                    category=category,
                    tags=safe_tags,
                    ttl_policy=ttl_policy,
                    review_payload={
                        **conflict_review_contract(
                            approve_effect="create_new_fact_keep_conflicting_fact"
                        ),
                        "conflicting_fact_id": duplicate_id,
                        "conflict_source": "mcp_preflight",
                        **duplicate_payload,
                    },
                )
                return self._ok(
                    "Potentially conflicting memory found. Suggestion created for review.",
                    data=payload.get("data", payload),
                    policy=self._policy_payload(policy),
                    side_effects=["created_suggestion"],
                    warnings=[*policy.warnings, "infinity_context_mcp.conflict.requires_review"],
                )
            safe_key = idempotency_key or stable_key("mcp-remember", scope, kind, text)
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
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = "active",
        category: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                ensure_choice("status", status, FACT_STATUSES)
            payload = await self._gateway.list_facts(
                scope=self._scope(space_slug, memory_scope_external_ref, thread_external_ref),
                status=status,
                category=_normalize_optional_label(category),
                tag=_normalize_optional_label(tag),
                limit=limit,
                cursor=cursor,
            )
            return self._ok("Facts listed.", data=payload.get("data", payload))

        return await self._guard(action)

    async def browse_scope(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        limit: int = 50,
        fact_status: str | None = "active",
        episode_status: str | None = "active",
        document_status: str | None = "active",
        chunk_status: str | None = "active",
        extraction_status: str | None = None,
        thread_status: str | None = "active",
        capture_status: str | None = None,
        asset_status: str | None = "stored",
        anchor_status: str | None = "active",
        link_status: str | None = None,
        suggestion_status: str | None = None,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            _ensure_optional_choice("fact_status", fact_status, FACT_STATUSES)
            _ensure_optional_choice(
                "episode_status",
                episode_status,
                MEMORY_BROWSER_EPISODE_STATUSES,
            )
            _ensure_optional_choice(
                "document_status",
                document_status,
                MEMORY_BROWSER_DOCUMENT_STATUSES,
            )
            _ensure_optional_choice("chunk_status", chunk_status, MEMORY_BROWSER_CHUNK_STATUSES)
            _ensure_optional_choice(
                "extraction_status",
                extraction_status,
                MEMORY_BROWSER_EXTRACTION_STATUSES,
            )
            _ensure_optional_choice(
                "thread_status",
                thread_status,
                MEMORY_BROWSER_THREAD_STATUSES,
            )
            _ensure_optional_choice("capture_status", capture_status, CAPTURE_STATUSES)
            _ensure_optional_choice("asset_status", asset_status, MEMORY_BROWSER_ASSET_STATUSES)
            _ensure_optional_choice("anchor_status", anchor_status, MEMORY_BROWSER_ANCHOR_STATUSES)
            _ensure_optional_choice("link_status", link_status, CONTEXT_LINK_STATUSES)
            _ensure_optional_choice(
                "suggestion_status",
                suggestion_status,
                CONTEXT_LINK_SUGGESTION_STATUSES,
            )
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=200,
            )
            payload = await self._gateway.get_memory_browser(
                scope=self._scope(space_slug, memory_scope_external_ref, None),
                limit=effective_limit,
                fact_status=fact_status,
                episode_status=episode_status,
                document_status=document_status,
                chunk_status=chunk_status,
                extraction_status=extraction_status,
                thread_status=thread_status,
                capture_status=capture_status,
                asset_status=asset_status,
                anchor_status=anchor_status,
                link_status=link_status,
                suggestion_status=suggestion_status,
            )
            return self._ok(
                "Memory scope browser read model loaded.",
                data=payload.get("data", payload),
                side_effects=[],
                warnings=warnings,
            )

        return await self._guard(action)

    async def get_fact(self, *, fact_id: str) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            payload = await self._gateway.get_fact(fact_id=fact_id)
            return self._ok("Fact loaded.", data=payload.get("data", payload))

        return await self._guard(action)

    async def get_related_facts(
        self,
        *,
        fact_id: str,
        limit: int = 10,
        include_other_threads: bool = False,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=50,
            )
            payload = await self._gateway.get_related_facts(
                fact_id=fact_id,
                limit=effective_limit,
                include_other_threads=include_other_threads,
            )
            data = payload.get("data", payload)
            return self._ok(
                "Related facts loaded with explainable relation reasons.",
                data=data,
                side_effects=[],
                warnings=warnings,
            )

        return await self._guard(action)

    async def link_facts(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: str = "related_to",
        reason: str,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            self._ensure_writes_allowed()
            ensure_choice("relation_type", relation_type, FACT_RELATION_TYPES)
            if not reason.strip():
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message="relation reason is required",
                    retryable=False,
                )
            if contains_sensitive_value(reason):
                raise MemoryGatewayError(
                    status_code=403,
                    code="infinity_context_mcp.policy.secret_detected",
                    message="Relation reason contains a credential-like value",
                    retryable=False,
                )
            payload = await self._gateway.link_facts(
                source_fact_id=source_fact_id,
                target_fact_id=target_fact_id,
                relation_type=relation_type,
                reason=reason,
            )
            return self._ok(
                "Facts linked with a durable typed relation.",
                data=payload.get("data", payload),
                side_effects=["linked_facts"],
            )

        return await self._guard(action)

    async def list_fact_relations(
        self,
        *,
        fact_id: str,
        status: str | None = "active",
        limit: int = 50,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if status is not None:
                ensure_choice("status", status, FACT_RELATION_STATUSES)
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=100,
            )
            payload = await self._gateway.list_fact_relations(
                fact_id=fact_id,
                status=status,
                limit=effective_limit,
            )
            return self._ok(
                "Fact relations listed.",
                data=payload.get("data", payload),
                side_effects=[],
                warnings=warnings,
            )

        return await self._guard(action)

    async def unlink_fact_relation(self, *, relation_id: str) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.FORGET,
                text=relation_id,
                source_type=None,
            )
            payload = await self._gateway.unlink_fact_relation(relation_id=relation_id)
            return self._ok(
                "Fact relation unlinked and hidden from active relation traversal.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["unlinked_fact_relation"],
                warnings=list(policy.warnings),
            )

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



def _ensure_optional_choice(name: str, value: str | None, allowed: set[str]) -> None:
    if value is not None:
        ensure_choice(name, value, allowed)
