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
    answer_unit_shapes: tuple[str, ...] = ()

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
            "answer_unit_shapes": self.answer_unit_shapes,
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
            "answer_unit_shapes": list(self.answer_unit_shapes),
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
    if {"how long", "long", "duration"} & temporal_term_set:
        return "duration"
    if {
        "before",
        "beforehand",
        "after",
        "afterward",
        "afterwards",
        "since",
    } & temporal_term_set:
        return "temporal_sequence"
    if _RELATIVE_TIME_TERMS & temporal_term_set or _has_ordinal_event_term(
        temporal_terms
    ):
        return "relative_time"
    if temporal_surface_terms:
        return "explicit_time"
    return "temporal_lookup"


_RELATIVE_WEEKDAY_TERMS = frozenset(
    f"{modifier} {weekday}"
    for modifier in ("last", "next", "this")
    for weekday in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
)
_RELATIVE_ORDINAL_PERIOD_TERMS = frozenset(
    f"{ordinal} {period}"
    for ordinal in ("first", "second", "third", "fourth", "last")
    for period in ("weekend", "week", "half", "quarter", "month")
)
_RELATIVE_SEASON_TERMS = frozenset(
    f"{modifier} {season}"
    for modifier in ("last", "next", "this")
    for season in ("spring", "summer", "fall", "autumn", "winter")
)
_SEASON_TERMS = frozenset({"spring", "summer", "fall", "autumn", "winter"})
_ORDINAL_EVENT_TERM_RE = re.compile(
    r"\b(?:first|second|third|fourth|fifth|last|latest)\s+"
    r"(?:(?!(?:at|for|in|of|on|place|the)\b)[a-z0-9-]+\s+){0,3}"
    r"(?:call-?out|competition|event|game|project|screenplay|script|"
    r"tournament|tourney|trip)\b"
)
_RELATIVE_TIME_TERMS = (
    frozenset(
        {
            "ago",
            "again",
            "earlier",
            "earlier today",
            "earliest event",
            "early",
            "end",
            "first half",
            "last night",
            "last quarter",
            "last week",
            "last weekend",
            "last month",
            "last year",
            "later",
            "late",
            "latest event",
            "long ago",
            "next month",
            "next quarter",
            "next week",
            "next weekend",
            "next year",
            "previous",
            "recent",
            "second half",
            "since",
            "soon",
            "start",
            "this month",
            "this afternoon",
            "this evening",
            "this morning",
            "this quarter",
            "this week",
            "this weekend",
            "this year",
            "today",
            "tonight",
            "currently",
            "tomorrow afternoon",
            "tomorrow evening",
            "tomorrow morning",
            "tomorrow",
            "upcoming",
            "upcoming event",
            "yesterday afternoon",
            "yesterday evening",
            "yesterday morning",
            "yesterday",
        }
    )
    | _RELATIVE_WEEKDAY_TERMS
    | _RELATIVE_ORDINAL_PERIOD_TERMS
    | _RELATIVE_SEASON_TERMS
    | _SEASON_TERMS
)


