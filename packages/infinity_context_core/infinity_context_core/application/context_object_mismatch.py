"""Object-kind mismatch signals for deterministic memory reranking."""

from __future__ import annotations

import re

_PET_QUERY_CONTEXT_RE = re.compile(
    r"\b(?:pet|pets|animal|animals|mention(?:ed)?|named|called|have|has|had|"
    r"own(?:s|ed)?|adopt(?:ed)?|домашн\w*|питомц\w*|животн\w*|"
    r"упоминал\w*|звал\w*|назвал\w*)\b",
    re.IGNORECASE,
)
_NON_PET_CONTEXT_RE = re.compile(
    r"\b(?:shelter|rescue|park|team|logo|mascot|breed\s+club|приют|команда)\b",
    re.IGNORECASE,
)
_EXPLICIT_CONTRAST_QUERY_RE = re.compile(
    r"\b(?:instead\s+of|rather\s+than|not\s+the|вместо|а\s+не)\b",
    re.IGNORECASE,
)
_SPECIES_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hamster", re.compile(r"\bhamsters?\b|\bхомяк\w*\b", re.IGNORECASE)),
    ("cat", re.compile(r"\bcats?\b|\bkittens?\b|\bкошк\w*|\bкот\w*\b", re.IGNORECASE)),
    (
        "dog",
        re.compile(
            r"\bdogs?\b|\bpupp(?:y|ies)\b|\bpups?\b|\bсобак\w*|\bп[её]с\w*\b",
            re.IGNORECASE,
        ),
    ),
    ("turtle", re.compile(r"\bturtles?\b|\bчерепах\w*\b", re.IGNORECASE)),
    ("rabbit", re.compile(r"\brabbits?\b|\bbunn(?:y|ies)\b|\bкролик\w*\b", re.IGNORECASE)),
    ("bird", re.compile(r"\bbirds?\b|\bparrots?\b|\bптиц\w*|\bпопугай\w*\b", re.IGNORECASE)),
    ("fish", re.compile(r"\bfish(?:es)?\b|\bрыб\w*\b", re.IGNORECASE)),
)


def object_kind_mismatch_signal(*, query: str, text: str) -> tuple[float, float, str]:
    if _EXPLICIT_CONTRAST_QUERY_RE.search(query) is not None:
        return 0.0, 0.0, ""
    requested_species = _species_in_text(query)
    if not requested_species or not _looks_like_pet_query(query):
        return 0.0, 0.0, ""
    text_species = _species_in_text(text)
    if not text_species:
        return 0.0, 0.0, ""
    if requested_species & text_species:
        return 0.018, 0.0, "object_kind_match"
    return 0.0, 0.052, "object_kind_species_mismatch"


def _looks_like_pet_query(query: str) -> bool:
    if _NON_PET_CONTEXT_RE.search(query) is not None:
        return False
    return _PET_QUERY_CONTEXT_RE.search(query) is not None


def _species_in_text(text: str) -> frozenset[str]:
    return frozenset(
        species
        for species, pattern in _SPECIES_PATTERNS
        if pattern.search(text) is not None
    )
