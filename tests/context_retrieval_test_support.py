"""Deterministic retrieval fixtures; never a model-backed quality measurement."""

from __future__ import annotations

from infinity_context_core.ports.adapters import EmbeddingResult, PortStatus


class DeterministicBatchEmbeddings:
    """Return one three-dimensional fixture vector per input, including batches."""

    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        return EmbeddingResult(
            status=PortStatus.OK,
            vectors=((0.1, 0.2, 0.3),) * len(texts),
        )
