"""Locked identity and candidate trust invariants."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from ..domain.candidate import _create_trusted_cognitive_candidate
from ..public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveCandidateIdentity,
    CognitiveDerivationOrigin,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveMemoryInvariantError,
    CognitiveProjectionVersion,
    CognitiveScope,
)


def _scope() -> CognitiveScope:
    return CognitiveScope("space-1", "scope-1", "thread-1")


def _evidence(evidence_id: str, version: int = 1) -> CanonicalEvidenceIdentity:
    return CanonicalEvidenceIdentity("fact", evidence_id, version, _scope())


def _candidate(
    *,
    kind: CognitiveKind = CognitiveKind.OBSERVATION,
    confidence: float = 0.8,
    version: str = "cognitive-v1",
    origin: CognitiveDerivationOrigin = CognitiveDerivationOrigin.SOURCE,
    content: str = "The deployment needs a review gate.",
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> CognitiveCandidate:
    evidence = _evidence("fact-1")
    return _create_trusted_cognitive_candidate(
        scope=_scope(),
        kind=kind,
        derivation_origin=origin,
        content=content,
        projection_version=CognitiveProjectionVersion(version),
        evidence_refs=(CognitiveEvidenceRef(evidence, "fact:fact-1@1"),),
        confidence=confidence,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def test_candidate_identity_is_order_independent_and_provider_neutral() -> None:
    evidence_a = _evidence("a")
    evidence_b = _evidence("b")
    arguments = {
        "scope": _scope(),
        "kind": CognitiveKind.LESSON.value,
        "content_hash": "sha256:content",
        "projection_version": CognitiveProjectionVersion("v1"),
    }

    forward = CognitiveCandidateIdentity.derive(
        evidence_identities=(evidence_a, evidence_b), **arguments
    )
    reverse = CognitiveCandidateIdentity.derive(
        evidence_identities=(evidence_b, evidence_a), **arguments
    )

    assert forward == reverse
    assert "provider" not in {field.name for field in fields(CognitiveCandidateIdentity)}
    assert "provider" not in {field.name for field in fields(CognitiveCandidate)}


def test_projection_semantic_version_changes_candidate_identity() -> None:
    assert _candidate(version="schema-v1").identity != _candidate(version="schema-v2").identity


@pytest.mark.parametrize("confidence", (-0.01, 1.01, True))
def test_confidence_is_bounded_and_never_grants_authority(confidence: float) -> None:
    with pytest.raises(CognitiveMemoryInvariantError):
        _candidate(confidence=confidence)

    high_confidence = _candidate(confidence=1.0)
    assert high_confidence.confidence == 1.0
    assert high_confidence.is_authoritative is False


def test_candidate_requires_cited_exact_canonical_evidence() -> None:
    with pytest.raises(CognitiveMemoryInvariantError, match="requires canonical evidence"):
        _create_trusted_cognitive_candidate(
            scope=_scope(),
            kind=CognitiveKind.EXPERIENCE,
            derivation_origin=CognitiveDerivationOrigin.SOURCE,
            content="Uncited synthesis",
            projection_version=CognitiveProjectionVersion("v1"),
            evidence_refs=(),
            confidence=0.2,
        )


def test_candidate_rejects_cross_scope_evidence() -> None:
    other_scope = CognitiveScope("space-2", "scope-2")
    evidence = CanonicalEvidenceIdentity("fact", "fact-1", 1, other_scope)

    with pytest.raises(CognitiveMemoryInvariantError, match="share candidate scope"):
        _create_trusted_cognitive_candidate(
            scope=_scope(),
            kind=CognitiveKind.OBSERVATION,
            derivation_origin=CognitiveDerivationOrigin.SOURCE,
            content="Cross-scope synthesis",
            projection_version=CognitiveProjectionVersion("v1"),
            evidence_refs=(CognitiveEvidenceRef(evidence, "fact:fact-1@1"),),
            confidence=0.5,
        )


def test_candidate_rejects_duplicate_exact_source_identities() -> None:
    evidence = _evidence("fact-1")
    reference = CognitiveEvidenceRef(evidence, "fact:fact-1@1")

    with pytest.raises(CognitiveMemoryInvariantError, match="duplicate canonical evidence"):
        _create_trusted_cognitive_candidate(
            scope=_scope(),
            kind=CognitiveKind.EXPERIENCE,
            derivation_origin=CognitiveDerivationOrigin.SOURCE,
            content="Duplicated evidence",
            projection_version=CognitiveProjectionVersion("v1"),
            evidence_refs=(reference, reference),
            confidence=0.5,
        )


@pytest.mark.parametrize("version", (True, 1.0, "1"))
def test_canonical_evidence_version_requires_exact_integer(version: object) -> None:
    with pytest.raises(CognitiveMemoryInvariantError, match="version must be positive"):
        CanonicalEvidenceIdentity("fact", "fact-1", version, _scope())  # type: ignore[arg-type]


def test_candidate_content_is_normalized_before_hashing_and_storage() -> None:
    padded = _candidate(content="  Normalized cognition.\n")
    normalized = _candidate(content="Normalized cognition.")

    assert padded.content == "Normalized cognition."
    assert padded.content_hash == normalized.content_hash
    assert padded.identity == normalized.identity


def test_candidate_requires_timezone_aware_temporal_bounds() -> None:
    with pytest.raises(CognitiveMemoryInvariantError, match="valid_from must be timezone-aware"):
        _candidate(valid_from=datetime(2026, 1, 1))
    with pytest.raises(CognitiveMemoryInvariantError, match="valid_to must be timezone-aware"):
        _candidate(valid_from=datetime(2026, 1, 1, tzinfo=UTC), valid_to=datetime(2026, 1, 2))


def test_candidate_rejects_reversed_aware_temporal_bounds_with_domain_error() -> None:
    start = datetime(2026, 1, 2, tzinfo=UTC)

    with pytest.raises(CognitiveMemoryInvariantError, match="valid_to must not precede"):
        _candidate(valid_from=start, valid_to=start - timedelta(days=1))
