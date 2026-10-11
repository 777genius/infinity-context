"""Pure, ordered keyword admission policy; diagnostic reasons contain no evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.use_cases.build_context_keyword_aggregation import (
    _keyword_anchor_conflict_allowed,
)


@dataclass(frozen=True)
class KeywordAdmission:
    reason: Literal["project_identity", "anchor_conflict", "insufficient_relevance", "admitted"]
    best_query: tuple[str, str, QueryRelevance] | None = None


def admit_keyword_chunk(
    *,
    query: str,
    text: str,
    anchor_intent: QueryAnchorIntent,
    best_query: Callable[[], tuple[str, str, QueryRelevance]],
) -> KeywordAdmission:
    # Preserve short circuiting: mismatched projects never calculate relevance.
    if has_project_identity_mismatch(query=query, text=text):
        return KeywordAdmission("project_identity")
    best = best_query()
    expansion_query, expansion_reason, relevance = best
    if query_anchor_intent_text_conflicts(anchor_intent, text) and not (
        _keyword_anchor_conflict_allowed(
            expansion_reason=expansion_reason, relevance=relevance, text=text
        )
    ):
        return KeywordAdmission("anchor_conflict", best)
    if not is_chunk_candidate_relevance_sufficient(
        query=expansion_query, text=text, relevance=relevance
    ):
        return KeywordAdmission("insufficient_relevance", best)
    return KeywordAdmission("admitted", best)
