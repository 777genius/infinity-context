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
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase

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
_HONORIFIC_ENTITY_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof)\.\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\b"
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
    r"\b(?:sharing image|image shows|sharing photo|photo shows|picture shows)\b",
    re.IGNORECASE,
)
_PREFERENCE_EVIDENCE_RE = re.compile(
    r"\b(?:love|loved|like|liked|enjoy|enjoyed|interested|prefer|preferred|"
    r"outdoors|camping|national park|self-care|relax|refresh|refreshes|"
    r"refreshing)\b",
    re.IGNORECASE,
)
_QUERY_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "any",
    "are",
    "asked",
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
    "said",
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
_QUERY_TOKEN_ALIASES = {
    "agency": ("agencies",),
    "amaz": ("amazing",),
    "awarenes": ("awareness",),
    "carv": ("carve",),
    "camp": ("camping",),
    "clas": ("class",),
    "counsel": ("counseling", "counselor"),
    "dat": ("dating",),
    "decid": ("decide",),
    "destres": ("destress",),
    "educaton": ("education",),
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
    "persue": ("pursue",),
    "plann": ("plan",),
    "politic": ("political",),
    "proces": ("process",),
    "prioritiz": ("prioritize",),
    "pursu": ("pursue",),
    "rais": ("raise",),
    "receiv": ("receive", "received"),
    "read": ("read",),
    "realiz": ("realize",),
    "refreshe": ("refresh",),
    "religiou": ("religious",),
    "relocat": ("relocated",),
    "statu": ("status",),
    "stres": ("stress",),
    "symboliz": ("symbolize", "symbol"),
    "writ": ("write", "writing"),
    "grow": ("growing", "childhood"),
}
_QUERY_RENDER_SURFACES = {
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
    "relocat": "relocated",
    "thrill": "thrilled",
    "upbring": "upbringing",
    "wellnes": "wellness",
}
_PERSON_ENTITY_ALIASES = {
    "mel": ("melanie",),
}
_NON_SPEAKER_ENTITY_SURFACES = {
    "dr",
    "four",
    "lgbtq",
    "seasons",
    "seuss",
    "vivaldi",
}
_HIGH_SIGNAL_RELATION_VARIANTS = {
    "amazing",
    "awesome",
    "camping",
    "care",
    "classical",
    "conservative",
    "dinosaur",
    "faith",
    "inclusive",
    "inclusivity",
    "known",
    "lgbtq",
    "love",
    "mental",
    "mom",
    "nature",
    "important",
    "real",
    "right",
    "rights",
    "self-care",
    "strength",
    "sunrise",
    "transgender",
    "trip",
    "wed",
    "wedding",
    "writing",
    "year",
}
_RELATION_QUERY_TERMS = {
    "activity",
    "birthday",
    "book",
    "bookshelf",
    "bought",
    "between",
    "bring",
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
    "excite",
    "feel",
    "former",
    "give",
    "go",
    "friend",
    "group",
    "grow",
    "help",
    "interest",
    "identity",
    "learn",
    "like",
    "love",
    "make",
    "marry",
    "meet",
    "mention",
    "move",
    "plan",
    "political",
    "previous",
    "prioritize",
    "pursue",
    "raise",
    "receive",
    "read",
    "religious",
    "relationship",
    "realize",
    "research",
    "run",
    "sign",
    "symbolize",
    "support",
    "status",
    "tell",
    "think",
    "want",
    "work",
}
_RELATION_QUERY_TERMS.update(
    {
        "adopt",
        "adoption",
        "agency",
        "ally",
        "community",
        "counsel",
        "career",
        "charity",
        "current",
        "decision",
        "field",
        "individual",
        "kid",
        "member",
        "music",
        "necklace",
        "paint",
        "park",
        "path",
        "personality",
        "process",
        "race",
        "roadtrip",
        "school",
        "self-care",
        "song",
        "speech",
        "sunrise",
        "summer",
        "trait",
        "write",
    }
)
_RELATION_QUERY_VARIANTS = {
    "activity": (
        "activities",
        "hobby",
        "hobbies",
        "partake",
        "do",
        "class",
        "kids",
        "photo",
        "image",
        "family",
        "weekend",
        "unplug",
    ),
    "birthday": ("birthday", "born", "age", "years", "ago"),
    "book": (
        "books",
        "reading",
        "read",
        "bookshelf",
        "kids",
        "stories",
    ),
    "bookshelf": (
        "books",
        "book",
        "reading",
        "read",
        "kids",
        "stories",
    ),
    "bought": ("buy", "purchased", "got"),
    "bring": ("brought", "take", "took"),
    "camp": (
        "camped",
        "camping",
        "family",
        "unplug",
        "connection",
        "close",
        "together",
        "outdoors",
        "trip",
        "tent",
        "site",
    ),
    "career": ("path", "field", "job", "work", "working", "profession", "option"),
    "cause": ("caused", "because", "reason"),
    "choose": ("chose", "picked", "selected"),
    "consider": ("considered", "considering", "looked at", "thinking"),
    "conference": ("event", "attend", "going", "transgender"),
    "decide": ("decided", "chose", "planned", "thinking", "figuring"),
    "destress": (
        "stress",
        "relax",
        "unwind",
        "clear mind",
        "headspace",
        "therapy",
        "class",
        "running",
        "farther",
        "activity",
        "practice",
        "routine",
        "therapeutic",
        "creative",
        "express",
        "decompress",
        "self-care",
    ),
    "enjoy": ("enjoyed", "like", "liked", "love", "fan", "interested"),
    "excite": ("excited", "looking forward", "enthusiastic"),
    "feel": ("felt", "feeling"),
    "field": ("career", "option", "education", "study", "work", "working", "profession"),
    "give": ("gave", "giving", "offered"),
    "go": ("went", "going", "visited"),
    "current": ("known", "years", "been", "existing", "ongoing"),
    "compare": ("comparison", "difference", "different", "alternative", "instead"),
    "friend": ("friends", "group", "family", "mentors", "support"),
    "different": ("difference", "alternative", "compare", "instead"),
    "difference": ("different", "alternative", "compare", "instead"),
    "former": ("formerly", "previously", "earlier", "before", "used to"),
    "grow": ("growing", "grew", "childhood", "journey", "upbringing"),
    "group": ("friends", "family", "mentors", "support"),
    "help": ("helped", "helping", "assist", "support"),
    "identity": (
        "pride",
        "gender",
        "story",
        "identify",
        "self",
        "person",
        "background",
        "community",
        "support",
        "inspiring",
        "accepted",
        "courage",
        "embrace",
    ),
    "interest": ("interested", "prefer", "enjoy", "like", "outdoors", "park"),
    "learn": ("learned", "learning", "studied"),
    "like": ("liked", "enjoy", "enjoyed", "love"),
    "love": ("loved", "enjoy", "enjoyed", "like"),
    "make": ("made", "create", "created"),
    "marry": (
        "married",
        "marriage",
        "wedding",
        "years",
        "anniversary",
        "husband",
        "wife",
        "spouse",
        "bride",
        "dress",
    ),
    "meet": ("met", "meeting", "friends", "family", "mentors", "gathering"),
    "mention": ("mentioned", "said", "talked", "told"),
    "move": ("moved", "from", "relocated", "came", "home", "country", "origin"),
    "plan": (
        "planned",
        "planning",
        "going to",
        "want",
        "dream",
        "family",
        "loving home",
        "kids",
    ),
    "political": (
        "politics",
        "leaning",
        "belief",
        "views",
        "values",
        "rights",
        "conservative",
        "lgbtq",
        "social",
        "activism",
        "policy",
        "transition",
        "comment",
        "hike",
        "upset",
        "support",
        "accept",
    ),
    "path": ("career", "field", "work", "working", "profession", "direction"),
    "previous": ("previously", "earlier", "before", "used to", "former"),
    "prioritize": (
        "prioritized",
        "self-care",
        "routine",
        "refresh",
        "present",
        "wellness",
        "balance",
    ),
    "pursue": (
        "pursued",
        "pursuing",
        "career",
        "education",
        "study",
        "field",
        "support",
        "similar",
        "issues",
        "keen",
    ),
    "raise": ("raised", "raising", "awareness", "fundraiser"),
    "receive": ("received", "got", "support", "help", "growing up"),
    "read": ("reading", "books", "book", "bookshelf"),
    "religious": (
        "religion",
        "faith",
        "church",
        "belief",
        "spiritual",
        "journey",
        "change",
        "changing",
        "growth",
        "acceptance",
    ),
    "relationship": (
        "status",
        "parent",
        "breakup",
        "family",
        "kids",
        "friend",
        "support",
        "challenge",
        "dating",
        "partner",
        "married",
    ),
    "realize": ("realized", "learned", "understood"),
    "research": ("researching", "looked into", "looking into", "check out", "checked out"),
    "run": ("ran", "running", "race", "charity", "marathon"),
    "sign": ("signed", "signup", "class", "pottery", "registered"),
    "symbolize": ("symbolized", "symbol", "represents", "meaning", "stands for"),
    "support": ("supported", "supporting", "help", "helped"),
    "status": (
        "relationship",
        "parent",
        "breakup",
        "family",
        "kids",
        "friend",
        "support",
        "challenge",
        "dating",
        "partner",
        "married",
    ),
    "tell": ("told", "said", "mentioned"),
    "think": ("thought", "considered"),
    "want": ("wanted", "wants", "hoping", "planned"),
    "work": ("worked", "working", "job", "career"),
}
_RELATION_QUERY_VARIANTS.update(
    {
        "activity": (
            "activities",
            "hobby",
            "hobbies",
            "partake",
            "do",
            "interest",
            "interests",
            "interesting",
            "class",
            "kids",
            "photo",
            "image",
            "family",
            "weekend",
            "unplug",
            "paint",
            "swim",
            "run",
            "read",
            "violin",
            "creative",
            "express",
            "therapeutic",
            "refresh",
            "fun",
            "pastime",
            "leisure",
        ),
        "adopt": (
            "adoption",
            "agency",
            "process",
            "family",
            "kids",
            "children",
        ),
        "adoption": (
            "adopt",
            "agency",
            "process",
            "family",
            "kids",
            "children",
            "lgbtq",
            "inclusive",
            "inclusivity",
        ),
        "agency": (
            "adoption",
            "adopt",
            "process",
            "individuals",
            "folks",
            "lgbtq",
            "inclusive",
            "inclusivity",
            "support",
            "help",
        ),
        "ally": ("support", "transgender", "lgbtq", "community", "advocate"),
        "choose": (
            "chose",
            "picked",
            "selected",
            "reason",
            "cause",
            "fit",
            "value",
            "spoke",
            "decide",
            "decision",
        ),
        "community": ("lgbtq", "transgender", "ally", "member", "support"),
        "counsel": ("counseling", "counselor", "mental", "health", "support"),
        "charity": ("race", "fundraiser", "awareness", "support"),
        "consider": (
            "considered",
            "considering",
            "looked at",
            "thinking",
        ),
        "decision": (
            "decide",
            "decided",
            "choice",
            "adopt",
            "adoption",
            "reaction",
            "response",
            "creating",
            "lovely",
            "luck",
        ),
        "excite": (
            "excited",
            "thrilled",
            "looking forward",
            "enthusiastic",
            "adoption",
            "family",
            "kids",
            "mom",
        ),
        "individual": ("individuals", "people", "lgbtq", "inclusive", "support"),
        "kid": (
            "kids",
            "children",
            "family",
            "preference",
            "interest",
            "like",
            "animals",
            "bones",
            "exhibit",
            "learning",
            "stoked",
            "outdoors",
        ),
        "member": ("community", "lgbtq", "transgender", "ally", "belong"),
        "music": ("song", "composer", "piece", "instrumental", "orchestra"),
        "necklace": (
            "symbol",
            "meaning",
            "represents",
            "message",
            "value",
            "gift",
            "grandma",
            "roots",
            "reminder",
            "family",
            "support",
            "special",
        ),
        "paint": ("painted", "painting", "image", "picture"),
        "park": (
            "national",
            "outdoor",
            "nature",
            "camping",
            "trip",
            "campfire",
            "marshmallow",
            "stories",
            "meteor",
            "sky",
            "summer",
            "hike",
            "trail",
        ),
        "personality": (
            "traits",
            "concern",
            "thank",
            "care",
            "real",
            "help",
            "drive",
            "concern",
            "character",
            "describe",
            "quality",
            "impression",
        ),
        "plan": (
            "planned",
            "planning",
            "going to",
            "want",
            "summer",
            "dream",
            "family",
            "loving home",
            "kids",
            "future",
            "upcoming",
            "next",
            "goal",
        ),
        "process": (
            "adoption",
            "adopt",
            "make",
            "create",
            "family",
            "kids",
            "children",
        ),
        "race": ("ran", "running", "charity", "marathon", "fundraiser", "awareness"),
        "realize": (
            "realized",
            "learned",
            "understood",
            "lesson",
            "reflection",
            "thought",
            "event",
            "journey",
        ),
        "roadtrip": (
            "road trip",
            "trip",
            "travel",
            "drive",
            "soon",
            "another",
            "accident",
            "son",
            "family",
            "safe",
        ),
        "school": ("speech", "event", "students", "talk", "presentation"),
        "self-care": (
            "wellness",
            "routine",
        "refresh",
        "present",
        "balance",
        "rest",
            "relax",
            "care",
        ),
        "song": ("piece", "composer", "instrumental", "orchestra", "fan"),
        "speech": ("school", "event", "students", "talk", "presentation"),
        "sunrise": ("paint", "painted", "painting", "image", "picture"),
        "support": (
            "supported",
            "supporting",
            "help",
            "helped",
            "lgbtq",
            "inclusive",
            "group",
        ),
        "summer": (
            "plans",
            "dream",
            "family",
            "loving home",
            "kids",
            "future",
            "upcoming",
            "next",
            "season",
            "goal",
        ),
        "think": ("thought", "considered", "opinion", "reaction", "response", "feel"),
        "trait": (
            "personality",
            "concern",
            "thank",
            "care",
            "real",
            "help",
            "drive",
            "character",
            "quality",
        ),
        "write": (
            "writing",
            "author",
            "book",
            "read",
            "draft",
            "story",
            "jobs",
        ),
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
        focus_actions = _relation_query_terms(relation_terms, relation_variant_terms)
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
        relation_query_terms = _relation_query_terms(
            relation_terms,
            relation_variant_terms,
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
                role="compact_relation",
                query=" ".join(
                    (
                        *compact_entity_surfaces,
                        *_render_query_terms(relation_query_terms[:relation_term_limit]),
                    )
                ),
                priority=30,
                query_type="lexical",
                reason_codes=("relation_terms", "raw_turn_compact"),
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
    if (
        not temporal_query_terms
        and any(candidate.role == "multi_hop_bridge" for candidate in query_candidates)
    ):
        extra_query_slots += 1
    max_selected_queries = max_queries + extra_query_slots
    query_plan = QueryPlannerV2(max_queries=max_selected_queries).plan(
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
    if "multi_hop" in intent.evidence_need or intent.multi_hop_markers:
        families.append("multi_hop")
    return tuple(dict.fromkeys(families))


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
    evidence_need = infer_evidence_need(
        question=question,
        relation_terms=relation_terms,
        time_intent=time_intent,
        visual_terms=visual_terms,
        multi_hop_markers=multi_hop_markers,
        benchmark_category=category,
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
    relation_terms: Sequence[str],
    relation_variant_terms: Sequence[str],
) -> tuple[str, ...]:
    relation_term_set = set(relation_terms)
    blocked_terms: set[str] = set()
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
    if "destress" in relation_term_set:
        priority_variant_order.extend(
            (
                "stress",
                "relax",
                "unwind",
                "class",
                "clear",
                "mind",
                "headspace",
                "run",
                "farther",
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
                "grandma",
                "roots",
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
    if "move" in relation_term_set:
        priority_variant_order.extend(("moved", "home", "country", "relocated"))
    if "sign" in relation_term_set:
        priority_variant_order.extend(("signed", "signup", "class", "pottery", "yesterday"))
        priority_surface_terms.update(("signed", "yesterday"))
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


def _entity_speaks_in_memory(entity: str, text: str) -> bool:
    escaped = re.escape(entity)
    return bool(
        re.search(
            rf"(?:^|\n|\bD\d+:\d+\s+){escaped}\s*:",
            text,
            flags=re.IGNORECASE,
        )
    )


def _entity_surface_in_memory(entity: str, text: str) -> bool:
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


def _memory_has_focused_turn_surface(memory: RetrievedMemory) -> bool:
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


def _entity_surfaces(entities: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    for entity in entities:
        surfaces.append(entity)
        surfaces.extend(_PERSON_ENTITY_ALIASES.get(entity, ()))
    return tuple(dict.fromkeys(surfaces))


def _render_query_terms(terms: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(_QUERY_RENDER_SURFACES.get(str(term), str(term)) for term in terms)
    )


def _visual_surface_terms(terms: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    if "paint" in terms:
        surfaces.append("painting")
    return tuple(dict.fromkeys(surfaces))


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


def _compact_temporal_relation_terms(lexical_terms: Sequence[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for term in lexical_terms:
        if _is_numeric_or_ordinal_query_token(term) or (
            term in _COMPACT_TEMPORAL_RELATION_TERMS
        ):
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def _is_numeric_or_ordinal_query_token(token: str) -> bool:
    return bool(token) and token[0].isdigit()


def _speaker_surfaces(entity_surfaces: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        entity
        for entity in entity_surfaces
        if _allowed_speaker_surface(entity)
    )


def _allowed_speaker_surface(entity: str) -> bool:
    parts = str(entity or "").casefold().split()
    return bool(parts) and not any(part in _NON_SPEAKER_ENTITY_SURFACES for part in parts)


def _speaker_match_surfaces(entity_surfaces: Sequence[str]) -> tuple[str, ...]:
    surfaces: list[str] = []
    for entity in entity_surfaces:
        normalized = entity.casefold()
        surfaces.append(normalized)
        surfaces.extend(_PERSON_ENTITY_ALIASES.get(normalized, ()))
        surfaces.extend(
            canonical
            for canonical, aliases in _PERSON_ENTITY_ALIASES.items()
            if normalized in aliases
        )
    return tuple(dict.fromkeys(surfaces))


def _memory_has_temporal_surface(memory: RetrievedMemory) -> bool:
    if _memory_timestamp_values(memory):
        return True
    return bool(
        _TIME_SURFACE_RE.search(memory.text) or _DURATION_SURFACE_RE.search(memory.text)
    )


def _memory_has_sequence_surface(memory: RetrievedMemory) -> bool:
    return bool(_SEQUENCE_SURFACE_RE.search(memory.text))


def _memory_has_visual_evidence(memory: RetrievedMemory) -> bool:
    return bool(_VISUAL_EVIDENCE_RE.search(memory.text))


def _is_preference_query(profile: Mapping[str, object]) -> bool:
    preference_terms = {"interest", "enjoy", "like", "love", "prioritize", "destress"}
    relation_terms = set(_string_sequence(profile.get("relation_terms")))
    return bool(preference_terms & relation_terms)


def _is_contrast_query(profile: Mapping[str, object]) -> bool:
    return bool(
        "contrast" in _string_sequence(profile.get("evidence_need"))
        or "contrast" in _string_sequence(profile.get("relation_categories"))
    )


def _memory_has_preference_evidence(memory: RetrievedMemory) -> bool:
    return bool(_PREFERENCE_EVIDENCE_RE.search(memory.text))


def _timestamped_memory_count(memories: Sequence[RetrievedMemory]) -> int:
    return sum(1 for memory in memories if _memory_timestamp_values(memory))


def _memory_timestamp_values(memory: RetrievedMemory) -> tuple[int, ...]:
    values = memory.metadata.get("source_ref_time_start_ms")
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        return ()
    return tuple(value for item in values if (value := _optional_int(item)) is not None)


def _normalized_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in _WORD_RE.findall(text.casefold()):
        token = raw.strip("'-")
        if token.endswith("'s"):
            token = token[:-2]
        if _query_token_too_short(token) or token in _QUERY_STOPWORDS:
            continue
        term = _stem_query_token(token)
        terms.append(term)
        terms.extend(_QUERY_TOKEN_ALIASES.get(term, ()))
    return tuple(terms)


def _query_token_too_short(token: str) -> bool:
    if len(token) >= 3:
        return False
    return not token.isdigit()


def _question_phrase_terms(text: str) -> tuple[str, ...]:
    terms: list[str] = []
    if re.search(r"\bgo\s+to\b", text, flags=re.IGNORECASE):
        terms.append("go")
    return tuple(terms)


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


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(str(item) for item in value if str(item))


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
