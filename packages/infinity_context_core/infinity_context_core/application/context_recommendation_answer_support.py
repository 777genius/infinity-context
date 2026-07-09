"""English recommendation-list answer-support ranking helpers."""

from __future__ import annotations

import re

_RECOMMENDATION_LIST_REASONS = frozenset(
    {
        "book_suggestion_bridge",
        "decomposition_action_role",
        "decomposition_recommendation_source",
        "recommendation_source_bridge",
    }
)
_RECOMMENDATION_OBJECT = (
    r"(?:activities?|animals?|books?|cakes?|desserts?|dramas?|flavou?ring|foods?|games?|"
    r"ingredients?|items?|movies?|novels?|one|pets?|recipes?|series|shows?|songs?|"
    r"stories?|things?|titles?|tools?|trilogy|trip|video\s+games?)"
)
_RECOMMENDATION_VERB = (
    r"(?:recommend(?:ed|ing|s)?|reccomend(?:ed|ing|s)?|reccomended|"
    r"suggest(?:ed|ing|s)?|advis(?:e|ed|ing))"
)
_RECOMMENDATION_NOUN = r"(?:recommendations?|reccomendations?|suggestions?|advice)"

_DIRECT_RECOMMENDATION_OBJECT_RE = re.compile(
    rf"\b{_RECOMMENDATION_VERB}\b(?=.{{0,220}}\b{_RECOMMENDATION_OBJECT}\b)|"
    rf"\b{_RECOMMENDATION_OBJECT}\b(?=.{{0,220}}\b{_RECOMMENDATION_VERB}\b)|"
    rf"\b(?:(?:would\s+)?(?:highly|really|definitely)\s+){_RECOMMENDATION_VERB}\b|"
    r"\b(?:must[-\s]?(?:read|see|try)|great\s+read)\b",
    re.IGNORECASE | re.DOTALL,
)
_IMPLICIT_RECOMMENDATION_OBJECT_RE = re.compile(
    rf"\b(?:this|that|these)\s+(?:[\w'-]+\s+){{0,3}}?{_RECOMMENDATION_OBJECT}\b"
    r"(?=.{0,180}\b(?:amazing|awesome|excellent|favorite|favourite|faves?|good|great|"
    r"love|loved|must[-\s]?(?:read|see|try)|one\s+of\s+my|"
    r"blew\s+me\s+away|blow\s+me\s+away)\b)|"
    r"\b(?:one\s+of\s+my\s+(?:favorites?|favourites?|faves?)|"
    r"must[-\s]?(?:read|see|try)|great\s+read)\b",
    re.IGNORECASE | re.DOTALL,
)
_POSITIVE_CONFIRMATION_RECOMMENDATION_RE = re.compile(
    r"\b(?:that|this)(?:'s|\s+is|\s+sounds(?:\s+like)?)\s+"
    r"(?:an?\s+)?(?:amazing|awesome|excellent|good|great|perfect|solid)\s+one\b"
    r"|"
    r"\b(?:great|good|nice|perfect|solid)\s+(?:choice|idea|pick)\b"
    r"(?=.{0,140}\b(?:let\s+me\s+know|think|try|watch|read|play|use|make)\b)",
    re.IGNORECASE | re.DOTALL,
)
_REQUEST_QUESTION_RECOMMENDATION_RE = re.compile(
    rf"\b(?:any|some)\s+(?:good\s+)?(?:ones?|{_RECOMMENDATION_OBJECT})\b"
    rf"(?=.{{0,120}}\b(?:you(?:'d| would| can| could)?|would\s+you|"
    rf"could\s+you|can\s+you)\s+{_RECOMMENDATION_VERB}\b)|"
    rf"\b(?:would|could|can)\s+you\s+{_RECOMMENDATION_VERB}\b|"
    rf"\b(?:what|which)\s+(?:[\w'-]+\s+){{0,4}}(?:would|could|can)\s+you\s+"
    rf"{_RECOMMENDATION_VERB}\b",
    re.IGNORECASE | re.DOTALL,
)
_ADVICE_LIST_RECOMMENDATION_RE = re.compile(
    r"\b(?:for\s+one|first(?:ly)?|also)\b"
    r"(?=.{0,220}\b(?:you\s+(?:should|can|could)|make\s+sure|"
    r"invest\s+in|look\s+for|try|use|buy|visit|watch|read|play|make|get)\b)"
    r"|"
    r"\b(?:you\s+(?:should|can|could)|make\s+sure|invest\s+in|look\s+for)\b"
    r"(?=.{0,220}\b(?:also|another|for\s+one|first(?:ly)?|"
    r"pointers?|tips?|advice|recommend|suggest)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SETUP_RECOMMENDATION_OBJECT_RE = re.compile(
    r"\bhow\s+about\s+(?:this|that|these)\s+[\w'-]+\b|"
    r"\bshould(?:n't)?\s+i\b"
    r"(?=.{0,160}\b(?:start|get|buy|try|watch|read|play|make|use|visit|"
    r"look\s+for|invest\s+in)\b)",
    re.IGNORECASE | re.DOTALL,
)
_POSSESSIVE_OBJECT_RECOMMENDATION_RE = re.compile(
    rf"\b(?:your|their|his|her|my|our)\s+(?:[\w'-]+\s+){{1,6}}{_RECOMMENDATION_NOUN}\b|"
    rf"\b{_RECOMMENDATION_NOUN}\s+(?:you|they|he|she)\s+gave\b"
    rf"(?=.{{0,120}}\b{_RECOMMENDATION_OBJECT}\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACCEPTED_GENERIC_RECOMMENDATION_RE = re.compile(
    rf"\b(?:followed|took|used|tried|watched|read|played|made|bought|visited|"
    rf"listened)\b(?=.{{0,140}}\b(?:your|their|his|her|my|our)\s+"
    rf"{_RECOMMENDATION_NOUN}\b)|"
    rf"\b{_RECOMMENDATION_NOUN}\b(?=.{{0,140}}\b(?:followed|took|used|tried|"
    r"watched|read|played|made|bought|visited|listened)\b)|"
    rf"\b(?:thanks|thank\s+you)\s+for\s+(?:the\s+|your\s+)?"
    rf"{_RECOMMENDATION_NOUN}\b",
    re.IGNORECASE | re.DOTALL,
)
_REQUEST_ONLY_RECOMMENDATION_RE = re.compile(
    rf"\b(?:any|give|got|have|looking\s+for|need|new|some|want|what|which)\b"
    rf"(?=.{{0,140}}\b{_RECOMMENDATION_NOUN}\b)|"
    r"\bwhat\b(?=.{0,80}\b(?:do|would)\s+you\b)(?=.{0,140}\benjoy\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOMMENDATION_ROLE_QUERY_RE = re.compile(
    rf"\b(?:has|did)\s+(?P<source>[A-Z][A-Za-z'’-]{{1,40}})\b"
    rf"(?=.{{0,100}}\b(?:{_RECOMMENDATION_VERB}|{_RECOMMENDATION_NOUN})\b)"
    r"(?=.{0,140}\b(?:to|for)\s+"
    r"(?P<recipient>[A-Z][A-Za-z'’-]{1,40})\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOMMENDATION_NOMINAL_SOURCE_TO_QUERY_RE = re.compile(
    rf"\b{_RECOMMENDATION_NOUN}\b"
    r"(?=.{0,120}\b(?:has|did|does)\s+"
    r"(?P<source>[A-Z][A-Za-z'’-]{1,40})\b)"
    rf"(?=.{{0,180}}\b(?:give|gave|given|make|made|{_RECOMMENDATION_VERB})\b)"
    r"(?=.{0,220}\b(?:to|for)\s+"
    r"(?P<recipient>[A-Z][A-Za-z'’-]{1,40})\b)",
    re.IGNORECASE | re.DOTALL,
)
_RECOMMENDATION_RECEIVED_FROM_QUERY_RE = re.compile(
    r"\b(?:has|did)\s+(?P<recipient>[A-Z][A-Za-z'’-]{1,40})\b"
    r"(?=.{0,140}\b(?:received|got|taken|used|followed|tried|read|"
    r"watched|played|made|bought|visited|listened)\b)"
    r"(?=.{0,220}\bfrom\s+"
    r"(?P<source>[A-Z][A-Za-z'’-]{1,40})\b)",
    re.IGNORECASE | re.DOTALL,
)
_DIALOGUE_SPEAKER_RE = re.compile(
    r"\bD\d+:\d+\s+(?P<speaker>[A-Z][A-Za-z'’-]{1,40})\s*:",
)
_VISUAL_RECOMMENDATION_OBJECT_CUE_RE = re.compile(
    r"\b(?:image\s+caption|visual\s+query|video\s+caption)\s*:",
    re.IGNORECASE,
)


