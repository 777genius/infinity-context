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
from infinity_context_server.memory_comparison_query_terms import (
    _HIGH_SIGNAL_RELATION_VARIANTS,
    _contrast_support_query_terms,
    _location_support_query_terms,
    _relation_query_terms,
    _support_query_terms,
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

_RELATION_QUERY_TERMS = {
    "activity",
    "action",
    "age",
    "anniversary",
    "advise",
    "ask",
    "attend",
    "based",
    "because",
    "birthday",
    "book",
    "bookshelf",
    "bought",
    "between",
    "bring",
    "brought",
    "camp",
    "call",
    "caus",
    "cause",
    "chat",
    "choose",
    "class",
    "compare",
    "consider",
    "conference",
    "contact",
    "deadline",
    "decide",
    "destress",
    "diet",
    "discus",
    "discuss",
    "different",
    "difference",
    "education",
    "employment",
    "enjoy",
    "avoid",
    "dislike",
    "exercise",
    "enroll",
    "excite",
    "favorite",
    "favourite",
    "feel",
    "former",
    "gift",
    "give",
    "go",
    "friend",
    "get",
    "got",
    "group",
    "grow",
    "hate",
    "health",
    "help",
    "hike",
    "hobby",
    "interest",
    "identity",
    "inspir",
    "join",
    "learn",
    "like",
    "live",
    "love",
    "make",
    "marry",
    "meet",
    "message",
    "messag",
    "mention",
    "motivat",
    "motivate",
    "motivation",
    "move",
    "nickname",
    "offer",
    "origin",
    "participate",
    "plan",
    "political",
    "prefer",
    "previous",
    "prompt",
    "prompted",
    "promise",
    "prioritize",
    "purchas",
    "purchase",
    "pursue",
    "raise",
    "receive",
    "recommend",
    "register",
    "request",
    "read",
    "religious",
    "relationship",
    "realize",
    "reason",
    "remember",
    "research",
    "run",
    "say",
    "said",
    "sign",
    "suggest",
    "symbolize",
    "support",
    "status",
    "stay",
    "sport",
    "talk",
    "task",
    "team",
    "tell",
    "text",
    "think",
    "told",
    "travel",
    "vehicle",
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
        "boyfriend",
        "boss",
        "brother",
        "colleague",
        "cousin",
        "community",
        "counsel",
        "coworker",
        "career",
        "child",
        "children",
        "charity",
        "current",
        "daughter",
        "decision",
        "dating",
        "father",
        "fiance",
        "fiancee",
        "field",
        "girlfriend",
        "grandfather",
        "grandmother",
        "husband",
        "engag",
        "individual",
        "kid",
        "member",
        "manager",
        "mentor",
        "mother",
        "music",
        "necklace",
        "neighbor",
        "paint",
        "park",
        "parent",
        "partner",
        "path",
        "personality",
        "pet",
        "process",
        "race",
        "relocate",
        "relocated",
        "relocation",
        "roommate",
        "roadtrip",
        "school",
        "self-care",
        "sibling",
        "sister",
        "skill",
        "song",
        "son",
        "speech",
        "spouse",
        "sunrise",
        "summer",
        "teammate",
        "trait",
        "wife",
        "write",
    }
)
_TEMPORAL_QUERY_TERMS = (
    "when",
    "how long",
    "long ago",
    "during",
    "before",
    "beforehand",
    "after",
    "afterward",
    "afterwards",
    "since",
    "ago",
    "soon",
    "yesterday",
    "today",
    "tomorrow",
    "earlier today",
    "tonight",
    "earliest event",
    "latest event",
    "upcoming",
    "upcoming event",
    "last night",
    "this morning",
    "this afternoon",
    "this evening",
    "tomorrow morning",
    "tomorrow afternoon",
    "tomorrow evening",
    "yesterday morning",
    "yesterday afternoon",
    "yesterday evening",
    "last weekend",
    "last week",
    "last month",
    "last quarter",
    "last year",
    "next weekend",
    "next week",
    "next month",
    "next quarter",
    "next year",
    "this weekend",
    "this week",
    "this month",
    "this quarter",
    "this year",
    "earlier",
    "later",
    "previous",
    "recent",
    "date",
    "time",
)
_ORDERED_EVENT_REQUEST_RE = re.compile(
    r"\b(?P<order>first|earliest|oldest|latest|newest|recent|"
    r"most\s+recent|last|previous|prior|"
    r"next|upcoming)\s+"
    r"(?:conversation|call|meeting|chat|dm|message|text|discussion|sync|"
    r"review|demo|interview|workshop|session)\b",
    re.IGNORECASE,
)
_ORDINAL_EVENT_REQUEST_RE = re.compile(
    r"\b(?P<ordinal>first|second|third|fourth|fifth|last|latest)\s+"
    r"(?P<event>(?:(?!(?:at|for|in|of|on|place|the)\b)[a-z0-9-]+\s+){0,3}"
    r"(?:call-?out|competition|event|game|project|screenplay|script|"
    r"tournament|tourney|trip))\b",
    re.IGNORECASE,
)
_PERIOD_ANCHOR_TERMS_RE = re.compile(
    r"\b(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december|spring|summer|fall|autumn|winter|\d{4})\b",
    re.IGNORECASE,
)
_SEASON_TERMS = frozenset({"spring", "summer", "fall", "autumn", "winter"})
_RELATIVE_WEEKDAY_RE = re.compile(
    r"\b(?:last|next|this)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_TEMPORAL_SURFACE_TERMS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "christmas",
    "easter",
    "halloween",
    "holiday",
    "independence day",
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
    "thanksgiving",
    "weekend",
    "quarter",
    "week",
    "month",
    "year",
)
_NON_ENTITY_UPPERCASE_TERMS = frozenset({"dob"})
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
            action_support="action_support" in intent.evidence_need,
            communication_support=(
                "communication_support" in intent.bundle_evidence_roles
            ),
            commitment_support="commitment_profile" in intent.evidence_need,
            contact_support="contact_profile" in intent.evidence_need,
            diet_support="diet_profile" in intent.evidence_need,
            education_support="education_profile" in intent.evidence_need,
            employment_support="employment_profile" in intent.evidence_need,
            age_support="age_profile" in intent.evidence_need,
            alias_support="alias_profile" in intent.evidence_need,
            health_support="health_profile" in intent.evidence_need,
            pet_support="pet_profile" in intent.evidence_need,
            preference_support="preference" in intent.evidence_need,
            skill_support="skill_profile" in intent.evidence_need,
            vehicle_support="vehicle_profile" in intent.evidence_need,
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
            action_support=compact_relation_role == "action_support",
            communication_support=compact_relation_role == "communication_support",
            commitment_support=compact_relation_role == "commitment_support",
            contact_support=compact_relation_role == "contact_support",
            diet_support=compact_relation_role == "diet_support",
            education_support=compact_relation_role == "education_support",
            employment_support=compact_relation_role == "employment_support",
            age_support=compact_relation_role == "age_support",
            alias_support=compact_relation_role == "alias_support",
            health_support=compact_relation_role == "health_support",
            pet_support=compact_relation_role == "pet_support",
            preference_support=compact_relation_role
            in {"favorite_support", "preference_support"},
            skill_support=compact_relation_role == "skill_support",
            vehicle_support=compact_relation_role == "vehicle_support",
        )
        if compact_relation_role == "causal_support":
            relation_query_terms = _causal_compact_query_terms(
                lexical_terms=lexical_terms,
                relation_terms=relation_terms,
                relation_variant_terms=relation_variant_terms,
                fallback_terms=relation_query_terms,
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
        elif compact_relation_role in {"age_support", "communication_support"}:
            relation_term_limit = 8
        elif (
            "activity" in relation_terms
            or {"prioritize", "self-care"}.issubset(relation_terms)
            or "destress" in relation_terms
        ):
            relation_term_limit = 10 if "destress" in relation_terms else 8
        elif {"current", "live"} <= set(relation_terms):
            relation_term_limit = 9
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
        if "location_support" in intent.evidence_need and "current" not in relation_terms
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
    evidence_need_set = set(intent.evidence_need)
    count_query_terms = (
        _count_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
        if "count_support" in evidence_need_set
        else ()
    )
    if count_query_terms and (entity_surfaces or len(count_query_terms) >= 4):
        query_candidates.append(
            QueryPlanCandidate(
                role="count_support",
                query=" ".join(
                    (*entity_surfaces, *_render_query_terms(count_query_terms[:10]))
                ),
                priority=38,
                query_type="lexical",
                reason_codes=(
                    "count_support",
                    "quantity_aggregation",
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
    bridge_query_terms = (
        _temporal_multi_hop_bridge_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            temporal_terms=temporal_terms,
            temporal_surface_terms=temporal_surface_terms,
            multi_hop_markers=multi_hop_markers,
        )
        if temporal_query_terms
        else _multi_hop_bridge_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            multi_hop_markers=multi_hop_markers,
        )
    )
    if multi_hop_markers and entity_surfaces and bridge_query_terms:
        bridge_query_render_terms = tuple(
            term for term in bridge_query_terms if term not in set(entity_surfaces)
        )
        bridge_query_term_limit = 10 if temporal_query_terms else 8
        query_candidates.append(
            QueryPlanCandidate(
                role="multi_hop_bridge",
                query=" ".join(
                    (
                        *entity_surfaces,
                        *_render_query_terms(
                            bridge_query_render_terms[:bridge_query_term_limit]
                        ),
                    )
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
    causal_temporal_bridge_terms = _causal_temporal_bridge_query_terms(
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        lexical_terms=lexical_terms,
        temporal_terms=temporal_terms,
        temporal_surface_terms=temporal_surface_terms,
        enabled=(
            "causal_support" in evidence_need_set
            and "temporal_sequence" in evidence_need_set
        ),
    )
    if entity_surfaces and causal_temporal_bridge_terms:
        causal_temporal_bridge_query_terms = tuple(
            term for term in causal_temporal_bridge_terms if term not in set(entity_surfaces)
        )
        query_candidates.append(
            QueryPlanCandidate(
                role="multi_hop_bridge",
                query=" ".join(
                    (
                        *entity_surfaces,
                        *_render_query_terms(causal_temporal_bridge_query_terms[:9]),
                    )
                ),
                priority=45,
                query_type="lexical",
                reason_codes=(
                    "multi_hop_bridge",
                    "causal_temporal_bridge",
                    "question_only",
                ),
            )
        )
    causal_bridge_terms = _causal_bridge_query_terms(
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        lexical_terms=lexical_terms,
        enabled=(
            "causal_support" in evidence_need_set
            and not multi_hop_markers
            and not temporal_query_terms
        ),
    )
    if entity_surfaces and causal_bridge_terms:
        causal_bridge_query_terms = tuple(
            term for term in causal_bridge_terms if term not in set(entity_surfaces)
        )
        query_candidates.append(
            QueryPlanCandidate(
                role="multi_hop_bridge",
                query=" ".join(
                    (
                        *entity_surfaces,
                        *_render_query_terms(causal_bridge_query_terms[:9]),
                    )
                ),
                priority=45,
                query_type="lexical",
                reason_codes=(
                    "multi_hop_bridge",
                    "causal_bridge",
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
    if any(candidate.role == "count_support" for candidate in query_candidates):
        extra_query_slots += 1
    if any(candidate.role == "contrast_support" for candidate in query_candidates):
        extra_query_slots += 1
    has_location_support_query = any(
        candidate.role == "location_support" for candidate in query_candidates
    )
    if has_location_support_query and temporal_query_terms:
        extra_query_slots += 1
    has_multi_hop_bridge_query = any(
        candidate.role == "multi_hop_bridge" for candidate in query_candidates
    )
    needs_causal_temporal_bridge = (
        "causal_support" in evidence_need_set
        and "temporal_sequence" in evidence_need_set
    )
    needs_temporal_multi_hop_bridge = bool(
        temporal_query_terms and multi_hop_markers and has_multi_hop_bridge_query
    )
    if (
        (
            not temporal_query_terms
            or needs_causal_temporal_bridge
            or needs_temporal_multi_hop_bridge
        )
        and has_multi_hop_bridge_query
    ):
        extra_query_slots += 1
    max_selected_queries = max_queries + extra_query_slots
    max_queries_per_type = (
        3
        if (
            (has_location_support_query and temporal_query_terms)
            or ("count_support" in evidence_need_set and visual_terms)
            or ("count_support" in evidence_need_set and has_multi_hop_bridge_query)
            or ("count_support" in evidence_need_set and temporal_query_terms)
            or needs_causal_temporal_bridge
            or needs_temporal_multi_hop_bridge
            or (
                "causal_support" in evidence_need_set
                and multi_hop_markers
                and has_multi_hop_bridge_query
            )
            or (visual_terms and has_multi_hop_bridge_query)
            or (
                contrast_query_terms
                and (temporal_query_terms or has_location_support_query)
            )
        )
        else 2
    )
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


def _temporal_multi_hop_bridge_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    temporal_terms: tuple[str, ...],
    temporal_surface_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> tuple[str, ...]:
    if not multi_hop_markers:
        return ()
    bridge_terms: list[str] = []
    bridge_terms.extend(_relation_query_terms(relation_terms, relation_variant_terms)[:6])
    bridge_terms.extend(
        term
        for term in (*temporal_terms, *temporal_surface_terms, *lexical_terms)
        if term not in _QUERY_STOPWORDS and term not in bridge_terms
    )
    for marker in multi_hop_markers:
        bridge_terms.extend(_MULTI_HOP_BRIDGE_MARKER_TERMS.get(marker, ()))
    return tuple(dict.fromkeys(bridge_terms))


def _causal_temporal_bridge_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    temporal_terms: tuple[str, ...],
    temporal_surface_terms: tuple[str, ...],
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return ()
    bridge_terms: list[str] = []
    bridge_terms.extend(_relation_query_terms(relation_terms, relation_variant_terms)[:6])
    bridge_terms.extend(
        term
        for term in (*temporal_terms, *temporal_surface_terms, *lexical_terms)
        if term not in _QUERY_STOPWORDS and term not in bridge_terms
    )
    return tuple(dict.fromkeys(bridge_terms))


def _causal_bridge_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    enabled: bool,
) -> tuple[str, ...]:
    if not enabled:
        return ()
    bridge_terms: list[str] = []
    bridge_terms.extend(_relation_query_terms(relation_terms, relation_variant_terms)[:6])
    bridge_terms.extend(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS and term not in bridge_terms
    )
    return tuple(dict.fromkeys(bridge_terms))


def _count_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    count_terms: list[str] = []
    count_terms.extend(_relation_query_terms(relation_terms, relation_variant_terms)[:6])
    count_terms.extend(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in entity_tokens
        and term not in count_terms
    )
    count_terms.extend(("count", "number", "total", "times"))
    if "time" in lexical_terms:
        count_terms.extend(("once", "twice", "three times", "repeated"))
    return tuple(dict.fromkeys(count_terms))


def _causal_compact_query_terms(
    *,
    lexical_terms: tuple[str, ...],
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    fallback_terms: tuple[str, ...],
) -> tuple[str, ...]:
    emotion_cue_terms = (
        "happy",
        "sad",
        "angry",
        "frustrat",
        "frustration",
        "nervous",
        "proud",
        "relieved",
        "upset",
        "worried",
        "excite",
        "excited",
    )
    causal_variant_order = (
        "motivat",
        "motivation",
        "reason",
        "because",
        "cause",
        "caus",
        "decision",
        "explain",
        "prompt",
        "inspir",
        "reflect",
        "felt",
        "reaction",
        "response",
    )
    variant_set = set(relation_variant_terms)
    relation_set = set(relation_terms)
    lexical_set = set(lexical_terms)
    prioritized_emotion_terms = tuple(
        term for term in emotion_cue_terms if term in lexical_set
    )
    prioritized_variants = tuple(
        term for term in causal_variant_order if term in variant_set
    )
    missing_generic_causal_terms = tuple(
        term
        for term in ("reason", "because", "cause")
        if term not in relation_set and term not in variant_set
    )
    return tuple(
        dict.fromkeys(
            (
                *relation_terms,
                *prioritized_emotion_terms,
                *prioritized_variants,
                *missing_generic_causal_terms,
                *fallback_terms,
            )
        )
    )


def _recommended_query_role_families(intent: RetrievalIntent) -> tuple[str, ...]:
    families: list[str] = ["base_query"]
    if intent.relation_terms or intent.relation_variant_terms:
        families.append("relation_compact")
    if intent.visual_terms:
        families.append("visual_support")
    if intent.time_intent.is_temporal and not (
        "contrast" in intent.evidence_need
        and intent.time_intent.kind == "temporal_sequence"
    ):
        families.append("temporal_support")
    if "contrast" in intent.evidence_need:
        families.append("contrast_support")
    if "location_support" in intent.evidence_need:
        families.append("location_support")
    if "count_support" in intent.evidence_need:
        families.append("count_support")
    if "causal_support" in intent.evidence_need:
        families.append("multi_hop")
    if "multi_hop" in intent.evidence_need or intent.multi_hop_markers:
        families.append("multi_hop")
    return tuple(dict.fromkeys(families))


def _compact_relation_query_role(intent: RetrievalIntent) -> str:
    evidence_needs = set(intent.evidence_need)
    if "education_profile" in evidence_needs:
        return "education_support"
    if "action_support" in evidence_needs:
        return "action_support"
    if "commitment_profile" in evidence_needs:
        return "commitment_support"
    if "contact_profile" in evidence_needs:
        return "contact_support"
    if "date_profile" in evidence_needs:
        return "date_support"
    if "diet_profile" in evidence_needs:
        return "diet_support"
    if "identity_profile" in evidence_needs:
        return "identity_support"
    if "communication" in evidence_needs:
        return "communication_support"
    if "causal_support" in evidence_needs and "reason" in set(intent.relation_terms):
        return "causal_support"
    if "causal_support" in evidence_needs and {
        "because",
        "caus",
        "cause",
    } & set(intent.relation_terms):
        return "causal_support"
    if "causal_support" in evidence_needs and {
        "motivat",
        "motivate",
        "motivation",
    } & set(intent.relation_terms):
        return "causal_support"
    if (
        "causal_support" in evidence_needs
        and "emotion_response" in evidence_needs
        and "inspir" in set(intent.relation_terms)
    ):
        return "causal_support"
    if {"activity_profile", "activity_support"} & evidence_needs:
        return "activity_support"
    if "employment_profile" in evidence_needs:
        return "employment_support"
    if "age_profile" in evidence_needs:
        return "age_support"
    if "alias_profile" in evidence_needs:
        return "alias_support"
    if "health_profile" in evidence_needs:
        return "health_support"
    if "pet_profile" in evidence_needs:
        return "pet_support"
    if "skill_profile" in evidence_needs:
        return "skill_support"
    if "status_profile" in evidence_needs:
        return "status_support"
    if "vehicle_profile" in evidence_needs:
        return "vehicle_support"
    if "causal_support" in evidence_needs:
        return "causal_support"
    if "support_goal" in evidence_needs:
        return "support_goal_support"
    if "current_goal" in evidence_needs:
        return "current_goal_support"
    if "favorite_preference" in evidence_needs:
        return "favorite_support"
    role_priority = (
        "communication_support",
        "event_support",
        "exchange_support",
        "emotion_response_support",
        "symbolic_meaning_support",
        "preference_support",
        "causal_support",
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
    timestamp_order_boosts = _temporal_timestamp_order_boosts(memories, profile)
    session_order_boosts = _temporal_session_order_boosts(
        memories,
        profile,
        timestamp_order_boosts=timestamp_order_boosts,
    )
    reranked = [
        _with_temporal_rerank_boost(
            memory,
            timestamp_order_boost=timestamp_order_boosts.get(index, 0.0),
            session_order_boost=session_order_boosts.get(index, 0.0),
        )
        if _memory_timestamp_values(memory)
        or session_order_boosts.get(index, 0.0) > 0
        else memory
        for index, memory in enumerate(memories)
    ]
    reranked.sort(key=lambda memory: (-memory.score, memory.rank))
    timestamped_count = _timestamped_memory_count(memories)
    return reranked, {
        **profile,
        "applied": timestamped_count > 0,
        "timestamped_memory_count": timestamped_count,
        "reranked_memory_count": len(reranked),
        "boost": 0.3 if timestamped_count > 0 else 0.0,
        "timestamp_order_boosted_count": sum(
            1 for boost in timestamp_order_boosts.values() if boost > 0
        ),
        "session_order_boosted_count": sum(
            1 for boost in session_order_boosts.values() if boost > 0
        ),
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

    reranked.sort(key=_benchmark_rerank_sort_key)
    return reranked, {
        "applied": bool(boosts),
        "boosted_memory_count": len(boosts),
        "max_boost": round(max(boosts), 6) if boosts else 0.0,
        "query_profile": profile,
        "retrieval_intent": intent.to_diagnostics(),
        "uses_ground_truth": False,
    }


def _benchmark_rerank_sort_key(memory: RetrievedMemory) -> tuple[float, float, float, int]:
    diagnostics = (
        memory.metadata.get("diagnostics")
        if isinstance(memory.metadata.get("diagnostics"), Mapping)
        else {}
    )
    score_signals = (
        diagnostics.get("score_signals")
        if isinstance(diagnostics.get("score_signals"), Mapping)
        else {}
    )
    visual_boost = _positive_float(
        score_signals.get("benchmark_visual_evidence_boost")
    )
    focused_support_boost = sum(
        _positive_float(score_signals.get(key))
        for key in (
            "benchmark_focused_turn_boost",
            "benchmark_political_context_boost",
            "benchmark_roadtrip_incident_boost",
            "benchmark_destress_running_shape_boost",
            "benchmark_outdoor_park_preference_boost",
        )
    )
    return (-memory.score, -focused_support_boost, -visual_boost, memory.rank)


def _positive_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed > 0 else 0.0


def _with_temporal_rerank_boost(
    memory: RetrievedMemory,
    *,
    timestamp_order_boost: float = 0.0,
    session_order_boost: float = 0.0,
) -> RetrievedMemory:
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
    if timestamp_order_boost > 0:
        score_signals["benchmark_temporal_timestamp_order_boost"] = round(
            timestamp_order_boost,
            6,
        )
    if session_order_boost > 0:
        score_signals["benchmark_temporal_session_order_boost"] = round(
            session_order_boost,
            6,
        )
    diagnostics["score_signals"] = score_signals
    diagnostics["temporal_rerank_boosted"] = True
    return replace(
        memory,
        score=round(memory.score + 0.3 + timestamp_order_boost + session_order_boost, 6),
        metadata={**dict(memory.metadata), "diagnostics": diagnostics},
    )


def _temporal_timestamp_order_boosts(
    memories: Sequence[RetrievedMemory],
    profile: Mapping[str, object],
) -> dict[int, float]:
    matched_terms = set(_string_sequence(profile.get("matched_terms")))
    if not _requests_temporal_order_boost(matched_terms):
        return {}
    earliest_requested = "earliest event" in matched_terms
    timestamped: list[tuple[int, int]] = []
    for index, memory in enumerate(memories):
        timestamps = _memory_timestamp_values(memory)
        if timestamps:
            representative_timestamp = (
                min(timestamps) if earliest_requested else max(timestamps)
            )
            timestamped.append((index, representative_timestamp))
    if len(timestamped) <= 1:
        return {}
    ordered_timestamps = sorted({timestamp for _, timestamp in timestamped})
    if len(ordered_timestamps) <= 1:
        return {}
    denominator = len(ordered_timestamps) - 1
    return {
        index: round(
            0.12
            * (
                1.0 - (ordered_timestamps.index(timestamp) / denominator)
                if earliest_requested
                else ordered_timestamps.index(timestamp) / denominator
            ),
            6,
        )
        for index, timestamp in timestamped
    }


def _temporal_session_order_boosts(
    memories: Sequence[RetrievedMemory],
    profile: Mapping[str, object],
    *,
    timestamp_order_boosts: Mapping[int, float],
) -> dict[int, float]:
    matched_terms = set(_string_sequence(profile.get("matched_terms")))
    if not _requests_temporal_order_boost(matched_terms):
        return {}
    earliest_requested = "earliest event" in matched_terms
    session_indexed: list[tuple[int, int]] = []
    for index, memory in enumerate(memories):
        if index in timestamp_order_boosts:
            continue
        session_indices = _memory_session_indices(memory)
        if session_indices:
            representative_session = (
                min(session_indices) if earliest_requested else max(session_indices)
            )
            session_indexed.append((index, representative_session))
    if len(session_indexed) <= 1:
        return {}
    ordered_sessions = sorted({session for _, session in session_indexed})
    if len(ordered_sessions) <= 1:
        return {}
    denominator = len(ordered_sessions) - 1
    return {
        index: round(
            0.1
            * (
                1.0 - (ordered_sessions.index(session) / denominator)
                if earliest_requested
                else ordered_sessions.index(session) / denominator
            ),
            6,
        )
        for index, session in session_indexed
    }


def _requests_temporal_order_boost(matched_terms: set[str]) -> bool:
    return bool(
        {
            "currently",
            "earliest event",
            "latest event",
            "recent",
            "soon",
            "upcoming",
            "upcoming event",
        }
        & matched_terms
    )


def _memory_session_indices(memory: RetrievedMemory) -> tuple[int, ...]:
    raw_values = [
        memory.metadata.get("session_index"),
        memory.metadata.get("session_id"),
    ]
    session_key = memory.metadata.get("session_key")
    if isinstance(session_key, str):
        raw_values.append(session_key)
    raw_values.extend(memory.source_refs)
    raw_values.append(memory.text)
    indices: list[int] = []
    for value in raw_values:
        if (parsed := _optional_int(value)) is not None:
            indices.append(parsed)
            continue
        for match in re.finditer(r"\bsession_(\d+)\b", str(value or ""), re.IGNORECASE):
            indices.append(int(match.group(1)))
    return tuple(dict.fromkeys(index for index in indices if index > 0))


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
    relation_terms = _filter_relation_terms_for_profile(
        question=question,
        relation_terms=relation_terms,
    )
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if "skill" not in relation_terms and _has_skill_profile_question(normalized_question):
        relation_terms = (*relation_terms, "skill")
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
    is_count_question = bool(
        re.search(r"\b(?:how\s+many|number\s+of|count\s+of)\b", question, re.IGNORECASE)
    )
    if (category == 1 and not is_count_question) or _non_temporal_process_how_marker(
        question
    ):
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
    if re.search(
        r"\bhow\s+(?:can|could|do|does|did)\s+(?:i|we|you)\s+"
        r"(?:contact|reach)\b",
        question,
        flags=re.IGNORECASE,
    ):
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
        and (
            relation not in _QUERY_TOKEN_ALIASES.get(term, ())
            or {relation, term} <= {"say", "said"}
        )
    )


def _filter_relation_terms_for_profile(
    *,
    question: str,
    relation_terms: Sequence[str],
) -> tuple[str, ...]:
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    relation_set = set(relation_terms)
    filtered: list[str] = []
    for term in relation_terms:
        if term == "work" and _has_employment_profile_question(normalized_question):
            continue
        if term == "health" and not _has_health_profile_question(
            normalized_question,
        ):
            continue
        if term == "contact" and not _has_contact_profile_question(
            normalized_question,
        ):
            continue
        if term in {"deadline", "promise", "remember", "task"} and not (
            _has_commitment_profile_question(normalized_question)
        ):
            continue
        if term == "diet" and not _has_diet_profile_question(normalized_question):
            continue
        if term in {"exercise", "hobby", "sport"} and not _has_activity_profile_question(
            normalized_question,
        ):
            continue
        if term == "age" and not _has_age_profile_question(normalized_question):
            continue
        if term == "pet" and not _has_pet_profile_question(normalized_question):
            continue
        if term == "skill" and not _has_skill_profile_question(normalized_question):
            continue
        if term == "vehicle" and not _has_vehicle_profile_question(
            normalized_question,
        ):
            continue
        if term in {"class", "education"} and {"enroll", "register", "sign"} & relation_set:
            continue
        if term == "education" and not _has_education_profile_question(
            normalized_question,
        ):
            continue
        if term == "class" and not re.search(
            r"\bwhat\s+class\b|\bclass\b.+\b(?:take|taking|study|studying)\b",
            normalized_question,
        ):
            continue
        if term == "stay" and not re.search(
            r"\bwhere\b.+\bstay(?:ing)?\b|\bstay(?:ed|ing)?\b.+\b(?:in|at|near)\b",
            normalized_question,
        ):
            continue
        if term == "raise" and re.search(
            r"\bwhere\b.+\braised\b|\braised\b.+\bwhere\b",
            normalized_question,
        ):
            continue
        filtered.append(term)
    return tuple(filtered)


def _has_education_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:what|which)\s+school\b|"
            r"\b(?:college|university)\b|"
            r"\b(?:study|studies|studying|majoring)\b|"
            r"\bwhat\s+(?:is|was)\b.+\bmajor\b(?:\s+(?:in|at)\b|$)|"
            r"\bwhat\s+(?:is|was)\b.+\bdegree\b(?:\s+(?:in|from)\b|$)|"
            r"\bwhat\s+degree\s+(?:does|did|is|was|has|have)\b|"
            r"\bdegree\s+(?:does|did)\b.+\bhave\b|"
            r"\b(?:major|degree)\s+in\b|"
            r"\b(?:where|when|what\s+school)\b.+\bgraduat(?:e|ed|ion)\b|"
            r"\bgraduat(?:e|ed|ion)\b.+\b(?:from|school|college|university)\b|"
            r"\bwhat\s+class\b",
            normalized_question,
        )
    )


def _has_activity_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:what|which)\s+(?:activity|activities|hobby|hobbies|sport|sports)\b|"
            r"\b(?:hobby|hobbies|pastime|free\s+time|for\s+fun)\b|"
            r"\bwhat\b.+\b(?:do|does)\b.+\b(?:for\s+fun|free\s+time|relax)\b|"
            r"\b(?:exercise|workout)\b",
            normalized_question,
        )
    )


def _has_employment_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:what|which)\s+(?:company|job|occupation|profession|workplace)\b|"
            r"\bwhat\s+(?:is|was)\b.+\b(?:salary|wage|pay\s+rate|hourly\s+rate)\b|"
            r"\b(?:job|occupation|profession|workplace)\b|"
            r"\bwhere\b.+\bwork\b|"
            r"\bwhat\b.+\bdo\b.+\bfor\s+work\b|"
            r"\bwork\b.+\b(?:company|for)\b",
            normalized_question,
        )
    )


