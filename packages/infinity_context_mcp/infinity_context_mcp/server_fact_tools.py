"""FastMCP fact, suggestion, and capture tool registrations."""

from __future__ import annotations

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from infinity_context_mcp.application.service import MemoryToolService
from infinity_context_mcp.domain.models import (
    MemoryCaptureListResponse,
    MemoryCaptureMutationResponse,
    MemoryFactListResponse,
    MemoryFactMutationResponse,
    MemoryFactRelationResponse,
    MemoryFactRelationsResponse,
    MemoryFactResponse,
    MemoryProposalResponse,
    MemoryRelatedFactsResponse,
    MemoryReviewSuggestionBatchItemInput,
    MemoryReviewSuggestionResponse,
    MemoryReviewSuggestionsBatchResponse,
    MemorySuggestBatchItemInput,
    MemorySuggestBatchResponse,
    MemorySuggestionListResponse,
    MemoryUpdateCandidateInput,
)
from infinity_context_mcp.server_request_mapping import (
    CaptureConsolidationStatus,
    CaptureStatus,
    ConfidenceValue,
    FactRelationStatus,
    FactRelationType,
    FactStatus,
    MemoryClassification,
    MemoryKind,
    ReviewAction,
    SourceType,
    SuggestionOperation,
    SuggestionStatus,
)
from infinity_context_mcp.server_response import tool_response as _tool_response