def is_recommendation_list_reason(query_reason: str) -> bool:
    """Return true when an expansion reason asks for recommendation evidence."""

    return query_reason.replace("-", "_") in _RECOMMENDATION_LIST_REASONS


def recommendation_list_answer_support_rank(
    *,
    text: str,
    query_reason: str,
) -> int:
    """Rank recommendation-list candidates by answer shape.

    Lower is better. The ranking is intentionally about recommendation evidence
    shape, not about any concrete recommended object.
    """

    if not is_recommendation_list_reason(query_reason):
        return 0
    kind = recommendation_list_answer_kind(text=text, query_reason=query_reason)
    if kind in {"possessive_object", "direct"}:
        return 0
    if kind == "implicit" and _VISUAL_RECOMMENDATION_OBJECT_CUE_RE.search(text):
        return 0
    if kind in {"confirmation", "implicit"}:
        return 1
    if kind == "accepted":
        return 2
    if kind == "setup":
        return 2
    if kind == "request":
        return 6
    if kind == "generic":
        return 4
    return 5


def recommendation_list_answer_kind(*, text: str, query_reason: str) -> str:
    """Classify the recommendation evidence shape in a candidate text."""

    if not is_recommendation_list_reason(query_reason):
        return "none"
    if _POSSESSIVE_OBJECT_RECOMMENDATION_RE.search(text) is not None:
        return "possessive_object"
    if _ACCEPTED_GENERIC_RECOMMENDATION_RE.search(text) is not None:
        return "accepted"
    if _REQUEST_QUESTION_RECOMMENDATION_RE.search(text) is not None:
        return "request"
    if _DIRECT_RECOMMENDATION_OBJECT_RE.search(text) is not None:
        return "direct"
    if _ADVICE_LIST_RECOMMENDATION_RE.search(text) is not None:
        return "direct"
    if _POSITIVE_CONFIRMATION_RECOMMENDATION_RE.search(text) is not None:
        return "confirmation"
    if _SETUP_RECOMMENDATION_OBJECT_RE.search(text) is not None:
        return "setup"
    if _IMPLICIT_RECOMMENDATION_OBJECT_RE.search(text) is not None:
        return "implicit"
    if _REQUEST_ONLY_RECOMMENDATION_RE.search(text) is not None:
        return "request"
    if re.search(_RECOMMENDATION_NOUN, text, re.IGNORECASE) is not None:
        return "generic"
    return "none"