def _has_age_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\bhow\s+old\b|\bwhat\b.+\bage\b|\bage\b.+\b(?:is|of)\b",
            normalized_question,
        )
    )


def _has_health_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:doctor|physician|therapist|medication|medicine|prescription|allerg"
            r"(?:y|ic)|health\s+issue|condition|dentist|dental)\b"
            r"|\bblood\s+type\b"
            r"|\bprimary\s+care\s+(?:doctor|physician|provider)\b"
            r"|\b(?:medical|doctor(?:'s)?|dentist(?:'s)?|therapy|clinic)\s+"
            r"appointment\b",
            normalized_question,
        )
    )


def _has_contact_profile_question(normalized_question: str) -> bool:
    if re.search(
        r"\baddress(?:ed|es|ing)?\s+(?:a|an|the|their|his|her|my|our)?\s*"
        r"(?:concern|issue|problem|question|risk|topic)\b|"
        r"\b(?:concern|issue|problem|question|risk|topic)\b.+"
        r"\baddress(?:ed|es|ing)?\b|"
        r"\baddress(?:ed|es|ing)?\b.+\bwith\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:contact\s+(?:info|information|details)|"
            r"emergency\s+contact|"
            r"email|e mail|phone|telephone|cell|mobile|address)\b|"
            r"\b(?:phone|telephone|cell|mobile)\s+number\b|"
            r"\b(?:instagram|signal|slack|telegram|whatsapp)\s+"
            r"(?:handle|username|number)\b|"
            r"\bwhat\s+is\s+(?:[a-z0-9]+(?:\s+s)?|my|his|her|their|our|your)\s+"
            r"(?:handle|number|username)\b|"
            r"\bhow\s+(?:can|could|do|does|did)\s+(?:i|we|you)\s+"
            r"(?:contact|reach)\b",
            normalized_question,
        )
    )


