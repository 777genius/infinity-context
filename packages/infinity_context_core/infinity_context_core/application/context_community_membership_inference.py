"""Community membership inference evidence signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_answer_evidence_types import (
    AnswerEvidenceSignal,
)
from infinity_context_core.application.context_lexical import query_terms

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_COMMUNITY_MEMBERSHIP_QUERY_TERMS = frozenset(
    {
        "belong",
        "community",
        "lgbt",
        "lgbtq",
        "member",
        "membership",
        "part",
        "queer",
        "trans",
        "transgender",
    }
)
_COMMUNITY_IDENTITY_TERMS = frozenset(
    {
        "belong",
        "belonged",
        "belonging",
        "came",
        "community",
        "identifies",
        "identify",
        "identity",
        "joined",
        "lgbt",
        "lgbtq",
        "member",
        "membership",
        "part",
        "pride",
        "queer",
        "support",
        "trans",
        "transgender",
    }
)
_COMMUNITY_DOMAIN_TERMS = frozenset(
    {
        "lgbt",
        "lgbtq",
        "pride",
        "queer",
        "trans",
        "transgender",
    }
)
_COMMUNITY_MEMBERSHIP_MARKER_RE = re.compile(
    r"\b(?:identif(?:y|ies|ied)|member|part\s+of|belong(?:s|ed|ing)?\s+to|"
    r"came\s+out|is\s+(?:transgender|queer|lgbtq?)|joined)\b"
    r".{0,120}\b(?:lgbtq?|trans(?:gender)?|queer|pride|support\s+group|community)\b|"
    r"\b(?:lgbtq?|trans(?:gender)?|queer|pride|support\s+group|community)\b"
    r".{0,120}\b(?:identif(?:y|ies|ied)|member|part\s+of|belong(?:s|ed|ing)?|"
    r"came\s+out|joined)\b",
    re.IGNORECASE | re.DOTALL,
)
_COMMUNITY_ALLY_NOISE_RE = re.compile(
    r"\b(?:ally|allies|supportive|supported|encourag(?:e|ed|es|ing)|"
    r"advocat(?:e|ed|es|ing))\b.{0,100}\b(?:lgbtq?|trans(?:gender)?|"
    r"queer|community|rights)\b|"
    r"\b(?:lgbtq?|trans(?:gender)?|queer|pride|community|rights)\b.{0,100}"
    r"\b(?:ally|allies|supportive|supported|encourag(?:e|ed|es|ing)|"
    r"advocat(?:e|ed|es|ing))\b",
    re.IGNORECASE | re.DOTALL,
)
_GENERAL_COMMUNITY_TOPIC_RE = re.compile(
    r"\bcommunity\b.{0,80}\b(?:fundraiser|event|meeting|cleanup|downtown|local)\b|"
    r"\b(?:fundraiser|event|meeting|cleanup|downtown|local)\b.{0,80}\bcommunity\b",
    re.IGNORECASE | re.DOTALL,
)


def community_membership_inference_signal(
    *,
    query: str,
    text: str,
) -> AnswerEvidenceSignal:
    """Return evidence-fit signal for community membership inference questions."""

    if not _requests_community_membership_inference(query):
        return AnswerEvidenceSignal()
    text_tokens = _raw_term_set(text)
    if _COMMUNITY_MEMBERSHIP_MARKER_RE.search(text) and (
        text_tokens & _COMMUNITY_DOMAIN_TERMS
    ):
        return AnswerEvidenceSignal(
            boost=0.032,
            reason="inference_community_membership_evidence",
        )
    if _COMMUNITY_ALLY_NOISE_RE.search(text):
        return AnswerEvidenceSignal(
            penalty=0.046,
            reason="inference_community_membership_ally_noise",
        )
    if _GENERAL_COMMUNITY_TOPIC_RE.search(text):
        return AnswerEvidenceSignal(
            penalty=0.032,
            reason="inference_community_membership_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _requests_community_membership_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    if not {"member", "membership", "part", "belong"} & query_tokens:
        return False
    return bool(query_tokens & _COMMUNITY_MEMBERSHIP_QUERY_TERMS)


def _term_set(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for term in query_terms(text, min_chars=2, max_terms=40):
        terms.update(term.variants)
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            terms.add(token)
    return frozenset(terms)


def _raw_term_set(text: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold().strip("_")
        for match in _TOKEN_RE.finditer(text)
        if len(match.group(0).strip("_")) >= 2
    )
