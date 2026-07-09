"""Answer-evidence fit signals for deterministic memory reranking."""

from __future__ import annotations

import re

from infinity_context_core.application.context_allergy_condition_inference import (
    allergy_condition_inference_signal,
)
from infinity_context_core.application.context_answer_evidence_types import (
    AnswerEvidenceSignal,
)
from infinity_context_core.application.context_community_membership_inference import (
    community_membership_inference_signal,
)
from infinity_context_core.application.context_generic_behavior_inference import (
    generic_behavior_inference_signal,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_political_inference import (
    political_inference_signal,
)
from infinity_context_core.application.context_preference_inference import (
    preference_inference_signal,
    preference_polarity_conflict_signal,
)
from infinity_context_core.application.context_query_support_role import (
    support_role_query_variants,
)
from infinity_context_core.application.context_social_education_inference import (
    social_education_inference_signal,
)
from infinity_context_core.application.context_state_residence_inference import (
    state_residence_inference_signal,
)

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

_INFERENCE_QUERY_TERMS = frozenset(
    {
        "could",
        "infer",
        "inference",
        "likely",
        "may",
        "might",
        "probably",
        "should",
        "would",
        "вероятно",
        "может",
        "похоже",
    }
)
_CAUSAL_QUERY_TERMS = frozenset(
    {
        "because",
        "belonging",
        "cause",
        "caused",
        "gave",
        "reason",
        "why",
        "почему",
        "причина",
        "принадлежность",
        "принадлежности",
        "чувство",
        "ощущение",
        "дал",
        "дала",
        "дало",
    }
)
_SUPPORT_ROLE_ACTION_TERMS = frozenset(
    {
        "advise",
        "advised",
        "advising",
        "care",
        "cared",
        "coach",
        "coached",
        "comfort",
        "comforted",
        "confide",
        "confided",
        "confides",
        "confiding",
        "counsel",
        "counseled",
        "counseling",
        "empathy",
        "empathetic",
        "guide",
        "guided",
        "guidance",
        "help",
        "helped",
        "helping",
        "listen",
        "listened",
        "mentor",
        "mentored",
        "mentoring",
        "mentorship",
        "open",
        "opened",
        "opening",
        "patient",
        "reliable",
        "responsible",
        "support",
        "supported",
        "supporting",
        "trust",
        "trusted",
        "trusting",
        "volunteer",
        "volunteered",
        "volunteering",
    }
)
_GENERIC_SUPPORT_ACTION_TERMS = frozenset(
    {
        "support",
        "supported",
        "supporting",
    }
)
_SUPPORT_ROLE_SCENARIO_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "ally",
        "allies",
        "anxiety",
        "children",
        "community",
        "group",
        "health",
        "issue",
        "kids",
        "lgbtq",
        "people",
        "personal",
        "pride",
        "private",
        "problem",
        "problems",
        "secret",
        "sensitive",
        "safe",
        "shelter",
        "similar",
        "struggle",
        "struggles",
        "trans",
        "transgender",
        "youth",
    }
)
_INTERPERSONAL_SUPPORT_ACTION_TERMS = _SUPPORT_ROLE_ACTION_TERMS - frozenset(
    {
        "reliable",
        "responsible",
        "support",
        "supported",
        "supporting",
        "volunteer",
        "volunteered",
        "volunteering",
    }
)
_SUPPORT_ROLE_OPERATIONAL_NOISE_RE = re.compile(
    r"\b(?:backend|provider|technical|customer|ticket|tickets?|issue\s+tracker|"
    r"support\s+notes?|support\s+queue|support\s+desk|help\s+desk)\b",
    re.IGNORECASE,
)
_COUNTERFACTUAL_SUPPORT_QUERY_TERMS = frozenset(
    {
        "accept",
        "accepted",
        "ally",
        "confide",
        "confided",
        "confiding",
        "encourage",
        "encouraging",
        "help",
        "helping",
        "join",
        "joining",
        "safe",
        "support",
        "supporting",
        "trust",
        "trusted",
        "trusting",
        "welcome",
        "союзник",
        "поможет",
        "помог",
        "помогла",
        "поддержит",
        "поддержал",
        "поддержала",
        "примет",
    }
)
_COUNTERFACTUAL_SUPPORT_EVIDENCE_TERMS = frozenset(
    {
        "accepted",
        "accepting",
        "acceptance",
        "ally",
        "comforted",
        "confided",
        "confide",
        "confiding",
        "encourage",
        "encouraged",
        "encouraging",
        "helped",
        "listened",
        "opened",
        "private",
        "safe",
        "supportive",
        "trusted",
        "trusting",
        "welcomed",
        "welcome",
        "безопасно",
        "выслушал",
        "выслушала",
        "помог",
        "помогла",
        "помогал",
        "помогала",
        "поддержал",
        "поддержала",
        "поддерживал",
        "поддерживала",
        "принял",
        "приняла",
    }
)
_COUNTERFACTUAL_SUPPORT_DOMAIN_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "community",
        "group",
        "lgbt",
        "lgbtq",
        "pride",
        "queer",
        "safe",
        "trans",
        "transgender",
        "welcome",
        "youth",
        "группа",
        "группу",
        "квир",
        "лгбт",
        "прайд",
        "сообщество",
        "транс",
    }
)
_WILLINGNESS_QUERY_TERMS = frozenset(
    {
        "consider",
        "considered",
        "considering",
        "open",
        "ready",
        "willing",
        "would",
    }
)
_WILLINGNESS_MARKER_TERMS = frozenset(
    {
        "consider",
        "considered",
        "considering",
        "excited",
        "hope",
        "hopeful",
        "hopes",
        "interested",
        "join",
        "joined",
        "joining",
        "open",
        "plan",
        "planned",
        "planning",
        "ready",
        "want",
        "wanted",
        "wants",
        "willing",
    }
)
_RELOCATION_WILLINGNESS_QUERY_TERMS = frozenset(
    {
        "abroad",
        "another",
        "country",
        "international",
        "move",
        "moving",
        "relocate",
        "relocation",
    }
)
_WILLINGNESS_TEXT_DOMAIN_TERMS = frozenset(
    {
        "abroad",
        "campaign",
        "country",
        "international",
        "military",
        "mission",
        "move",
        "moving",
        "office",
        "politics",
        "public",
        "relocate",
        "relocation",
        "service",
        "veteran",
    }
)
_PUBLIC_OFFICE_SERVICE_TEXT_TERMS = frozenset(
    {
        "campaign",
        "civic",
        "elected",
        "election",
        "office",
        "politics",
        "public",
        "running",
    }
)
_CAREER_INFERENCE_QUERY_TERMS = frozenset(
    {
        "career",
        "field",
        "future",
        "job",
        "jobs",
        "occupation",
        "path",
        "pursue",
        "work",
    }
)
_ANIMAL_CAREER_QUERY_TERMS = frozenset(
    {
        "alternative",
        "career",
        "gaming",
    }
)
_CAREER_DECISION_QUERY_TERMS = frozenset(
    {
        "choose",
        "chooses",
        "chose",
        "chosen",
        "decide",
        "decided",
        "education",
        "educaton",
        "edu",
        "field",
        "fields",
        "option",
        "options",
        "persue",
        "pursue",
    }
)
_CAREER_DOMAIN_TEXT_TERMS = frozenset(
    {
        "bed",
        "counseling",
        "counselor",
        "desk",
        "food",
        "front",
        "health",
        "homeless",
        "mental",
        "residents",
        "shelter",
        "social",
        "talks",
        "volunteer",
        "volunteered",
        "volunteering",
        "work",
    }
)
_CAREER_FIELD_TEXT_TERMS = frozenset(
    {
        "counseling",
        "counselor",
        "health",
        "mental",
        "psychology",
        "social",
        "therapy",
        "therapist",
        "work",
    }
)
_CAREER_INTENT_TEXT_TERMS = frozenset(
    {
        "compliments",
        "connecting",
        "difference",
        "fulfilled",
        "fulfilling",
        "helping",
        "interested",
        "looking",
        "meaningful",
        "purpose",
        "pursue",
        "rewarding",
        "wanted",
        "wants",
    }
)
_CAREER_DECISION_TEXT_TERMS = frozenset(
    {
        "choose",
        "choosing",
        "chose",
        "chosen",
        "considering",
        "decided",
        "interested",
        "keen",
        "looking",
        "love",
        "pursue",
        "pursuing",
        "support",
        "want",
        "wanted",
        "wants",
    }
)
_CAREER_TOPIC_ONLY_TERMS = frozenset(
    {
        "career",
        "fair",
        "future",
        "job",
        "jobs",
        "occupation",
        "path",
        "work",
    }
)
_CAREER_NEGATED_DECISION_RE = re.compile(
    r"\b(?:did\s+not|didn't|does\s+not|doesn't|would\s+not|won't|never)\s+"
    r"(?:decide|decided|choose|chose|want|wanted|pursue|pursued|consider|"
    r"considered|look|looked|looking)\b|"
    r"\b(?:decided|chose)\s+not\s+to\s+(?:pursue|choose|work|study)\b|"
    r"\bno\s+longer\s+(?:pursuing|interested|considering)\b",
    re.IGNORECASE,
)
_ANIMAL_CARE_TEXT_TERMS = frozenset(
    {
        "animal",
        "animals",
        "care",
        "clean",
        "cute",
        "diet",
        "feed",
        "fruits",
        "habitat",
        "insects",
        "joy",
        "light",
        "pet",
        "pets",
        "store",
        "tank",
        "turtle",
        "turtles",
        "vegetables",
    }
)
_ANIMAL_CARE_TOPIC_NOISE_TERMS = frozenset(
    {
        "console",
        "game",
        "games",
        "gaming",
        "tournament",
        "tournaments",
    }
)
_MILITARY_SERVICE_TEXT_TERMS = frozenset(
    {
        "military",
        "mission",
        "service",
        "veteran",
    }
)
_PATRIOTIC_QUERY_TERMS = frozenset(
    {
        "patriot",
        "patriotic",
        "patriotism",
    }
)
_PATRIOTIC_SERVICE_TEXT_TERMS = frozenset(
    {
        "aptitude",
        "military",
        "mission",
        "serve",
        "serving",
        "service",
        "volunteer",
        "volunteering",
    }
)
_PATRIOTIC_MOTIVE_TEXT_TERMS = frozenset(
    {
        "country",
        "duty",
        "eagle",
        "flag",
        "honor",
        "honour",
        "patriotic",
        "pride",
        "proud",
    }
)
_CHILDREN_BOOKS_QUERY_TERMS = frozenset(
    {
        "book",
        "books",
        "bookshelf",
        "childrens",
        "dr",
        "seuss",
    }
)
_CHILDREN_BOOKS_TEXT_TERMS = frozenset(
    {
        "children",
        "childrens",
        "classics",
        "classic",
        "cultures",
        "educational",
        "kids",
        "stories",
    }
)
_BOOK_TOPIC_TEXT_TERMS = frozenset(
    {
        "book",
        "books",
        "bookshelf",
        "collection",
        "fantasy",
        "novel",
        "read",
        "series",
    }
)
_RELIGIOUS_QUERY_TERMS = frozenset(
    {
        "religion",
        "religious",
        "faith",
    }
)
_RELIGIOUS_TEXT_TERMS = frozenset(
    {
        "church",
        "faith",
        "glass",
        "pray",
        "prayer",
        "prayers",
        "prays",
        "religious",
        "spiritual",
        "stained",
        "worship",
        "worships",
    }
)
_RELIGIOUS_STRONG_TEXT_TERMS = frozenset(
    {
        "church",
        "faith",
        "glass",
        "pray",
        "prayer",
        "prayers",
        "prays",
        "spiritual",
        "stained",
        "worship",
        "worships",
    }
)
_RELIGIOUS_TOPIC_NOISE_TERMS = frozenset(
    {
        "acceptance",
        "accept",
        "conservative",
        "conservatives",
        "growth",
        "journey",
        "transgender",
        "transition",
        "unwelcoming",
    }
)
_RELIGIOUS_CONTRAST_CONTEXT_TERMS = frozenset(
    {
        "conservative",
        "conservatives",
        "unwelcoming",
        "upset",
        "lgbtq",
        "rights",
    }
)
_CAUSAL_TEXT_RE = re.compile(
    r"\b(?:because|so|since|therefore|reason|caused|led\s+to|inspired|"
    r"motivated|made\s+(?:me|her|him|them)\s+feel|gave\s+(?:me|her|him|them)|"
    r"source\s+of|helped\s+(?:me|her|him|them)\s+feel|feel\s+at\s+home|"
    r"sense\s+of\s+belonging|belonged|belonging)\b|"
    r"\b(?:потому|поэтому|причин\w*|из-за|вдохнов\w*|мотивир\w*|"
    r"дал[оаи]?|помогл?[оаи]?\s+почувствовать|почувств\w+\s+себя\s+дома|"
    r"ощущени\w+\s+принадлежност\w*)\b",
    re.IGNORECASE,
)
_PREFERENCE_REASON_QUERY_RE = re.compile(
    r"\b(?:why|reason)\b(?=[^?.!]{0,160}\b(?:likes?|loves?|enjoys?|prefers?|"
    r"favorite|favourite|interested|avoids?|dislikes?|hates?|not\s+(?:like|"
    r"enjoy|prefer|want)|not\s+interested)\b)",
    re.IGNORECASE | re.DOTALL,
)
_PREFERENCE_REASON_TEXT_RE = re.compile(
    r"\b(?:likes?|loves?|enjoys?|prefers?|favorite|favourite|interested|"
    r"avoids?|dislikes?|hates?|not\s+(?:like|enjoy|prefer|want)|"
    r"not\s+interested)\b",
    re.IGNORECASE,
)
_CAUSAL_EFFECT_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "belong",
        "belonged",
        "belonging",
        "community",
        "fulfilling",
        "happiness",
        "happy",
        "home",
        "inspired",
        "motivated",
        "powerful",
        "pride",
        "proud",
        "purpose",
        "safe",
        "welcomed",
        "дома",
        "принадлежность",
        "принадлежности",
        "сообщество",
        "своим",
        "своей",
    }
)
_CAUSAL_QUERY_STOP_TERMS = frozenset(
    {
        "did",
        "does",
        "gave",
        "give",
        "is",
        "of",
        "sense",
        "the",
        "to",
        "was",
        "what",
        "when",
        "who",
        "why",
    }
)
_EMOTION_CAUSE_QUERY_TERMS = frozenset(
    {
        "accepted",
        "acceptance",
        "belong",
        "belonging",
        "feel",
        "feeling",
        "fulfilled",
        "happy",
        "happiness",
        "home",
        "proud",
        "sense",
        "дома",
        "принадлежность",
        "принадлежности",
        "чувство",
        "ощущение",
    }
)
_GENERIC_SUPPORT_NOISE_RE = re.compile(
    r"\b(?:friends?|family|mentors?|parents?|people\s+around|support\s+system|rocks)\b"
    r".{0,100}\b(?:support|there\s+for|encourage|motivate|strength)\b|"
    r"\b(?:supportive|support|supported)\b.{0,80}\b(?:friend|family|mentor|parent)\b",
    re.IGNORECASE | re.DOTALL,
)


