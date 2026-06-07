"""Ports used by the Memo Stack MCP application service."""

from __future__ import annotations

from typing import Any, Protocol

from memo_stack_mcp.domain.models import MemoryReadScope, MemoryScope, SourceRef


class MemoryGatewayPort(Protocol):
    async def health(self) -> dict[str, Any]: ...

    async def capabilities(self) -> dict[str, Any]: ...

    async def build_context(
        self,
        *,
        scope: MemoryReadScope,
        query: str,
        token_budget: int,
        max_facts: int,
        max_chunks: int,
        category: str | None = None,
        tags_any: list[str] | None = None,
        tags_all: list[str] | None = None,
        tags_none: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def build_digest(
        self,
        *,
        scope: MemoryReadScope,
        topic: str,
        token_budget: int,
        max_facts: int,
        max_chunks: int,
        max_suggestions: int,
        include_pending_suggestions: bool,
        include_superseded: bool,
        include_related: bool,
    ) -> dict[str, Any]: ...

    async def build_insights(
        self,
        *,
        scope: MemoryReadScope,
        max_facts: int,
        max_documents: int,
        max_suggestions: int,
        max_captures: int,
        max_activity: int,
    ) -> dict[str, Any]: ...

    async def export_graph(
        self,
        *,
        scope: MemoryScope,
        include_deleted: bool,
        include_restricted: bool,
        max_facts: int,
        max_documents: int,
        max_chunks: int,
    ) -> dict[str, Any]: ...

    async def export_profile_snapshot(
        self,
        *,
        scope: MemoryScope,
        redacted: bool,
    ) -> dict[str, Any]: ...

    async def import_profile_snapshot(
        self,
        *,
        scope: MemoryScope,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None,
        dry_run: bool,
        merge_strategy: str,
        confirmed: bool,
        source_name: str,
    ) -> dict[str, Any]: ...

    async def preview_profile_snapshot_import(
        self,
        *,
        scope: MemoryScope,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None,
        merge_strategy: str,
    ) -> dict[str, Any]: ...

    async def remember_fact(
        self,
        *,
        scope: MemoryScope,
        text: str,
        kind: str,
        source_refs: list[SourceRef],
        classification: str,
        idempotency_key: str,
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
    ) -> dict[str, Any]: ...

    async def list_facts(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        limit: int,
        cursor: str | None,
        category: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]: ...

    async def get_fact(self, *, fact_id: str) -> dict[str, Any]: ...

    async def get_related_facts(
        self,
        *,
        fact_id: str,
        limit: int,
        include_other_threads: bool,
    ) -> dict[str, Any]: ...

    async def link_facts(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: str,
        reason: str,
    ) -> dict[str, Any]: ...

    async def list_fact_relations(
        self,
        *,
        fact_id: str,
        status: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    async def unlink_fact_relation(self, *, relation_id: str) -> dict[str, Any]: ...

    async def list_fact_versions(self, *, fact_id: str) -> dict[str, Any]: ...

    async def update_fact(
        self,
        *,
        fact_id: str,
        expected_version: int,
        text: str,
        reason: str,
        source_refs: list[SourceRef],
    ) -> dict[str, Any]: ...

    async def forget_fact(self, *, fact_id: str) -> dict[str, Any]: ...

    async def create_suggestion(
        self,
        *,
        scope: MemoryScope,
        candidate_text: str,
        kind: str,
        source_refs: list[SourceRef],
        confidence: str,
        trust_level: str,
        safe_reason: str,
        category: str | None = None,
        tags: list[str] | None = None,
        ttl_policy: str | None = None,
        review_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def create_suggestions_batch(
        self,
        *,
        scope: MemoryScope,
        items: list[dict[str, Any]],
        continue_on_error: bool,
    ) -> dict[str, Any]: ...

    async def list_suggestions(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    async def approve_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
        force: bool,
    ) -> dict[str, Any]: ...

    async def review_suggestions_batch(
        self,
        *,
        items: list[dict[str, Any]],
        continue_on_error: bool,
    ) -> dict[str, Any]: ...

    async def reject_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
    ) -> dict[str, Any]: ...

    async def expire_suggestion(
        self,
        *,
        suggestion_id: str,
        reason: str | None,
    ) -> dict[str, Any]: ...

    async def list_captures(
        self,
        *,
        scope: MemoryScope,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    async def consolidate_capture(
        self,
        *,
        capture_id: str,
        force: bool,
    ) -> dict[str, Any]: ...

    async def ingest_document(
        self,
        *,
        scope: MemoryScope,
        title: str,
        text: str,
        source_type: str,
        source_external_id: str,
        classification: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...
