"""Pet ownership signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class PetOwnershipQueryKind(Enum):
    OWNER_FOR_PET = "owner_for_pet"
    OWNER_AND_PET = "owner_and_pet"
    PET_FOR_OWNER = "pet_for_owner"


class PetOwnershipSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PetOwnershipQuery:
    kind: PetOwnershipQueryKind
    owner_label: str = ""
    pet_label: str = ""


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):",
)
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_WHO_OWNS_PET_RE = re.compile(
    rf"(?i:\bwho\s+(?:owns|has|adopted|got)\s+)(?P<pet>{_LABEL_RE})\b|"
    rf"(?i:\bwhose\s+(?:dog|cat|puppy|pup|pet)\s+(?:is|was)\s+)"
    rf"(?P<whose_pet>{_LABEL_RE})\b",
)
_WHO_HAS_NAMED_PET_RE = re.compile(
    rf"(?i:\bwho\s+(?:has|owns|adopted|got)\s+(?:a\s+|an\s+)?"
    rf"(?:dog|cat|puppy|pup|pet)\s+(?:named|called)\s+)"
    rf"(?P<pet>{_LABEL_RE})\b|"
    rf"(?i:\bwhose\s+(?:dog|cat|puppy|pup|pet)\s+(?:is|was)\s+"
    rf"(?:named|called)\s+)(?P<whose_pet>{_LABEL_RE})\b",
)
_OWNER_PET_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+(?:is|was|are|were)\s+)(?P<owner>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?:dog|cat|puppy|pup|pet)(?:'s|s')?\s+"
    rf"(?i:name|names)\b|"
    rf"\b(?P<owner_direct>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?i:(?:dog|cat|puppy|pup|pet)\s+(?:named|called|name))\b",
)
_OWNER_HAS_PET_QUERY_RE = re.compile(
    rf"(?i:\bdoes\s+)(?P<owner>{_LABEL_RE})\s+"
    rf"(?i:(?:have|own|adopt|get)\s+(?:a\s+|an\s+)?(?:dog|cat|puppy|pup|pet))"
)
_OWNER_HAS_NAMED_PET_QUERY_RE = re.compile(
    rf"(?i:\b(?:does|did)\s+)(?P<owner>{_LABEL_RE})\s+"
    rf"(?i:(?:have|own|adopt|get)\s+(?:a\s+|an\s+)?"
    rf"(?:dog|cat|puppy|pup|pet)\s+(?:named|called)\s+)"
    rf"(?P<pet>{_LABEL_RE})\b",
)
_PET_OWNERSHIP_CUE_RE = re.compile(
    r"\b(?:has|have|had|owns?|owned|adopt(?:ed|s)?|got|belongs?\s+to|"
    r"dog|cat|puppy|pup|pet|named|called|new\s+addition)\b",
    re.IGNORECASE,
)
_PET_KIND_RE = re.compile(r"\b(?:dog|cat|puppy|pup|pet)\b", re.IGNORECASE)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "who", "whose"})


def pet_ownership_signal(*, query: str, text: str) -> PetOwnershipSignal:
    """Return bounded evidence signal for named pet ownership questions."""

    ownership_query = _pet_ownership_query(query)
    if ownership_query is None:
        return PetOwnershipSignal()
    if _text_satisfies_pet_ownership(ownership_query, text):
        return PetOwnershipSignal(boost=0.022, reason="pet_ownership_match")
    if _text_mentions_pet_decoy(ownership_query, text):
        return PetOwnershipSignal(penalty=0.02, reason="pet_ownership_other_owner")
    return PetOwnershipSignal()


def _pet_ownership_query(query: str) -> _PetOwnershipQuery | None:
    for pattern in (_WHO_HAS_NAMED_PET_RE, _WHO_OWNS_PET_RE):
        match = pattern.search(query)
        if match is not None:
            pet = (match.group("pet") or match.group("whose_pet") or "").strip(" :,.!?;")
            if _valid_label(pet):
                return _PetOwnershipQuery(
                    kind=PetOwnershipQueryKind.OWNER_FOR_PET,
                    pet_label=pet,
                )
    named_owner_match = _OWNER_HAS_NAMED_PET_QUERY_RE.search(query)
    if named_owner_match is not None:
        owner = named_owner_match.group("owner").strip(" :,.!?;")
        pet = named_owner_match.group("pet").strip(" :,.!?;")
        if _valid_label(owner) and _valid_label(pet):
            return _PetOwnershipQuery(
                kind=PetOwnershipQueryKind.OWNER_AND_PET,
                owner_label=owner,
                pet_label=pet,
            )
    for pattern in (_OWNER_PET_QUERY_RE, _OWNER_HAS_PET_QUERY_RE):
        match = pattern.search(query)
        if match is None:
            continue
        owner = (
            match.groupdict().get("owner")
            or match.groupdict().get("owner_direct")
            or ""
        ).strip(" :,.!?;")
        if _valid_label(owner):
            return _PetOwnershipQuery(
                kind=PetOwnershipQueryKind.PET_FOR_OWNER,
                owner_label=owner,
            )
    return None


def _text_satisfies_pet_ownership(
    ownership_query: _PetOwnershipQuery,
    text: str,
) -> bool:
    if _PET_OWNERSHIP_CUE_RE.search(text) is None:
        return False
    if ownership_query.kind is PetOwnershipQueryKind.OWNER_FOR_PET:
        return _text_mentions_label(ownership_query.pet_label, text) and (
            _PET_KIND_RE.search(text) is not None or _text_mentions_other_person("", text)
        )
    if ownership_query.kind is PetOwnershipQueryKind.OWNER_AND_PET:
        return (
            _text_mentions_label(ownership_query.owner_label, text)
            and _text_mentions_label(ownership_query.pet_label, text)
            and _PET_KIND_RE.search(text) is not None
        )
    return _text_mentions_label(ownership_query.owner_label, text) and (
        _PET_KIND_RE.search(text) is not None
    )


def _text_mentions_pet_decoy(
    ownership_query: _PetOwnershipQuery,
    text: str,
) -> bool:
    if _PET_OWNERSHIP_CUE_RE.search(text) is None:
        return False
    if ownership_query.kind is PetOwnershipQueryKind.OWNER_FOR_PET:
        return _text_mentions_label(ownership_query.pet_label, text)
    if ownership_query.kind is PetOwnershipQueryKind.OWNER_AND_PET:
        return (
            _PET_KIND_RE.search(text) is not None
            and _text_mentions_label(ownership_query.owner_label, text)
            and not _text_mentions_label(ownership_query.pet_label, text)
        ) or (
            _text_mentions_label(ownership_query.pet_label, text)
            and not _text_mentions_label(ownership_query.owner_label, text)
            and _text_mentions_other_person(ownership_query.owner_label, text)
        )
    return (
        _PET_KIND_RE.search(text) is not None
        and not _text_mentions_label(ownership_query.owner_label, text)
        and _text_mentions_other_person(ownership_query.owner_label, text)
    )


def _text_mentions_label(label: str, text: str) -> bool:
    label_aliases = person_alias_keys(label)
    return any(
        label_aliases.intersection(person_alias_keys(match.group("speaker")))
        for match in _DIALOGUE_SPEAKER_RE.finditer(text)
    ) or any(
        person_labels_match(match.group(0), label)
        for match in _LABEL_TOKEN_RE.finditer(text)
    )


def _text_mentions_other_person(owner: str, text: str) -> bool:
    for match in _DIALOGUE_SPEAKER_RE.finditer(text):
        if owner and person_labels_match(match.group("speaker"), owner):
            continue
        return True
    for match in _LABEL_TOKEN_RE.finditer(text):
        label = match.group(0)
        if owner and person_labels_match(label, owner):
            continue
        label_key = "".join(char for char in label.casefold() if char.isalnum())
        if label_key.startswith("d") and label_key[1:].isdigit():
            continue
        return True
    return False


def _valid_label(label: str) -> bool:
    return bool(person_alias_keys(label)) and label.casefold() not in _QUERY_LABEL_STOP_WORDS