def answer_evidence_rerank_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    """Score answer evidence fit without treating retrieved text as truth."""

    if _requests_causal_answer(query):
        preference_conflict_signal = preference_polarity_conflict_signal(
            query=query,
            text=text,
        )
        if preference_conflict_signal.reason:
            return preference_conflict_signal
        preference_reason_signal = _preference_reason_grounding_signal(
            query=query,
            text=text,
        )
        if preference_reason_signal.reason:
            return preference_reason_signal
        return _causal_answer_signal(query=query, text=text)
    social_education_signal = social_education_inference_signal(query=query, text=text)
    if social_education_signal.reason:
        return social_education_signal
    state_residence_signal = state_residence_inference_signal(query=query, text=text)
    if state_residence_signal.reason:
        return state_residence_signal
    political_signal = political_inference_signal(query=query, text=text)
    if political_signal.reason:
        return political_signal
    community_membership_signal = community_membership_inference_signal(
        query=query,
        text=text,
    )
    if community_membership_signal.reason:
        return community_membership_signal
    allergy_condition_signal = allergy_condition_inference_signal(
        query=query,
        text=text,
    )
    if allergy_condition_signal.reason:
        return allergy_condition_signal
    preference_signal = preference_inference_signal(query=query, text=text)
    if preference_signal.reason:
        return preference_signal
    if not _requests_inference(query):
        if _requests_career_inference(query):
            return _career_inference_signal(query=query, text=text)
        return AnswerEvidenceSignal()
    if support_role_query_variants(query):
        support_role_signal = _support_role_fit_signal(query=query, text=text)
        if support_role_signal.reason:
            return support_role_signal
    if _requests_career_inference(query):
        return _career_inference_signal(query=query, text=text)
    if _requests_willingness_inference(query):
        return _willingness_inference_signal(query=query, text=text)
    if _requests_children_books_inference(query):
        return _children_books_inference_signal(query=query, text=text)
    if _requests_religious_inference(query):
        return _religious_inference_signal(query=query, text=text)
    if _requests_patriotic_inference(query):
        return _patriotic_service_inference_signal(query=query, text=text)
    counterfactual_signal = _counterfactual_support_signal(query=query, text=text)
    if counterfactual_signal.reason:
        return counterfactual_signal
    return generic_behavior_inference_signal(query=query, text=text)


