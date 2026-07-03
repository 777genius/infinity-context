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
