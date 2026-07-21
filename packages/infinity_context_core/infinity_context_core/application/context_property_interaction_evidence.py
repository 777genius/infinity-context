"""Conservative property-interaction event evidence for set projections."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_identity_terms import (
    singularize_identity_term,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'/-]{0,39}")
PROPERTY_ENTITY_TERMS = frozenset(
    {"apartment", "bungalow", "condo", "home", "house", "property", "townhouse"}
)
_IDENTITY_SCAFFOLD = frozenset({"a", "an", "another", "my", "new", "our", "that", "the", "this"})
_IDENTITY_BOUNDARIES = frozenset(
    {
        "about",
        "and",
        "at",
        "but",
        "for",
        "from",
        "in",
        "like",
        "liked",
        "love",
        "loved",
        "near",
        "of",
        "on",
        "or",
        "saw",
        "seeing",
        "seen",
        "to",
        "tour",
        "toured",
        "touring",
        "view",
        "viewed",
        "viewing",
        "while",
        "with",
    }
)
_ACTOR_PATTERN = r"(?:my|our|[A-Z][A-Za-z'-]{1,39}(?:\s+[A-Z][A-Za-z'-]{1,39}){0,2}'s)"
_OUTCOME_PATTERN = r"(?:accepted|approved|cancelled|declined|denied|outbid|rejected|withdrawn)"
_POSSESSIVE_OFFER_OUTCOME_RE = re.compile(
    rf"\b(?P<actor>{_ACTOR_PATTERN})\s+(?:purchase\s+)?(?:offer|bid)\b"
    rf"(?P<context>.{{0,160}}?)\b(?:was|got|had\s+been|has\s+been)\s+"
    rf"(?:not\s+)?{_OUTCOME_PATTERN}\b",
    re.IGNORECASE,
)
_ACTIVE_OFFER_OUTCOME_RE = re.compile(
    rf"\b{_OUTCOME_PATTERN}\s+(?P<actor>{_ACTOR_PATTERN})\s+"
    rf"(?:purchase\s+)?(?:offer|bid)\b(?P<context>.{{0,120}})",
    re.IGNORECASE,
)
_OFFER_INSTRUMENT_RE = re.compile(r"\b(?:offer|bid)\b", re.IGNORECASE)
_OBJECT_LINK_RE = re.compile(r"\s+(?:on|for)\s+", re.IGNORECASE)
_NEGATED_VIEWING_RE = re.compile(
    r"\b(?:"
    r"never\s+(?:[A-Za-z'-]+\s+){0,3}(?:saw|seen|toured|viewed)|"
    r"(?:did|do|does|had|has|have|was|were)\s+not\s+(?:ever\s+)?"
    r"(?:see|seen|tour(?:ed)?|view(?:ed)?)|"
    r"(?:didn't|doesn't|don't|hadn't|hasn't|haven't|wasn't|weren't)\s+"
    r"(?:ever\s+)?(?:see|seen|tour(?:ed)?|view(?:ed)?)|"
    r"without\s+(?:ever\s+)?(?:seeing|touring|viewing|having\s+(?:ever\s+)?"
    r"(?:seen|toured|viewed))|"
    r"no\s+(?:in[- ]person\s+)?(?:tour|viewing)(?!\s+appointment)|"
    r"(?:tour|viewing)\s+(?:did\s+not|never)\s+(?:happen|occur|take\s+place)"
    r")\b",
    re.IGNORECASE,
)
_SIGHT_UNSEEN_RE = re.compile(r"\bsight[-\s]+unseen\b", re.IGNORECASE)
_COMPLETED_VIEWING_RE = re.compile(r"\b(?:saw|seen|toured|viewed)\b", re.IGNORECASE)
_VIEWING_PRONOUN_RE = re.compile(
    r"\s+(?:it|that|this|the\s+(?:home|one|property))\b",
    re.IGNORECASE,
)
_VIEWING_REFERENCE_RE = re.compile(
    r"\b(?:see|tour|view)\s+(?:it|that|the\s+(?:home|property))\b",
    re.IGNORECASE,
)
_NON_COMPLETED_VIEWING_PREFIX_RE = re.compile(
    r"\b(?:never|not|without|plan(?:ned|ning)?|schedul(?:e|ed|ing)|"
    r"intend(?:ed|ing)?|would|will|going\s+to)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_ACTOR_RE = re.compile(r"\b(?:I|we)\b", re.IGNORECASE)
_ACTORLESS_VIEWING_PREFIX_RE = re.compile(
    r"^(?:the|there\s+(?:was|were|had\s+been))?$",
    re.IGNORECASE,
)
_PLANNED_VIEW_AFTER_OFFER_RE = re.compile(
    r"(?:"
    r"\b(?:plan(?:ned|ning)?|schedul(?:e|ed|ing)|intend(?:ed|ing)?|would|will|"
    r"(?:am|are|is|was|were)\s+going\s+to)\b.{0,64}?"
    r"\b(?:see|tour|view)\b.{0,48}?\b(?:only\s+)?after\b.{0,40}?\b(?:offer|bid)\b|"
    r"\b(?:tour|viewing)\b.{0,48}?\b(?:planned|scheduled|intended)\b.{0,48}?"
    r"\b(?:only\s+)?after\b.{0,40}?\b(?:offer|bid)\b|"
    r"\bafter\b.{0,40}?\b(?:offer|bid)\b.{0,64}?"
    r"\b(?:plan(?:ned|ning)?|schedul(?:e|ed|ing)|intend(?:ed|ing)?|would|will|"
    r"(?:am|are|is|was|were)\s+going\s+to)\b.{0,48}?\b(?:see|tour|view)\b"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PropertyInteractionEventEvidence:
    """Subject-checked property identities backed by a realized offer event."""

    identities: tuple[str, ...] = ()
    matched_event_count: int = 0
    subject_conflict: bool = False
    viewing_conflict: bool = False
    excluded_identities: tuple[str, ...] = ()
    completed_identities: tuple[str, ...] = ()

    @property
    def present(self) -> bool:
        return bool(self.identities and self.matched_event_count)


@dataclass(frozen=True)
class _PropertyMention:
    identity: str
    start: int
    end: int


def project_property_interaction_event(
    *,
    sentence: str,
    target_terms: tuple[str, ...],
    requested_action_terms: tuple[str, ...],
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> PropertyInteractionEventEvidence:
    """Keep realized property offers as evidence for a property-view set query.

    The projection does not convert rejection or denial into a successful outcome. It
    preserves the original user sentence for downstream reasoning and only identifies
    the property participating in the event.
    """

    normalized_targets = {singularize_identity_term(term.casefold()) for term in target_terms}
    if not normalized_targets.intersection(PROPERTY_ENTITY_TERMS) or "view" not in {
        term.casefold() for term in requested_action_terms
    }:
        return PropertyInteractionEventEvidence()
    mentions = _property_mentions(sentence)
    if not mentions:
        return PropertyInteractionEventEvidence()
    events = tuple(
        (match, event_mentions)
        for match in _offer_outcome_matches(sentence)
        if (event_mentions := _event_property_mentions(sentence, match=match, mentions=mentions))
    )
    requested_events = tuple(
        (match, event_mentions)
        for match, event_mentions in events
        if _actor_matches_request(
            match.group("actor"),
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        )
    )
    event_linked_identities = frozenset(
        mention.identity
        for _match, event_mentions in requested_events
        for mention in event_mentions
    )
    unique_event_identity = (
        next(iter(event_linked_identities)) if len(event_linked_identities) == 1 else None
    )
    completed_by_event = {
        (match.start(), match.end()): _completed_prior_viewing_identities(
            sentence,
            match=match,
            event_mentions=event_mentions,
            mentions=mentions,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        )
        for match, event_mentions in requested_events
    }
    completed_identities = frozenset(
        identity for identities in completed_by_event.values() for identity in identities
    )
    excluded_identities = set(
        _explicitly_unseen_identities(
            sentence,
            mentions=mentions,
            completed_identities=completed_identities,
            unique_event_identity=unique_event_identity,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        )
    )
    identities: list[str] = []
    seen: set[str] = set()
    matched_event_count = 0
    subject_conflict = False
    for match, event_mentions in events:
        if not _actor_matches_request(
            match.group("actor"),
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        ):
            subject_conflict = True
            continue
        event_completed_identities = completed_by_event.get(
            (match.start(), match.end()), frozenset()
        )
        event_conflicts = tuple(
            mention
            for mention in event_mentions
            if mention.identity not in event_completed_identities
            and (
                mention.identity in excluded_identities
                or _unscoped_conflict_applies_to_event(
                    sentence,
                    match=match,
                    event_mentions=event_mentions,
                    mentions=mentions,
                    subject_is_first_person=subject_is_first_person,
                    subject_terms=subject_terms,
                )
                or _temporal_inversion_applies_to_event(
                    sentence,
                    match=match,
                    event_mentions=event_mentions,
                    mentions=mentions,
                    unique_event_identity=unique_event_identity,
                    subject_is_first_person=subject_is_first_person,
                    subject_terms=subject_terms,
                )
            )
        )
        if event_conflicts:
            excluded_identities.update(mention.identity for mention in event_conflicts)
            continue
        matched_event_count += 1
        for mention in event_mentions:
            if mention.identity in seen:
                continue
            seen.add(mention.identity)
            identities.append(mention.identity)
    return PropertyInteractionEventEvidence(
        identities=tuple(identities),
        matched_event_count=matched_event_count,
        subject_conflict=subject_conflict and not identities,
        viewing_conflict=bool(excluded_identities),
        excluded_identities=tuple(sorted(excluded_identities)),
        completed_identities=tuple(sorted(completed_identities)),
    )


def _completed_prior_viewing_identities(
    sentence: str,
    *,
    match: re.Match[str],
    event_mentions: tuple[_PropertyMention, ...],
    mentions: tuple[_PropertyMention, ...],
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> frozenset[str]:
    identities: set[str] = set()
    event_identities = {mention.identity for mention in event_mentions}
    for viewing_match in _COMPLETED_VIEWING_RE.finditer(sentence):
        prefix = sentence[max(0, viewing_match.start() - 40) : viewing_match.start()]
        if _NON_COMPLETED_VIEWING_PREFIX_RE.search(prefix):
            continue
        if not _viewing_statement_matches_request(
            sentence,
            match=viewing_match,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        ):
            continue
        following = _direct_following_property_mention(
            sentence,
            match=viewing_match,
            mentions=mentions,
        )
        if following is None or following.identity not in event_identities:
            continue
        if following.end > match.start() or _viewing_occurs_after_event(
            sentence,
            event_match=match,
            viewing_match=viewing_match,
            reference_end=following.end,
        ):
            continue
        identities.add(following.identity)
    return frozenset(identities)


def _explicitly_unseen_identities(
    sentence: str,
    *,
    mentions: tuple[_PropertyMention, ...],
    completed_identities: frozenset[str],
    unique_event_identity: str | None,
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> tuple[str, ...]:
    identities: set[str] = set()
    for match in _NEGATED_VIEWING_RE.finditer(sentence):
        if not _viewing_statement_matches_request(
            sentence,
            match=match,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        ):
            continue
        following = _following_property_mention(sentence, match=match, mentions=mentions)
        if following is not None:
            identities.add(following.identity)
            continue
        if unique_event_identity is not None and _viewing_pronoun_reference(sentence, match=match):
            identities.add(unique_event_identity)
    for match in _SIGHT_UNSEEN_RE.finditer(sentence):
        nearby = _nearest_property_mention(match=match, mentions=mentions)
        if nearby is not None:
            identities.add(nearby.identity)
    for match in _PLANNED_VIEW_AFTER_OFFER_RE.finditer(sentence):
        if not _viewing_statement_matches_request(
            sentence,
            match=match,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        ):
            continue
        nearby = _mention_within_span(match=match, mentions=mentions)
        if nearby is not None and nearby.identity not in completed_identities:
            identities.add(nearby.identity)
    return tuple(sorted(identities))


def _viewing_statement_matches_request(
    sentence: str,
    *,
    match: re.Match[str],
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> bool:
    prefix = _local_actor_prefix(sentence, action_start=match.start())
    if subject_is_first_person:
        if _FIRST_PERSON_ACTOR_RE.search(prefix):
            return True
    else:
        requested = {term.casefold() for term in subject_terms}
        prefix_terms = {
            token.group(0).casefold().removesuffix("'s").strip("'/-")
            for token in _TOKEN_RE.finditer(prefix)
        }
        if requested and requested.issubset(prefix_terms):
            return True
    surface = match.group(0).casefold()
    actorless = surface.startswith(("no ", "tour ", "viewing ")) or (
        surface.startswith("the ") and "scheduled" in surface
    )
    return actorless and _ACTORLESS_VIEWING_PREFIX_RE.fullmatch(prefix.strip()) is not None


def _local_actor_prefix(sentence: str, *, action_start: int) -> str:
    bounded_start = max(0, action_start - 80)
    local = sentence[bounded_start:action_start]
    boundary = max(
        local.rfind(","),
        local.rfind(";"),
        local.casefold().rfind(" and "),
        local.casefold().rfind(" but "),
        local.casefold().rfind(" while "),
    )
    return local[boundary + 1 :]


def _following_property_mention(
    sentence: str,
    *,
    match: re.Match[str],
    mentions: tuple[_PropertyMention, ...],
) -> _PropertyMention | None:
    candidates = tuple(
        mention
        for mention in mentions
        if match.end() <= mention.start and mention.start - match.end() <= 80
    )
    if not candidates:
        return None
    nearest = min(candidates, key=lambda mention: mention.start)
    bridge = sentence[match.end() : nearest.start]
    if re.search(r"[,;.!?]|\b(?:and|but|while)\b", bridge, re.IGNORECASE):
        return None
    return nearest


def _direct_following_property_mention(
    sentence: str,
    *,
    match: re.Match[str],
    mentions: tuple[_PropertyMention, ...],
) -> _PropertyMention | None:
    following = _following_property_mention(sentence, match=match, mentions=mentions)
    if following is None:
        return None
    bridge = sentence[match.end() : following.start]
    if bridge.strip():
        return None
    return following


def _viewing_pronoun_reference(sentence: str, *, match: re.Match[str]) -> bool:
    return _VIEWING_PRONOUN_RE.match(sentence, match.end()) is not None


def _nearest_property_mention(
    *,
    match: re.Match[str],
    mentions: tuple[_PropertyMention, ...],
) -> _PropertyMention | None:
    candidates = tuple(
        mention
        for mention in mentions
        if min(abs(mention.end - match.start()), abs(mention.start - match.end())) <= 100
    )
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda mention: min(
            abs(mention.end - match.start()),
            abs(mention.start - match.end()),
        ),
    )


def _mention_within_span(
    *,
    match: re.Match[str],
    mentions: tuple[_PropertyMention, ...],
) -> _PropertyMention | None:
    candidates = tuple(
        mention
        for mention in mentions
        if match.start() <= mention.start and mention.end <= match.end()
    )
    if len({mention.identity for mention in candidates}) != 1:
        return None
    return candidates[0]


def _temporal_inversion_applies_to_event(
    sentence: str,
    *,
    match: re.Match[str],
    event_mentions: tuple[_PropertyMention, ...],
    mentions: tuple[_PropertyMention, ...],
    unique_event_identity: str | None,
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> bool:
    event_identities = {mention.identity for mention in event_mentions}
    for viewing_match in _COMPLETED_VIEWING_RE.finditer(sentence):
        prefix = sentence[max(0, viewing_match.start() - 40) : viewing_match.start()]
        if _NON_COMPLETED_VIEWING_PREFIX_RE.search(prefix):
            continue
        if not _viewing_statement_matches_request(
            sentence,
            match=viewing_match,
            subject_is_first_person=subject_is_first_person,
            subject_terms=subject_terms,
        ):
            continue
        following = _direct_following_property_mention(
            sentence,
            match=viewing_match,
            mentions=mentions,
        )
        if following is not None:
            viewing_identity = following.identity
            reference_end = following.end
        elif unique_event_identity is not None and (
            pronoun := _VIEWING_PRONOUN_RE.match(sentence, viewing_match.end())
        ):
            viewing_identity = unique_event_identity
            reference_end = pronoun.end()
        else:
            continue
        if viewing_identity not in event_identities:
            continue
        if _viewing_occurs_after_event(
            sentence,
            event_match=match,
            viewing_match=viewing_match,
            reference_end=reference_end,
        ):
            return True
    return False


def _viewing_occurs_after_event(
    sentence: str,
    *,
    event_match: re.Match[str],
    viewing_match: re.Match[str],
    reference_end: int,
) -> bool:
    if event_match.end() <= viewing_match.start():
        bridge = sentence[event_match.end() : viewing_match.start()]
        if _OFFER_INSTRUMENT_RE.search(bridge):
            return False
        if re.search(r"\b(?:before|then|later)\b", bridge, re.IGNORECASE):
            return True
        event_prefix = sentence[max(0, event_match.start() - 32) : event_match.start()]
        return re.search(r"(?:^|[,;])\s*after\s*$", event_prefix, re.IGNORECASE) is not None
    if reference_end > event_match.start():
        return False
    relation = sentence[reference_end : event_match.start()]
    if _OFFER_INSTRUMENT_RE.search(relation):
        return False
    if re.fullmatch(r"\s+(?:only\s+)?after\s*", relation, re.IGNORECASE):
        return True
    viewing_prefix = sentence[max(0, viewing_match.start() - 48) : viewing_match.start()]
    return (
        re.search(
            r"(?:^|[,;])\s*before\s+(?:I|we|[A-Z][A-Za-z'-]{1,39})\s*$",
            viewing_prefix,
            re.IGNORECASE,
        )
        is not None
    )


def _unscoped_conflict_applies_to_event(
    sentence: str,
    *,
    match: re.Match[str],
    event_mentions: tuple[_PropertyMention, ...],
    mentions: tuple[_PropertyMention, ...],
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> bool:
    if _SIGHT_UNSEEN_RE.search(sentence, max(0, match.start() - 120), match.end() + 120):
        return len({mention.identity for mention in mentions}) == 1
    planned = _PLANNED_VIEW_AFTER_OFFER_RE.search(sentence)
    if planned is None:
        return False
    if not _viewing_statement_matches_request(
        sentence,
        match=planned,
        subject_is_first_person=subject_is_first_person,
        subject_terms=subject_terms,
    ):
        return False
    if len({mention.identity for mention in event_mentions}) != 1:
        return False
    local = sentence[planned.start() : planned.end()]
    return (
        bool(_VIEWING_REFERENCE_RE.search(local))
        or len({mention.identity for mention in mentions}) == 1
    )


def _offer_outcome_matches(sentence: str) -> tuple[re.Match[str], ...]:
    matches = [
        *_POSSESSIVE_OFFER_OUTCOME_RE.finditer(sentence),
        *_ACTIVE_OFFER_OUTCOME_RE.finditer(sentence),
    ]
    return tuple(sorted(matches, key=lambda match: (match.start(), match.end())))


def _property_mentions(sentence: str) -> tuple[_PropertyMention, ...]:
    tokens = tuple(_TOKEN_RE.finditer(sentence))
    mentions: list[_PropertyMention] = []
    for index, token in enumerate(tokens):
        term = singularize_identity_term(token.group(0).casefold().strip("'/-"))
        if term not in PROPERTY_ENTITY_TERMS:
            continue
        start_index = max(0, index - 5)
        for prior_index in range(index - 1, start_index - 1, -1):
            prior = tokens[prior_index].group(0).casefold().strip("'/-")
            if prior in _IDENTITY_BOUNDARIES:
                start_index = prior_index + 1
                break
        identity_terms = [
            singularize_identity_term(match.group(0).casefold().strip("'/-"))
            for match in tokens[start_index : index + 1]
        ]
        identity = " ".join(
            value for value in identity_terms if value and value not in _IDENTITY_SCAFFOLD
        )
        if identity:
            mentions.append(
                _PropertyMention(
                    identity=identity,
                    start=tokens[start_index].start(),
                    end=token.end(),
                )
            )
    return tuple(mentions)


def _event_property_mentions(
    sentence: str,
    *,
    match: re.Match[str],
    mentions: tuple[_PropertyMention, ...],
) -> tuple[_PropertyMention, ...]:
    instrument = _OFFER_INSTRUMENT_RE.search(sentence, match.start(), match.end())
    if instrument is not None:
        link = _OBJECT_LINK_RE.match(sentence, instrument.end())
        if link is not None:
            explicit = tuple(
                mention
                for mention in mentions
                if link.end() <= mention.start and mention.start - link.end() <= 100
            )
            if explicit:
                selected = explicit[0]
                if selected.identity != "property":
                    return (selected,)
                antecedents = tuple(
                    mention
                    for mention in mentions
                    if mention.end <= match.start() and mention.identity != "property"
                )
                unique = {mention.identity: mention for mention in antecedents}
                if len(unique) == 1:
                    return tuple(unique.values())
                return ()
    antecedents = tuple(mention for mention in mentions if mention.end <= match.start())
    unique = {mention.identity: mention for mention in antecedents}
    if len(unique) != 1:
        return ()
    return tuple(unique.values())


def _actor_matches_request(
    actor: str,
    *,
    subject_is_first_person: bool,
    subject_terms: tuple[str, ...],
) -> bool:
    normalized = actor.casefold().strip()
    if subject_is_first_person:
        return normalized in {"my", "our"}
    actor_terms = {
        match.group(0).casefold().removesuffix("'s").strip("'/-")
        for match in _TOKEN_RE.finditer(actor)
    }
    requested = {term.casefold() for term in subject_terms}
    return bool(requested and requested.issubset(actor_terms))