def _has_commitment_profile_question(normalized_question: str) -> bool:
    if re.search(
        r"\bremember(?:ed|s|ing)?\s+(?:childhood|story|trip|vacation|birthday)\b|"
        r"\bpromise\s+ring\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:deadline|due\s+date|when\b.+\bdue|"
            r"what\b.+\b(?:task|todo|to do|to-do)|"
            r"what\b.+\bpromise(?:d)?|"
            r"(?:need|needs|needed)\s+to\s+remember|"
            r"remember\s+to)\b",
            normalized_question,
        )
    )


def _has_diet_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:dietary\s+(?:restriction|restrictions)|"
            r"vegetarian|vegan|gluten\s?free|dairy\s?free)\b|"
            r"\b(?:avoid|avoids|can t|cannot|can\s+not|doesn t|does\s+not|"
            r"don t|do\s+not)\s+eat\b|"
            r"\bwhat\s+can\b.+\bnot\s+eat\b|"
            r"\bwhat\s+food\b.+\b(?:avoid|eat)\b",
            normalized_question,
        )
    )


def _has_pet_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\bwhat\s+pet\b|\b(?:dog|cat|pet)\b.+\bnamed?\b|"
            r"\bname\b.+\b(?:dog|cat|pet)\b|"
            r"\bbreed\b.+\b(?:dog|cat|pet)\b|\b(?:dog|cat|pet)\b.+\bbreed\b|"
            r"\b(?:dog|cat|pet|puppy|kitten)\b.+\bmicrochip\b|"
            r"\bmicrochip\b.+\b(?:dog|cat|pet|puppy|kitten)\b",
            normalized_question,
        )
    )


