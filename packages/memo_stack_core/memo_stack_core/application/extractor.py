"""Extractor boundary and validation for auto-memory candidates."""

from __future__ import annotations

from dataclasses import dataclass

from memo_stack_core.application.auto_memory import RuleBasedMemoryClassifier
from memo_stack_core.domain.errors import MemoryValidationError
from memo_stack_core.ports.auto_memory import (
    CandidateOperation,
    MemoryCandidate,
    MemoryClassifierPort,
    MemoryExtractorPort,
    SourceProvenance,
)

MAX_EXTRACTOR_CANDIDATES = 20
MAX_EXTRACTOR_CANDIDATE_CHARS = 1200


@dataclass(frozen=True)
class ExtractorValidationResult:
    candidates: tuple[MemoryCandidate, ...]
    rejected_codes: tuple[str, ...] = ()


class NoopMemoryExtractor(MemoryExtractorPort):
    version = "noop-extractor-v1"
    prompt_version = None
    requires_external_ai = False

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        return ()


class RuleBasedMemoryExtractor(MemoryExtractorPort):
    version = "rule-based-memory-extractor-v1"
    prompt_version = None
    requires_external_ai = False

    def __init__(self, classifier: MemoryClassifierPort | None = None) -> None:
        self._classifier = classifier or RuleBasedMemoryClassifier()

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        return await self._classifier.classify(text=text, source=source)


def validate_extractor_candidates(
    *,
    candidates: tuple[MemoryCandidate, ...],
    source_text: str,
) -> ExtractorValidationResult:
    """Validate untrusted extractor output before resolver/persistence.

    Provider adapters should parse raw JSON before constructing MemoryCandidate,
    but the application still treats every candidate as untrusted.
    """

    if len(candidates) > MAX_EXTRACTOR_CANDIDATES:
        raise MemoryValidationError("extractor_output_too_many_candidates")

    accepted: list[MemoryCandidate] = []
    rejected: list[str] = []
    normalized_source = _normalize_evidence(source_text)
    for candidate in candidates:
        code = _candidate_rejection_code(candidate, normalized_source=normalized_source)
        if code is not None:
            rejected.append(code)
            continue
        accepted.append(candidate)
    return ExtractorValidationResult(
        candidates=tuple(accepted),
        rejected_codes=tuple(rejected),
    )


def _candidate_rejection_code(
    candidate: MemoryCandidate,
    *,
    normalized_source: str,
) -> str | None:
    operation = candidate.operation_hint
    if operation == CandidateOperation.NOOP:
        return None
    if operation in {CandidateOperation.ADD, CandidateOperation.UPDATE} and not candidate.text:
        return "empty_candidate"
    if len(candidate.text) > MAX_EXTRACTOR_CANDIDATE_CHARS:
        return "candidate_text_too_large"
    if operation in {CandidateOperation.UPDATE, CandidateOperation.DELETE}:
        if not candidate.target_fact_id:
            return "target_fact_required"
        if operation == CandidateOperation.UPDATE and candidate.target_fact_version is None:
            return "target_version_required"
    for source_ref in candidate.source_refs:
        quote = source_ref.quote_preview
        if quote and _normalize_evidence(quote) not in normalized_source:
            return "evidence_quote_not_found"
    return None


def _normalize_evidence(value: str) -> str:
    return " ".join(value.casefold().split())
