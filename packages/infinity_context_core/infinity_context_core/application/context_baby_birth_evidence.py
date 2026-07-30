"""Baby-birth count evidence projection."""

from __future__ import annotations

import re
from collections.abc import Sequence

BABY_BIRTH_RETRIEVAL_TERMS = (
    "baby",
    "babies",
    "born",
    "had a baby",
    "welcomed",
    "newborn",
    "twins",
    "son",
    "daughter",
    "friends family",
)
BABY_BIRTH_QUERY_RE = re.compile(
    r"\bhow\s+many\s+babies\s+were\s+born\b"
    r"(?=.{0,180}\b(?:friends?|family|members?|relatives?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_FIRST_PERSON_CONTEXT_RE = re.compile(r"\b(?:I|I'm|I've|my|our)\b", re.IGNORECASE)
_BIRTH_CONTEXT_RE = re.compile(
    r"\b(?:born|had\s+a\s+baby|welcomed|newborn|new\s+twin|baby\s+boy|"
    r"baby\s+girl|twin\s+girls?|twin\s+boys?)\b",
    re.IGNORECASE,
)
_ADOPTION_OR_PET_RE = re.compile(r"\b(?:adopted|dog|puppy|pet|gotcha\s+day)\b", re.IGNORECASE)
_TWINS_NAMED_RE = re.compile(
    r"\btwins?\b[^.]{0,80}?\b(?P<first>[A-Z][a-z]+)\s+and\s+(?P<second>[A-Z][a-z]+)\b"
)
_NAMED_BABY_RE = re.compile(
    r"\b(?:baby\s+(?:boy|girl)|son|daughter|girl|boy)\s+named\s+(?P<name>[A-Z][a-z]+)\b|"
    r"\b(?:son|daughter)\s+(?P<child>[A-Z][a-z]+)\b(?=.{0,80}\bborn\b)|"
    r"\bborn\b(?=.{0,80}\b(?:son|daughter|baby|girl|boy)\s+(?P<after>[A-Z][a-z]+)\b)"
)


def baby_birth_count_query(query: str) -> bool:
    return BABY_BIRTH_QUERY_RE.search(query) is not None


def project_baby_birth_count(
    segments: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    identities: list[str] = []
    evidence: list[str] = []
    seen_identities: set[str] = set()
    seen_sentences: set[str] = set()
    for segment in segments:
        normalized_segment = " ".join(segment.split()).strip()
        if _FIRST_PERSON_CONTEXT_RE.search(normalized_segment) is None:
            continue
        for match in _SENTENCE_RE.finditer(normalized_segment):
            sentence = " ".join(match.group(0).split()).strip()
            if (
                not sentence
                or _BIRTH_CONTEXT_RE.search(sentence) is None
                or _ADOPTION_OR_PET_RE.search(sentence) is not None
            ):
                continue
            sentence_identities = _baby_birth_identities(sentence)
            if not sentence_identities:
                continue
            for identity in sentence_identities:
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                identities.append(identity)
            key = sentence.casefold()
            if key not in seen_sentences:
                seen_sentences.add(key)
                evidence.append(sentence)
            if len(identities) >= 8 or len(evidence) >= 8:
                return tuple(identities[:8]), tuple(evidence[:8])
    return tuple(identities), tuple(evidence)


def _baby_birth_identities(sentence: str) -> tuple[str, ...]:
    names: list[str] = []
    if twins := _TWINS_NAMED_RE.search(sentence):
        names.extend((twins.group("first"), twins.group("second")))
    for match in _NAMED_BABY_RE.finditer(sentence):
        name = match.group("name") or match.group("child") or match.group("after")
        if name:
            names.append(name)
    return tuple(dict.fromkeys(f"born:{name.casefold()}" for name in names))
