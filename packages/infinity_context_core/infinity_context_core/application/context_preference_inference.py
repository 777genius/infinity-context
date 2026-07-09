"""Preference inference evidence signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_answer_evidence_types import (
    AnswerEvidenceSignal,
)
from infinity_context_core.application.context_lexical import query_terms

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_INFERENCE_QUERY_TERMS = frozenset(
    {
        "could",
        "infer",
        "inference",
        "likely",
        "may",
        "might",
        "probably",
        "should",
        "would",
        "вероятно",
        "может",
        "похоже",
    }
)
_PREFERENCE_QUERY_TERMS = frozenset(
    {
        "enjoy",
        "enjoying",
        "interest",
        "interested",
        "like",
        "likes",
        "love",
        "loves",
        "prefer",
        "prefers",
    }
)
_NEGATIVE_PREFERENCE_QUERY_TERMS = frozenset(
    {
        "avoid",
        "avoided",
        "avoids",
        "dislike",
        "disliked",
        "dislikes",
        "hate",
        "hated",
        "hates",
    }
)
_POSITIVE_PREFERENCE_TERMS = frozenset(
    {
        "enjoy",
        "enjoyed",
        "enjoys",
        "fan",
        "favorite",
        "favourite",
        "interested",
        "like",
        "liked",
        "likes",
        "love",
        "loved",
        "loves",
        "prefer",
        "preferred",
        "prefers",
    }
)
_NEGATIVE_PREFERENCE_TERMS = frozenset(
    {
        "avoid",
        "avoided",
        "avoids",
        "dislike",
        "disliked",
        "dislikes",
        "hate",
        "hated",
        "hates",
        "instead",
    }
)
_STRONG_NEGATIVE_PREFERENCE_TERMS = _NEGATIVE_PREFERENCE_TERMS - frozenset({"instead"})
_NEGATIVE_PREFERENCE_FIT_RE = re.compile(
    r"\b(?:doesn'?t|does\s+not|didn'?t|did\s+not|wouldn'?t|would\s+not|not)\s+"
    r"(?:like|enjoy|prefer|want|care\s+for)\b|"
    r"\b(?:no\s+interest\s+in|not\s+interested\s+in|not\s+a\s+fan\s+of)\b",
    re.IGNORECASE,
)
_POSITIVE_GROUNDED_PREFERENCE_QUERY_RE = re.compile(
    r"\b(?:what|which|why|reason)\b(?=[^?.!]{0,140}\b(?:likes?|loves?|"
    r"enjoys?|prefers?|favorite|favourite|interested)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MUSIC_QUERY_TERMS = frozenset(
    {
        "bach",
        "classical",
        "four",
        "music",
        "seasons",
        "song",
        "vivaldi",
    }
)
_CLASSICAL_MUSIC_TEXT_TERMS = frozenset(
    {
        "bach",
        "classical",
        "mozart",
        "music",
        "orchestra",
        "symphony",
        "vivaldi",
    }
)


def preference_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    """Return preference answer-evidence signal, if the query asks for it."""

    raw_query_tokens = _raw_token_set(query)
    if not raw_query_tokens & (
        _PREFERENCE_QUERY_TERMS | _NEGATIVE_PREFERENCE_QUERY_TERMS
    ):
        return AnswerEvidenceSignal()
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    wants_negative = _requests_negative_preference(query=query, query_tokens=query_tokens)
    if query_tokens & _MUSIC_QUERY_TERMS:
        return _classical_music_preference_signal(
            query=query,
            wants_negative=wants_negative,
            text=text,
            text_tokens=text_tokens,
        )
    positive_hits = text_tokens & _POSITIVE_PREFERENCE_TERMS
    negative_hits = text_tokens & _NEGATIVE_PREFERENCE_TERMS
    has_domain_overlap = _has_preference_domain_overlap(query_tokens, text_tokens)
    has_negative_evidence = _has_negative_preference_evidence(
        text=text,
        text_tokens=text_tokens,
    )
    if wants_negative and positive_hits and not has_negative_evidence and has_domain_overlap:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_positive_preference_conflict",
        )
    if (
        _requests_grounded_positive_preference(query)
        and has_negative_evidence
        and has_domain_overlap
    ):
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_negative_preference_conflict",
        )
    if (
        positive_hits
        and not has_negative_evidence
        and has_domain_overlap
    ):
        return AnswerEvidenceSignal(
            boost=0.028,
            reason="inference_preference_fit_evidence",
        )
    if (
        (negative_hits or has_negative_evidence)
        and has_negative_evidence
        and has_domain_overlap
    ):
        return AnswerEvidenceSignal(
            boost=0.026,
            reason="inference_negative_preference_fit_evidence",
        )
    if negative_hits and not positive_hits:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_negative_preference_noise",
        )
    return AnswerEvidenceSignal()


def preference_polarity_conflict_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    """Return a conflict when causal snippets ground the opposite preference polarity."""

    raw_query_tokens = _raw_token_set(query)
    if not raw_query_tokens & (
        _PREFERENCE_QUERY_TERMS | _NEGATIVE_PREFERENCE_QUERY_TERMS
    ):
        return AnswerEvidenceSignal()
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    if not _has_preference_domain_overlap(query_tokens, text_tokens):
        return AnswerEvidenceSignal()
    wants_negative = _requests_negative_preference(query=query, query_tokens=query_tokens)
    has_negative_evidence = _has_negative_preference_evidence(
        text=text,
        text_tokens=text_tokens,
    )
    positive_hits = text_tokens & _POSITIVE_PREFERENCE_TERMS
    if wants_negative and positive_hits and not has_negative_evidence:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_positive_preference_conflict",
        )
    if _requests_grounded_positive_preference(query) and has_negative_evidence:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_negative_preference_conflict",
        )
    return AnswerEvidenceSignal()


def _classical_music_preference_signal(
    *,
    query: str,
    wants_negative: bool,
    text: str,
    text_tokens: frozenset[str],
) -> AnswerEvidenceSignal:
    positive_hits = text_tokens & _POSITIVE_PREFERENCE_TERMS
    negative_hits = text_tokens & _NEGATIVE_PREFERENCE_TERMS
    classical_hits = text_tokens & _CLASSICAL_MUSIC_TEXT_TERMS
    has_negative_evidence = _has_negative_preference_evidence(
        text=text,
        text_tokens=text_tokens,
    )
    if wants_negative and positive_hits and not has_negative_evidence and classical_hits:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_positive_preference_conflict",
        )
    if (
        _requests_grounded_positive_preference(query)
        and has_negative_evidence
        and classical_hits
    ):
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_negative_preference_conflict",
        )
    if positive_hits and not has_negative_evidence and classical_hits:
        return AnswerEvidenceSignal(
            boost=0.028,
            reason="inference_preference_fit_evidence",
        )
    if (
        (negative_hits or has_negative_evidence)
        and classical_hits
        and has_negative_evidence
    ):
        return AnswerEvidenceSignal(
            boost=0.026,
            reason="inference_negative_preference_fit_evidence",
        )
    if negative_hits and not positive_hits:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_negative_preference_noise",
        )
    if classical_hits and not positive_hits:
        return AnswerEvidenceSignal(
            penalty=0.032,
            reason="inference_classical_music_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _has_preference_domain_overlap(
    query_tokens: frozenset[str],
    text_tokens: frozenset[str],
) -> bool:
    return bool(
        (
            query_tokens
            - _INFERENCE_QUERY_TERMS
            - _PREFERENCE_QUERY_TERMS
            - _NEGATIVE_PREFERENCE_QUERY_TERMS
        )
        & text_tokens
    )


def _requests_negative_preference(
    *,
    query: str,
    query_tokens: frozenset[str],
) -> bool:
    return bool(
        query_tokens & _NEGATIVE_PREFERENCE_QUERY_TERMS
        or _NEGATIVE_PREFERENCE_FIT_RE.search(query)
    )


def _requests_grounded_positive_preference(query: str) -> bool:
    return _POSITIVE_GROUNDED_PREFERENCE_QUERY_RE.search(query) is not None


def _has_negative_preference_evidence(
    *,
    text: str,
    text_tokens: frozenset[str],
) -> bool:
    return bool(
        text_tokens & _STRONG_NEGATIVE_PREFERENCE_TERMS
        or _NEGATIVE_PREFERENCE_FIT_RE.search(text)
    )


def _term_set(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for term in query_terms(text, min_chars=2, max_terms=40):
        terms.update(term.variants)
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            terms.add(token)
    return frozenset(terms)


def _raw_token_set(text: str) -> frozenset[str]:
    return frozenset(
        token
        for match in _TOKEN_RE.finditer(text)
        if len(token := match.group(0).casefold().strip("_")) >= 2
    )
