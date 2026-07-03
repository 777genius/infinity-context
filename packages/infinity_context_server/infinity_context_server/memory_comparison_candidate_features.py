"""Typed candidate evidence features for benchmark retrieval rerank."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infinity_context_server.memory_comparison_candidate_risks import (
    memory_has_broad_summary,
    memory_has_conflict_or_stale,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_relation_support import (
    has_alias_go_by_surface,
    has_date_profile_surface,
    has_employment_occupation_surface,
    has_vehicle_model_surface,
    typed_relation_category_support,
)

_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_TURN_REF_PARTS_RE = re.compile(r"\bD(?P<dialogue>\d+):(?P<turn>\d+)\b")
_SOURCE_SESSION_TURN_RE = re.compile(
    r"(?:^|:)session_(?P<session>\d+):D\d+:(?P<turn>\d+):turn$",
    re.IGNORECASE,
)
_TEXT_SESSION_TURN_RE = re.compile(
    r"\bsession_(?P<session>\d+)\s+(?:turn\s+)?(?P<turn_ref>D\d+:\d+)\b",
    re.IGNORECASE,
)
_TEXT_SESSION_DATE_TURN_RE = re.compile(
    r"\bsession_(?P<session>\d+)\s+date:\s*[^.\n]{0,80}?\s"
    r"(?P<turn_ref>D\d+:\d+)\b",
    re.IGNORECASE,
)
_DIRECT_TURN_SPEAKER_RE = re.compile(
    r"\bD\d+:\d+\s+[A-Z][a-zA-Z0-9_-]{1,40}\s*:"
)
_NEGATION_SURFACE_RE = re.compile(
    r"\b(?:no longer|not|never|without|didn't|doesn't|don't|hadn't|wasn't|"
    r"isn't|won't|can't|couldn't)\b",
    re.IGNORECASE,
)
_CURRENTNESS_SURFACE_RE = re.compile(
    r"\b(?:currently|current|now|these days|still|ongoing|recently|today|lately)\b",
    re.IGNORECASE,
)
_STALE_SURFACE_RE = re.compile(
    r"\b(?:used to|previously|formerly|before|back then|in the past|prior|"
    r"earlier|no longer|changed|switched|instead)\b",
    re.IGNORECASE,
)
_CONTRAST_SURFACE_RE = re.compile(
    r"\b(?:but|however|although|though|instead|rather|whereas|while|"
    r"no longer|changed|without)\b",
    re.IGNORECASE,
)
_NUMBER_WORD_RE = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
)
_DURATION_EVIDENCE_RE = re.compile(
    rf"\b(?:(?:\d+|{_NUMBER_WORD_RE})\s+"
    r"(?:days?|weeks?|months?|years?)|"
    rf"(?:for|over|about|around|nearly|almost|roughly|approximately)\s+"
    rf"(?:\d+|{_NUMBER_WORD_RE})\s*(?:days?|weeks?|months?|years?)|"
    r"since\s+(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_RELATIVE_TIME_EVIDENCE_RE = re.compile(
    r"\b(?:today|yesterday|tomorrow|ago|recently|recent|lately|"
    r"last|next|previously|previous|earlier|later|back then|these days)\b",
    re.IGNORECASE,
)
_EXPLICIT_TIME_EVIDENCE_RE = re.compile(
    r"\b(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|(?:19|20)\d{2}|"
    r"date:|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)
_EXPLICIT_TIME_CONTENT_RE = re.compile(
    r"\b(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|(?:19|20)\d{2}|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    re.IGNORECASE,
)
_TEMPORAL_SEQUENCE_EVIDENCE_RE = re.compile(
    r"\b(?:before|after|during|then|following|subsequent|subsequently|"
    r"previously|earlier|later|prior)\b",
    re.IGNORECASE,
)
_INTENT_RELATION_CATEGORY_ORDER = (
    "causal",
    "contrast",
    "registration_event",
    "symbolic_meaning",
    "participation_event",
    "emotion_response",
    "communication",
    "exchange",
    "favorite_preference",
    "preference",
    "status_profile",
    "activity",
    "activity_profile",
    "current_goal",
    "location_transition",
    "support_goal",
    "identity_profile",
    "commitment_profile",
    "contact_profile",
    "diet_profile",
    "education_profile",
    "employment_profile",
    "age_profile",
    "alias_profile",
    "date_profile",
    "health_profile",
    "pet_profile",
    "skill_profile",
    "vehicle_profile",
)


@dataclass(frozen=True)
class CandidateEvidenceFeatures:
    """Feature snapshot for a retrieved memory candidate."""

    memory_terms: frozenset[str]
    overlap_terms: tuple[str, ...]
    relation_hits: tuple[str, ...]
    relation_categories: tuple[str, ...]
    relation_category_hits: tuple[str, ...]
    relation_category_coverage_ratio: float
    entity_hits: tuple[str, ...]
    speaker_hits: tuple[str, ...]
    relation_coverage_ratio: float
    high_signal_relation_hit_count: int
    direct_speaker_turn: bool
    broad_summary: bool
    focused_turn_surface: bool
    focused_turn_score: float
    time_intent_kind: str
    has_temporal_surface: bool
    has_sequence_surface: bool
    has_duration_surface: bool
    has_relative_time_surface: bool
    has_explicit_time_surface: bool
    has_explicit_time_content_surface: bool
    has_temporal_sequence_surface: bool
    has_preference_evidence: bool
    has_visual_evidence: bool
    source_ref_count: int
    source_turn_refs: tuple[str, ...]
    source_turn_span: int
    turn_ref_count: int
    source_ref_density: float
    source_locality_score: float
    source_locality_reason_codes: tuple[str, ...]
    source_type: str
    source_types: tuple[str, ...]
    retrieval_sources: tuple[str, ...]
    query_roles: tuple[str, ...]
    bridge_query_hit: bool
    duplicate_key: str
    source_ref_dedupe_key: str
    conflict_or_stale: bool
    negation_surface: bool
    currentness_surface: bool
    stale_surface: bool
    contrast_surface: bool
    answerability_score: float
    answerability_reason_codes: tuple[str, ...]
    query_has_entities: bool
    is_temporal_query: bool
    is_preference_query: bool
    is_contrast_query: bool
    has_visual_terms: bool
    has_multi_hop_markers: bool

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": "candidate_evidence_features.v1",
            "direct_speaker_turn": self.direct_speaker_turn,
            "broad_summary": self.broad_summary,
            "focused_turn_surface": self.focused_turn_surface,
            "focused_turn_score": round(self.focused_turn_score, 6),
            "time_intent_kind": self.time_intent_kind,
            "source_ref_count": self.source_ref_count,
            "source_turn_refs": list(self.source_turn_refs),
            "source_turn_span": self.source_turn_span,
            "turn_ref_count": self.turn_ref_count,
            "source_ref_density": round(self.source_ref_density, 6),
            "source_locality_score": round(self.source_locality_score, 6),
            "source_locality_reason_codes": list(
                self.source_locality_reason_codes
            ),
            "source_type": self.source_type,
            "source_types": list(self.source_types),
            "retrieval_sources": list(self.retrieval_sources),
            "query_roles": list(self.query_roles),
            "bridge_query_hit": self.bridge_query_hit,
            "duplicate_key": self.duplicate_key,
            "source_ref_dedupe_key": self.source_ref_dedupe_key,
            "conflict_or_stale": self.conflict_or_stale,
            "negation_surface": self.negation_surface,
            "currentness_surface": self.currentness_surface,
            "stale_surface": self.stale_surface,
            "contrast_surface": self.contrast_surface,
            "answerability_score": round(self.answerability_score, 6),
            "answerability_reason_codes": list(self.answerability_reason_codes),
            "relation_coverage_ratio": round(self.relation_coverage_ratio, 6),
            "relation_categories": list(self.relation_categories),
            "relation_category_hits": list(self.relation_category_hits),
            "relation_category_coverage_ratio": round(
                self.relation_category_coverage_ratio,
                6,
            ),
            "high_signal_relation_hit_count": self.high_signal_relation_hit_count,
            "overlap_terms": list(self.overlap_terms),
            "relation_hits": list(self.relation_hits),
            "entity_hits": list(self.entity_hits),
            "speaker_hits": list(self.speaker_hits),
            "is_contrast_query": self.is_contrast_query,
            "has_temporal_surface": self.has_temporal_surface,
            "has_sequence_surface": self.has_sequence_surface,
            "has_duration_surface": self.has_duration_surface,
            "has_relative_time_surface": self.has_relative_time_surface,
            "has_explicit_time_surface": self.has_explicit_time_surface,
            "has_explicit_time_content_surface": (
                self.has_explicit_time_content_surface
            ),
            "has_temporal_sequence_surface": self.has_temporal_sequence_surface,
            "has_preference_evidence": self.has_preference_evidence,
            "has_visual_evidence": self.has_visual_evidence,
        }


def build_candidate_evidence_features(
    memory: RetrievedMemory,
    *,
    memory_terms: set[str],
    query_terms: Sequence[str],
    relation_terms: Sequence[str],
    relation_variant_terms: Sequence[str],
    relation_category_terms: Mapping[str, Sequence[str]] | None = None,
    entities: Sequence[str],
    entity_hits: Sequence[str],
    speaker_hits: Sequence[str],
    high_signal_relation_terms: set[str],
    is_temporal_query: bool,
    is_preference_query: bool,
    has_visual_terms: bool,
    has_multi_hop_markers: bool,
    has_temporal_surface: bool,
    has_sequence_surface: bool,
    has_preference_evidence: bool,
    has_visual_evidence: bool,
    has_focused_turn_surface: bool,
    is_contrast_query: bool = False,
    time_intent_kind: str = "",
) -> CandidateEvidenceFeatures:
    overlap_terms = tuple(term for term in query_terms if term in memory_terms)
    relation_hits = tuple(
        dict.fromkeys(
            term
            for term in (*relation_terms, *relation_variant_terms)
            if term in memory_terms
        )
    )
    text = memory.text or ""
    relation_category_hits = _relation_category_hits(
        memory_terms,
        relation_category_terms or {},
        query_terms=query_terms,
        memory_text=text,
    )
    high_signal_hit_count = sum(
        1 for term in relation_hits if term in high_signal_relation_terms
    )
    contrast_features = _contrast_features(text)
    temporal_features = _temporal_evidence_features(text)
    source_refs = tuple(str(ref) for ref in memory.source_refs if str(ref).strip())
    text_turn_refs = tuple(dict.fromkeys(_TURN_REF_RE.findall(text)))
    text_session_turn_refs = _text_session_turn_refs(text)
    source_turn_refs = _source_turn_refs(source_refs)
    turn_refs = tuple(dict.fromkeys((*text_turn_refs, *source_turn_refs)))
    source_turn_span = _source_turn_span(
        turn_refs,
        source_refs=source_refs,
        text_session_turn_refs=text_session_turn_refs,
    )
    broad_summary = memory_has_broad_summary(memory)
    direct_speaker_turn = bool(_DIRECT_TURN_SPEAKER_RE.search(text)) and not broad_summary
    source_locality_score, source_locality_reasons = _source_locality(
        source_ref_count=len(source_refs),
        turn_ref_count=len(turn_refs),
        source_turn_span=source_turn_span,
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
    )
    focused_turn_score = (
        0.08
        if speaker_hits
        and relation_hits
        and not has_visual_terms
        and has_focused_turn_surface
        else 0.0
    )
    query_relation_surface_count = len(
        tuple(dict.fromkeys((*relation_terms, *relation_variant_terms)))
    )
    relation_categories = tuple((relation_category_terms or {}).keys())
    conflict_or_stale = memory_has_conflict_or_stale(memory)
    query_roles = _query_roles(memory)
    answerability_score, answerability_reasons = _answerability(
        entity_count=len(tuple(dict.fromkeys(entities))),
        entity_hit_count=len(tuple(dict.fromkeys((*entity_hits, *speaker_hits)))),
        relation_hit_count=len(relation_hits),
        relation_surface_count=query_relation_surface_count,
        overlap_count=len(overlap_terms),
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
        source_ref_count=len(source_refs),
        turn_ref_count=len(turn_refs),
        source_locality_score=source_locality_score,
        conflict_or_stale=conflict_or_stale,
        is_temporal_query=is_temporal_query,
        time_intent_kind=time_intent_kind,
        has_temporal_surface=has_temporal_surface,
        has_sequence_surface=has_sequence_surface,
        has_duration_surface=temporal_features["has_duration_surface"],
        has_relative_time_surface=temporal_features["has_relative_time_surface"],
        has_explicit_time_surface=temporal_features["has_explicit_time_surface"],
        has_explicit_time_content_surface=temporal_features[
            "has_explicit_time_content_surface"
        ],
        has_temporal_sequence_surface=temporal_features[
            "has_temporal_sequence_surface"
        ],
        is_preference_query=is_preference_query,
        has_preference_evidence=has_preference_evidence,
        is_contrast_query=is_contrast_query,
        negation_surface=contrast_features["negation_surface"],
        currentness_surface=contrast_features["currentness_surface"],
        stale_surface=contrast_features["stale_surface"],
        contrast_surface=contrast_features["contrast_surface"],
        has_visual_terms=has_visual_terms,
        has_visual_evidence=has_visual_evidence,
        has_multi_hop_markers=has_multi_hop_markers,
        relation_categories=relation_categories,
        relation_category_hits=relation_category_hits,
    )
    source_type = _source_type(memory)
    return CandidateEvidenceFeatures(
        memory_terms=frozenset(memory_terms),
        overlap_terms=overlap_terms,
        relation_hits=relation_hits,
        relation_categories=relation_categories,
        relation_category_hits=relation_category_hits,
        relation_category_coverage_ratio=_ratio(
            len(relation_category_hits),
            len(relation_category_terms or {}),
        ),
        entity_hits=tuple(entity_hits),
        speaker_hits=tuple(speaker_hits),
        relation_coverage_ratio=_ratio(
            len(relation_hits),
            query_relation_surface_count,
        ),
        high_signal_relation_hit_count=high_signal_hit_count,
        direct_speaker_turn=direct_speaker_turn,
        broad_summary=broad_summary,
        focused_turn_surface=has_focused_turn_surface,
        focused_turn_score=focused_turn_score,
        time_intent_kind=time_intent_kind,
        has_temporal_surface=has_temporal_surface,
        has_sequence_surface=has_sequence_surface,
        has_duration_surface=temporal_features["has_duration_surface"],
        has_relative_time_surface=temporal_features["has_relative_time_surface"],
        has_explicit_time_surface=temporal_features["has_explicit_time_surface"],
        has_explicit_time_content_surface=temporal_features[
            "has_explicit_time_content_surface"
        ],
        has_temporal_sequence_surface=temporal_features[
            "has_temporal_sequence_surface"
        ],
        has_preference_evidence=has_preference_evidence,
        has_visual_evidence=has_visual_evidence,
        source_ref_count=len(source_refs),
        source_turn_refs=source_turn_refs,
        source_turn_span=source_turn_span,
        turn_ref_count=len(turn_refs),
        source_ref_density=_ratio(len(source_refs), max(1, len(turn_refs))),
        source_locality_score=source_locality_score,
        source_locality_reason_codes=source_locality_reasons,
        source_type=source_type,
        source_types=_source_types(memory, source_type=source_type),
        retrieval_sources=_retrieval_sources(memory),
        query_roles=query_roles,
        bridge_query_hit=_bridge_query_hit(memory, query_roles),
        duplicate_key=_duplicate_key(memory, source_refs),
        source_ref_dedupe_key=_source_ref_dedupe_key(
            source_refs,
            text_turn_refs=text_turn_refs,
            text_session_turn_refs=text_session_turn_refs,
        ),
        conflict_or_stale=conflict_or_stale,
        negation_surface=contrast_features["negation_surface"],
        currentness_surface=contrast_features["currentness_surface"],
        stale_surface=contrast_features["stale_surface"],
        contrast_surface=contrast_features["contrast_surface"],
        answerability_score=answerability_score,
        answerability_reason_codes=answerability_reasons,
        query_has_entities=bool(entities),
        is_temporal_query=is_temporal_query,
        is_preference_query=is_preference_query,
        is_contrast_query=is_contrast_query,
        has_visual_terms=has_visual_terms,
        has_multi_hop_markers=has_multi_hop_markers,
    )


def _contrast_features(text: str) -> dict[str, bool]:
    negation_surface = bool(_NEGATION_SURFACE_RE.search(text))
    currentness_surface = bool(_CURRENTNESS_SURFACE_RE.search(text))
    stale_surface = bool(_STALE_SURFACE_RE.search(text))
    contrast_surface = bool(_CONTRAST_SURFACE_RE.search(text)) or (
        negation_surface and stale_surface
    )
    return {
        "negation_surface": negation_surface,
        "currentness_surface": currentness_surface,
        "stale_surface": stale_surface,
        "contrast_surface": contrast_surface,
    }


def _temporal_evidence_features(text: str) -> dict[str, bool]:
    content_text = _evidence_content_text(text)
    duration_surface = bool(_DURATION_EVIDENCE_RE.search(text))
    relative_time_surface = bool(_RELATIVE_TIME_EVIDENCE_RE.search(text))
    explicit_time_surface = bool(_EXPLICIT_TIME_EVIDENCE_RE.search(text))
    explicit_time_content_surface = bool(_EXPLICIT_TIME_CONTENT_RE.search(content_text))
    temporal_sequence_surface = bool(_TEMPORAL_SEQUENCE_EVIDENCE_RE.search(text))
    return {
        "has_duration_surface": duration_surface,
        "has_relative_time_surface": relative_time_surface,
        "has_explicit_time_surface": explicit_time_surface,
        "has_explicit_time_content_surface": explicit_time_content_surface,
        "has_temporal_sequence_surface": temporal_sequence_surface,
    }


def _evidence_content_text(text: str) -> str:
    match = re.search(
        r"\bD\d+:\d+\s+[A-Z][a-zA-Z0-9_-]{1,40}\s*:\s*",
        text,
    )
    if match:
        return text[match.end() :]
    turn_matches = tuple(_TURN_REF_RE.finditer(text))
    if not turn_matches:
        return text
    return text[turn_matches[-1].end() :]


def _relation_category_hits(
    memory_terms: set[str],
    relation_category_terms: Mapping[str, Sequence[str]],
    *,
    query_terms: Sequence[str],
    memory_text: str = "",
) -> tuple[str, ...]:
    hits: list[str] = []
    query_term_set = set(query_terms)
    for category, terms in relation_category_terms.items():
        term_values = tuple(str(term) for term in terms if str(term).strip())
        typed_support = typed_relation_category_support(
            str(category),
            memory_terms,
            memory_text=memory_text,
        )
        if typed_support is not None:
            if typed_support and _typed_category_has_query_grounding(
                category=str(category),
                memory_terms=memory_terms,
                term_values=term_values,
                memory_text=memory_text,
            ):
                hits.append(str(category))
            continue
        grounding_terms = tuple(term for term in term_values if term not in query_term_set)
        terms_to_match = grounding_terms or term_values
        if any(term in memory_terms for term in terms_to_match):
            hits.append(str(category))
    return tuple(dict.fromkeys(hits))


def _typed_category_has_query_grounding(
    *,
    category: str,
    memory_terms: set[str],
    term_values: Sequence[str],
    memory_text: str = "",
) -> bool:
    if category == "education_profile" and _has_named_school_surface(memory_text):
        return True
    if category == "employment_profile" and has_employment_occupation_surface(
        memory_text
    ):
        return True
    if category == "vehicle_profile" and has_vehicle_model_surface(memory_text):
        return True
    if category == "alias_profile" and has_alias_go_by_surface(memory_text):
        return True
    if category == "date_profile" and has_date_profile_surface(memory_text):
        return True
    if category not in {
        "communication",
        "activity_profile",
        "age_profile",
        "alias_profile",
        "commitment_profile",
        "contact_profile",
        "date_profile",
        "diet_profile",
        "education_profile",
        "employment_profile",
        "exchange",
        "favorite_preference",
        "health_profile",
        "pet_profile",
        "skill_profile",
        "status_profile",
        "vehicle_profile",
    }:
        return True
    return any(term in memory_terms for term in term_values)


def _has_named_school_surface(memory_text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:go|goes|went)\s+to\s+[A-Z][a-zA-Z0-9_-]+"
            r"(?:\s+[A-Z][a-zA-Z0-9_-]+){0,3}\b",
            memory_text,
        )
    )


def _answerability(
    *,
    entity_count: int,
    entity_hit_count: int,
    relation_hit_count: int,
    relation_surface_count: int,
    overlap_count: int,
    direct_speaker_turn: bool,
    broad_summary: bool,
    source_ref_count: int,
    turn_ref_count: int,
    source_locality_score: float,
    conflict_or_stale: bool,
    is_temporal_query: bool,
    time_intent_kind: str,
    has_temporal_surface: bool,
    has_sequence_surface: bool,
    has_duration_surface: bool,
    has_relative_time_surface: bool,
    has_explicit_time_surface: bool,
    has_explicit_time_content_surface: bool,
    has_temporal_sequence_surface: bool,
    is_preference_query: bool,
    has_preference_evidence: bool,
    is_contrast_query: bool,
    negation_surface: bool,
    currentness_surface: bool,
    stale_surface: bool,
    contrast_surface: bool,
    has_visual_terms: bool,
    has_visual_evidence: bool,
    has_multi_hop_markers: bool,
    relation_categories: Sequence[str],
    relation_category_hits: Sequence[str],
) -> tuple[float, tuple[str, ...]]:
    entity_score = (
        1.0
        if entity_count == 0
        else min(1.0, entity_hit_count / max(1, entity_count))
    )
    relation_score = (
        1.0
        if relation_surface_count == 0
        else min(1.0, relation_hit_count / min(4, max(1, relation_surface_count)))
    )
    provenance_score = _provenance_answerability_score(
        source_locality_score=source_locality_score,
    )
    intent_score, intent_reason_codes = _intent_answerability(
        is_temporal_query=is_temporal_query,
        time_intent_kind=time_intent_kind,
        has_temporal_surface=has_temporal_surface,
        has_sequence_surface=has_sequence_surface,
        has_duration_surface=has_duration_surface,
        has_relative_time_surface=has_relative_time_surface,
        has_explicit_time_surface=has_explicit_time_surface,
        has_explicit_time_content_surface=has_explicit_time_content_surface,
        has_temporal_sequence_surface=has_temporal_sequence_surface,
        is_preference_query=is_preference_query,
        has_preference_evidence=has_preference_evidence,
        is_contrast_query=is_contrast_query,
        negation_surface=negation_surface,
        currentness_surface=currentness_surface,
        stale_surface=stale_surface,
        contrast_surface=contrast_surface,
        has_visual_terms=has_visual_terms,
        has_visual_evidence=has_visual_evidence,
        has_multi_hop_markers=has_multi_hop_markers,
        relation_hit_count=relation_hit_count,
        overlap_count=overlap_count,
        relation_categories=relation_categories,
        relation_category_hits=relation_category_hits,
    )
    score = (
        (0.32 * entity_score)
        + (0.34 * relation_score)
        + (0.18 * provenance_score)
        + (0.16 * intent_score)
    )
    if broad_summary:
        score -= 0.1
    if conflict_or_stale:
        score -= 0.16
    rounded_score = round(max(0.0, min(1.0, score)), 6)
    return rounded_score, _answerability_reasons(
        answerability_score=rounded_score,
        entity_score=entity_score,
        relation_score=relation_score,
        provenance_score=provenance_score,
        intent_score=intent_score,
        intent_reason_codes=intent_reason_codes,
        broad_summary=broad_summary,
        conflict_or_stale=conflict_or_stale,
    )


def _provenance_answerability_score(
    *,
    source_locality_score: float,
) -> float:
    return max(0.0, min(1.0, source_locality_score))


def _source_locality(
    *,
    source_ref_count: int,
    turn_ref_count: int,
    source_turn_span: int,
    direct_speaker_turn: bool,
    broad_summary: bool,
) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []
    if direct_speaker_turn and 0 < turn_ref_count <= 2:
        score = 1.0
        reasons.append("direct_localized_turn")
    elif not broad_summary and 1 < turn_ref_count <= 3 and 0 < source_turn_span <= 3:
        score = 0.95
        reasons.append("proximate_source_turn_refs")
    elif turn_ref_count == 1 and source_ref_count <= 3:
        score = 0.9
        reasons.append("localized_turn_refs")
    elif 0 < turn_ref_count <= 5:
        score = 0.65
        reasons.append("multi_turn_refs")
    elif turn_ref_count > 5:
        score = 0.35
        reasons.append("broad_turn_refs")
    elif source_ref_count == 1:
        score = 0.45
        reasons.append("single_source_ref")
    elif source_ref_count > 1:
        score = 0.3
        reasons.append("broad_source_refs")
    else:
        score = 0.0
        reasons.append("missing_source_refs")

    if broad_summary:
        score = min(score, 0.45)
        reasons.append("broad_summary_locality_cap")
    return round(score, 6), tuple(reasons)


def _intent_answerability(
    *,
    is_temporal_query: bool,
    time_intent_kind: str,
    has_temporal_surface: bool,
    has_sequence_surface: bool,
    has_duration_surface: bool,
    has_relative_time_surface: bool,
    has_explicit_time_surface: bool,
    has_explicit_time_content_surface: bool,
    has_temporal_sequence_surface: bool,
    is_preference_query: bool,
    has_preference_evidence: bool,
    is_contrast_query: bool,
    negation_surface: bool,
    currentness_surface: bool,
    stale_surface: bool,
    contrast_surface: bool,
    has_visual_terms: bool,
    has_visual_evidence: bool,
    has_multi_hop_markers: bool,
    relation_hit_count: int,
    overlap_count: int,
    relation_categories: Sequence[str],
    relation_category_hits: Sequence[str],
) -> tuple[float, tuple[str, ...]]:
    scores: list[float] = []
    reasons: list[str] = []
    category_set = set(relation_categories)
    category_hit_set = set(relation_category_hits)
    has_non_preference_category_hit = bool(category_hit_set - {"preference"})
    if is_temporal_query:
        score, reason = _temporal_intent_answerability(
            time_intent_kind=time_intent_kind,
            has_temporal_surface=has_temporal_surface,
            has_sequence_surface=has_sequence_surface,
            has_duration_surface=has_duration_surface,
            has_relative_time_surface=has_relative_time_surface,
            has_explicit_time_surface=has_explicit_time_surface,
            has_explicit_time_content_surface=has_explicit_time_content_surface,
            has_temporal_sequence_surface=has_temporal_sequence_surface,
        )
        scores.append(score)
        reasons.append(reason)
    if is_preference_query and not has_non_preference_category_hit:
        scores.append(1.0 if has_preference_evidence else 0.0)
        reasons.append(
            "preference_evidence" if has_preference_evidence else "missing_preference_evidence"
        )
    if is_contrast_query:
        has_old_new_surface = currentness_surface and stale_surface
        has_explicit_contrast = contrast_surface and (
            currentness_surface or stale_surface or negation_surface
        )
        if has_explicit_contrast or has_old_new_surface:
            scores.append(1.0)
            reasons.append("contrast_evidence")
        elif contrast_surface:
            scores.append(0.75)
            reasons.append("contrast_evidence_partial")
        elif currentness_surface or stale_surface:
            scores.append(0.35)
            reasons.append("current_or_stale_surface_only")
        else:
            scores.append(0.0)
            reasons.append("missing_contrast_evidence")
    if has_visual_terms:
        scores.append(1.0 if has_visual_evidence else 0.0)
        reasons.append("visual_evidence" if has_visual_evidence else "missing_visual_evidence")
    for category in _INTENT_RELATION_CATEGORY_ORDER:
        if category not in category_set:
            continue
        if category in category_hit_set:
            scores.append(1.0)
            reasons.append(f"{category}_evidence")
        elif (
            category == "preference"
            and has_non_preference_category_hit
            or category in {"identity_profile", "support_goal"}
            and category_hit_set
        ):
            continue
        else:
            scores.append(0.2)
            reasons.append(f"missing_{category}_evidence")
    if has_multi_hop_markers:
        scores.append(1.0 if relation_hit_count >= 2 and overlap_count >= 2 else 0.35)
        reasons.append(
            "multi_hop_relation_evidence"
            if relation_hit_count >= 2 and overlap_count >= 2
            else "multi_hop_relation_evidence_partial"
        )
    if not scores:
        return 1.0, ()
    return sum(scores) / len(scores), tuple(dict.fromkeys(reasons))


def _temporal_intent_answerability(
    *,
    time_intent_kind: str,
    has_temporal_surface: bool,
    has_sequence_surface: bool,
    has_duration_surface: bool,
    has_relative_time_surface: bool,
    has_explicit_time_surface: bool,
    has_explicit_time_content_surface: bool,
    has_temporal_sequence_surface: bool,
) -> tuple[float, str]:
    generic_temporal = (
        has_duration_surface
        or has_relative_time_surface
        or has_explicit_time_content_surface
        or has_temporal_sequence_surface
    )
    if time_intent_kind == "duration":
        if has_duration_surface:
            return 1.0, "duration_temporal_evidence"
        return (0.45, "duration_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_duration_temporal_evidence",
        )
    if time_intent_kind == "relative_time":
        if has_relative_time_surface:
            return 1.0, "relative_temporal_evidence"
        return (0.5, "relative_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_relative_temporal_evidence",
        )
    if time_intent_kind == "explicit_time":
        if has_explicit_time_content_surface:
            return 1.0, "explicit_temporal_evidence"
        return (0.5, "explicit_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_explicit_temporal_evidence",
        )
    if time_intent_kind == "temporal_sequence":
        if has_temporal_sequence_surface:
            return 1.0, "sequence_temporal_evidence"
        return (0.45, "sequence_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_sequence_temporal_evidence",
        )
    if generic_temporal:
        return 1.0, "generic_temporal_evidence"
    return 0.0, "missing_temporal_evidence"


def _answerability_reasons(
    *,
    answerability_score: float,
    entity_score: float,
    relation_score: float,
    provenance_score: float,
    intent_score: float,
    intent_reason_codes: Sequence[str],
    broad_summary: bool,
    conflict_or_stale: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if entity_score >= 1.0:
        reasons.append("entity_satisfied")
    elif entity_score > 0:
        reasons.append("entity_partial")
    if relation_score >= 1.0:
        reasons.append("relation_satisfied")
    elif relation_score > 0:
        reasons.append("relation_partial")
    if provenance_score >= 1.0:
        reasons.append("direct_provenance")
    elif provenance_score > 0:
        reasons.append("source_provenance")
    if intent_score >= 1.0:
        reasons.append("intent_satisfied")
    elif intent_score > 0:
        reasons.append("intent_partial")
    reasons.extend(intent_reason_codes)
    if broad_summary:
        reasons.append("broad_summary_penalty")
    if conflict_or_stale:
        reasons.append("conflict_or_stale_penalty")
    if answerability_score >= 0.8:
        reasons.append("high_answerability")
    elif answerability_score >= 0.55:
        reasons.append("medium_answerability")
    else:
        reasons.append("low_answerability")
    return tuple(reasons)


def _source_type(memory: RetrievedMemory) -> str:
    value = memory.metadata.get("item_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _source_types(memory: RetrievedMemory, *, source_type: str) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    return tuple(
        dict.fromkeys(
            (
                *(source for source in (source_type,) if source != "unknown"),
                *_string_sequence(fusion.get("source_types")),
            )
        )
    )


def _retrieval_sources(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    sources = _string_sequence(diagnostics.get("retrieval_sources"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    return tuple(
        dict.fromkeys(
            (
                *sources,
                *_string_sequence(fusion.get("retrieval_sources")),
            )
        )
    )


def _query_roles(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    roles = _string_sequence(diagnostics.get("benchmark_query_roles"))
    if roles:
        return roles
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    return _string_sequence(fusion.get("query_roles"))


def _bridge_query_hit(
    memory: RetrievedMemory,
    query_roles: Sequence[str],
) -> bool:
    if "multi_hop_bridge" in set(query_roles):
        return True
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    if diagnostics.get("benchmark_bridge_query_hit") is True:
        return True
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    return fusion.get("bridge_query_hit") is True


def _duplicate_key(memory: RetrievedMemory, source_refs: Sequence[str]) -> str:
    if source_refs:
        return "source_refs:" + "|".join(sorted(source_refs))
    if memory.item_id:
        return f"item_id:{memory.item_id}"
    digest = hashlib.sha1((memory.text or "").encode("utf-8")).hexdigest()[:16]
    return f"text_sha1:{digest}"


def _source_ref_dedupe_key(
    source_refs: Sequence[str],
    *,
    text_turn_refs: Sequence[str] = (),
    text_session_turn_refs: Sequence[str] = (),
) -> str:
    source_turn_refs = _source_turn_refs(source_refs)
    source_session_turn_refs = _source_session_turn_refs(source_refs)
    if _has_multiple_sessions(source_session_turn_refs) and len(source_session_turn_refs) <= 3:
        return "source_session_turn_refs:" + "|".join(sorted(source_session_turn_refs))
    if (
        not source_turn_refs
        and _has_multiple_sessions(text_session_turn_refs)
        and len(text_session_turn_refs) <= 3
    ):
        return "source_session_turn_refs:" + "|".join(sorted(text_session_turn_refs))
    turn_refs = source_turn_refs or tuple(
        dict.fromkeys(ref for ref in text_turn_refs if _TURN_REF_RE.fullmatch(str(ref)))
    )
    if not turn_refs or len(turn_refs) > 3:
        return ""
    return "source_turn_refs:" + "|".join(sorted(turn_refs))


def _source_turn_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            ref
            for source_ref in source_refs
            for ref in _TURN_REF_RE.findall(str(source_ref))
        )
    )


def _source_session_turn_refs(source_refs: Sequence[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for source_ref in source_refs:
        match = _SOURCE_SESSION_TURN_RE.search(str(source_ref))
        if match is None:
            continue
        if turn_match := _TURN_REF_RE.search(str(source_ref)):
            refs.append(f"session_{match.group('session')}:{turn_match.group(0)}")
    return tuple(dict.fromkeys(refs))


def _text_session_turn_refs(text: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            f"session_{match.group('session')}:{match.group('turn_ref')}"
            for pattern in (_TEXT_SESSION_TURN_RE, _TEXT_SESSION_DATE_TURN_RE)
            for match in pattern.finditer(text)
        )
    )


def _source_turn_span(
    turn_refs: Sequence[str],
    *,
    source_refs: Sequence[str] = (),
    text_session_turn_refs: Sequence[str] = (),
) -> int:
    if _cross_session_exact_turn_refs(
        source_refs,
        text_session_turn_refs=text_session_turn_refs,
    ):
        return 0
    parsed = tuple(_parse_turn_ref(ref) for ref in turn_refs)
    parsed = tuple(ref for ref in parsed if ref is not None)
    if len(parsed) <= 1:
        return 0
    by_dialogue: dict[int, list[int]] = {}
    for dialogue, turn in parsed:
        by_dialogue.setdefault(dialogue, []).append(turn)
    if len(by_dialogue) != 1:
        return 0
    turns = tuple(turn for values in by_dialogue.values() for turn in values)
    return max(turns) - min(turns) + 1


def _cross_session_exact_turn_refs(
    source_refs: Sequence[str],
    *,
    text_session_turn_refs: Sequence[str] = (),
) -> bool:
    return _has_multiple_sessions(
        (*_source_session_turn_refs(source_refs), *text_session_turn_refs)
    )


def _has_multiple_sessions(session_turn_refs: Sequence[str]) -> bool:
    sessions = {
        match.group("session")
        for session_turn_ref in session_turn_refs
        if (
            match := re.search(
                r"\bsession_(?P<session>\d+):D\d+:\d+\b",
                str(session_turn_ref),
                re.IGNORECASE,
            )
        )
    }
    return len(sessions) > 1


def _parse_turn_ref(ref: str) -> tuple[int, int] | None:
    match = _TURN_REF_PARTS_RE.search(str(ref))
    if match is None:
        return None
    return int(match.group("dialogue")), int(match.group("turn"))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _string_sequence(value: object) -> tuple[str, ...]:
    return tuple(str(item) for item in _sequence(value) if str(item).strip())