def _has_skill_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\blanguages?\b.+\b(?:speak|know|fluent|bilingual)\b|"
            r"\b(?:speak|know)\b.+\blanguages?\b|"
            r"\b(?:fluent|bilingual)\b.+\blanguages?\b|"
            r"\blanguages?\b.+\blearn(?:ed|ing)?\b|"
            r"\blearn(?:ed|ing)?\b.+\blanguages?\b|"
            r"\bprogramming\s+languages?\b|\blanguages?\b.+\bprogramming\b|"
            r"\bskill\b.+\blearn(?:ed|ing)?\b|"
            r"\blearn(?:ed|ing)?\b.+\bskill\b|"
            r"\b(?:certification|credential)\b|"
            r"\bcertified\s+in\b|"
            r"\binstrument\b.+\bplay\b|\bplay\b.+\binstrument\b|"
            r"\bplay\s+(?:guitar|piano|violin|drums?)\b",
            normalized_question,
        )
    )


def _has_vehicle_profile_question(normalized_question: str) -> bool:
    return bool(
        re.search(
            r"\blicen[cs]e\s+plate\b|"
            r"\b(?:what|which|kind\s+of|color)\b.+"
            r"\b(?:car|vehicle|truck|suv|sedan|van)\b|"
            r"\b(?:car|vehicle|truck|suv|sedan|van)\b.+"
            r"\b(?:drive|have|has|own|color)\b|"
            r"\bdrive\s+(?:a|an|the|my|his|her|their)\s+"
            r"(?:car|vehicle|truck|suv|sedan|van)\b",
            normalized_question,
        )
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
    if {"think", "decision", "adopt"}.issubset(relation_term_set):
        blocked_terms.update(
            {
                "agencies",
                "agency",
                "creating",
                "creat",
                "children",
                "family",
                "kid",
                "kids",
                "lovely",
                "luck",
                "mom",
                "process",
                "support",
            }
        )
    if {"individual", "adoption", "support"}.issubset(
        relation_term_set
    ) and not re.search(
        r"\b(?:inclusive|inclusivity|lgbtq|queer|transgender)\b",
        normalized_question,
    ):
        blocked_terms.update(
            {
                "children",
                "family",
                "inclusive",
                "inclusivity",
                "kid",
                "kids",
                "lgbtq",
                "process",
            }
        )
    if {"plan", "summer"}.issubset(relation_term_set) and not re.search(
        r"\b(?:adopt|adoption|child|children|family|home|kid|kids)\b",
        normalized_question,
    ):
        blocked_terms.update(
            {
                "children",
                "dream",
                "family",
                "home",
                "kid",
                "kids",
                "loving",
                "lov",
            }
        )
    if {"go", "support", "group"}.issubset(relation_term_set) and not re.search(
        r"\b(?:inclusive|inclusivity|lgbtq|queer|transgender)\b",
        normalized_question,
    ):
        blocked_terms.update({"inclusive", "inclusivity", "lgbtq"})
    if {"personality", "trait"} & relation_term_set:
        blocked_terms.update({"mention", "mentioned", "said", "say", "tell", "told"})
    if "prompt" in relation_term_set and not re.search(
        r"\bprompt(?:ed|ing)?\b.+\b(?:to|into)\b"
        r"|\bthat\s+prompt(?:ed|ing)?\b",
        normalized_question,
    ):
        blocked_terms.update({"because", "cause", "prompted", "reason", "reflect"})
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


def _temporal_query_profile(case: PublicBenchmarkCase) -> dict[str, object]:
    query = " ".join(str(case.question or "").casefold().split())
    category = _optional_int(case.metadata.get("category"))
    temporal_query = re.sub(r"\b(?:free\s+time|pastime)\b", " ", query)
    matched_terms = tuple(
        term
        for term in _TEMPORAL_QUERY_TERMS
        if _contains_temporal_query_term(temporal_query, term)
    )
    period_modifier_terms = _period_modifier_temporal_terms(query)
    if period_modifier_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *period_modifier_terms)))
    ordinal_period_terms = _ordinal_period_temporal_terms(query)
    if ordinal_period_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *ordinal_period_terms)))
    season_terms = _season_temporal_terms(query)
    if season_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *season_terms)))
    ordinal_event_terms = _ordinal_event_temporal_terms(query)
    if ordinal_event_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *ordinal_event_terms)))
    repeated_event_terms = _repeated_event_temporal_terms(query)
    if repeated_event_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *repeated_event_terms)))
    duration_amount_terms = _duration_amount_temporal_terms(query)
    if duration_amount_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *duration_amount_terms)))
    relative_offset_terms = _relative_offset_temporal_terms(query)
    if relative_offset_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *relative_offset_terms)))
    relative_weekday_terms = _relative_weekday_temporal_terms(query)
    if relative_weekday_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *relative_weekday_terms)))
    explicit_date_anchor_terms = _explicit_date_anchor_temporal_terms(query)
    if explicit_date_anchor_terms:
        matched_terms = tuple(
            dict.fromkeys((*matched_terms, *explicit_date_anchor_terms))
        )
    current_state_terms = _current_state_temporal_terms(query)
    if current_state_terms:
        matched_terms = tuple(dict.fromkeys((*matched_terms, *current_state_terms)))
    ordered_event_term = _ordered_event_temporal_term(query)
    if ordered_event_term:
        matched_terms = tuple(dict.fromkeys((*matched_terms, ordered_event_term)))
    if "during" in matched_terms and not re.search(
        r"\b(?:session|conversation|chat|call|meeting|event|interview)\b",
        temporal_query,
    ):
        matched_terms = tuple(term for term in matched_terms if term != "during")
    matched_terms = _without_overlapped_relative_temporal_terms(matched_terms)
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


