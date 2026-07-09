"""Capture, graph, snapshot, and document lifecycle operations for MCP memory tools."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from infinity_context_mcp.application.service_base import MemoryToolApplicationServiceBase
from infinity_context_mcp.application.service_constants import (
    CAPTURE_CONSOLIDATION_STATUSES,
    CAPTURE_STATUSES,
    CLASSIFICATIONS,
    MEMORY_SCOPE_SNAPSHOT_MERGE_STRATEGIES,
)
from infinity_context_mcp.application.service_helpers import (
    clamp_int,
    ensure_bool,
    ensure_choice,
    stable_key,
)
from infinity_context_mcp.domain.models import MemoryGatewayError
from infinity_context_mcp.domain.policy import MemoryPolicyOperation


class MemoryToolLifecycleService(MemoryToolApplicationServiceBase):
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
        async def action() -> dict[str, Any]:
            if status is not None:
                ensure_choice("status", status, CAPTURE_STATUSES)
            if consolidation_status is not None:
                ensure_choice(
                    "consolidation_status",
                    consolidation_status,
                    CAPTURE_CONSOLIDATION_STATUSES,
                )
            effective_limit, warnings = clamp_int(
                name="limit",
                value=limit,
                minimum=1,
                maximum=500,
            )
            payload = await self._gateway.list_captures(
                scope=self._scope(space_slug, memory_scope_external_ref, thread_external_ref),
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
            ensure_bool("force", force)
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
        memory_scope_external_ref: str | None = None,
        thread_external_ref: str | None = None,
        include_deleted: bool = False,
        include_restricted: bool = False,
        max_facts: int = 250,
        max_documents: int = 100,
        max_episodes: int = 100,
        max_chunks: int = 500,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_bool("include_deleted", include_deleted)
            ensure_bool("include_restricted", include_restricted)
            bounded_facts, fact_warnings = clamp_int(
                name="max_facts",
                value=max_facts,
                minimum=0,
                maximum=1_000,
            )
            bounded_documents, document_warnings = clamp_int(
                name="max_documents",
                value=max_documents,
                minimum=0,
                maximum=500,
            )
            bounded_episodes, episode_warnings = clamp_int(
                name="max_episodes",
                value=max_episodes,
                minimum=0,
                maximum=500,
            )
            bounded_chunks, chunk_warnings = clamp_int(
                name="max_chunks",
                value=max_chunks,
                minimum=0,
                maximum=2_000,
            )
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            payload = await self._gateway.export_graph(
                scope=scope,
                include_deleted=include_deleted,
                include_restricted=include_restricted,
                max_facts=bounded_facts,
                max_documents=bounded_documents,
                max_episodes=bounded_episodes,
                max_chunks=bounded_chunks,
            )
            return self._ok(
                "Portable canonical memory graph exported.",
                data=payload.get("data", payload),
                scope=asdict(scope),
                side_effects=[],
                warnings=[*fact_warnings, *document_warnings, *episode_warnings, *chunk_warnings],
            )

        return await self._guard(action)

    async def export_memory_scope_snapshot(
        self,
        *,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        redacted: bool = True,
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            ensure_bool("redacted", redacted)
            scope = self._scope(space_slug, memory_scope_external_ref, None)
            payload = await self._gateway.export_memory_scope_snapshot(
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
                "Portable memory_scope memory snapshot exported.",
                data=data,
                scope=asdict(scope),
                side_effects=[],
                warnings=[] if status == "ok" else [status],
            )

        return await self._guard(action)

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
        async def action() -> dict[str, Any]:
            if not isinstance(snapshot, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message="snapshot must be a JSON object",
                    retryable=False,
                )
            if manifest is not None and not isinstance(manifest, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message="manifest must be a JSON object when provided",
                    retryable=False,
                )
            ensure_bool("dry_run", dry_run)
            ensure_bool("confirmed", confirmed)
            ensure_choice(
                "merge_strategy",
                merge_strategy,
                MEMORY_SCOPE_SNAPSHOT_MERGE_STRATEGIES,
            )
            normalized_source_name = (source_name.strip() or "mcp-memory_scope-snapshot")[:160]
            scope = self._scope(space_slug, memory_scope_external_ref, None)
            policy = None
            side_effects: list[str] = []
            if not dry_run:
                if not confirmed:
                    raise MemoryGatewayError(
                        status_code=403,
                        code="infinity_context_mcp.policy.explicit_confirmation_required",
                        message="MemoryScope snapshot import requires confirmed=true",
                        retryable=False,
                    )
                policy = self._decide_policy(
                    operation=MemoryPolicyOperation.REVIEW,
                    text=f"memory_scope_snapshot_import:{normalized_source_name}",
                    source_type="memory_scope_snapshot",
                    user_confirmed=True,
                )
                side_effects.append("imported_memory_scope_snapshot")
            payload = await self._gateway.import_memory_scope_snapshot(
                scope=scope,
                snapshot=snapshot,
                manifest=manifest,
                dry_run=dry_run,
                merge_strategy=merge_strategy,
                confirmed=confirmed,
                source_name=normalized_source_name,
            )
            return self._ok(
                "MemoryScope memory snapshot import checked."
                if dry_run
                else "MemoryScope memory snapshot imported.",
                data=payload.get("data", payload),
                scope=asdict(scope),
                policy=self._policy_payload(policy) if policy is not None else None,
                side_effects=side_effects,
            )

        return await self._guard(action)

    async def preview_memory_scope_snapshot_import(
        self,
        *,
        snapshot: dict[str, Any],
        manifest: dict[str, Any] | None = None,
        space_slug: str | None = None,
        memory_scope_external_ref: str | None = None,
        merge_strategy: str = "fail_on_conflict",
    ) -> dict[str, Any]:
        async def action() -> dict[str, Any]:
            if not isinstance(snapshot, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message="snapshot must be a JSON object",
                    retryable=False,
                )
            if manifest is not None and not isinstance(manifest, dict):
                raise MemoryGatewayError(
                    status_code=400,
                    code="infinity_context_mcp.validation.invalid_input",
                    message="manifest must be a JSON object when provided",
                    retryable=False,
                )
            ensure_choice(
                "merge_strategy",
                merge_strategy,
                MEMORY_SCOPE_SNAPSHOT_MERGE_STRATEGIES,
            )
            scope = self._scope(space_slug, memory_scope_external_ref, None)
            payload = await self._gateway.preview_memory_scope_snapshot_import(
                scope=scope,
                snapshot=snapshot,
                manifest=manifest,
                merge_strategy=merge_strategy,
            )
            return self._ok(
                "MemoryScope memory snapshot import preview built.",
                data=payload.get("data", payload),
                scope=asdict(scope),
                side_effects=[],
            )

        return await self._guard(action)

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
        async def action() -> dict[str, Any]:
            ensure_choice("classification", classification, CLASSIFICATIONS)
            scope = self._scope(space_slug, memory_scope_external_ref, thread_external_ref)
            policy = self._decide_policy(
                operation=MemoryPolicyOperation.INGEST_DOCUMENT,
                text=text,
                source_type=source_type,
                text_length=len(text),
            )
            safe_source_id = source_external_id or stable_key("mcp-doc-source", scope, title, text)
            safe_key = idempotency_key or stable_key("mcp-doc", scope, safe_source_id, text)
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
