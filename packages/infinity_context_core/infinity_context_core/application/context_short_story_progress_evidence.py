"""Short-story progress count evidence projection."""

from __future__ import annotations

import re
from collections.abc import Sequence

SHORT_STORY_PROGRESS_RETRIEVAL_TERMS = (
    "short stories",
    "short story",
    "writing regularly",
    "written",
    "wrote",
    "complete",
    "completed",
    "finished",
    "started writing",
)
SHORT_STORY_PROGRESS_QUERY_RE = re.compile(
    r"\bhow\s+many\s+short\s+stories\b"
    r"(?=.{0,180}\b(?:written|wrote|complete|completed|finished)\b)"
    r"(?=.{0,220}\bsince\b.{0,120}\bstarted\s+writing\s+regularly\b)",
    re.IGNORECASE | re.DOTALL,
)
_COUNT_VALUE = r"\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten"
_SHORT_STORY_COUNT_RE = re.compile(
    rf"\b(?:written|wrote|complete[ds]?|finished)\s+"
    rf"(?P<count_direct>{_COUNT_VALUE})\b|"
    rf"\b(?P<count>{_COUNT_VALUE})\b"
    r"(?=.{0,80}\bshort\s+stor(?:y|ies)\b)|"
    r"\bshort\s+stor(?:y|ies)\b"
    rf"(?=.{0,80}\b(?P<count_after>{_COUNT_VALUE})\b)",
    re.IGNORECASE | re.DOTALL,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_FIRST_PERSON_RE = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|me|my)\b", re.IGNORECASE)
_WRITING_PROGRESS_RE = re.compile(
    r"\b(?:writing\s+regularly|started\s+writing|written|wrote|complete[ds]?|finished)\b",
    re.IGNORECASE,
)
_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def short_story_progress_count_query(query: str) -> bool:
    """Return whether query asks for a since-started short-story count."""

    return SHORT_STORY_PROGRESS_QUERY_RE.search(query) is not None


def project_short_story_progress_count(
    segments: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return opaque-safe count identities and user evidence sentences."""

    identities: list[str] = []
    evidence: list[str] = []
    seen_sentences: set[str] = set()
    for segment in segments:
        normalized_segment = " ".join(segment.split()).strip()
        if _FIRST_PERSON_RE.search(normalized_segment) is None:
            continue
        for match in _SENTENCE_RE.finditer(normalized_segment):
            sentence = " ".join(match.group(0).split()).strip()
            if (
                not sentence
                or _WRITING_PROGRESS_RE.search(sentence) is None
                or "short stor" not in sentence.casefold()
            ):
                continue
            count_matches = tuple(_SHORT_STORY_COUNT_RE.finditer(sentence))
            direct_match = next(
                (item for item in count_matches if item.group("count_direct")), None
            )
            ordered_matches = (direct_match,) if direct_match is not None else count_matches
            for count_match in ordered_matches:
                raw = (
                    count_match.group("count_direct")
                    or count_match.group("count")
                    or count_match.group("count_after")
                )
                count = _normalize_count(raw)
                if count <= 0:
                    continue
                identity = f"short_story_progress_count:{count}"
                if identity not in identities:
                    identities.append(identity)
                sentence_key = sentence.casefold()
                if sentence_key not in seen_sentences:
                    seen_sentences.add(sentence_key)
                    evidence.append(sentence)
                break
            if len(identities) >= 8:
                return tuple(identities), tuple(evidence)
    return tuple(identities), tuple(evidence)


def _normalize_count(raw: str) -> int:
    value = raw.casefold()
    if value.isdigit():
        return int(value)
    return _COUNT_WORDS.get(value, 0)


__all__ = (
    "SHORT_STORY_PROGRESS_RETRIEVAL_TERMS",
    "project_short_story_progress_count",
    "short_story_progress_count_query",
)