def _has_ordinal_event_term(temporal_terms: tuple[str, ...]) -> bool:
    return any(_ORDINAL_EVENT_TERM_RE.search(term) for term in temporal_terms)


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
        if category == "causal" and not _has_causal_support_intent(
            question=question,
            relation_terms=relation_terms,
            multi_hop_markers=multi_hop_markers,
            time_intent=time_intent,
        ):
            continue
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
        if category == "action_event" and not _has_action_event_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "exchange" and not _has_exchange_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "participation_event" and not _has_participation_event_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "activity_profile" and not _has_activity_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "education_profile" and not _has_education_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "employment_profile" and not _has_employment_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "health_profile" and not _has_health_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "contact_profile" and not _has_contact_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "diet_profile" and not _has_diet_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "pet_profile" and not _has_pet_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "skill_profile" and not _has_skill_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "vehicle_profile" and not _has_vehicle_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "date_profile" and not _has_date_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "communication" and not _has_communication_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "status_profile" and not _has_status_profile_intent(
            question=question,
            relation_terms=relation_terms,
            time_intent=time_intent,
        ):
            continue
        if category == "support_goal" and not _has_support_goal_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "commitment_profile" and not _has_commitment_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        terms = tuple(term for term in relation_terms if term in config["terms"])
        variants = tuple(
            term for term in relation_variant_terms if term in config["variants"]
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
                    question=question,
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
    answer_unit_shapes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    needs: list[str] = []
    relation_set = set(relation_terms)
    answer_unit_set = set(answer_unit_shapes)
    count_intent = _has_count_intent(question) and benchmark_category != 3
    direct_emotion_response = _has_direct_emotion_response_intent(
        question=question,
        relation_terms=relation_terms,
    )
    if multi_hop_markers and not direct_emotion_response:
        needs.append("multi_hop")
    if count_intent:
        needs.append("count_support")
    if "quantity_dollar" in answer_unit_set:
        needs.append("value_support")
    if time_intent.is_temporal:
        needs.append(
            "temporal_sequence"
            if time_intent.kind == "temporal_sequence"
            else "temporal_support"
        )
    if visual_terms:
        needs.append("visual_evidence")
    if {"favorite", "favourite"} & relation_set:
        needs.append("favorite_preference")
    if {
        "avoid",
        "dislike",
        "favorite",
        "favourite",
        "hate",
        "interest",
        "prefer",
        "preference",
        "enjoy",
        "like",
        "love",
    } & relation_set:
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
    if not count_intent and _has_causal_support_intent(
        question=question,
        relation_terms=relation_terms,
        multi_hop_markers=multi_hop_markers,
        time_intent=time_intent,
    ):
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
    if "count_support" in evidence_need_set:
        roles.append("count_support")
    if "value_support" in evidence_need_set:
        roles.append("value_support")
    if "location_support" in evidence_need_set:
        roles.append("location_support")
    if "preference" in evidence_need_set:
        roles.append("preference_support")
    if "favorite_preference" in evidence_need_set:
        roles.append("favorite_support")
    if "visual_evidence" in evidence_need_set:
        roles.append("visual_support")
    if "emotion_response" in evidence_need_set:
        roles.append("emotion_response_support")
    if "symbolic_meaning" in evidence_need_set:
        roles.append("symbolic_meaning_support")
    if "communication" in evidence_need_set:
        roles.append("communication_support")
    profile_role_by_need = {
        "action_support": "action_support",
        "activity_support": "activity_support",
        "activity_profile": "activity_support",
        "age_profile": "age_support",
        "alias_profile": "alias_support",
        "current_goal": "current_goal_support",
        "date_profile": "date_support",
        "education_profile": "education_support",
        "employment_profile": "employment_support",
        "health_profile": "health_support",
        "identity_profile": "identity_support",
        "pet_profile": "pet_support",
        "skill_profile": "skill_support",
        "status_profile": "status_support",
        "support_goal": "support_goal_support",
        "vehicle_profile": "vehicle_support",
    }
    roles.extend(
        role
        for need, role in profile_role_by_need.items()
        if need in evidence_need_set
        and not (benchmark_category == 1 and need == "activity_support")
    )
    if "commitment_profile" in evidence_need_set:
        roles.append("commitment_support")
    if "contact_profile" in evidence_need_set:
        roles.append("contact_support")
    if "diet_profile" in evidence_need_set:
        roles.append("diet_support")
    if "exchange" in evidence_need_set:
        roles.append("exchange_support")
    if "favorite_preference" in evidence_need_set:
        roles.append("favorite_support")
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

    category_promoted_needs: set[str] = set()
    promoted_needs = {
        "emotion_response",
        "commitment_profile",
        "contact_profile",
        "diet_profile",
        "education_profile",
        "employment_profile",
        "age_profile",
        "alias_profile",
        "activity_profile",
        "activity_support",
        "action_support",
        "date_profile",
        "health_profile",
        "pet_profile",
        "skill_profile",
        "status_profile",
        "vehicle_profile",
        "communication",
        "current_goal",
        "exchange",
        "favorite_preference",
        "inference_support",
        "identity_profile",
        "participation_event",
        "registration_event",
        "support_goal",
        "symbolic_meaning",
    }
    relation_needs: list[str] = []
    for intent in relation_intents:
        if intent.category in category_promoted_needs:
            if "inference_support" not in evidence_need:
                continue
            relation_need = intent.category
        else:
            relation_need = intent.evidence_need
        if relation_need in promoted_needs and relation_need != "inference_support":
            if relation_need == "activity_support" and any(
                relation_intent.category == "activity_profile"
                for relation_intent in relation_intents
            ):
                continue
            if relation_need == "activity_support" and "preference" in evidence_need:
                continue
            if (
                relation_need == "support_goal"
                and {"causal_support", "multi_hop"} & set(evidence_need)
                and not _is_direct_support_relation_intent(intent)
            ):
                continue
            relation_needs.append(relation_need)
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


def _has_count_intent(question: str) -> bool:
    normalized = " ".join(str(question or "").casefold().split())
    return bool(
        normalized
        and re.search(
            r"\b(?:how\s+many|number\s+of|count\s+of|total\s+(?:number|count))\b",
            normalized,
        )
    )


def _has_causal_support_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> bool:
    relation_set = set(relation_terms)
    marker_set = set(multi_hop_markers)
    if _has_direct_emotion_response_intent(
        question=question,
        relation_terms=relation_terms,
    ):
        return False
    normalized = " ".join(str(question or "").casefold().split())
    if "motivation" in relation_set and _has_motivation_artifact_lookup(normalized):
        return False
    if {"why"} & marker_set:
        return True
    if not time_intent.is_temporal and ({"how"} & marker_set or {"how"} & relation_set):
        return True
    if "prompt" in relation_set and re.search(
        r"\bprompt(?:ed|ing)?\b.+\b(?:to|into)\b"
        r"|\bthat\s+prompt(?:ed|ing)?\b",
        normalized,
    ):
        return True
    direct_causal_terms = {
        "because",
        "caus",
        "cause",
        "inspir",
        "motivat",
        "motivate",
        "realize",
        "reason",
        "why",
    }
    if direct_causal_terms & relation_set:
        return True
    if "motivation" not in relation_set:
        return False
    return bool(
        re.search(
            r"\bwhat\s+(?:is|was)\b.+\bmotivation\s+for\s+"
            r"(?:chang|changing|creat|creating|get|getting|keep|keeping|"
            r"leav|leaving|mak|making|pursu|pursuing|runn|running|"
            r"tak|taking|writ|writing)\b",
            normalized,
        )
        or re.search(
            r"\b(?:boost|boosts|boosted|boosting|keep|keeping|stay|staying)\b"
            r".+\bmotivation\b",
            normalized,
        )
    )


def _has_motivation_artifact_lookup(normalized_question: str) -> bool:
    return bool(
        normalized_question
        and re.search(
            r"\b(?:displayed|shown|wrote|written|quote|quotes|plaque|board|"
            r"cork\s+board|whiteboard|journal|spread|schedule)\b"
            r".+\bmotivation(?:al)?\b"
            r"|\bmotivation(?:al)?\b.+"
            r"\b(?:quote|quotes|plaque|board|cork\s+board|whiteboard|"
            r"journal|spread|schedule)\b",
            normalized_question,
        )
    )


def _has_location_transition_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {
        "grow",
        "based",
        "live",
        "move",
        "origin",
        "relocate",
        "relocated",
        "roadtrip",
        "camp",
        "employment",
        "travel",
        "trip",
        "visit",
        "stay",
    } & relation_set:
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
            r"home\s+country|hometown|born|raised|childhood|originally|"
            r"relocat(?:e|ed|ion)|current\s+(?:city|home|location))\b",
            normalized,
        )
        or re.search(
            r"\b(?:move|moved|moving|relocate|relocated|live|lived|living|based|"
            r"stay|stayed|staying|grow|grew|camp|camped|camping|travel|"
            r"traveled|travelled|traveling|travelling|visit|visited|visiting)\s+"
            r"(?:from|in|at|near|around|up\b)",
            normalized,
        )
        or re.search(
            r"\b(?:where|which\s+(?:city|country|place)|what\s+place)\b"
            r".+\b(?:work|worked|working)\b|"
            r"\b(?:work|worked|working)\b.+"
            r"\b(?:where|which\s+(?:city|country|place)|what\s+place)\b",
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
    if re.search(r"\b(?:if|hadn t|had not)\b", normalized):
        return False
    if "plan" in set(relation_terms) and re.search(
        r"\b(?:plan|plans|planned|planning)\b",
        normalized,
    ):
        return True
    if "want" in set(relation_terms) and re.search(
        r"\b(?:want|wants|wanted|wanting)\s+to\s+"
        r"(?:create|build|make|teach|keep|expand|move|meet|work|go|do|try|"
        r"share|learn|pursue|start|open|organize|visit|live)\b",
        normalized,
    ):
        return True
    return bool(
        normalized
        and (
            _has_future_home_move_goal_intent(normalized)
            or re.search(r"\b(?:current\s+goal|future|soon)\b", normalized)
        )
    )


def _has_support_goal_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {
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
    } & relation_set:
        return False
    normalized_question = " ".join(str(question or "").casefold().split())
    if re.search(
        r"\b(?:different|difference|compare|compared|before|former|previous)\b",
        normalized_question,
    ):
        return False
    if _has_direct_support_role_question(normalized_question):
        return True
    return bool(
        normalized_question
        and (
            re.search(
                r"\b(?:support|supported|growing\s+up|"
                r"adoption\s+agency|agency\b.+\bsupport|support\b.+\bagency)\b",
                normalized_question,
            )
            or re.search(
                r"\bhelp(?:ed|ing)?\s+(?:children|kids|people|others|students|"
                r"community|individuals|folks)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:career|field|path|profession|work|job|write|writing|"
                r"counsel(?:ing|or)?|pursue)\b",
                normalized_question,
            )
        )
    )


def _is_direct_support_relation_intent(intent: RetrievalRelationIntent) -> bool:
    return "direct_support_question" in set(intent.reason_codes)


def _has_direct_support_role_question(normalized_question: str) -> bool:
    support_action = r"(?:help(?:ed|ing)?|assist(?:ed|ing)?|support(?:s|ed|ing)?)"
    return bool(
        re.search(
            rf"\b(?:who|whom)\b.+\b{support_action}\b",
            normalized_question,
        )
        or re.search(
            r"\bhow\b.+\b(?:get|got|receive|received|find|found)\b.+\bsupport\b"
            r".+\b(?:after|through|when|with|from)\b",
            normalized_question,
        )
        or re.search(
            rf"\b{support_action}\b.+\b(?:after|through|when|with)\b",
            normalized_question,
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


def _has_action_event_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "action" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\bwhat\s+did\b.+\b(?:"
            r"bring|brought|take|took|send|sent|share|shared|paint|painted|"
            r"draw|drew|make|made|book|booked|schedule|scheduled|prepare|prepared|"
            r"complete|completed|fix|fixed|repair|repaired|create|created"
            r")\b",
            normalized_question,
        )
    )


def _has_exchange_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    exchange_terms = {
        "bought",
        "bring",
        "brought",
        "give",
        "get",
        "got",
        "gift",
        "offer",
        "purchas",
        "purchase",
        "receive",
    }
    if not exchange_terms & relation_set:
        return False
    if "give" in relation_set and {"school", "speech", "talk", "presentation"} & relation_set:
        return False
    if {"support", "grow", "counsel", "help"} & relation_set and {
        "get",
        "got",
        "receive",
    } & relation_set:
        return False
    if {"get", "got"} & relation_set:
        normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
        return bool(
            re.search(
                r"\b(?:what|which)(?:\s+\w+){0,3}\s+"
                r"(?:did|do|does|had|has|have|will|would|could|should)\b"
                r".+\b(?:get|got)\b",
                normalized_question,
            )
            or re.search(r"\b(?:get|got)\b.+\bfrom\b", normalized_question)
        )
    return True


def _has_participation_event_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {
        "attend",
        "join",
        "meet",
        "participate",
        "travel",
        "visit",
    } & relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if "meet" in relation_set:
        if re.search(
            r"\bmeet(?:ing)?\s+(?:agenda|notes|minutes|summary)\b|"
            r"\bmeet\s+"
            r"(?:expectation|expectations|goal|goals|requirement|requirements)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:who|when|where)\b.+\bmeet\b|"
                r"\bmeet\s+up\b|\bmet\s+(?:with|up)\b|"
                r"\bmeeting\s+with\b|\bmeet(?:ing)?\b.+\b(?:friend|family|mentor|"
                r"colleague|coworker|team|group)\b",
                normalized_question,
            )
        )
    if "travel" not in relation_set:
        return True
    if re.search(
        r"\btravel\s+(?:book|guide|story|documentary|show)\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(
            r"\bwhere\b.+\btravel\b|\btravel(?:ed|ing)?\s+to\b|"
            r"\b(?:what|which)\s+(?:country|city|place)\b.+\btravel\b|"
            r"\b(?:trip|vacation)\b",
            normalized_question,
        )
    )


