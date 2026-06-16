"""Constants shared by Memo Stack MCP application services."""

from __future__ import annotations

MEMORY_KINDS = {"note", "architecture_decision", "constraint", "user_preference"}
CLASSIFICATIONS = {"public", "internal", "restricted", "unknown"}
FACT_STATUSES = {"active", "superseded", "disputed", "deleted"}
FACT_RELATION_TYPES = {
    "supports",
    "supersedes",
    "contradicts",
    "duplicates",
    "references",
    "depends_on",
    "related_to",
}
FACT_RELATION_STATUSES = {"active", "deleted"}
SUGGESTION_STATUSES = {"pending", "approved", "rejected", "expired"}
SUGGESTION_OPERATIONS = {"add", "update", "delete", "review"}
MEMORY_BROWSER_THREAD_STATUSES = {"active", "deleted"}
MEMORY_BROWSER_EPISODE_STATUSES = {"active", "deleted"}
MEMORY_BROWSER_DOCUMENT_STATUSES = {"active", "deleted"}
MEMORY_BROWSER_CHUNK_STATUSES = {"active", "deleted"}
MEMORY_BROWSER_EXTRACTION_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "unsupported",
    "canceled",
    "stale",
}
MEMORY_BROWSER_ASSET_STATUSES = {"stored", "deleted"}
MEMORY_BROWSER_ANCHOR_STATUSES = {"active", "deleted"}
CAPTURE_STATUSES = {"accepted", "rejected", "redacted", "purged"}
CAPTURE_CONSOLIDATION_STATUSES = {
    "not_required",
    "pending",
    "running",
    "consolidated",
    "retry_pending",
    "dead",
    "skipped",
}
CONFIDENCE_VALUES = {"low", "medium", "high"}
TRUST_VALUES = {"low", "medium", "high"}
MEMORY_SCOPE_SNAPSHOT_MERGE_STRATEGIES = {
    "fail_on_conflict",
    "skip_existing",
    "create_new_memory_scope",
    "supersede_matching_facts",
}
UNCERTAIN_EVIDENCE_MARKERS = (
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
SOURCE_TYPES = {
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
