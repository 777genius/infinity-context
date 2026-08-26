from __future__ import annotations

from types import SimpleNamespace

import pytest
from infinity_context_core.domain.errors import MemoryForbiddenError
from infinity_context_server.api.auth import authorize_resolved_retrieval_scope
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_READ, ActiveServiceToken


def _request(token: ActiveServiceToken | None):
    state = SimpleNamespace()
    if token is not None:
        state.active_service_token = token
    return SimpleNamespace(state=state)


def _token(*, space: str = "space-a", scopes=frozenset({"scope-a"})):
    return ActiveServiceToken(
        token_id="token-a",
        space_id=space,
        memory_scope_ids=scopes,
        permissions=frozenset({MEMORY_PERMISSION_READ}),
    )


def test_exact_canonical_retrieval_scope_is_allowed() -> None:
    authorize_resolved_retrieval_scope(
        _request(_token()), space_id="space-a", memory_scope_id="scope-a"
    )


@pytest.mark.parametrize(
    ("space_id", "memory_scope_id"),
    (("space-b", "scope-a"), ("space-a", "scope-b")),
)
def test_cross_scope_canonical_retrieval_is_denied(space_id: str, memory_scope_id: str) -> None:
    with pytest.raises(MemoryForbiddenError):
        authorize_resolved_retrieval_scope(
            _request(_token()),
            space_id=space_id,
            memory_scope_id=memory_scope_id,
        )


def test_root_service_token_without_database_scope_is_allowed() -> None:
    authorize_resolved_retrieval_scope(
        _request(None), space_id="any-space", memory_scope_id="any-scope"
    )
