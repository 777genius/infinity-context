"""Structured query intent for anchor-aware context retrieval."""

from __future__ import annotations

from infinity_context_core.application.context_query_intent_contracts import (
    QueryAnchorHint,
    QueryAnchorIntent,
    QueryAnchorLookupKey,
    QueryAnchorMatch,
)
from infinity_context_core.application.context_query_intent_extraction import (
    build_query_anchor_intent,
    query_anchor_lookup_keys,
)
from infinity_context_core.application.context_query_intent_matching import (
    match_query_anchor_intent,
    match_query_anchor_intent_to_text,
    query_anchor_intent_conflicts,
    query_anchor_intent_text_conflicts,
)

__all__ = [
    "QueryAnchorHint",
    "QueryAnchorIntent",
    "QueryAnchorLookupKey",
    "QueryAnchorMatch",
    "build_query_anchor_intent",
    "match_query_anchor_intent",
    "match_query_anchor_intent_to_text",
    "query_anchor_intent_conflicts",
    "query_anchor_intent_text_conflicts",
    "query_anchor_lookup_keys",
]
