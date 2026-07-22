"""Provider-neutral policy for one bounded inference-evidence reservation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_SUPPORTED_QUERY_RE = re.compile(
    r"\AWhat might (?P<subject>[A-Z][a-z]{1,30})(?:'s|’s) "
    r"(?P<relation>financial status) be\?\Z"
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_FINANCIAL_EVIDENCE_WORDS = frozenset(
    {
        "afford",
        "affordable",
        "budget",
        "debt",
        "finances",
        "financial",
        "income",
        "money",
        "poor",
        "rich",
        "salary",
        "savings",
        "struggling",
        "wealthy",
    }
)
_UNRELATED_EVIDENCE_WORDS = frozenset(
    {"abundance", "abundant", "homework", "midnight", "schedule", "time", "timer"}
)
_PURCHASE_COST_WORDS = frozenset(
    {"buy", "bought", "cost", "costs", "expensive", "price", "purchase", "purchased"}
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
    tokens = _tokens(candidate.text)
    return (
        predicate.relation is InferenceRelation.FINANCIAL_STATUS
        and _is_safe_inference_candidate(candidate)
        and predicate.subject in tokens
        and bool(tokens.intersection(_FINANCIAL_EVIDENCE_WORDS))
        and not tokens.intersection(_UNRELATED_EVIDENCE_WORDS)
        and not tokens.intersection(_PURCHASE_COST_WORDS)
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
        candidate.query_reason == "decomposition_inference_support"
        and candidate.source_backed
        and not candidate.instruction
        and not candidate.conflict_ids
        and not candidate.review_only
    )


def _tokens(text: str) -> frozenset[str]:
    return frozenset(match.group(0).casefold().strip("'-") for match in _TOKEN_RE.finditer(text))


def _displacement_key(candidate: InferenceEvidenceCandidate) -> tuple[float, int, str]:
    return candidate.score, -candidate.rank, candidate.candidate_id
