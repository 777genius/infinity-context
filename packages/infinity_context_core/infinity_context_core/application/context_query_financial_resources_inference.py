"""Narrow retrieval evidence policy for personal financial-resource inference."""

from __future__ import annotations

import re
from collections.abc import Collection

FINANCIAL_RESOURCES_INFERENCE_TAIL = (
    "household family dependents children kids material needs resources assets surplus "
    "scarcity inequality disparity income salary earnings bills expenses wealth savings "
    "debt budget security"
)

_INFERENCE_TERMS = frozenset(
    {
        "could",
        "infer",
        "inference",
        "likely",
        "may",
        "might",
        "probably",
        "suggest",
        "suggests",
        "would",
    }
)
_FINANCIAL_TOPIC_TERMS = frozenset(
    {
        "economic",
        "financial",
        "financially",
        "finance",
        "finances",
        "income",
        "resource",
        "resources",
        "wealth",
    }
)
_NON_FINANCIAL_RELATION_TERMS = frozenset({"account", "api", "endpoint", "order", "relationship"})
_DIRECT_PURCHASE_TERMS = frozenset(
    {"bought", "buy", "cost", "costs", "paid", "price", "purchase", "purchased"}
)
_NEGATED_FINANCIAL_TERMS = frozenset({"broke", "impoverished", "poor"})
_DOLLAR_AMOUNT_RE = re.compile(r"\$\s*\d")
_FINANCIAL_SUBJECT_RE = re.compile(
    r"\b(?P<subject>[A-Z][a-z]{1,30})(?:'s|’s)\s+"
    r"(?:"
    r"(?:(?:personal|household|overall)\s+)?financial\s+"
    r"(?:status|situation|condition|circumstances|position|resources?)"
    r"|economic\s+(?:status|situation|condition|circumstances|position)"
    r"|finances?|income|resources?|wealth|salary|earnings?|money|assets?|savings?|debt|budget"
    r")\b"
)
_NEGATED_INTENT_RE = re.compile(r"\b(?:not|isn(?:'|’)?t)\b", re.IGNORECASE)
_NAMED_POSSESSIVE_RE = re.compile(r"\b[A-Z][a-z]{1,30}(?:'s|’s)\b")


def financial_resources_inference_tail(
    *,
    query: str,
    identities: tuple[str, ...],
    raw_tokens: Collection[str],
    variants: Collection[str],
) -> str | None:
    """Return generic resource evidence terms for a named-person inference only."""

    token_set = frozenset(raw_tokens)
    variant_set = frozenset(variants)
    financial_subject = _financial_subject(query)
    identity_keys = frozenset(identity.casefold() for identity in identities)
    if financial_subject is None or financial_subject not in identity_keys:
        return None
    if _NEGATED_INTENT_RE.search(query) is not None:
        return None
    if not variant_set.intersection(_INFERENCE_TERMS):
        return None
    if not variant_set.intersection(_FINANCIAL_TOPIC_TERMS):
        return None
    if token_set.intersection(_NON_FINANCIAL_RELATION_TERMS):
        return None
    if token_set.intersection(_DIRECT_PURCHASE_TERMS) or _DOLLAR_AMOUNT_RE.search(query):
        return None
    if token_set.intersection(_NEGATED_FINANCIAL_TERMS):
        return None
    return FINANCIAL_RESOURCES_INFERENCE_TAIL


def _financial_subject(query: str) -> str | None:
    match = _FINANCIAL_SUBJECT_RE.search(query)
    return match.group("subject").casefold() if match is not None else None
