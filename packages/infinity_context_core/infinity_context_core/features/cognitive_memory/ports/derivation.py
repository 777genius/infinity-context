"""Narrow provider-neutral cognitive derivation port."""

from __future__ import annotations

from typing import Protocol

from .contracts import CognitiveDerivationDraft, CognitiveDerivationRequest


class CognitiveDerivationPort(Protocol):
    """Derive non-authoritative candidates from canonically hydrated evidence."""

    async def derive(
        self, request: CognitiveDerivationRequest
    ) -> tuple[CognitiveDerivationDraft, ...]: ...