def register_memory_fact_tools(mcp: FastMCP, tool_service: MemoryToolService) -> None:
    @mcp.tool(
        name="memory_remember_fact",
        title="Remember Fact",
        description=(
            "Persist a stable fact, preference, constraint, or architecture decision. Do not "
            "store secrets. Use only for explicit confirmed durable facts. Prefer "
            "memory_update_fact when replacing an existing fact, and use suggestions/proposals "
            "for uncertain or agent-inferred memory. Preserve exact identifiers, project names, "
            "file paths, version labels, URLs, and quoted durable fact wording."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_remember_fact(
        text: Annotated[
            str,
            Field(min_length=1, max_length=4000, description="Durable fact text to remember."),
        ],
        kind: Annotated[
            MemoryKind,
            Field(
                default="note",
                description=(
                    "Fact kind: note, architecture_decision, constraint, or user_preference."
                ),
            ),
        ] = "note",
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        source_type: Annotated[
            SourceType | None,
            Field(default=None, description="Evidence source type, e.g. ai_response or manual."),
        ] = None,
        source_id: Annotated[
            str | None,
            Field(
                default=None,
                min_length=1,
                max_length=240,
                description="Stable source/event id if the caller has one.",
            ),
        ] = None,
        quote_preview: Annotated[
            str | None,
            Field(default=None, max_length=240, description="Short evidence preview."),
        ] = None,
        classification: Annotated[
            MemoryClassification,
            Field(default="internal", description="public, internal, restricted, or unknown."),
        ] = "internal",
        category: Annotated[
            str | None,
            Field(
                default=None,
                max_length=80,
                description="Optional normalized memory category, e.g. architecture.",
            ),
        ] = None,
        tags: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=48)]] | None,
            Field(
                default=None,
                max_length=10,
                description="Optional memory tags for later filtering.",
            ),
        ] = None,
        ttl_policy: Annotated[
            str | None,
            Field(default=None, max_length=80, description="Optional TTL policy name."),
        ] = None,
        idempotency_key: Annotated[
            str | None,
            Field(
                default=None,
                min_length=1,
                max_length=240,
                description="Stable key to make retries safe.",
            ),
        ] = None,
    ) -> Annotated[CallToolResult, MemoryFactMutationResponse]:
        return _tool_response(
            await tool_service.remember_fact(
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
            ),
            MemoryFactMutationResponse,
        )

    @mcp.tool(
        name="memory_list_facts",
        title="List Facts",
        description="List facts in one memory scope for audit, management, or update discovery.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_list_facts(
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        status: Annotated[
            FactStatus | None,
            Field(default="active", description="active, superseded, disputed, deleted, or null."),
        ] = "active",
        category: Annotated[str | None, Field(default=None, max_length=80)] = None,
        tag: Annotated[str | None, Field(default=None, max_length=48)] = None,
        limit: Annotated[int, Field(default=50, ge=1, le=500)] = 50,
        cursor: Annotated[str | None, Field(default=None, min_length=1, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryFactListResponse]:
        return _tool_response(
            await tool_service.list_facts(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
                status=status,
                category=category,
                tag=tag,
                limit=limit,
                cursor=cursor,
            ),
            MemoryFactListResponse,
        )

    @mcp.tool(
        name="memory_get_fact",
        title="Get Fact",
        description="Load one fact by fact_id, including current version and source refs.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_get_fact(
        fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Canonical fact id.")
        ],
    ) -> Annotated[CallToolResult, MemoryFactResponse]:
        return _tool_response(await tool_service.get_fact(fact_id=fact_id), MemoryFactResponse)

    @mcp.tool(
        name="memory_related_facts",
        title="Related Facts",
        description=(
            "Load facts related to one canonical fact with explainable relation_reasons. "
            "Use this after memory_search or memory_get_fact when auditing, updating, "
            "deleting, or summarizing adjacent project memory. By default it stays inside "
            "the same thread/memory_scope-wide scope; include_other_threads must be explicit."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_related_facts(
        fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Canonical fact id.")
        ],
        limit: Annotated[int, Field(default=10, ge=1, le=50)] = 10,
        include_other_threads: Annotated[
            bool,
            Field(
                default=False,
                description="Include other thread-scoped facts from the same memory_scope.",
            ),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryRelatedFactsResponse]:
        return _tool_response(
            await tool_service.get_related_facts(
                fact_id=fact_id,
                limit=limit,
                include_other_threads=include_other_threads,
            ),
            MemoryRelatedFactsResponse,
        )

    @mcp.tool(
        name="memory_link_facts",
        title="Link Facts",
        description=(
            "Create a durable typed relation between two canonical facts. Use this when the "
            "relationship itself should be remembered, for example supports, supersedes, "
            "contradicts, duplicates, references, depends_on, or related_to. First load both "
            "facts with memory_search or memory_get_fact and pass exact fact ids, not raw text."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_link_facts(
        source_fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Source fact id.")
        ],
        target_fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Target fact id.")
        ],
        relation_type: Annotated[
            FactRelationType,
            Field(default="related_to", description="Typed relation to persist."),
        ] = "related_to",
        reason: Annotated[
            str,
            Field(min_length=1, max_length=320, description="Short source-backed reason."),
        ] = "agent linked related facts",
    ) -> Annotated[CallToolResult, MemoryFactRelationResponse]:
        return _tool_response(
            await tool_service.link_facts(
                source_fact_id=source_fact_id,
                target_fact_id=target_fact_id,
                relation_type=relation_type,
                reason=reason,
            ),
            MemoryFactRelationResponse,
        )

    @mcp.tool(
        name="memory_list_fact_relations",
        title="List Fact Relations",
        description=(
            "List durable typed incoming and outgoing relations for one canonical fact. Use this "
            "when auditing why facts are connected or before changing linked memory."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_list_fact_relations(
        fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Canonical fact id.")
        ],
        status: Annotated[FactRelationStatus | None, Field(default="active")] = "active",
        limit: Annotated[int, Field(default=50, ge=1, le=100)] = 50,
    ) -> Annotated[CallToolResult, MemoryFactRelationsResponse]:
        return _tool_response(
            await tool_service.list_fact_relations(fact_id=fact_id, status=status, limit=limit),
            MemoryFactRelationsResponse,
        )

    @mcp.tool(
        name="memory_unlink_fact_relation",
        title="Unlink Fact Relation",
        description=(
            "Soft-delete one durable fact relation by relation_id. This does not delete either "
            "fact. It is destructive metadata cleanup and follows delete policy."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_unlink_fact_relation(
        relation_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Fact relation id.")
        ],
    ) -> Annotated[CallToolResult, MemoryFactRelationResponse]:
        return _tool_response(
            await tool_service.unlink_fact_relation(relation_id=relation_id),
            MemoryFactRelationResponse,
        )

    @mcp.tool(
        name="memory_list_fact_versions",
        title="List Fact Versions",
        description=(
            "Load all stored versions for one fact_id before auditing or resolving updates."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_list_fact_versions(
        fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Canonical fact id.")
        ],
    ) -> Annotated[CallToolResult, MemoryFactListResponse]:
        return _tool_response(
            await tool_service.list_fact_versions(fact_id=fact_id),
            MemoryFactListResponse,
        )

    @mcp.tool(
        name="memory_update_fact",
        title="Update Fact",
        description=(
            "Update a known fact by fact_id using optimistic locking. You must pass the "
            "current expected_version from memory_get_fact, memory_list_facts, or a prior "
            "memory_search result. Prefer this over memory_propose_updates when the user "
            "explicitly confirms that an existing current fact changed, so the old active fact "
            "is superseded immediately. Do not use this for a new fact."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_update_fact(
        fact_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Canonical fact id.")
        ],
        expected_version: Annotated[
            int,
            Field(ge=1, description="Current version to update from."),
        ],
        text: Annotated[str, Field(min_length=1, max_length=4000, description="Replacement fact.")],
        reason: Annotated[str, Field(min_length=1, max_length=240, description="Why it changed.")],
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, min_length=1, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
    ) -> Annotated[CallToolResult, MemoryFactMutationResponse]:
        return _tool_response(
            await tool_service.update_fact(
                fact_id=fact_id,
                expected_version=expected_version,
                text=text,
                reason=reason,
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
            ),
            MemoryFactMutationResponse,
        )

    @mcp.tool(
        name="memory_forget_fact",
        title="Forget Fact",
        description=(
            "Forget one fact by fact_id. This is destructive and hides the fact from future "
            "context retrieval. Use only when the fact is wrong, outdated, or should not be "
            "stored. Never pass user text or a search query as fact_id; if the user gives text, "
            "call memory_search or memory_list_facts first and use the returned concrete fact_id."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_forget_fact(
        fact_id: Annotated[
            str,
            Field(min_length=1, max_length=160, description="Canonical fact id to forget."),
        ],
    ) -> Annotated[CallToolResult, MemoryFactMutationResponse]:
        return _tool_response(
            await tool_service.forget_fact(fact_id=fact_id),
            MemoryFactMutationResponse,
        )

    @mcp.tool(
        name="memory_suggest_fact",
        title="Suggest Fact",
        description=(
            "Create a pending memory suggestion for review. Use this for unreviewed "
            "auto-memory, transcript-derived facts, or agent-inferred facts."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_suggest_fact(
        candidate_text: Annotated[
            str,
            Field(min_length=1, max_length=4000, description="Candidate fact text."),
        ],
        kind: Annotated[
            MemoryKind,
            Field(
                default="note",
                description=(
                    "Fact kind: note, architecture_decision, constraint, or user_preference."
                ),
            ),
        ] = "note",
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, min_length=1, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        confidence: Annotated[
            ConfidenceValue,
            Field(default="medium", description="low, medium, or high."),
        ] = "medium",
        trust_level: Annotated[
            ConfidenceValue,
            Field(default="medium", description="low, medium, or high."),
        ] = "medium",
        safe_reason: Annotated[
            str,
            Field(default="mcp_agent_suggestion_requires_review", min_length=1, max_length=320),
        ] = "mcp_agent_suggestion_requires_review",
    ) -> Annotated[CallToolResult, MemoryFactMutationResponse]:
        return _tool_response(
            await tool_service.suggest_fact(
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
            ),
            MemoryFactMutationResponse,
        )

    @mcp.tool(
        name="memory_suggest_facts_batch",
        title="Suggest Facts Batch",
        description=(
            "Create a bounded batch of pending memory suggestions for review. Use this for "
            "multiple unreviewed agent-inferred facts or transcript-derived facts. It does "
            "not activate memory; use memory_review_suggestions_batch after the user reviews "
            "the returned per-item suggestions."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_suggest_facts_batch(
        items: Annotated[
            list[MemorySuggestBatchItemInput],
            Field(min_length=1, max_length=50, description="Candidate suggestions."),
        ],
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, min_length=1, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        continue_on_error: Annotated[bool, Field(default=False)] = False,
    ) -> Annotated[CallToolResult, MemorySuggestBatchResponse]:
        return _tool_response(
            await tool_service.suggest_facts_batch(
                items=items,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                continue_on_error=continue_on_error,
            ),
            MemorySuggestBatchResponse,
        )

    @mcp.tool(
        name="memory_propose_updates",
        title="Propose Memory Updates",
        description=(
            "Process a batch of candidate memory changes through local MCP policy. Prefer this "
            "for agent-generated memory, uncertain claims, post-task review, or unreviewed "
            "auto-memory. Direct remember is acceptable only for explicit confirmed durable "
            "facts. This is a mutating tool: call memory_search or memory_get_fact first when "
            "candidates may duplicate, update, forget, or conflict with existing memory. For a "
            "single explicit confirmed update with a known fact_id and current version, prefer "
            "memory_update_fact instead of creating a review-only suggestion."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_propose_updates(
        candidates: Annotated[
            list[MemoryUpdateCandidateInput],
            Field(min_length=1, max_length=30, description="Candidate memory changes."),
        ],
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        source_type: Annotated[SourceType | None, Field(default=None)] = None,
        source_id: Annotated[str | None, Field(default=None, min_length=1, max_length=240)] = None,
        quote_preview: Annotated[str | None, Field(default=None, max_length=240)] = None,
        dry_run: Annotated[bool, Field(default=False)] = False,
        user_confirmed: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "Set true only when the user explicitly confirmed the candidate as a "
                    "durable current fact. Keep false for uncertain claims, guesses, rumors, "
                    "auto-memory, inferred facts, and review-needed candidates."
                ),
            ),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryProposalResponse]:
        return _tool_response(
            await tool_service.propose_updates(
                candidates=candidates,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
                source_type=source_type,
                source_id=source_id,
                quote_preview=quote_preview,
                dry_run=dry_run,
                user_confirmed=user_confirmed,
            ),
            MemoryProposalResponse,
        )

    @mcp.tool(
        name="memory_list_suggestions",
        title="List Suggestions",
        description="List pending or reviewed memory suggestions for a scope.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_list_suggestions(
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        status: Annotated[
            SuggestionStatus | None,
            Field(default="pending", description="pending, approved, rejected, expired, or null."),
        ] = "pending",
        operation: Annotated[
            SuggestionOperation | None,
            Field(default=None, description="Optional queue filter: add, update, delete, review."),
        ] = None,
        category: Annotated[
            str | None,
            Field(default=None, max_length=80, description="Optional normalized category filter."),
        ] = None,
        tag: Annotated[
            str | None,
            Field(default=None, max_length=48, description="Optional normalized tag filter."),
        ] = None,
        limit: Annotated[int, Field(default=50, ge=1, le=500)] = 50,
    ) -> Annotated[CallToolResult, MemorySuggestionListResponse]:
        return _tool_response(
            await tool_service.list_suggestions(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
                status=status,
                operation=operation,
                category=category,
                tag=tag,
                limit=limit,
            ),
            MemorySuggestionListResponse,
        )

    @mcp.tool(
        name="memory_list_captures",
        title="List Auto-Memory Captures",
        description=(
            "List redacted auto-memory capture diagnostics for the current scope. Use this for "
            "debugging hook ingestion, pending consolidation, and review queues. This tool "
            "does not expose raw hook payloads and does not make captured text active memory."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_list_captures(
        space_slug: Annotated[str | None, Field(default=None, min_length=1, max_length=160)] = None,
        memory_scope_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        thread_external_ref: Annotated[
            str | None,
            Field(default=None, min_length=1, max_length=160),
        ] = None,
        status: Annotated[
            CaptureStatus | None,
            Field(default=None, description="accepted, rejected, redacted, purged, or null."),
        ] = None,
        consolidation_status: Annotated[
            CaptureConsolidationStatus | None,
            Field(
                default=None,
                description=(
                    "not_required, pending, running, consolidated, retry_pending, dead, "
                    "skipped, or null."
                ),
            ),
        ] = None,
        limit: Annotated[int, Field(default=50, ge=1, le=500)] = 50,
    ) -> Annotated[CallToolResult, MemoryCaptureListResponse]:
        return _tool_response(
            await tool_service.list_captures(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
                thread_external_ref=thread_external_ref,
                status=status,
                consolidation_status=consolidation_status,
                limit=limit,
            ),
            MemoryCaptureListResponse,
        )

    @mcp.tool(
        name="memory_consolidate_capture",
        title="Consolidate Auto-Memory Capture",
        description=(
            "Run one accepted auto-memory capture through the review-gated consolidation path. "
            "The result creates pending suggestions, not active memory, unless a reviewer "
            "later approves them. Use for operator/debug workflows, not routine retrieval."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_consolidate_capture(
        capture_id: Annotated[
            str,
            Field(min_length=1, max_length=160, description="Canonical capture id."),
        ],
        force: Annotated[
            bool,
            Field(default=False, description="Re-run even when the capture was already handled."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryCaptureMutationResponse]:
        return _tool_response(
            await tool_service.consolidate_capture(capture_id=capture_id, force=force),
            MemoryCaptureMutationResponse,
        )

    @mcp.tool(
        name="memory_approve_suggestion",
        title="Approve Suggestion",
        description=(
            "Approve one pending memory suggestion by suggestion_id. Approval creates or "
            "updates canonical memory through the Infinity Context review policy."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_approve_suggestion(
        suggestion_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Suggestion id.")
        ],
        reason: Annotated[str | None, Field(default=None, max_length=320)] = None,
        force: Annotated[
            bool,
            Field(default=False, description="Allow explicit reviewer override."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryReviewSuggestionResponse]:
        return _tool_response(
            await tool_service.approve_suggestion(
                suggestion_id=suggestion_id,
                reason=reason,
                force=force,
            ),
            MemoryReviewSuggestionResponse,
        )

    @mcp.tool(
        name="memory_review_suggestion",
        title="Review Suggestion",
        description="Approve, reject, or expire one pending memory suggestion by suggestion_id.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_review_suggestion(
        suggestion_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Suggestion id.")
        ],
        action: Annotated[
            ReviewAction,
            Field(description="Review action: approve, reject, or expire."),
        ],
        reason: Annotated[str | None, Field(default=None, max_length=320)] = None,
        force: Annotated[
            bool,
            Field(default=False, description="Allow explicit reviewer override on approve."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryReviewSuggestionResponse]:
        return _tool_response(
            await tool_service.review_suggestion(
                suggestion_id=suggestion_id,
                action=action,
                reason=reason,
                force=force,
            ),
            MemoryReviewSuggestionResponse,
        )

    @mcp.tool(
        name="memory_review_suggestions_batch",
        title="Review Suggestions Batch",
        description=(
            "Approve, reject, or expire multiple pending memory suggestions in one bounded "
            "batch. Use after memory_list_suggestions or memory_digest when the user wants "
            "to review several suggestions at once. The result is per-item: one failed "
            "suggestion can stop the batch unless continue_on_error=true."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_review_suggestions_batch(
        items: Annotated[
            list[MemoryReviewSuggestionBatchItemInput],
            Field(min_length=1, max_length=50, description="Review actions to apply."),
        ],
        continue_on_error: Annotated[
            bool,
            Field(default=False, description="Continue after item-level failures."),
        ] = False,
    ) -> Annotated[CallToolResult, MemoryReviewSuggestionsBatchResponse]:
        return _tool_response(
            await tool_service.review_suggestions_batch(
                items=[item.model_dump(exclude_none=True) for item in items],
                continue_on_error=continue_on_error,
            ),
            MemoryReviewSuggestionsBatchResponse,
        )

    @mcp.tool(
        name="memory_reject_suggestion",
        title="Reject Suggestion",
        description="Reject one pending memory suggestion by suggestion_id.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_reject_suggestion(
        suggestion_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Suggestion id.")
        ],
        reason: Annotated[str | None, Field(default=None, max_length=320)] = None,
    ) -> Annotated[CallToolResult, MemoryReviewSuggestionResponse]:
        return _tool_response(
            await tool_service.reject_suggestion(suggestion_id=suggestion_id, reason=reason),
            MemoryReviewSuggestionResponse,
        )

    @mcp.tool(
        name="memory_expire_suggestion",
        title="Expire Suggestion",
        description="Expire one pending memory suggestion by suggestion_id.",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    async def memory_expire_suggestion(
        suggestion_id: Annotated[
            str, Field(min_length=1, max_length=160, description="Suggestion id.")
        ],
        reason: Annotated[str | None, Field(default=None, max_length=320)] = None,
    ) -> Annotated[CallToolResult, MemoryReviewSuggestionResponse]:
        return _tool_response(
            await tool_service.expire_suggestion(suggestion_id=suggestion_id, reason=reason),
            MemoryReviewSuggestionResponse,
        )