"""Provider-neutral policy for one bounded inference-evidence reservation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_SUPPORTED_QUERY_RE = re.compile(
    r"\AWhat might (?P<subject>[A-Z][a-z]{1,30})(?:'s|’s) "
    r"(?P<relation>financial status) be\?\Z"
)
_SEGMENT_SPLIT_RE = re.compile(r"[.!?;]+")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_HOUSEHOLD_TERMS = frozenset({"children", "dependents", "family", "household", "kids"})
_REPORTING_TERMS = frozenset(
    {"explained", "mentioned", "said", "says", "shared", "told", "tells"}
)
_OWNED_HOUSEHOLD_POSSESSIVES = frozenset({"her", "his", "my", "our"})
_HOUSEHOLD_ACTIONS = frozenset({"had", "has", "have", "having", "is", "was", "were"})
_ABUNDANCE_TERMS = frozenset({"abundant", "enough", "plenty", "surplus"})
_NEGATED_TERMS = frozenset(
    {
        "aint",
        "arent",
        "cant",
        "cannot",
        "couldnt",
        "didnt",
        "doesnt",
        "dont",
        "hadnt",
        "hasnt",
        "havent",
        "isnt",
        "lack",
        "mustnt",
        "neednt",
        "never",
        "no",
        "not",
        "shouldnt",
        "wasnt",
        "werent",
        "wont",
        "wouldnt",
    }
)
_CONTRAST_TERMS = frozenset({"but", "whereas", "while"})
_OUTGROUP_TERMS = frozenset({"other", "others"})
_OUTGROUP_NOUNS = frozenset({"children", "dependents", "families", "households", "kids"})
_SCARCITY_TERMS = frozenset({"lack", "lacks", "lacking", "less", "scarce", "scarcity", "without"})
_SCARCITY_MATERIAL_PREFIXES = frozenset({"basic", "material"})
_DIRECT_FINANCIAL_ACTIONS = frozenset(
    {
        "afford",
        "afforded",
        "affords",
        "covers",
        "cover",
        "earned",
        "earns",
        "had",
        "has",
        "made",
        "makes",
        "paid",
        "pays",
        "saved",
        "saves",
    }
)
_DIRECT_STATE_ACTIONS = frozenset({"is", "was"})
_MATERIAL_OBJECT_PREFIXES = frozenset(
    {
        "a",
        "an",
        "ample",
        "adequate",
        "considerable",
        "enough",
        "little",
        "many",
        "much",
        "significant",
        "some",
        "substantial",
        "the",
    }
)
_MATERIAL_TERMS = frozenset(
    {
        "assets",
        "bills",
        "budget",
        "debt",
        "earnings",
        "expenses",
        "financially",
        "finances",
        "income",
        "money",
        "possessions",
        "resources",
        "salary",
        "savings",
        "wealth",
        "wealthy",
    }
)
_FINANCIAL_NOUNS = frozenset(
    {
        "assets",
        "bills",
        "budget",
        "debt",
        "earnings",
        "expenses",
        "finances",
        "income",
        "money",
        "possessions",
        "resources",
        "salary",
        "savings",
        "wealth",
    }
)
_FINANCIALLY_STATE_PREDICATES = frozenset(
    {
        "comfortable",
        "independent",
        "poor",
        "rich",
        "secure",
        "stable",
        "struggling",
    }
)
_OWNED_FINANCIAL_ASSERTION_ACTIONS = frozenset(
    {
        "cover",
        "covered",
        "covers",
        "decline",
        "declined",
        "declines",
        "decrease",
        "decreased",
        "decreases",
        "grow",
        "grew",
        "grows",
        "increase",
        "increased",
        "increases",
        "support",
        "supported",
        "supports",
        "total",
        "totaled",
        "totals",
    }
)
_SAFE_QUERY_REASONS = frozenset(
    {"decomposition_financial_resources_inference", "decomposition_inference_support"}
)


class InferenceReservationPressure(Enum):
    """Typed packer pressures; policy accepts only the character cap."""

    CHARACTER_CAP = "character_cap"
    TOKEN_BUDGET = "token_budget"
    SOURCE_CAP = "source_cap"
    COVERAGE = "coverage"


class InferenceRelation(Enum):
    """Relations supported by the deliberately narrow reservation policy."""

    FINANCIAL_STATUS = "financial_status"


@dataclass(frozen=True, slots=True)
class InferenceQueryPredicate:
    """A parsed, typed inference request rather than a bag of matching terms."""

    subject: str
    relation: InferenceRelation


@dataclass(frozen=True, slots=True)
class InferenceEvidenceCandidate:
    """Provider-agnostic evidence facts needed by the policy."""

    candidate_id: str
    text: str
    query_reason: str
    rank: int
    score: float
    source_backed: bool
    instruction: bool
    conflict_ids: frozenset[str] = frozenset()
    review_only: bool = False


@dataclass(frozen=True, slots=True)
class InferenceEvidenceReservationRequest:
    query: str
    pressure: InferenceReservationPressure
    rejected: InferenceEvidenceCandidate
    selected: tuple[InferenceEvidenceCandidate, ...]
    protected_candidate_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class InferenceEvidenceReservation:
    candidate_id: str
    displaced_candidate_id: str


def reserve_inference_evidence(
    request: InferenceEvidenceReservationRequest,
) -> InferenceEvidenceReservation | None:
    """Return at most one deterministic swap under proven character pressure."""

    if request.pressure is not InferenceReservationPressure.CHARACTER_CAP:
        return None
    predicate = inference_query_predicate(request.query)
    if predicate is None or not _is_relation_evidence(request.rejected, predicate=predicate):
        return None
    displacement = next(
        (
            candidate
            for candidate in sorted(request.selected, key=_displacement_key)
            if candidate.candidate_id not in request.protected_candidate_ids
            and _is_safe_generic_inference(candidate, predicate=predicate)
        ),
        None,
    )
    if displacement is None:
        return None
    return InferenceEvidenceReservation(
        candidate_id=request.rejected.candidate_id,
        displaced_candidate_id=displacement.candidate_id,
    )


def inference_query_predicate(query: str) -> InferenceQueryPredicate | None:
    """Parse only the single reviewed inference-question grammar."""

    match = _SUPPORTED_QUERY_RE.fullmatch(query)
    if match is None:
        return None
    return InferenceQueryPredicate(
        subject=match.group("subject").casefold(),
        relation=InferenceRelation.FINANCIAL_STATUS,
    )


def _is_relation_evidence(
    candidate: InferenceEvidenceCandidate,
    *,
    predicate: InferenceQueryPredicate,
) -> bool:
    return (
        predicate.relation is InferenceRelation.FINANCIAL_STATUS
        and _is_safe_inference_candidate(candidate)
        and any(
            _segment_has_financial_evidence(segment, subject=predicate.subject)
            for segment in _segments(candidate.text)
        )
    )


def _segment_has_financial_evidence(
    tokens: tuple[str, ...],
    *,
    subject: str,
) -> bool:
    household_index = _owned_household_index(tokens, subject=subject)
    return _has_direct_subject_financial_evidence(tokens, subject=subject) or (
        household_index is not None
        and _has_ordered_household_material_contrast(
            tokens,
            household_index=household_index,
        )
    )


def _has_direct_subject_financial_evidence(
    tokens: tuple[str, ...],
    *,
    subject: str,
) -> bool:
    possessive_subject = f"{subject}s"
    for index, token in enumerate(tokens):
        if token == possessive_subject and _has_possessive_subject_financial_evidence(
            tokens,
            start=index + 1,
        ):
            return True
        if token == subject:
            return _has_immediate_subject_financial_evidence(tokens, start=index + 1)
    return False


def _has_possessive_subject_financial_evidence(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> bool:
    """Require a subject-owned financial noun followed by an assertion."""

    financial_end = _owned_financial_term_end(tokens, start=start)
    if financial_end is None or financial_end >= len(tokens):
        return False
    assertion = tokens[financial_end]
    return assertion in _OWNED_FINANCIAL_ASSERTION_ACTIONS or (
        assertion in _DIRECT_STATE_ACTIONS
        and _has_immediate_financial_predicate(tokens, start=financial_end + 1)
    )


def _owned_household_index(
    tokens: tuple[str, ...],
    *,
    subject: str,
) -> int | None:
    possessive_subject = f"{subject}s"
    for index, token in enumerate(tokens):
        if token == possessive_subject and _is_household_at(tokens, index + 1):
            return index + 1
        if token != subject or index + 1 >= len(tokens):
            continue
        if tokens[index + 1] not in _REPORTING_TERMS:
            continue
        owner_index = index + 2
        if owner_index < len(tokens) and tokens[owner_index] == "that":
            owner_index += 1
        if (
            owner_index < len(tokens)
            and tokens[owner_index] in _OWNED_HOUSEHOLD_POSSESSIVES
            and _is_household_at(tokens, owner_index + 1)
        ):
            return owner_index + 1
    return None


def _is_household_at(tokens: tuple[str, ...], index: int) -> bool:
    return index < len(tokens) and tokens[index] in _HOUSEHOLD_TERMS


def _has_immediate_subject_financial_evidence(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> bool:
    if start >= len(tokens):
        return False
    action = tokens[start]
    if action in _DIRECT_FINANCIAL_ACTIONS:
        return _has_immediate_material_object(tokens, start=start + 1)
    return action in _DIRECT_STATE_ACTIONS and _has_immediate_financial_predicate(
        tokens,
        start=start + 1,
    )


def _has_immediate_material_object(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> bool:
    object_index = _skip_material_object_prefixes(tokens, start=start)
    if object_index >= len(tokens):
        return False
    return _is_financial_object_at(tokens, index=object_index)


def _is_financial_object_at(tokens: tuple[str, ...], *, index: int) -> bool:
    if tokens[index] in _FINANCIAL_NOUNS:
        return True
    return (
        tokens[index] == "financial"
        and index + 1 < len(tokens)
        and tokens[index + 1]
        in _FINANCIAL_NOUNS | {"security", "situation", "status"}
    )


def _owned_financial_term_end(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> int | None:
    noun_index = _skip_material_object_prefixes(tokens, start=start)
    if noun_index >= len(tokens):
        return None
    if tokens[noun_index] in _FINANCIAL_NOUNS:
        return noun_index + 1
    if (
        tokens[noun_index] == "financial"
        and noun_index + 1 < len(tokens)
        and tokens[noun_index + 1]
        in _FINANCIAL_NOUNS | {"security", "situation", "status"}
    ):
        return noun_index + 2
    return None


def _skip_material_object_prefixes(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> int:
    index = start
    for _ in range(3):
        if index >= len(tokens) or tokens[index] not in _MATERIAL_OBJECT_PREFIXES:
            break
        index += 1
    return index


def _has_immediate_financial_predicate(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> bool:
    if start >= len(tokens):
        return False
    predicate = tokens[start]
    if predicate == "in":
        return start + 1 < len(tokens) and tokens[start + 1] == "debt"
    return (
        predicate == "financially"
        and start + 1 < len(tokens)
        and tokens[start + 1] in _FINANCIALLY_STATE_PREDICATES
    )


def _has_ordered_household_material_contrast(
    tokens: tuple[str, ...],
    *,
    household_index: int,
) -> bool:
    abundance_index = _household_abundance_index(tokens, household_index=household_index)
    if abundance_index is None:
        return False
    connector_index = next(
        (
            index
            for index in range(abundance_index + 1, len(tokens))
            if tokens[index] in _CONTRAST_TERMS
        ),
        None,
    )
    return (
        connector_index is not None
        and _has_material_household_abundance_complement(
            tokens[abundance_index + 1 : connector_index]
        )
        and _has_outgroup_material_scarcity(tokens[connector_index + 1 :])
    )


def _has_material_household_abundance_complement(tokens: tuple[str, ...]) -> bool:
    """Allow ellipsis, but make an explicit household object materially grounded."""

    if not tokens:
        return True
    complement = tokens[1:] if tokens[:1] == ("of",) else tokens
    return _has_material_indicator(complement)


def _household_abundance_index(
    tokens: tuple[str, ...],
    *,
    household_index: int,
) -> int | None:
    for action_index in range(household_index + 1, min(len(tokens), household_index + 4)):
        if tokens[action_index] not in _HOUSEHOLD_ACTIONS:
            continue
        for index in range(action_index + 1, min(len(tokens), action_index + 5)):
            if _is_abundance_indicator(tokens, index=index) and not any(
                token in _NEGATED_TERMS
                for token in tokens[household_index + 1 : index + 1]
            ):
                return index
    return None


def _is_abundance_indicator(tokens: tuple[str, ...], *, index: int) -> bool:
    token = tokens[index]
    if token in _ABUNDANCE_TERMS:
        return True
    if token == "lot" and index > 0 and tokens[index - 1] == "a":
        return True
    return token == "met" and any(
        tokens[previous] == "needs"
        for previous in range(max(0, index - 2), index)
    )


def _has_outgroup_material_scarcity(tokens: tuple[str, ...]) -> bool:
    start = 1 if tokens[:1] == ("the",) else 0
    if start >= len(tokens) or tokens[start] not in _OUTGROUP_TERMS:
        return False
    start += 1
    if start < len(tokens) and tokens[start] in _OUTGROUP_NOUNS:
        start += 1
    tail = tokens[start:]
    if not tail:
        return False
    if tail[0] in _SCARCITY_TERMS:
        return _has_immediate_scarcity_material_object(tail, start=1)
    return (
        tail[:2] in {("cant", "afford"), ("cannot", "afford"), ("couldnt", "afford")}
        and _has_immediate_scarcity_material_object(tail, start=2)
    )


def _has_immediate_scarcity_material_object(
    tokens: tuple[str, ...],
    *,
    start: int,
) -> bool:
    object_index = _skip_material_object_prefixes(tokens, start=start)
    if object_index >= len(tokens):
        return False
    if tokens[object_index] in _SCARCITY_MATERIAL_PREFIXES:
        object_index += 1
        return object_index < len(tokens) and (
            tokens[object_index] == "needs"
            or _is_financial_object_at(tokens, index=object_index)
        )
    return _is_financial_object_at(tokens, index=object_index)


def _has_material_indicator(tokens: tuple[str, ...]) -> bool:
    return any(token in _MATERIAL_TERMS for token in tokens) or any(
        tokens[index] == "financial"
        and index + 1 < len(tokens)
        and tokens[index + 1] in {"security", "status", "situation"}
        for index in range(len(tokens))
    ) or any(
        tokens[index] in {"basic", "material", "standard"}
        and index + 1 < len(tokens)
        and tokens[index + 1] in {"living", "needs"}
        for index in range(len(tokens))
    )


def _is_safe_generic_inference(
    candidate: InferenceEvidenceCandidate,
    *,
    predicate: InferenceQueryPredicate,
) -> bool:
    return _is_safe_inference_candidate(candidate) and not _is_relation_evidence(
        candidate,
        predicate=predicate,
    )


def _is_safe_inference_candidate(candidate: InferenceEvidenceCandidate) -> bool:
    return (
        candidate.query_reason in _SAFE_QUERY_REASONS
        and candidate.source_backed
        and not candidate.instruction
        and not candidate.conflict_ids
        and not candidate.review_only
    )


def _segments(text: str) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tokens
        for segment in _SEGMENT_SPLIT_RE.split(text)
        if (tokens := _tokens(segment))
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).casefold().replace("'", "").replace("’", "")
        for match in _TOKEN_RE.finditer(text)
    )


def _displacement_key(candidate: InferenceEvidenceCandidate) -> tuple[float, int, str]:
    return candidate.score, -candidate.rank, candidate.candidate_id
