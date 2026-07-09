"""Context-link application service operations for MCP memory tools."""

from __future__ import annotations

from typing import Any

from infinity_context_mcp.application.context_link_review import (
    CONTEXT_LINK_STATUSES,
    CONTEXT_LINK_SUGGESTION_STATUSES,
    normalize_context_link_review_batch_items,
    normalize_context_link_review_item,
    status_filter_payload,
)
from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_helpers import clamp_int, ensure_bool
from infinity_context_mcp.domain.models import MemoryGatewayError, contains_sensitive_value
from infinity_context_mcp.domain.policy import MemoryPolicyOperation


class MemoryToolContextLinkService(MemoryToolApplicationServiceBase):
    async def suggest_context_links(
        self,
        *,
        text: str = "",
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        limit: int = 10,
        persist: bool = False,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            ensure_bool("persist", persist)
            if contains_sensitive_value(text):
                raise MemoryGatewayError(
                    status_code=403,
                    code="infinity_context_mcp.policy.secret_detected",
                    message="Context-link suggestion text contains a credential-like value",
                    retryable=False,
                )
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=30,
            )
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.SUGGEST,
                text=text or f"{source_type or 'source'}:{source_id or 'unknown'}",
                source_type=source_type,
            )
            payload = await self._gateway.suggest_context_links(
                scope=scope,
                text=text,
                source_type=source_type,
                source_id=source_id,
                limit=effective_limit,
                persist=persist,
            )
            return self._ok(
                "Context-link candidates suggested for review."
                if persist
                else "Context-link candidates suggested.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["created_context_link_suggestions"] if persist else [],
                warnings=list(policy.warnings) + warnings,
            )

        return await self._guard(run)

    async def list_context_links(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = "active",
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=200,
            )
            status_param, statuses_param = status_filter_payload(
                status=status,
                statuses=statuses,
                allowed=CONTEXT_LINK_STATUSES,
            )
            payload = await self._gateway.list_context_links(
                scope=self._scope(space_slug, memory_scope_external_ref, None),
                source_type=source_type,
                source_id=source_id,
                status=status_param,
                statuses=statuses_param,
                limit=effective_limit,
            )
            return self._ok(
                "Context links listed.",
                data=payload.get("data", payload),
                warnings=warnings,
            )

        return await self._guard(run)

    async def list_context_link_suggestions(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        status: str | None = "pending",
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=200,
            )
            status_param, statuses_param = status_filter_payload(
                status=status,
                statuses=statuses,
                allowed=CONTEXT_LINK_SUGGESTION_STATUSES,
            )
            payload = await self._gateway.list_context_link_suggestions(
                scope=self._scope(space_slug, memory_scope_external_ref, None),
                source_type=source_type,
                source_id=source_id,
                status=status_param,
                statuses=statuses_param,
                limit=effective_limit,
            )
            return self._ok(
                "Context-link suggestions listed.",
                data=payload.get("data", payload),
                warnings=warnings,
            )

        return await self._guard(run)

    async def review_context_link_suggestion(
        self,
        *,
        suggestion_id: str,
        action: str,
        reason: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        confidence: str | None = None,
        link_reason: str | None = None,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            normalized = normalize_context_link_review_item(
                {
                    "suggestion_id": suggestion_id,
                    "action": action,
                    "reason": reason,
                    "target_type": target_type,
                    "target_id": target_id,
                    "relation_type": relation_type,
                    "confidence": confidence,
                    "link_reason": link_reason,
                }
            )
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=normalized["suggestion_id"],
                source_type=None,
            )
            payload = await self._gateway.review_context_link_suggestion(**normalized)
            return self._ok(
                "Context-link suggestion reviewed.",
                data=payload.get("data", payload),
                policy=self._policy_payload(policy),
                side_effects=["reviewed_context_link_suggestion"],
                warnings=list(policy.warnings),
            )

        return await self._guard(run)

    async def review_context_link_suggestions_batch(
        self,
        *,
        items: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        async def run() -> dict[str, Any]:
            ensure_bool("continue_on_error", continue_on_error)
            normalized = normalize_context_link_review_batch_items(items)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.REVIEW,
                text=" ".join(item["suggestion_id"] for item in normalized),
                source_type=None,
            )
            payload = await self._gateway.review_context_link_suggestions_batch(
                items=normalized,
                continue_on_error=continue_on_error,
            )
            data = payload.get("data", payload)
            failed = int(data.get("failed", 0)) if isinstance(data, dict) else 0
            return self._ok(
                "Context-link suggestion review batch applied."
                if failed == 0
                else "Context-link suggestion review batch finished with item failures.",
                data=data,
                policy=self._policy_payload(policy),
                side_effects=["reviewed_context_link_suggestions_batch"],
                warnings=list(policy.warnings),
                degraded=failed > 0,
            )

        return await self._guard(run)
