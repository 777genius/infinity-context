"""Polarity and absence-contrast signals for deterministic context reranking."""

from __future__ import annotations

import re

_NOT_BLOCKED_QUERY_RE = re.compile(
    r"\b(?:not\s+blocked|isn'?t\s+blocked|unblocked|not\s+stuck)\b|"
    r"\b(?:не\s+заблокирован\w*|не\s+застрял\w*)\b",
    re.IGNORECASE,
)
_BLOCKED_TEXT_RE = re.compile(
    r"\b(?:blocked|stuck|blocked\s+by|blocked\s+on)\b|"
    r"\b(?:заблокирован\w*|застрял\w*)\b",
    re.IGNORECASE,
)
_NOT_BLOCKED_TEXT_RE = re.compile(
    r"\b(?:not\s+blocked|isn'?t\s+blocked|unblocked|not\s+stuck|active|open)\b|"
    r"\b(?:не\s+заблокирован\w*|не\s+застрял\w*|активн\w*)\b",
    re.IGNORECASE,
)
_NEGATIVE_PREFERENCE_QUERY_RE = re.compile(
    r"\b(?:not\s+(?:like|likes|liked|interested|eat|eats|enjoy|enjoys|want|wants)|"
    r"doesn'?t\s+(?:like|eat|enjoy|want)|does\s+not\s+(?:like|eat|enjoy|want)|"
    r"would\s+not\s+(?:like|eat|enjoy|want)|never\s+(?:eat|eats|like|likes)|"
    r"avoid|avoids|allergic)\b",
    re.IGNORECASE,
)
_NEGATIVE_EATING_QUERY_RE = re.compile(
    r"\b(?:can\W*t|cannot|can\s+not|unable\s+to)\b(?=.{0,80}\beat(?:s|ing)?\b)|"
    r"\beat(?:s|ing)?\b(?=.{0,80}\b(?:can\W*t|cannot|can\s+not|unable\s+to)\b)",
    re.IGNORECASE | re.DOTALL,
)
_NEGATIVE_PREFERENCE_TEXT_RE = re.compile(
    r"\b(?:not\s+(?:like|likes|liked|interested|eat|eats|enjoy|enjoys|want|wants)|"
    r"doesn'?t\s+(?:like|eat|enjoy|want)|does\s+not\s+(?:like|eat|enjoy|want)|"
    r"would\s+not\s+(?:like|eat|enjoy|want)|never\s+(?:eat|eats|like|likes)|"
    r"dislikes?|hates?|avoids?|allergic|cannot\s+eat|can'?t\s+eat)\b",
    re.IGNORECASE,
)
_POSITIVE_PREFERENCE_TEXT_RE = re.compile(
    r"\b(?:likes?|liked|loves?|loved|eats?|ate|enjoys?|enjoyed|wants?|wanted|"
    r"interested\s+in|fan\s+of)\b",
    re.IGNORECASE,
)
_CORRECTED_NEGATIVE_PREFERENCE_TEXT_RE = re.compile(
    r"\b(?:used\s+to|previously|formerly|once)\b"
    r"(?=.{0,100}\b(?:dislikes?|hates?|avoids?|"
    r"not\s+(?:like|likes|liked|eat|eats|enjoy|enjoys|want|wants)|"
    r"doesn'?t\s+(?:like|eat|enjoy|want)|"
    r"didn'?t\s+(?:like|eat|enjoy|want)|"
    r"cannot\s+eat|can'?t\s+eat)\b)"
    r"(?=.{0,180}\b(?:but\s+now|now|currently|these\s+days|nowadays)\b"
    r".{0,100}\b(?:likes?|loves?|eats?|enjoys?|wants?|prefers?|can\s+eat)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ABSENCE_CONTRAST_NEGATIVE_DESCRIPTOR_RE = (
    r"(?:"
    r"pet|animal|provider|model|project|thread|scope|meeting|call|event|person|"
    r"contact|file|document|doc|image|screenshot|audio|video|old|previous|former|"
    r"current|primary|backup|recommended|домашн\w*|питомц\w*|животн\w*|"
    r"провайдер\w*|модел\w*|проект\w*|тред\w*|встреч\w*|звон\w*|событи\w*|"
    r"человек\w*|контакт\w*|файл\w*|документ\w*|картинк\w*|скриншот\w*|"
    r"аудио|видео|стар\w*|прошл\w*|текущ\w*|основн\w*|резервн\w*|"
    r"рекомендованн\w*"
    r")"
)
_ABSENCE_CONTRAST_NAMED_QUERY_RE = re.compile(
    r"\b(?:named|called|назвал\w*)\s+(?P<positive>[A-Za-zА-Яа-яЁё][\w.-]{1,60})\s+"
    r"(?:instead\s+of|rather\s+than)\s+"
    r"(?:(?:a|an|the)\b\s*)?"
    rf"(?:(?:{_ABSENCE_CONTRAST_NEGATIVE_DESCRIPTOR_RE})\s+){{0,3}}"
    r"(?P<negative>[A-Za-zА-Яа-яЁё][\w.-]{1,60})\b",
    re.IGNORECASE,
)
_ABSENCE_CONTRAST_CHOICE_QUERY_RE = re.compile(
    r"\b(?:choose|chooses|chose|chosen|selects?|selected|picks?|picked|"
    r"prefers?|preferred|recommends?|recommended|uses?|used|using|adopts?|"
    r"adopted|switch(?:es|ed)?\s+to|went\s+with|go\s+with)\b"
    r"[^?.!;\n]{0,80}?"
    r"(?P<positive>[A-Za-zА-Яа-яЁё][\w.-]{1,60})\s+"
    r"(?:instead\s+of|rather\s+than)\s+"
    r"(?:(?:a|an|the)\b\s*)?"
    rf"(?:(?:{_ABSENCE_CONTRAST_NEGATIVE_DESCRIPTOR_RE})\s+){{0,3}}"
    r"(?P<negative>[A-Za-zА-Яа-яЁё][\w.-]{1,60})\b",
    re.IGNORECASE,
)
_NEGATED_ACTION_QUERY_RE = re.compile(
    r"\b(?:who|what|which)\b(?=[^?.!]{0,120}\b(?:did\s+not|didn't|does\s+not|"
    r"doesn't|never)\b)"
    r"(?=[^?.!]{0,160}\b(?:attend|go|bring|like|join|visit|help|ask|send|"
    r"come|show\s+up)\b)|"
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|never)\s+"
    r"(?:attend|go|bring|like|join|visit|help|ask|send|come|show\s+up)\b",
    re.IGNORECASE | re.DOTALL,
)
_ABSENCE_QUERY_RE = re.compile(
    r"\b(?:what|which|who|whether|was|were|is|are|did)\b"
    r"(?=[^?.!]{0,160}\b(?:missing|absent|absence|not\s+(?:there|included|"
    r"present)|wasn'?t\s+(?:there|included|present)|weren'?t\s+(?:there|"
    r"included|present)|without|no\s+one|nobody|did\s+not\s+(?:happen|occur|"
    r"show\s+up)|didn't\s+(?:happen|occur|show\s+up))\b)",
    re.IGNORECASE | re.DOTALL,
)
_NEGATED_ACTION_TEXT_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|never|not)\s+"
    r"(?:attend|attended|go|goes|went|bring|brings|brought|like|likes|liked|"
    r"enjoy|enjoys|enjoyed|join|joined|visit|visited|help|helped|ask|asked|"
    r"send|sent|come|came|show\s+up|showed\s+up)\b|"
    r"\b(?:missed|skipped|sat\s+out|wasn'?t\s+there|weren'?t\s+there|"
    r"absent\s+from|without)\b",
    re.IGNORECASE,
)
_POSITIVE_ACTION_TEXT_RE = re.compile(
    r"\b(?:attend|attended|go|goes|went|bring|brings|brought|like|likes|liked|"
    r"enjoy|enjoys|enjoyed|join|joined|visit|visited|help|helped|ask|asked|"
    r"send|sent|come|came|show\s+up|showed\s+up)\b",
    re.IGNORECASE,
)
_ABSENCE_TEXT_RE = re.compile(
    r"\b(?:missing|absent|absence|not\s+(?:there|included|present)|wasn'?t\s+"
    r"(?:there|included|present)|weren'?t\s+(?:there|included|present)|"
    r"without|no\s+one|nobody|did\s+not\s+(?:happen|occur|show\s+up)|didn't\s+"
    r"(?:happen|occur|show\s+up)|missed|skipped|sat\s+out)\b",
    re.IGNORECASE,
)
_PRESENCE_TEXT_RE = re.compile(
    r"\b(?:included|present|there|available|happened|occurred|showed\s+up|"
    r"attended|went|brought|had|contained|joined|visited|came)\b",
    re.IGNORECASE,
)
_ABSENCE_CONTEXT_STOPWORDS = frozenset(
    {
        "absent",
        "absence",
        "after",
        "and",
        "anyone",
        "are",
        "ask",
        "asked",
        "attend",
        "attended",
        "before",
        "bring",
        "brought",
        "came",
        "come",
        "did",
        "does",
        "event",
        "expected",
        "for",
        "from",
        "go",
        "had",
        "has",
        "have",
        "happen",
        "help",
        "helped",
        "into",
        "included",
        "is",
        "item",
        "join",
        "joined",
        "like",
        "missing",
        "never",
        "not",
        "of",
        "on",
        "occur",
        "present",
        "send",
        "sent",
        "show",
        "that",
        "the",
        "there",
        "this",
        "to",
        "visit",
        "visited",
        "was",
        "went",
        "were",
        "what",
        "when",
        "where",
        "whether",
        "which",
        "who",
        "without",
    }
)


