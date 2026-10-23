"""Benchmark-owned comparison patterns policy."""

from __future__ import annotations

import re


def _has_negative_absence_intent(question: str) -> bool:
    normalized = re.sub(r"[^0-9a-z']+", " ", question.casefold()).strip()
    if not normalized:
        return False
    return bool(
        re.search(
            r"\b(?:"
            r"no\s+longer|not\s+yet|never|none|nobody|no\s+one|"
            r"(?:has|have|had|with|there\s+is|there\s+are)\s+no|"
            r"not\s+(?:valid|current|available|present|registered|attending|"
            r"going|using|used|mentioned|included)|"
            r"without|missing|absent"
            r")\b",
            normalized,
        )
    )


def _has_contrast_intent(
    *,
    question: str = "",
    relation_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    if _has_commonality_intent(normalized) and not _has_explicit_difference_intent(normalized):
        return False
    relation_set = set(relation_terms)
    return bool(
        {"between", "compare", "different", "difference", "former", "previous"} & relation_set
        or {"compare", "between", "before", "after"} & set(multi_hop_markers)
        or _has_comparative_choice_intent(normalized)
    )


_COMMONALITY_INTENT_RE = re.compile(
    r"\b(?:both|common|connects?|mutual|overlap|same|shared|similar)\b|"
    r"\bin\s+common\b"
)


_EXPLICIT_DIFFERENCE_INTENT_RE = re.compile(
    r"\b(?:compare|compared|contrast|different|difference)\b"
)


_COMPARATIVE_CHOICE_INTENT_RE = re.compile(
    r"\b(?:which\s+(?:one|person)|who)\b"
    r".{0,100}\b(?:chang(?:e|ed|es|ing)?|prefer(?:s|red|ring)?|"
    r"lik(?:e|es|ed|ing)?|enjoy(?:s|ed|ing)?|lov(?:e|es|ed|ing)?)\b"
    r".{0,60}\b(?:more|less|most|least)\b"
)


def _has_commonality_intent(normalized_question: str) -> bool:
    return bool(normalized_question and _COMMONALITY_INTENT_RE.search(normalized_question))


def _has_explicit_difference_intent(normalized_question: str) -> bool:
    return bool(normalized_question and _EXPLICIT_DIFFERENCE_INTENT_RE.search(normalized_question))


def _has_comparative_choice_intent(normalized_question: str) -> bool:
    return bool(normalized_question and _COMPARATIVE_CHOICE_INTENT_RE.search(normalized_question))


def _has_count_intent(question: str) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    return bool(
        normalized
        and re.search(
            r"\b(?:how\s+many|number\s+of|count\s+of|total\s+(?:number|count))\b",
            normalized,
        )
    )


def _has_list_intent(question: str) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    if not normalized:
        return False
    return bool(
        re.search(
            r"\b(?:list|names|items)\b.+\b(?:are|were|of|for)\b|"
            r"\b(?:what|which)\s+(?:are|were)\s+(?:the\s+)?"
            r"(?:names?|items?|things?|activities|hobbies|books|songs|"
            r"movies|places|people|friends|pets|dogs|cats|children|kids)\b|"
            r"\bwhich\s+(?:names?|items?|things?|activities|hobbies|books|"
            r"songs|movies|places|people|friends|pets|dogs|cats|children|kids)\s+"
            r"(?:do|does|did|has|have|had|is|are|was|were)\b|"
            r"\bwho\s+(?:are|were)\b",
            normalized,
        )
    )