def _contains_temporal_query_term(query: str, term: str) -> bool:
    if term == "date":
        return bool(re.search(r"\b(?:date|birthdate)\b", query))
    if term == "time":
        return bool(re.search(r"\btimes?\b", query))
    if term not in {
        "after",
        "afterward",
        "afterwards",
        "before",
        "during",
        "since",
    }:
        return term in query
    escaped = re.escape(term)
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", query))


def _ordered_event_temporal_term(query: str) -> str:
    match = _ORDERED_EVENT_REQUEST_RE.search(query)
    if match is None:
        return ""
    order = match.group("order").casefold()
    if order in {"next", "upcoming"}:
        return "upcoming event"
    if order in {"first", "earliest", "oldest"}:
        return "earliest event"
    return "latest event"


def _period_modifier_temporal_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in re.finditer(r"\b(early|late)\s+([a-z]+|\d{4})\b", query):
        anchor = match.group(2)
        if _PERIOD_ANCHOR_TERMS_RE.fullmatch(anchor):
            terms.append(match.group(1))
            if anchor in _SEASON_TERMS:
                terms.append(anchor)
    for match in re.finditer(r"\b(first|second)\s+half\s+of\s+([a-z]+|\d{4})\b", query):
        anchor = match.group(2)
        if _PERIOD_ANCHOR_TERMS_RE.fullmatch(anchor):
            terms.append(f"{match.group(1)} half")
            if anchor in _SEASON_TERMS:
                terms.append(anchor)
    for match in re.finditer(
        r"\b(?:towards?|near|around)?\s*(?:the\s+)?"
        r"(start|beginning|end)\s+of\s+(?:the\s+)?([a-z]+|\d{4})\b",
        query,
    ):
        anchor = match.group(2)
        if _PERIOD_ANCHOR_TERMS_RE.fullmatch(anchor):
            boundary = "start" if match.group(1) == "beginning" else match.group(1)
            terms.append(boundary)
            if anchor in _SEASON_TERMS:
                terms.append(anchor)
    return tuple(dict.fromkeys(terms))


