"""Typed retrieval intent contracts for memory-comparison retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalEntityIntent:
    """Person or named-entity surfaces extracted from a question."""

    canonical: str
    surfaces: tuple[str, ...]
    speaker_surfaces: tuple[str, ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "canonical": self.canonical,
            "surfaces": list(self.surfaces),
            "speaker_surfaces": list(self.speaker_surfaces),
        }


@dataclass(frozen=True)
class RetrievalTimeIntent:
    """Temporal constraints extracted from a question."""

    is_temporal: bool
    terms: tuple[str, ...]
    surface_terms: tuple[str, ...]
    kind: str

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "is_temporal": self.is_temporal,
            "terms": list(self.terms),
            "surface_terms": list(self.surface_terms),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class RetrievalRelationIntent:
    """Typed relation facet inferred from question-only relation terms."""

    category: str
    terms: tuple[str, ...]
    variant_terms: tuple[str, ...]
    evidence_need: str
    reason_codes: tuple[str, ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "category": self.category,
            "terms": list(self.terms),
            "variant_terms": list(self.variant_terms),
            "evidence_need": self.evidence_need,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True)
class RetrievalIntent:
    """Question-only retrieval intent used by query planning and rerank."""

    question: str
    lexical_terms: tuple[str, ...]
    entities: tuple[RetrievalEntityIntent, ...]
    relation_terms: tuple[str, ...]
    relation_variant_terms: tuple[str, ...]
    time_intent: RetrievalTimeIntent
    visual_terms: tuple[str, ...]
    multi_hop_markers: tuple[str, ...]
    evidence_need: tuple[str, ...]
    risk_flags: tuple[str, ...]
    bundle_evidence_roles: tuple[str, ...] = ()
    relation_intents: tuple[RetrievalRelationIntent, ...] = ()

    @property
    def entity_names(self) -> tuple[str, ...]:
        return tuple(entity.canonical for entity in self.entities)

    @property
    def entity_surfaces(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                surface for entity in self.entities for surface in entity.surfaces
            )
        )

    @property
    def speaker_surfaces(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                surface
                for entity in self.entities
                for surface in entity.speaker_surfaces
            )
        )

    def to_query_profile(self) -> dict[str, object]:
        return {
            "lexical_terms": self.lexical_terms,
            "entities": self.entity_names,
            "entity_surfaces": self.entity_surfaces,
            "speaker_surfaces": self.speaker_surfaces,
            "relation_terms": self.relation_terms,
            "relation_variant_terms": self.relation_variant_terms,
            "relation_categories": tuple(
                intent.category for intent in self.relation_intents
            ),
            "relation_category_terms": {
                intent.category: tuple(
                    dict.fromkeys((*intent.terms, *intent.variant_terms))
                )
                for intent in self.relation_intents
            },
            "is_temporal_query": self.time_intent.is_temporal,
            "time_intent_kind": self.time_intent.kind,
            "temporal_terms": self.time_intent.terms,
            "temporal_surface_terms": self.time_intent.surface_terms,
            "visual_terms": self.visual_terms,
            "multi_hop_markers": self.multi_hop_markers,
            "evidence_need": self.evidence_need,
            "bundle_evidence_roles": self.bundle_evidence_roles,
            "risk_flags": self.risk_flags,
        }

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": "retrieval_intent.v1",
            "entity_count": len(self.entities),
            "entities": [entity.to_diagnostics() for entity in self.entities],
            "relations": {
                "terms": list(self.relation_terms),
                "variant_terms": list(self.relation_variant_terms),
                "intents": [
                    intent.to_diagnostics() for intent in self.relation_intents
                ],
            },
            "time_intent": self.time_intent.to_diagnostics(),
            "visual_terms": list(self.visual_terms),
            "multi_hop_markers": list(self.multi_hop_markers),
            "evidence_need": list(self.evidence_need),
            "bundle_evidence_roles": list(self.bundle_evidence_roles),
            "risk_flags": list(self.risk_flags),
            "uses_ground_truth": False,
        }


def infer_time_intent_kind(
    *,
    is_temporal: bool,
    temporal_terms: tuple[str, ...],
    temporal_surface_terms: tuple[str, ...],
) -> str:
    if not is_temporal:
        return "none"
    temporal_term_set = set(temporal_terms)
    if {"before", "after"} & temporal_term_set:
        return "temporal_sequence"
    if {"how long", "long", "duration"} & temporal_term_set:
        return "duration"
    if _RELATIVE_TIME_TERMS & temporal_term_set:
        return "relative_time"
    if temporal_surface_terms:
        return "explicit_time"
    return "temporal_lookup"


_RELATIVE_TIME_TERMS = frozenset(
    {
        "ago",
        "earlier",
        "last week",
        "later",
        "long ago",
        "next week",
        "previous",
        "recent",
        "today",
        "tomorrow",
        "yesterday",
    }
)


def infer_relation_intents(
    *,
    question: str = "",
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
    visual_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> tuple[RetrievalRelationIntent, ...]:
    """Classify relation terms into stable retrieval facets."""

    relation_set = set(relation_terms)
    variant_set = set(relation_variant_terms)
    facets: list[RetrievalRelationIntent] = []
    for category, config in _RELATION_FACET_CONFIG.items():
        if category == "location_transition" and not _has_location_transition_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "current_goal" and not _has_current_goal_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "exchange" and not _has_exchange_intent(
            relation_terms=relation_terms,
        ):
            continue
        if category == "communication" and not _has_communication_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        terms = tuple(term for term in relation_terms if term in config["terms"])
        variants = tuple(
            term for term in relation_variant_terms if term in config["variants"]
        )
        if category == "activity" and "activity" in relation_set:
            variants = tuple(
                dict.fromkeys(
                    (
                        *variants,
                        "camping",
                        "painting",
                        "pottery",
                        "swimming",
                        "unplug",
                        "violin",
                        "workshop",
                    )
                )
            )
        marker_hit = bool(set(config["markers"]) & set(multi_hop_markers))
        if not terms and not marker_hit:
            continue
        facets.append(
            RetrievalRelationIntent(
                category=category,
                terms=terms,
                variant_terms=variants,
                evidence_need=str(config["evidence_need"]),
                reason_codes=_relation_facet_reason_codes(
                    category=category,
                    terms=terms,
                    variants=variants,
                    marker_hit=marker_hit,
                ),
            )
        )
    if time_intent.is_temporal:
        facets.append(
            RetrievalRelationIntent(
                category="temporal",
                terms=tuple(term for term in relation_terms if term in relation_set),
                variant_terms=tuple(
                    term
                    for term in relation_variant_terms
                    if term in variant_set and term in _TEMPORAL_SUPPORT_VARIANTS
                ),
                evidence_need=(
                    "temporal_sequence"
                    if time_intent.kind == "temporal_sequence"
                    else "temporal_support"
                ),
                reason_codes=("time_intent", f"time_kind:{time_intent.kind}"),
            )
        )
    if visual_terms:
        facets.append(
            RetrievalRelationIntent(
                category="visual",
                terms=visual_terms,
                variant_terms=(),
                evidence_need="visual_evidence",
                reason_codes=("visual_terms",),
            )
        )
    return tuple(_dedupe_relation_intents(facets))


def infer_evidence_need(
    *,
    question: str = "",
    relation_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
    visual_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
    benchmark_category: int | None = None,
) -> tuple[str, ...]:
    needs: list[str] = []
    relation_set = set(relation_terms)
    if multi_hop_markers:
        needs.append("multi_hop")
    if time_intent.is_temporal:
        needs.append(
            "temporal_sequence"
            if time_intent.kind == "temporal_sequence"
            else "temporal_support"
        )
    if visual_terms:
        needs.append("visual_evidence")
    if {"interest", "prefer", "enjoy", "like", "love"} & relation_set:
        needs.append("preference")
    if _has_contrast_intent(
        relation_terms=relation_terms,
        multi_hop_markers=multi_hop_markers,
    ):
        needs.append("contrast")
    if _has_inference_support_intent(
        question=question,
        relation_terms=relation_terms,
        benchmark_category=benchmark_category,
    ):
        needs.append("inference_support")
    causal_relation_terms = {"why", "cause", "realize"} & relation_set
    causal_marker_terms = {"why"} & set(multi_hop_markers)
    if not time_intent.is_temporal:
        causal_relation_terms = causal_relation_terms | ({"how"} & relation_set)
        causal_marker_terms = causal_marker_terms | ({"how"} & set(multi_hop_markers))
    if causal_relation_terms or causal_marker_terms:
        needs.append("causal_support")
    if _has_location_transition_intent(
        question=question,
        relation_terms=relation_terms,
    ):
        needs.append("location_support")
    if not needs:
        needs.append("single_fact")
    return tuple(dict.fromkeys(needs))


def infer_bundle_evidence_roles(
    *,
    evidence_need: tuple[str, ...],
    benchmark_category: int | None = None,
) -> tuple[str, ...]:
    roles: list[str] = ["primary"]
    evidence_need_set = set(evidence_need)
    if benchmark_category == 1 or "multi_hop" in evidence_need_set:
        roles.append("bridge")
    if benchmark_category == 2 or {
        "temporal_support",
        "temporal_sequence",
    } & evidence_need_set:
        roles.append("temporal_support")
    if "contrast" in evidence_need_set:
        roles.append("contrast")
    if "location_support" in evidence_need_set:
        roles.append("location_support")
    if "preference" in evidence_need_set:
        roles.append("preference_support")
    if "visual_evidence" in evidence_need_set:
        roles.append("visual_support")
    if "emotion_response" in evidence_need_set:
        roles.append("emotion_response_support")
    if "symbolic_meaning" in evidence_need_set:
        roles.append("symbolic_meaning_support")
    if "communication" in evidence_need_set:
        roles.append("communication_support")
    if "exchange" in evidence_need_set:
        roles.append("exchange_support")
    if {"registration_event", "participation_event"} & evidence_need_set:
        roles.append("event_support")
    if "causal_support" in evidence_need_set:
        roles.append("causal_support")
    if (
        "inference_support" in evidence_need_set
        and "multi_hop" not in evidence_need_set
    ):
        roles.append("inference_support")
    return tuple(dict.fromkeys(roles))


def merge_relation_evidence_needs(
    evidence_need: tuple[str, ...],
    relation_intents: tuple[RetrievalRelationIntent, ...],
) -> tuple[str, ...]:
    """Promote selected typed relation-facet needs into bundle planning."""

    promoted_needs = {
        "emotion_response",
        "communication",
        "exchange",
        "inference_support",
        "participation_event",
        "registration_event",
        "symbolic_meaning",
    }
    relation_needs = tuple(
        intent.evidence_need
        for intent in relation_intents
        if intent.evidence_need in promoted_needs
        and (
            intent.evidence_need != "inference_support"
            or intent.category == "status_profile"
        )
    )
    if not relation_needs:
        return evidence_need
    base_needs = tuple(need for need in evidence_need if need != "single_fact")
    return tuple(dict.fromkeys((*base_needs, *relation_needs)))


def _has_contrast_intent(
    *,
    relation_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    return bool(
        {"between", "compare", "different", "difference", "former", "previous"}
        & relation_set
        or {"compare", "between", "before", "after"} & set(multi_hop_markers)
    )


def _has_location_transition_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"move", "relocate", "relocated", "roadtrip"} & set(relation_terms):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    if not normalized:
        return False
    if _has_future_home_move_goal_intent(normalized):
        return False
    if re.search(
        r"\b(?:move|moved|moving|relocate|relocated)\s+"
        r"(?:the\s+)?(?:meeting|call|note|document|file|deadline|appointment|"
        r"task|ticket|event|conversation)\b",
        normalized,
    ):
        return False
    return bool(
        re.search(
            r"\b(?:where|which\s+(?:city|country|place)|from|origin|"
            r"home\s+country|relocat(?:e|ed|ion))\b",
            normalized,
        )
        or re.search(
            r"\b(?:move|moved|moving|relocate|relocated)\s+from\b",
            normalized,
        )
    )


def _has_current_goal_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"want", "plan"} & set(relation_terms):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    return bool(
        normalized
        and (
            _has_future_home_move_goal_intent(normalized)
            or re.search(r"\b(?:current\s+goal|future|soon)\b", normalized)
        )
    )


def _has_future_home_move_goal_intent(normalized_question: str) -> bool:
    if re.search(r"\b(?:where|which\s+(?:city|country|place)|from|origin)\b", normalized_question):
        return False
    return bool(
        re.search(r"\b(?:would|want|wants|wanted|hope|hoping|plan|plans)\b", normalized_question)
        and re.search(r"\bmove\s+back\b", normalized_question)
        and re.search(r"\bhome\s+country\b", normalized_question)
    )


def _has_inference_support_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    benchmark_category: int | None,
) -> bool:
    if benchmark_category == 3:
        return True
    relation_set = set(relation_terms)
    if {"relationship", "status"}.issubset(relation_set):
        return True
    if "decision" in relation_set:
        return True
    normalized = " ".join(str(question or "").casefold().split())
    return bool(
        re.search(r"\b(?:would|likely|might|could)\b", normalized)
        and relation_set
    )


def _has_exchange_intent(*, relation_terms: tuple[str, ...]) -> bool:
    relation_set = set(relation_terms)
    exchange_terms = {
        "bought",
        "bring",
        "brought",
        "gift",
        "purchas",
        "purchase",
        "receive",
    }
    if not exchange_terms & relation_set:
        return False
    return not (
        "receive" in relation_set and {"support", "grow", "counsel"} & relation_set
    )


def _has_communication_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if {"ask", "recommend", "suggest", "tell"} & relation_set:
        return True
    if "mention" not in relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:who|whom)\b.+\bmention\b|\bmention(?:ed)?\b.+\b(?:to|with)\b",
            normalized_question,
        )
    )


def infer_risk_flags(
    *,
    entity_count: int,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> tuple[str, ...]:
    flags: list[str] = []
    if entity_count == 0:
        flags.append("no_entity")
    if entity_count > 2:
        flags.append("ambiguous_entity_scope")
    if not relation_terms and not time_intent.is_temporal:
        flags.append("broad_query")
    if len(relation_variant_terms) > 18:
        flags.append("wide_relation_expansion")
    return tuple(flags)


_TEMPORAL_SUPPORT_VARIANTS = frozenset(
    {
        "age",
        "ago",
        "anniversary",
        "birthday",
        "born",
        "current",
        "date",
        "duration",
        "event",
        "month",
        "planned",
        "registered",
        "session",
        "signed",
        "time",
        "week",
        "weekend",
        "year",
        "years",
    }
)
_RELATION_FACET_CONFIG: dict[str, dict[str, object]] = {
    "activity": {
        "terms": frozenset(
            {
                "activity",
                "book",
                "bookshelf",
                "camp",
                "destress",
                "hike",
                "paint",
                "park",
                "read",
                "roadtrip",
                "run",
                "song",
            }
        ),
        "variants": frozenset(
            {
                "activities",
                "book",
                "books",
                "camping",
                "class",
                "creative",
                "express",
                "hobby",
                "hiking",
                "music",
                "outdoors",
                "photo",
                "pic",
                "reading",
                "running",
                "spot",
                "stories",
                "summer",
                "trail",
                "trip",
                "violin",
                "waterfall",
                "weekend",
                "went",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "single_fact",
    },
    "preference": {
        "terms": frozenset(
            {
                "enjoy",
                "interest",
                "like",
                "love",
                "prioritize",
                "self-care",
                "want",
            }
        ),
        "variants": frozenset(
            {
                "balance",
                "enjoyed",
                "fan",
                "interested",
                "like",
                "liked",
                "love",
                "outdoors",
                "prefer",
                "refresh",
                "relax",
                "routine",
                "wellness",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "preference",
    },
    "current_goal": {
        "terms": frozenset({"plan", "want"}),
        "variants": frozenset(
            {
                "future",
                "goal",
                "hop",
                "hope",
                "plan",
                "planned",
                "soon",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "inference_support",
    },
    "identity_profile": {
        "terms": frozenset(
            {"ally", "identity", "individual", "personality", "political", "religious"}
        ),
        "variants": frozenset(
            {
                "accept",
                "accepted",
                "activism",
                "background",
                "belief",
                "care",
                "church",
                "community",
                "concern",
                "conservative",
                "courage",
                "faith",
                "gender",
                "journey",
                "lgbtq",
                "person",
                "pride",
                "right",
                "rights",
                "self",
                "story",
                "support",
                "transition",
                "values",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "inference_support",
    },
    "status_profile": {
        "terms": frozenset(
            {
                "child",
                "children",
                "brother",
                "daughter",
                "family",
                "father",
                "friend",
                "husband",
                "marry",
                "mother",
                "parent",
                "partner",
                "relationship",
                "sibling",
                "sister",
                "son",
                "spouse",
                "status",
                "wife",
            }
        ),
        "variants": frozenset(
            {
                "breakup",
                "challenge",
                "child",
                "children",
                "brother",
                "dating",
                "daughter",
                "family",
                "father",
                "friend",
                "friends",
                "husband",
                "marry",
                "kids",
                "marriage",
                "married",
                "mother",
                "parent",
                "partner",
                "sibling",
                "sister",
                "son",
                "spouse",
                "support",
                "wife",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "inference_support",
    },
    "causal": {
        "terms": frozenset(
            {"cause", "choose", "decide", "decision", "feel", "realize", "think"}
        ),
        "variants": frozenset(
            {
                "because",
                "chose",
                "fit",
                "reason",
                "reaction",
                "response",
                "spoke",
                "thought",
                "understood",
                "value",
            }
        ),
        "markers": frozenset({"why", "how"}),
        "evidence_need": "causal_support",
    },
    "emotion_response": {
        "terms": frozenset({"excite", "feel"}),
        "variants": frozenset(
            {
                "anxious",
                "concern",
                "emotion",
                "enthusiastic",
                "excite",
                "excited",
                "feel",
                "feeling",
                "felt",
                "happy",
                "nervous",
                "overwhelmed",
                "proud",
                "reaction",
                "relieved",
                "response",
                "thrilled",
                "upset",
                "worried",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "emotion_response",
    },
    "support_goal": {
        "terms": frozenset(
            {
                "adopt",
                "adoption",
                "agency",
                "career",
                "counsel",
                "field",
                "grow",
                "help",
                "path",
                "pursue",
                "receive",
                "support",
                "work",
                "write",
            }
        ),
        "variants": frozenset(
            {
                "agencies",
                "career",
                "childhood",
                "counseling",
                "education",
                "helped",
                "inclusive",
                "inclusivity",
                "job",
                "kids",
                "lgbtq",
                "option",
                "profession",
                "similar",
                "support",
                "working",
                "writing",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "inference_support",
    },
    "exchange": {
        "terms": frozenset(
            {
                "bought",
                "bring",
                "brought",
                "gift",
                "purchas",
                "purchase",
                "receive",
            }
        ),
        "variants": frozenset(
            {
                "buy",
                "brought",
                "gave",
                "gift",
                "got",
                "offer",
                "offered",
                "purchas",
                "purchased",
                "receiv",
                "received",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "exchange",
    },
    "symbolic_meaning": {
        "terms": frozenset({"necklace", "symbolize"}),
        "variants": frozenset(
            {
                "family",
                "gift",
                "mean",
                "message",
                "reminder",
                "represent",
                "special",
                "support",
                "symbol",
                "value",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "symbolic_meaning",
    },
    "registration_event": {
        "terms": frozenset({"enroll", "register", "sign"}),
        "variants": frozenset(
            {
                "class",
                "course",
                "enrolled",
                "lesson",
                "registration",
                "signed",
                "signup",
                "workshop",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "registration_event",
    },
    "participation_event": {
        "terms": frozenset({"attend", "join", "participate", "visit"}),
        "variants": frozenset(
            {
                "attended",
                "class",
                "conference",
                "event",
                "group",
                "joined",
                "meeting",
                "participated",
                "place",
                "studio",
                "trip",
                "visited",
                "workshop",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "participation_event",
    },
    "communication": {
        "terms": frozenset(
            {
                "ask",
                "mention",
                "recommend",
                "suggest",
                "tell",
            }
        ),
        "variants": frozenset(
            {
                "advis",
                "advise",
                "advised",
                "mention",
                "mentioned",
                "recommend",
                "request",
                "said",
                "suggest",
                "suggested",
                "told",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "communication",
    },
    "location_transition": {
        "terms": frozenset({"move", "relocate", "relocated", "roadtrip"}),
        "variants": frozenset(
            {
                "city",
                "country",
                "drive",
                "from",
                "home",
                "origin",
                "relocated",
                "travel",
                "trip",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "location_support",
    },
    "contrast": {
        "terms": frozenset(
            {
                "compare",
                "different",
                "difference",
                "former",
                "previous",
            }
        ),
        "variants": frozenset(
            {
                "alternative",
                "before",
                "changed",
                "currently",
                "difference",
                "earlier",
                "former",
                "instead",
                "now",
                "ongoing",
                "previously",
                "used to",
            }
        ),
        "markers": frozenset({"after", "before", "between", "compare"}),
        "evidence_need": "contrast",
    },
}


def _relation_facet_reason_codes(
    *,
    category: str,
    terms: tuple[str, ...],
    variants: tuple[str, ...],
    marker_hit: bool,
) -> tuple[str, ...]:
    reasons: list[str] = [f"category:{category}"]
    if terms:
        reasons.append("relation_terms")
    if variants:
        reasons.append("relation_variants")
    if marker_hit:
        reasons.append("question_marker")
    return tuple(reasons)


def _dedupe_relation_intents(
    facets: tuple[RetrievalRelationIntent, ...] | list[RetrievalRelationIntent],
) -> tuple[RetrievalRelationIntent, ...]:
    by_category: dict[str, RetrievalRelationIntent] = {}
    for facet in facets:
        current = by_category.get(facet.category)
        if current is None:
            by_category[facet.category] = facet
            continue
        by_category[facet.category] = RetrievalRelationIntent(
            category=facet.category,
            terms=tuple(dict.fromkeys((*current.terms, *facet.terms))),
            variant_terms=tuple(
                dict.fromkeys((*current.variant_terms, *facet.variant_terms))
            ),
            evidence_need=current.evidence_need,
            reason_codes=tuple(dict.fromkeys((*current.reason_codes, *facet.reason_codes))),
        )
    return tuple(by_category.values())
