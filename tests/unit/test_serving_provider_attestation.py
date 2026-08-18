import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter


def test_embedding_adapter_reverifies_and_disables_redirects() -> None:
    verifier_calls: list[None] = []
    clients: list[object] = []

    class Embeddings:
        async def create(self, **_kwargs: object):
            return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 2.0])])

    class AsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            clients.append(kwargs["http_client"])
            self.embeddings = Embeddings()

        async def close(self) -> None:
            return None

    openai = ModuleType("openai")
    openai.AsyncOpenAI = AsyncOpenAI  # type: ignore[attr-defined]
    adapter = OpenAIEmbeddingAdapter(
        api_key="token", base_url="http://tei.test/v1", model="model", dimensions=2,
        runtime_verifier=lambda: verifier_calls.append(None),
    )
    with patch.dict(sys.modules, {"openai": openai}):
        result = asyncio.run(adapter.embed_texts(("one",)))
    assert result.vectors == ((1.0, 2.0),)
    assert verifier_calls == [None]
    assert len(clients) == 1
    assert clients[0].follow_redirects is False  # type: ignore[attr-defined]


def test_replaced_runtime_is_rejected_before_second_embedding_request() -> None:
    calls = 0

    def verify() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("TEI replaced")

    adapter = OpenAIEmbeddingAdapter(
        api_key="token", base_url="http://tei.test/v1", model="model", dimensions=2,
        runtime_verifier=verify,
    )
    adapter._client = _fake_client  # type: ignore[method-assign]
    first = asyncio.run(adapter.embed_texts(("one",)))
    second = asyncio.run(adapter.embed_texts(("two",)))
    assert first.vectors == ((1.0, 2.0),)
    assert second.vectors == ()
    assert calls == 2


async def _fake_client():
    class Client:
        embeddings = SimpleNamespace(
            create=lambda **_kwargs: _embedding_response()
        )

        async def close(self) -> None:
            return None

    return Client()


async def _embedding_response():
    return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 2.0])])
