"""Embedding adapters package."""

from memo_stack_adapters.embeddings.noop_adapter import NoopEmbeddingAdapter
from memo_stack_adapters.embeddings.openai_adapter import OpenAIEmbeddingAdapter

__all__ = ["NoopEmbeddingAdapter", "OpenAIEmbeddingAdapter"]
