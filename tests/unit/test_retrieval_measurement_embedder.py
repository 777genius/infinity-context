"""Prevent an eight-query benchmark from silently embedding just its first query."""

from __future__ import annotations

import asyncio

import pytest

from tests.context_retrieval_test_support import DeterministicBatchEmbeddings


@pytest.mark.parametrize("query_count", [0, 1, 8])
def test_retrieval_measurement_embedder_preserves_input_cardinality(query_count):
    queries = tuple(f"query {index}" for index in range(query_count))
    result = asyncio.run(DeterministicBatchEmbeddings().embed_texts(queries))
    assert result.status.value == "ok"
    assert result.vectors == ((0.1, 0.2, 0.3),) * query_count