def _has_activity_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {"activity", "exercise", "hobby", "sport"} & relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bsports?\s+(?:team|score|game|match|event)\b", normalized_question):
        return False
    if "activity" in relation_set and not {"exercise", "hobby", "sport"} & relation_set:
        return bool(
            re.search(
                r"\b(?:hobby|hobbies|pastime|free\s+time|for\s+fun)\b|"
                r"\bwhat\b.+\b(?:do|does)\b.+\b(?:for\s+fun|free\s+time|relax)\b|"
                r"\b(?:exercise|workout)\b",
                normalized_question,
            )
        )
    return bool(
        re.search(
            r"\b(?:what|which)\s+(?:activity|activities|hobby|hobbies|sport|sports)\b|"
            r"\b(?:hobby|hobbies|pastime|free\s+time|for\s+fun)\b|"
            r"\bwhat\b.+\b(?:do|does)\b.+\b(?:for\s+fun|free\s+time|relax)\b|"
            r"\b(?:exercise|workout)\b",
            normalized_question,
        )
    )


def _has_communication_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if (
        {"advise", "ask", "recommend", "request", "suggest", "tell", "told"}
        & relation_set
    ):
        return True
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if {"chat", "discus", "discuss", "talk"} & relation_set:
        if re.search(
            r"\bwhy\b.+\b(?:after|before|while)\s+"
            r"(?:chat(?:ted|ting)?|discuss(?:ed|ing)?|talk(?:ed|ing)?)\b",
            normalized_question,
        ):
            return False
        if re.search(
            r"\b(?:give|gave|giving|present|presented|presentation|speech)\b"
            r".{0,40}\b(?:talk|discussion)\b"
            r"|\b(?:talk|discussion)\b.{0,40}\b(?:school|speech|event|presentation)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(
                r"\b(?:who|whom|what)\b.+\b(?:chat|discuss|talk)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:chat|discuss|talk)(?:ed|ing)?\b.+\b(?:about|to|with)\b",
                normalized_question,
            )
        )
    if {"call", "message", "messag", "send", "sent", "text"} & relation_set:
        if "call" in relation_set and {"miss", "missed"} & relation_set:
            return False
        if re.search(r"\bwhat\s+did\b.+\bcall\b(?!.*\b(?:about|to|with)\b)", normalized_question):
            return False
        return bool(
            re.search(
                r"\b(?:who|whom|when)\b.+\b(?:call|message|send|sent|text)\b",
                normalized_question,
            )
            or re.search(
                r"\b(?:call|message|messag|send|sent|text)(?:ed|ing)?\b"
                r".+\b(?:about|to|with)\b",
                normalized_question,
            )
        )
    if {"say", "said"} & relation_set:
        if {"personality", "trait"} & relation_set:
            return False
        if re.search(
            r"\b(?:what|which)\s+(?:do|does|did)\s+(?:the\s+)?"
            r"(?:book|card|document|label|letter|note|sign|text)\s+"
            r"(?:say|said)\b",
            normalized_question,
        ):
            return False
        return bool(
            re.search(r"\b(?:what|who|whom)\b.+\b(?:say|said)\b", normalized_question)
            or re.search(
                r"\b(?:say|said)\b.+\b(?:about|that|to|with)\b",
                normalized_question,
            )
        )
    if "mention" not in relation_set:
        return False
    return bool(
        re.search(
            r"\b(?:who|whom)\b.+\bmention\b|\bmention(?:ed)?\b.+\b(?:to|with)\b",
            normalized_question,
        )
    )


