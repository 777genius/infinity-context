"""Optional OpenAI embeddings adapter."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from infinity_context_core.ports.adapters import AdapterCapabilities, EmbeddingResult, PortStatus

from infinity_context_adapters.provider_errors import classify_provider_exception


class VerifiedRuntimeSession(Protocol):
    http_client: object
    inference_base_url: str

    def assert_single_connection(self) -> None: ...


class OpenAIEmbeddingAdapter:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None = None,
        model: str,
        dimensions: int,
        runtime_verifier: Callable[[], None] | None = None,
        runtime_session_factory: (
            Callable[[], AbstractAsyncContextManager[VerifiedRuntimeSession]] | None
        ) = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._dimensions = dimensions
        self._runtime_verifier = runtime_verifier
        self._runtime_session_factory = runtime_session_factory

    async def capabilities(self) -> AdapterCapabilities:
        if not self._api_key:
            return self._disabled("missing_api_key")
        client = None
        try:
            if self._runtime_session_factory is not None:
                async with self._runtime_session_factory() as session:
                    client = await self._runtime_client(session)
                return self._healthy()
            if self._runtime_verifier is not None:
                await asyncio.to_thread(self._runtime_verifier)
            client = await self._client()
        except Exception:
            return self._disabled("openai_sdk_missing")
        finally:
            await _close_client(client)
        return self._healthy()

    def _healthy(self) -> AdapterCapabilities:
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
            if self._runtime_session_factory is not None:
                async with self._runtime_session_factory() as session:
                    client = await self._runtime_client(session)
                    response = await self._request(client, texts)
                    session.assert_single_connection()
                    return self._validated_result(response, texts)
            if self._runtime_verifier is not None:
                await asyncio.to_thread(self._runtime_verifier)
            client = await self._client()
            response = await self._request(client, texts)
            return self._validated_result(response, texts)
        except Exception as exc:
            code, retryable = classify_provider_exception(
                exc,
                prefix="embeddings",
                default_code="embeddings.provider_error",
            )
            return EmbeddingResult.degraded(code, retryable=retryable)
        finally:
            await _close_client(client)

    async def _client(self):
        import httpx
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            http_client=httpx.AsyncClient(follow_redirects=False),
        )

    async def _runtime_client(self, session: VerifiedRuntimeSession):
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._api_key,
            base_url=session.inference_base_url,
            http_client=session.http_client,
        )

    async def _request(self, client: object, texts: tuple[str, ...]):
        return await client.embeddings.create(
            model=self._model,
            input=list(texts),
            dimensions=self._dimensions,
        )

    def _validated_result(self, response: object, texts: tuple[str, ...]) -> EmbeddingResult:
        data = tuple(response.data)
        if len(data) != len(texts):
            raise RuntimeError("embedding response cardinality mismatch")
        vectors: list[tuple[float, ...]] = []
        for expected_index, item in enumerate(data):
            if getattr(item, "index", None) != expected_index:
                raise RuntimeError("embedding response index mismatch")
            vector = tuple(float(value) for value in item.embedding)
            if len(vector) != self._dimensions or not all(map(math.isfinite, vector)):
                raise RuntimeError("embedding response vector is invalid")
            vectors.append(vector)
        return EmbeddingResult(
            status=PortStatus.OK,
            vectors=tuple(vectors),
            model=self._model,
            dimensions=self._dimensions,
        )

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