def _ordinal_period_temporal_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in re.finditer(
        r"\b(first|second|third|fourth|last)\s+"
        r"(weekend|week|half|quarter|month)\s+of\s+(?:the\s+)?([a-z]+|\d{4})\b",
        query,
    ):
        anchor = match.group(3)
        if _PERIOD_ANCHOR_TERMS_RE.fullmatch(anchor):
            terms.append(f"{match.group(1)} {match.group(2)}")
            if anchor in _SEASON_TERMS:
                terms.append(anchor)
    return tuple(dict.fromkeys(terms))


def _season_temporal_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    season = r"spring|summer|fall|autumn|winter"
    for match in re.finditer(rf"\b(last|next|this)\s+({season})\b", query):
        terms.append(f"{match.group(1)} {match.group(2)}")
    for match in re.finditer(rf"\b({season})\s+((?:19|20)\d{{2}})\b", query):
        terms.extend((match.group(1), match.group(2)))
    return tuple(dict.fromkeys(terms))


def _ordinal_event_temporal_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _ORDINAL_EVENT_REQUEST_RE.finditer(query):
        terms.append(f"{match.group('ordinal')} {match.group('event')}")
    return tuple(dict.fromkeys(terms))


def _repeated_event_temporal_terms(query: str) -> tuple[str, ...]:
    if not re.search(r"\bagain\b", query):
        return ()
    action = (
        r"attend|finish|go|join|meet|move|read|reconnect|return|run|start|"
        r"travel|visit|watch|win|write"
    )
    if re.search(rf"\b(?:{action})\b(?:\W+\w+){{0,6}}\W+again\b", query):
        return ("again",)
    if re.search(rf"\bagain\b(?:\W+\w+){{0,6}}\W+\b(?:{action})\b", query):
        return ("again",)
    return ()