def status_polarity_signal(*, query: str, text: str) -> tuple[float, float, str]:
    if not _NOT_BLOCKED_QUERY_RE.search(query):
        return 0.0, 0.0, ""
    if _NOT_BLOCKED_TEXT_RE.search(text):
        return 0.024, 0.0, "status_polarity_not_blocked_match"
    if _BLOCKED_TEXT_RE.search(text):
        return 0.0, 0.034, "status_polarity_blocked_conflict"
    return 0.0, 0.0, ""


def negative_preference_signal(*, query: str, text: str) -> tuple[float, float, str]:
    if not (
        _NEGATIVE_PREFERENCE_QUERY_RE.search(query)
        or _NEGATIVE_EATING_QUERY_RE.search(query)
    ):
        return 0.0, 0.0, ""
    if _CORRECTED_NEGATIVE_PREFERENCE_TEXT_RE.search(text):
        return 0.0, 0.03, "negative_preference_positive_conflict"
    if _NEGATIVE_PREFERENCE_TEXT_RE.search(text):
        return 0.026, 0.0, "negative_preference_match"
    if _POSITIVE_PREFERENCE_TEXT_RE.search(text):
        return 0.0, 0.03, "negative_preference_positive_conflict"
    return 0.0, 0.0, ""


def absence_contrast_signal(*, query: str, text: str) -> tuple[float, float, str]:
    match = _absence_contrast_match(query)
    if match is None:
        return 0.0, 0.0, ""
    positive = match.group("positive")
    negative = match.group("negative")
    if not positive or not negative:
        return 0.0, 0.0, ""
    has_positive = _query_token_in_text(positive, text)
    has_negative = _query_token_in_text(negative, text)
    if has_positive and not has_negative:
        return 0.026, 0.0, "absence_contrast_positive_match"
    if has_negative and not has_positive:
        return 0.0, 0.032, "absence_contrast_negative_only_conflict"
    return 0.0, 0.0, ""


