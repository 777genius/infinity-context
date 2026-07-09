"""MCP request-schema aliases for memory tool registration."""

from __future__ import annotations

from typing import Literal

MemoryKind = Literal["note", "architecture_decision", "constraint", "user_preference"]
MemoryClassification = Literal["public", "internal", "restricted", "unknown"]
FactStatus = Literal["active", "superseded", "disputed", "deleted"]
FactRelationType = Literal[
    "supports",
    "supersedes",
    "contradicts",
    "duplicates",
    "references",
    "depends_on",
    "related_to",
]
FactRelationStatus = Literal["active", "deleted"]
SuggestionStatus = Literal["pending", "approved", "rejected", "expired"]
SuggestionOperation = Literal["add", "update", "delete", "review"]
ContextLinkStatus = Literal["active", "deleted"]
ContextLinkSuggestionStatus = Literal["pending", "approved", "rejected", "expired"]
ContextLinkReviewAction = Literal["approve", "reject", "expire"]
CaptureStatus = Literal["accepted", "rejected", "redacted", "purged"]
MemoryBrowserThreadStatus = Literal["active", "deleted"]
MemoryBrowserEpisodeStatus = Literal["active", "deleted"]
MemoryBrowserDocumentStatus = Literal["active", "deleted"]
MemoryBrowserChunkStatus = Literal["active", "deleted"]
MemoryBrowserExtractionStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "unsupported",
    "canceled",
    "stale",
]
MemoryBrowserAssetStatus = Literal["stored", "deleted"]
MemoryBrowserAnchorStatus = Literal["active", "deleted"]
CaptureConsolidationStatus = Literal[
    "not_required",
    "pending",
    "running",
    "consolidated",
    "retry_pending",
    "dead",
    "skipped",
]
ConfidenceValue = Literal["low", "medium", "high"]
ReviewAction = Literal["approve", "reject", "expire"]
MemoryScopeSnapshotMergeStrategy = Literal[
    "fail_on_conflict",
    "skip_existing",
    "create_new_memory_scope",
    "supersede_matching_facts",
]
SourceType = Literal[
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
]
