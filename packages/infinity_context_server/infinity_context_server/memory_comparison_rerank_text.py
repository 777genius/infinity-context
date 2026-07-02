"""Lexical and memory-surface helpers for benchmark reranking."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_models import RetrievedMemory

_WORD_RE = re.compile(r"\d+(?:st|nd|rd|th)?|[a-zA-Z][a-zA-Z0-9+'-]*")
_TIME_SURFACE_RE = re.compile(
    r"\b(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|(?:19|20)\d{2}|"
    r"today|yesterday|tomorrow|"
    r"(?:last|next|previous|this)\s+(?:night|week|weekend|month|year|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"\d+\s+weekends?\s+ago|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)
_SEQUENCE_SURFACE_RE = re.compile(r"\b(?:session[_\s-]?\d+|D\d+:\d+|date:)\b")
_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_DIRECT_TURN_SPEAKER_RE = re.compile(
    r"\bD\d+:\d+\s+[A-Z][a-zA-Z0-9_-]{1,40}\s*:"
)
_BROAD_SUMMARY_SURFACE_RE = re.compile(
    r"\b(?:observations|events date|related turns)\b",
    re.IGNORECASE,
)
_DURATION_SURFACE_RE = re.compile(
    r"\b(?:\d+\s*)?(?:days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_COMPACT_TEMPORAL_RELATION_TERMS = frozenset(
    {
        "ago",
        "day",
        "month",
        "today",
        "tomorrow",
        "week",
        "weekend",
        "year",
        "yesterday",
    }
)
_VISUAL_EVIDENCE_RE = re.compile(
    r"\b(?:sharing\s+(?:image|photo|picture)|(?:image|photo|picture)\s+shows|"
    r"visual query)\b"
    r"|\b(?:send|sent|share|shared|show|showed|showing)\b"
    r".{0,80}\b(?:image|photo|picture|pic|painting)\b",
    re.IGNORECASE,
)
_PREFERENCE_EVIDENCE_RE = re.compile(
    r"\b(?:love|loved|like|liked|enjoy|enjoyed|favorite|favourite|"
    r"interested|prefer|preferred|"
    r"outdoors|camping|national park|self-care|relax|refresh|refreshes|"
    r"refreshing)\b",
    re.IGNORECASE,
)
QUERY_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "any",
    "are",
    "before",
    "being",
    "between",
    "did",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "him",
    "his",
    "how",
    "into",
    "its",
    "last",
    "later",
    "many",
    "more",
    "much",
    "next",
    "not",
    "off",
    "out",
    "over",
    "own",
    "she",
    "should",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "through",
    "time",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "with",
    "would",
    "you",
    "your",
}
QUERY_TOKEN_ALIASES = {
    "agency": ("agencies",),
    "amaz": ("amazing",),
    "advis": ("advise",),
    "awarenes": ("awareness",),
    "carv": ("carve",),
    "camp": ("camping",),
    "clas": ("class",),
    "counsel": ("counseling", "counselor"),
    "dat": ("dating",),
    "decid": ("decide",),
    "destres": ("destress",),
    "educaton": ("education",),
    "enrol": ("enroll",),
    "engag": ("engaged",),
    "enjoy": ("enjoy",),
    "excit": ("excite",),
    "gather": ("gathering",),
    "giv": ("give",),
    "interest": ("interest",),
    "interested": ("interest",),
    "kids": ("kid",),
    "lik": ("like",),
    "marri": ("marry", "married"),
    "mov": ("move", "moved"),
    "nervou": ("nervous",),
    "overwhelm": ("overwhelmed",),
    "persue": ("pursue",),
    "plann": ("plan",),
    "participat": ("participate",),
    "politic": ("political",),
    "proces": ("process",),
    "prioritiz": ("prioritize",),
    "pursu": ("pursue",),
    "rais": ("raise",),
    "receiv": ("receive", "received"),
    "read": ("read",),
    "realiz": ("realize",),
    "refreshe": ("refresh",),
    "reliev": ("relieved",),
    "religiou": ("religious",),
    "relocat": ("relocated",),
    "statu": ("status",),
    "stres": ("stress",),
    "symboliz": ("symbolize", "symbol"),
    "worri": ("worried",),
    "writ": ("write", "writing"),
    "grow": ("growing", "childhood"),
}
QUERY_RENDER_SURFACES = {
    "carv": "carving",
    "dres": "dress",
    "decompres": "decompress",
    "expres": "express",
    "figur": "figuring",
    "accept": "accepted",
    "chang": "changing",
    "inspir": "inspiring",
    "lov": "loving",
    "register": "registered",
    "engag": "engaged",
    "relocat": "relocated",
    "thrill": "thrilled",
    "upbring": "upbringing",
    "wellnes": "wellness",
}
PERSON_ENTITY_ALIASES = {
    "mel": ("melanie",),
}
NON_SPEAKER_ENTITY_SURFACES = {
    "dr",
    "four",
    "lgbtq",
    "seasons",
    "seuss",
    "vivaldi",
}
HONORIFIC_ENTITY_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof)\.\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\b"
)


def entity_speaks_in_memory(entity: str, text: str) -> bool:
    escaped = re.escape(entity)
    return bool(
        re.search(
            rf"(?:^|\n|\bD\d+:\d+\s+){escaped}\s*:",
            text,
            flags=re.IGNORECASE,
        )
    )


def entity_surface_in_memory(entity: str, text: str) -> bool:
    surface = " ".join(str(entity or "").casefold().split())
    if not surface:
        return False
    escaped = r"[\s.:'\"/-]+".join(re.escape(part) for part in surface.split())
    return bool(
        re.search(
            rf"(?<![0-9a-zA-Z_]){escaped}(?![0-9a-zA-Z_])",
            text,
            flags=re.IGNORECASE,
        )
    )


def memory_has_focused_turn_surface(memory: RetrievedMemory) -> bool:
    text = memory.text or ""
    if not _DIRECT_TURN_SPEAKER_RE.search(text):
        return False
    if _BROAD_SUMMARY_SURFACE_RE.search(text):
        return False
    turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(text)))
    if 0 < len(turn_refs) <= 2:
        return True
    source_turn_refs = tuple(
        ref for ref in memory.source_refs if _TURN_REF_RE.search(str(ref))
    )
    return bool(source_turn_refs) and len(memory.source_refs) <= 3


def entity_surfaces(entities: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    for entity in entities:
        surfaces.append(entity)
        surfaces.extend(PERSON_ENTITY_ALIASES.get(entity, ()))
    return tuple(dict.fromkeys(surfaces))


def render_query_terms(terms: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(QUERY_RENDER_SURFACES.get(str(term), str(term)) for term in terms)
    )


def visual_surface_terms(terms: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    if "paint" in terms:
        surfaces.append("painting")
    return tuple(dict.fromkeys(surfaces))


def compact_temporal_relation_terms(lexical_terms: Sequence[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for term in lexical_terms:
        if _is_numeric_or_ordinal_query_token(term) or (
            term in _COMPACT_TEMPORAL_RELATION_TERMS
        ):
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def speaker_surfaces(entity_surfaces: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        entity for entity in entity_surfaces if _allowed_speaker_surface(entity)
    )


def speaker_match_surfaces(entity_surfaces: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    for entity in entity_surfaces:
        normalized = entity.casefold()
        surfaces.append(normalized)
        surfaces.extend(PERSON_ENTITY_ALIASES.get(normalized, ()))
        surfaces.extend(
            canonical
            for canonical, aliases in PERSON_ENTITY_ALIASES.items()
            if normalized in aliases
        )
    return tuple(dict.fromkeys(surfaces))


def memory_has_temporal_surface(memory: RetrievedMemory) -> bool:
    if memory_timestamp_values(memory):
        return True
    return bool(
        _TIME_SURFACE_RE.search(memory.text) or _DURATION_SURFACE_RE.search(memory.text)
    )


def memory_has_sequence_surface(memory: RetrievedMemory) -> bool:
    return bool(_SEQUENCE_SURFACE_RE.search(memory.text))


def memory_has_visual_evidence(memory: RetrievedMemory) -> bool:
    return bool(_VISUAL_EVIDENCE_RE.search(memory.text))


def memory_has_preference_evidence(memory: RetrievedMemory) -> bool:
    return bool(_PREFERENCE_EVIDENCE_RE.search(memory.text))


def is_preference_query(profile: Mapping[str, object]) -> bool:
    preference_terms = {
        "destress",
        "enjoy",
        "favorite",
        "favourite",
        "interest",
        "like",
        "love",
        "prioritize",
    }
    relation_terms = set(string_sequence(profile.get("relation_terms")))
    return bool(preference_terms & relation_terms)


def is_contrast_query(profile: Mapping[str, object]) -> bool:
    return bool(
        "contrast" in string_sequence(profile.get("evidence_need"))
        or "contrast" in string_sequence(profile.get("relation_categories"))
    )


def timestamped_memory_count(memories: Sequence[RetrievedMemory]) -> int:
    return sum(1 for memory in memories if memory_timestamp_values(memory))


def memory_timestamp_values(memory: RetrievedMemory) -> tuple[int, ...]:
    values = memory.metadata.get("source_ref_time_start_ms")
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        return ()
    return tuple(value for item in values if (value := optional_int(item)) is not None)


def normalized_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in _WORD_RE.findall(text.casefold()):
        token = raw.strip("'-")
        if token.endswith("'s"):
            token = token[:-2]
        if _query_token_too_short(token) or token in QUERY_STOPWORDS:
            continue
        term = _stem_query_token(token)
        terms.append(term)
        terms.extend(QUERY_TOKEN_ALIASES.get(term, ()))
    return tuple(terms)


def question_phrase_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    if re.search(r"\bgo\s+to\b", text, flags=re.IGNORECASE):
        terms.append("go")
    if re.search(
        r"\b(?:what|which)\s+school\b|"
        r"\b(?:college|university)\b|"
        r"\b(?:study|studies|studying|major|majoring|degree)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("education")
    if re.search(r"\bwhat\s+class\b", text, flags=re.IGNORECASE):
        terms.append("class")
        if not re.search(
            r"\b(?:enroll|enrolled|register|registered|sign(?:ed)?)\b",
            text,
            flags=re.IGNORECASE,
        ):
            terms.append("education")
    if re.search(
        r"\b(?:what|which)\s+(?:company|job|occupation|profession|workplace)\b|"
        r"\b(?:job|occupation|profession|workplace)\b|"
        r"\bwhere\b.+\bwork\b|"
        r"\bwhat\b.+\bdo\b.+\bfor\s+work\b|"
        r"\bwork\b.+\b(?:company|for)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("employment")
    if re.search(
        r"\b(?:doctor|therapist|medication|medicine|prescription|allerg"
        r"(?:y|ic)|health\s+issue|condition)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("health")
    if re.search(
        r"\bhow\s+old\b|\bwhat\b.+\bage\b|\bage\b.+\b(?:is|of)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("age")
    if re.search(
        r"\bnicknames?\b|\balias\b|"
        r"\bwhat\s+(?:does|did)\b.+\bcall\b(?!.*\b(?:about|to|with)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("nickname")
    if re.search(
        r"\bwhat\s+pet\b|\b(?:dog|cat|pet)\b.+\bnamed?\b|"
        r"\bname\b.+\b(?:dog|cat|pet)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("pet")
    if re.search(
        r"\blanguages?\b.+\bspeak\b|\bspeak\b.+\blanguages?\b|"
        r"\binstrument\b.+\bplay\b|\bplay\b.+\binstrument\b|"
        r"\bplay\s+(?:guitar|piano|violin|drums?)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("skill")
    if re.search(
        r"\b(?:what|which|kind\s+of|color)\b.+"
        r"\b(?:car|vehicle|truck|suv|sedan|van)\b|"
        r"\b(?:car|vehicle|truck|suv|sedan|van)\b.+"
        r"\b(?:drive|have|has|own|color)\b|"
        r"\bdrive\s+(?:a|an|the|my|his|her|their)\s+"
        r"(?:car|vehicle|truck|suv|sedan|van)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("vehicle")
    if re.search(
        r"\bwhere\b.+\blive\b|\blive\b.+\bwhere\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("live")
    if re.search(
        r"\b(?:where|city|country|place)\b.+\b(?:from|originally)\b",
        text,
        flags=re.IGNORECASE,
    ) and not re.search(
        r"\b(?:move|moved|moving|relocate|relocated|relocation)\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("origin")
    if re.search(
        r"\bwhere\b.+\b(?:grow|grew)\s+up\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.extend(("grow", "origin"))
    if re.search(
        r"\bwhere\b.+\bborn\b|\bhometown\b|"
        r"\bwhere\b.+\bchildhood\b|\bchildhood\b.+\bwhere\b",
        text,
        flags=re.IGNORECASE,
    ):
        terms.append("origin")
    if re.search(r"\bwhere\b.+\bstay\b", text, flags=re.IGNORECASE):
        terms.append("stay")
    return tuple(terms)


def string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(str(item) for item in value if str(item))


def optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_numeric_or_ordinal_query_token(token: str) -> bool:
    return bool(token) and token[0].isdigit()


def _allowed_speaker_surface(entity: str) -> bool:
    parts = str(entity or "").casefold().split()
    return bool(parts) and not any(part in NON_SPEAKER_ENTITY_SURFACES for part in parts)


def _query_token_too_short(token: str) -> bool:
    if len(token) >= 3:
        return False
    return not token.isdigit()


def _stem_query_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ing"):
        base = token[:-3]
        if len(base) > 3 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token