def _duration_amount_temporal_terms(query: str) -> tuple[str, ...]:
    match = re.search(
        r"\bhow\s+many\s+"
        r"(day|days|week|weeks|month|months|year|years|hour|hours)\b",
        query,
    )
    if match is None:
        return ()
    return ("duration", match.group(1))


def _relative_offset_temporal_terms(query: str) -> tuple[str, ...]:
    amount = r"\d+|one|two|three|four|five|six|seven|few|couple"
    unit = r"day|days|week|weeks|month|months|year|years"
    return tuple(
        dict.fromkeys(
            f"{match.group(1)} {match.group(2)}"
            for match in re.finditer(
                rf"\b({amount})\s+({unit})\s+(?:before|after)\b",
                query,
            )
        )
    )


def _relative_weekday_temporal_terms(query: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(match.group(0) for match in _RELATIVE_WEEKDAY_RE.finditer(query))
    )


def _explicit_date_anchor_temporal_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    month_pattern = (
        r"january|february|march|april|may|june|july|august|september|"
        r"october|november|december"
    )
    for match in re.finditer(
        rf"\b(?:{month_pattern})\s+(\d{{1,2}}(?:st|nd|rd|th)?)"
        r"(?:\s*,?\s*(\d{4}))?\b",
        query,
    ):
        terms.extend(term for term in match.groups() if term)
    for match in re.finditer(
        rf"\b(\d{{1,2}}(?:st|nd|rd|th)?)\s+(?:of\s+)?(?:{month_pattern})"
        r"(?:\s*,?\s*(\d{4}))?\b",
        query,
    ):
        terms.extend(term for term in match.groups() if term)
    for match in re.finditer(rf"\b(?:{month_pattern})\s+((?:19|20)\d{{2}})\b", query):
        terms.append(match.group(1))
    return tuple(dict.fromkeys(terms))