def absence_negation_signal(*, query: str, text: str) -> tuple[float, float, str]:
    if not _is_absence_negation_query(query):
        return 0.0, 0.0, ""
    context_terms = _absence_context_terms(query)
    context_matched = not context_terms or _text_has_context_term(text, context_terms)
    has_negative_evidence = (
        _NEGATED_ACTION_TEXT_RE.search(text) is not None
        or _ABSENCE_TEXT_RE.search(text) is not None
    )
    if has_negative_evidence and context_matched:
        return 0.052, 0.0, "absence_negation_match"
    if has_negative_evidence and not context_matched:
        return 0.0, 0.036, "absence_negation_unrelated_absence"
    if context_matched and _has_positive_action_or_presence(text):
        return 0.0, 0.04, "absence_negation_positive_conflict"
    return 0.0, 0.0, ""


def _absence_contrast_match(query: str) -> re.Match[str] | None:
    for pattern in (
        _ABSENCE_CONTRAST_NAMED_QUERY_RE,
        _ABSENCE_CONTRAST_CHOICE_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            return match
    return None


def _query_token_in_text(token: str, text: str) -> bool:
    normalized = token.strip("._- ")
    if not normalized:
        return False
    return bool(re.search(rf"\b{re.escape(normalized)}\b", text, flags=re.IGNORECASE))


def _is_absence_negation_query(query: str) -> bool:
    return bool(_NEGATED_ACTION_QUERY_RE.search(query) or _ABSENCE_QUERY_RE.search(query))


def _absence_context_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"\b[A-Za-z][A-Za-z0-9'-]{2,}\b", query.casefold()):
        term = raw.strip("'-")
        if term in _ABSENCE_CONTEXT_STOPWORDS or term.endswith("n't"):
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return tuple(terms[:6])


def _text_has_context_term(text: str, context_terms: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE)
        for term in context_terms
    )


def _has_positive_action_or_presence(text: str) -> bool:
    if _PRESENCE_TEXT_RE.search(text) is not None:
        return True
    for match in _POSITIVE_ACTION_TEXT_RE.finditer(text):
        prefix = text[max(0, match.start() - 32) : match.start()]
        if _NEGATED_ACTION_TEXT_RE.search(prefix):
            continue
        return True
    return False
