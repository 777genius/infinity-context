"""Owner grounding signals for possessive/pronoun object evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class OwnerGroundingSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _OwnerObjectQuery:
    owner_label: str
    object_term: str


@dataclass(frozen=True)
class _PronounObjectRelation:
    antecedent_labels: tuple[str, ...]


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_OWNED_OBJECT_RE = (
    r"dogs?|cats?|pupp(?:y|ies)|pups?|pets?|laptops?|computers?|classes?|courses?|"
    r"plans?|tickets?|tasks?|issues?"
)
_POSSESSIVE_OBJECT_QUERY_RE = re.compile(
    rf"\b(?P<owner>{_LABEL_RE})(?:'s|s')?\s+(?P<object>(?i:{_OWNED_OBJECT_RE}))\b",
)
_OWNER_HAS_OBJECT_QUERY_RE = re.compile(
    rf"(?i:\b(?:does|did|has|have|what|which)\b)"
    rf"(?=.{{0,90}}\b(?P<object>(?i:{_OWNED_OBJECT_RE}))\b)"
    rf"(?=.{{0,90}}\b(?P<owner>{_LABEL_RE})\b)"
    r"(?=.{0,120}\b(?:have|has|own|owns|use|uses|work(?:s|ed|ing)?\s+on|"
    r"assigned|named|called|taking|take|attend(?:s|ed|ing)?|plan(?:s|ned|ning)?)\b)",
    re.DOTALL,
)
_WHAT_OBJECT_DOES_OWNER_QUERY_RE = re.compile(
    rf"(?i:\b(?:what|which)\s+)(?P<object>{_OWNED_OBJECT_RE})"
    rf"(?i:\s+(?:does|did)\s+)(?P<owner>{_LABEL_RE})\s+"
    r"(?i:(?:have|own|use|work(?:s|ed|ing)?\s+on|take|attend|plan))\b",
)
_DOES_OWNER_HAVE_OBJECT_QUERY_RE = re.compile(
    rf"(?i:\b(?:does|did|has|have)\s+)(?P<owner>{_LABEL_RE})\s+"
    r"(?i:(?:have|own|use|work(?:s|ed|ing)?\s+on|take|attend|plan)\b)"
    rf"(?=.{{0,80}}\b(?P<object>{_OWNED_OBJECT_RE})\b)",
    re.DOTALL,
)
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):",
    re.IGNORECASE,
)
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_SENTENCE_RE = re.compile(r"[^.?!;\n]+")
_QUERY_LABEL_STOP_WORDS = frozenset(
    {
        "did",
        "does",
        "has",
        "have",
        "her",
        "his",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "why",
        "their",
    }
)
_OBJECT_NORMALIZATIONS = {
    "cats": "cat",
    "classes": "class",
    "computers": "computer",
    "courses": "course",
    "dogs": "dog",
    "issues": "issue",
    "laptops": "laptop",
    "pets": "pet",
    "plans": "plan",
    "puppies": "puppy",
    "pups": "pup",
    "tasks": "task",
    "tickets": "ticket",
}
_SELF_POSSESSIVE_RE = re.compile(r"\b(?:my|our)\b", re.IGNORECASE)
_THIRD_PERSON_POSSESSIVE_OBJECT_RE = r"\b(?P<pronoun>her|his|their)\s+(?:\w+\s+){0,3}"
_OWNER_RELATION_RE = re.compile(
    r"\b(?:has|have|had|owns?|owned|uses?|used|keeps?|kept|got|adopt(?:ed|s)?|"
    r"named|called|taking|took|attends?|attended|work(?:s|ed|ing)?\s+on|"
    r"assigned|opened|filed|plan(?:s|ned|ning)?|belongs?\s+to)\b",
    re.IGNORECASE,
)
_GENERIC_OBJECT_ARTICLE_RE = re.compile(r"\b(?:the|a|an|this|that)\b", re.IGNORECASE)


def owner_grounding_signal(*, query: str, text: str) -> OwnerGroundingSignal:
    """Return bounded signal for named-owner object evidence grounded by pronouns."""

    owner_query = _owner_object_query(query)
    if owner_query is None:
        return OwnerGroundingSignal()
    object_pattern = _object_pattern(owner_query.object_term)
    if object_pattern.search(text) is None:
        return OwnerGroundingSignal()
    if _text_has_owner_grounded_object(owner_query, text, object_pattern):
        return OwnerGroundingSignal(boost=0.026, reason="owner_grounded_object_match")
    if _text_has_other_owner_object(owner_query, text, object_pattern):
        return OwnerGroundingSignal(penalty=0.032, reason="owner_grounded_object_other_owner")
    return OwnerGroundingSignal()


def _owner_object_query(query: str) -> _OwnerObjectQuery | None:
    for pattern in (
        _POSSESSIVE_OBJECT_QUERY_RE,
        _WHAT_OBJECT_DOES_OWNER_QUERY_RE,
        _DOES_OWNER_HAVE_OBJECT_QUERY_RE,
        _OWNER_HAS_OBJECT_QUERY_RE,
    ):
        for match in pattern.finditer(query):
            owner = _clean_label(match.group("owner"))
            object_term = _normalize_object(match.group("object"))
            if not owner or not object_term:
                continue
            if owner.casefold() in _QUERY_LABEL_STOP_WORDS or not person_alias_keys(owner):
                continue
            return _OwnerObjectQuery(owner_label=owner, object_term=object_term)
    return None


def _text_has_owner_grounded_object(
    owner_query: _OwnerObjectQuery,
    text: str,
    object_pattern: re.Pattern[str],
) -> bool:
    for sentence, speaker in _sentences_with_speaker(text):
        if object_pattern.search(sentence) is None:
            continue
        if (
            speaker
            and person_labels_match(speaker, owner_query.owner_label)
            and _has_self_object_relation(sentence, object_pattern)
        ):
            return True
        if _has_named_owner_object_relation(
            sentence,
            owner_query=owner_query,
            object_pattern=object_pattern,
        ):
            return True
    return False


def _text_has_other_owner_object(
    owner_query: _OwnerObjectQuery,
    text: str,
    object_pattern: re.Pattern[str],
) -> bool:
    for sentence, speaker in _sentences_with_speaker(text):
        if object_pattern.search(sentence) is None:
            continue
        if _has_named_owner_object_relation(
            sentence,
            owner_query=owner_query,
            object_pattern=object_pattern,
        ):
            continue
        if (
            speaker
            and not person_labels_match(speaker, owner_query.owner_label)
            and (
                _has_self_object_relation(sentence, object_pattern)
                or _has_generic_object_relation(sentence, object_pattern)
            )
        ):
            return True
        if _has_other_named_possessive(sentence, owner_query.owner_label, object_pattern):
            return True
        if _has_other_pronoun_object_relation(
            sentence,
            owner_query=owner_query,
            object_pattern=object_pattern,
        ):
            return True
    return False


def _sentences_with_speaker(text: str) -> tuple[tuple[str, str], ...]:
    spans: list[tuple[str, str]] = []
    for sentence_match in _SENTENCE_RE.finditer(text):
        sentence = sentence_match.group(0)
        speaker = ""
        for speaker_match in _DIALOGUE_SPEAKER_RE.finditer(text, 0, sentence_match.end()):
            speaker = speaker_match.group("speaker")
        spans.append((sentence, speaker))
    return tuple(spans)


def _has_named_owner_object_relation(
    sentence: str,
    *,
    owner_query: _OwnerObjectQuery,
    object_pattern: re.Pattern[str],
) -> bool:
    owner_pattern = _label_pattern(owner_query.owner_label)
    if re.search(
        rf"{owner_pattern}(?:'s|s')?\s+(?:\w+\s+){{0,3}}{object_pattern.pattern}",
        sentence,
        re.IGNORECASE,
    ):
        return True
    if _has_owner_pronoun_object_relation(
        sentence,
        owner_query=owner_query,
        object_pattern=object_pattern,
    ):
        return True
    if (
        _has_other_named_possessive(sentence, owner_query.owner_label, object_pattern)
        or _has_other_pronoun_object_relation(
            sentence,
            owner_query=owner_query,
            object_pattern=object_pattern,
        )
    ):
        return False
    return bool(
        re.search(
            rf"{owner_pattern}\b(?=.{{0,120}}{object_pattern.pattern})"
            rf"(?=.{{0,120}}{_OWNER_RELATION_RE.pattern})",
            sentence,
            re.IGNORECASE | re.DOTALL,
        )
    )


def _has_owner_pronoun_object_relation(
    sentence: str,
    *,
    owner_query: _OwnerObjectQuery,
    object_pattern: re.Pattern[str],
) -> bool:
    for relation in _pronoun_object_relations(sentence, object_pattern):
        if any(
            person_labels_match(label, owner_query.owner_label)
            for label in relation.antecedent_labels
        ):
            return True
    return False


def _has_other_pronoun_object_relation(
    sentence: str,
    *,
    owner_query: _OwnerObjectQuery,
    object_pattern: re.Pattern[str],
) -> bool:
    for relation in _pronoun_object_relations(sentence, object_pattern):
        if relation.antecedent_labels and not any(
            person_labels_match(label, owner_query.owner_label)
            for label in relation.antecedent_labels
        ):
            return True
    return False


def _pronoun_object_relations(
    sentence: str,
    object_pattern: re.Pattern[str],
) -> tuple[_PronounObjectRelation, ...]:
    relations: list[_PronounObjectRelation] = []
    mention_pattern = re.compile(
        rf"{_THIRD_PERSON_POSSESSIVE_OBJECT_RE}{object_pattern.pattern}",
        re.IGNORECASE,
    )
    for match in mention_pattern.finditer(sentence):
        pronoun = match.group("pronoun").casefold()
        labels = _nearby_pronoun_antecedent_labels(sentence, match.start(), pronoun)
        if labels:
            relations.append(_PronounObjectRelation(antecedent_labels=labels))
    return tuple(relations)


def _nearby_pronoun_antecedent_labels(
    sentence: str,
    pronoun_start: int,
    pronoun: str,
) -> tuple[str, ...]:
    labels = _preceding_non_speaker_labels(sentence, pronoun_start)
    if not labels:
        return ()
    if pronoun == "their":
        return labels[-2:]
    return (labels[-1],)


def _preceding_non_speaker_labels(sentence: str, end: int) -> tuple[str, ...]:
    labels: list[str] = []
    prefix = sentence[:end]
    for label_match in _LABEL_TOKEN_RE.finditer(prefix):
        label = _clean_label(label_match.group(0))
        if not label or label.casefold() in _QUERY_LABEL_STOP_WORDS:
            continue
        tail = prefix[label_match.end() : label_match.end() + 1]
        if tail == ":":
            continue
        labels.append(label)
    return tuple(labels)


def _has_self_object_relation(sentence: str, object_pattern: re.Pattern[str]) -> bool:
    return bool(
        re.search(
            rf"{_SELF_POSSESSIVE_RE.pattern}\s+(?:\w+\s+){{0,3}}{object_pattern.pattern}",
            sentence,
            re.IGNORECASE,
        )
        or re.search(
            rf"\b(?:i|we)\b(?=.{{0,120}}{object_pattern.pattern})"
            rf"(?=.{{0,120}}{_OWNER_RELATION_RE.pattern})",
            sentence,
            re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"{object_pattern.pattern}\s+(?:is|was|are|were)\s+(?:mine|ours)\b",
            sentence,
            re.IGNORECASE,
        )
    )


def _has_generic_object_relation(sentence: str, object_pattern: re.Pattern[str]) -> bool:
    return bool(
        re.search(
            rf"{_GENERIC_OBJECT_ARTICLE_RE.pattern}\s+{object_pattern.pattern}",
            sentence,
            re.IGNORECASE,
        )
        and _OWNER_RELATION_RE.search(sentence)
    )


def _has_other_named_possessive(
    sentence: str,
    owner_label: str,
    object_pattern: re.Pattern[str],
) -> bool:
    for label_match in _LABEL_TOKEN_RE.finditer(sentence):
        label = label_match.group(0)
        if label.casefold() in _QUERY_LABEL_STOP_WORDS:
            continue
        if person_labels_match(label, owner_label):
            continue
        label_end = label_match.end()
        tail = sentence[label_end : label_end + 80]
        if re.search(
            rf"^(?:'s|s')?\s+(?:\w+\s+){{0,3}}{object_pattern.pattern}",
            tail,
            re.IGNORECASE,
        ):
            return True
    return False


def _object_pattern(object_term: str) -> re.Pattern[str]:
    if object_term == "puppy":
        pattern = r"pupp(?:y|ies)"
    elif object_term == "class":
        pattern = r"(?:class|course)"
    elif object_term == "computer":
        pattern = r"(?:computer|laptop)"
    else:
        pattern = rf"{re.escape(object_term)}s?"
    return re.compile(rf"\b{pattern}\b", re.IGNORECASE)


def _normalize_object(value: str) -> str:
    normalized = (value or "").casefold().strip(" :,.!?;")
    return _OBJECT_NORMALIZATIONS.get(normalized, normalized)


def _clean_label(value: str) -> str:
    return (value or "").strip(" :,.!?;")


def _label_pattern(label: str) -> str:
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9._-]*", label)
    if not tokens:
        return rf"(?<!\w){re.escape(label)}(?!\w)"
    alias_patterns = [r"\s+".join(re.escape(token) for token in tokens)]
    if len(tokens) > 1:
        alias_patterns.append(re.escape(tokens[0]))
    return rf"(?<!\w)(?:{'|'.join(alias_patterns)})(?!\w)"