def recommendation_role_alignment_rank(
    *,
    text: str,
    query: str,
    query_reason: str,
) -> int:
    """Rank candidate dialogue direction for ``X recommended to Y`` queries."""

    if not is_recommendation_list_reason(query_reason):
        return 0
    role_match = _recommendation_role_query_match(query)
    if role_match is None:
        return 0
    kind = recommendation_list_answer_kind(text=text, query_reason=query_reason)
    if kind in {"none", "request", "generic"}:
        return 3
    source = role_match.group("source").casefold()
    recipient = role_match.group("recipient").casefold()
    speakers = tuple(
        dict.fromkeys(
            match.group("speaker").casefold()
            for match in _DIALOGUE_SPEAKER_RE.finditer(text)
        )
    )
    if not speakers:
        return 2
    answer_speakers = _recommendation_answer_speakers(
        text=text,
        query_reason=query_reason,
    )
    if answer_speakers:
        if source in answer_speakers and kind != "accepted":
            return 0
        if recipient in answer_speakers and kind in {
            "accepted",
            "possessive_object",
            "setup",
        }:
            return 1
        return 5
    if source in speakers and kind != "accepted":
        return 0
    if recipient in speakers and kind in {"accepted", "possessive_object", "setup"}:
        return 1
    return 5


def _recommendation_role_query_match(query: str) -> re.Match[str] | None:
    return (
        _RECOMMENDATION_ROLE_QUERY_RE.search(query)
        or _RECOMMENDATION_NOMINAL_SOURCE_TO_QUERY_RE.search(query)
        or _RECOMMENDATION_RECEIVED_FROM_QUERY_RE.search(query)
    )


