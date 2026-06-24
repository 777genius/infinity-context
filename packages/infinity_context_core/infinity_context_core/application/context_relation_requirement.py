"""Deterministic relation-shape checks for explicit evidence queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from infinity_context_core.application.context_lexical import lexical_variants


class RelationRequirementSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _Token:
    raw: str
    variants: frozenset[str]
    start: int
    end: int


@dataclass(frozen=True)
class _RelationGroup:
    key: str
    query_re: re.Pattern[str]
    text_re: re.Pattern[str]


@dataclass(frozen=True)
class _RelationRequirement:
    group: _RelationGroup
    subject: _Token
    object_tokens: tuple[_Token, ...]


_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9._-]*", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.?!;\n]+")
_QUESTION_RE = re.compile(
    r"\b(?:do\s+we\s+know|is\s+there\s+any|are\s+there\s+any|"
    r"any\s+(?:evidence|proof|source|record|mention)|"
    r"(?:did|does|has|have)\b|ever\b|"
    r"известно\s+ли|есть\s+ли|когда-либо|упоминал(?:а)?\s+ли)\b|\?",
    re.IGNORECASE,
)
_SUBJECT_STOP_VARIANTS = frozenset(
    {
        "any",
        "are",
        "did",
        "do",
        "does",
        "ever",
        "evidence",
        "has",
        "have",
        "is",
        "know",
        "proof",
        "record",
        "source",
        "that",
        "there",
        "we",
        "whether",
        "есть",
        "известно",
        "ли",
    }
)
_OBJECT_STOP_VARIANTS = frozenset(
    {
        "a",
        "about",
        "after",
        "an",
        "and",
        "any",
        "at",
        "before",
        "by",
        "call",
        "chat",
        "during",
        "event",
        "for",
        "from",
        "in",
        "meeting",
        "on",
        "or",
        "the",
        "thread",
        "to",
        "with",
        "звонок",
        "на",
        "о",
        "об",
        "по",
        "после",
        "про",
        "с",
    }
)
_OBJECT_DESCRIPTOR_STOP_VARIANTS = frozenset(
    {
        "issue",
        "project",
        "repo",
        "repository",
        "ticket",
        "задача",
        "проект",
    }
)
_SPAN_BREAKER_RE = re.compile(
    r"\b(?:and|but|or|then|while|where|when|who|which|"
    r"visited?|went|attended?|joined?|mentioned?|said|told|wrote|"
    r"discussed|talked|bought|purchased|used|played|read|watched|"
    r"и|но|или|потом|где|когда|кто|посетил\w*|упомянул\w*|сказал\w*)\b",
    re.IGNORECASE,
)
_POSSESSIVE_SUFFIX_RE = re.compile(r"(?:'s|’s)$", re.IGNORECASE)

_RELATION_GROUPS: tuple[_RelationGroup, ...] = (
    _RelationGroup(
        key="mention",
        query_re=re.compile(
            r"\b(?:mention(?:ed|s|ing)?|say|said|tell|told|write|wrote|"
            r"brought\s+up|bring\s+up|raise(?:d)?|refer(?:red)?\s+to|"
            r"упомянул\w*|упомина\w*|говорил\w*|сказал\w*|рассказал\w*|"
            r"писал\w*|написал\w*)\b",
            re.IGNORECASE,
        ),
        text_re=re.compile(
            r"\b(?:mention(?:ed|s|ing)?|said|told|wrote|noted|reported|"
            r"brought\s+up|raised|referred\s+to|discussed|talked\s+about|"
            r"упомянул\w*|упомина\w*|говорил\w*|сказал\w*|рассказал\w*|"
            r"писал\w*|написал\w*|сообщил\w*)\b",
            re.IGNORECASE,
        ),
    ),
    _RelationGroup(
        key="possession",
        query_re=re.compile(
            r"\b(?:has|have|had|having|own(?:s|ed|ing)?|keep(?:s|ing)?|"
            r"kept|adopt(?:ed|s|ing)?|got)\b",
            re.IGNORECASE,
        ),
        text_re=re.compile(
            r"\b(?:has|have|had|having|own(?:s|ed|ing)?|keep(?:s|ing)?|"
            r"kept|adopt(?:ed|s|ing)?|got)\b",
            re.IGNORECASE,
        ),
    ),
    _RelationGroup(
        key="visit",
        query_re=re.compile(
            r"\b(?:visit(?:ed|s|ing)?|went\s+to|go\s+to|attend(?:ed|s|ing)?|"
            r"join(?:ed|s|ing)?|посетил\w*|посещал\w*|сходил\w*|ездил\w*)\b",
            re.IGNORECASE,
        ),
        text_re=re.compile(
            r"\b(?:visit(?:ed|s|ing)?|went\s+to|go\s+to|attend(?:ed|s|ing)?|"
            r"join(?:ed|s|ing)?|participat(?:ed|es|ing)|посетил\w*|посещал\w*|"
            r"сходил\w*|ездил\w*)\b",
            re.IGNORECASE,
        ),
    ),
    _RelationGroup(
        key="acquire",
        query_re=re.compile(
            r"\b(?:buy|bought|purchase(?:d|s|ing)?|got|receive(?:d|s|ing)?|"
            r"купил\w*|получил\w*)\b",
            re.IGNORECASE,
        ),
        text_re=re.compile(
            r"\b(?:buy|bought|purchase(?:d|s|ing)?|got|receive(?:d|s|ing)?|"
            r"купил\w*|получил\w*)\b",
            re.IGNORECASE,
        ),
    ),
    _RelationGroup(
        key="use",
        query_re=re.compile(
            r"\b(?:use(?:d|s|ing)?|try|tried|run|ran|install(?:ed|s|ing)?|"
            r"использовал\w*|запустил\w*)\b",
            re.IGNORECASE,
        ),
        text_re=re.compile(
            r"\b(?:use(?:d|s|ing)?|tried|ran|install(?:ed|s|ing)?|"
            r"использовал\w*|запустил\w*)\b",
            re.IGNORECASE,
        ),
    ),
)


def relation_requirement_signal(*, query: str, text: str) -> RelationRequirementSignal:
    """Return a deterministic support/decoy signal for explicit relation queries."""

    requirement = _relation_requirement(query)
    if requirement is None:
        return RelationRequirementSignal()
    if _text_satisfies_requirement(requirement, text):
        return RelationRequirementSignal(boost=0.018, reason="relation_requirement_match")
    if _text_mentions_requirement_anchors(requirement, text):
        return RelationRequirementSignal(
            penalty=0.056,
            reason="relation_requirement_missing_relation",
        )
    if _text_mentions_subject_relation_without_object(requirement, text):
        return RelationRequirementSignal(
            penalty=0.048,
            reason="relation_requirement_object_mismatch",
        )
    return RelationRequirementSignal()


def _relation_requirement(query: str) -> _RelationRequirement | None:
    if not _QUESTION_RE.search(query):
        return None
    tokens = _tokens(query)
    if len(tokens) < 3:
        return None
    for group in _RELATION_GROUPS:
        for relation_match in group.query_re.finditer(query):
            subject = _nearest_subject(tokens, relation_match.start())
            object_tokens = _object_tokens(tokens, relation_match.end())
            if subject is None or not object_tokens:
                continue
            return _RelationRequirement(
                group=group,
                subject=subject,
                object_tokens=object_tokens,
            )
    return None


def _text_satisfies_requirement(requirement: _RelationRequirement, text: str) -> bool:
    for sentence_match in _SENTENCE_RE.finditer(text):
        sentence = sentence_match.group(0)
        if not _has_token_variants(sentence, requirement.subject.variants):
            continue
        if not all(
            _has_token_variants(sentence, token.variants)
            for token in requirement.object_tokens
        ):
            continue
        if requirement.group.key == "possession" and _has_possessive_match(
            requirement,
            sentence,
        ):
            return True
        if _has_active_relation_match(requirement, sentence):
            return True
        if requirement.group.key == "mention" and _has_passive_mention_match(
            requirement,
            sentence,
        ):
            return True
    return False


def _has_active_relation_match(requirement: _RelationRequirement, sentence: str) -> bool:
    subject_pos = _first_variant_position(sentence, requirement.subject.variants)
    object_pos = _first_object_position(sentence, requirement.object_tokens)
    if subject_pos is None or object_pos is None:
        return False
    for relation_match in requirement.group.text_re.finditer(sentence):
        if subject_pos[0] > relation_match.start() or relation_match.end() > object_pos[0]:
            continue
        if _span_has_breaker(sentence[relation_match.end() : object_pos[0]]):
            continue
        return True
    return False


def _has_passive_mention_match(requirement: _RelationRequirement, sentence: str) -> bool:
    subject_pos = _first_variant_position(sentence, requirement.subject.variants)
    object_pos = _first_object_position(sentence, requirement.object_tokens)
    if subject_pos is None or object_pos is None:
        return False
    for relation_match in requirement.group.text_re.finditer(sentence):
        if object_pos[1] > relation_match.start():
            continue
        after_relation = sentence[relation_match.end() : subject_pos[0]]
        if subject_pos[0] > relation_match.end() and re.search(
            r"\bby\b.{0,40}$",
            after_relation,
            re.IGNORECASE,
        ):
            return True
    return False


def _has_possessive_match(requirement: _RelationRequirement, sentence: str) -> bool:
    subject_pos = _first_variant_position(sentence, requirement.subject.variants)
    object_pos = _first_object_position(sentence, requirement.object_tokens)
    if subject_pos is None or object_pos is None or subject_pos[1] > object_pos[0]:
        return False
    between = sentence[subject_pos[1] : object_pos[0]]
    return _POSSESSIVE_SUFFIX_RE.search(sentence[subject_pos[0] : subject_pos[1]]) is not None or (
        len(between) <= 24 and re.search(r"(?:'s|’s)\s*$", between)
    )


def _text_mentions_requirement_anchors(requirement: _RelationRequirement, text: str) -> bool:
    return _has_token_variants(text, requirement.subject.variants) and all(
        _has_token_variants(text, token.variants)
        for token in requirement.object_tokens
    )


def _text_mentions_subject_relation_without_object(
    requirement: _RelationRequirement,
    text: str,
) -> bool:
    for sentence_match in _SENTENCE_RE.finditer(text):
        sentence = sentence_match.group(0)
        if not _has_token_variants(sentence, requirement.subject.variants):
            continue
        if not requirement.group.text_re.search(sentence):
            continue
        if all(_has_token_variants(sentence, token.variants) for token in requirement.object_tokens):
            continue
        return True
    return False


def _nearest_subject(tokens: tuple[_Token, ...], relation_start: int) -> _Token | None:
    before = [token for token in tokens if token.end <= relation_start]
    for token in reversed(before[-6:]):
        if _is_stop_token(token, _SUBJECT_STOP_VARIANTS):
            continue
        return token
    return None


def _object_tokens(tokens: tuple[_Token, ...], relation_end: int) -> tuple[_Token, ...]:
    after = [token for token in tokens if token.start >= relation_end]
    selected: list[_Token] = []
    for token in after[:6]:
        if _is_stop_token(token, _OBJECT_STOP_VARIANTS):
            if selected:
                break
            continue
        selected.append(token)
        if len(selected) >= 3:
            break
    filtered = tuple(
        token for token in selected if not _is_stop_token(token, _OBJECT_DESCRIPTOR_STOP_VARIANTS)
    )
    return filtered or tuple(selected)


def _tokens(text: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    for match in _TOKEN_RE.finditer(text):
        variants = frozenset(lexical_variants(match.group(0)))
        if not variants:
            continue
        tokens.append(
            _Token(
                raw=match.group(0),
                variants=variants,
                start=match.start(),
                end=match.end(),
            )
        )
    return tuple(tokens)


def _is_stop_token(token: _Token, stop_variants: frozenset[str]) -> bool:
    return bool(token.variants.intersection(stop_variants))


def _has_token_variants(text: str, variants: frozenset[str]) -> bool:
    return _first_variant_position(text, variants) is not None


def _first_object_position(
    text: str,
    object_tokens: tuple[_Token, ...],
) -> tuple[int, int] | None:
    positions = tuple(_first_variant_position(text, token.variants) for token in object_tokens)
    if any(position is None for position in positions):
        return None
    present = tuple(position for position in positions if position is not None)
    return (min(position[0] for position in present), max(position[1] for position in present))


def _first_variant_position(text: str, variants: frozenset[str]) -> tuple[int, int] | None:
    for token in _tokens(text):
        if token.variants.intersection(variants):
            return token.start, token.end
    return None


def _span_has_breaker(span: str) -> bool:
    return _SPAN_BREAKER_RE.search(span) is not None
