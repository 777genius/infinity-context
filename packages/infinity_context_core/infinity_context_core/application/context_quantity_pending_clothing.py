"""Pending-clothing target extraction and bounded anaphora resolution."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_quantity_evidence_patterns import (
    _CLOTHING_CANONICAL,
    _CLOTHING_EVIDENCE_RE,
    _CLOTHING_MODIFIER_RE,
    _COORDINATED_COLOR_RE,
    _FIRST_PERSON_PENDING_ACTION_RE,
    _FIRST_PERSON_RE,
    _NAMED_STORE_CONTEXT_RE,
    _PENDING_EVIDENCE_RE,
    _PICKUP_RE,
    _PLURAL_PICKUP_ANAPHORA_RE,
    _PLURAL_RETURN_ANAPHORA_RE,
    _QUANTITY_MODIFIER_RE,
    _QUANTITY_WORDS,
    _RESOLVED_OR_CANCELLED_RE,
    _RETURN_RE,
    _STORE_CONTEXT_RE,
    _THIRD_PARTY_ACTION_RE,
)


@dataclass(frozen=True)
class PendingClothingResolution:
    """Grounded action identities and the sentences needed to support them."""

    identities: tuple[str, ...]
    evidence_sentences: tuple[str, ...]


def resolve_pending_clothing_sentence(
    *,
    action_terms: tuple[str, ...],
    requires_store_context: bool,
    current_sentence: str,
    prior_sentence: str | None,
) -> PendingClothingResolution | None:
    """Resolve an explicit target or a strictly adjacent plural anaphor."""

    current = " ".join(current_sentence.split()).strip()
    if not _is_unresolved_first_person_action(current):
        return None

    anaphoric_actions = _anaphoric_action_matches(action_terms, current)
    current_targets = _target_matches(current)
    if anaphoric_actions and current_targets:
        first_anaphora_position = min(position for _, position in anaphoric_actions)
        if (
            len(current_targets) != 1
            or current_targets[0][0] >= first_anaphora_position
        ):
            return None
    if anaphoric_actions and not current_targets:
        return _resolve_plural_anaphora(
            actions=tuple(action for action, _ in anaphoric_actions),
            requires_store_context=requires_store_context,
            current=current,
            prior_sentence=prior_sentence,
        )

    explicit_identities = _pending_action_identities(action_terms, current)
    if explicit_identities:
        if requires_store_context and not _has_store_context(current):
            return None
        return PendingClothingResolution(
            identities=explicit_identities,
            evidence_sentences=(current,),
        )

    return None


def _resolve_plural_anaphora(
    *,
    actions: tuple[str, ...],
    requires_store_context: bool,
    current: str,
    prior_sentence: str | None,
) -> PendingClothingResolution | None:
    if prior_sentence is None or _target_matches(current):
        return None
    prior = " ".join(prior_sentence.split()).strip()
    if (
        not prior
        or _RESOLVED_OR_CANCELLED_RE.search(prior) is not None
        or _THIRD_PARTY_ACTION_RE.search(prior) is not None
        or (requires_store_context and not _has_store_context(prior, current))
    ):
        return None
    targets = _target_matches(prior)
    if len(targets) != 1:
        return None
    target = targets[0][1]
    return PendingClothingResolution(
        identities=tuple(f"{action}:{target}" for action in actions),
        evidence_sentences=(prior, current),
    )


def _is_unresolved_first_person_action(sentence: str) -> bool:
    return bool(
        sentence
        and _FIRST_PERSON_RE.search(sentence) is not None
        and _PENDING_EVIDENCE_RE.search(sentence) is not None
        and _FIRST_PERSON_PENDING_ACTION_RE.search(sentence) is not None
        and _RESOLVED_OR_CANCELLED_RE.search(sentence) is None
        and _THIRD_PARTY_ACTION_RE.search(sentence) is None
    )


def _has_store_context(*sentences: str) -> bool:
    return any(
        _STORE_CONTEXT_RE.search(sentence) is not None
        or _NAMED_STORE_CONTEXT_RE.search(sentence) is not None
        for sentence in sentences
    )


def _pending_action_identities(
    action_terms: tuple[str, ...],
    sentence: str,
) -> tuple[str, ...]:
    targets = _target_matches(sentence)
    if not targets:
        return ()
    identities: list[str] = []
    for action, pattern in (("pickup", _PICKUP_RE), ("return", _RETURN_RE)):
        if action not in action_terms:
            continue
        for action_match in pattern.finditer(sentence):
            closest_position, _ = min(
                targets,
                key=lambda value: abs(value[0] - action_match.start()),
            )
            for position, target in targets:
                if position != closest_position:
                    continue
                identity = f"{action}:{target}"
                if identity not in identities:
                    identities.append(identity)
    return tuple(identities)


def _anaphoric_action_matches(
    action_terms: tuple[str, ...],
    sentence: str,
) -> tuple[tuple[str, int], ...]:
    actions: list[tuple[str, int]] = []
    for action, pattern in (
        ("pickup", _PLURAL_PICKUP_ANAPHORA_RE),
        ("return", _PLURAL_RETURN_ANAPHORA_RE),
    ):
        if action not in action_terms:
            continue
        if match := pattern.search(sentence):
            actions.append((action, match.start()))
    return tuple(actions)


def _target_matches(sentence: str) -> tuple[tuple[int, str], ...]:
    matches: list[tuple[int, str]] = []
    for match in _CLOTHING_EVIDENCE_RE.finditer(sentence):
        surface = " ".join(match.group("target").casefold().split())
        target = _CLOTHING_CANONICAL.get(surface, surface)
        prefix = sentence[max(0, match.start() - 28) : match.start()]
        coordinated = _COORDINATED_COLOR_RE.search(prefix)
        modifier_matches = tuple(_CLOTHING_MODIFIER_RE.finditer(prefix))
        modifiers = (
            (coordinated.group("first").casefold(), coordinated.group("second").casefold())
            if coordinated
            else (
                (modifier_matches[-1].group(0).casefold(),)
                if modifier_matches
                else ("",)
            )
        )
        quantity_matches = tuple(_QUANTITY_MODIFIER_RE.finditer(prefix))
        quantity = 1
        if quantity_matches:
            raw_quantity = quantity_matches[-1].group("count").casefold()
            quantity = (
                int(raw_quantity)
                if raw_quantity.isdigit()
                else _QUANTITY_WORDS[raw_quantity]
            )
        for modifier in modifiers:
            identity = f"{modifier} {target}".strip()
            matches.extend(
                (match.start(), identity if quantity == 1 else f"{identity}#{index}")
                for index in range(1, quantity + 1)
            )
    return tuple(matches)


__all__ = ("PendingClothingResolution", "resolve_pending_clothing_sentence")
