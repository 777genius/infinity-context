"""Evidence matching helpers for action-role rerank policy."""

from __future__ import annotations

import re

import infinity_context_core.application.context_action_role_labels as _action_role_labels

_LABEL_RE = _action_role_labels.LABEL_RE
_QUERY_LABEL_RE = _action_role_labels.QUERY_LABEL_RE
_INFO_SOURCE_VERB_RE = (
    r"hear(?:d|s|ing)?|learn(?:ed|s|ing)?|find\s+out|found\s+out|"
    r"узнал(?:а|и)?|услышал(?:а|и)?"
)
_BORROW_SOURCE_VERB_RE = r"borrow(?:ed|s|ing)?"
_RECIPIENT_FOLLOWUP_ACTION_RE = (
    r"read|watch(?:ed)?|try|tried|buy|bought|use|used|visit(?:ed)?|"
    r"listen(?:ed)?|start(?:ed)?|play(?:ed)?|make|made|eat|ate"
)
_REPORTED_SUBJECT_SHIFT_RE = re.compile(
    rf"\b(?:heard|learned|mentioned|reported|said|told|wrote)\b"
    rf".{{0,80}}\b{_LABEL_RE}\W*$",
    re.IGNORECASE | re.DOTALL,
)
_NEGATED_ACTION_GAP_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|never|not|"
    r"cannot|can\s+not|can't|could\s+not|couldn't|would\s+not|wouldn't|"
    r"no\s+longer)\b|"
    r"\b(?:не|никогда\s+не)\b",
    re.IGNORECASE | re.DOTALL,
)
_NEGATION_CANCEL_RE = re.compile(
    r"\bnot\s+only\b|\bне\s+только\b",
    re.IGNORECASE | re.DOTALL,
)
_DIRECT_RECIPIENT_VERBS = frozenset(
    {
        "ask",
        "assign",
        "call",
        "give",
        "help",
        "introduce",
        "lend",
        "message",
        "promise",
        "send",
        "tell",
    }
)

def _owner_labels_in_text(text: str) -> frozenset[str]:
    labels: set[str] = set()
    for pattern in (
        rf"(?P<label>{_LABEL_RE})\b.{{0,80}}\b(?:owns?|owner|responsible)\b",
        rf"\b(?:owner|responsible)\b.{{0,80}}\b(?P<label>{_LABEL_RE})\b",
        rf"\bassigned\s+to\s+(?P<label>{_LABEL_RE})\b",
    ):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            label = _action_role_labels.clean_label(match.group("label"))
            if label:
                labels.add(label)
    return frozenset(labels)