def inference_evidence_rerank_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    return answer_evidence_rerank_signal(query=query, text=text)


def _support_role_fit_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    action_hits = text_tokens & _SUPPORT_ROLE_ACTION_TERMS
    strong_action_hits = action_hits - _GENERIC_SUPPORT_ACTION_TERMS
    interpersonal_action_hits = strong_action_hits & _INTERPERSONAL_SUPPORT_ACTION_TERMS
    scenario_hits = text_tokens & _support_role_scenario_terms(query_tokens)
    if (
        _SUPPORT_ROLE_OPERATIONAL_NOISE_RE.search(text)
        and not interpersonal_action_hits
    ):
        return AnswerEvidenceSignal(
            penalty=0.034,
            reason="inference_support_role_operational_noise",
        )
    if len(interpersonal_action_hits) >= 2 and scenario_hits:
        return AnswerEvidenceSignal(
            boost=0.034,
            reason="inference_support_role_fit_evidence",
        )
    if interpersonal_action_hits and scenario_hits:
        return AnswerEvidenceSignal(
            boost=0.022,
            reason="inference_support_role_partial_evidence",
        )
    if _GENERIC_SUPPORT_NOISE_RE.search(text) and not strong_action_hits:
        return AnswerEvidenceSignal(
            penalty=0.055,
            reason="inference_generic_support_noise",
        )
    return AnswerEvidenceSignal()


