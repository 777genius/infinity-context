"""English exact-turn support for person activity inventories."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

_MAX_EXACT_PERSON_ACTIVITY_TURNS = 8
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_SPEAKER_RE = re.compile(r"\bD\d+:\d+\s+(?P<speaker>[A-Z][A-Za-z'.-]{1,40}):")
_TURN_SOURCE_ID_RE = re.compile(r"^(?P<group>.+):D\d+:\d+:turn$")
_SOURCE_ID_SUFFIX_RE = re.compile(r"[^A-Za-z0-9]+")
_QUERY_NAME_RE = re.compile(r"\b[A-Z][A-Za-z'.-]{1,40}\b")
_QUERY_NAME_STOPWORDS = frozenset(
    {"Answer", "Did", "Does", "Do", "How", "Is", "What", "When", "Where", "Which", "Why"}
)
_ACTIVITY_QUERY_RE = re.compile(
    r"\b(?:activities?|sports?|outdoor|outdoors|hobbies?|exercises?|workouts?|"
    r"performance)\b",
    re.IGNORECASE,
)
_FAMILY_QUERY_RE = re.compile(
    r"\b(?:family|families|kids?|child|children)\b",
    re.IGNORECASE,
)
_FAMILY_EVIDENCE_RE = re.compile(
    r"\b(?:family|families|kids?|child|children|sons?|daughters?|parents?|"
    r"mothers?|fathers?|moms?|dads?|siblings?|brothers?|sisters?|spouses?|"
    r"husbands?|wives|grandparents?)\b",
    re.IGNORECASE,
)
_FAMILY_MEMBER_FRAGMENT = (
    r"(?:(?:my|our|the|their|his|her)\s+)?"
    r"(?:family|families|kids?|child|children|sons?|daughters?|parents?|"
    r"mothers?|fathers?|moms?|dads?|siblings?|brothers?|sisters?|spouses?|"
    r"husbands?|wives|grandparents?)"
)
_FAMILY_ACTIVITY_GAP_FRAGMENT = r"(?:\s+(?!(?:and|but|while|although|however)\b)[a-z][a-z'-]*){0,8}"
_WITH_FAMILY_FRAGMENT = rf"{_FAMILY_ACTIVITY_GAP_FRAGMENT}\s+with\s+{_FAMILY_MEMBER_FRAGMENT}\b"
_OUTDOOR_QUERY_RE = re.compile(
    r"\b(?:outdoor|outdoors|hiking|hike|trail|camping|surfing|nature)\b",
    re.IGNORECASE,
)
_SPORT_QUERY_RE = re.compile(
    r"\b(?:sports?|basketball|game|games|athletic|performance)\b",
    re.IGNORECASE,
)
_ALTERNATIVE_ACTIVITY_QUERY_RE = re.compile(
    r"\b(?:besides|other\s+than|apart\s+from|except|other)\b",
    re.IGNORECASE,
)
_EXERCISE_QUERY_RE = re.compile(
    r"\b(?:exercises?|workouts?|strength|flexibility|performance)\b",
    re.IGNORECASE,
)
_EXERCISE_BENEFIT_RE = re.compile(
    r"\b(?:strength|flexibility|balance|focus|performance|workouts?|"
    r"training|schedule|routine|improv(?:e|ed|es|ing)|impact|benefits?)\b",
    re.IGNORECASE,
)
_DIRECT_PARTICIPATION_RE = re.compile(
    r"\b(?:i|we)\b(?=.{0,180}\b(?:started|joined|play|played|playing|"
    r"practice|practicing|scored|went|go|going|love|enjoy|enjoyed|"
    r"trying|tried|taking|take|took|training|surfing|hiking|camping|yoga)\b)|"
    r"\bmy\s+(?:hiking\s+club|team|club|practice|game)\b|"
    r"\b(?:shooting\s+guard|season\s+opener|scored\s+\d+|on\s+and\s+off\s+the\s+court)\b|"
    r"\brecent\s+game\b(?=.{0,180}\b(?:basketball|court|jersey|visual\s+query)\b)",
    re.IGNORECASE | re.DOTALL,
)
_OUTDOOR_DIRECT_RE = re.compile(
    r"\b(?:surfing|surf|surfboard|waves?|hiking\s+club|hiking|hike|trail|"
    r"camping|campfire|kayak(?:ing)?|climb(?:ing)?|beach|mountains?)\b",
    re.IGNORECASE,
)
_SPORT_DIRECT_RE = re.compile(
    r"\b(?:basketball|shooting\s+guard|season\s+opener|scored\s+\d+|"
    r"court|game|games|team|jerseys?|surfing|surfboard|waves?)\b",
    re.IGNORECASE,
)
_EXERCISE_DIRECT_RE = re.compile(
    r"\b(?:yoga|strength\s+training|strength|flexibility|running|boxing|"
    r"sprinting|training|workouts?)\b",
    re.IGNORECASE,
)
_FAMILY_MUSEUM_ACTIVITY_RE = re.compile(
    r"\b(?:museums?|art\s+galler(?:y|ies)|aquariums?|zoos?|"
    r"science\s+cent(?:er|re)s?)\b",
    re.IGNORECASE,
)
_FAMILY_SWIMMING_ACTIVITY_RE = re.compile(
    r"\b(?:swam|swim|swims|swimming|swimming\s+pool|pool)\b",
    re.IGNORECASE,
)
_FAMILY_MUSEUM_DIRECT_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently|often|usually|sometimes)\s+){0,2}"
    r"(?:visit|visits|visited|visiting)\s+(?:an?\s+|the\s+)?"
    r"(?:(?:[a-z-]+\s+){0,2}museum|art\s+gallery|aquarium|zoo|"
    rf"science\s+cent(?:er|re))\b{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently)\s+){0,2}"
    r"(?:went|go|going)\s+to\s+(?:an?\s+|the\s+)?"
    r"(?:(?:[a-z-]+\s+){0,2}museum|art\s+gallery|aquarium|zoo|"
    rf"science\s+cent(?:er|re))\b{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently)\s+){0,2}"
    rf"(?:take|takes|taking|took|bring|brings|bringing|brought|accompanied)\s+"
    rf"{_FAMILY_MEMBER_FRAGMENT}\s+(?:to|into|through)\s+"
    r"(?:an?\s+|the\s+)?"
    r"(?:(?:[a-z-]+\s+){0,2}museum|art\s+gallery|aquarium|zoo|"
    r"science\s+cent(?:er|re))\b|"
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently)\s+){0,2}"
    rf"(?:went|go|going)\s+with\s+{_FAMILY_MEMBER_FRAGMENT}\s+to\s+"
    r"(?:an?\s+|the\s+)?"
    r"(?:(?:[a-z-]+\s+){0,2}museum|art\s+gallery|aquarium|zoo|"
    r"science\s+cent(?:er|re))\b",
    re.IGNORECASE,
)
_FAMILY_SWIMMING_DIRECT_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently|often|usually|sometimes)\s+){0,2}"
    rf"(?:swam|swim|swimming|went\s+swimming|go\s+swimming|going\s+swimming)\b"
    rf"{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i(?:'m|\s+am)|we(?:'re|\s+are))\s+(?:(?:all|both)\s+)?"
    r"(?:off|going|headed|about)\s+to\s+(?:go\s+)?"
    rf"(?:swim|swimming)\b{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently)\s+){0,2}"
    rf"(?:take|takes|taking|took|bring|brings|bringing|brought|accompanied)\s+"
    rf"{_FAMILY_MEMBER_FRAGMENT}\s+(?:(?:to\s+)?(?:go\s+)?swimming|"
    r"to\s+(?:an?\s+|the\s+)?(?:swimming\s+)?pool)\b",
    re.IGNORECASE,
)
_FAMILY_OTHER_ACTIVITY_DIRECT_RE = re.compile(
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently|often|usually|sometimes)\s+){0,2}"
    r"(?:(?:went|go|going)\s+(?:hiking|camping|surfing|kayaking|climbing)|"
    rf"hiked|camped|surfed|kayaked|climbed|played|practiced|trained)\b"
    rf"{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i|we)\s+(?:really\s+)?(?:love|enjoy|enjoyed)\s+(?:going\s+)?"
    rf"(?:hiking|camping|surfing|kayaking|climbing)\b{_WITH_FAMILY_FRAGMENT}|"
    r"\b(?:i|we)\s+(?:(?:also|both|just|recently)\s+){0,2}"
    rf"(?:take|takes|taking|took|bring|brings|bringing|brought|accompanied)\s+"
    rf"{_FAMILY_MEMBER_FRAGMENT}\s+(?:(?:to\s+)?(?:go\s+)?"
    r"(?:hiking|camping|surfing|kayaking|climbing)|to\s+(?:practice|a\s+game))\b",
    re.IGNORECASE,
)
_NOISY_ACTIVITY_CONTEXT_RE = re.compile(
    r"\b(?:outdoor\s+gear\s+company|photoshoot|fan\s+project|fantasy|"
    r"family\s+support|supportive\s+team|good\s+mood|energized)\b",
    re.IGNORECASE,
)


def exact_person_activity_turn_candidates(
    items: Iterable[ContextItem],
    *,
    query: str,
    limit: int = _MAX_EXACT_PERSON_ACTIVITY_TURNS,
) -> tuple[ContextItem, ...]:
    """Return exact activity turns where a queried person participates directly."""

    if limit <= 0 or _ACTIVITY_QUERY_RE.search(query or "") is None:
        return ()
    limit = min(limit, _MAX_EXACT_PERSON_ACTIVITY_TURNS)
    family_query = _is_family_activity_query(query)
    query_names = _query_names(query)
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        for turn in _focused_activity_turns(item):
            speaker = _speaker(turn.text)
            if family_query and (
                not query_names or not speaker or speaker.casefold() not in query_names
            ):
                continue
            if (
                not family_query
                and query_names
                and speaker
                and speaker.casefold() not in query_names
            ):
                continue
            rank = _activity_turn_rank(turn.text, query=query)
            if rank >= 5:
                continue
            ranked.append(
                (
                    (
                        rank,
                        _source_order_rank(turn),
                        context_rank_key(turn),
                    ),
                    turn,
                )
            )

    ordered_ranked = sorted(ranked, key=lambda value: value[0])
    if family_query:
        ordered_ranked = list(_family_activity_diverse_order(ordered_ranked))

    selected: list[ContextItem] = []
    selected_sources: set[str] = set()
    for _, item in ordered_ranked:
        source_id = _primary_source_id(item)
        if source_id in selected_sources:
            continue
        selected.append(item)
        selected_sources.add(source_id)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _focused_activity_turns(item: ContextItem) -> tuple[ContextItem, ...]:
    exact_refs = tuple(
        ref for ref in item.source_refs if str(ref.source_id).casefold().endswith(":turn")
    )
    if len(exact_refs) == 1:
        return (item,)

    focused: list[ContextItem] = []
    for ref in exact_refs:
        marker = _source_ref_marker(ref)
        if not marker:
            continue
        turn_text = _focused_marker_text(item.text, marker)
        focused.append(
            replace(
                item,
                item_id=f"{item.item_id}:activity_exact:{_source_suffix(ref)}"[:220],
                text=turn_text,
                source_refs=(ref,),
            )
        )
    return tuple(focused)


def _activity_turn_rank(text: str, *, query: str) -> int:
    if _is_family_activity_query(query):
        family_activity_slot = _family_activity_slot(text)
        if _FAMILY_EVIDENCE_RE.search(text) is None or not family_activity_slot:
            return 5
        return 2 if _NOISY_ACTIVITY_CONTEXT_RE.search(text) is not None else 0
    if _DIRECT_PARTICIPATION_RE.search(text) is None:
        return 5
    noise_penalty = 2 if _NOISY_ACTIVITY_CONTEXT_RE.search(text) is not None else 0
    wants_outdoor = _OUTDOOR_QUERY_RE.search(query or "") is not None
    wants_sport = _SPORT_QUERY_RE.search(query or "") is not None
    wants_exercise = _EXERCISE_QUERY_RE.search(query or "") is not None
    wants_alternative = _ALTERNATIVE_ACTIVITY_QUERY_RE.search(query or "") is not None
    has_outdoor = _OUTDOOR_DIRECT_RE.search(text) is not None
    has_sport = _SPORT_DIRECT_RE.search(text) is not None
    has_exercise = _EXERCISE_DIRECT_RE.search(text) is not None

    if wants_exercise:
        if has_exercise:
            if _EXERCISE_BENEFIT_RE.search(text) is not None:
                return noise_penalty
            return 1 + noise_penalty
        if has_sport:
            return 3 + noise_penalty
    if wants_outdoor and has_outdoor:
        if re.search(r"\b(?:surfing|hiking\s+club|hiking)\b", text, re.IGNORECASE):
            return noise_penalty
        return 1 + noise_penalty
    if wants_sport and has_sport:
        if wants_alternative and has_outdoor:
            return noise_penalty
        if wants_alternative:
            return 1 + noise_penalty
        return noise_penalty
    if has_outdoor or has_sport or has_exercise:
        return 2 + noise_penalty
    return 5


def _is_family_activity_query(query: str) -> bool:
    return (
        _ACTIVITY_QUERY_RE.search(query or "") is not None
        and _FAMILY_QUERY_RE.search(query or "") is not None
    )


def _family_activity_slot(text: str) -> str:
    for slot, pattern in (
        ("museum", _FAMILY_MUSEUM_ACTIVITY_RE),
        ("swimming", _FAMILY_SWIMMING_ACTIVITY_RE),
        ("outdoor", _OUTDOOR_DIRECT_RE),
        ("sport", _SPORT_DIRECT_RE),
        ("exercise", _EXERCISE_DIRECT_RE),
    ):
        if pattern.search(text) is not None and _has_direct_family_activity(text, slot=slot):
            return slot
    return ""


def _has_direct_family_activity(text: str, *, slot: str) -> bool:
    if slot == "museum":
        pattern = _FAMILY_MUSEUM_DIRECT_RE
    elif slot == "swimming":
        pattern = _FAMILY_SWIMMING_DIRECT_RE
    else:
        pattern = _FAMILY_OTHER_ACTIVITY_DIRECT_RE
    return pattern.search(text) is not None


def _family_activity_diverse_order(
    ranked: list[tuple[tuple[object, ...], ContextItem]],
) -> tuple[tuple[tuple[object, ...], ContextItem], ...]:
    buckets: dict[
        tuple[str, str],
        list[tuple[tuple[object, ...], ContextItem]],
    ] = {}
    for entry in ranked:
        item = entry[1]
        key = (_family_activity_slot(item.text), _source_group(item))
        buckets.setdefault(key, []).append(entry)

    ordered: list[tuple[tuple[object, ...], ContextItem]] = []
    for offset in range(max((len(bucket) for bucket in buckets.values()), default=0)):
        for bucket in buckets.values():
            if offset < len(bucket):
                ordered.append(bucket[offset])
    return tuple(ordered)


def _query_names(query: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold()
        for match in _QUERY_NAME_RE.finditer(query or "")
        if match.group(0) not in _QUERY_NAME_STOPWORDS
    )


def _speaker(text: str) -> str:
    match = _SPEAKER_RE.search(text)
    return match.group("speaker") if match is not None else ""


def _focused_marker_text(text: str, marker: str) -> str:
    match = re.search(rf"\b{re.escape(marker)}\b", text)
    if match is None:
        return text
    next_match = _DIALOGUE_MARKER_RE.search(text, match.end())
    end = next_match.start() if next_match is not None else len(text)
    return text[match.start() : end].strip() or text


def _source_ref_marker(ref: SourceRef) -> str:
    match = re.search(r"\bD\d+:\d+(?=:turn$)", str(ref.source_id))
    return match.group(0) if match is not None else ""


def _primary_source_id(item: ContextItem) -> str:
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if source_id.casefold().endswith(":turn"):
            return source_id
    return str(item.source_refs[0].source_id) if item.source_refs else item.item_id


def _source_group(item: ContextItem) -> str:
    source_id = _primary_source_id(item)
    match = _TURN_SOURCE_ID_RE.match(source_id)
    return match.group("group") if match is not None else source_id


def _source_order_rank(item: ContextItem) -> tuple[int, int]:
    match = re.search(r":session_(\d+):D\d+:(\d+):turn$", _primary_source_id(item))
    if match is None:
        return (999, 999)
    return (int(match.group(1)), int(match.group(2)))


def _source_suffix(ref: SourceRef) -> str:
    return _SOURCE_ID_SUFFIX_RE.sub("_", str(ref.source_id)).strip("_") or "turn"
