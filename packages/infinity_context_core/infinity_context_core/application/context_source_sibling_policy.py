"""Source-sibling admission and companion policies."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import replace

from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_counts,
)
from infinity_context_core.application.context_query_workflow_intent import (
    workflow_commitment_query_variants,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    PRECISE_TURN_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_chunk_candidate_relevance_sufficient,
)
from infinity_context_core.application.context_reported_obligation_attribution import (
    obligation_promotion_exclusion_spans,
)
from infinity_context_core.application.context_source_sibling_contracts import (
    _ObligationEvidenceProjection,
    _SourceGroupSeed,
    _SourceSiblingRank,
)
from infinity_context_core.application.context_source_sibling_evidence_rules import (
    _birdwatching_city_schedule_slot_count,
    _is_activity_duration_source_sibling_strong,
    _is_animal_care_instruction_source_sibling_strong,
    _is_animal_diet_evidence_source_sibling_strong,
    _is_birdwatching_city_schedule_source_sibling_strong,
    _is_book_reading_inventory_source_sibling_strong,
    _is_career_path_source_sibling_strong,
    _is_church_friend_activity_inventory_source_sibling_strong,
    _is_degree_policy_source_sibling_strong,
    _is_direct_source_sibling_answer_evidence,
    _is_frequency_recurrence_source_sibling_strong,
    _is_generic_behavior_source_sibling_strong,
    _is_post_event_activity_source_sibling_strong,
    _is_pottery_type_observation_companion_text,
    _is_pottery_type_source_sibling_scope,
    _is_pottery_type_source_sibling_strong,
    _is_running_reason_source_sibling_strong,
    _is_volunteering_inventory_source_sibling_strong_for_reason,
    _is_volunteering_service_activity_source_sibling_strong_for_reason,
)
from infinity_context_core.application.context_source_sibling_evidence_shared import (
    _is_cause_awareness_source_sibling_strong_for_reason,
    _is_children_preference_source_sibling_strong_for_reason,
    _is_classical_music_preference_source_sibling_strong_for_reason,
    _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason,
    _is_outdoor_preference_source_sibling_strong_for_reason,
    _is_sentimental_reminder_source_sibling_strong_for_reason,
)
from infinity_context_core.application.context_source_sibling_identity import source_turn_marker
from infinity_context_core.application.context_source_sibling_patterns import (
    _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS,
    _COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS,
    _DIALOGUE_MARKER_RE,
    _DIALOGUE_VISUAL_REFERENCE_RE,
    _EVENT_VISUAL_SOURCE_SIBLING_REASONS,
    _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS,
    _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON,
    _MAX_SOURCE_GROUP_SIBLING_ITEMS,
    _MAX_SOURCE_GROUPS,
    _MAX_SOURCE_SIBLING_CANDIDATES,
    _MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS,
    _MAX_SOURCE_SIBLING_GROUPS,
    _SOURCE_SIBLING_CANDIDATES_PER_GROUP,
    _SOURCE_SIBLING_CANDIDATES_PER_ITEM,
    _VISUAL_REFERENT_SIBLING_RE,
    _VISUAL_SOURCE_SIBLING_QUERY_RE,
    _VISUAL_SOURCE_SIBLING_REASONS,
)
from infinity_context_core.domain.entities import MemoryChunk

_OBLIGATION_QUERY_RE = re.compile(
    r"\b(?:needs?|have|has|supposed|expected)\s+to\b|\bmust\b|"
    r"\b(?:left|remaining|outstanding|pending|unfinished)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_OBLIGATION_RE = re.compile(
    r"\b(?:I|we)\s+(?:(?:still|also|just|really)\s+)*"
    r"(?:(?:need|have|am\s+supposed|are\s+supposed|"
    r"am\s+expected|are\s+expected)\s+to|must)\b|"
    r"\b(?:I|we)(?:'ve|\s+have)\s+not\b.{0,120}\b(?:yet|chance)\b",
    re.IGNORECASE | re.DOTALL,
)
_OBLIGATION_ADVICE_RE = re.compile(
    r"\b(?:tips?|advice|recommendations?|consider|remember\s+to|don't\s+forget|"
    r"you\s+(?:can|could|should|might|may|need\s+to)|set\s+reminders?|"
    r"create\s+(?:a|an|your)\s+(?:list|reminder))\b",
    re.IGNORECASE,
)
_NEGATED_OBLIGATION_RE = re.compile(
    r"\b(?:must(?:\s+(?:not|never)|n't)|should(?:\s+(?:not|never)|n't)|"
    r"needs?(?:\s+not|n't)|"
    r"(?:do|does|did)(?:\s+not|n't)\s+(?:need|have)\s+to|"
    r"(?:am|is|are|was|were)\s+not\s+(?:supposed|expected|required)\s+to|"
    r"(?:no\s+longer|never)\s+(?:need|needs|have|has)\s+to)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_QUERY_RE = re.compile(
    r"\b(?:I|me|my|mine|we|our|ours)\b",
    re.IGNORECASE,
)
_THIRD_PERSON_OBLIGATION_RE = re.compile(
    r"\b(?:he|she|they|it|[A-Z][A-Za-z'’-]{1,39}|"
    r"(?:the|this|that)\s+[A-Za-z][A-Za-z'’-]*"
    r"(?:\s+[A-Za-z][A-Za-z'’-]*){0,7})\s+"
    r"(?:(?:still|also|just|really)\s+)*"
    r"(?:(?:needs?|has|is\s+supposed|is\s+expected)\s+to|must)\b",
    re.IGNORECASE,
)
_QUERY_SUBJECT_BEFORE_OBLIGATION_RE = re.compile(
    r"\b(?:does|do|did)\s+"
    r"(?P<subject>(?:(?:the|this|that)\s+)?[A-Za-z][A-Za-z'’-]*"
    r"(?:\s+[A-Za-z][A-Za-z'’-]*){0,7}?)\s+"
    r"(?:(?:still|also|just|really)\s+)*(?:need|needs|have|has)\s+to\b",
    re.IGNORECASE,
)
_QUERY_SUBJECT_AFTER_MODAL_RE = re.compile(
    r"\bmust\s+"
    r"(?P<subject>(?:the\s+)?[A-Za-z][A-Za-z'’-]*"
    r"(?:\s+[A-Za-z][A-Za-z'’-]*){0,7}?)\s+"
    r"(?P<action>[A-Za-z][A-Za-z'’-]*)"
    r"(?=\s+(?:and|or|before|after|by|for|with|to|from|at|on)\b|[?.!;]|$)",
    re.IGNORECASE,
)
_QUERY_DECLARATIVE_SUBJECT_RE = re.compile(
    r"\b(?P<subject>[A-Z][A-Za-z'’-]{1,39}|(?:the|this|that)\s+"
    r"[A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*){0,7})\s+"
    r"(?:(?:still|also|just|really)\s+)*"
    r"(?:(?:needs?|has|is\s+supposed|is\s+expected)\s+to|must)\b",
    re.IGNORECASE,
)
_QUERY_ACTION_TAIL_RE = re.compile(
    r"\b(?:needs?|need|have|has|supposed|expected)\s+to\s+"
    r"(?P<tail>[^?.!;]{1,100})",
    re.IGNORECASE,
)
_QUERY_FIRST_PERSON_MODAL_ACTION_RE = re.compile(
    r"\bmust\s+(?:I|we)\s+(?P<tail>[^?.!;]{1,100})",
    re.IGNORECASE,
)
_OBLIGATION_CLAUSE_BOUNDARY_RE = re.compile(
    r"[.!?;\n]+[\"'”’]?\s*|"
    r"(?:,\s*|:\s*|[—–]\s*|\s+)(?=(?:but|however|yet)\b)|"
    r"(?:,\s*(?:and\s+)?|:\s*|[—–]\s*|\s+and\s+)(?=(?:I|we)\b)|"
    r",\s*(?=(?:and\s+)?you\s+(?:can|could|should|might|may|need\s+to)\b)",
    re.IGNORECASE,
)
_OBLIGATION_SEMANTIC_ROLE_TERMS = frozenset(
    {
        "action",
        "assigned",
        "assignee",
        "amount",
        "commitment",
        "complete",
        "completed",
        "count",
        "deadline",
        "due",
        "errand",
        "expected",
        "few",
        "five",
        "follow",
        "four",
        "have",
        "item",
        "items",
        "left",
        "many",
        "much",
        "multiple",
        "must",
        "need",
        "needs",
        "next",
        "number",
        "one",
        "open",
        "outstanding",
        "owner",
        "pending",
        "promised",
        "remaining",
        "reminder",
        "responsible",
        "several",
        "seven",
        "six",
        "step",
        "still",
        "supposed",
        "task",
        "tasks",
        "todo",
        "total",
        "three",
        "times",
        "ten",
        "two",
        "quantity",
        "eight",
        "nine",
        "zero",
        "unfinished",
        "work",
    }
)
_MAX_OBLIGATION_EVIDENCE_SPANS = 16


def source_sibling_group_limit() -> int:
    return _MAX_SOURCE_SIBLING_GROUPS


def source_sibling_seed_group_limit() -> int:
    """Return the unchanged bound used before final source-group selection."""

    return _MAX_SOURCE_GROUPS


def source_group_admission_rank(
    *,
    group: str,
    original_relevance: QueryRelevance,
    relevance: QueryRelevance,
    answer_evidence: bool,
    related_anchor: bool,
) -> tuple[int | float | str, ...]:
    """Rank a bounded source group by query semantics, independent of seed order."""

    semantic_match = bool(
        original_relevance.distinctive_term_hits
        or original_relevance.phrase_bigram_hits
        or original_relevance.unique_term_hits >= 2
    )
    return (
        0 if semantic_match else 1,
        0 if answer_evidence else 1,
        -original_relevance.distinctive_term_hits,
        -original_relevance.phrase_bigram_hits,
        -original_relevance.unique_term_hits,
        -original_relevance.hit_ratio,
        0 if related_anchor else 1,
        -relevance.distinctive_term_hits,
        -relevance.unique_term_hits,
        -relevance.hit_ratio,
        group,
    )


def select_source_sibling_groups(
    *,
    source_groups: Mapping[str, _SourceGroupSeed],
    rank_by_group: Mapping[str, tuple[int | float | str, ...]],
    limit: int,
) -> dict[str, _SourceGroupSeed]:
    """Admit and reprioritize source groups under the existing hard bound."""

    if limit <= 0:
        return {}
    fallback = (1, 0, 0, 0, 0.0, 1, 1, 0, 0, 0.0)
    ordered = sorted(
        source_groups.items(),
        key=lambda entry: (*rank_by_group.get(entry[0], fallback), entry[0]),
    )[:limit]
    return {
        group: replace(seed, priority=priority) for priority, (group, seed) in enumerate(ordered)
    }


def source_sibling_obligation_evidence_rank(
    *,
    query_text: str,
    relevance: QueryRelevance,
    text: str,
    semantic_query_text: str = "",
) -> int:
    """Prefer direct pending obligations over topical instructions and advice."""

    return project_source_sibling_obligation_evidence(
        query_text=query_text,
        semantic_query_text=semantic_query_text,
        relevance=relevance,
        text=text,
    ).rank


def is_direct_source_sibling_obligation_evidence(
    *,
    query_text: str,
    text: str,
) -> bool:
    """Recognize an explicit query-bounded obligation, not action overlap alone."""

    if not _is_obligation_query(query_text):
        return False
    reported_spans = obligation_promotion_exclusion_spans(text)
    return any(
        not any(
            start < reported_end and reported_start < end
            for reported_start, reported_end in reported_spans
        )
        and _is_query_bounded_direct_obligation_clause(
            query_text=query_text,
            clause=text[start:end],
            context_text=_obligation_scope_text(text=text, start=start, end=end),
        )
        and not _clause_ends_with_question(text=text, end=end)
        for start, end in _obligation_clause_spans(text)
    )


def project_source_sibling_obligation_evidence(
    *,
    query_text: str,
    relevance: QueryRelevance,
    text: str,
    semantic_query_text: str = "",
) -> _ObligationEvidenceProjection:
    """Project aligned obligation clauses while retaining canonical offsets."""

    if not _is_obligation_query(query_text):
        return _ObligationEvidenceProjection(rank=1, text=text)
    # Retrieval expansions may nominate a clause, but only the original query can
    # establish the direct-evidence action, subject, and scope contract.
    reported_spans = obligation_promotion_exclusion_spans(text)
    direct_spans: list[tuple[int, int]] = []
    direct_shape_seen = False
    rejected_shape_seen = False
    advice_seen = False
    for start, end in _obligation_clause_spans(text):
        clause = text[start:end]
        locally_rejected = _NEGATED_OBLIGATION_RE.search(clause) is not None or any(
            start < reported_end and reported_start < end
            for reported_start, reported_end in reported_spans
        )
        if locally_rejected:
            rejected_shape_seen = rejected_shape_seen or _obligation_semantics_align(
                query_text=query_text,
                semantic_query_text=semantic_query_text,
                text=clause,
                context_text=clause,
            )
            continue
        direct_shape = _direct_query_subject_obligation(
            query_text=query_text,
            text=clause,
        ) and _obligation_action_align(query_text=query_text, text=clause)
        direct_shape = direct_shape and not _clause_ends_with_question(
            text=text,
            end=end,
        )
        direct_shape_seen = direct_shape_seen or direct_shape
        advice_seen = advice_seen or _OBLIGATION_ADVICE_RE.search(clause) is not None
        query_bounded = direct_shape and _obligation_semantics_align(
            query_text=query_text,
            semantic_query_text=semantic_query_text,
            text=clause,
            context_text=_obligation_scope_text(text=text, start=start, end=end),
        )
        if query_bounded and len(direct_spans) < _MAX_OBLIGATION_EVIDENCE_SPANS:
            direct_spans.append((start, end))
    if direct_spans:
        focused_text = " ".join(text[start:end].strip() for start, end in direct_spans).strip()
        return _ObligationEvidenceProjection(
            rank=0,
            text=focused_text or text,
            spans=tuple(direct_spans),
        )
    if direct_shape_seen or rejected_shape_seen:
        return _ObligationEvidenceProjection(rank=3, text=text)
    return _ObligationEvidenceProjection(rank=2 if advice_seen else 1, text=text)


def _is_obligation_query(query_text: str) -> bool:
    return bool(
        workflow_commitment_query_variants(query_text) or _OBLIGATION_QUERY_RE.search(query_text)
    )


def _obligation_semantics_align(
    *,
    query_text: str,
    semantic_query_text: str = "",
    text: str,
    context_text: str = "",
) -> bool:
    if not _obligation_action_align(query_text=query_text, text=text):
        return False
    counts = text_variant_counts(text)
    action_terms = _query_obligation_action_terms(query_text)
    scope_terms = _obligation_semantic_terms(
        query_text,
        excluded_terms=(
            *action_terms,
            *_query_obligation_subject_terms(query_text),
        ),
    )
    if not scope_terms or _any_obligation_term_matches(scope_terms, counts):
        return True
    if not _query_has_disjunctive_obligation_actions(query_text):
        return False

    # A compound action alternative keeps the obligation clause query-bounded.
    # Permit its surrounding retrieval context to establish the object/topic
    # scope, including a candidate-specific deterministic query expansion.
    context_counts = text_variant_counts(context_text or text)
    if _any_obligation_term_matches(scope_terms, context_counts):
        return True
    expanded_scope_terms = _obligation_semantic_terms(
        semantic_query_text,
        excluded_terms=(
            *action_terms,
            *_query_obligation_subject_terms(query_text),
        ),
    )
    return bool(
        semantic_query_text
        and semantic_query_text != query_text
        and expanded_scope_terms
        and _any_obligation_term_matches(expanded_scope_terms, context_counts)
    )


def _obligation_action_align(*, query_text: str, text: str) -> bool:
    action_terms = _query_obligation_action_terms(query_text)
    return bool(action_terms) and _any_obligation_term_matches(
        action_terms, text_variant_counts(text)
    )


def _obligation_semantic_terms(
    query_text: str,
    *,
    excluded_terms: tuple[LexicalQueryTerm, ...] = (),
) -> tuple[LexicalQueryTerm, ...]:
    excluded_variants = {variant for term in excluded_terms for variant in term.variants}
    return tuple(
        term
        for term in query_terms(query_text)
        if not set(term.variants).intersection(_OBLIGATION_SEMANTIC_ROLE_TERMS)
        and not set(term.variants).intersection(excluded_variants)
    )


def _any_obligation_term_matches(
    terms: tuple[LexicalQueryTerm, ...],
    counts: Mapping[str, int],
) -> bool:
    return any(query_term_frequency(term, counts) > 0 for term in terms)


def _is_query_bounded_direct_obligation_clause(
    *,
    query_text: str,
    clause: str,
    context_text: str = "",
) -> bool:
    return _direct_query_subject_obligation(
        query_text=query_text,
        text=clause,
    ) and _obligation_semantics_align(
        query_text=query_text,
        text=clause,
        context_text=context_text,
    )


def _obligation_clause_spans(text: str) -> Iterator[tuple[int, int]]:
    cursor = 0
    for match in _OBLIGATION_CLAUSE_BOUNDARY_RE.finditer(text):
        span = _trimmed_clause_span(text=text, start=cursor, end=match.start())
        if span is not None:
            yield span
        cursor = match.end()
    span = _trimmed_clause_span(text=text, start=cursor, end=len(text))
    if span is not None:
        yield span


def _trimmed_clause_span(
    *,
    text: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end > start:
        return start, end
    return None


def _obligation_scope_text(*, text: str, start: int, end: int) -> str:
    scope_start = max((text.rfind(boundary, 0, start) for boundary in ".!?;\n"), default=-1) + 1
    scope_ends = tuple(index for boundary in ".!?;\n" if (index := text.find(boundary, end)) >= 0)
    return text[scope_start : min(scope_ends, default=len(text))]


def _clause_ends_with_question(*, text: str, end: int) -> bool:
    return end < len(text) and text[end] == "?"


def _query_obligation_action_terms(query_text: str) -> tuple[LexicalQueryTerm, ...]:
    action_words = [
        action
        for tail in _query_obligation_action_tails(query_text)
        for action in _action_words_from_tail(tail)
    ]
    unique_words = tuple(dict.fromkeys(word.casefold() for word in action_words))
    return tuple(term for word in unique_words for term in query_terms(word))


def _query_obligation_action_tails(query_text: str) -> tuple[str, ...]:
    query_text = _normalize_name_apostrophes(query_text)
    tails: list[str] = []
    action_match = _QUERY_ACTION_TAIL_RE.search(query_text)
    if action_match is not None:
        tails.append(action_match.group("tail"))
    first_person_modal_match = _QUERY_FIRST_PERSON_MODAL_ACTION_RE.search(query_text)
    if first_person_modal_match is not None:
        tails.append(first_person_modal_match.group("tail"))
    for subject in _query_obligation_subjects(query_text):
        modal_match = re.search(
            rf"\bmust\s+{re.escape(subject)}\s+(?P<tail>[^?.!;]{{1,100}})",
            query_text,
            re.IGNORECASE,
        )
        if modal_match is not None:
            tails.append(modal_match.group("tail"))
    return tuple(tails)


def _query_has_disjunctive_obligation_actions(query_text: str) -> bool:
    return any(
        re.search(r"\bor\b", tail, re.IGNORECASE) is not None
        and len(_action_words_from_tail(tail)) >= 2
        for tail in _query_obligation_action_tails(query_text)
    )


def _action_words_from_tail(tail: str) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", tail)
    if not words or words[0].casefold() == "do":
        return ()
    actions = [words[0]]
    for index, word in enumerate(words[:-1]):
        if word.casefold() in {"and", "or"}:
            actions.append(words[index + 1])
    return tuple(actions)


def _query_obligation_subjects(query_text: str) -> tuple[str, ...]:
    query_text = _normalize_name_apostrophes(query_text)
    if _FIRST_PERSON_QUERY_RE.search(query_text):
        return ()
    subjects: list[str] = []
    for pattern in (
        _QUERY_SUBJECT_BEFORE_OBLIGATION_RE,
        _QUERY_SUBJECT_AFTER_MODAL_RE,
        _QUERY_DECLARATIVE_SUBJECT_RE,
    ):
        for match in pattern.finditer(query_text):
            subject = " ".join(match.group("subject").split())
            if subject.casefold() not in {"what", "when", "which", "who"}:
                subjects.append(subject)
    return tuple(dict.fromkeys(subjects))


def _query_obligation_subject_terms(query_text: str) -> tuple[LexicalQueryTerm, ...]:
    return tuple(
        term for subject in _query_obligation_subjects(query_text) for term in query_terms(subject)
    )


def _direct_query_subject_obligation(*, query_text: str, text: str) -> bool:
    if _NEGATED_OBLIGATION_RE.search(text):
        return False
    if _FIRST_PERSON_QUERY_RE.search(query_text):
        first_person_subjects: list[tuple[str, str]] = []
        if re.search(r"\b(?:I|me|my|mine)\b", query_text, re.IGNORECASE):
            first_person_subjects.append(("I", "my"))
        if re.search(r"\b(?:we|us|our|ours)\b", query_text, re.IGNORECASE):
            first_person_subjects.append(("we", "our"))
        return any(
            _subject_has_clause_local_obligation(
                text=text,
                subject=subject,
                possessor=possessor,
            )
            for subject, possessor in first_person_subjects
        )
    subjects = _query_obligation_subjects(query_text)
    if subjects:
        return any(
            _subject_has_clause_local_obligation(text=text, subject=subject) for subject in subjects
        )
    return bool(
        _FIRST_PERSON_OBLIGATION_RE.search(text) or _THIRD_PERSON_OBLIGATION_RE.search(text)
    )


def _subject_has_clause_local_obligation(
    *,
    text: str,
    subject: str,
    possessor: str | None = None,
) -> bool:
    text = _normalize_name_apostrophes(text)
    subject = _normalize_name_apostrophes(subject)
    possessor = _normalize_name_apostrophes(possessor) if possessor is not None else None
    adverbs = r"(?:(?:still|also|just|really)\s+)*"
    modal = r"(?:(?:needs?|has|is\s+supposed|is\s+expected)\s+to|must)\b"
    if re.search(
        rf"\b{re.escape(subject)}\b\s+{adverbs}{modal}",
        text,
        re.IGNORECASE,
    ):
        return True
    owner = re.escape(possessor or subject) + ("" if possessor else r"(?:'s|’s)")
    return (
        re.search(
            rf"\b{owner}\s+(?:(?:remaining|outstanding|pending)\s+)?"
            r"(?:obligation|task|responsibility|commitment|assignment)\s+"
            r"(?:is|was|remains?)\s+to\b",
            text,
            re.IGNORECASE,
        )
        is not None
    )


def _normalize_name_apostrophes(value: str) -> str:
    return value.replace("’", "'").replace("‘", "'")


def source_sibling_item_limit() -> int:
    return _MAX_SOURCE_GROUP_SIBLING_ITEMS


def source_sibling_candidate_limit(*, max_items: int, source_group_count: int) -> int:
    if max_items <= 0 or source_group_count <= 0:
        return 0
    return min(
        _MAX_SOURCE_SIBLING_CANDIDATES,
        max(
            max_items * _SOURCE_SIBLING_CANDIDATES_PER_ITEM,
            source_group_count * _SOURCE_SIBLING_CANDIDATES_PER_GROUP,
        ),
    )


def source_sibling_max_candidate_limit() -> int:
    return _MAX_SOURCE_SIBLING_CANDIDATES


def source_sibling_companion_extra_item_limit() -> int:
    return _MAX_SOURCE_SIBLING_COMPANION_EXTRA_ITEMS


def is_pottery_type_observation_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    if not str(chunk.source_external_id).endswith(":observation"):
        return False
    return _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    )


def source_sibling_marker_coverage_count(*, expansion_reason: str, text: str) -> int:
    if expansion_reason == "birdwatching_city_schedule_bridge":
        return _birdwatching_city_schedule_slot_count(text)
    if not _is_pottery_type_observation_companion_text(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return 0
    return len(tuple(dict.fromkeys(_DIALOGUE_MARKER_RE.findall(text))))


def is_same_document_answer_companion(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
    text: str,
) -> bool:
    return is_pottery_type_observation_companion(
        chunk=chunk,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_pottery_type_retrieval_scope(*, expansion_reason: str, expansion_query: str) -> bool:
    return _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    )


def is_pottery_type_evidence_text(text: str) -> bool:
    return _is_pottery_type_source_sibling_strong(text)


def source_sibling_companion_extra_slot(*, chunk: MemoryChunk, text: str) -> str:
    if not str(chunk.source_external_id).endswith(":observation"):
        return ""
    markers = tuple(dict.fromkeys(match.group(0) for match in _DIALOGUE_MARKER_RE.finditer(text)))
    if len(markers) < 2:
        return ""
    return f"{chunk.source_external_id}:{markers[0]}:{markers[-1]}"


def source_sibling_relevance_allowed(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if _is_pottery_type_source_sibling_scope(
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
    ) and not _is_pottery_type_source_sibling_strong(text):
        return False
    if expansion_reason == "animal_care_instruction_bridge":
        return _is_animal_care_instruction_source_sibling_strong(text)
    if expansion_reason == "animal_diet_evidence_bridge":
        return _is_animal_diet_evidence_source_sibling_strong(text)
    if expansion_reason in {
        "running_reason_bridge",
        "running_reason_question_bridge",
    } and not _is_running_reason_source_sibling_strong(text):
        return False
    if (
        expansion_reason == "post_event_activity_timing_bridge"
        and not _is_post_event_activity_source_sibling_strong(text)
    ):
        return False
    if expansion_reason == "cause_awareness_event_bridge":
        return _is_cause_awareness_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    if (
        _is_classical_music_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_sentimental_reminder_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_outdoor_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_outdoor_activity_visual_companion_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
        or _is_children_preference_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    ):
        return True
    if expansion_reason == _GENERIC_BEHAVIOR_SOURCE_SIBLING_REASON:
        return _is_generic_behavior_source_sibling_strong(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "degree_policy_inference_bridge":
        return _is_degree_policy_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "career_path_bridge":
        return _is_career_path_source_sibling_strong(text)
    if expansion_reason == "book_reading_list_bridge":
        return _is_book_reading_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason == "church_friend_activity_inventory_bridge":
        return _is_church_friend_activity_inventory_source_sibling_strong(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason in {
        "volunteering_inventory_bridge",
        "volunteering_people_inventory_bridge",
    }:
        return _is_volunteering_inventory_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
            expansion_reason=expansion_reason,
            text=text,
        )
    if expansion_reason in _ACTIVITY_DURATION_SOURCE_SIBLING_REASONS:
        return _is_activity_duration_source_sibling_strong(
            text,
            expansion_query=expansion_query,
        )
    if expansion_reason in _FREQUENCY_RECURRENCE_SOURCE_SIBLING_REASONS:
        return _is_frequency_recurrence_source_sibling_strong(text)
    if _is_book_reading_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_church_friend_activity_inventory_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_volunteering_inventory_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ) or _is_volunteering_service_activity_source_sibling_strong_for_reason(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_birdwatching_city_schedule_source_sibling_strong(
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if _is_direct_source_sibling_answer_evidence(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    ):
        return True
    if aggregation_answer_slot_count(query=expansion_query, text=text) > 0:
        return True
    if _is_count_activity_followup_source_sibling(
        rank=rank,
        expansion_reason=expansion_reason,
        expansion_query=expansion_query,
        text=text,
    ):
        return True
    return is_chunk_candidate_relevance_sufficient(
        query=expansion_query,
        text=text,
        relevance=relevance,
    ) or _is_visual_referent_source_sibling(
        rank=rank,
        relevance=relevance,
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
        text=text,
    )


def is_visual_continuation_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    return (
        rank.group_level_seed
        and rank.turn_delta > 0
        and rank.turn_distance <= 1
        and _is_visual_referent_source_sibling(
            rank=rank,
            relevance=relevance,
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        )
    )


def is_dialogue_visual_reference_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if not rank.group_level_seed:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _DIALOGUE_VISUAL_REFERENCE_RE.search(text) is not None


def is_precise_source_sibling_turn(
    *,
    chunk: MemoryChunk,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in PRECISE_TURN_SOURCE_SIBLING_REASONS
        and source_turn_marker(chunk.source_external_id) is not None
    )


def _is_count_activity_followup_source_sibling(
    *,
    rank: _SourceSiblingRank,
    expansion_reason: str,
    expansion_query: str,
    text: str,
) -> bool:
    if expansion_reason not in _COUNT_ACTIVITY_FOLLOWUP_SOURCE_SIBLING_REASONS:
        return False
    if rank.turn_delta <= 0 or rank.turn_distance > 2:
        return False
    subject = _query_subject_name(expansion_query)
    if not subject:
        return False
    return re.search(rf"\b{re.escape(subject)}\b", text, re.IGNORECASE) is not None


def _query_subject_name(query: str) -> str:
    match = re.match(r"\s*([A-Z][A-Za-z][A-Za-z'-]*)\b", query)
    return match.group(1) if match is not None else ""


def _is_visual_referent_source_sibling(
    *,
    rank: _SourceSiblingRank,
    relevance: QueryRelevance,
    expansion_query: str,
    expansion_reason: str,
    text: str,
) -> bool:
    if not _visual_source_sibling_priority_allowed(
        expansion_query=expansion_query,
        expansion_reason=expansion_reason,
    ):
        return False
    if rank.turn_distance > 2:
        return False
    if relevance.unique_term_hits <= 0 and relevance.distinctive_term_hits <= 0:
        return False
    return _VISUAL_REFERENT_SIBLING_RE.search(text) is not None


def _visual_source_sibling_priority_allowed(
    *,
    expansion_query: str,
    expansion_reason: str,
) -> bool:
    return (
        expansion_reason in _VISUAL_SOURCE_SIBLING_REASONS
        or expansion_reason in _EVENT_VISUAL_SOURCE_SIBLING_REASONS
        or _VISUAL_SOURCE_SIBLING_QUERY_RE.search(expansion_query) is not None
    )
