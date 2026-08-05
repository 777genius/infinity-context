"""Trusted orchestration for untrusted cognitive derivation adapters."""

from __future__ import annotations

from ..domain import (
    CognitiveCandidate,
    CognitiveDerivationOrigin,
    CognitiveMemoryInvariantError,
)
from ..domain.candidate import _create_trusted_cognitive_candidate
from ..ports import CognitiveDerivationPort, CognitiveDerivationRequest


class ProviderCognitiveDerivationUseCase:
    """Validate provider drafts and stamp immutable provider provenance."""

    def __init__(self, derivation: CognitiveDerivationPort) -> None:
        self._derivation = derivation

    async def derive(self, request: CognitiveDerivationRequest) -> tuple[CognitiveCandidate, ...]:
        drafts = await self._derivation.derive(request)
        request_identities = {source.identity for source in request.sources}
        candidates: list[CognitiveCandidate] = []
        for draft in drafts:
            draft_identities = {reference.identity for reference in draft.evidence_refs}
            if not draft_identities or not draft_identities <= request_identities:
                raise CognitiveMemoryInvariantError(
                    "provider draft evidence must be a non-empty subset of request evidence"
                )
            candidates.append(
                _create_trusted_cognitive_candidate(
                    scope=request.scope,
                    kind=draft.kind,
                    derivation_origin=CognitiveDerivationOrigin.PROVIDER,
                    content=draft.content,
                    projection_version=request.projection_version,
                    evidence_refs=draft.evidence_refs,
                    confidence=draft.confidence,
                    valid_from=draft.valid_from,
                    valid_to=draft.valid_to,
                )
            )
        return tuple(candidates)
