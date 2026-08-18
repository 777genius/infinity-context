import asyncio
import math
import sys
from contextlib import asynccontextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from infinity_context_adapters.embeddings import OpenAIEmbeddingAdapter
from infinity_context_adapters.qdrant import QdrantVectorMemoryAdapter
from infinity_context_server.api.v1.capabilities import _public_embedding_profile


def test_embedding_adapter_reverifies_and_disables_redirects() -> None:
    verifier_calls: list[None] = []
    clients: list[object] = []

    class Embeddings:
        async def create(self, **_kwargs: object):
            return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0, 2.0])])

    class AsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            clients.append(kwargs["http_client"])
            self.embeddings = Embeddings()

        async def close(self) -> None:
            return None

    openai = ModuleType("openai")
    openai.AsyncOpenAI = AsyncOpenAI  # type: ignore[attr-defined]
    adapter = OpenAIEmbeddingAdapter(
        api_key="token",
        base_url="http://tei.test/v1",
        model="model",
        dimensions=2,
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
        api_key="token",
        base_url="http://tei.test/v1",
        model="model",
        dimensions=2,
        runtime_verifier=verify,
    )
    adapter._client = _fake_client  # type: ignore[method-assign]
    first = asyncio.run(adapter.embed_texts(("one",)))
    second = asyncio.run(adapter.embed_texts(("two",)))
    assert first.vectors == ((1.0, 2.0),)
    assert second.vectors == ()
    assert calls == 2


def test_verified_session_is_reused_for_probe_and_embedding() -> None:
    assertions: list[None] = []

    class Session:
        http_client = object()
        inference_base_url = "http://192.0.2.10/v1"

        def assert_single_connection(self) -> None:
            assertions.append(None)

    @asynccontextmanager
    async def session_factory():
        yield Session()

    adapter = OpenAIEmbeddingAdapter(
        api_key="token",
        base_url="http://tei.test/v1",
        model="model",
        dimensions=2,
        runtime_session_factory=session_factory,
    )
    adapter._runtime_client = lambda _session: _fake_client()  # type: ignore[method-assign]
    result = asyncio.run(adapter.embed_texts(("one",)))
    assert result.vectors == ((1.0, 2.0),)
    assert assertions == [None]


def test_invalid_embedding_shapes_fail_closed() -> None:
    responses = (
        [],
        [SimpleNamespace(index=1, embedding=[1.0, 2.0])],
        [SimpleNamespace(index=0, embedding=[1.0])],
        [SimpleNamespace(index=0, embedding=[math.nan, 2.0])],
    )
    for data in responses:
        adapter = OpenAIEmbeddingAdapter(
            api_key="token",
            model="model",
            dimensions=2,
        )

        async def client_factory(data=data):
            class Client:
                embeddings = SimpleNamespace(create=lambda **_kwargs: response())

                async def close(self) -> None:
                    return None

            async def response():
                return SimpleNamespace(data=data)

            return Client()

        adapter._client = client_factory  # type: ignore[method-assign]
        result = asyncio.run(adapter.embed_texts(("one",)))
        assert result.vectors == ()


def test_qdrant_wrong_distance_is_not_published_as_healthy() -> None:
    class Client:
        async def collection_exists(self, _name: str) -> bool:
            return True

        async def get_collection(self, *, collection_name: str) -> object:
            assert collection_name == "chunks"
            vectors = SimpleNamespace(size=3, distance="Dot")
            return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))

        async def close(self) -> None:
            return None

    async def client_factory():
        return Client(), SimpleNamespace()

    adapter = QdrantVectorMemoryAdapter(
        url="http://qdrant.test",
        collection_name="chunks",
        vector_size=3,
    )
    adapter._client = client_factory  # type: ignore[method-assign]
    capabilities = asyncio.run(adapter.capabilities())
    assert capabilities.healthy is False
    assert capabilities.degraded_reason == "qdrant.distance_mismatch"
    container = SimpleNamespace(
        settings=SimpleNamespace(qdrant_enabled=True),
        serving_profile=SimpleNamespace(
            embedding_profile_id="dense-v1",
            embedding_profile_digest_sha256="sha256:" + "a" * 64,
        ),
    )
    assert _public_embedding_profile(
        container,
        SimpleNamespace(adapters=(capabilities,)),
    ) == (None, None)


async def _fake_client():
    class Client:
        embeddings = SimpleNamespace(create=lambda **_kwargs: _embedding_response())

        async def close(self) -> None:
            return None

    return Client()


async def _embedding_response():
    return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0, 2.0])])
