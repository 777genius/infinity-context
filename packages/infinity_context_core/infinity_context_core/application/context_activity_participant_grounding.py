"""Activity participant grounding helpers for deterministic reranking."""

from __future__ import annotations

import re

_PARTICIPANT_ACTIVITY_VERBS = frozenset(
    {"attend", "help", "join", "meet", "visit"}
)
_GENERIC_ACTIVITY_MENTION_RE = re.compile(
    r"\b(?:enjoy(?:s|ed|ing)?|lik(?:e|es|ed|ing)?|lov(?:e|es|ed|ing)?|"
    r"prefer(?:s|red|ring)?|favorite|favourite|hobb(?:y|ies)|pastime|"
    r"interested\s+in|fan\s+of|talk(?:s|ed|ing)?\s+about|mention(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)


def local_action_segment(body: str) -> str:
    """Keep participant/activity role checks inside the current sentence or turn."""

    return re.split(r"\bD\d+:\d+\b|(?<=[.!?;])\s+|[\n\r]+", body, maxsplit=1)[0]


def generic_activity_mention_without_participant_role(
    text: str,
    *,
    participant: str,
    verb_key: str,
    context_terms: tuple[str, ...],
) -> bool:
    if verb_key not in _PARTICIPANT_ACTIVITY_VERBS or not context_terms:
        return False
    participant_key = _normalized_label(participant)
    for segment in _local_text_segments(text):
        if not _context_terms_match(segment, context_terms):
            continue
        if _GENERIC_ACTIVITY_MENTION_RE.search(segment) is None:
            continue
        if _participant_action_re(verb_key).search(segment) is not None:
            continue
        if participant_key and not _segment_mentions_participant(
            segment,
            participant=participant,
        ):
            continue
        return True
    return False


def _local_text_segments(text: str) -> tuple[str, ...]:
    return tuple(
        segment.strip()
        for segment in re.split(r"\bD\d+:\d+\b|(?<=[.!?;])\s+|[\n\r]+", text)
        if segment.strip()
    )


def _context_terms_match(text: str, context_terms: tuple[str, ...]) -> bool:
    if not context_terms:
        return True
    normalized = text.casefold()
    hits = sum(1 for term in context_terms if term in normalized)
    required = min(len(context_terms), 2)
    return hits >= required


def _segment_mentions_participant(segment: str, *, participant: str) -> bool:
    return re.search(
        rf"(?<!\w){re.escape(participant)}(?!\w)",
        segment,
        flags=re.IGNORECASE | re.DOTALL,
    ) is not None


def _normalized_label(label: str) -> str:
    return re.sub(r"[^A-Za-zА-Яа-яЁё0-9]+", "", label.casefold())


def _participant_action_re(verb_key: str) -> re.Pattern[str]:
    forms = {
        "attend": r"attend(?:ed|s|ing)?|participat(?:e|ed|es|ing)",
        "help": r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?",
        "join": r"join(?:ed|s|ing)?",
        "meet": r"meet|met",
        "visit": r"visit(?:ed|s|ing)?",
    }
    return re.compile(rf"\b(?:{forms.get(verb_key, r'(?!x)x')})\b", re.IGNORECASE)