def _has_direct_emotion_response_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    relation_set = set(relation_terms)
    if not {"excite", "feel"} & relation_set:
        return False
    if {"cause", "decide", "decision", "realize", "think", "why"} & relation_set:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bwhy\b|\bwhat\s+(?:made|caused)\b", normalized_question):
        return False
    return bool(
        re.search(r"\bhow\b.+\b(?:feel|feeling|felt)\b", normalized_question)
        or re.search(r"\bwhat\b.+\bexcited\b", normalized_question)
    )


def _has_status_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> bool:
    relation_set = set(relation_terms)
    status_terms = {
        "boyfriend",
        "boss",
        "brother",
        "child",
        "children",
        "colleague",
        "cousin",
        "coworker",
        "dating",
        "daughter",
        "engag",
        "engaged",
        "family",
        "father",
        "fiance",
        "fiancee",
        "friend",
        "girlfriend",
        "grandfather",
        "grandmother",
        "husband",
        "manager",
        "member",
        "mentor",
        "marital",
        "marri",
        "marry",
        "married",
        "mother",
        "neighbor",
        "parent",
        "partner",
        "relationship",
        "roommate",
        "sibling",
        "sister",
        "son",
        "spouse",
        "status",
        "team",
        "teammate",
        "wife",
    }
    if not status_terms & relation_set:
        return False
    if time_intent.is_temporal:
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    if re.search(r"\bgroup\s+of\s+friends\b", normalized_question):
        return False
    if re.search(
        r"\bpartner(?:ed)?\s+with\b.+\b(?:project|work|assignment|team|"
        r"presentation|report)\b|"
        r"\bwho\s+did\b.+\bpartner\s+with\b|"
        r"\b(?:project|work|assignment|team|presentation|report)\s+"
        r"partner\s+s\s+name\b",
        normalized_question,
    ):
        return False
    return bool(
        re.search(r"\b(?:relationship|marital)\s+status\b", normalized_question)
        or re.search(
            r"\bwho\b.+\b(?:boyfriend|boss|brother|child|children|colleague|"
            r"cousin|coworker|daughter|father|fiancee?|friend|girlfriend|"
            r"grandfather|grandmother|husband|"
            r"kids|manager|mentor|mother|neighbor|parent|parents|partner|roommate|sibling|"
            r"sister|son|spouse|team|team\s+member|teammate|wife)\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:does|do|did)\b.+\bhave\b.+"
            r"\b(?:child|children|kids|son|daughter)\b",
            normalized_question,
        )
        or re.search(
            r"\bwhat\s+(?:is|are|was|were)\b.+"
            r"\b(?:boyfriend|boss|brother|child|children|colleague|cousin|"
            r"coworker|daughter|father|fiancee?|friend|girlfriend|grandfather|"
            r"grandmother|husband|kids|manager|mentor|mother|neighbor|parent|"
            r"parents|partner|roommate|sibling|sister|son|spouse|team|"
            r"team\s+member|teammate|wife)"
            r"\s+s\s+names?\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:who|whom)\b.+\b(?:team\s+member|teammate)\b|"
            r"\b(?:who|whom)\b.+\bon\b.+\bteam\b|"
            r"\bwhat\b.+\bteam\b.+\b(?:on|member|teammate)\b",
            normalized_question,
        )
        or re.search(
            r"\b(?:is|are|was|were)\b.+\b(?:dating|engaged|married|single|"
            r"divorced)\b",
            normalized_question,
        )
    )


