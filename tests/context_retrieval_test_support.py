"""Deterministic retrieval fixtures; never a model-backed quality measurement."""

from __future__ import annotations

from infinity_context_core.ports.adapters import EmbeddingResult, PortStatus

CONTEXT_CHAR_BUDGET = 1024


class DeterministicBatchEmbeddings:
    """Return one three-dimensional fixture vector per input, including batches."""

    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        return EmbeddingResult(
            status=PortStatus.OK,
            vectors=((0.1, 0.2, 0.3),) * len(texts),
        )


def retrieval_context_payload() -> dict[str, str | int]:
    return {
        "space_slug": "recall-reserve",
        "memory_scope_external_ref": "default",
        "query": "deployment coordinator",
        "max_chunks": 1,
        "max_facts": 0,
        "max_evidence_items": 1,
        "token_budget": 512,
    }
