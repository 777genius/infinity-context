"""Build cognitive candidates through the public application boundary."""

from __future__ import annotations

import asyncio

from infinity_context_core.features.cognitive_memory.public import (
    CanonicalEvidenceIdentity,
    CognitiveCandidate,
    CognitiveDerivationDraft,
    CognitiveDerivationRequest,
    CognitiveDerivationSource,
    CognitiveEvidenceRef,
    CognitiveKind,
    CognitiveProjectionVersion,
    CognitiveScope,
    ProviderCognitiveDerivationUseCase,
)


class _SingleDraftAdapter:
    def __init__(self, draft: CognitiveDerivationDraft) -> None:
        self._draft = draft

    async def derive(
        self,
        request: CognitiveDerivationRequest,
    ) -> tuple[CognitiveDerivationDraft, ...]:
        del request
        return (self._draft,)


def create_cognitive_candidate(*, version: int, content: str) -> CognitiveCandidate:
    scope = CognitiveScope("space-1", "scope-1")
    identity = CanonicalEvidenceIdentity("fact", "fact-1", version, scope)
    reference = CognitiveEvidenceRef(identity, f"fact:fact-1@{version}")
    request = CognitiveDerivationRequest(
        scope=scope,
        sources=(CognitiveDerivationSource(identity, reference, content),),
        projection_version=CognitiveProjectionVersion("observation-v1"),
    )
    adapter = _SingleDraftAdapter(
        CognitiveDerivationDraft(
            kind=CognitiveKind.OBSERVATION,
            content=content,
            evidence_refs=(reference,),
            confidence=0.9,
        )
    )
    return asyncio.run(ProviderCognitiveDerivationUseCase(adapter).derive(request))[0]


__all__ = ("create_cognitive_candidate",)
