"""Optional OpenAI embeddings adapter."""

from __future__ import annotations

import inspect

from memo_stack_core.ports.adapters import AdapterCapabilities, EmbeddingResult, PortStatus


class OpenAIEmbeddingAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        dimensions: int,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions

    async def capabilities(self) -> AdapterCapabilities:
        if not self._api_key:
            return self._disabled("missing_api_key")
        client = None
        try:
            client = await self._client()
        except Exception:
            return self._disabled("openai_sdk_missing")
        finally:
            await _close_client(client)
        return AdapterCapabilities(
            name="embeddings",
            enabled=True,
            healthy=True,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
        )

    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(status=PortStatus.OK, vectors=(), model=self._model)
        if not self._api_key:
            return EmbeddingResult.degraded("embeddings.missing_api_key", retryable=False)
        client = None
        try:
            client = await self._client()
            response = await client.embeddings.create(
                model=self._model,
                input=list(texts),
                dimensions=self._dimensions,
            )
            vectors = tuple(
                tuple(float(value) for value in item.embedding) for item in response.data
            )
            return EmbeddingResult(
                status=PortStatus.OK,
                vectors=vectors,
                model=self._model,
                dimensions=self._dimensions,
            )
        except Exception:
            return EmbeddingResult.degraded("embeddings.provider_error", retryable=True)
        finally:
            await _close_client(client)

    async def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self._api_key)

    def _disabled(self, reason: str) -> AdapterCapabilities:
        return AdapterCapabilities(
            name="embeddings",
            enabled=False,
            healthy=False,
            supports_upsert=False,
            supports_delete=False,
            supports_search=False,
            supports_filters=False,
            degraded_reason=reason,
        )


async def _close_client(client: object | None) -> None:
    if client is None:
        return
    for method_name in ("aclose", "close"):
        close = getattr(client, method_name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
