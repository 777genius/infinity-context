"""Read-side application service operations for MCP memory tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from infinity_context_mcp.application.normalization import (
    normalize_optional_label as _normalize_optional_label,
)
from infinity_context_mcp.application.normalization import (
    normalize_tool_tags as _normalize_tool_tags,
)
from infinity_context_mcp.application.readiness import build_readiness, safe_gateway_error
from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_helpers import clamp_int
from infinity_context_mcp.application.usage_guide import MEMORY_USAGE_GUIDE
from infinity_context_mcp.domain.models import (
    MemoryGatewayError,
    contains_sensitive_value,
    redact_sensitive_text,
)


class MemoryToolQueryService(MemoryToolApplicationServiceBase):
    async def status(self) -> dict[str, Any]:
        health, health_error = await self._capture_gateway(self._gateway.health)
        capabilities, capabilities_error = await self._capture_gateway(self._gateway.capabilities)
        capability_diagnostics = capabilities.get("capabilities", []) if capabilities else []
        readiness = build_readiness(
            health=health,
            health_error=health_error,
            capabilities=capabilities,
            capabilities_error=capabilities_error,
            writes_enabled=self._settings.writes_enabled,
            deletes_enabled=self._settings.deletes_enabled,
        )
        warnings = list(readiness["degraded_reasons"])
        return self._ok(
            "Infinity Context MCP adapter status computed.",
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
                "health_error": safe_gateway_error(health_error),
                "capabilities_error": safe_gateway_error(capabilities_error),
            },
        )

    async def search(
        self,
        *,
        query: str,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
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
                    code="infinity_context_mcp.policy.secret_detected",
                    message="Search query contains a credential-like value",
                    retryable=False,
                )
            effective_token_budget, token_warnings = clamp_int(
                name="token_budget",
                value=token_budget,
                minimum=self._settings.min_token_budget,
                maximum=self._settings.max_token_budget,
            )
            effective_max_facts, facts_warnings = clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_chunks, chunks_warnings = clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            warnings = token_warnings + facts_warnings + chunks_warnings
            scope = self._read_scope(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
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
            data.setdefault(
                "requested_memory_scope_external_refs", list(scope.memory_scope_external_refs)
            )
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
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
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
                    code="infinity_context_mcp.policy.secret_detected",
                    message="Digest topic contains a credential-like value",
                    retryable=False,
                )
            effective_token_budget, token_warnings = clamp_int(
                name="token_budget",
                value=token_budget,
                minimum=self._settings.min_token_budget,
                maximum=self._settings.max_token_budget,
            )
            effective_max_facts, facts_warnings = clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_chunks, chunks_warnings = clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            effective_max_suggestions, suggestions_warnings = clamp_int(
                name="max_suggestions",
                value=max_suggestions,
                minimum=0,
                maximum=self._settings.max_search_items,
            )
            warnings = token_warnings + facts_warnings + chunks_warnings + suggestions_warnings
            scope = self._read_scope(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
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
            data.setdefault(
                "requested_memory_scope_external_refs", list(scope.memory_scope_external_refs)
            )
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
            markdown_truncated = len(original_markdown) > self._settings.max_tool_text_chars
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
        memory_scope_external_ref: str | None = None,
        memory_scope_external_refs: list[str] | None = None,
        thread_external_ref: str | None = None,
        max_facts: int = 200,
        max_documents: int = 100,
        max_episodes: int = 100,
        max_suggestions: int = 100,
        max_captures: int = 100,
        max_activity: int = 50,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            effective_max_facts, fact_warnings = clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=1000,
            )
            effective_max_documents, document_warnings = clamp_int(
                name="max_documents",
                value=max_documents,
                minimum=0,
                maximum=500,
            )
            effective_max_episodes, episode_warnings = clamp_int(
                name="max_episodes",
                value=max_episodes,
                minimum=0,
                maximum=500,
            )
            effective_max_suggestions, suggestion_warnings = clamp_int(
                name="max_suggestions",
                value=max_suggestions,
                minimum=0,
                maximum=500,
            )
            effective_max_captures, capture_warnings = clamp_int(
                name="max_captures",
                value=max_captures,
                minimum=0,
                maximum=500,
            )
            effective_max_activity, activity_warnings = clamp_int(
                name="max_activity",
                value=max_activity,
                minimum=0,
                maximum=100,
            )
            warnings = (
                fact_warnings
                + document_warnings
                + episode_warnings
                + suggestion_warnings
                + capture_warnings
                + activity_warnings
            )
            scope = self._read_scope(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                memory_scope_external_refs=memory_scope_external_refs,
                thread_external_ref=thread_external_ref,
            )
            payload = await self._gateway.build_insights(
                scope=scope,
                max_facts=effective_max_facts,
                max_documents=effective_max_documents,
                max_episodes=effective_max_episodes,
                max_suggestions=effective_max_suggestions,
                max_captures=effective_max_captures,
                max_activity=effective_max_activity,
            )
            data = payload.get("data", {})
            if not isinstance(data, dict):
                data = {}
            data = self._redact_sensitive_search_data(data)
            data.setdefault(
                "requested_memory_scope_external_refs", list(scope.memory_scope_external_refs)
            )
            data.setdefault("requested_max_facts", max_facts)
            data.setdefault("effective_max_facts", effective_max_facts)
            data.setdefault("requested_max_documents", max_documents)
            data.setdefault("effective_max_documents", effective_max_documents)
            data.setdefault("requested_max_episodes", max_episodes)
            data.setdefault("effective_max_episodes", effective_max_episodes)
            data.setdefault("requested_max_suggestions", max_suggestions)
            data.setdefault("effective_max_suggestions", effective_max_suggestions)
            data.setdefault("requested_max_captures", max_captures)
            data.setdefault("effective_max_captures", effective_max_captures)
            data.setdefault("requested_max_activity", max_activity)
            data.setdefault("effective_max_activity", effective_max_activity)
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