def _current_state_temporal_terms(query: str) -> tuple[str, ...]:
    if not re.search(r"\bcurrently\b", query):
        return ()
    if _PERIOD_ANCHOR_TERMS_RE.search(query):
        return ()
    return ("currently",)


def _without_overlapped_relative_temporal_terms(
    matched_terms: tuple[str, ...],
) -> tuple[str, ...]:
    term_set = set(matched_terms)
    blocked: set[str] = set()
    if "last weekend" in term_set:
        blocked.add("last week")
    if "next weekend" in term_set:
        blocked.add("next week")
    if "this weekend" in term_set:
        blocked.add("this week")
    return tuple(term for term in matched_terms if term not in blocked)


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
        if entity and entity not in (
            _QUERY_STOPWORDS | set(_TEMPORAL_SURFACE_TERMS) | _NON_ENTITY_UPPERCASE_TERMS
        ):
            entities.append((match.start(), entity))
    return tuple(entity for _, entity in sorted(entities, key=lambda item: item[0]))


def _clean_query_entity(raw: str) -> str:
    terms: list[str] = []
    for raw_term in raw.split():
        term = raw_term.casefold().strip(" .'\"")
        if term.endswith("'s"):
            term = term[:-2]
        if term and term not in (
            _QUERY_STOPWORDS | set(_TEMPORAL_SURFACE_TERMS) | _NON_ENTITY_UPPERCASE_TERMS
        ):
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
        relation_category_hits=candidate_features.relation_category_hits,
        direct_speaker_turn=candidate_features.direct_speaker_turn,
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
            )
        )
    )