def _recommendation_answer_speakers(
    *,
    text: str,
    query_reason: str,
) -> tuple[str, ...]:
    speakers: list[str] = []
    for speaker, turn_text in _dialogue_turn_segments(text):
        kind = recommendation_list_answer_kind(
            text=turn_text,
            query_reason=query_reason,
        )
        if kind in {"none", "request", "generic", "setup"}:
            continue
        if (
            recommendation_list_answer_support_rank(
                text=turn_text,
                query_reason=query_reason,
            )
            > 2
        ):
            continue
        speaker_key = speaker.casefold()
        if speaker_key not in speakers:
            speakers.append(speaker_key)
    return tuple(speakers)


def _dialogue_turn_segments(text: str) -> tuple[tuple[str, str], ...]:
    matches = tuple(_DIALOGUE_SPEAKER_RE.finditer(text))
    segments: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segments.append((match.group("speaker"), text[match.start() : end]))
    return tuple(segments)


def is_concrete_recommendation_answer(*, text: str, query_reason: str) -> bool:
    return is_recommendation_list_reason(query_reason) and recommendation_list_answer_support_rank(
        text=text,
        query_reason=query_reason,
    ) <= 2


def recommendation_query_focus_applies(
    *,
    text: str,
    query: str,
    query_reason: str,
    has_exact_turn: bool,
) -> bool:
    return (
        has_exact_turn
        and is_recommendation_list_reason(query_reason)
        and recommendation_list_answer_support_rank(
            text=text,
            query_reason=query_reason,
        )
        <= 1
        and recommendation_role_alignment_rank(
            text=text,
            query=query,
            query_reason=query_reason,
        )
        <= 1
    )


def recommendation_family_priority(
    *,
    text: str,
    query: str,
    query_reason: str,
) -> int | None:
    if not is_recommendation_list_reason(query_reason):
        return None
    answer_rank = recommendation_list_answer_support_rank(
        text=text,
        query_reason=query_reason,
    )
    role_rank = recommendation_role_alignment_rank(
        text=text,
        query=query,
        query_reason=query_reason,
    )
    if answer_rank <= 1 and role_rank == 0:
        return -5
    if answer_rank <= 2 and role_rank <= 1:
        return -4
    return None


def recommendation_list_broad_turn_slot(
    *,
    text: str,
    query_reason: str,
    source_id: str,
) -> str:
    """Return a stable slot for concrete recommendation-list evidence turns."""

    if not is_recommendation_list_reason(query_reason):
        return ""
    rank = recommendation_list_answer_support_rank(
        text=text,
        query_reason=query_reason,
    )
    if rank <= 2:
        return source_id
    return ""
