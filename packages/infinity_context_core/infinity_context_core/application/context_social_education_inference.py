"""Social and education inference evidence signals."""

from __future__ import annotations

import re

from infinity_context_core.application.context_answer_evidence_types import (
    AnswerEvidenceSignal,
)
from infinity_context_core.application.context_lexical import lexical_variants, query_terms

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_FRIEND_TEAM_EXCLUDED_PERSON_RE = re.compile(
    r"\b(?:besides|other\s+than|apart\s+from|кроме|помимо)\s+"
    r"([A-Za-zА-Яа-яЁё][\w._-]*)",
    re.IGNORECASE,
)

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
_FRIEND_TEAM_QUERY_TERMS = frozenset(
    {
        "apart",
        "besides",
        "friend",
        "friends",
        "other",
        "teammate",
        "teammates",
        "team",
        "than",
        "друг",
        "друзей",
        "друзья",
        "кроме",
        "помимо",
    }
)
_FRIEND_TEAM_PERSON_QUERY_TERMS = frozenset(
    {
        "friend",
        "friends",
        "teammate",
        "teammates",
        "друг",
        "друзей",
        "друзья",
    }
)
_FRIEND_TEAM_TEXT_TERMS = frozenset(
    {
        "buddies",
        "clan",
        "friend",
        "friends",
        "guild",
        "online",
        "squad",
        "team",
        "teammate",
        "teammates",
        "друг",
        "друзей",
        "друзья",
        "друзьями",
        "команда",
        "команде",
        "командой",
        "тиммейт",
        "тиммейты",
    }
)
_FRIEND_TEAM_ACTIVITY_TERMS = frozenset(
    {
        "champion",
        "console",
        "game",
        "games",
        "gaming",
        "play",
        "played",
        "plays",
        "tournament",
        "tournaments",
        "valorant",
        "video",
        "видеоигра",
        "игра",
        "играл",
        "играла",
        "играет",
        "играют",
        "команда",
        "командой",
        "онлайн",
        "турнир",
        "турнирах",
        "турнирам",
        "турниры",
    }
)
_DEGREE_FIELD_QUERY_TERMS = frozenset(
    {
        "degree",
        "major",
        "studied",
        "study",
        "university",
    }
)
_POLICY_DEGREE_TEXT_TERMS = frozenset(
    {
        "campaign",
        "civic",
        "government",
        "law",
        "legislation",
        "policy",
        "policymaking",
        "political",
        "politics",
        "public",
        "reform",
        "rights",
        "science",
    }
)
_DEGREE_STUDY_TEXT_TERMS = frozenset(
    {
        "college",
        "degree",
        "major",
        "school",
        "studied",
        "study",
        "university",
    }
)
_DEGREE_MEASUREMENT_NOISE_RE = re.compile(
    r"\b(?:degree|degrees)\b(?=.{0,40}\b(?:angle|temperature|fahrenheit|celsius|"
    r"weather|heat|cold|thermostat)\b)|"
    r"\b(?:angle|temperature|fahrenheit|celsius|weather|heat|cold|thermostat)\b"
    r"(?=.{0,40}\b(?:degree|degrees)\b)",
    re.IGNORECASE | re.DOTALL,
)


def social_education_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    """Return social or education answer-evidence signal, if the query asks for it."""

    if _requests_friend_team_inference(query):
        return _friend_team_inference_signal(query=query, text=text)
    if _requests_degree_field_inference(query):
        return _degree_field_inference_signal(text=text)
    return AnswerEvidenceSignal()


def _friend_team_inference_signal(*, query: str, text: str) -> AnswerEvidenceSignal:
    text_tokens = _term_set(text)
    friend_hits = text_tokens & _FRIEND_TEAM_TEXT_TERMS
    activity_hits = text_tokens & _FRIEND_TEAM_ACTIVITY_TERMS
    if friend_hits and activity_hits:
        return AnswerEvidenceSignal(
            boost=0.03,
            reason="inference_friend_team_evidence",
        )
    excluded_person_terms = _excluded_friend_comparator_terms(query)
    if excluded_person_terms and excluded_person_terms & text_tokens and not friend_hits:
        return AnswerEvidenceSignal(
            penalty=0.035,
            reason="inference_friend_team_single_contact_noise",
        )
    return AnswerEvidenceSignal()


def _degree_field_inference_signal(*, text: str) -> AnswerEvidenceSignal:
    text_tokens = _term_set(text)
    policy_hits = text_tokens & _POLICY_DEGREE_TEXT_TERMS
    study_hits = text_tokens & _DEGREE_STUDY_TEXT_TERMS
    if len(policy_hits) >= 2 and study_hits:
        return AnswerEvidenceSignal(
            boost=0.03,
            reason="inference_degree_policy_evidence",
        )
    if _DEGREE_MEASUREMENT_NOISE_RE.search(text):
        return AnswerEvidenceSignal(
            penalty=0.036,
            reason="inference_degree_measurement_noise",
        )
    return AnswerEvidenceSignal()


def _requests_friend_team_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    if not query_tokens & _FRIEND_TEAM_QUERY_TERMS:
        return False
    if query_tokens & _INFERENCE_QUERY_TERMS:
        return True
    if not query_tokens & _FRIEND_TEAM_PERSON_QUERY_TERMS:
        return False
    return bool(
        "besides" in query_tokens
        or {"other", "than"} <= query_tokens
        or {"apart", "from"} <= query_tokens
        or "кроме" in query_tokens
        or "помимо" in query_tokens
    )


def _excluded_friend_comparator_terms(query: str) -> frozenset[str]:
    match = _FRIEND_TEAM_EXCLUDED_PERSON_RE.search(query)
    if match is None:
        return frozenset()
    raw_name = match.group(1).casefold().strip("_")
    if len(raw_name) < 2:
        return frozenset()
    variants = {raw_name, *lexical_variants(raw_name)}
    if re.search(r"[а-яё]", raw_name, re.IGNORECASE):
        variants.update(_russian_name_case_variants(raw_name))
    return frozenset(variants)


def _russian_name_case_variants(name: str) -> set[str]:
    variants: set[str] = set()
    if len(name) < 3:
        return variants
    if name.endswith(("ы", "и")):
        stem = name[:-1]
        variants.update({stem, f"{stem}а", f"{stem}ой", f"{stem}ей"})
    if name.endswith("а"):
        stem = name[:-1]
        variants.update({stem, f"{stem}ом", f"{stem}ой", f"{stem}у"})
    return variants


def _requests_degree_field_inference(query: str) -> bool:
    query_tokens = _term_set(query)
    return bool(query_tokens & _DEGREE_FIELD_QUERY_TERMS) and bool(
        query_tokens & _INFERENCE_QUERY_TERMS
    )


def _term_set(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for term in query_terms(text, min_chars=2, max_terms=40):
        terms.update(term.variants)
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            terms.add(token)
    return frozenset(terms)
