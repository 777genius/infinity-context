"""Composition for the embedding provider boundary."""

from infinity_context_adapters.noop import NoopEmbeddingAdapter
from infinity_context_core.ports.adapters import MemoryAdapterPort

from infinity_context_server.config import Settings
from infinity_context_server.serving_profile import VerifiedServingProfile


def build_embedding_adapter(
    settings: Settings, profile: VerifiedServingProfile
) -> MemoryAdapterPort:
    if not settings.embeddings_enabled:
        return NoopEmbeddingAdapter(name="embeddings")
    if settings.embeddings_provider == "openai":
        from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter

        return OpenAIEmbeddingAdapter(
            api_key=settings.openai_api_key,
            base_url=profile.inference_base_url,
            model=settings.embeddings_model,
            dimensions=settings.embeddings_dimensions,
            runtime_session_factory=(
                profile.runtime_session if profile.runtime_probe is not None else None
            ),
        )
    return NoopEmbeddingAdapter(name="embeddings")