def _has_commitment_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"deadline", "promise", "remember", "task"} & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_education_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"class", "education"} & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_employment_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "employment" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:what|which)\s+"
            r"(?:company|employer|job|occupation|profession|workplace)\b|"
            r"\bwho\s+(?:is|was)\b.+\bemployer\b|"
            r"\bwhat\s+(?:is|was)\b.+\b(?:salary|wage|pay\s+rate|hourly\s+rate)\b|"
            r"\b(?:job|occupation|profession|workplace)\b|"
            r"\bwhere\b.+\bwork\b|"
            r"\bwhat\b.+\bdo\b.+\bfor\s+work\b|"
            r"\bwork\b.+\b(?:company|for)\b",
            normalized_question,
        )
    )


def _has_health_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "health" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_contact_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "contact" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_diet_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "diet" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\b(?:dietary\s+(?:restriction|restrictions)|"
            r"vegetarian|vegan|gluten\s?free|dairy\s?free)\b|"
            r"\b(?:avoid|avoids|can t|cannot|can\s+not|doesn t|does\s+not|don t|do\s+not)\s+eat\b|"
            r"\bwhat\s+can\b.+\bnot\s+eat\b|"
            r"\bavoid(?:s|ed)?\s+eating\b|"
            r"\bwhat\s+food\b.+\b(?:avoid|eat)\b",
            normalized_question,
        )
    )


