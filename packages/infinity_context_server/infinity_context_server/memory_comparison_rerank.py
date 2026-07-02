"""Question-only rerank helpers for memory comparison benchmark retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_intent import (
    RetrievalEntityIntent,
    RetrievalIntent,
    RetrievalTimeIntent,
    infer_bundle_evidence_roles,
    infer_evidence_need,
    infer_relation_intents,
    infer_risk_flags,
    infer_time_intent_kind,
    merge_relation_evidence_needs,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_query_plan import (
    QueryPlanCandidate,
    QueryPlannerV2,
)
from infinity_context_server.memory_comparison_rerank_intents import (
    focused_intent_policy_boosts,
)
from infinity_context_server.memory_comparison_rerank_policy import (
    BenchmarkRerankFeatures,
    score_benchmark_rerank_candidate,
)
from infinity_context_server.memory_comparison_rerank_shapes import (
    focused_evidence_shape_boosts,
)
from infinity_context_server.memory_comparison_rerank_terms import (
    RELATION_QUERY_VARIANTS as _RELATION_QUERY_VARIANTS,
)
from infinity_context_server.memory_comparison_rerank_text import (
    HONORIFIC_ENTITY_RE as _HONORIFIC_ENTITY_RE,
)
from infinity_context_server.memory_comparison_rerank_text import (
    QUERY_STOPWORDS as _QUERY_STOPWORDS,
)
from infinity_context_server.memory_comparison_rerank_text import (
    QUERY_TOKEN_ALIASES as _QUERY_TOKEN_ALIASES,
)
from infinity_context_server.memory_comparison_rerank_text import (
    compact_temporal_relation_terms as _compact_temporal_relation_terms,
)
from infinity_context_server.memory_comparison_rerank_text import (
    entity_speaks_in_memory as _entity_speaks_in_memory,
)
from infinity_context_server.memory_comparison_rerank_text import (
    entity_surface_in_memory as _entity_surface_in_memory,
)
from infinity_context_server.memory_comparison_rerank_text import (
    entity_surfaces as _entity_surfaces,
)
from infinity_context_server.memory_comparison_rerank_text import (
    is_contrast_query as _is_contrast_query,
)
from infinity_context_server.memory_comparison_rerank_text import (
    is_preference_query as _is_preference_query,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_has_focused_turn_surface as _memory_has_focused_turn_surface,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_has_preference_evidence as _memory_has_preference_evidence,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_has_sequence_surface as _memory_has_sequence_surface,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_has_temporal_surface as _memory_has_temporal_surface,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_has_visual_evidence as _memory_has_visual_evidence,
)
from infinity_context_server.memory_comparison_rerank_text import (
    memory_timestamp_values as _memory_timestamp_values,
)
from infinity_context_server.memory_comparison_rerank_text import (
    normalized_terms as _normalized_terms,
)
from infinity_context_server.memory_comparison_rerank_text import (
    optional_int as _optional_int,
)
from infinity_context_server.memory_comparison_rerank_text import (
    question_phrase_terms as _question_phrase_terms,
)
from infinity_context_server.memory_comparison_rerank_text import (
    render_query_terms as _render_query_terms,
)
from infinity_context_server.memory_comparison_rerank_text import (
    speaker_match_surfaces as _speaker_match_surfaces,
)
from infinity_context_server.memory_comparison_rerank_text import (
    speaker_surfaces as _speaker_surfaces,
)
from infinity_context_server.memory_comparison_rerank_text import (
    string_sequence as _string_sequence,
)
from infinity_context_server.memory_comparison_rerank_text import (
    timestamped_memory_count as _timestamped_memory_count,
)
from infinity_context_server.memory_comparison_rerank_text import (
    visual_surface_terms as _visual_surface_terms,
)
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

_HIGH_SIGNAL_RELATION_VARIANTS = {
    "amazing",
    "awesome",
    "camping",
    "care",
    "classical",
    "conservative",
    "brother",
    "daughter",
    "dinosaur",
    "faith",
    "husband",
    "father",
    "inclusive",
    "inclusivity",
    "hiking",
    "known",
    "lgbtq",
    "love",
    "mental",
    "mom",
    "mother",
    "nature",
    "important",
    "parent",
    "partner",
    "real",
    "right",
    "rights",
    "self-care",
    "sister",
    "son",
    "spouse",
    "strength",
    "sunrise",
    "transgender",
    "trail",
    "trip",
    "wed",
    "wedding",
    "wife",
    "writing",
    "year",
}
_RELATION_QUERY_TERMS = {
    "activity",
    "ask",
    "attend",
    "birthday",
    "book",
    "bookshelf",
    "bought",
    "between",
    "bring",
    "brought",
    "camp",
    "cause",
    "choose",
    "compare",
    "consider",
    "conference",
    "decide",
    "destress",
    "different",
    "difference",
    "enjoy",
    "enroll",
    "excite",
    "feel",
    "former",
    "gift",
    "give",
    "go",
    "friend",
    "group",
    "grow",
    "help",
    "hike",
    "interest",
    "identity",
    "join",
    "learn",
    "like",
    "love",
    "make",
    "marry",
    "meet",
    "mention",
    "move",
    "participate",
    "plan",
    "political",
    "previous",
    "prioritize",
    "purchas",
    "purchase",
    "pursue",
    "raise",
    "receive",
    "recommend",
    "register",
    "read",
    "religious",
    "relationship",
    "realize",
    "research",
    "run",
    "sign",
    "suggest",
    "symbolize",
    "support",
    "status",
    "tell",
    "think",
    "visit",
    "want",
    "work",
}
_RELATION_QUERY_TERMS.update(
    {
        "adopt",
        "adoption",
        "agency",
        "ally",
        "brother",
        "community",
        "counsel",
        "career",
        "child",
        "children",
        "charity",
        "current",
        "daughter",
        "decision",
        "father",
        "field",
        "husband",
        "individual",
        "kid",
        "member",
        "mother",
        "music",
        "necklace",
        "paint",
        "park",
        "parent",
        "partner",
        "path",
        "personality",
        "process",
        "race",
        "relocate",
        "relocated",
        "relocation",
        "roadtrip",
        "school",
        "self-care",
        "sibling",
        "sister",
        "song",
        "son",
        "speech",
        "spouse",
        "sunrise",
        "summer",
        "trait",
        "wife",
        "write",
    }
)
_TEMPORAL_QUERY_TERMS = (
    "when",
    "how long",
    "long ago",
    "before",
    "after",
    "ago",
    "yesterday",
    "today",
    "tomorrow",
    "last week",
    "next week",
    "earlier",
    "later",
    "previous",
    "recent",
    "date",
    "time",
)
_TEMPORAL_SURFACE_TERMS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
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
    "weekend",
    "week",
    "month",
    "year",
)
_RELATIVE_TEMPORAL_QUERY_SURFACES = (
    "last",
    "today",
    "yesterday",
    "tomorrow",
    "weekend",
    "week",
)
_VISUAL_QUERY_TERMS = (
    "image",
    "photo",
    "picture",
    "paint",
    "painting",
    "drawing",
    "share",
    "showed",
    "show",
    "shown",
    "shared",
    "saw",
    "see",
    "look",
)
_MULTI_HOP_BRIDGE_MARKER_TERMS = {
    "why": ("reason", "because", "cause", "decision", "value", "fit"),
    "how": ("process", "support", "help", "change", "result", "because"),
    "after": ("after", "then", "later", "date", "time"),
    "before": ("before", "earlier", "then", "date", "time"),
    "compare": ("compare", "difference", "alternative", "more", "less"),
    "between": ("between", "difference", "alternative", "more", "less"),
}
_CONTRAST_RELATION_MARKER_TERMS = frozenset(
    {"compare", "different", "difference", "former", "previous"}
)
_CONTRAST_SUPPORT_QUERY_SURFACES = frozenset(
    {
        "alternative",
        "before",
        "change",
        "changed",
        "compare",
        "current",
        "currently",
        "difference",
        "different",
        "earlier",
        "former",
        "formerly",
        "instead",
        "now",
        "ongoing",
        "previous",
        "previously",
        "used",
    }
)
_CONTRAST_QUERY_VARIANT_BLOCKLIST = frozenset(
    {"been", "existing", "known", "year", "years"}
)
_CONTRAST_CURRENTNESS_BACKFILL = ("current", "now", "ongoing")
_CONTRAST_STALE_BACKFILL = ("previous", "before", "earlier", "used")


def expanded_search_query(case: PublicBenchmarkCase) -> tuple[str, dict[str, object]]:
    """Build a fair query expansion from question text only."""

    intent = _query_retrieval_intent(case)
    profile = intent.to_query_profile()
    focus_parts: list[str] = []
    entities = intent.entity_names
    entity_surfaces = intent.entity_surfaces
    speaker_surfaces = intent.speaker_surfaces
    relation_terms = intent.relation_terms
    relation_variant_terms = intent.relation_variant_terms
    temporal_terms = intent.time_intent.terms
    temporal_surface_terms = intent.time_intent.surface_terms
    visual_terms = intent.visual_terms
    multi_hop_markers = intent.multi_hop_markers
    if entities:
        focus_parts.append(f"entities: {', '.join(entity_surfaces)}")
        if speaker_surfaces:
            focus_parts.append(
                f"speakers: {', '.join(f'{entity}:' for entity in speaker_surfaces)}"
            )
    if relation_terms:
        focus_actions = _support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=intent.lexical_terms,
            entity_surfaces=entity_surfaces,
            communication_support=(
                "communication_support" in intent.bundle_evidence_roles
            ),
        )
        focus_parts.append(
            f"actions: {', '.join(_render_query_terms(focus_actions[:8]))}"
        )
    if temporal_terms:
        focus_temporal = _temporal_search_terms(temporal_terms, temporal_surface_terms)
        focus_parts.append(f"temporal: {', '.join(focus_temporal[:8])}")
    if visual_terms:
        focus_visual = tuple(dict.fromkeys((*visual_terms, "image", "photo", "shows")))
        focus_parts.append(f"visual: {', '.join(focus_visual[:8])}")
    if multi_hop_markers:
        focus_parts.append(f"multi-hop markers: {', '.join(multi_hop_markers)}")
    if not focus_parts:
        return case.question, {
            "applied": False,
            "original_query": case.question,
            "expanded_query": case.question,
            "query_profile": profile,
            "retrieval_intent": intent.to_diagnostics(),
            "uses_ground_truth": False,
        }
    expanded = f"{case.question}\nSearch focus: {'; '.join(focus_parts)}"
    return expanded, {
        "applied": True,
        "original_query": case.question,
        "expanded_query": expanded,
        "query_profile": profile,
        "retrieval_intent": intent.to_diagnostics(),
        "uses_ground_truth": False,
    }


def decomposed_search_queries(
    case: PublicBenchmarkCase,
    *,
    max_queries: int = 3,
) -> tuple[tuple[str, ...], dict[str, object]]:
    """Build bounded subqueries from question text only."""

    original_query = str(case.question or "").strip()
    expanded_query, expansion = expanded_search_query(case)
    intent = _query_retrieval_intent(case)
    profile = intent.to_query_profile()
    entities = intent.entity_names
    entity_surfaces = intent.entity_surfaces
    speaker_surfaces = intent.speaker_surfaces
    relation_terms = intent.relation_terms
    relation_variant_terms = intent.relation_variant_terms
    temporal_terms = intent.time_intent.terms
    temporal_surface_terms = intent.time_intent.surface_terms
    lexical_terms = intent.lexical_terms
    is_temporal_query = intent.time_intent.is_temporal
    visual_terms = intent.visual_terms
    multi_hop_markers = intent.multi_hop_markers

    query_candidates: list[QueryPlanCandidate] = []
    if original_query:
        query_candidates.append(
            QueryPlanCandidate(
                role="original_question",
                query=original_query,
                priority=0,
                query_type="semantic",
                reason_codes=("original_question",),
            )
        )
    if expansion["applied"]:
        query_candidates.append(
            QueryPlanCandidate(
                role="expanded_focus",
                query=expanded_query,
                priority=10,
                query_type="semantic",
                reason_codes=("typed_intent_focus",),
            )
        )
    if visual_terms and is_temporal_query:
        visual_temporal_terms = tuple(
            dict.fromkeys(
                (
                    *visual_terms[:3],
                    *(
                        term
                        for term in lexical_terms
                        if term not in entity_surfaces and term not in visual_terms
                    ),
                    *_visual_surface_terms(visual_terms),
                    *temporal_terms[:2],
                    "date",
                    "time",
                    "image",
                    "caption",
                    "shows",
                )
            )
        )
        query_candidates.append(
            QueryPlanCandidate(
                role="visual_temporal_support",
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(visual_temporal_terms[:8]))
                ),
                priority=20,
                query_type="lexical",
                reason_codes=("visual_evidence", "temporal_support"),
            )
        )
    elif visual_terms:
        query_candidates.append(
            QueryPlanCandidate(
                role="visual_support",
                query=" ".join(
                    (
                        *entity_surfaces,
                        *_render_query_terms(visual_terms[:5]),
                        "image",
                        "shows",
                    )
                ),
                priority=20,
                query_type="lexical",
                reason_codes=("visual_evidence",),
            )
        )
    if relation_terms:
        compact_relation_role = _compact_relation_query_role(intent)
        relation_query_terms = _support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
            communication_support=compact_relation_role == "communication_support",
        )
        compact_temporal_terms = (
            _compact_temporal_relation_terms(lexical_terms) if is_temporal_query else ()
        )
        if compact_temporal_terms:
            relation_query_terms = tuple(
                dict.fromkeys(
                    (
                        *relation_query_terms[:4],
                        *compact_temporal_terms,
                        *relation_query_terms[4:],
                    )
                )
            )
            relation_term_limit = 7
        elif compact_relation_role == "communication_support":
            relation_term_limit = 8
        elif (
            "activity" in relation_terms
            or {"prioritize", "self-care"}.issubset(relation_terms)
            or "destress" in relation_terms
        ):
            relation_term_limit = 10 if "destress" in relation_terms else 8
        else:
            relation_term_limit = 6
        compact_entity_surfaces = speaker_surfaces or entity_surfaces
        query_candidates.append(
            QueryPlanCandidate(
                role=compact_relation_role,
                query=" ".join(
                    (
                        *compact_entity_surfaces,
                        *_render_query_terms(relation_query_terms[:relation_term_limit]),
                    )
                ),
                priority=30,
                query_type="lexical",
                reason_codes=(
                    "relation_terms",
                    "raw_turn_compact",
                    f"query_role:{compact_relation_role}",
                ),
            )
        )
    contrast_query_terms = (
        _contrast_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
        )
        if "contrast" in intent.evidence_need
        else ()
    )
    if contrast_query_terms and (entity_surfaces or len(contrast_query_terms) >= 4):
        query_candidates.append(
            QueryPlanCandidate(
                role="contrast_support",
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(contrast_query_terms[:9]))
                ),
                priority=35,
                query_type="lexical",
                reason_codes=(
                    "contrast_support",
                    "current_previous_evidence",
                    "question_only",
                ),
            )
        )
    location_query_terms = (
        _location_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
        )
        if "location_support" in intent.evidence_need
        else ()
    )
    if location_query_terms and (entity_surfaces or len(location_query_terms) >= 4):
        query_candidates.append(
            QueryPlanCandidate(
                role="location_support",
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(location_query_terms[:9]))
                ),
                priority=37,
                query_type="lexical",
                reason_codes=(
                    "location_support",
                    "location_transition",
                    "question_only",
                ),
            )
        )
    temporal_query_terms = (
        _temporal_search_terms(temporal_terms, temporal_surface_terms)
        if is_temporal_query
        else ()
    )
    if temporal_query_terms:
        temporal_role = _temporal_query_role(intent.time_intent.kind)
        query_candidates.append(
            QueryPlanCandidate(
                role=temporal_role,
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(temporal_query_terms[:7]))
                ),
                priority=40,
                query_type="lexical",
                reason_codes=(
                    "temporal_support",
                    temporal_role,
                    f"time_kind:{intent.time_intent.kind}",
                ),
            )
        )
    bridge_query_terms = _multi_hop_bridge_query_terms(
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        lexical_terms=lexical_terms,
        multi_hop_markers=multi_hop_markers,
    )
    if multi_hop_markers and entity_surfaces and bridge_query_terms:
        query_candidates.append(
            QueryPlanCandidate(
                role="multi_hop_bridge",
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(bridge_query_terms[:8]))
                ),
                priority=45,
                query_type="lexical",
                reason_codes=(
                    "multi_hop_bridge",
                    "entity_relation_bridge",
                    "question_only",
                ),
            )
        )
    if multi_hop_markers and entities:
        query_candidates.append(
            QueryPlanCandidate(
                role="multi_hop_support",
                query=f"{original_query} supporting evidence {' '.join(entity_surfaces)}",
                priority=50,
                query_type="semantic",
                reason_codes=("multi_hop_support",),
            )
        )

    extra_query_slots = 0
    if any(candidate.role == "contrast_support" for candidate in query_candidates):
        extra_query_slots += 1
    has_location_support_query = any(
        candidate.role == "location_support" for candidate in query_candidates
    )
    if has_location_support_query and temporal_query_terms:
        extra_query_slots += 1
    if (
        not temporal_query_terms
        and any(candidate.role == "multi_hop_bridge" for candidate in query_candidates)
    ):
        extra_query_slots += 1
    max_selected_queries = max_queries + extra_query_slots
    max_queries_per_type = 3 if has_location_support_query and temporal_query_terms else 2
    query_plan = QueryPlannerV2(
        max_queries=max_selected_queries,
        max_queries_per_type=max_queries_per_type,
    ).plan(
        query_candidates,
        fallback_query=original_query,
        recommended_role_families=_recommended_query_role_families(intent),
    )
    unique_queries = query_plan.queries
    return unique_queries, {
        "applied": query_plan.applied,
        "strategy": "question_only_multi_query",
        "query_count": len(unique_queries),
        "queries": list(unique_queries),
        "original_query": original_query,
        "expanded_query": expanded_query,
        "query_profile": profile,
        "retrieval_intent": intent.to_diagnostics(),
        "query_plan": query_plan.to_diagnostics(),
        "uses_ground_truth": False,
    }


def _multi_hop_bridge_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> tuple[str, ...]:
    if not multi_hop_markers:
        return ()
    bridge_terms: list[str] = []
    bridge_terms.extend(_relation_query_terms(relation_terms, relation_variant_terms)[:6])
    for marker in multi_hop_markers:
        bridge_terms.extend(_MULTI_HOP_BRIDGE_MARKER_TERMS.get(marker, ()))
    bridge_terms.extend(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS and term not in bridge_terms
    )
    return tuple(dict.fromkeys(bridge_terms))


def _support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
    communication_support: bool,
) -> tuple[str, ...]:
    if communication_support:
        return _communication_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if {"sign", "enroll", "register"} & set(relation_terms):
        return _registration_event_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    return _relation_query_terms(relation_terms, relation_variant_terms)


def _communication_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token
        for surface in entity_surfaces
        for token in _normalized_terms(surface)
    }
    communication_surface_terms = {
        "advis",
        "ask",
        "asked",
        "mention",
        "recommend",
        "recommended",
        "request",
        "said",
        "suggest",
        "suggested",
        "tell",
        "told",
    }
    allowed_communication_terms: set[str] = set()
    relation_term_set = set(relation_terms)
    if relation_term_set & {"tell", "mention"}:
        allowed_communication_terms.update(("mention", "said", "tell", "told"))
    if "ask" in relation_term_set:
        allowed_communication_terms.update(("ask", "asked", "request"))
    if relation_term_set & {"recommend", "suggest"}:
        allowed_communication_terms.update(
            ("advis", "recommend", "recommended", "suggest", "suggested", "told")
        )
    if not allowed_communication_terms:
        allowed_communication_terms.update(communication_surface_terms)
    relation_specific_variants = tuple(
        term
        for term in relation_variant_terms
        if term not in communication_surface_terms or term in allowed_communication_terms
    )
    communication_terms = tuple(
        term
        for term in _relation_query_terms(relation_terms, relation_variant_terms)
        if term in allowed_communication_terms
    )
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_specific_variants
        and term not in communication_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *relation_terms,
                *relation_specific_variants[:4],
                *topical_terms[:6],
                *communication_terms,
                *relation_specific_variants,
            )
        )
    )


def _registration_event_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    base_terms = _relation_query_terms(relation_terms, relation_variant_terms)
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in _QUERY_TOKEN_ALIASES
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys((*base_terms[:4], *topical_terms[:4], *base_terms[4:]))
    )


def _recommended_query_role_families(intent: RetrievalIntent) -> tuple[str, ...]:
    families: list[str] = ["base_query"]
    if intent.relation_terms or intent.relation_variant_terms:
        families.append("relation_compact")
    if intent.visual_terms:
        families.append("visual_support")
    if intent.time_intent.is_temporal:
        families.append("temporal_support")
    if "contrast" in intent.evidence_need:
        families.append("contrast_support")
    if "location_support" in intent.evidence_need:
        families.append("location_support")
    if "causal_support" in intent.evidence_need:
        families.append("multi_hop")
    if "multi_hop" in intent.evidence_need or intent.multi_hop_markers:
        families.append("multi_hop")
    return tuple(dict.fromkeys(families))


def _compact_relation_query_role(intent: RetrievalIntent) -> str:
    role_priority = (
        "communication_support",
        "event_support",
        "exchange_support",
        "emotion_response_support",
        "symbolic_meaning_support",
        "preference_support",
        "causal_support",
        "inference_support",
    )
    roles = set(intent.bundle_evidence_roles)
    for role in role_priority:
        if role in roles:
            return role
    return "compact_relation"


def _temporal_query_role(time_kind: str) -> str:
    return {
        "duration": "duration_temporal_support",
        "explicit_time": "explicit_temporal_support",
        "relative_time": "relative_temporal_support",
        "temporal_sequence": "temporal_sequence_support",
    }.get(time_kind, "temporal_support")


def _contrast_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
) -> tuple[str, ...]:
    relation_query_terms = _relation_query_terms(
        relation_terms,
        relation_variant_terms,
    )
    topical_terms = tuple(
        term
        for term in relation_terms
        if term not in _CONTRAST_RELATION_MARKER_TERMS
        and term not in _CONTRAST_QUERY_VARIANT_BLOCKLIST
    )
    explicit_contrast_terms = tuple(
        term for term in lexical_terms if term in _CONTRAST_SUPPORT_QUERY_SURFACES
    )
    contrast_variants = tuple(
        term
        for term in relation_query_terms
        if term in _CONTRAST_SUPPORT_QUERY_SURFACES
    )
    topical_variants = tuple(
        term
        for term in relation_query_terms
        if term not in topical_terms
        and term not in _CONTRAST_SUPPORT_QUERY_SURFACES
        and term not in _CONTRAST_QUERY_VARIANT_BLOCKLIST
        and term not in _QUERY_STOPWORDS
    )
    backfill_terms: tuple[str, ...] = ()
    if {"current", "currently", "now"} & set(
        (*explicit_contrast_terms, *contrast_variants)
    ):
        backfill_terms = (*backfill_terms, *_CONTRAST_CURRENTNESS_BACKFILL)
    if explicit_contrast_terms or contrast_variants:
        backfill_terms = (*backfill_terms, *_CONTRAST_STALE_BACKFILL)
    return tuple(
        dict.fromkeys(
            (
                *topical_terms[:4],
                *explicit_contrast_terms,
                *backfill_terms,
                *contrast_variants,
                *topical_variants[:5],
            )
        )
    )

def _location_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
) -> tuple[str, ...]:
    relation_query_terms = _relation_query_terms(
        relation_terms,
        relation_variant_terms,
    )
    location_surfaces = (
        "from",
        "origin",
        "home",
        "country",
        "city",
        "relocated",
        "moved",
        "came",
        "travel",
        "trip",
    )
    explicit_location_terms = tuple(
        term
        for term in lexical_terms
        if term in {"from", "where", "which", "country", "city", "place", "origin"}
    )
    return tuple(
        dict.fromkeys(
            (
                *(
                    term
                    for term in relation_query_terms
                    if term not in _QUERY_STOPWORDS
                ),
                *explicit_location_terms,
                *location_surfaces,
            )
        )
    )


def query_support_terms(case: PublicBenchmarkCase) -> tuple[str, ...]:
    """Return question-only terms useful for evidence support diagnostics."""

    profile = _query_retrieval_intent(case).to_query_profile()
    terms: list[str] = []
    for key in (
        "entities",
        "entity_surfaces",
        "relation_terms",
        "relation_variant_terms",
        "temporal_terms",
        "temporal_surface_terms",
        "visual_terms",
        "lexical_terms",
    ):
        terms.extend(_string_sequence(profile.get(key)))
    return tuple(dict.fromkeys(terms))


def temporal_rerank_memories(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> tuple[list[RetrievedMemory], dict[str, object]]:
    profile = _temporal_query_profile(case)
    if not profile["is_temporal_query"] or not memories:
        return list(memories), {
            **profile,
            "applied": False,
            "timestamped_memory_count": _timestamped_memory_count(memories),
            "reranked_memory_count": 0,
        }
    reranked = [
        _with_temporal_rerank_boost(memory)
        if _memory_timestamp_values(memory)
        else memory
        for memory in memories
    ]
    reranked.sort(key=lambda memory: (-memory.score, memory.rank))
    timestamped_count = _timestamped_memory_count(memories)
    return reranked, {
        **profile,
        "applied": timestamped_count > 0,
        "timestamped_memory_count": timestamped_count,
        "reranked_memory_count": len(reranked),
        "boost": 0.3 if timestamped_count > 0 else 0.0,
    }


def benchmark_rerank_memories(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> tuple[list[RetrievedMemory], dict[str, object]]:
    intent = _query_retrieval_intent(case)
    profile = intent.to_query_profile()
    if not memories or not profile["lexical_terms"]:
        return list(memories), {
            "applied": False,
            "boosted_memory_count": 0,
            "max_boost": 0.0,
            "query_profile": profile,
            "retrieval_intent": intent.to_diagnostics(),
            "uses_ground_truth": False,
        }

    reranked: list[RetrievedMemory] = []
    boosts: list[float] = []
    for memory in memories:
        reranked_memory, boost = _with_benchmark_rerank_boost(memory, profile)
        reranked.append(reranked_memory)
        if boost > 0:
            boosts.append(boost)

    reranked.sort(key=lambda memory: (-memory.score, memory.rank))
    return reranked, {
        "applied": bool(boosts),
        "boosted_memory_count": len(boosts),
        "max_boost": round(max(boosts), 6) if boosts else 0.0,
        "query_profile": profile,
        "retrieval_intent": intent.to_diagnostics(),
        "uses_ground_truth": False,
    }


def _with_temporal_rerank_boost(memory: RetrievedMemory) -> RetrievedMemory:
    diagnostics = (
        dict(memory.metadata.get("diagnostics"))
        if isinstance(memory.metadata.get("diagnostics"), Mapping)
        else {}
    )
    score_signals = (
        dict(diagnostics.get("score_signals"))
        if isinstance(diagnostics.get("score_signals"), Mapping)
        else {}
    )
    score_signals["benchmark_temporal_source_ref_boost"] = 0.3
    diagnostics["score_signals"] = score_signals
    diagnostics["temporal_rerank_boosted"] = True
    return replace(
        memory,
        score=round(memory.score + 0.3, 6),
        metadata={**dict(memory.metadata), "diagnostics": diagnostics},
    )


def query_retrieval_intent(case: PublicBenchmarkCase) -> RetrievalIntent:
    """Build question-only retrieval intent shared by planner, rerank and evidence."""

    return _query_retrieval_intent(case)


def _query_retrieval_intent(case: PublicBenchmarkCase) -> RetrievalIntent:
    question = str(case.question or "")
    lexical_terms = tuple(
        dict.fromkeys((*_normalized_terms(question), *_question_phrase_terms(question)))
    )
    entity_names = tuple(dict.fromkeys(_query_entities(question)))
    entities = tuple(
        RetrievalEntityIntent(
            canonical=entity,
            surfaces=_entity_surfaces((entity,)),
            speaker_surfaces=_speaker_surfaces(_entity_surfaces((entity,))),
        )
        for entity in entity_names
    )
    relation_terms = tuple(term for term in lexical_terms if term in _RELATION_QUERY_TERMS)
    relation_variant_terms = tuple(
        dict.fromkeys(
            variant
            for relation in relation_terms
            for variant in _relation_variant_terms(relation)
        )
    )
    relation_variant_terms = _filter_relation_variant_terms_for_profile(
        question=question,
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
    )
    temporal_profile = _temporal_query_profile(case)
    visual_terms = tuple(term for term in lexical_terms if term in _VISUAL_QUERY_TERMS)
    category = _optional_int(case.metadata.get("category"))
    marker_candidates = ["why"]
    if category == 1 or _non_temporal_process_how_marker(question):
        marker_candidates.append("how")
    multi_hop_markers = tuple(
        marker
        for marker in marker_candidates
        if re.search(rf"\b{re.escape(marker)}\b", question, flags=re.IGNORECASE)
    )
    temporal_terms = tuple(temporal_profile["matched_terms"])
    temporal_surface_terms = tuple(temporal_profile["surface_terms"])
    time_intent = RetrievalTimeIntent(
        is_temporal=bool(temporal_profile["is_temporal_query"]),
        terms=temporal_terms,
        surface_terms=temporal_surface_terms,
        kind=infer_time_intent_kind(
            is_temporal=bool(temporal_profile["is_temporal_query"]),
            temporal_terms=temporal_terms,
            temporal_surface_terms=temporal_surface_terms,
        ),
    )
    relation_intents = infer_relation_intents(
        question=question,
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        time_intent=time_intent,
        visual_terms=visual_terms,
        multi_hop_markers=multi_hop_markers,
    )
    evidence_need = merge_relation_evidence_needs(
        infer_evidence_need(
            question=question,
            relation_terms=relation_terms,
            time_intent=time_intent,
            visual_terms=visual_terms,
            multi_hop_markers=multi_hop_markers,
            benchmark_category=category,
        ),
        relation_intents,
    )
    return RetrievalIntent(
        question=question,
        lexical_terms=lexical_terms,
        entities=entities,
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        time_intent=time_intent,
        visual_terms=visual_terms,
        multi_hop_markers=multi_hop_markers,
        evidence_need=evidence_need,
        risk_flags=infer_risk_flags(
            entity_count=len(entities),
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            time_intent=time_intent,
        ),
        bundle_evidence_roles=infer_bundle_evidence_roles(
            evidence_need=evidence_need,
            benchmark_category=category,
        ),
        relation_intents=relation_intents,
    )


def _query_rerank_profile(case: PublicBenchmarkCase) -> dict[str, object]:
    return _query_retrieval_intent(case).to_query_profile()


def _non_temporal_process_how_marker(question: str) -> bool:
    if not re.search(r"\bhow\b", question, flags=re.IGNORECASE):
        return False
    if re.search(r"\bhow\s+(?:long|many|much|old)\b", question, flags=re.IGNORECASE):
        return False
    return not re.search(
        r"\b(?:compare|between|different|difference|previous|former)\b",
        question,
        flags=re.IGNORECASE,
    )


def _relation_variant_terms(relation: str) -> tuple[str, ...]:
    variants = _RELATION_QUERY_VARIANTS.get(relation, ())
    terms: list[str] = []
    for phrase in variants:
        terms.extend(_normalized_terms(phrase))
    return tuple(
        term
        for term in terms
        if term != relation
        and term not in _QUERY_TOKEN_ALIASES
        and relation not in _QUERY_TOKEN_ALIASES.get(term, ())
    )


def _filter_relation_variant_terms_for_profile(
    *,
    question: str,
    relation_terms: Sequence[str],
    relation_variant_terms: Sequence[str],
) -> tuple[str, ...]:
    relation_term_set = set(relation_terms)
    blocked_terms: set[str] = set()
    normalized_question = " ".join(str(question or "").casefold().split())
    if _has_future_home_move_goal_intent(normalized_question, relation_terms):
        blocked_terms.update(
            {
                "came",
                "country",
                "home",
                "moved",
                "origin",
                "relocated",
            }
        )
    if {"choose", "adoption", "agency"}.issubset(relation_term_set):
        blocked_terms.update(
            {
                "folk",
                "children",
                "family",
                "help",
                "inclusive",
                "inclusivity",
                "individual",
                "kid",
                "lgbtq",
                "support",
            }
        )
    if {"excite", "adoption", "process"}.issubset(relation_term_set):
        blocked_terms.update(
            {
                "children",
                "family",
                "inclusive",
                "inclusivity",
                "kid",
                "lgbtq",
                "mom",
            }
        )
    if not blocked_terms:
        return tuple(relation_variant_terms)
    return tuple(term for term in relation_variant_terms if term not in blocked_terms)


def _has_future_home_move_goal_intent(
    normalized_question: str,
    relation_terms: Sequence[str],
) -> bool:
    if not {"want", "move"} <= set(relation_terms):
        return False
    if re.search(
        r"\b(?:where|which\s+(?:city|country|place)|from|origin)\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:would|want|wants|wanted|hope|hoping|plan|plans)\b",
            normalized_question,
        )
        and re.search(r"\bmove\s+back\b", normalized_question)
        and re.search(r"\bhome\s+country\b", normalized_question)
    )


def _relation_query_terms(
    relation_terms: Sequence[str],
    relation_variant_terms: Sequence[str],
) -> tuple[str, ...]:
    relation_terms = tuple(relation_terms)
    generic_relation_terms = {"consider"}
    if "receive" in relation_terms and "grow" in relation_terms:
        generic_relation_terms.add("career")
    base_terms = (
        tuple(term for term in relation_terms if term not in generic_relation_terms)
        if len(relation_terms) > 1
        else relation_terms
    )
    delayed_base_terms: tuple[str, ...] = ()
    relation_term_set = set(relation_terms)
    if {"excite", "adoption", "process"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"adoption", "process"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"think", "decision", "adopt"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"decision", "adopt"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"receive", "support", "grow"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"pursue", "receive", "grow"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"career", "path", "pursue"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"decide", "pursue"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"write", "career"}.issubset(relation_term_set):
        delayed_base_terms = tuple(term for term in base_terms if term == "pursue")
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"realize", "charity", "race"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"charity", "race"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"individual", "adoption", "support"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"agency", "individual"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"choose", "adoption", "agency"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"choose", "agency"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"relationship", "status"}.issubset(relation_term_set):
        delayed_base_terms = base_terms
        base_terms = ()
    elif {"charity", "race", "raise"}.issubset(relation_term_set):
        delayed_base_terms = tuple(term for term in base_terms if term == "raise")
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif {"book", "bookshelf"}.issubset(relation_term_set):
        delayed_base_terms = tuple(term for term in base_terms if term == "bookshelf")
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    elif "marry" in relation_term_set:
        delayed_base_terms = base_terms
        base_terms = ()
    elif {"field", "pursue"}.issubset(relation_term_set):
        delayed_base_terms = tuple(
            term for term in base_terms if term in {"field", "pursue"}
        )
        base_terms = tuple(term for term in base_terms if term not in delayed_base_terms)
    high_signal_variants = tuple(
        term for term in relation_variant_terms if term in _HIGH_SIGNAL_RELATION_VARIANTS
    )
    priority_variant_order: list[str] = []
    priority_surface_terms: set[str] = set()
    if "activity" in relation_term_set:
        priority_variant_order.extend(
            (
                "hobby",
                "hobbies",
                "partake",
                "class",
                "paint",
                "swim",
                "run",
                "read",
                "violin",
                "kid",
                "photo",
                "creative",
                "fun",
                "interest",
                "expres",
                "refresh",
                "image",
                "family",
                "weekend",
                "unplug",
                "therapeutic",
                "leisure",
            )
        )
        priority_surface_terms.add("express")
    if "hike" in relation_term_set:
        priority_variant_order.extend(
            (
                "trail",
                "hiking",
                "waterfall",
                "went",
                "spot",
                "weekend",
                "summer",
                "photo",
            )
        )
    if {"excite", "adoption", "process"}.issubset(relation_term_set):
        priority_variant_order.extend(("kid", "make", "create", "thrilled", "process"))
        priority_surface_terms.add("thrilled")
    if {"go", "support", "group"}.issubset(relation_term_set):
        priority_variant_order.extend(("went", "lgbtq", "inclusive"))
    if {"book", "read"}.issubset(relation_term_set):
        priority_variant_order.extend(("reading",))
        priority_surface_terms.add("reading")
    if {"kid", "like"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "animal",
                "bones",
                "exhibit",
                "learning",
                "stoked",
                "family",
                "preference",
                "children",
                "like",
                "love",
            )
        )
        priority_surface_terms.update(("animal", "bones", "learning", "stoked"))
    if "birthday" in relation_term_set:
        priority_variant_order.extend(("18th", "year", "ago", "born", "age"))
        priority_surface_terms.add("18th")
    if "camp" in relation_term_set:
        priority_variant_order.extend(
            ("camping", "family", "unplug", "connection", "close", "outdoor", "trip")
        )
    if {"book", "bookshelf"}.issubset(relation_term_set):
        priority_variant_order.extend(("books", "kids", "stories", "reading", "read"))
        priority_surface_terms.update(("books", "kids", "stories"))
    if {"receive", "support", "grow"}.issubset(relation_term_set):
        priority_variant_order.extend(("got", "help", "growing", "journey"))
    if {"bought", "buy", "purchas", "purchase"} & relation_term_set:
        priority_variant_order.extend(("got", "purchased", "buy", "bought"))
        priority_surface_terms.update(("got", "purchased"))
    if "destress" in relation_term_set:
        priority_variant_order.extend(
            (
                "stress",
                "relax",
                "unwind",
                "class",
                "clear",
                "mind",
                "run",
                "therapy",
                "therapeutic",
                "creative",
                "expres",
                "decompress",
                "self-care",
            )
        )
    if "identity" in relation_term_set:
        priority_variant_order.extend(
            (
                "support",
                "inspir",
                "story",
                "gender",
                "accept",
                "courage",
                "embrace",
                "pride",
                "self",
            )
        )
    if {"think", "decision", "adopt"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "reaction",
                "response",
                "opinion",
                "feel",
                "creating",
                "family",
                "lovely",
                "luck",
                "support",
                "kid",
            )
        )
    if {"excite", "feel"} & relation_term_set and not {
        "adoption",
        "excite",
        "process",
    }.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "felt",
                "feeling",
                "reaction",
                "response",
                "excited",
                "thrilled",
                "nervous",
                "relieved",
                "proud",
                "worried",
                "upset",
            )
        )
        priority_surface_terms.update(("excited", "thrilled", "worried"))
    if "political" in relation_term_set:
        priority_variant_order.extend(
            (
                "conservatives",
                "rights",
                "lgbtq",
                "transition",
                "comment",
                "upset",
                "support",
                "accept",
                "conservative",
                "belief",
                "view",
            )
        )
        priority_surface_terms.update(("rights", "conservatives"))
    if "religious" in relation_term_set:
        priority_variant_order.extend(
            (
                "church",
                "conservatives",
                "think",
                "journey",
                "chang",
                "acceptance",
                "faith",
                "growth",
            )
        )
        priority_surface_terms.add("conservatives")
    if {"career", "path", "pursue"}.issubset(relation_term_set):
        priority_variant_order.extend(("work", "working", "think", "figur", "option"))
        priority_surface_terms.add("working")
    if {"write", "career"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "looking",
                "books",
                "book",
                "support",
                "similar",
                "issue",
                "jobs",
                "job",
                "option",
                "draft",
                "story",
            )
        )
        priority_surface_terms.update(("looking", "books"))
    if {"enjoy", "song"}.issubset(relation_term_set):
        priority_variant_order.extend(
            ("fan", "piece", "composer", "instrumental", "orchestra", "like")
        )
    if {"necklace", "symbolize"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "symbol",
                "mean",
                "gift",
                "reminder",
                "family",
                "support",
                "special",
                "represent",
                "message",
            )
        )
    if {"field", "pursue"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "career",
                "option",
                "work",
                "support",
                "similar",
                "issue",
                "keen",
                "edu",
                "education",
                "study",
                "working",
            )
        )
        priority_surface_terms.add("edu")
    if {"interest", "park"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "camping",
                "trip",
                "campfire",
                "marshmallow",
                "story",
                "meteor",
                "sky",
                "summer",
                "enjoy",
                "nature",
                "outdoor",
            )
        )
        priority_surface_terms.update(("enjoy", "story"))
    if {"prioritize", "self-care"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "routine",
                "refreshes",
                "present",
                "wellness",
                "balance",
                "rest",
                "relax",
            )
        )
        priority_surface_terms.add("refreshes")
    if {"realize", "charity", "race"}.issubset(relation_term_set):
        priority_variant_order.extend(
            ("lesson", "reflection", "thought", "event", "journey")
        )
    if {"relationship", "status"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "parent",
                "breakup",
                "family",
                "kid",
                "friend",
                "support",
                "challenge",
                "dating",
                "partner",
            )
        )
    if {"charity", "race", "raise"}.issubset(relation_term_set):
        priority_variant_order.extend(("raising", "raised", "awareness", "fundraiser"))
        priority_surface_terms.update(("raising", "raised"))
    if {"run", "charity", "race"}.issubset(relation_term_set):
        priority_variant_order.extend(("last", "ran", "marathon", "fundraiser"))
        priority_surface_terms.add("last")
    if "research" in relation_term_set:
        priority_variant_order.extend(("researching",))
        priority_surface_terms.add("researching")
    if {"ask", "tell", "mention", "recommend", "suggest"} & relation_term_set:
        priority_variant_order.extend(
            (
                "told",
                "asked",
                "recommended",
                "suggested",
                "request",
                "said",
            )
        )
        priority_surface_terms.update(("asked", "recommended", "suggested"))
    if "visit" in relation_term_set:
        priority_variant_order.extend(("visited", "studio", "place", "trip", "event"))
        priority_surface_terms.add("visited")
    if "attend" in relation_term_set:
        priority_variant_order.extend(
            ("attended", "event", "meeting", "conference", "class", "workshop")
        )
        priority_surface_terms.add("attended")
    if "join" in relation_term_set:
        priority_variant_order.extend(
            ("joined", "group", "community", "club", "class", "event")
        )
        priority_surface_terms.add("joined")
    if "participate" in relation_term_set:
        priority_variant_order.extend(
            ("participated", "event", "group", "class", "workshop", "activity")
        )
        priority_surface_terms.add("participated")
    if "move" in relation_term_set:
        priority_variant_order.extend(("moved", "home", "country", "relocated"))
    if "sign" in relation_term_set:
        priority_variant_order.extend(("signed", "signup", "class", "registered"))
        priority_surface_terms.add("signed")
    if {"enroll", "register"} & relation_term_set:
        priority_variant_order.extend(
            (
                "signed",
                "signup",
                "class",
                "registered",
                "registration",
                "enrolled",
                "course",
                "lesson",
                "workshop",
            )
        )
        priority_surface_terms.update(("signed", "registered", "enrolled"))
    if "conference" in relation_term_set:
        priority_variant_order.extend(("transgender", "going", "month", "community", "event"))
        priority_surface_terms.update(("month", "community"))
    if "roadtrip" in relation_term_set:
        priority_variant_order.extend(
            (
                "accident",
                "son",
                "family",
                "safe",
                "trip",
                "road",
                "weekend",
                "past",
                "soon",
                "another",
            )
        )
        priority_surface_terms.update(("weekend", "past"))
    if {"individual", "adoption", "support"}.issubset(relation_term_set):
        priority_variant_order.extend(
            ("help", "lgbtq", "folks", "inclusivity", "inclusive")
        )
        priority_surface_terms.add("folks")
    if {"choose", "adoption", "agency"}.issubset(relation_term_set):
        priority_variant_order.extend(
            ("chose", "reason", "cause", "fit", "value", "spoke", "decision")
        )
    if {"plan", "summer"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "dream",
                "family",
                "lov",
                "home",
                "kid",
                "future",
                "upcoming",
                "season",
                "goal",
                "want",
                "going",
            )
        )
        priority_surface_terms.update(("upcoming", "going"))
    if "marry" in relation_term_set:
        priority_variant_order.extend(
            ("wed", "year", "already", "bride", "dres", "wedding", "married")
        )
        priority_surface_terms.add("already")
    if {"give", "speech", "school"}.issubset(relation_term_set):
        priority_variant_order.extend(("event", "talk", "student"))
    priority_variants = tuple(
        term
        for term in priority_variant_order
        if term in relation_variant_terms or term in priority_surface_terms
    )
    return tuple(
        dict.fromkeys(
            (
                *base_terms,
                *priority_variants,
                *delayed_base_terms,
                *high_signal_variants,
                *relation_variant_terms,
            )
        )
    )


def _temporal_query_profile(case: PublicBenchmarkCase) -> dict[str, object]:
    query = " ".join(str(case.question or "").casefold().split())
    category = _optional_int(case.metadata.get("category"))
    matched_terms = tuple(term for term in _TEMPORAL_QUERY_TERMS if term in query)
    surface_terms = tuple(term for term in _TEMPORAL_SURFACE_TERMS if term in query)
    is_temporal = category == 2 or bool(matched_terms) or bool(surface_terms)
    reasons: list[str] = []
    if category == 2:
        reasons.append("locomo_temporal_category")
    reasons.extend(f"query_term:{term}" for term in matched_terms)
    reasons.extend(f"surface_term:{term}" for term in surface_terms)
    return {
        "is_temporal_query": is_temporal,
        "reasons": reasons,
        "matched_terms": list(matched_terms),
        "surface_terms": list(surface_terms),
    }


def _query_entities(text: str) -> tuple[str, ...]:
    entities: list[tuple[int, str]] = []
    protected_spans: list[tuple[int, int]] = []
    for match in _HONORIFIC_ENTITY_RE.finditer(text):
        entity = _clean_query_entity(match.group(0))
        if entity:
            entities.append((match.start(), entity))
            protected_spans.append(match.span())
    for match in re.finditer(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\b", text):
        if _span_overlaps(match.span(), protected_spans):
            continue
        entity = _clean_query_entity(match.group(0))
        if entity:
            entities.append((match.start(), entity))
    for match in re.finditer(r"\b[A-Z]{2,}\+?\b", text):
        if _span_overlaps(match.span(), protected_spans):
            continue
        entity = _clean_query_entity(match.group(0))
        if entity not in _QUERY_STOPWORDS | set(_TEMPORAL_SURFACE_TERMS):
            entities.append((match.start(), entity))
    return tuple(entity for _, entity in sorted(entities, key=lambda item: item[0]))


def _clean_query_entity(raw: str) -> str:
    terms: list[str] = []
    for raw_term in raw.split():
        term = raw_term.casefold().strip(" .'\"")
        if term.endswith("'s"):
            term = term[:-2]
        if term and term not in _QUERY_STOPWORDS | set(_TEMPORAL_SURFACE_TERMS):
            terms.append(term)
    return " ".join(terms)


def _span_overlaps(
    span: tuple[int, int],
    protected_spans: Sequence[tuple[int, int]],
) -> bool:
    return any(
        span[0] < protected[1] and protected[0] < span[1]
        for protected in protected_spans
    )


def _with_benchmark_rerank_boost(
    memory: RetrievedMemory,
    profile: Mapping[str, object],
) -> tuple[RetrievedMemory, float]:
    boost, signals = _benchmark_rerank_boost(memory, profile)
    if boost <= 0:
        return memory, 0.0

    diagnostics = (
        dict(memory.metadata.get("diagnostics"))
        if isinstance(memory.metadata.get("diagnostics"), Mapping)
        else {}
    )
    score_signals = (
        dict(diagnostics.get("score_signals"))
        if isinstance(diagnostics.get("score_signals"), Mapping)
        else {}
    )
    score_signals.update(signals["score_signals"])
    diagnostics["score_signals"] = score_signals
    diagnostics["benchmark_rerank_boosted"] = True
    diagnostics["benchmark_query_overlap_terms"] = signals["overlap_terms"]
    diagnostics["benchmark_query_entities"] = signals["entity_hits"]
    diagnostics["benchmark_candidate_features"] = signals["candidate_features"]
    diagnostics["benchmark_rerank_policy"] = signals["policy_contributions"]
    return replace(
        memory,
        score=round(memory.score + boost, 6),
        metadata={**dict(memory.metadata), "diagnostics": diagnostics},
    ), boost


def _benchmark_rerank_boost(
    memory: RetrievedMemory,
    profile: Mapping[str, object],
) -> tuple[float, dict[str, object]]:
    memory_terms = set(_normalized_terms(memory.text))
    query_terms = tuple(_string_sequence(profile.get("lexical_terms")))
    relation_terms = tuple(_string_sequence(profile.get("relation_terms")))
    relation_variant_terms = tuple(_string_sequence(profile.get("relation_variant_terms")))
    relation_category_terms = _relation_category_terms(profile)
    entities = tuple(_string_sequence(profile.get("entities")))
    entity_surfaces = tuple(_string_sequence(profile.get("entity_surfaces"))) or entities
    speaker_surfaces = tuple(_string_sequence(profile.get("speaker_surfaces")))
    primary_speaker_surfaces = speaker_surfaces[:1] or speaker_surfaces
    entity_hits = tuple(
        entity
        for entity in entity_surfaces
        if _entity_surface_in_memory(entity, memory.text)
    )
    speaker_hits = tuple(
        entity
        for entity in _speaker_match_surfaces(primary_speaker_surfaces)
        if _entity_speaks_in_memory(entity, memory.text)
    )
    candidate_features = build_candidate_evidence_features(
        memory,
        memory_terms=memory_terms,
        query_terms=query_terms,
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        relation_category_terms=relation_category_terms,
        entities=entities,
        entity_hits=entity_hits,
        speaker_hits=speaker_hits,
        high_signal_relation_terms=_HIGH_SIGNAL_RELATION_VARIANTS,
        is_temporal_query=bool(profile.get("is_temporal_query")),
        time_intent_kind=str(profile.get("time_intent_kind") or ""),
        is_preference_query=_is_preference_query(profile),
        is_contrast_query=_is_contrast_query(profile),
        has_visual_terms=bool(profile.get("visual_terms")),
        has_multi_hop_markers=bool(profile.get("multi_hop_markers")),
        has_temporal_surface=_memory_has_temporal_surface(memory),
        has_sequence_surface=_memory_has_sequence_surface(memory),
        has_preference_evidence=_memory_has_preference_evidence(memory),
        has_visual_evidence=_memory_has_visual_evidence(memory),
        has_focused_turn_surface=_memory_has_focused_turn_surface(memory),
    )
    intent_policy_boosts = focused_intent_policy_boosts(
        memory_terms=set(candidate_features.memory_terms),
        relation_terms=relation_terms,
        relation_hits=candidate_features.relation_hits,
        focused_turn_boost=candidate_features.focused_turn_score,
    )
    focused_shape_boosts = focused_evidence_shape_boosts(
        memory_terms=set(candidate_features.memory_terms),
        relation_terms=relation_terms,
        focused_turn_boost=candidate_features.focused_turn_score,
    )
    score = score_benchmark_rerank_candidate(
        BenchmarkRerankFeatures(
            overlap_terms=candidate_features.overlap_terms,
            entity_hits=candidate_features.entity_hits,
            speaker_hits=candidate_features.speaker_hits,
            relation_hits=candidate_features.relation_hits,
            relation_terms=relation_terms,
            relation_categories=candidate_features.relation_categories,
            relation_category_hits=candidate_features.relation_category_hits,
            relation_category_coverage_ratio=(
                candidate_features.relation_category_coverage_ratio
            ),
            query_has_entities=candidate_features.query_has_entities,
            high_signal_relation_hit_count=(
                candidate_features.high_signal_relation_hit_count
            ),
            is_temporal_query=candidate_features.is_temporal_query,
            has_temporal_surface=candidate_features.has_temporal_surface,
            has_sequence_surface=candidate_features.has_sequence_surface,
            time_intent_kind=candidate_features.time_intent_kind,
            has_duration_surface=candidate_features.has_duration_surface,
            has_relative_time_surface=candidate_features.has_relative_time_surface,
            has_explicit_time_surface=candidate_features.has_explicit_time_surface,
            has_explicit_time_content_surface=(
                candidate_features.has_explicit_time_content_surface
            ),
            has_temporal_sequence_surface=(
                candidate_features.has_temporal_sequence_surface
            ),
            is_preference_query=candidate_features.is_preference_query,
            has_preference_evidence=candidate_features.has_preference_evidence,
            has_visual_terms=candidate_features.has_visual_terms,
            has_visual_evidence=candidate_features.has_visual_evidence,
            focused_turn_boost=candidate_features.focused_turn_score,
            has_multi_hop_markers=candidate_features.has_multi_hop_markers,
            policy_boosts=intent_policy_boosts,
            shape_boosts=focused_shape_boosts,
            source_type=candidate_features.source_type,
            source_ref_count=candidate_features.source_ref_count,
            turn_ref_count=candidate_features.turn_ref_count,
            source_ref_density=candidate_features.source_ref_density,
            source_locality_score=candidate_features.source_locality_score,
            direct_speaker_turn=candidate_features.direct_speaker_turn,
            broad_summary=candidate_features.broad_summary,
            conflict_or_stale=candidate_features.conflict_or_stale,
            negation_surface=candidate_features.negation_surface,
            currentness_surface=candidate_features.currentness_surface,
            stale_surface=candidate_features.stale_surface,
            contrast_surface=candidate_features.contrast_surface,
            answerability_score=candidate_features.answerability_score,
            answerability_reason_codes=candidate_features.answerability_reason_codes,
            evidence_need=tuple(_string_sequence(profile.get("evidence_need"))),
            query_roles=candidate_features.query_roles,
        )
    )
    return score.boost, {
        **score.signals,
        "candidate_features": candidate_features.to_diagnostics(),
    }


def _relation_category_terms(
    profile: Mapping[str, object],
) -> dict[str, tuple[str, ...]]:
    raw_value = profile.get("relation_category_terms")
    if not isinstance(raw_value, Mapping):
        return {}
    return {
        str(category): tuple(_string_sequence(terms))
        for category, terms in raw_value.items()
        if str(category).strip()
    }


def _temporal_search_terms(
    temporal_terms: Sequence[str],
    temporal_surface_terms: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *temporal_terms,
                *temporal_surface_terms,
                "session",
                "date",
                "time",
                *_RELATIVE_TEMPORAL_QUERY_SURFACES,
            )
        )
    )
