"""Question-derived, source-backed evidence for distinct-set cardinality."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice

_MAX_QUERY_CHARS = 512
_MAX_EVIDENCE_CHARS = 12_000
_MAX_USER_SEGMENTS = 24
_MAX_SENTENCES = 64
_MAX_EVIDENCE_SENTENCES = 12
_MAX_MEMBER_IDENTITIES = 12
_MAX_PROJECTION_CHARS = 3_000
_DISTINCT_SET_QUERY_RE = re.compile(
    r"\bhow\s+many\s+(?P<target>.{1,120}?)\s+"
    r"(?:do|does|did|have|has|had|am|are|was|were|will|would|can|could)\b"
    r"(?P<predicate>.{1,260})",
    re.IGNORECASE | re.DOTALL,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'./-]{0,39}")
_USER_SEGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])user:\s*(?P<text>.*?)"
    r"(?=(?<![A-Za-z0-9_])(?:assistant|system|user):|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_ROLE_SEGMENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:assistant|system|user):",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_FIRST_PERSON_RE = re.compile(r"\b(?:I(?:'ve|'m|'d|'ll)?|me|my)\b", re.IGNORECASE)
_FIRST_PERSON_SUBJECT_RE = re.compile(r"^\s*(?:I|we)\b", re.IGNORECASE)
_CURRENT_QUERY_RE = re.compile(r"\b(?:current|currently|now|still\s+have)\b", re.IGNORECASE)
_THIS_YEAR_QUERY_RE = re.compile(r"\b(?:in\s+)?this\s+year\b", re.IGNORECASE)
_RECENT_QUERY_RE = re.compile(
    r"\b(?:recently|in\s+the\s+past\s+(?:few|several)\s+months?|"
    r"over\s+the\s+(?:last|past)\s+(?:few|several)\s+months?)\b",
    re.IGNORECASE,
)
_LAST_YEAR_RE = re.compile(r"\b(?:last|previous|prior)\s+year\b", re.IGNORECASE)
_NUMERIC_DATE_RE = re.compile(r"\b(?P<month>1[0-2]|0?[1-9])/(?P<day>[0-3]?\d)\b")
_TEMPORAL_MARKER_RE = re.compile(
    r"\b(?:currently|now|still|no\s+longer|not\s+anymore|this\s+year|"
    r"last\s+year|previous\s+year|prior\s+year|last\s+weekend|"
    r"recently|january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)
_TEMPORAL_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?:\s*,\s*|\s+)(?:and|but|however|whereas|while)\s+|\s*;\s*",
    re.IGNORECASE,
)
_STALE_ASSERTION_RE = re.compile(
    r"\b(?:no\s+longer|not\s+anymore|used\s+to|former|previous|"
    r"old(?:\s+[A-Za-z0-9'./-]+){0,3}\s+"
    r"(?:one|tank|service|property|kit)|sold\s+it)\b",
    re.IGNORECASE,
)
_ACTIVE_ASSERTION_RE = re.compile(
    r"\b(?:currently|now|still|I\s+have|I've\s+got)\b",
    re.IGNORECASE,
)
_TARGET_SCAFFOLD = frozenset(
    {
        "a",
        "an",
        "different",
        "distinct",
        "item",
        "items",
        "kind",
        "kinds",
        "number",
        "of",
        "piece",
        "pieces",
        "the",
        "type",
        "types",
    }
)
_IDENTITY_SCAFFOLD = frozenset(
    {
        "a",
        "about",
        "an",
        "another",
        "few",
        "finally",
        "first",
        "for",
        "from",
        "got",
        "had",
        "have",
        "i",
        "i've",
        "in",
        "last",
        "my",
        "new",
        "one",
        "recently",
        "small",
        "some",
        "that",
        "the",
        "this",
        "to",
        "week",
        "weeks",
        "with",
    }
)
_GENERIC_IDENTITIES = frozenset(
    {
        "cocktail",
        "cuisine",
        "delivery service",
        "food delivery service",
        "fruit",
        "furniture",
        "gallery",
        "kit",
        "model kit",
        "museum",
        "property",
        "recipe",
        "service",
        "tank",
        "wedding",
    }
)
_PHRASE_BOUNDARY_TERMS = _IDENTITY_SCAFFOLD | frozenset(
    {
        "after",
        "and",
        "at",
        "back",
        "before",
        "but",
        "by",
        "did",
        "does",
        "her",
        "him",
        "his",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "she",
        "their",
        "them",
        "they",
        "up",
        "was",
        "we",
        "were",
    }
)
_INGREDIENT_TARGET_TERMS = frozenset(
    {"fruit", "vegetable", "ingredient", "herb", "spice", "citrus"}
)
_PROVIDER_TARGET_TERMS = frozenset({"app", "platform", "provider", "service", "vendor"})
_CATEGORY_TARGET_TERMS = frozenset({"cuisine", "genre", "method", "style", "tradition"})
_CATEGORY_NON_IDENTITY_TERMS = frozenset({"cooking", "just", "local", "new", "online"})
_ACTION_ALIASES = {
    "assemble": "assemble",
    "assembled": "assemble",
    "attend": "attend",
    "attended": "attend",
    "bought": "buy",
    "buy": "buy",
    "cook": "learn",
    "cooked": "learn",
    "finish": "work",
    "finished": "work",
    "fix": "fix",
    "fixed": "fix",
    "get": "buy",
    "got": "buy",
    "had": "own",
    "has": "own",
    "have": "own",
    "learn": "learn",
    "learned": "learn",
    "made": "use",
    "make": "use",
    "mixed": "use",
    "ordered": "buy",
    "own": "own",
    "owned": "own",
    "purchased": "buy",
    "repair": "fix",
    "repaired": "fix",
    "saw": "view",
    "see": "view",
    "seen": "view",
    "sell": "sell",
    "sold": "sell",
    "tried": "try",
    "try": "try",
    "use": "use",
    "used": "use",
    "using": "use",
    "view": "view",
    "viewed": "view",
    "visit": "visit",
    "visited": "visit",
    "work": "work",
    "worked": "work",
}
_ACTION_PHRASES = (
    (
        re.compile(r"\b(?:been|went|took\s+(?:\w+\s+){1,3})to\b", re.IGNORECASE),
        "visit",
    ),
    (re.compile(r"\b(?:been\s+to|got\s+back\s+from)\b", re.IGNORECASE), "attend"),
    (re.compile(r"\bset\s+up\b", re.IGNORECASE), "own"),
    (re.compile(r"\b(?:taking\s+care\s+of|relying\s+on|relied\s+on)\b", re.IGNORECASE), "own"),
    (re.compile(r"\b(?:relying\s+on|all\s+about)\b", re.IGNORECASE), "use"),
    (re.compile(r"\b(?:started|start)\s+working\s+on\b", re.IGNORECASE), "work"),
    (re.compile(r"\b(?:put\s+in|made)\s+an?\s+offer\b", re.IGNORECASE), "offer"),
)
_POSSESSION_RE = re.compile(
    r"\b(?:my\s+|I\s+(?:currently\s+)?have\s+|I've\s+got\s+|"
    r"I'm\s+taking\s+care\s+of\s+)",
    re.IGNORECASE,
)
_MATERIAL_MEMBER_RE = re.compile(
    r"\b(?P<member>[A-Za-z][A-Za-z'-]{2,30})\s+"
    r"(?:juice|peels?|rinds?|zest|wedges?|bitters?|slices?)\b",
    re.IGNORECASE,
)
_MATERIAL_LIST_RE = re.compile(
    r"\b(?:slices?|wedges?|peels?)\s+of\s+"
    r"(?P<members>[A-Za-z][A-Za-z'-]{2,30}(?:\s*(?:,|and|or)\s*"
    r"[A-Za-z][A-Za-z'-]{2,30}){0,4})",
    re.IGNORECASE,
)
_CATEGORY_MEMBER_RE = re.compile(
    r"\b(?P<member>[A-Za-z][A-Za-z'-]{2,30})(?:-inspired)?\s+"
    r"(?:cuisine|restaurant|dish|recipe|class|food|meal|bibimbap|lasagna)\b",
    re.IGNORECASE,
)
_PROPER_NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9'/-]{1,30}(?:\s+[A-Z][A-Za-z0-9'./-]{1,30}){0,3}\b")
_VISITED_NAMED_VENUE_RE = re.compile(
    r"\b(?:saw|visited)\s+(?:an?\s+|the\s+)?"
    r"(?P<venue>[A-Z][A-Za-z0-9'/-]{1,30}"
    r"(?:\s+[A-Z][A-Za-z0-9'./-]{1,30}){0,3})\b"
)
_PROVIDER_RELATION_CUE_RE = re.compile(
    r"\b(?:all\s+about|called|from|had|like|on|ordered|relied\s+on|"
    r"relying\s+on|through|tried|used|using|via)\s*$",
    re.IGNORECASE,
)
_PROVIDER_TARGET_CUE_RE = re.compile(
    r"\b(?:delivery|deliveries|food\s+service|meal\s+service|"
    r"provider|platform|app|service|vendor)\b",
    re.IGNORECASE,
)
_PROVIDER_NAME_HINT_RE = re.compile(r"(?:dash|deliver|eats?)\b", re.IGNORECASE)
_PROVIDER_NAME_STOPWORDS = frozenset(
    {
        "after",
        "assistant",
        "before",
        "during",
        "in",
        "last",
        "system",
        "the",
        "this",
        "user",
    }
)
_ENTITY_OBJECT_TERMS = {
    "furniture": frozenset(
        {
            "bed",
            "bookshelf",
            "cabinet",
            "chair",
            "couch",
            "desk",
            "mattress",
            "shelf",
            "sofa",
            "table",
        }
    ),
    "kit": frozenset(
        {"bomber", "camaro", "diorama", "kit", "model", "spitfire", "tank"}
    ),
    "property": frozenset(
        {"apartment", "bungalow", "condo", "home", "house", "property", "townhouse"}
    ),
    "tank": frozenset({"aquarium", "tank"}),
    "wedding": frozenset({"marriage", "wedding"}),
}
_ACTION_OBJECT_RE = re.compile(
    r"\b(?:bought|ordered|assembled|fixed|repaired|viewed|visited|saw|seen|"
    r"attended|finished|got|working\s+on|worked\s+on)\s+"
    r"(?P<object>(?:an?|the|that|my|new|recently|finally|\d+(?:/\d+)?|"
    r"[A-Za-z0-9][A-Za-z0-9'./-]*)"
    r"(?:\s+(?:[A-Za-z0-9][A-Za-z0-9'./-]*)){0,6})",
    re.IGNORECASE,
)
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


class DistinctSetTargetKind(StrEnum):
    ENTITY = "entity"
    INGREDIENT_VARIETY = "ingredient_variety"
    NAMED_PROVIDER = "named_provider"
    NAMED_CATEGORY = "named_category"


class DistinctSetTemporalWindow(StrEnum):
    NONE = "none"
    CURRENT = "current"
    MONTH = "month"
    RECENT = "recent"
    THIS_YEAR = "this_year"


@dataclass(frozen=True)
class DistinctSetRequest:
    target_terms: tuple[str, ...]
    action_terms: tuple[str, ...]
    target_kind: DistinctSetTargetKind
    current_only: bool
    month_terms: tuple[str, ...]
    subject_is_first_person: bool
    subject_terms: tuple[str, ...]
    temporal_window: DistinctSetTemporalWindow


@dataclass(frozen=True)
class DistinctSetEvidenceProjection:
    member_ids: tuple[str, ...] = ()
    identities: tuple[str, ...] = ()
    evidence_sentences: tuple[str, ...] = ()
    rendered_text: str = ""
    temporal_rejection_count: int = 0
    subject_rejection_count: int = 0

    @property
    def present(self) -> bool:
        return bool(self.member_ids and self.rendered_text)

    @property
    def temporal_conflict(self) -> bool:
        return not self.present and self.temporal_rejection_count > 0

    @property
    def subject_conflict(self) -> bool:
        return not self.present and self.subject_rejection_count > 0


def distinct_set_retrieval_terms(request: DistinctSetRequest) -> tuple[str, ...]:
    """Return bounded target/action terms for a second canonical keyword pass."""

    terms = [*request.target_terms, *request.action_terms]
    if request.target_kind is DistinctSetTargetKind.INGREDIENT_VARIETY:
        terms.extend(("juice", "peel", "rind", "zest", "wedge"))
    elif request.target_kind is DistinctSetTargetKind.NAMED_CATEGORY:
        terms.extend(("cuisine", "dish", "recipe", "class", "food", "meal"))
    elif request.target_kind is DistinctSetTargetKind.NAMED_PROVIDER:
        terms.extend(("delivery", "app", "service", "provider"))
    else:
        terms.extend(
            alias
            for target in request.target_terms
            for alias in _ENTITY_OBJECT_TERMS.get(target, ())
        )
    return tuple(dict.fromkeys(terms))[:24]


def extract_distinct_set_request(query: str) -> DistinctSetRequest | None:
    """Parse an explicit cardinality set without answer or benchmark inputs."""

    bounded = query[:_MAX_QUERY_CHARS]
    match = _DISTINCT_SET_QUERY_RE.search(bounded)
    if match is None:
        return None
    target_terms = _normalized_terms(match.group("target"), excluded=_TARGET_SCAFFOLD)
    action_terms = _action_terms(match.group("predicate"))
    if not target_terms or not action_terms:
        return None
    target_set = set(target_terms)
    target_surface = match.group("target").casefold()
    if "type" in target_surface and target_set.intersection(_INGREDIENT_TARGET_TERMS):
        target_kind = DistinctSetTargetKind.INGREDIENT_VARIETY
    elif target_set.intersection(_PROVIDER_TARGET_TERMS):
        target_kind = DistinctSetTargetKind.NAMED_PROVIDER
    elif target_set.intersection(_CATEGORY_TARGET_TERMS):
        target_kind = DistinctSetTargetKind.NAMED_CATEGORY
    else:
        target_kind = DistinctSetTargetKind.ENTITY
    current_only = bool(_CURRENT_QUERY_RE.search(bounded))
    month_terms = tuple(month for month in _MONTHS if month in bounded.casefold())
    subject_is_first_person = bool(_FIRST_PERSON_SUBJECT_RE.search(match.group("predicate")))
    return DistinctSetRequest(
        target_terms=target_terms,
        action_terms=action_terms,
        target_kind=target_kind,
        current_only=current_only,
        month_terms=month_terms,
        subject_is_first_person=subject_is_first_person,
        subject_terms=_query_subject_terms(
            match.group("predicate"),
            subject_is_first_person=subject_is_first_person,
        ),
        temporal_window=_temporal_window(
            bounded,
            current_only=current_only,
            month_terms=month_terms,
        ),
    )


def project_distinct_set_evidence(*, query: str, text: str) -> DistinctSetEvidenceProjection:
    """Project bounded user assertions and opaque target-member identities."""

    request = extract_distinct_set_request(query)
    if request is None or not text.strip():
        return DistinctSetEvidenceProjection()
    evidence_sentences: list[str] = []
    identities: list[str] = []
    seen_sentences: set[str] = set()
    seen_identities: set[str] = set()
    temporal_rejection_count = 0
    subject_rejection_count = 0
    for sentence in _user_assertion_sentences(text):
        normalized_sentence = " ".join(sentence.split())
        if not normalized_sentence:
            continue
        clauses = _evidence_clauses(request, normalized_sentence)
        sentence_actions = set(_action_terms(normalized_sentence))
        sentence_subject_grounded = _subject_grounded(request, normalized_sentence)
        for clause_index, clause in enumerate(clauses):
            normalized_clause = " ".join(clause.split()).strip(" ,;")
            if not normalized_clause or normalized_clause.casefold() in seen_sentences:
                continue
            clause_actions = set(_action_terms(normalized_clause))
            inherited_grounding = clause_index > 0 and len(clauses) > 1
            evidence_actions = clause_actions | (
                sentence_actions if inherited_grounding else set()
            )
            if not _request_action_supported(request, evidence_actions):
                continue
            clause_identities = _member_identities(request, normalized_clause)
            if not clause_identities:
                continue
            subject_grounded = _subject_grounded(request, normalized_clause)
            if not subject_grounded and inherited_grounding and sentence_subject_grounded:
                subject_grounded = not _clause_has_conflicting_subject(request, normalized_clause)
            if not subject_grounded:
                subject_rejection_count += 1
                continue
            if not _sentence_within_request_bounds(request, normalized_clause):
                temporal_rejection_count += 1
                continue
            seen_sentences.add(normalized_clause.casefold())
            evidence_sentences.append(normalized_clause)
            for identity in clause_identities:
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                identities.append(identity)
                if len(identities) >= _MAX_MEMBER_IDENTITIES:
                    break
            if (
                len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES
                or len(identities) >= _MAX_MEMBER_IDENTITIES
            ):
                break
        if len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES or len(
            identities
        ) >= _MAX_MEMBER_IDENTITIES:
            break
    if not identities:
        return DistinctSetEvidenceProjection(
            temporal_rejection_count=temporal_rejection_count,
            subject_rejection_count=subject_rejection_count,
        )
    member_ids = tuple(_opaque_member_id(identity) for identity in identities)
    rendered_text = _render_projection(text=text, evidence_sentences=evidence_sentences)
    return DistinctSetEvidenceProjection(
        member_ids=member_ids,
        identities=tuple(identities),
        evidence_sentences=tuple(evidence_sentences),
        rendered_text=rendered_text,
        temporal_rejection_count=temporal_rejection_count,
        subject_rejection_count=subject_rejection_count,
    )


def _user_assertion_sentences(text: str) -> tuple[str, ...]:
    bounded = text[:_MAX_EVIDENCE_CHARS]
    segments = tuple(
        match.group("text")
        for match in islice(_USER_SEGMENT_RE.finditer(bounded), _MAX_USER_SEGMENTS)
    )
    if not segments:
        if _ROLE_SEGMENT_RE.search(bounded):
            return ()
        segments = (bounded,)
    sentences: list[str] = []
    for segment in segments:
        for match in _SENTENCE_RE.finditer(segment):
            sentence = match.group(0).strip()
            if sentence:
                sentences.append(sentence)
                if len(sentences) >= _MAX_SENTENCES:
                    return tuple(sentences)
    return tuple(sentences)


def _sentence_within_request_bounds(request: DistinctSetRequest, sentence: str) -> bool:
    if (
        request.current_only
        and _STALE_ASSERTION_RE.search(sentence)
        and _ACTIVE_ASSERTION_RE.search(sentence) is None
    ):
        return False
    if request.temporal_window in {
        DistinctSetTemporalWindow.RECENT,
        DistinctSetTemporalWindow.THIS_YEAR,
    } and _LAST_YEAR_RE.search(sentence):
        return False
    sentence_months = {month for month in _MONTHS if month in sentence.casefold()}
    if request.month_terms and sentence_months:
        return not sentence_months.isdisjoint(request.month_terms)
    numeric_months = {
        _MONTHS[int(match.group("month")) - 1] for match in _NUMERIC_DATE_RE.finditer(sentence)
    }
    return not (
        request.month_terms
        and numeric_months
        and numeric_months.isdisjoint(request.month_terms)
    )


def _member_identities(request: DistinctSetRequest, sentence: str) -> tuple[str, ...]:
    identities: list[str] = []
    if request.target_kind is DistinctSetTargetKind.INGREDIENT_VARIETY:
        identities.extend(_material_member_identities(sentence))
    elif request.target_kind is DistinctSetTargetKind.NAMED_PROVIDER:
        identities.extend(_provider_member_identities(request, sentence))
    elif request.target_kind is DistinctSetTargetKind.NAMED_CATEGORY:
        identities.extend(_category_member_identities(sentence))
    else:
        identities.extend(_target_phrase_identities(request, sentence))
    selected: list[str] = []
    seen: set[str] = set()
    for identity in identities:
        value = _normalize_identity(identity)
        if not value or value in _GENERIC_IDENTITIES or value in seen:
            continue
        seen.add(value)
        selected.append(value)
        if len(selected) >= _MAX_MEMBER_IDENTITIES:
            break
    if selected or request.target_kind is not DistinctSetTargetKind.ENTITY:
        return tuple(selected)
    for identity in _action_object_identities(request, sentence):
        value = _normalize_identity(identity)
        if not value or value in _GENERIC_IDENTITIES or value in seen:
            continue
        seen.add(value)
        selected.append(value)
        if len(selected) >= _MAX_MEMBER_IDENTITIES:
            break
    return tuple(selected)


def _material_member_identities(sentence: str) -> tuple[str, ...]:
    values = [match.group("member") for match in _MATERIAL_MEMBER_RE.finditer(sentence)]
    for match in _MATERIAL_LIST_RE.finditer(sentence):
        values.extend(re.split(r"\s*(?:,|\band\b|\bor\b)\s*", match.group("members")))
    return tuple(values)


def _provider_member_identities(
    request: DistinctSetRequest,
    sentence: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for match in _PROPER_NAME_RE.finditer(sentence):
        surface = match.group(0)
        terms = tuple(
            token.casefold().strip(".'/-") for token in _TOKEN_RE.findall(surface)
        )
        if not terms or any(term in _MONTHS for term in terms):
            continue
        while terms and terms[0] in _PROVIDER_NAME_STOPWORDS:
            terms = terms[1:]
        if not terms:
            continue
        normalized_surface = " ".join(terms)
        if _provider_name_grounded(
            request,
            sentence=sentence,
            start=match.start(),
            end=match.end(),
            normalized_surface=normalized_surface,
        ):
            values.append(normalized_surface)
    return tuple(values)


def _provider_name_grounded(
    request: DistinctSetRequest,
    *,
    sentence: str,
    start: int,
    end: int,
    normalized_surface: str,
) -> bool:
    relation_start = max(
        sentence.rfind(" and ", 0, start),
        sentence.rfind(" but ", 0, start),
        sentence.rfind(" while ", 0, start),
        sentence.rfind(";", 0, start),
    )
    relation_end_candidates = tuple(
        position
        for marker in (" and ", " but ", " while ", ";")
        if (position := sentence.find(marker, end)) >= 0
    )
    relation_end = min(relation_end_candidates, default=len(sentence))
    relation = sentence[relation_start + 1 : relation_end]
    local_before = sentence[max(relation_start + 1, start - 32) : start]
    has_relation_cue = _PROVIDER_RELATION_CUE_RE.search(local_before) is not None
    has_target_cue = _PROVIDER_TARGET_CUE_RE.search(relation) is not None
    has_provider_name_hint = _PROVIDER_NAME_HINT_RE.search(normalized_surface) is not None
    return has_relation_cue and (has_target_cue or has_provider_name_hint) and (
        _request_action_supported(request, set(_action_terms(relation)))
        or "called" in local_before.casefold()
        or "like" in local_before.casefold()
    )


def _category_member_identities(sentence: str) -> tuple[str, ...]:
    return tuple(
        member
        for match in _CATEGORY_MEMBER_RE.finditer(sentence)
        if (member := match.group("member")).casefold() not in _CATEGORY_NON_IDENTITY_TERMS
    )


def _target_phrase_identities(
    request: DistinctSetRequest,
    sentence: str,
) -> tuple[str, ...]:
    tokens = tuple(_TOKEN_RE.finditer(sentence))
    values: list[str] = []
    target_terms = set(request.target_terms)
    for index, match in enumerate(tokens):
        term = _singular(match.group(0).casefold().strip(".'/-"))
        if term not in target_terms:
            continue
        prefix = [token.group(0) for token in tokens[max(0, index - 5) : index]]
        boundary = max(
            (
                offset
                for offset, token in enumerate(prefix)
                if token.casefold().strip(".'/-") in _PHRASE_BOUNDARY_TERMS
            ),
            default=-1,
        )
        values.append(" ".join((*prefix[boundary + 1 :], match.group(0))))
    return tuple(values)


def _action_object_identities(
    request: DistinctSetRequest,
    sentence: str,
) -> tuple[str, ...]:
    aliases = frozenset(
        alias
        for target in request.target_terms
        for alias in _ENTITY_OBJECT_TERMS.get(target, (target,))
    )
    values: list[str] = []
    if {"gallery", "museum"}.intersection(request.target_terms):
        values.extend(
            match.group("venue") for match in _VISITED_NAMED_VENUE_RE.finditer(sentence)
        )
        if values:
            return tuple(values)
    for match in _ACTION_OBJECT_RE.finditer(sentence):
        value = match.group("object")
        terms = _normalized_terms(value, excluded=frozenset())
        named_venue = (
            {"gallery", "museum"}.intersection(request.target_terms)
            and re.match(r"^(?:an?\s+|the\s+)?[A-Z]", value) is not None
        )
        if aliases.intersection(terms) or named_venue:
            values.append(value)
    return tuple(values)


def _action_terms(text: str) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    bounded = text[:_MAX_QUERY_CHARS]
    for pattern, action in _ACTION_PHRASES:
        if pattern.search(bounded) and action not in seen:
            seen.add(action)
            selected.append(action)
    if _POSSESSION_RE.search(bounded) and "own" not in seen:
        seen.add("own")
        selected.append("own")
    for match in _TOKEN_RE.finditer(bounded):
        action = _ACTION_ALIASES.get(match.group(0).casefold().strip(".'/-"))
        if action is None or action in seen:
            continue
        seen.add(action)
        selected.append(action)
    return tuple(selected[:8])


def _action_spans(text: str) -> tuple[tuple[int, str], ...]:
    spans: list[tuple[int, str]] = []
    for pattern, action in _ACTION_PHRASES:
        spans.extend((match.start(), action) for match in pattern.finditer(text))
    for match in _TOKEN_RE.finditer(text):
        action = _ACTION_ALIASES.get(match.group(0).casefold().strip(".'/-"))
        if action is not None:
            spans.append((match.start(), action))
    return tuple(sorted(set(spans)))


def _request_action_supported(
    request: DistinctSetRequest,
    evidence_actions: set[str],
) -> bool:
    requested = set(request.action_terms)
    if requested.intersection(evidence_actions):
        return True
    if "visit" in requested and "attend" in evidence_actions:
        return True
    if (
        request.target_kind is DistinctSetTargetKind.NAMED_CATEGORY
        and "learn" in requested
        and "attend" in evidence_actions
    ):
        return True
    return bool(
        request.target_kind is DistinctSetTargetKind.NAMED_PROVIDER
        and "use" in requested
        and "buy" in evidence_actions
    )


def _query_subject_terms(
    predicate: str,
    *,
    subject_is_first_person: bool,
) -> tuple[str, ...]:
    if subject_is_first_person:
        return ()
    action_starts = [start for start, _action in _action_spans(predicate)]
    subject_surface = predicate[: min(action_starts, default=len(predicate))]
    values: list[str] = []
    seen: set[str] = set()
    for match in _PROPER_NAME_RE.finditer(subject_surface):
        for token in _TOKEN_RE.findall(match.group(0)):
            value = token.casefold().strip(".'/-")
            if value and value not in seen:
                seen.add(value)
                values.append(value)
    return tuple(values[:4])


def _subject_grounded(request: DistinctSetRequest, sentence: str) -> bool:
    if request.subject_is_first_person:
        return _FIRST_PERSON_RE.search(sentence) is not None
    if not request.subject_terms:
        return False
    first_person = _FIRST_PERSON_RE.search(sentence)
    for action_start, action in _action_spans(sentence):
        if not _request_action_supported(request, {action}):
            continue
        if first_person is not None and first_person.start() < action_start:
            continue
        if any(
            (match := re.search(rf"\b{re.escape(term)}\b", sentence, re.IGNORECASE))
            and match.end() <= action_start
            for term in request.subject_terms
        ):
            return True
    return False


def _clause_has_conflicting_subject(request: DistinctSetRequest, clause: str) -> bool:
    if request.subject_is_first_person:
        return False
    if _FIRST_PERSON_RE.search(clause) is not None:
        return True
    supported_action_starts = tuple(
        start
        for start, action in _action_spans(clause)
        if _request_action_supported(request, {action})
    )
    if not supported_action_starts:
        return False
    subject_surface = clause[: min(supported_action_starts)]
    named_terms = {
        token.casefold().strip(".'/-")
        for match in _PROPER_NAME_RE.finditer(subject_surface)
        for token in _TOKEN_RE.findall(match.group(0))
    }
    named_terms.difference_update(_MONTHS)
    named_terms.difference_update(_PROVIDER_NAME_STOPWORDS)
    return bool(named_terms and named_terms.isdisjoint(request.subject_terms))


def _temporal_window(
    query: str,
    *,
    current_only: bool,
    month_terms: tuple[str, ...],
) -> DistinctSetTemporalWindow:
    if current_only:
        return DistinctSetTemporalWindow.CURRENT
    if month_terms:
        return DistinctSetTemporalWindow.MONTH
    if _THIS_YEAR_QUERY_RE.search(query):
        return DistinctSetTemporalWindow.THIS_YEAR
    if _RECENT_QUERY_RE.search(query):
        return DistinctSetTemporalWindow.RECENT
    return DistinctSetTemporalWindow.NONE


def _evidence_clauses(
    request: DistinctSetRequest,
    sentence: str,
) -> tuple[str, ...]:
    clauses = tuple(
        clause.strip()
        for clause in _TEMPORAL_CLAUSE_BOUNDARY_RE.split(sentence)
        if clause.strip()
    )
    temporal_markers = len(tuple(_TEMPORAL_MARKER_RE.finditer(sentence)))
    named_subject_clauses = sum(
        _subject_grounded(request, clause)
        or _clause_has_conflicting_subject(request, clause)
        for clause in clauses
    )
    if temporal_markers < 2 and (
        request.subject_is_first_person or named_subject_clauses < 2
    ):
        return (sentence,)
    return clauses or (sentence,)


def _normalized_terms(text: str, *, excluded: frozenset[str]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(text):
        value = _singular(match.group(0).casefold().strip(".'/-"))
        if value in excluded or value in seen:
            continue
        seen.add(value)
        values.append(value)
        if len(values) >= 8:
            break
    return tuple(values)


def _normalize_identity(value: str) -> str:
    terms = [
        _singular(match.group(0).casefold().strip(".'/-")) for match in _TOKEN_RE.finditer(value)
    ]
    filtered = [term for term in terms if term and term not in _IDENTITY_SCAFFOLD]
    return " ".join(filtered[-5:])


def _singular(term: str) -> str:
    if term.endswith("'s"):
        return term
    if term.endswith("ies") and len(term) > 4:
        return f"{term[:-3]}y"
    if term.endswith(("sses", "shes", "ches", "xes", "zes")) and len(term) > 4:
        return term[:-2]
    if term.endswith("s") and not term.endswith(("is", "ss", "us")) and len(term) > 3:
        return term[:-1]
    return term


def _opaque_member_id(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"member_{digest}"


def _render_projection(*, text: str, evidence_sentences: list[str]) -> str:
    header = _source_header(text)
    lines = [header] if header else []
    lines.extend(f"user assertion: {sentence}" for sentence in evidence_sentences)
    rendered = "\n\n".join(lines)
    return rendered[:_MAX_PROJECTION_CHARS].strip()


def _source_header(text: str) -> str:
    for line in text.splitlines():
        value = " ".join(line.split()).strip()
        if not value or re.match(r"^(?:user|assistant|system):", value, re.IGNORECASE):
            continue
        return value[:240]
    return ""
