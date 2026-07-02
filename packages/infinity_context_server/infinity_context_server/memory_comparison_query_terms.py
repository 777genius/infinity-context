"""Question-only query-term planning helpers for memory comparison."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_server.memory_comparison_rerank_text import (
    QUERY_STOPWORDS as _QUERY_STOPWORDS,
)
from infinity_context_server.memory_comparison_rerank_text import (
    QUERY_TOKEN_ALIASES as _QUERY_TOKEN_ALIASES,
)
from infinity_context_server.memory_comparison_rerank_text import (
    normalized_terms as _normalized_terms,
)

_HIGH_SIGNAL_RELATION_VARIANTS = {
    "amazing",
    "awesome",
    "camping",
    "care",
    "classical",
    "conservative",
    "brother",
    "boyfriend",
    "dating",
    "daughter",
    "dinosaur",
    "engaged",
    "faith",
    "fiance",
    "fiancee",
    "girlfriend",
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


def _support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
    communication_support: bool,
    contact_support: bool,
    diet_support: bool,
    education_support: bool,
    employment_support: bool,
    age_support: bool,
    alias_support: bool,
    health_support: bool,
    pet_support: bool,
    preference_support: bool,
    skill_support: bool,
    vehicle_support: bool,
) -> tuple[str, ...]:
    if communication_support:
        return _communication_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if contact_support:
        return _contact_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if diet_support:
        return _diet_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if education_support:
        return _education_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if employment_support:
        return _employment_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if age_support:
        return _age_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if alias_support:
        return _alias_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if health_support:
        return _health_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if pet_support:
        return _pet_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if preference_support and {"favorite", "favourite"} & set(relation_terms):
        return _preference_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if skill_support:
        return _skill_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    if vehicle_support:
        return _vehicle_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
        )
    relation_term_set = set(relation_terms)
    if (
        (
            {"live", "move", "origin", "relocate", "relocated", "roadtrip"}
            & relation_term_set
            or (
                {"grow", "stay"} & relation_term_set
                and {"where", "from", "city", "country", "place", "origin"}
                & set(lexical_terms)
            )
        )
        and not {"plan", "want"} & relation_term_set
    ):
        return _location_support_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
        )
    if {"sign", "enroll", "register", "conference"} & relation_term_set:
        return _topical_relation_query_terms(
            relation_terms=relation_terms,
            relation_variant_terms=relation_variant_terms,
            lexical_terms=lexical_terms,
            entity_surfaces=entity_surfaces,
            topic_after=1 if "conference" in relation_terms else 4,
        )
    return _relation_query_terms(relation_terms, relation_variant_terms)


def _contact_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    contact_terms = {
        "address",
        "cell",
        "contact",
        "e-mail",
        "email",
        "mobile",
        "number",
        "phone",
        "telephone",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "contact"),
                *(term for term in relation_variant_terms if term in contact_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in contact_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _diet_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    diet_terms = {
        "avoid",
        "dairy",
        "diet",
        "dietary",
        "eat",
        "food",
        "gluten",
        "meat",
        "pork",
        "restriction",
        "vegan",
        "vegetarian",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "diet"),
                *(term for term in relation_variant_terms if term in diet_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in diet_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _education_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    education_terms = {
        "campu",
        "campus",
        "class",
        "college",
        "course",
        "degree",
        "education",
        "major",
        "majoring",
        "school",
        "studies",
        "study",
        "studying",
        "university",
    }
    relation_action_terms = {"attend", "education", "go", "school"}
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term in relation_action_terms),
                *(term for term in relation_variant_terms if term in education_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in education_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _employment_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    employment_terms = {
        "career",
        "company",
        "employer",
        "employment",
        "job",
        "occupation",
        "office",
        "profession",
        "role",
        "work",
        "worked",
        "working",
        "workplace",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "employment"),
                *(term for term in relation_variant_terms if term in employment_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in employment_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _age_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    age_terms = {"age", "birthday", "born", "old", "year", "years"}
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "age"),
                *(term for term in relation_variant_terms if term in age_terms),
                *topical_terms[:4],
            )
        )
    )


def _alias_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    alias_terms = {
        "alias",
        "call",
        "called",
        "calls",
        "name",
        "named",
        "nickname",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term in {"call", "nickname"}),
                *(term for term in relation_variant_terms if term in alias_terms),
                *topical_terms[:4],
            )
        )
    )


def _health_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    health_terms = {
        "allergic",
        "allergy",
        "appointment",
        "clinic",
        "condition",
        "doctor",
        "health",
        "medication",
        "medicine",
        "prescription",
        "take",
        "taking",
        "therapist",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "health"),
                *(term for term in relation_variant_terms if term in health_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in health_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _pet_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    pet_terms = {
        "animal",
        "cat",
        "dog",
        "kitten",
        "name",
        "named",
        "pet",
        "puppy",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "pet"),
                *(term for term in relation_variant_terms if term in pet_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in pet_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _skill_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    skill_terms = {
        "drums",
        "guitar",
        "instrument",
        "language",
        "piano",
        "play",
        "plays",
        "skill",
        "speak",
        "speaks",
        "spoken",
        "violin",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "skill"),
                *(term for term in relation_variant_terms if term in skill_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in skill_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


def _preference_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    preference_actions = {
        "enjoy",
        "enjoyed",
        "favorite",
        "favourite",
        "interest",
        "interested",
        "like",
        "liked",
        "love",
        "prefer",
    }
    preference_domains = {
        "animal",
        "book",
        "color",
        "food",
        "music",
        "park",
        "restaurant",
        "song",
    }
    lexical_domain_terms = tuple(
        term
        for term in lexical_terms
        if term in preference_domains and term not in entity_tokens
    )
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term in preference_actions),
                *lexical_domain_terms,
                *(term for term in relation_variant_terms if term in preference_actions),
                *(term for term in relation_variant_terms if term in preference_domains),
                *topical_terms[:4],
            )
        )
    )


def _vehicle_support_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
) -> tuple[str, ...]:
    entity_tokens = {
        token for surface in entity_surfaces for token in _normalized_terms(surface)
    }
    vehicle_terms = {
        "car",
        "color",
        "drive",
        "drives",
        "driving",
        "own",
        "owns",
        "sedan",
        "suv",
        "truck",
        "van",
        "vehicle",
    }
    topical_terms = tuple(
        term
        for term in lexical_terms
        if term not in _QUERY_STOPWORDS
        and term not in relation_terms
        and term not in relation_variant_terms
        and term not in entity_tokens
    )
    return tuple(
        dict.fromkeys(
            (
                *(term for term in relation_terms if term == "vehicle"),
                *(term for term in relation_variant_terms if term in vehicle_terms),
                *topical_terms[:4],
                *(
                    term
                    for term in _relation_query_terms(
                        relation_terms,
                        relation_variant_terms,
                    )
                    if term not in vehicle_terms and term not in _QUERY_STOPWORDS
                ),
            )
        )
    )


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
        "advise",
        "ask",
        "asked",
        "call",
        "called",
        "chat",
        "chatted",
        "conversation",
        "discuss",
        "discussed",
        "message",
        "messag",
        "messaged",
        "mention",
        "recommend",
        "recommended",
        "request",
        "said",
        "send",
        "sent",
        "suggest",
        "suggested",
        "talk",
        "talked",
        "tell",
        "text",
        "texted",
        "told",
    }
    allowed_communication_terms: set[str] = set()
    relation_term_set = set(relation_terms)
    if relation_term_set & {"say", "said", "tell", "mention"}:
        allowed_communication_terms.update(("mention", "said", "tell", "told"))
    if relation_term_set & {"chat", "discus", "discuss", "talk"}:
        allowed_communication_terms.update(
            (
                "chat",
                "chatted",
                "conversation",
                "discus",
                "discuss",
                "discussed",
                "talk",
                "talked",
            )
        )
    if relation_term_set & {"call", "message", "messag", "send", "sent", "text"}:
        allowed_communication_terms.update(
            (
                "call",
                "called",
                "message",
                "messag",
                "messaged",
                "send",
                "sent",
                "text",
                "texted",
            )
        )
    if "ask" in relation_term_set:
        allowed_communication_terms.update(("ask", "asked", "request"))
    if relation_term_set & {"recommend", "suggest"}:
        allowed_communication_terms.update(
            ("advise", "recommend", "recommended", "suggest", "suggested", "told")
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


def _topical_relation_query_terms(
    *,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    lexical_terms: tuple[str, ...],
    entity_surfaces: tuple[str, ...],
    topic_after: int,
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
        dict.fromkeys(
            (
                *base_terms[:topic_after],
                *topical_terms[:4],
                *base_terms[topic_after:],
            )
        )
    )



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
        "place",
        "live",
        "lived",
        "living",
        "stay",
        "stayed",
        "hotel",
        "grew",
        "childhood",
        "born",
        "hometown",
        "originally",
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



def _relation_query_terms(
    relation_terms: Sequence[str],
    relation_variant_terms: Sequence[str],
) -> tuple[str, ...]:
    relation_terms = tuple(relation_terms)
    generic_relation_terms = {"consider"}
    if "receive" in relation_terms and "grow" in relation_terms:
        generic_relation_terms.add("career")
    if {"personality", "trait", "say"} <= set(relation_terms):
        generic_relation_terms.add("say")
    if {"personality", "trait", "said"} <= set(relation_terms):
        generic_relation_terms.add("said")
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
                "creative",
                "fun",
                "interest",
                "expres",
                "refresh",
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
        priority_variant_order.extend(("went",))
    if {"book", "read"}.issubset(relation_term_set):
        priority_variant_order.extend(("reading",))
        priority_surface_terms.add("reading")
    if {"kid", "like"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "animal",
                "exhibit",
                "learning",
                "family",
                "preference",
                "children",
                "like",
                "love",
            )
        )
        priority_surface_terms.update(("animal", "learning"))
    if "birthday" in relation_term_set:
        priority_variant_order.extend(("18th", "year", "ago", "born", "age"))
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
                "rights",
                "lgbtq",
                "support",
                "accept",
                "belief",
                "view",
                "value",
                "policy",
            )
        )
        priority_surface_terms.add("rights")
    if "religious" in relation_term_set:
        priority_variant_order.extend(
            (
                "church",
                "think",
                "journey",
                "chang",
                "acceptance",
                "faith",
                "growth",
            )
        )
    if {"career", "path", "pursue"}.issubset(relation_term_set):
        priority_variant_order.extend(("work", "working", "think", "figur", "option"))
        priority_surface_terms.add("working")
    if {"write", "career"}.issubset(relation_term_set):
        priority_variant_order.extend(
            (
                "looking",
                "work",
                "working",
                "jobs",
                "job",
                "option",
                "path",
                "support",
            )
        )
        priority_surface_terms.add("looking")
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
                "story",
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
        priority_variant_order.extend(("last", "ran", "fundraiser", "awareness"))
        priority_surface_terms.add("last")
    if "research" in relation_term_set:
        priority_variant_order.extend(("researching",))
        priority_surface_terms.add("researching")
    if {
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
        "send",
        "sent",
        "suggest",
        "talk",
        "tell",
        "text",
        "told",
    } & relation_term_set:
        if relation_term_set & {"call", "message", "messag", "send", "sent", "text"}:
            priority_variant_order.extend(
                ("message", "sent", "messaged", "texted", "called")
            )
        if relation_term_set & {"chat", "discus", "discuss", "talk"}:
            priority_variant_order.extend(
                ("discussed", "talked", "conversation", "chat")
            )
        if relation_term_set & {"mention", "say", "said", "tell", "told"}:
            priority_variant_order.extend(("told", "said", "mentioned"))
        if relation_term_set & {"ask", "request"}:
            priority_variant_order.extend(("asked", "request"))
            priority_surface_terms.add("asked")
        if relation_term_set & {"advise", "recommend", "suggest"}:
            priority_variant_order.extend(
                ("advised", "recommended", "suggested", "told")
            )
            priority_surface_terms.update(("advised", "recommended", "suggested"))
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
            )
        )
        priority_surface_terms.update(("signed", "registered", "enrolled"))
    if "conference" in relation_term_set:
        priority_variant_order.extend(("going", "month", "event", "attend"))
        priority_surface_terms.add("month")
    if "roadtrip" in relation_term_set:
        priority_variant_order.extend(
            (
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