def _has_support_presence_for_recipient(text: str, *, recipient: str) -> bool:
    recipient_pattern = _action_role_labels.role_label_pattern(recipient)
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:is|was|were|are|has\s+been|have\s+been|'s)\s+"
            rf"there\s+for\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:был|была|были)\s+рядом\s+с\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_negated_support_presence_for_recipient(text: str, *, recipient: str) -> bool:
    recipient_pattern = _action_role_labels.role_label_pattern(recipient)
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\b"
            rf"(?:was|were|is|are|has\s+been|have\s+been)\s+not\s+"
            rf"there\s+for\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"\b{_LABEL_RE}\b.{{0,80}}\bне\s+"
            rf"(?:был|была|были)\s+рядом\s+с\s+{recipient_pattern}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _recipient_present_for_other(text: str, *, recipient: str) -> bool:
    recipient_pattern = _action_role_labels.role_label_pattern(recipient)
    return bool(
        re.search(
            rf"{recipient_pattern}.{{0,80}}\b"
            rf"(?:is|was|were|are|has\s+been|have\s+been|'s)\s+"
            rf"there\s+for\s+{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        or re.search(
            rf"{recipient_pattern}.{{0,80}}\b"
            rf"(?:был|была|были)\s+рядом\s+с\s+{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_ordered_action(
    text: str,
    *,
    actor: str,
    verb_key: str,
    target: str,
) -> bool:
    return bool(
        _ordered_action_match_iter(
            text,
            actor=actor,
            verb_key=verb_key,
            tail_pattern=rf".{{0,100}}{_action_role_labels.label_pattern(target)}",
        )
    )


def _has_ordered_action_object_to_recipient(
    text: str,
    *,
    verb_key: str,
    object_label: str,
    recipient: str,
) -> bool:
    return bool(
        re.search(
            rf"\b(?:{_verb_forms(verb_key)})\b.{{0,80}}"
            rf"{_action_role_labels.role_label_pattern(object_label)}.{{0,80}}\b"
            rf"(?:{_recipient_preposition_forms(verb_key)})\s+"
            rf"{_action_role_labels.role_label_pattern(recipient)}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_actor_action_object_to_any_recipient(
    text: str,
    *,
    actor: str,
    verb_key: str,
    object_label: str,
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b.{{0,80}}"
        rf"{_action_role_labels.role_label_pattern(object_label)}.{{0,80}}\b"
        rf"(?:{_recipient_preposition_forms(verb_key)})\s+"
        rf"(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient and _action_role_labels.looks_like_text_recipient(recipient):
            return True
    return False


def _ordered_action_match_iter(
    text: str,
    *,
    actor: str,
    verb_key: str,
    tail_pattern: str,
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf"{tail_pattern}",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return any(
        not _action_gap_blocks_positive_match(match.group("gap"))
        for match in pattern.finditer(text)
    )


def _has_actor_action(text: str, *, actor: str, verb_key: str) -> bool:
    return _ordered_action_match_iter(
        text,
        actor=actor,
        verb_key=verb_key,
        tail_pattern="",
    )


def _has_negated_actor_action(
    text: str,
    *,
    actor: str,
    verb_key: str,
    target: str = "",
    recipient_requested: bool = False,
    context_terms: tuple[str, ...] = (),
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if not _negated_action_gap(match.group("gap")):
            continue
        body = match.group("body")
        if target and not re.search(
            _action_role_labels.recipient_label_pattern(target, verb_key=verb_key),
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            continue
        if recipient_requested and not _body_has_recipient_for_verb(
            body,
            verb_key=verb_key,
        ):
            continue
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        return True
    return False


def _has_actor_action_to_any_recipient(text: str, *, actor: str, verb_key: str) -> bool:
    preposition_pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf".{{0,140}}\b(?:to|for)\s+(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in preposition_pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient and _action_role_labels.looks_like_text_recipient(recipient):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
            rf"(?:{_verb_forms(verb_key)})\b\s+"
            rf"(?P<recipient>{_LABEL_RE})\b(?P<tail>.{{0,40}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            recipient = _action_role_labels.clean_label(match.group("recipient"))
            if (
                recipient
                and _action_role_labels.looks_like_direct_recipient(recipient)
                and _direct_recipient_context_allows(verb_key, match.group("tail"))
            ):
                return True
    passive_pattern = re.compile(
        rf"(?P<recipient>{_LABEL_RE})\b.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b.{{0,140}}\bby\s+{_action_role_labels.label_pattern(actor)}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in passive_pattern.finditer(text):
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient and _action_role_labels.looks_like_text_recipient(recipient):
            return True
    if verb_key != "recommend":
        return False
    russian_direct_pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)"
        rf"\b(?:{_russian_recommendation_forms()})\b\s+"
        rf"(?P<recipient>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    for match in russian_direct_pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        recipient = _action_role_labels.clean_label(match.group("recipient"))
        if recipient and _action_role_labels.looks_like_text_recipient(recipient):
            return True
    return False


def _has_actor_action_to_any_recipient_with_context(
    text: str,
    *,
    actor: str,
    verb_key: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms(verb_key)})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if not _body_has_recipient_for_verb(body, verb_key=verb_key):
            continue
        if _context_terms_match(body, context_terms):
            return True
    return False


def _body_has_recipient_for_verb(body: str, *, verb_key: str) -> bool:
    if re.search(rf"\b(?:to|for)\s+{_LABEL_RE}\b", body):
        return True
    if verb_key not in _DIRECT_RECIPIENT_VERBS:
        return False
    direct_match = re.match(
        rf"\s+(?P<recipient>{_LABEL_RE})\b(?P<tail>.{{0,80}})",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if direct_match is None:
        return False
    recipient = _action_role_labels.clean_label(direct_match.group("recipient"))
    if not _action_role_labels.looks_like_direct_recipient(recipient):
        return False
    return _direct_recipient_context_allows(verb_key, direct_match.group("tail"))


def _reported_subject_shift_before_action(gap: str) -> bool:
    return bool(_REPORTED_SUBJECT_SHIFT_RE.search(gap))


def _action_gap_blocks_positive_match(gap: str) -> bool:
    return _reported_subject_shift_before_action(gap) or _negated_action_gap(gap)


def _negated_action_gap(gap: str) -> bool:
    if not gap:
        return False
    if _NEGATION_CANCEL_RE.search(gap):
        return False
    return bool(_NEGATED_ACTION_GAP_RE.search(gap))


def _action_prefix_blocks_positive_match(text: str, action_start: int) -> bool:
    prefix = text[max(0, action_start - 64) : action_start]
    return _negated_action_gap(prefix)


def _has_actor_info_from_any_source(text: str, *, actor: str) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_INFO_SOURCE_VERB_RE})\b.{{0,160}}\b(?:from|от)\b(?P<tail>.{{0,80}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        if _source_tail_has_evidence(match.group("tail")):
            return True
    return False


def _has_source_told_actor(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"\b{_LABEL_RE}\b.{{0,100}}\b"
            rf"(?:told|said|mentioned|reported|wrote|"
            rf"сказал(?:а)?|рассказал(?:а)?|упомянул(?:а)?)\b"
            rf".{{0,100}}{_action_role_labels.label_pattern(actor)}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _actor_tells_other(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"{_action_role_labels.label_pattern(actor)}.{{0,100}}\b"
            rf"(?:told|said|mentioned|reported|wrote|"
            rf"сказал(?:а)?|рассказал(?:а)?|упомянул(?:а)?)\b"
            rf".{{0,80}}\b{_LABEL_RE}\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_other_actor_info_from_source(text: str, *, expected_actor: str) -> bool:
    expected = _action_role_labels.normalized_label(expected_actor)
    pattern = re.compile(
        rf"(?P<actor>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_INFO_SOURCE_VERB_RE})\b.{{0,160}}\b(?:from|от)\b(?P<tail>.{{0,80}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        actor = _action_role_labels.clean_label(match.group("actor"))
        if (
            actor
            and _action_role_labels.normalized_label(actor) != expected
            and _source_tail_has_evidence(match.group("tail"))
        ):
            return True
    return False


def _has_info_actor_without_source(text: str, *, actor: str) -> bool:
    return bool(
        re.search(
            rf"{_action_role_labels.label_pattern(actor)}.{{0,80}}\b(?:{_INFO_SOURCE_VERB_RE})\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _source_tail_has_evidence(tail: str) -> bool:
    normalized = tail.casefold()
    if re.search(rf"\b{_LABEL_RE}\b", tail):
        return True
    return bool(
        re.search(
            r"\b(?:a|an|the|elderly|veteran|friend|teacher|doctor|mentor|"
            r"colleague|teammate|volunteer|отец|мать|друг|подруга|учитель|"
            r"врач|ментор|коллега)\b",
            normalized,
        )
    )


def _has_actor_borrow_from_source(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if _borrow_body_has_source(body):
            return True
    return False


def _has_source_lent_to_actor(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    actor_key = _action_role_labels.normalized_label(actor)
    pattern = re.compile(
        rf"(?P<source>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_verb_forms('lend')})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        source = _action_role_labels.clean_label(match.group("source"))
        if not _action_role_labels.looks_like_text_recipient(source):
            continue
        if _action_role_labels.normalized_label(source) == actor_key:
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if re.search(
            _action_role_labels.recipient_label_pattern(actor, verb_key="lend"),
            body,
            re.IGNORECASE,
        ):
            return True
    return False


def _actor_lent_to_other(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    if context_terms:
        return _has_actor_action_to_any_recipient_with_context(
            text,
            actor=actor,
            verb_key="lend",
            context_terms=context_terms,
        )
    return _has_actor_action_to_any_recipient(text, actor=actor, verb_key="lend")


def _other_borrowed_from_actor(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    actor_key = _action_role_labels.normalized_label(actor)
    pattern = re.compile(
        rf"(?P<borrower>{_LABEL_RE})(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,220}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        borrower = _action_role_labels.clean_label(match.group("borrower"))
        if not _action_role_labels.looks_like_text_recipient(borrower):
            continue
        if _action_role_labels.normalized_label(borrower) == actor_key:
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if re.search(
            rf"\bfrom\s+{_action_role_labels.label_pattern(actor)}\b|{_action_role_labels.label_pattern(actor)}(?:'s|s')",
            body,
            re.IGNORECASE | re.DOTALL,
        ):
            return True
    return False


def _has_actor_borrow_without_source(
    text: str,
    *,
    actor: str,
    context_terms: tuple[str, ...],
) -> bool:
    pattern = re.compile(
        rf"{_action_role_labels.label_pattern(actor)}(?P<gap>.{{0,80}}?)\b"
        rf"(?:{_BORROW_SOURCE_VERB_RE})\b(?P<body>.{{0,160}})",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        body = match.group("body")
        if context_terms and not _context_terms_match(body, context_terms):
            continue
        if not _borrow_body_has_source(body):
            return True
    return False


def _borrow_body_has_source(body: str) -> bool:
    from_match = re.search(
        rf"\bfrom\s+(?P<source>{_LABEL_RE})\b",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if from_match is not None:
        source = _action_role_labels.clean_label(from_match.group("source"))
        if _action_role_labels.looks_like_text_recipient(source):
            return True
    possessive_match = re.search(
        rf"\b(?P<source>{_LABEL_RE})(?:'s|s')\b",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if possessive_match is None:
        return False
    source = _action_role_labels.clean_label(possessive_match.group("source"))
    return _action_role_labels.looks_like_text_recipient(source)


def _has_non_actor_action(text: str, *, expected_actor: str, verb_key: str) -> bool:
    pattern = re.compile(
        rf"(?=\b(?P<actor>{_LABEL_RE})\b(?P<gap>.{{0,80}}?)"
        rf"\b(?:{_verb_forms(verb_key)})\b)",
        re.IGNORECASE | re.DOTALL,
    )
    expected = _action_role_labels.normalized_label(expected_actor)
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        actor = _action_role_labels.clean_label(match.group("actor"))
        if actor and _action_role_labels.normalized_label(actor) != expected:
            return True
    return False


def _has_action_to_recipient(text: str, *, recipient: str, verb_key: str) -> bool:
    recipient_pattern = _action_role_labels.recipient_label_pattern(recipient, verb_key=verb_key)
    preposition_match = re.search(
        rf"\b(?:{_verb_forms(verb_key)})\b.{{0,140}}\b(?:to|for)\s+"
        rf"{recipient_pattern}",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if preposition_match is not None and not _action_prefix_blocks_positive_match(
        text,
        preposition_match.start(),
    ):
        return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_match = re.search(
            rf"\b(?:{_verb_forms(verb_key)})\b\s+"
            rf"{recipient_pattern}(?P<tail>.{{0,40}})",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if (
            direct_match is not None
            and not _action_prefix_blocks_positive_match(text, direct_match.start())
            and _direct_recipient_context_allows(
                verb_key,
                direct_match.group("tail"),
            )
        ):
            return True
    passive_match = re.search(
        rf"{recipient_pattern}.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if passive_match is not None and not _negated_action_gap(passive_match.group(0)):
        return True
    if verb_key != "recommend":
        return False
    if _has_recommendation_that_recipient_acts(text, recipient=recipient):
        return True
    return bool(
        re.search(
            rf"\b(?:{_russian_recommendation_forms()})\b\s+{recipient_pattern}",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _has_negated_action_to_recipient(
    text: str,
    *,
    recipient: str,
    verb_key: str,
    object_label: str = "",
) -> bool:
    recipient_pattern = _action_role_labels.recipient_label_pattern(recipient, verb_key=verb_key)
    target_pattern = (
        rf".{{0,100}}{_action_role_labels.role_label_pattern(object_label)}"
        if object_label
        else rf".{{0,140}}(?:to|for)\s+{recipient_pattern}"
    )
    preposition_pattern = re.compile(
        rf"\b(?:{_verb_forms(verb_key)})\b{target_pattern}",
        re.IGNORECASE | re.DOTALL,
    )
    for match in preposition_pattern.finditer(text):
        if _action_prefix_blocks_positive_match(text, match.start()):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"\b(?:{_verb_forms(verb_key)})\b\s+"
            rf"{recipient_pattern}(?P<tail>.{{0,80}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_prefix_blocks_positive_match(
                text,
                match.start(),
            ) and _direct_recipient_context_allows(verb_key, match.group("tail")):
                return True
    passive_pattern = re.compile(
        rf"{recipient_pattern}.{{0,100}}\b(?:was|were)\s+"
        rf"(?:{_verb_forms(verb_key)})\b",
        re.IGNORECASE | re.DOTALL,
    )
    return any(_negated_action_gap(match.group(0)) for match in passive_pattern.finditer(text))


def _recipient_acts_to_other(text: str, *, recipient: str, verb_key: str) -> bool:
    recipient_pattern = _action_role_labels.recipient_label_pattern(recipient, verb_key=verb_key)
    pattern = re.compile(
        rf"{recipient_pattern}(?P<gap>.{{0,80}}?)\b(?:{_verb_forms(verb_key)})\b"
        rf".{{0,140}}\b(?:to|for)\s+(?P<other>{_LABEL_RE})\b",
        re.IGNORECASE | re.DOTALL,
    )
    recipient_key = _action_role_labels.normalized_label(recipient)
    for match in pattern.finditer(text):
        if _action_gap_blocks_positive_match(match.group("gap")):
            continue
        other = _action_role_labels.clean_label(match.group("other"))
        if (
            other
            and _action_role_labels.looks_like_text_recipient(other)
            and _action_role_labels.normalized_label(other) != recipient_key
        ):
            return True
    if verb_key in _DIRECT_RECIPIENT_VERBS:
        direct_pattern = re.compile(
            rf"{recipient_pattern}(?P<gap>.{{0,80}}?)\b"
            rf"(?:{_verb_forms(verb_key)})\b\s+"
            rf"(?P<other>{_LABEL_RE})\b(?P<tail>.{{0,40}})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _action_role_labels.clean_label(match.group("other"))
            if (
                other
                and _action_role_labels.looks_like_text_recipient(other)
                and _action_role_labels.normalized_label(other) != recipient_key
                and _direct_recipient_context_allows(verb_key, match.group("tail"))
            ):
                return True
    if verb_key == "recommend":
        that_action_pattern = re.compile(
            rf"{_action_role_labels.label_pattern(recipient)}(?P<gap>.{{0,80}}?)"
            rf"\b(?:{_verb_forms(verb_key)})\b.{{0,80}}\b"
            rf"(?:that\s+)?(?P<other>{_LABEL_RE})\s+"
            rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
            re.IGNORECASE | re.DOTALL,
        )
        for match in that_action_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _action_role_labels.clean_label(match.group("other"))
            if (
                other
                and _action_role_labels.looks_like_text_recipient(other)
                and _action_role_labels.normalized_label(other) != recipient_key
            ):
                return True
        russian_direct_pattern = re.compile(
            rf"{_action_role_labels.label_pattern(recipient)}(?P<gap>.{{0,80}}?)"
            rf"\b(?:{_russian_recommendation_forms()})\b\s+(?P<other>{_LABEL_RE})\b",
            re.IGNORECASE | re.DOTALL,
        )
        for match in russian_direct_pattern.finditer(text):
            if _action_gap_blocks_positive_match(match.group("gap")):
                continue
            other = _action_role_labels.clean_label(match.group("other"))
            if (
                other
                and _action_role_labels.looks_like_text_recipient(other)
                and _action_role_labels.normalized_label(other) != recipient_key
            ):
                return True
    return False


def _has_recommendation_that_recipient_acts(text: str, *, recipient: str) -> bool:
    return bool(
        re.search(
            rf"\b(?:{_verb_forms('recommend')})\b.{{0,100}}\b"
            rf"(?:that\s+)?{_action_role_labels.label_pattern(recipient)}\s+"
            rf"(?:{_RECIPIENT_FOLLOWUP_ACTION_RE})\b",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _context_terms_match(text: str, context_terms: tuple[str, ...]) -> bool:
    if not context_terms:
        return True
    normalized = text.casefold()
    hits = sum(1 for term in context_terms if term in normalized)
    required = min(len(context_terms), 2)
    return hits >= required


def _verb_forms(verb_key: str) -> str:
    forms = {
        "recommend": (
            r"recommend(?:ed|s|ing)?|suggest(?:ed|s|ing)?|"
            r"made\s+(?:a\s+|the\s+)?(?:recommendation|suggestion)|"
            rf"{_russian_recommendation_forms()}"
        ),
        "introduce": (
            r"introduc(?:e|ed|es|ing)|"
            r"познакомил(?:а|и)?|представил(?:а|и)?"
        ),
        "promise": (
            r"promise(?:d|s|ing)?|made\s+(?:a\s+|the\s+)?promise|"
            r"пообещал(?:а)?|обещал(?:а)?"
        ),
        "decide": r"decid(?:e|ed|es|ing)|made\s+(?:a\s+|the\s+)?decision|решил(?:а)?",
        "ask": r"ask(?:ed|s|ing)?|спросил(?:а)?",
        "assign": r"assign(?:ed|s|ing)?|назначил(?:а)?",
        "approve": r"approv(?:e|ed|es|ing)|одобрил(?:а)?",
        "call": r"call(?:ed|s|ing)?",
        "help": (
            r"help(?:ed|s|ing)?|assist(?:ed|s|ing)?|support(?:ed|s|ing)?|"
            r"помог(?:ла|ли)?|поддержал(?:а|и)?"
        ),
        "message": r"message(?:d|s|ing)?|text(?:ed|s|ing)?",
        "send": r"send|sent",
        "give": r"give|gave|given",
        "lend": r"lend|lent",
        "tell": r"tell|told|сказал(?:а)?",
    }
    return forms.get(verb_key, r"(?!x)x")


def _recipient_preposition_forms(verb_key: str) -> str:
    if verb_key == "introduce":
        return r"to|for|with|с|со"
    return r"to|for"


def _russian_recommendation_forms() -> str:
    return r"рекомендовал(?:а)?|порекомендовал(?:а)?|посоветовал(?:а)?"


def _direct_recipient_context_allows(verb_key: str, tail: str) -> bool:
    normalized = tail.casefold()
    if verb_key in {"ask", "tell"}:
        context_markers = (
            r"about|regarding|whether|if|that|to|why|how|when|where|"
            r"про|что|о|об|почему|как|когда|где"
        )
        if verb_key == "ask":
            context_markers = (
                r"about|regarding|whether|if|that|to|for|why|how|when|where|"
                r"про|что|о|об|почему|как|когда|где"
            )
        return bool(
            re.match(
                rf"\s*(?:{context_markers})\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "message":
        return bool(
            re.match(
                r"\s*(?:about|regarding|whether|if|that|why|how|when|where|"
                r"про|что|о|об|почему|как|когда|где)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "call":
        return bool(
            re.match(
                r"\s*(?:about|regarding|after|before|during|on|at|when|where|"
                r"про|о|об|после|до|во\s+время|когда|где)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "introduce":
        return bool(
            re.match(
                r"\s*(?:to|with|for|at|during|after|before|on|in|"
                r"с|со|на|во\s+время|после|до)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "help":
        return bool(
            re.match(
                r"\s*(?:with|on|through|during|after|before|about|for|in|at|"
                r"с|со|по|в|на|во\s+время|после|до|про|о|об)\b|\s*[,.;!?]?\s*$",
                normalized,
            )
        )
    if verb_key == "promise":
        return bool(
            re.match(
                r"\s*(?:to|that|he|she|they|we|i|it|would|will|что|он|она|они|мы)\b",
                normalized,
            )
        )
    return True
