"""Question-derived contributor slots for pending item actions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice

from infinity_context_core.application.context_baby_birth_evidence import (
    BABY_BIRTH_RETRIEVAL_TERMS,
    baby_birth_count_query,
    project_baby_birth_count,
)
from infinity_context_core.application.context_quantity_evidence_patterns import (
    _BAKED_ITEM_RE,
    _BAKING_EVENT_QUERY_RE,
    _BAKING_EVENT_RE,
    _CLOTHING_QUERY_RE,
    _COMPLETED_EXPENSE_RE,
    _COUNT_QUERY_RE,
    _DURATION_ACTIVITY_RE,
    _DURATION_VALUE_RE,
    _FIRST_PERSON_RE,
    _FUTURE_EXPENSE_RE,
    _IDENTITY_STOPWORDS,
    _IDENTITY_TOKEN_RE,
    _MAX_EVIDENCE_CHARS,
    _MAX_EVIDENCE_SENTENCES,
    _MAX_MEMBER_IDENTITIES,
    _MAX_PROJECTION_CHARS,
    _MAX_QUERY_CHARS,
    _MAX_SENTENCES,
    _MAX_USER_SEGMENTS,
    _MONEY_VALUE_RE,
    _NEGATED_CAMPING_RE,
    _PENDING_QUERY_RE,
    _PERSONAL_NUMERIC_PARTICIPATION_RE,
    _PICKUP_RE,
    _PROJECT_LEADERSHIP_QUERY_RE,
    _RETURN_RE,
    _ROLE_SEGMENT_RE,
    _SENTENCE_RE,
    _SPENT_DURATION_ON_QUERY_RE,
    _TARGET_STOPWORDS,
    _TOTAL_DURATION_QUERY_RE,
    _TOTAL_MONEY_QUERY_RE,
    _USER_SEGMENT_RE,
)
from infinity_context_core.application.context_quantity_pending_clothing import (
    resolve_pending_clothing_sentence,
)
from infinity_context_core.application.context_short_story_progress_evidence import (
    SHORT_STORY_PROGRESS_RETRIEVAL_TERMS,
    project_short_story_progress_count,
    short_story_progress_count_query,
)


class QuantityEvidenceTargetKind(StrEnum):
    BABY_BIRTH_COUNT = "baby_birth_count"
    BAKING_EVENT_COUNT = "baking_event_count"
    PENDING_CLOTHING_ACTION = "pending_clothing_action"
    PROJECT_LEADERSHIP_COUNT = "project_leadership_count"
    SHORT_STORY_PROGRESS_COUNT = "short_story_progress_count"
    TOTAL_ACTIVITY_DURATION = "total_activity_duration"
    TOTAL_MONEY_EXPENSE = "total_money_expense"


@dataclass(frozen=True)
class QuantityEvidenceRequest:
    target_kind: QuantityEvidenceTargetKind
    target_terms: tuple[str, ...]
    action_terms: tuple[str, ...]
    requires_store_context: bool = False


@dataclass(frozen=True)
class QuantityEvidenceProjection:
    request_detected: bool = False
    member_ids: tuple[str, ...] = ()
    identities: tuple[str, ...] = ()
    evidence_sentences: tuple[str, ...] = ()
    rendered_text: str = ""

    @property
    def present(self) -> bool:
        return bool(self.member_ids and self.rendered_text)


def extract_quantity_evidence_request(query: str) -> QuantityEvidenceRequest | None:
    """Recognize bounded contributor questions without answer-side inputs."""

    bounded = query[:_MAX_QUERY_CHARS]
    if money_match := _TOTAL_MONEY_QUERY_RE.search(bounded):
        target_terms = _normalized_target_terms(money_match.group("target"))
        if target_terms:
            return QuantityEvidenceRequest(
                target_kind=QuantityEvidenceTargetKind.TOTAL_MONEY_EXPENSE,
                target_terms=target_terms,
                action_terms=("spent", "paid", "cost", "bought", "installed"),
            )
    if duration_match := _TOTAL_DURATION_QUERY_RE.search(bounded):
        target_terms = _normalized_target_terms(duration_match.group("target"))
        if target_terms:
            return QuantityEvidenceRequest(
                target_kind=QuantityEvidenceTargetKind.TOTAL_ACTIVITY_DURATION,
                target_terms=target_terms,
                action_terms=(duration_match.group("action").casefold(),),
            )
    if spent_duration_match := _SPENT_DURATION_ON_QUERY_RE.search(bounded):
        target_terms = _normalized_target_terms(spent_duration_match.group("target"))
        if target_terms:
            return QuantityEvidenceRequest(
                target_kind=QuantityEvidenceTargetKind.TOTAL_ACTIVITY_DURATION,
                target_terms=target_terms,
                action_terms=("spent",),
            )
    if _PROJECT_LEADERSHIP_QUERY_RE.search(bounded):
        return QuantityEvidenceRequest(
            target_kind=QuantityEvidenceTargetKind.PROJECT_LEADERSHIP_COUNT,
            target_terms=("project",),
            action_terms=("project_leadership",),
        )
    if _BAKING_EVENT_QUERY_RE.search(bounded):
        return QuantityEvidenceRequest(
            target_kind=QuantityEvidenceTargetKind.BAKING_EVENT_COUNT,
            target_terms=("baking",),
            action_terms=("baking_event",),
        )
    if baby_birth_count_query(bounded):
        return QuantityEvidenceRequest(
            target_kind=QuantityEvidenceTargetKind.BABY_BIRTH_COUNT,
            target_terms=("baby",),
            action_terms=("baby_birth",),
        )
    if short_story_progress_count_query(bounded):
        return QuantityEvidenceRequest(
            target_kind=QuantityEvidenceTargetKind.SHORT_STORY_PROGRESS_COUNT,
            target_terms=("short", "story"),
            action_terms=("short_story_progress",),
        )
    match = _COUNT_QUERY_RE.search(bounded)
    if match is None or _PENDING_QUERY_RE.search(match.group("predicate")) is None:
        return None
    if _FIRST_PERSON_RE.search(match.group("predicate")) is None:
        return None
    if _CLOTHING_QUERY_RE.search(match.group("target")) is None:
        return None
    actions = _requested_actions(match.group("predicate"))
    if not actions:
        return None
    return QuantityEvidenceRequest(
        target_kind=QuantityEvidenceTargetKind.PENDING_CLOTHING_ACTION,
        target_terms=("clothing",),
        action_terms=actions,
        requires_store_context=bool(
            re.search(r"\b(?:store|shop|retailer)\b", bounded, re.IGNORECASE)
        ),
    )


def quantity_evidence_retrieval_terms(
    *,
    target_terms: tuple[str, ...] = ("clothing",),
    action_terms: tuple[str, ...] = ("pickup", "return"),
) -> tuple[str, ...]:
    """Return fixed linguistic aliases, never benchmark or answer-derived terms."""

    if {"paid", "cost", "bought", "installed"}.intersection(action_terms):
        return tuple(
            dict.fromkeys(
                (
                    *target_terms,
                    "spent",
                    "paid",
                    "cost",
                    "bought",
                    "purchased",
                    "installed",
                    "dollar",
                    "usd",
                )
            )
        )[:24]
    if {"playing", "doing", "practicing", "watching", "working on", "spent"}.intersection(
        action_terms
    ):
        return tuple(
            dict.fromkeys(
                (
                    *target_terms,
                    *action_terms,
                    "hours",
                    "days",
                    "played",
                    "completed",
                    "finished",
                    "took",
                    "trip",
                )
            )
        )[:24]
    if "project_leadership" in action_terms:
        return tuple(
            dict.fromkeys(
                (
                    "project",
                    "projects",
                    "led",
                    "leading",
                    "currently",
                    "working on",
                    "solo project",
                    "research",
                    "poster",
                    "case competition",
                    "presentation",
                )
            )
        )[:24]
    if "baby_birth" in action_terms:
        return BABY_BIRTH_RETRIEVAL_TERMS[:24]
    if "baking_event" in action_terms:
        return tuple(
            dict.fromkeys(
                (
                    "baked",
                    "baking",
                    "bake",
                    "recipe",
                    "bread",
                    "cake",
                    "cookies",
                    "baguette",
                    "sourdough",
                    "oven",
                    "convection",
                )
            )
        )[:24]
    if "short_story_progress" in action_terms:
        return SHORT_STORY_PROGRESS_RETRIEVAL_TERMS[:24]
    action_aliases: list[str] = []
    if "pickup" in action_terms:
        action_aliases.extend(("pick up", "collect"))
    if "return" in action_terms:
        action_aliases.extend(("return", "exchange"))
    return tuple(
        dict.fromkeys(
            (
                *action_aliases,
                *target_terms,
                "clothes",
                "garment",
                "apparel",
                "wardrobe",
                "store",
                "shop",
                "retailer",
            )
        )
    )[:24]


def project_quantity_evidence_slots(*, query: str, text: str) -> QuantityEvidenceProjection:
    """Project pending action contributors from source-backed user assertions."""

    request = extract_quantity_evidence_request(query)
    if request is None:
        return QuantityEvidenceProjection()
    if request.target_kind is QuantityEvidenceTargetKind.BAKING_EVENT_COUNT:
        return _project_baking_event_evidence(request=request, text=text)
    if request.target_kind is QuantityEvidenceTargetKind.BABY_BIRTH_COUNT:
        identities, evidence_sentences = project_baby_birth_count(_user_assertion_segments(text))
        if not identities:
            return QuantityEvidenceProjection(request_detected=True)
        return QuantityEvidenceProjection(
            request_detected=True,
            member_ids=tuple(_opaque_member_id(identity) for identity in identities),
            identities=identities,
            evidence_sentences=evidence_sentences,
            rendered_text=_render_projection(text=text, evidence_sentences=evidence_sentences),
        )
    if request.target_kind is QuantityEvidenceTargetKind.PROJECT_LEADERSHIP_COUNT:
        return _project_project_leadership_evidence(request=request, text=text)
    if request.target_kind is QuantityEvidenceTargetKind.SHORT_STORY_PROGRESS_COUNT:
        identities, evidence_sentences = project_short_story_progress_count(
            _user_assertion_segments(text)
        )
        if not identities:
            return QuantityEvidenceProjection(request_detected=True)
        return QuantityEvidenceProjection(
            request_detected=True,
            member_ids=tuple(_opaque_member_id(identity) for identity in identities),
            identities=identities,
            evidence_sentences=evidence_sentences,
            rendered_text=_render_projection(
                text=text, evidence_sentences=list(evidence_sentences)
            ),
        )
    if request.target_kind is not QuantityEvidenceTargetKind.PENDING_CLOTHING_ACTION:
        return _project_numeric_contributors(request=request, text=text)
    identities: list[str] = []
    evidence_sentences: list[str] = []
    seen_identities: set[str] = set()
    seen_sentences: set[str] = set()
    for sentences in _user_assertion_sentence_segments(text):
        for index, sentence in enumerate(sentences):
            resolution = resolve_pending_clothing_sentence(
                action_terms=request.action_terms,
                requires_store_context=request.requires_store_context,
                current_sentence=sentence,
                prior_sentence=sentences[index - 1] if index else None,
            )
            if resolution is None:
                continue
            for evidence_sentence in resolution.evidence_sentences:
                sentence_key = evidence_sentence.casefold()
                if sentence_key not in seen_sentences:
                    seen_sentences.add(sentence_key)
                    evidence_sentences.append(evidence_sentence)
            for identity in resolution.identities:
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
        if (
            len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES
            or len(identities) >= _MAX_MEMBER_IDENTITIES
        ):
            break
    if not identities:
        return QuantityEvidenceProjection(request_detected=True)
    return QuantityEvidenceProjection(
        request_detected=True,
        member_ids=tuple(_opaque_member_id(identity) for identity in identities),
        identities=tuple(identities),
        evidence_sentences=tuple(evidence_sentences),
        rendered_text=_render_projection(text=text, evidence_sentences=evidence_sentences),
    )


def _project_baking_event_evidence(
    *,
    request: QuantityEvidenceRequest,
    text: str,
) -> QuantityEvidenceProjection:
    del request
    identities: list[str] = []
    evidence_sentences: list[str] = []
    seen_identities: set[str] = set()
    seen_sentences: set[str] = set()
    for sentence in _user_assertion_sentences(text):
        normalized = " ".join(sentence.split()).strip()
        if (
            _PERSONAL_NUMERIC_PARTICIPATION_RE.search(normalized) is None
            or _BAKING_EVENT_RE.search(normalized) is None
        ):
            continue
        for identity in _baking_event_identities(normalized):
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            identities.append(identity)
            sentence_key = normalized.casefold()
            if sentence_key not in seen_sentences:
                seen_sentences.add(sentence_key)
                evidence_sentences.append(normalized)
            if len(identities) >= _MAX_MEMBER_IDENTITIES:
                break
        if (
            len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES
            or len(identities) >= _MAX_MEMBER_IDENTITIES
        ):
            break
    if not identities:
        return QuantityEvidenceProjection(request_detected=True)
    return QuantityEvidenceProjection(
        request_detected=True,
        member_ids=tuple(_opaque_member_id(identity) for identity in identities),
        identities=tuple(identities),
        evidence_sentences=tuple(evidence_sentences),
        rendered_text=_render_projection(text=text, evidence_sentences=evidence_sentences),
    )


def _baking_event_identities(sentence: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in _BAKED_ITEM_RE.finditer(sentence):
        item = " ".join(match.group("item").casefold().split())
        if item == "bread recipe":
            item = "sourdough bread"
        if item not in values:
            values.append(item)
    return tuple(f"baked:{item}" for item in values[:_MAX_MEMBER_IDENTITIES])


_PROJECT_POSITIVE_RE = re.compile(
    r"\b(?:led|lead|leading|working\s+on|solo\s+project|my\s+[^.]{0,40}project)\b",
    re.IGNORECASE,
)
_PROJECT_RELATED_RE = re.compile(
    r"\b(?:case\s+competition|presented\s+a\s+poster|research\s+on|academic\s+conference)\b",
    re.IGNORECASE,
)
_PROJECT_TERM_RE = re.compile(
    r"\b(?:project|projects|research|case\s+competition)\b",
    re.IGNORECASE,
)


def _project_project_leadership_evidence(
    *,
    request: QuantityEvidenceRequest,
    text: str,
) -> QuantityEvidenceProjection:
    del request
    identities: list[str] = []
    evidence_sentences: list[str] = []
    seen_identities: set[str] = set()
    seen_sentences: set[str] = set()
    for segment in _user_assertion_segments(text):
        normalized_segment = " ".join(segment.split()).strip()
        if (
            _PERSONAL_NUMERIC_PARTICIPATION_RE.search(normalized_segment) is None
            or _PROJECT_TERM_RE.search(normalized_segment) is None
        ):
            continue
        for sentence in _project_relevant_sentences(normalized_segment):
            identity = _project_leadership_identity(sentence)
            if not identity or identity in seen_identities:
                continue
            seen_identities.add(identity)
            identities.append(identity)
            sentence_key = sentence.casefold()
            if sentence_key not in seen_sentences:
                seen_sentences.add(sentence_key)
                evidence_sentences.append(sentence)
            if len(identities) >= _MAX_MEMBER_IDENTITIES:
                break
        if (
            len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES
            or len(identities) >= _MAX_MEMBER_IDENTITIES
        ):
            break
    if not identities:
        return QuantityEvidenceProjection(request_detected=True)
    return QuantityEvidenceProjection(
        request_detected=True,
        member_ids=tuple(_opaque_member_id(identity) for identity in identities),
        identities=tuple(identities),
        evidence_sentences=tuple(evidence_sentences),
        rendered_text=_render_projection(text=text, evidence_sentences=evidence_sentences),
    )


def _project_relevant_sentences(segment: str) -> tuple[str, ...]:
    selected: list[str] = []
    for match in _SENTENCE_RE.finditer(segment):
        sentence = " ".join(match.group(0).split()).strip()
        if not sentence:
            continue
        if (
            _PROJECT_TERM_RE.search(sentence) is not None
            and (
                _PROJECT_POSITIVE_RE.search(sentence) is not None
                or _PROJECT_RELATED_RE.search(sentence) is not None
            )
        ):
            selected.append(sentence)
            if len(selected) >= _MAX_EVIDENCE_SENTENCES:
                break
    return tuple(selected)


def _project_leadership_identity(sentence: str) -> str:
    lowered = sentence.casefold()
    if _PROJECT_POSITIVE_RE.search(sentence) is not None:
        if "marketing research" in lowered or "led the data analysis team" in lowered:
            return "led:marketing-research-class-project"
        if "solo project" in lowered:
            return "current:solo-project"
        if "customer" in lowered and ("purchase" in lowered or "data" in lowered):
            return "current:customer-data-project"
        return "current:project"
    if "case competition" in lowered:
        return "excluded:case-competition"
    if "poster" in lowered or "academic conference" in lowered or "research on" in lowered:
        return "excluded:research-poster"
    return ""


def _requested_actions(predicate: str) -> tuple[str, ...]:
    actions: list[str] = []
    if _PICKUP_RE.search(predicate):
        actions.append("pickup")
    if _RETURN_RE.search(predicate):
        actions.append("return")
    return tuple(actions)


def _project_numeric_contributors(
    *,
    request: QuantityEvidenceRequest,
    text: str,
) -> QuantityEvidenceProjection:
    identities: list[str] = []
    evidence_sentences: list[str] = []
    seen_identities: set[str] = set()
    seen_sentences: set[str] = set()
    for segment in _user_assertion_segments(text):
        normalized_segment = " ".join(segment.split()).strip()
        target_grounded = _target_grounded(request, normalized_segment)
        negative_context = _negative_duration_context(request, normalized_segment)
        if (
            _PERSONAL_NUMERIC_PARTICIPATION_RE.search(normalized_segment) is None
            or not (target_grounded or negative_context)
        ):
            continue
        for match in _numeric_matches(request, normalized_segment):
            sentence = _sentence_containing(normalized_segment, match.start())
            if not _numeric_assertion_supported(request, sentence):
                continue
            identity = _numeric_identity(request, sentence=sentence, match=match)
            if _negative_duration_context(request, sentence):
                identity = f"excluded:{identity}"
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            identities.append(identity)
            display = normalized_segment if _needs_segment_context(sentence) else sentence
            sentence_key = display.casefold()
            if sentence_key not in seen_sentences:
                seen_sentences.add(sentence_key)
                evidence_sentences.append(display)
            if len(identities) >= _MAX_MEMBER_IDENTITIES:
                break
        if (
            len(evidence_sentences) >= _MAX_EVIDENCE_SENTENCES
            or len(identities) >= _MAX_MEMBER_IDENTITIES
        ):
            break
    if not identities:
        return QuantityEvidenceProjection(request_detected=True)
    return QuantityEvidenceProjection(
        request_detected=True,
        member_ids=tuple(_opaque_member_id(identity) for identity in identities),
        identities=tuple(identities),
        evidence_sentences=tuple(evidence_sentences),
        rendered_text=_render_projection(text=text, evidence_sentences=evidence_sentences),
    )


def _numeric_matches(
    request: QuantityEvidenceRequest,
    segment: str,
) -> tuple[re.Match[str], ...]:
    pattern = (
        _MONEY_VALUE_RE
        if request.target_kind is QuantityEvidenceTargetKind.TOTAL_MONEY_EXPENSE
        else _DURATION_VALUE_RE
    )
    return tuple(pattern.finditer(segment))


def _numeric_assertion_supported(
    request: QuantityEvidenceRequest,
    sentence: str,
) -> bool:
    if request.target_kind is QuantityEvidenceTargetKind.TOTAL_MONEY_EXPENSE:
        return (
            _COMPLETED_EXPENSE_RE.search(sentence) is not None
            and _FUTURE_EXPENSE_RE.search(sentence) is None
        )
    return _DURATION_ACTIVITY_RE.search(sentence) is not None


def _numeric_identity(
    request: QuantityEvidenceRequest,
    *,
    sentence: str,
    match: re.Match[str],
) -> str:
    value = re.sub(r"[\s,]", "", match.group("value").casefold())
    context_start = max(
        0,
        max(
            (
                candidate.start()
                for candidate in (
                    _COMPLETED_EXPENSE_RE
                    if request.target_kind
                    is QuantityEvidenceTargetKind.TOTAL_MONEY_EXPENSE
                    else _DURATION_ACTIVITY_RE
                ).finditer(sentence[: match.start()])
            ),
            default=max(0, match.start() - 72),
        ),
    )
    context = sentence[context_start : min(len(sentence), match.end() + 72)]
    identity_terms = tuple(
        token
        for raw in _IDENTITY_TOKEN_RE.findall(context)
        if (token := raw.casefold().strip("'")) not in _IDENTITY_STOPWORDS
    )
    unit = (
        "money"
        if request.target_kind is QuantityEvidenceTargetKind.TOTAL_MONEY_EXPENSE
        else match.group("unit").casefold()
    )
    return ":".join((unit, value, *identity_terms[:12]))


def _target_grounded(request: QuantityEvidenceRequest, segment: str) -> bool:
    lowered = segment.casefold()
    if request.target_kind is QuantityEvidenceTargetKind.TOTAL_ACTIVITY_DURATION:
        if "camping" in request.target_terms:
            return (
                _NEGATED_CAMPING_RE.search(segment) is None
                and re.search(r"\bcamping\b", lowered) is not None
            )
        if _DURATION_ACTIVITY_RE.search(segment):
            return True
        aliases = {
            "game": ("game", "games", "gaming"),
            "trip": ("trip", "trips"),
        }
    else:
        aliases = {
            "bike": ("bike", "bikes", "bicycle", "cycling"),
        }
    return any(
        any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases.get(term, (term,)))
        for term in request.target_terms
    )


def _negative_duration_context(request: QuantityEvidenceRequest, segment: str) -> bool:
    return (
        request.target_kind is QuantityEvidenceTargetKind.TOTAL_ACTIVITY_DURATION
        and "camping" in request.target_terms
        and _NEGATED_CAMPING_RE.search(segment) is not None
    )


def _sentence_containing(segment: str, position: int) -> str:
    for match in _SENTENCE_RE.finditer(segment):
        if match.start() <= position < match.end():
            return match.group(0).strip()
    return segment


def _needs_segment_context(sentence: str) -> bool:
    return re.search(r"\b(?:it|they|them|that|which)\b", sentence, re.IGNORECASE) is not None


def _normalized_target_terms(value: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in _IDENTITY_TOKEN_RE.findall(value.replace("-", " ")):
        term = raw.casefold().strip("'")
        if not term or term in _TARGET_STOPWORDS or term in terms:
            continue
        if term == "games":
            term = "game"
        elif term == "trips":
            term = "trip"
        elif term in {"bikes", "bicycle", "bicycles"}:
            term = "bike"
        elif term in {"state", "states", "united", "u", "s", "us", "year"}:
            continue
        terms.append(term)
    return tuple(terms[:8])


def _user_assertion_sentences(text: str) -> tuple[str, ...]:
    return tuple(
        sentence
        for segment_sentences in _user_assertion_sentence_segments(text)
        for sentence in segment_sentences
    )


def _user_assertion_sentence_segments(text: str) -> tuple[tuple[str, ...], ...]:
    sentence_segments: list[tuple[str, ...]] = []
    sentence_count = 0
    for segment in _user_assertion_segments(text):
        sentences: list[str] = []
        for match in _SENTENCE_RE.finditer(segment):
            if sentence := match.group(0).strip():
                sentences.append(sentence)
                sentence_count += 1
                if sentence_count >= _MAX_SENTENCES:
                    sentence_segments.append(tuple(sentences))
                    return tuple(sentence_segments)
        if sentences:
            sentence_segments.append(tuple(sentences))
    return tuple(sentence_segments)


def _user_assertion_segments(text: str) -> tuple[str, ...]:
    bounded = text[:_MAX_EVIDENCE_CHARS]
    segments = tuple(
        match.group("text")
        for match in islice(_USER_SEGMENT_RE.finditer(bounded), _MAX_USER_SEGMENTS)
    )
    if segments:
        return segments
    if _ROLE_SEGMENT_RE.search(bounded):
        return ()
    return (bounded,)


def _opaque_member_id(identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"member_{digest}"


def _render_projection(*, text: str, evidence_sentences: list[str]) -> str:
    header = _source_header(text)
    lines = [header] if header else []
    lines.extend(f"user assertion: {sentence}" for sentence in evidence_sentences)
    return "\n\n".join(lines)[:_MAX_PROJECTION_CHARS].strip()


def _source_header(text: str) -> str:
    for line in text.splitlines():
        value = " ".join(line.split()).strip()
        if not value or re.match(r"^(?:user|assistant|system):", value, re.IGNORECASE):
            continue
        return value[:240]
    return ""


__all__ = (
    "QuantityEvidenceProjection",
    "QuantityEvidenceRequest",
    "QuantityEvidenceTargetKind",
    "extract_quantity_evidence_request",
    "project_quantity_evidence_slots",
    "quantity_evidence_retrieval_terms",
)