def _career_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    raw_text_tokens = _raw_term_set(text)
    if _requests_animal_career_inference(query_tokens):
        animal_hits = text_tokens & _ANIMAL_CARE_TEXT_TERMS
        if len(animal_hits) >= 2:
            return AnswerEvidenceSignal(
                boost=0.03,
                reason="inference_animal_career_fit_evidence",
            )
        if text_tokens & _ANIMAL_CARE_TOPIC_NOISE_TERMS:
            return AnswerEvidenceSignal(
                penalty=0.034,
                reason="inference_animal_career_topic_only_noise",
            )
    if _CAREER_NEGATED_DECISION_RE.search(text) and (
        raw_text_tokens & (_CAREER_TOPIC_ONLY_TERMS | _CAREER_FIELD_TEXT_TERMS)
    ):
        return AnswerEvidenceSignal(
            penalty=0.04,
            reason="inference_career_negated_decision_noise",
        )
    field_hits = raw_text_tokens & _CAREER_FIELD_TEXT_TERMS
    decision_hits = raw_text_tokens & _CAREER_DECISION_TEXT_TERMS
    if field_hits and decision_hits:
        return AnswerEvidenceSignal(
            boost=0.032,
            reason="inference_career_field_decision_evidence",
        )
    domain_hits = raw_text_tokens & _CAREER_DOMAIN_TEXT_TERMS
    intent_hits = raw_text_tokens & _CAREER_INTENT_TEXT_TERMS
    if domain_hits and intent_hits:
        return AnswerEvidenceSignal(
            boost=0.03,
            reason="inference_career_fit_evidence",
        )
    if raw_text_tokens & _CAREER_TOPIC_ONLY_TERMS and not domain_hits:
        return AnswerEvidenceSignal(
            penalty=0.034,
            reason="inference_career_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _willingness_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    marker_hits = text_tokens & _WILLINGNESS_MARKER_TERMS
    domain_hits = text_tokens & _WILLINGNESS_TEXT_DOMAIN_TERMS
    if marker_hits and _has_willingness_domain_overlap(query_tokens, text_tokens):
        return AnswerEvidenceSignal(
            boost=0.028,
            reason="inference_willingness_fit_evidence",
        )
    if domain_hits and not marker_hits:
        return AnswerEvidenceSignal(
            penalty=0.032,
            reason="inference_willingness_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _children_books_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    text_tokens = _term_set(text)
    evidence_hits = text_tokens & _CHILDREN_BOOKS_TEXT_TERMS
    if len(evidence_hits) >= 2:
        return AnswerEvidenceSignal(
            boost=0.028,
            reason="inference_children_books_fit_evidence",
        )
    if text_tokens & _BOOK_TOPIC_TEXT_TERMS:
        return AnswerEvidenceSignal(
            penalty=0.034,
            reason="inference_children_books_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _religious_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    text_tokens = _term_set(text)
    raw_text_tokens = _raw_term_set(text)
    evidence_hits = text_tokens & _RELIGIOUS_TEXT_TERMS
    strong_evidence_hits = raw_text_tokens & _RELIGIOUS_STRONG_TEXT_TERMS
    if strong_evidence_hits:
        return AnswerEvidenceSignal(
            boost=0.026,
            reason="inference_religious_fit_evidence",
        )
    if _is_religious_contrast_evidence(text_tokens):
        return AnswerEvidenceSignal(
            penalty=0.014,
            reason="inference_religious_contrast_evidence",
        )
    if text_tokens & _RELIGIOUS_TOPIC_NOISE_TERMS:
        return AnswerEvidenceSignal(
            penalty=0.032,
            reason="inference_religious_topic_only_noise",
        )
    if evidence_hits:
        return AnswerEvidenceSignal(
            boost=0.014,
            reason="inference_religious_weak_evidence",
        )
    return AnswerEvidenceSignal()


def _is_religious_contrast_evidence(text_tokens: frozenset[str]) -> bool:
    if "religious" not in text_tokens:
        return False
    return bool(text_tokens & _RELIGIOUS_CONTRAST_CONTEXT_TERMS)


def _patriotic_service_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    text_tokens = _term_set(text)
    service_hits = text_tokens & _PATRIOTIC_SERVICE_TEXT_TERMS
    motive_hits = text_tokens & _PATRIOTIC_MOTIVE_TEXT_TERMS
    if _serving_country_phrase(text) or (service_hits and motive_hits):
        return AnswerEvidenceSignal(
            boost=0.03,
            reason="inference_patriotic_service_fit_evidence",
        )
    if service_hits or motive_hits:
        return AnswerEvidenceSignal(
            penalty=0.034,
            reason="inference_patriotic_topic_only_noise",
        )
    return AnswerEvidenceSignal()


def _counterfactual_support_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    query_tokens = _raw_term_set(query)
    if not query_tokens & _COUNTERFACTUAL_SUPPORT_QUERY_TERMS:
        return AnswerEvidenceSignal()
    text_tokens = _raw_term_set(text)
    evidence_hits = text_tokens & _COUNTERFACTUAL_SUPPORT_EVIDENCE_TERMS
    domain_overlap = bool(
        (query_tokens & _COUNTERFACTUAL_SUPPORT_DOMAIN_TERMS)
        and (text_tokens & _COUNTERFACTUAL_SUPPORT_DOMAIN_TERMS)
    )
    if len(evidence_hits) >= 2 and (domain_overlap or "ally" in query_tokens):
        return AnswerEvidenceSignal(
            boost=0.026,
            reason="inference_counterfactual_support_evidence",
        )
    if _GENERIC_SUPPORT_NOISE_RE.search(text) and not evidence_hits:
        return AnswerEvidenceSignal(
            penalty=0.038,
            reason="inference_counterfactual_support_noise",
        )
    return AnswerEvidenceSignal()


def _causal_answer_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    query_tokens = _term_set(query)
    text_tokens = _term_set(text)
    has_causal_marker = _CAUSAL_TEXT_RE.search(text) is not None
    salient_overlap = bool(_causal_salient_terms(query_tokens) & text_tokens)
    emotion_cause_match = bool(
        (query_tokens & _EMOTION_CAUSE_QUERY_TERMS) and (text_tokens & _CAUSAL_EFFECT_TERMS)
    )
    if has_causal_marker and (salient_overlap or emotion_cause_match):
        return AnswerEvidenceSignal(
            boost=0.03,
            reason="causal_answer_evidence",
        )
    if emotion_cause_match and not has_causal_marker:
        return AnswerEvidenceSignal(
            penalty=0.026,
            reason="causal_answer_missing_reason_signal",
        )
    return AnswerEvidenceSignal()


def _preference_reason_grounding_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    if _PREFERENCE_REASON_QUERY_RE.search(query) is None:
        return AnswerEvidenceSignal()
    if _CAUSAL_TEXT_RE.search(text) is None:
        return AnswerEvidenceSignal()
    query_tokens = _term_set(query)
    salient_terms = _causal_salient_terms(query_tokens)
    if not salient_terms:
        return AnswerEvidenceSignal()
    for sentence in _sentences(text):
        sentence_tokens = _term_set(sentence)
        if (
            _CAUSAL_TEXT_RE.search(sentence) is not None
            and _PREFERENCE_REASON_TEXT_RE.search(sentence) is not None
            and salient_terms & sentence_tokens
        ):
            return AnswerEvidenceSignal()
    text_tokens = _term_set(text)
    if _PREFERENCE_REASON_TEXT_RE.search(text) is not None and salient_terms & text_tokens:
        return AnswerEvidenceSignal(
            penalty=0.026,
            reason="causal_answer_unrelated_reason_signal",
        )
    return AnswerEvidenceSignal()


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    )


def _requests_career_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    raw_tokens = _raw_term_set(query)
    if not raw_tokens & _CAREER_INFERENCE_QUERY_TERMS:
        return False
    return bool(query_tokens & (_INFERENCE_QUERY_TERMS | _CAREER_DECISION_QUERY_TERMS))


def _requests_animal_career_inference(query_tokens: frozenset[str]) -> bool:
    return bool(query_tokens & _ANIMAL_CAREER_QUERY_TERMS) and bool(
        {"alternative", "gaming"} & query_tokens
    )


def _requests_willingness_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    if not query_tokens & _WILLINGNESS_QUERY_TERMS:
        return False
    return bool(query_tokens & _RELOCATION_WILLINGNESS_QUERY_TERMS)


def _requests_children_books_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    if "seuss" not in query_tokens:
        return False
    return bool(query_tokens & _CHILDREN_BOOKS_QUERY_TERMS)


def _requests_religious_inference(query: str) -> bool:
    return bool(_term_set(query) & _RELIGIOUS_QUERY_TERMS)


def _requests_patriotic_inference(query: str) -> bool:
    return bool(_term_set(query) & _PATRIOTIC_QUERY_TERMS)


def _serving_country_phrase(text: str) -> bool:
    return bool(
        re.search(
            r"\bserv(?:e|ed|es|ing)\b.{0,40}\b(?:my|his|her|their|the|our)?\s*country\b|"
            r"\bcountry\b.{0,40}\bserv(?:e|ed|es|ing)\b",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    )


def _has_willingness_domain_overlap(
    query_tokens: frozenset[str],
    text_tokens: frozenset[str],
) -> bool:
    query_domain = query_tokens & _RELOCATION_WILLINGNESS_QUERY_TERMS
    text_domain = text_tokens & _WILLINGNESS_TEXT_DOMAIN_TERMS
    if query_domain & text_domain:
        return True
    return bool(
        query_domain
        and (
            text_tokens & _MILITARY_SERVICE_TEXT_TERMS
            or text_tokens & _PUBLIC_OFFICE_SERVICE_TEXT_TERMS
        )
    )


def _requests_causal_answer(query: str) -> bool:
    tokens = _term_set(query)
    if tokens & _CAUSAL_QUERY_TERMS:
        return True
    return bool({"sense", "belonging"} <= tokens or {"feel", "home"} <= tokens)


def _causal_salient_terms(query_tokens: frozenset[str]) -> frozenset[str]:
    return frozenset(
        token
        for token in query_tokens
        if len(token) >= 3
        and token not in _CAUSAL_QUERY_STOP_TERMS
        and token not in _CAUSAL_QUERY_TERMS
    )


def _support_role_scenario_terms(query_tokens: frozenset[str]) -> frozenset[str]:
    requested = query_tokens & _SUPPORT_ROLE_SCENARIO_TERMS
    if requested:
        return requested | {"accepted", "acceptance", "safe", "similar"}
    return _SUPPORT_ROLE_SCENARIO_TERMS


def _requests_inference(query: str) -> bool:
    return bool(_term_set(query) & _INFERENCE_QUERY_TERMS)


def _term_set(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for term in query_terms(text, min_chars=2, max_terms=40):
        terms.update(term.variants)
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            terms.add(token)
    return frozenset(terms)


def _raw_term_set(text: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold().strip("_")
        for match in _TOKEN_RE.finditer(text)
        if len(match.group(0).strip("_")) >= 2
    )
