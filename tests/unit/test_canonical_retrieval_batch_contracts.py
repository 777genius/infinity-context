"""Core contracts for ordered canonical retrieval batching."""

import inspect
from dataclasses import FrozenInstanceError

import pytest
from infinity_context_core.ports.repositories import (
    ActiveAnchorKey,
    AnchorRepositoryPort,
    AnchorScopeQuery,
    ChunkKeywordSearch,
    ChunkRepositoryPort,
)


def test_batch_request_values_are_immutable_and_domain_shaped() -> None:
    request = ChunkKeywordSearch("space", ("scope",), "thread", "query", 5)

    with pytest.raises(FrozenInstanceError):
        request.limit = 6  # type: ignore[misc]

    source = inspect.getsource(inspect.getmodule(ChunkKeywordSearch))
    for forbidden in ("sqlalchemy", "AsyncSession", "dialect", "bind_limit"):
        assert forbidden not in source


def test_ports_expose_ordered_domain_requests_without_changing_scalar_calls() -> None:
    chunk_parameters = inspect.signature(ChunkRepositoryPort.keyword_search_many).parameters
    scope_parameters = inspect.signature(AnchorRepositoryPort.list_for_scopes).parameters
    key_parameters = inspect.signature(AnchorRepositoryPort.find_active_by_keys).parameters
    id_parameters = inspect.signature(AnchorRepositoryPort.get_by_ids).parameters

    assert chunk_parameters["requests"].annotation
    assert scope_parameters["requests"].annotation
    assert key_parameters["requests"].annotation
    assert id_parameters["anchor_ids"].annotation
    assert "requests" not in inspect.signature(ChunkRepositoryPort.keyword_search).parameters
    assert "requests" not in inspect.signature(AnchorRepositoryPort.list_for_scope).parameters

    assert AnchorScopeQuery("space", "scope", None, None, 10).memory_scope_id == "scope"
    assert ActiveAnchorKey("space", "scope", "person", "ada").normalized_key == "ada"
