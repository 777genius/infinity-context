"""Shared agent behavior benchmark contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_TRANSCRIPT_CORPUS_MAX_FILES = 20
DEFAULT_TRANSCRIPT_CORPUS_MAX_BYTES = 200_000

WRITE_TOOLS = {
    "memory_remember_fact",
    "memory_update_fact",
    "memory_forget_fact",
    "memory_link_facts",
    "memory_unlink_fact_relation",
    "memory_suggest_fact",
    "memory_propose_updates",
    "memory_approve_suggestion",
    "memory_review_suggestion",
    "memory_reject_suggestion",
    "memory_expire_suggestion",
    "memory_ingest_document",
}

READ_BEFORE_WRITE_TOOLS = {
    "memory_search",
    "memory_list_facts",
    "memory_get_fact",
    "memory_related_facts",
    "memory_list_fact_relations",
    "memory_list_fact_versions",
}

DIRECT_WRITE_TOOLS = {
    "memory_remember_fact",
    "memory_update_fact",
    "memory_forget_fact",
    "memory_link_facts",
    "memory_unlink_fact_relation",
    "memory_ingest_document",
}


class AgentBenchFailure(RuntimeError):
    """Raised when benchmark setup or execution cannot continue."""


@dataclass(frozen=True)
class AgentBenchScenario:
    id: str
    category: str
    user_prompt: str
    tags: tuple[str, ...] = ()
    setup_actions: tuple[dict[str, Any], ...] = ()
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    forbidden_side_effects: tuple[str, ...] = ()
    required_tool_arg_checks: tuple[dict[str, Any], ...] = ()
    required_memory_checks: tuple[dict[str, Any], ...] = ()
    critical: bool = True