def _has_pet_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "pet" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_skill_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "skill" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_vehicle_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if "vehicle" not in set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
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


def _has_date_profile_intent(
    *,
    question: str,
    relation_terms: tuple[str, ...],
) -> bool:
    if not {"anniversary", "birthday"} & set(relation_terms):
        return False
    normalized_question = re.sub(r"[^0-9a-z]+", " ", question.casefold()).strip()
    return bool(
        re.search(
            r"\bwhen\b.+\b(?:anniversary|birthday)\b|"
            r"\bwhat\s+(?:is|was)\b.+\b(?:anniversary|birthday)\b|"
            r"\b(?:what|which)\s+(?:date|day|month)\b.+"
            r"\b(?:anniversary|birthday)\b|"
            r"\b(?:anniversary|birthday)\b.+\b(?:date|when)\b|"
            r"\bwedding\s+date\b|"
            r"\b(?:date\s+of\s+birth|birth\s+date|birthdate|dob)\b",
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
                "music",
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
        "evidence_need": "activity_support",
    },
    "action_event": {
        "terms": frozenset({"action"}),
        "variants": frozenset(
            {
                "book",
                "booked",
                "bring",
                "brought",
                "complete",
                "completed",
                "create",
                "created",
                "draw",
                "drew",
                "fix",
                "fixed",
                "made",
                "make",
                "paint",
                "painted",
                "prepare",
                "prepared",
                "repair",
                "repaired",
                "schedule",
                "scheduled",
                "send",
                "sent",
                "share",
                "shared",
                "take",
                "took",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "action_support",
    },
    "favorite_preference": {
        "terms": frozenset({"favorite", "favourite"}),
        "variants": frozenset(
            {
                "book",
                "choice",
                "color",
                "favorite",
                "favourite",
                "food",
                "go-to",
                "music",
                "prefer",
                "preferred",
                "restaurant",
                "song",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "favorite_preference",
    },
    "preference": {
        "terms": frozenset(
            {
                "avoid",
                "dislike",
                "enjoy",
                "favorite",
                "favourite",
                "hate",
                "interest",
                "like",
                "love",
                "prefer",
                "preference",
                "prioritize",
                "self-care",
                "want",
            }
        ),
        "variants": frozenset(
            {
                "avoid",
                "avoided",
                "avoids",
                "balance",
                "dislik",
                "dislike",
                "disliked",
                "enjoyed",
                "fan",
                "favorite",
                "favourite",
                "hat",
                "hate",
                "hated",
                "hates",
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
    "activity_profile": {
        "terms": frozenset({"activity", "exercise", "hobby", "sport"}),
        "variants": frozenset(
            {
                "activities",
                "camping",
                "exercise",
                "fun",
                "hike",
                "hobbies",
                "hobby",
                "leisure",
                "outdoors",
                "paint",
                "painting",
                "pastime",
                "run",
                "running",
                "sport",
                "tennis",
                "yoga",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "activity_profile",
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
        "evidence_need": "current_goal",
    },
    "identity_profile": {
        "terms": frozenset(
            {"ally", "identity", "personality", "political", "religious"}
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
        "evidence_need": "identity_profile",
    },
    "status_profile": {
        "terms": frozenset(
            {
                "child",
                "children",
                "boyfriend",
                "brother",
                "cousin",
                "daughter",
                "dating",
                "engag",
                "engaged",
                "family",
                "father",
                "fiance",
                "fiancee",
                "friend",
                "girlfriend",
                "grandfather",
                "grandmother",
                "husband",
                "boss",
                "colleague",
                "coworker",
                "manager",
                "member",
                "mentor",
                "marry",
                "mother",
                "neighbor",
                "parent",
                "partner",
                "relationship",
                "roommate",
                "sibling",
                "sister",
                "son",
                "spouse",
                "status",
                "team",
                "teammate",
                "wife",
            }
        ),
        "variants": frozenset(
            {
                "breakup",
                "boyfriend",
                "challenge",
                "child",
                "children",
                "brother",
                "cousin",
                "dating",
                "daughter",
                "engaged",
                "family",
                "father",
                "fiance",
                "fiancee",
                "friend",
                "friends",
                "girlfriend",
                "grandfather",
                "grandmother",
                "grandparent",
                "husband",
                "boss",
                "colleague",
                "coworker",
                "manager",
                "member",
                "mentor",
                "marry",
                "kids",
                "marriage",
                "married",
                "mother",
                "neighbor",
                "parent",
                "partner",
                "relative",
                "roommate",
                "sibling",
                "sister",
                "son",
                "spouse",
                "support",
                "team",
                "teammate",
                "wife",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "status_profile",
    },
    "causal": {
        "terms": frozenset(
            {
                "because",
                "caus",
                "cause",
                "choose",
                "decide",
                "decision",
                "feel",
                "inspir",
                "motivat",
                "motivate",
                "motivation",
                "prompt",
                "prompted",
                "realize",
                "reason",
                "think",
            }
        ),
        "variants": frozenset(
            {
                "because",
                "cause",
                "caus",
                "chose",
                "decision",
                "explain",
                "fit",
                "inspir",
                "motivat",
                "motivation",
                "prompt",
                "prompted",
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
                "angry",
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
                "sad",
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
        "evidence_need": "support_goal",
    },
    "education_profile": {
        "terms": frozenset({"class", "education", "go"}),
        "variants": frozenset(
            {
                "campus",
                "college",
                "course",
                "degree",
                "major",
                "majoring",
                "school",
                "studies",
                "study",
                "studying",
                "university",
                "graduate",
                "graduated",
                "graduation",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "education_profile",
    },
    "employment_profile": {
        "terms": frozenset({"employment"}),
        "variants": frozenset(
            {
                "career",
                "company",
                "employer",
                "job",
                "occupation",
                "office",
                "pay",
                "rate",
                "profession",
                "role",
                "salary",
                "wage",
                "work",
                "worked",
                "working",
                "workplace",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "employment_profile",
    },
    "health_profile": {
        "terms": frozenset({"health"}),
        "variants": frozenset(
            {
                "allergic",
                "allergy",
                "appointment",
                "blood",
                "clinic",
                "condition",
                "dental",
                "dentist",
                "doctor",
                "health",
                "medication",
                "medicine",
                "physician",
                "prescription",
                "take",
                "taking",
                "therapist",
                "type",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "health_profile",
    },
    "contact_profile": {
        "terms": frozenset({"contact"}),
        "variants": frozenset(
            {
                "address",
                "cell",
                "contact",
                "e-mail",
                "email",
                "mobile",
                "number",
                "phone",
                "reach",
                "reached",
                "telephone",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "contact_profile",
    },
    "commitment_profile": {
        "terms": frozenset({"deadline", "promise", "remember", "task"}),
        "variants": frozenset(
            {
                "bring",
                "commit",
                "committed",
                "complete",
                "date",
                "deadline",
                "due",
                "finish",
                "need",
                "promise",
                "promised",
                "remember",
                "reminder",
                "task",
                "to-do",
                "todo",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "commitment_profile",
    },
    "diet_profile": {
        "terms": frozenset({"diet"}),
        "variants": frozenset(
            {
                "avoid",
                "dairy",
                "dietary",
                "eat",
                "egg",
                "eggs",
                "food",
                "gluten",
                "lactose",
                "meat",
                "pork",
                "restriction",
                "seafood",
                "soy",
                "vegan",
                "vegetarian",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "diet_profile",
    },
    "age_profile": {
        "terms": frozenset({"age"}),
        "variants": frozenset(
            {
                "age",
                "birthday",
                "born",
                "old",
                "turn",
                "turned",
                "turning",
                "turns",
                "year",
                "years",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "age_profile",
    },
    "alias_profile": {
        "terms": frozenset({"nickname"}),
        "variants": frozenset(
            {
                "alias",
                "call",
                "called",
                "calls",
                "name",
                "named",
                "nickname",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "alias_profile",
    },
    "date_profile": {
        "terms": frozenset({"anniversary", "birthday"}),
        "variants": frozenset(
            {
                "anniversary",
                "birthday",
                "born",
                "date",
                "married",
                "marry",
                "month",
                "wed",
                "wedding",
                "year",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "date_profile",
    },
    "pet_profile": {
        "terms": frozenset({"pet"}),
        "variants": frozenset(
            {
                "animal",
                "breed",
                "cat",
                "dog",
                "kitten",
                "labrador",
                "name",
                "named",
                "pet",
                "puppy",
                "retriever",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "pet_profile",
    },
    "skill_profile": {
        "terms": frozenset({"skill"}),
        "variants": frozenset(
            {
                "drums",
                "guitar",
                "instrument",
                "bilingual",
                "certification",
                "certified",
                "credential",
                "fluent",
                "know",
                "language",
                "piano",
                "play",
                "plays",
                "speak",
                "speaks",
                "spoken",
                "violin",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "skill_profile",
    },
    "vehicle_profile": {
        "terms": frozenset({"vehicle"}),
        "variants": frozenset(
            {
                "car",
                "color",
                "drive",
                "drives",
                "driving",
                "license",
                "licence",
                "own",
                "owns",
                "plate",
                "sedan",
                "suv",
                "truck",
                "van",
                "vehicle",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "vehicle_profile",
    },
    "exchange": {
        "terms": frozenset(
            {
                "bought",
                "bring",
                "brought",
                "give",
                "get",
                "got",
                "gift",
                "offer",
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
                "get",
                "gift",
                "got",
                "offer",
                "offered",
                "purchas",
                "purchased",
                "receiv",
                "receive",
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
            }
        ),
        "markers": frozenset(),
        "evidence_need": "registration_event",
    },
    "participation_event": {
        "terms": frozenset(
            {"attend", "join", "meet", "participate", "travel", "visit"}
        ),
        "variants": frozenset(
            {
                "attended",
                "city",
                "class",
                "conference",
                "country",
                "event",
                "group",
                "joined",
                "meeting",
                "met",
                "participated",
                "place",
                "studio",
                "trip",
                "traveled",
                "travelled",
                "visited",
                "went",
                "workshop",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "participation_event",
    },
    "communication": {
        "terms": frozenset(
            {
                "advise",
                "ask",
                "call",
                "chat",
                "discus",
                "discuss",
                "message",
                "messag",
                "mention",
                "recommend",
                "request",
                "say",
                "said",
                "suggest",
                "talk",
                "tell",
                "text",
                "told",
            }
        ),
        "variants": frozenset(
            {
                "advise",
                "advised",
                "called",
                "chatted",
                "conversation",
                "discus",
                "discuss",
                "discussed",
                "discussion",
                "mention",
                "mentioned",
                "messag",
                "messaged",
                "recommend",
                "request",
                "requested",
                "say",
                "said",
                "send",
                "sent",
                "suggest",
                "suggested",
                "talked",
                "texted",
                "told",
            }
        ),
        "markers": frozenset(),
        "evidence_need": "communication",
    },
    "location_transition": {
        "terms": frozenset(
            {
                "grow",
                "based",
                "camp",
                "employment",
                "live",
                "move",
                "origin",
                "relocate",
                "relocated",
                "roadtrip",
                "stay",
                "travel",
                "trip",
                "visit",
            }
        ),
        "variants": frozenset(
            {
                "camped",
                "campground",
                "camping",
                "campsite",
                "childhood",
                "city",
                "country",
                "based",
                "destination",
                "drive",
                "from",
                "grew",
                "home",
                "hometown",
                "hotel",
                "company",
                "employer",
                "office",
                "origin",
                "originally",
                "place",
                "raised",
                "relocated",
                "stayed",
                "staying",
                "travel",
                "traveled",
                "traveling",
                "trip",
                "visited",
                "visiting",
                "work",
                "worked",
                "working",
                "workplace",
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
    question: str,
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
    if category == "support_goal" and _has_direct_support_role_question(
        " ".join(str(question or "").casefold().split())
    ):
        reasons.append("direct_support_question")
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
