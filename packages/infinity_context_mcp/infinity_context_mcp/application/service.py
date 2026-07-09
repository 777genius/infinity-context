"""Agent-facing Infinity Context MCP tool service facade."""

from __future__ import annotations

from typing import Any

from infinity_context_mcp.application.policy import MemoryPolicyService
from infinity_context_mcp.application.ports import MemoryGatewayPort
from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_context_links import MemoryToolContextLinkService
from infinity_context_mcp.application.service_facts import MemoryToolFactService
from infinity_context_mcp.application.service_lifecycle import MemoryToolLifecycleService
from infinity_context_mcp.application.service_query import MemoryToolQueryService
from infinity_context_mcp.application.service_suggestions import MemoryToolSuggestionService
from infinity_context_mcp.application.usage_guide import MEMORY_USAGE_GUIDE as MEMORY_USAGE_GUIDE
from infinity_context_mcp.config import MemoryMcpSettings
from infinity_context_mcp.domain.models import (
    MemorySuggestBatchItemInput,
    MemoryUpdateCandidateInput,
)

__all__ = ["MEMORY_USAGE_GUIDE", "MemoryToolService"]


class MemoryToolService(MemoryToolApplicationServiceBase):
    def __init__(
        self,
        *,
        gateway: MemoryGatewayPort,
        settings: MemoryMcpSettings,
        policy: MemoryPolicyService | None = None,
    ) -> None:
        super().__init__(gateway=gateway, settings=settings, policy=policy)
        handler_kwargs = {
            "gateway": self._gateway,
            "settings": self._settings,
            "policy": self._policy,
        }
        self._query_service = MemoryToolQueryService(**handler_kwargs)
        self._fact_service = MemoryToolFactService(**handler_kwargs)
        self._suggestion_service = MemoryToolSuggestionService(**handler_kwargs)
        self._context_link_service = MemoryToolContextLinkService(**handler_kwargs)
        self._lifecycle_service = MemoryToolLifecycleService(**handler_kwargs)

    async def status(self) -> dict[str, Any]:
        return await self._query_service.status()

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
        return await self._query_service.search(
            query=query,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            memory_scope_external_refs=memory_scope_external_refs,
            thread_external_ref=thread_external_ref,
            token_budget=token_budget,
            max_facts=max_facts,
            max_chunks=max_chunks,
            category=category,
            tags_any=tags_any,
            tags_all=tags_all,
            tags_none=tags_none,
        )

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
        return await self._query_service.digest(
            topic=topic,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            memory_scope_external_refs=memory_scope_external_refs,
            thread_external_ref=thread_external_ref,
            token_budget=token_budget,
            max_facts=max_facts,
            max_chunks=max_chunks,
            max_suggestions=max_suggestions,
            include_pending_suggestions=include_pending_suggestions,
            include_superseded=include_superseded,
            include_related=include_related,
        )

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
        return await self._query_service.insights(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            memory_scope_external_refs=memory_scope_external_refs,
            thread_external_ref=thread_external_ref,
            max_facts=max_facts,
            max_documents=max_documents,
            max_episodes=max_episodes,
            max_suggestions=max_suggestions,
            max_captures=max_captures,
            max_activity=max_activity,
        )

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
        return await self._fact_service.remember_fact(
            text=text,
            kind=kind,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
            classification=classification,
            category=category,
            tags=tags,
            ttl_policy=ttl_policy,
            idempotency_key=idempotency_key,
        )

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
        return await self._fact_service.list_facts(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            status=status,
            category=category,
            tag=tag,
            limit=limit,
            cursor=cursor,
        )

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
        return await self._fact_service.browse_scope(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            limit=limit,
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

    async def get_fact(self, *, fact_id: str) -> dict[str, Any]:
        return await self._fact_service.get_fact(
            fact_id=fact_id,
        )

    async def get_related_facts(
        self,
        *,
        fact_id: str,
        limit: int = 10,
        include_other_threads: bool = False,
    ) -> dict[str, Any]:
        return await self._fact_service.get_related_facts(
            fact_id=fact_id,
            limit=limit,
            include_other_threads=include_other_threads,
        )

    async def link_facts(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: str = "related_to",
        reason: str,
    ) -> dict[str, Any]:
        return await self._fact_service.link_facts(
            source_fact_id=source_fact_id,
            target_fact_id=target_fact_id,
            relation_type=relation_type,
            reason=reason,
        )

    async def list_fact_relations(
        self,
        *,
        fact_id: str,
        status: str | None = "active",
        limit: int = 50,
    ) -> dict[str, Any]:
        return await self._fact_service.list_fact_relations(
            fact_id=fact_id,
            status=status,
            limit=limit,
        )

    async def unlink_fact_relation(self, *, relation_id: str) -> dict[str, Any]:
        return await self._fact_service.unlink_fact_relation(
            relation_id=relation_id,
        )

    async def list_fact_versions(self, *, fact_id: str) -> dict[str, Any]:
        return await self._fact_service.list_fact_versions(
            fact_id=fact_id,
        )

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
        return await self._fact_service.update_fact(
            fact_id=fact_id,
            expected_version=expected_version,
            text=text,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
        )

    async def forget_fact(self, *, fact_id: str) -> dict[str, Any]:
        return await self._fact_service.forget_fact(
            fact_id=fact_id,
        )

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
        return await self._suggestion_service.suggest_fact(
            candidate_text=candidate_text,
            kind=kind,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
            confidence=confidence,
            trust_level=trust_level,
            safe_reason=safe_reason,
        )

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
        return await self._suggestion_service.suggest_facts_batch(
            items=items,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
            continue_on_error=continue_on_error,
        )

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
        return await self._suggestion_service.propose_updates(
            candidates=candidates,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_id=source_id,
            quote_preview=quote_preview,
            dry_run=dry_run,
            user_confirmed=user_confirmed,
        )

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
        return await self._suggestion_service.list_suggestions(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            status=status,
            operation=operation,
            category=category,
            tag=tag,
            limit=limit,
        )

    async def approve_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._suggestion_service.approve_suggestion(
            suggestion_id=suggestion_id,
            reason=reason,
            force=force,
        )

    async def reject_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await self._suggestion_service.reject_suggestion(
            suggestion_id=suggestion_id,
            reason=reason,
        )

    async def expire_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return await self._suggestion_service.expire_suggestion(
            suggestion_id=suggestion_id,
            reason=reason,
        )

    async def review_suggestion(
        self,
        *,
        suggestion_id: str,
        action: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._suggestion_service.review_suggestion(
            suggestion_id=suggestion_id,
            action=action,
            reason=reason,
            force=force,
        )

    async def review_suggestions_batch(
        self,
        *,
        items: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        return await self._suggestion_service.review_suggestions_batch(
            items=items,
            continue_on_error=continue_on_error,
        )

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
        return await self._context_link_service.suggest_context_links(
            text=text,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_id=source_id,
            limit=limit,
            persist=persist,
        )

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
        return await self._context_link_service.list_context_links(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            source_type=source_type,
            source_id=source_id,
            status=status,
            statuses=statuses,
            limit=limit,
        )

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
        return await self._context_link_service.list_context_link_suggestions(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            source_type=source_type,
            source_id=source_id,
            status=status,
            statuses=statuses,
            limit=limit,
        )

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
        return await self._context_link_service.review_context_link_suggestion(
            suggestion_id=suggestion_id,
            action=action,
            reason=reason,
            target_type=target_type,
            target_id=target_id,
            relation_type=relation_type,
            confidence=confidence,
            link_reason=link_reason,
        )

    async def review_context_link_suggestions_batch(
        self,
        *,
        items: list[dict[str, Any]],
        continue_on_error: bool = False,
    ) -> dict[str, Any]:
        return await self._context_link_service.review_context_link_suggestions_batch(
            items=items,
            continue_on_error=continue_on_error,
        )

    async def list_captures(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        status: str | None = None,
        consolidation_status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return await self._lifecycle_service.list_captures(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            status=status,
            consolidation_status=consolidation_status,
            limit=limit,
        )

    async def consolidate_capture(
        self,
        *,
        capture_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        return await self._lifecycle_service.consolidate_capture(
            capture_id=capture_id,
            force=force,
        )

    async def export_graph(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        include_deleted: bool = False,
        include_restricted: bool = False,
        max_facts: int = 250,
        max_documents: int = 100,
        max_episodes: int = 100,
        max_chunks: int = 500,
    ) -> dict[str, Any]:
        return await self._lifecycle_service.export_graph(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            include_deleted=include_deleted,
            include_restricted=include_restricted,
            max_facts=max_facts,
            max_documents=max_documents,
            max_episodes=max_episodes,
            max_chunks=max_chunks,
        )

    async def export_memory_scope_snapshot(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        redacted: bool = True,
    ) -> dict[str, Any]:
        return await self._lifecycle_service.export_memory_scope_snapshot(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            redacted=redacted,
        )

    async def import_memory_scope_snapshot(
        self,
        *,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        dry_run: bool = True,
        merge_strategy: str = "fail_on_conflict",
        confirmed: bool = False,
        source_name: str = "mcp-memory_scope-snapshot",
    ) -> dict[str, Any]:
        return await self._lifecycle_service.import_memory_scope_snapshot(
            snapshot=snapshot,
            manifest=manifest,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            dry_run=dry_run,
            merge_strategy=merge_strategy,
            confirmed=confirmed,
            source_name=source_name,
        )

    async def preview_memory_scope_snapshot_import(
        self,
        *,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        merge_strategy: str = "fail_on_conflict",
    ) -> dict[str, Any]:
        return await self._lifecycle_service.preview_memory_scope_snapshot_import(
            snapshot=snapshot,
            manifest=manifest,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            merge_strategy=merge_strategy,
        )

    async def ingest_document(
        self,
        *,
        title: str,
        text: str,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        source_type: str = "document",
        source_external_id: str | None = None,
        classification: str = "unknown",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await self._lifecycle_service.ingest_document(
            title=title,
            text=text,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            thread_external_ref=thread_external_ref,
            source_type=source_type,
            source_external_id=source_external_id,
            classification=classification,
            idempotency_key=idempotency_key,
        )
