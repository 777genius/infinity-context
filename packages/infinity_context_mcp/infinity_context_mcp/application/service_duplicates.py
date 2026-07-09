"""Duplicate and conflict preflight helpers for MCP application services."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application.semantic_dedupe import (
    FactConflictMatch,
    describe_conflicting_fact_match,
    looks_equivalent_fact,
)

from infinity_context_mcp.application.service_helpers import normalize_candidate, payload_items
from infinity_context_mcp.domain.models import MemoryScope


class MemoryToolDuplicateMixin:
    async def _find_duplicate(
        self,
        scope: MemoryScope,
        text: str,
    ) -> tuple[str, str, dict[str, Any]] | None:
        normalized = normalize_candidate(text)
        facts = await self._gateway.list_facts(scope=scope, status="active", limit=50, cursor=None)
        possible_conflict: tuple[str, dict[str, Any]] | None = None
        for item in payload_items(facts):
            item_text = str(item.get("text", ""))
            item_id = str(item.get("id") or item.get("fact_id") or "")
            if normalize_candidate(item_text) == normalized:
                return ("duplicate", item_id, {})
            if looks_equivalent_fact(text, item_text):
                return ("duplicate", item_id, {})
            conflict_match = describe_conflicting_fact_match(text, item_text)
            if possible_conflict is None and conflict_match is not None:
                possible_conflict = (item_id, _conflict_review_payload(conflict_match))
        suggestions = await self._gateway.list_suggestions(
            scope=scope,
            status="pending",
            operation=None,
            category=None,
            tag=None,
            limit=50,
        )
        for item in payload_items(suggestions):
            candidate_text = str(item.get("candidate_text") or item.get("text") or "")
            if normalize_candidate(candidate_text) == normalized:
                return ("duplicate", str(item.get("id") or item.get("suggestion_id") or ""), {})
            if looks_equivalent_fact(text, candidate_text):
                return ("duplicate", str(item.get("id") or item.get("suggestion_id") or ""), {})
        if possible_conflict is not None:
            conflict_id, conflict_payload = possible_conflict
            return ("conflict", conflict_id, conflict_payload)
        return None


def _conflict_review_payload(match: FactConflictMatch) -> dict[str, Any]:
    return {
        "conflict_match_type": match.match_type,
        "conflict_score": match.score,
        "conflict_reason_codes": list(match.reason_codes),
        "conflict_overlap_terms": list(match.overlap_terms),
    }
